"""Build the DPM dictionary model **from the taxonomy package zip** via Arelle.

This is the per-package, taxonomy-agnostic alternative to `dpm_model.py` (which parses
the BoE DPM dictionary *Excel* workbook). It loads the package DTS with Arelle, walks the
concept set + label linkbase, and emits the SAME json shape as `model/dpm_model.json`
(`{metrics, dimensions, domains, members}`) so `generate.py` / `solve.py` consume it
unchanged — they only need `metrics[code].datatype`.

Datatype is mapped from the XSD item type. Numeric subtypes are ambiguous from the schema
alone (PERCENTAGE vs DECIMAL vs INTEGER all look like decimal item types), so those are
flagged `needs_refine=True` — the optional DPM-dictionary-Excel reconciliation (reconcile.py)
fixes exactly those.

Loading is cheap (~3-5 s for the full shared dictionary; the "Arelle = 46 min" warning is
about *validation*, not model loading).
"""
from __future__ import annotations

import json
import time
from pathlib import Path


# ----------------------------------------------------------------- datatype mapping
def _dpm_datatype(con) -> tuple[str, bool]:
    """XSD item type -> (DPM datatype, needs_refine).

    needs_refine flags numeric concepts whose precise DPM subtype (PERCENTAGE / DECIMAL /
    INTEGER) cannot be told apart from the schema — reconciliation against the DPM Excel
    resolves these.
    """
    if getattr(con, "isEnumeration", False):
        return "ENUMERATION", False
    typeq = str(getattr(con, "typeQname", None) or "").lower()
    base = (getattr(con, "baseXbrliType", None) or "").lower()
    if "enumeration" in typeq:
        return "ENUMERATION", False
    if "monetary" in base:
        return "MONETARY", False
    if "boolean" in base:
        return "BOOLEAN", False
    if "date" in base:
        return "DATE", False
    if "integer" in base:
        return "INTEGER", False
    if "string" in base:
        return "STRING", False
    if "percent" in typeq:
        return "PERCENTAGE", False
    if any(x in base for x in ("decimal", "double", "float", "pure")):
        return "DECIMAL", True          # ambiguous: could be PERCENTAGE / INTEGER
    return "STRING", False


def _owner(prefix: str) -> str:
    """'eba_met' -> 'eba', 'boe_AS' -> 'boe'."""
    return prefix.split("_", 1)[0] if "_" in prefix else prefix


def _split_qname(con) -> tuple[str, str] | None:
    """Concept -> (prefix, local) using the DPM-style qname str, e.g. 'eba_met:mi1'."""
    s = str(con.qname) if getattr(con, "qname", None) is not None else ""
    if ":" not in s:
        return None
    prefix, local = s.split(":", 1)
    return prefix, local


def build_model_from_dts(modelXbrl) -> dict:
    """Walk a loaded Arelle ModelXbrl into the dpm_model.json shape."""
    model = {"metrics": {}, "dimensions": {}, "domains": {}, "members": {}, "namespaces": {}}

    def label(con) -> str:
        try:
            return con.label(lang="en", fallbackToQname=False) or ""
        except Exception:
            return ""

    for qn, con in modelXbrl.qnameConcepts.items():
        if not getattr(con, "isItem", False):
            continue
        split = _split_qname(con)
        if split is None:
            continue
        prefix, local = split
        owner = _owner(prefix)
        # prefix -> namespace URI, needed to emit a valid instance from scratch
        try:
            ns = con.qname.namespaceURI
            if ns:
                model["namespaces"].setdefault(prefix, ns)
        except Exception:
            pass

        # ---- dimension ----
        if getattr(con, "isDimensionItem", False):
            is_typed = bool(getattr(con, "isTypedDimension", False))
            typed_domain = None
            if is_typed:
                tde = getattr(con, "typedDomainElement", None)
                if tde is not None and getattr(tde, "qname", None) is not None:
                    tq = tde.qname
                    typed_domain = f"{tq.prefix}:{tq.localName}" if tq.prefix else tq.localName
                    if tq.namespaceURI:
                        model["namespaces"].setdefault(tq.prefix, tq.namespaceURI)
            model["dimensions"][local] = {
                "label": label(con),
                "owner": owner,
                "prefix": prefix,
                "qname": f"{prefix}:{local}",
                "typed": is_typed,
                "typedDomain": typed_domain,
            }
            continue

        # ---- metric ----  (met namespace; prefix like eba_met / boe_met)
        if prefix.endswith("_met"):
            dt, needs_refine = _dpm_datatype(con)
            model["metrics"][local] = {
                "label": label(con),
                "owner": owner,
                "prefix": prefix,
                "qname": f"{prefix}:{local}",
                "datatype": dt,
                "needs_refine": needs_refine,
                "period_type": getattr(con, "periodType", None),
                "balance": getattr(con, "balance", None),
            }
            continue

        # ---- domain member ----  (type nonnum:domainItemType; prefix = '<owner>_<DOMAIN>')
        typeq = str(getattr(con, "typeQname", None) or "").lower()
        if "domainitemtype" in typeq:
            model["members"].setdefault(prefix, []).append({
                "code": local,
                "label": label(con),
                "owner": owner,
                "prefix": prefix,
                "qname": f"{prefix}:{local}",
            })
            # register the domain (explicit, since it has members)
            dom_code = prefix.split("_", 1)[1] if "_" in prefix else prefix
            model["domains"].setdefault(dom_code, {
                "label": "", "owner": owner, "type": "explicit",
                "datatype": None, "prefix": prefix,
            })

    return model


# ----------------------------------------------------------------------- DTS loading
# We build the dictionary from the **concept schemas** (met/dim + every domain's mem.xsd),
# NOT from module entry points: a module pulls in heavy table/presentation linkbases (the
# big modules take minutes), whereas the bare concept schemas load in seconds and still pull
# their label linkbases. Loading the dict schemas directly gives 100% coverage cheaply.
import glob as _glob
import os as _os
import re as _re

_DICT_SCHEMA_GLOBS = (
    "**/dict/met/met.xsd",
    "**/dict/dim/dim.xsd",
    "**/dict/dom/*/mem.xsd",
)


def _find_package_root(extracted_dir: str) -> str:
    """The dir holding META-INF/taxonomyPackage.xml (what Arelle wants as the package)."""
    hits = _glob.glob(_os.path.join(extracted_dir, "**", "META-INF", "taxonomyPackage.xml"),
                      recursive=True)
    if not hits:
        return extracted_dir
    return _os.path.dirname(_os.path.dirname(hits[0]))


def _dict_schema_paths(extracted_dir: str) -> list[str]:
    """Local file paths of every dictionary concept schema (met/dim + each domain's mem.xsd).

    We load by **local path**, not by canonical http URL: registering an extracted *directory*
    as an Arelle package is unreliable (it can be rejected as "not a zip", leaving the catalog
    rewrites inactive so http URLs don't remap and load to 0 concepts). Loading the file
    directly always reads its concepts; Arelle still resolves the schema's imports + label
    linkbases via the package's META-INF/catalog.xml.
    """
    paths = set()
    for pat in _DICT_SCHEMA_GLOBS:
        paths.update(_glob.glob(_os.path.join(extracted_dir, pat), recursive=True))
    return sorted(paths)


def _merge(into: dict, m: dict) -> None:
    for sec in ("metrics", "dimensions", "domains"):
        into[sec].update(m[sec])
    into.setdefault("namespaces", {}).update(m.get("namespaces", {}))
    for prefix, mems in m["members"].items():
        seen = {x["code"] for x in into["members"].setdefault(prefix, [])}
        into["members"][prefix].extend(x for x in mems if x["code"] not in seen)


def build_dimension_defaults(mm, extracted_dir: str) -> dict:
    """{dimension_qname -> default_member_qname}. Default members must be OMITTED from instance
    contexts (reporting one is an xbrldie:DefaultValueUsedInInstanceError). Read from the
    dimension-default relationships in dim.xsd's definition linkbase (loaded as a primary entry)."""
    from arelle import ModelXbrl, XbrlConst
    dims = sorted(_glob.glob(_os.path.join(extracted_dir, "**/dict/dim/dim.xsd"), recursive=True))
    out: dict = {}
    for d in dims:
        try:
            mx = ModelXbrl.load(mm, d)
        except Exception:
            continue
        try:
            rs = mx.relationshipSet(XbrlConst.dimensionDefault)
            for r in rs.modelRelationships:
                out[str(r.fromModelObject.qname)] = str(r.toModelObject.qname)
        except Exception:
            pass
        try:
            mx.close()
        except Exception:
            pass
    return out


def build_dimension_domains(mm, extracted_dir: str) -> dict:
    """{dimension local code -> [{qname,label}]} of the usable members of each EXPLICIT
    dimension's domain. Lets the UI offer *real* members for an OPEN explicit dimension (an
    aspectNode), instead of a synthesised integer that Arelle rejects as not-a-real-member.

    The dimension-domain + domain-member relationships live in the dim-def.xml linkbases that
    attach when dim.xsd is loaded as a primary entry. There are TWO dim.xsd (BoE + EBA); loading
    only one misses the other host's dimensions (e.g. eba_dim:IGS -> eba_exp:BT), so we load
    both and union. ~296 dimensions resolve; cheap (the same primary-entry loads we already do
    for dimension defaults)."""
    from arelle import ModelXbrl, XbrlConst
    dims = sorted(_glob.glob(_os.path.join(extracted_dir, "**/dict/dim/dim.xsd"), recursive=True))
    out: dict = {}
    for d in dims:
        try:
            mx = ModelXbrl.load(mm, d)
        except Exception:
            continue
        try:
            dd = mx.relationshipSet(XbrlConst.dimensionDomain)
            dm = mx.relationshipSet(XbrlConst.domainMember)
            for r in dd.modelRelationships:
                local = r.fromModelObject.qname.localName
                if local in out:
                    continue
                members = _walk_usable_members(mx, dm, r.toModelObject.qname)
                if members:
                    out[local] = members
        except Exception:
            pass
        try:
            mx.close()
        except Exception:
            pass
    return out


# Extensible Enumerations 1.0: each enum concept carries enum:domain (head member) +
# enum:linkrole (the domain-member network whose usable members are its allowed values).
_EE_NS = "http://xbrl.org/2014/extensible-enumerations"
_HIER_SCHEMA_GLOB = "**/dict/dom/*/hier.xsd"
_MET_SCHEMA_GLOB = "**/dict/met/met.xsd"
# (host, domain-token) extracted from an enum linkrole URI and from a hier.xsd file path, so we
# can load *only* the relevant domain schema per enum (loading a domain hier.xsd as a PRIMARY
# entry reliably discovers its hier-def linkbase — a secondary ModelDocument.load does not).
_ROLE_KEY_RE = _re.compile(r"//(www\.[^/]+)/.*/dict/dom/([^/]+)/[^/]+$")
_FILE_KEY_RE = _re.compile(r"/(www\.[^/]+)/.*/dict/dom/([^/]+)/hier\.xsd$")


def _walk_usable_members(mx, rel_set, head_qname) -> list[dict]:
    """Descendants of `head_qname` in a domain-member relationship set, usable members only."""
    out, seen = [], set()

    def walk(cq):
        node = mx.qnameConcepts.get(cq)
        if node is None:
            return
        for r in rel_set.fromModelObject(node):
            m = r.toModelObject
            mq = str(m.qname)
            if mq in seen:
                continue
            seen.add(mq)
            usable = (r.get(f"{{{_EE_NS}}}usable") or r.get("usable") or "true").lower()
            if usable != "false":
                try:
                    lab = m.label(lang="en", fallbackToQname=False) or m.qname.localName
                except Exception:
                    lab = m.qname.localName
                out.append({"qname": mq, "label": lab})
            walk(m.qname)

    walk(head_qname)
    return out


def _enum_specs(mm, extracted_dir: str) -> list[tuple]:
    """(metric code, enum:domain str, enum:linkrole, nsmap) for every ENUMERATION metric."""
    from arelle import ModelXbrl, ModelDocument

    mets = sorted(_glob.glob(_os.path.join(extracted_dir, _MET_SCHEMA_GLOB), recursive=True))
    if not mets:
        return []
    mx = ModelXbrl.load(mm, mets[0])
    for p in mets[1:]:
        try:
            ModelDocument.load(mx, p)
        except Exception:
            continue
    specs = []
    for q, con in mx.qnameConcepts.items():
        if not getattr(con, "isEnumeration", False):
            continue
        dom = con.get(f"{{{_EE_NS}}}domain")
        lr = con.get(f"{{{_EE_NS}}}linkrole")
        if dom and lr:
            specs.append((q.localName, dom, lr, dict(con.nsmap)))
    return specs


def build_enumerations(mm, extracted_dir: str) -> dict:
    """{metric local code -> [{qname,label}]} of allowed values for every ENUMERATION metric.

    EE 1.0 stores allowed values as the usable domain-members of `enum:domain` in the
    `enum:linkrole` network. That network lives in the *domain's* hier-def linkbase, which only
    attaches reliably when the domain `hier.xsd` is loaded as a **primary entry** (a secondary
    ModelDocument.load of EBA schemas silently drops their linkbaseRefs). So we map each enum to
    its domain hier.xsd (by host + domain token) and load only those, one primary entry each.
    Resolves ~99% of enums in ~30 s; metrics whose role isn't a standard dict/dom role (a few
    currency/metric-domain enums) are left without a value list (still typed ENUMERATION).
    """
    from arelle import ModelXbrl, XbrlConst
    from arelle.ModelValue import qname

    specs = _enum_specs(mm, extracted_dir)
    if not specs:
        return {}

    file_by_key = {}
    for h in _glob.glob(_os.path.join(extracted_dir, _HIER_SCHEMA_GLOB), recursive=True):
        m = _FILE_KEY_RE.search(h.replace(_os.sep, "/"))
        if m:
            file_by_key[(m.group(1), m.group(2).lower())] = h

    groups: dict[str, list] = {}
    for code, dom, lr, ns in specs:
        m = _ROLE_KEY_RE.search(lr)
        f = file_by_key.get((m.group(1), m.group(2).lower())) if m else None
        if f:
            groups.setdefault(f, []).append((code, dom, lr, ns))

    out: dict = {}
    for f, items in groups.items():
        try:
            mx = ModelXbrl.load(mm, f)
        except Exception:
            continue
        for code, dom, lr, ns in items:
            try:
                head = qname(dom, ns)
            except Exception:
                continue
            members = _walk_usable_members(mx, mx.relationshipSet(XbrlConst.domainMember, lr), head)
            if members:
                out[code] = members
        try:
            mx.close()
        except Exception:
            pass
    return out


def build_model(extracted_dir: str, package: str | None = None) -> dict:
    """Build the full dictionary model from an extracted taxonomy package directory.

    `package` is what Arelle registers for URL remapping; defaults to the package root dir
    inside `extracted_dir` (so the studio never needs to keep the original zip). Loads every
    dictionary concept schema **offline** (no network round-trips) and unions them. Also
    resolves ENUMERATION allowed values into `model["enumerations"]`.
    """
    from arelle import Cntlr, ModelManager, PackageManager
    root = package or _find_package_root(extracted_dir)
    cntlr = Cntlr.Cntlr(logFileName="logToBuffer")
    cntlr.startLogging()
    cntlr.webCache.workOffline = True            # skip the slow failed HTTP attempts
    PackageManager.init(cntlr)
    PackageManager.addPackage(cntlr, root)
    PackageManager.rebuildRemappings(cntlr)
    mm = ModelManager.initialize(cntlr)

    acc = {"metrics": {}, "dimensions": {}, "domains": {}, "members": {}}
    for path in _dict_schema_paths(extracted_dir):
        try:
            _merge(acc, build_model_from_dts(mm.load(path)))
        except Exception:
            continue
    try:
        acc["enumerations"] = build_enumerations(mm, extracted_dir)
    except Exception:
        acc["enumerations"] = {}
    try:
        acc["dim_defaults"] = build_dimension_defaults(mm, extracted_dir)
    except Exception:
        acc["dim_defaults"] = {}
    try:
        acc["dim_members"] = build_dimension_domains(mm, extracted_dir)
    except Exception:
        acc["dim_members"] = {}
    return acc


# ----------------------------------------------------------------------- verify main
if __name__ == "__main__":
    import sys
    from collections import Counter
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    extracted = sys.argv[1] if len(sys.argv) > 1 else (
        r"C:\Users\177069\ClaudeLearning\boebanking400")

    t0 = time.time()
    model = build_model(extracted)
    dt_ms = round((time.time() - t0) * 1000)

    n_members = sum(len(v) for v in model["members"].values())
    print(f"built from package dir in {dt_ms} ms")
    print(f"  metrics    : {len(model['metrics'])}")
    print(f"  dimensions : {len(model['dimensions'])}")
    print(f"  domains    : {len(model['domains'])}")
    print(f"  member sets: {len(model['members'])}  ({n_members} members)")
    hist = Counter(m["datatype"] for m in model["metrics"].values())
    refine = sum(1 for m in model["metrics"].values() if m.get("needs_refine"))
    print(f"  datatype histogram : {dict(sorted(hist.items()))}")
    print(f"  needs_refine (ambiguous numeric): {refine}")

    # compare to the known-good Excel-built model
    ref_path = Path(__file__).resolve().parent.parent / "model" / "dpm_model.json"
    if ref_path.exists():
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
        rhist = Counter(m.get("datatype") for m in ref["metrics"].values())
        print("\n  vs prebuilt dpm_model.json (Excel):")
        print(f"    metrics {len(ref['metrics'])}  dims {len(ref['dimensions'])}  "
              f"members {sum(len(v) for v in ref['members'].values())}")
        print(f"    Excel datatype histogram : {dict(sorted(rhist.items()))}")
        only_zip = set(model["metrics"]) - set(ref["metrics"])
        only_xl = set(ref["metrics"]) - set(model["metrics"])
        print(f"    metrics only-in-zip: {len(only_zip)}  only-in-Excel: {len(only_xl)}")
