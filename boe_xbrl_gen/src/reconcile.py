"""Reconcile the Arelle-derived dictionary model (built from the zip) against the DPM
dictionary **Excel** workbook the user optionally uploads.

The zip is authoritative for *what exists* and gives most datatypes exactly; the DPM Excel
adds the precise subtype for the numerics the schema can't disambiguate (PERCENTAGE / DECIMAL
/ INTEGER — flagged `needs_refine` by `taxonomy_model`) plus DPM-only metadata (referenced
domain, usable/default member flags, etc.). This module reports the differences and produces
a merged model (same `dpm_model.json` shape, so `generate.py`/`solve.py` are unaffected).

Merge policy (UI-overridable later):
  * existence  -> SCHEMA authoritative (a metric absent from the taxonomy can't appear in a
                  valid instance, so it is not merged in; only reported).
  * datatype   -> EXCEL only refines the ambiguous numerics (`needs_refine`); otherwise the
                  schema's real XBRL type wins. Every disagreement is still reported so the
                  user can flip it.
  * metadata   -> EXCEL fills fields the schema model lacks (ref_domain_*, usable/default…).
  * label      -> schema label kept; Excel fills it only when the schema label is empty.
"""
from __future__ import annotations

import re
from pathlib import Path


# ----------------------------------------------------------------- workbook sniffing
_TABLE_CODE_RE = re.compile(r"^[A-Z]{1,3}\d{2,3}(\.\d{2})+$")


def sniff_workbook(path: str) -> str:
    """Classify an uploaded .xlsx: 'dpm_dictionary' | 'annotated_templates' | 'unknown'.

    Lets the studio accept either workbook: a DPM dictionary reconciles now; an Annotated
    Templates workbook is stashed for the Phase 1b per-table view.
    """
    import openpyxl
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return "unknown"
    sheets = set(wb.sheetnames)
    wb.close()
    if {"Metrics", "Dimensions", "Domains"} <= sheets:
        return "dpm_dictionary"
    if any(_TABLE_CODE_RE.match(s) for s in sheets):
        return "annotated_templates"
    return "unknown"


# --------------------------------------------------------------------- diff helpers
def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).casefold()


def _diff_keyed(schema: dict, excel: dict, *, compare_datatype: bool) -> dict:
    """Diff two code->entry dicts (metrics or dimensions)."""
    s_keys, e_keys = set(schema), set(excel)
    only_schema = sorted(s_keys - e_keys)
    only_excel = sorted(e_keys - s_keys)
    dtype_mismatch, label_diff = [], []
    for code in sorted(s_keys & e_keys):
        s, e = schema[code], excel[code]
        if compare_datatype:
            sd, ed = (s.get("datatype") or ""), (e.get("datatype") or "")
            if sd != ed:
                dtype_mismatch.append({"code": code, "schema": sd, "excel": ed,
                                       "label": s.get("label") or e.get("label"),
                                       "needs_refine": bool(s.get("needs_refine"))})
        if _norm(s.get("label")) != _norm(e.get("label")):
            label_diff.append({"code": code, "schema": s.get("label"), "excel": e.get("label")})
    return {"only_in_schema": only_schema, "only_in_excel": only_excel,
            "datatype_mismatch": dtype_mismatch, "label_diff": label_diff}


def _flatten_members(model: dict) -> dict:
    """members{prefix:[...]} -> {'prefix:code': entry} (exact qname key)."""
    out = {}
    for prefix, mems in model.get("members", {}).items():
        for m in mems:
            out[f"{prefix}:{m['code']}"] = m
    return out


def _member_norm_key(prefix: str, code: str) -> str:
    """Domain+code identity, ignoring the owner re-declaration.

    BoE redeclares EBA-domain members under a `boe_eba_XX` namespace in addition to the
    plain `eba_XX` one; both are the same logical member. The DPM Excel lists them once
    under the `eba_XX` sheet. Keying on the trailing domain token (`AP`) + member code
    (`x10003`) makes the two sources line up.
    """
    return f"{prefix.split('_')[-1].upper()}:{code}"


def _member_norm_index(model: dict) -> tuple[dict, dict]:
    """Return (normkey -> representative member, normkey -> set(prefixes))."""
    rep, variants = {}, {}
    for prefix, mems in model.get("members", {}).items():
        for m in mems:
            k = _member_norm_key(prefix, m["code"])
            rep.setdefault(k, m)
            variants.setdefault(k, set()).add(prefix)
    return rep, variants


def _diff_members(schema: dict, excel: dict) -> dict:
    s, svar = _member_norm_index(schema)
    e, _ = _member_norm_index(excel)
    s_keys, e_keys = set(s), set(e)
    label_diff = [{"key": k, "schema": s[k].get("label"), "excel": e[k].get("label")}
                  for k in sorted(s_keys & e_keys)
                  if _norm(s[k].get("label")) != _norm(e[k].get("label"))]
    # members the schema declares under >1 owner namespace (informational, not "missing")
    redeclared = [{"key": k, "prefixes": sorted(v)} for k, v in sorted(svar.items())
                  if len(v) > 1]
    return {"only_in_schema": sorted(s_keys - e_keys),
            "only_in_excel": sorted(e_keys - s_keys),
            "label_diff": label_diff,
            "redeclared": redeclared}


# ------------------------------------------------------------------------- merging
def _merge_metric(s: dict, e: dict | None) -> dict:
    """Schema metric refined by the Excel entry (if any)."""
    out = dict(s)
    out["datatype_source"] = "schema"
    if e:
        # Excel refines ONLY the ambiguous numerics; otherwise the real XBRL type wins.
        if s.get("needs_refine") and e.get("datatype") and e["datatype"] != s.get("datatype"):
            out["datatype"] = e["datatype"]
            out["datatype_source"] = "excel"
        # DPM-only metadata the schema model lacks
        for fld in ("ref_domain_owner", "ref_domain_code"):
            if e.get(fld) is not None:
                out[fld] = e[fld]
        if not out.get("label") and e.get("label"):
            out["label"] = e["label"]
        for fld in ("period_type", "balance"):
            if out.get(fld) in (None, "") and e.get(fld) not in (None, ""):
                out[fld] = e[fld]
    return out


def merge_models(schema: dict, excel: dict) -> dict:
    """Merged model in dpm_model.json shape. Existence follows the schema."""
    merged = {"metrics": {}, "dimensions": {}, "domains": {}, "members": {}}
    for code, s in schema["metrics"].items():
        merged["metrics"][code] = _merge_metric(s, excel["metrics"].get(code))
    # dimensions/domains: keep schema, fill missing fields from Excel
    for code, s in schema["dimensions"].items():
        out = dict(s)
        e = excel["dimensions"].get(code)
        if e:
            for fld in ("domain_owner", "domain_code"):
                if e.get(fld) is not None:
                    out[fld] = e[fld]
            if not out.get("label") and e.get("label"):
                out["label"] = e["label"]
        merged["dimensions"][code] = out
    merged["domains"] = dict(schema["domains"])
    # members: keep the schema set (both eba_XX and boe_eba_XX qnames are valid in instances),
    # enrich each with Excel usable/default flags matched on the normalized domain+code key.
    e_mem, _ = _member_norm_index(excel)
    for prefix, mems in schema["members"].items():
        out_list = []
        for m in mems:
            out = dict(m)
            e = e_mem.get(_member_norm_key(prefix, m["code"]))
            if e:
                for fld in ("usable", "default"):
                    if fld in e:
                        out[fld] = e[fld]
                if not out.get("label") and e.get("label"):
                    out["label"] = e["label"]
            out_list.append(out)
        merged["members"][prefix] = out_list
    return merged


# --------------------------------------------------------------------- public API
def reconcile(schema: dict, excel: dict) -> dict:
    """Full reconciliation of the Arelle `schema` model against the Excel `excel` model."""
    metrics = _diff_keyed(schema["metrics"], excel["metrics"], compare_datatype=True)
    dims = _diff_keyed(schema["dimensions"], excel["dimensions"], compare_datatype=False)
    members = _diff_members(schema, excel)

    def counts(section, d):
        base = {"schema": len(schema[section]), "excel": len(excel[section])}
        base.update({k: len(v) for k, v in d.items()})
        return base

    s_rep, _ = _member_norm_index(schema)
    e_rep, _ = _member_norm_index(excel)
    member_summary = {
        "schema": len(s_rep),                                            # distinct (normalized)
        "excel": len(e_rep),
        "schema_total": sum(len(v) for v in schema["members"].values()),  # incl. redeclarations
        "only_in_schema": len(members["only_in_schema"]),
        "only_in_excel": len(members["only_in_excel"]),
        "label_diff": len(members["label_diff"]),
        "redeclared": len(members["redeclared"]),
    }

    return {
        "summary": {"metrics": counts("metrics", metrics),
                    "dimensions": counts("dimensions", dims),
                    "members": member_summary},
        "diffs": {"metrics": metrics, "dimensions": dims, "members": members},
        "merged": merge_models(schema, excel),
    }


def reconcile_with_excel(schema: dict, dict_workbook_path: str) -> dict:
    """Convenience: parse the uploaded DPM dictionary workbook, then reconcile."""
    from . import dpm_model
    excel = dpm_model.load_dpm(dict_workbook_path)
    return reconcile(schema, excel)


# ----------------------------------------------------------------------- verify main
if __name__ == "__main__":
    import sys
    import json
    from collections import Counter
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from . import taxonomy_model

    extracted = r"C:\Users\177069\ClaudeLearning\boebanking400"
    workbook = (r"C:\Users\177069\ClaudeLearning\boebankingtaxonomydpmv400"
                r"\Bank of England Banking DPM dictionary v4.0.0.xlsx")

    print(f"sniff: {sniff_workbook(workbook)}")
    print("building schema model from package…")
    schema = taxonomy_model.build_model(extracted)
    print("reconciling against DPM dictionary Excel…")
    rec = reconcile_with_excel(schema, workbook)

    for sec, c in rec["summary"].items():
        print(f"\n[{sec}] {c}")
    md = rec["diffs"]["metrics"]["datatype_mismatch"]
    print(f"\ndatatype mismatches ({len(md)}):")
    for m in md[:10]:
        print(f"  {m['code']:10} schema={m['schema']:10} excel={m['excel']:10} "
              f"needs_refine={m['needs_refine']}  {m['label']}")
    src = Counter(m["datatype_source"] for m in rec["merged"]["metrics"].values())
    print(f"\nmerged metric datatype_source: {dict(src)}")
    rd = rec["diffs"]["members"]["redeclared"]
    print(f"members redeclared under >1 namespace ({len(rd)}): "
          f"{[r['key'] for r in rd[:5]]}{' …' if len(rd) > 5 else ''}")
    if rd:
        print(f"  e.g. {rd[0]['key']} -> {rd[0]['prefixes']}")
    print(f"merged members (incl. redeclarations): "
          f"{sum(len(v) for v in rec['merged']['members'].values())}")
