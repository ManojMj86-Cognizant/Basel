"""Collect the package's business (formula) validation rules per module, for browsing.

A module entry point (`mod/<module>.xsd`) references assertion sets (`val/aset-*.xml`); each
assertion set links the table(s) it applies to (`../tab/<code>/<code>-rend.xml#boe_t<CODE>`) and
the value rule(s) it enforces (`vr-<id>.xml#<label>`). The `vr-<id>.xml` holds the assertion +
its XPath `test`/severity (parsed by `formula_rules.parse_file`); `vr-<id>-err-en.xml` holds the
human-readable message. We stitch these into flat rule records {id, severity, test, message,
tables} — read-only, no Arelle.
"""
from __future__ import annotations

import glob
import os
import re

from lxml import etree

_XLINK = "http://www.w3.org/1999/xlink"
_HREF = f"{{{_XLINK}}}href"
_AR_SEVERITY = "http://xbrl.org/arcrole/2016/assertion-unsatisfied-severity"
_REND_RE = re.compile(r"/tab/([^/]+)/[^/]+-rend\.xml(?:#|$)", re.IGNORECASE)
_VR_RE = re.compile(r"(vr-[^/#\"]+\.xml)(?:#(.+))?$", re.IGNORECASE)
_ASET_RE = re.compile(r'href="(\.\./val/aset-[^"]+\.xml)"')


def _module_path(extracted_dir: str, module: str) -> str | None:
    hits = glob.glob(os.path.join(extracted_dir, "**", "mod", f"{module}.xsd"), recursive=True)
    return hits[0] if hits else None


def _aset_paths(module_xsd: str) -> list[str]:
    text = open(module_xsd, encoding="utf-8", errors="replace").read()
    mod_dir = os.path.dirname(module_xsd)
    out, seen = [], set()
    for m in _ASET_RE.finditer(text):
        p = os.path.normpath(os.path.join(mod_dir, m.group(1)))
        if p not in seen and os.path.exists(p):
            seen.add(p)
            out.append(p)
    return out


def _parse_aset(aset_path: str) -> tuple[list[str], list[tuple[str, str]]]:
    """(tables, [(vr_path, assertion_label)]) referenced by one assertion set."""
    tables, vrs, seen_vr = [], [], set()
    val_dir = os.path.dirname(aset_path)
    try:
        root = etree.parse(aset_path).getroot()
    except Exception:
        return tables, vrs
    for el in root.iter():
        href = el.get(_HREF)
        if not href:
            continue
        mt = _REND_RE.search(href.replace("\\", "/"))
        if mt:
            code = mt.group(1).upper()
            if code not in tables:
                tables.append(code)
            continue
        mv = _VR_RE.search(href)
        if mv:
            vp = os.path.normpath(os.path.join(val_dir, mv.group(1)))
            key = (vp, mv.group(2) or "")
            if key not in seen_vr and os.path.exists(vp):
                seen_vr.add(key)
                vrs.append(key)
    return tables, vrs


def _lean_parse_vr(path: str) -> list[dict]:
    """Fast extract of {id, test, severity} per valueAssertion — no variable/filter graph
    (which is what makes formula_rules.parse_file slow on the big cross-table vr files)."""
    a_type = f"{{{_XLINK}}}type"
    a_label = f"{{{_XLINK}}}label"
    a_from = f"{{{_XLINK}}}from"
    a_to = f"{{{_XLINK}}}to"
    a_arcrole = f"{{{_XLINK}}}arcrole"
    assertions = []          # (label, id, test)
    sev_arc = {}             # from_label -> to_label (severity arcs only)
    loc_href = {}            # label -> href
    try:
        for _, el in etree.iterparse(path, events=("end",)):
            typ = el.get(a_type)
            if typ == "resource" and etree.QName(el).localname == "valueAssertion":
                assertions.append((el.get(a_label), el.get("id") or el.get(a_label), el.get("test")))
            elif typ == "arc" and el.get(a_arcrole) == _AR_SEVERITY:
                sev_arc[el.get(a_from)] = el.get(a_to)
            elif typ == "locator":
                loc_href[el.get(a_label)] = el.get(_HREF, "")
            el.clear()
    except Exception:
        return []
    out = []
    for label, rid, test in assertions:
        href = loc_href.get(sev_arc.get(label, ""), "")
        sev = href.split("#")[-1] if "#" in href else "ERROR"
        out.append({"id": rid, "test": test or "", "severity": sev or "ERROR"})
    return out


def _message_for(vr_path: str) -> str | None:
    """Human message from vr-<id>-err-en.xml (fallback -lab-en.xml). {{x}} -> {x}."""
    stem = vr_path[:-4]  # drop .xml
    for suffix in ("-err-en.xml", "-lab-en.xml"):
        mp = stem + suffix
        if not os.path.exists(mp):
            continue
        try:
            root = etree.parse(mp).getroot()
        except Exception:
            continue
        best = None
        for el in root.iter():
            if etree.QName(el).localname == "message" and el.text and el.text.strip():
                role = el.get("{http://www.w3.org/1999/xlink}role") or ""
                txt = el.text.strip().replace("{{", "{").replace("}}", "}")
                # prefer the verbose 'message' role over 'terseMessage'
                if role.endswith("/message"):
                    return txt
                best = best or txt
        if best:
            return best
    return None


def collect_module_rules(extracted_dir: str, module: str) -> dict:
    """All business rules a module enforces: {module, nRules, rules: [{id, severity, test,
    message, tables}]}. Rules are deduped by id; tables = union across the asets using them."""
    mod_xsd = _module_path(extracted_dir, module)
    if not mod_xsd:
        return {"module": module, "nRules": 0, "rules": [], "error": "module not found"}

    by_id: dict[str, dict] = {}
    parsed_cache: dict[str, list] = {}
    msg_cache: dict[str, str | None] = {}

    for aset in _aset_paths(mod_xsd):
        tables, vrs = _parse_aset(aset)
        for vr_path, label in vrs:
            if vr_path not in parsed_cache:
                parsed_cache[vr_path] = _lean_parse_vr(vr_path)
                msg_cache[vr_path] = _message_for(vr_path)
            for rule in parsed_cache[vr_path]:
                rid = rule["id"]
                rec = by_id.get(rid)
                if rec is None:
                    rec = by_id[rid] = {
                        "id": rid,
                        "severity": rule["severity"],
                        "test": rule["test"],
                        "message": msg_cache.get(vr_path),
                        "source": os.path.basename(vr_path),
                        "tables": [],
                    }
                for t in tables:
                    if t not in rec["tables"]:
                        rec["tables"].append(t)

    rules = sorted(by_id.values(), key=lambda r: r["id"])
    return {"module": module, "nRules": len(rules), "rules": rules}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    base = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\177069\ClaudeLearning\boebanking400"
    mod = sys.argv[2] if len(sys.argv) > 2 else "pra001"
    out = collect_module_rules(base, mod)
    print(f"module {mod}: {out['nRules']} rules")
    for r in out["rules"][:8]:
        print(f"  [{r['severity']}] {r['id']}  tables={r['tables']}")
        print(f"      msg: {(r['message'] or '')[:90]}")
        print(f"      test: {r['test'][:90]}")
