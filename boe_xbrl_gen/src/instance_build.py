"""Build an XBRL instance **from the taxonomy package alone** — no sample/seed instance.

The Studio's only input is the package zip, so we assemble the instance from the package
(module entry points) + the DPM model + the selected tables' datapoint values:
  - schemaRef       -> the module entry-point .xsd that imports the selected tables
  - contexts        -> one per (period, explicit dimensions); dimension DEFAULT members omitted
  - units           -> iso4217:GBP for MONETARY, xbrli:pure for other numerics
  - filing indicators -> the template code of each selected table (drop the last variant segment)
  - facts           -> metric + contextRef (+ unitRef/@decimals for numerics) + value

Module mapping is parsed straight from `mod/*.xsd` (`schemaLocation="../tab/<code>/..."`), so no
heavy DTS load is needed. Output is structurally/dimensionally valid by construction; business
(formula) assertions are reported separately by Arelle.
"""
from __future__ import annotations

import glob
import os
import re
import random
import string
from collections import OrderedDict

from lxml import etree

XBRLI = "http://www.xbrl.org/2003/instance"
LINK = "http://www.xbrl.org/2003/linkbase"
XLINK = "http://www.w3.org/1999/xlink"
XBRLDI = "http://xbrl.org/2006/xbrldi"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
ISO4217 = "http://www.xbrl.org/2003/iso4217"
FIND = "http://www.eurofiling.info/xbrl/ext/filing-indicators"

DEFAULT_LEI = "ABCDEFGHIJ0123456789"
LEI_SCHEME = "http://standards.iso.org/iso/17442"
DEFAULT_DATE = "2026-02-28"

_BASE_NS = {
    "xsi": XSI, "xbrli": XBRLI, "link": LINK, "xlink": XLINK,
    "xbrldi": XBRLDI, "iso4217": ISO4217, "find": FIND,
}
_IMPORT_TAB_RE = re.compile(r'schemaLocation="\.\./tab/([^/"]+)/')
_HOST_RE = re.compile(r"/(www\.[^/]+)/(.*)$")
_FW_RE = re.compile(r"/fws/[^/]+/([^/]+)/", re.IGNORECASE)


def _http_url(local_path: str) -> str | None:
    m = _HOST_RE.search(local_path.replace(os.sep, "/"))
    return f"http://{m.group(1)}/{m.group(2)}" if m else None


def module_index(extracted_dir: str) -> dict:
    """{TABLE_CODE: [ {module, schemaRef, framework, path}, ... ]} — modules that import the table."""
    out: dict = {}
    for mod in glob.glob(os.path.join(extracted_dir, "**/mod/*.xsd"), recursive=True):
        try:
            text = open(mod, encoding="utf-8").read()
        except Exception:
            continue
        tables = {m.group(1).upper() for m in _IMPORT_TAB_RE.finditer(text)}
        if not tables:
            continue
        n = mod.replace(os.sep, "/")
        fw = _FW_RE.search(n)
        info = {
            "module": os.path.basename(mod)[:-4],
            "schemaRef": _http_url(mod),
            "framework": fw.group(1) if fw else "",
            "path": mod,
        }
        for t in tables:
            out.setdefault(t, []).append(info)
    return out


def _template(code: str) -> str:
    """Filing-indicator (template) code: a table code minus its trailing variant segment.
    e.g. FS701.00.01.01 -> FS701.00.01 (so .01/.02 variants share one indicator)."""
    parts = code.split(".")
    return ".".join(parts[:-1]) if len(parts) > 3 else code


# --------------------------------------------------------------- datatype-safe random values
def gen_value(datatype: str | None, enum_values: list | None = None) -> str:
    dt = (datatype or "STRING").upper()
    if dt == "MONETARY":
        return str(random.randint(1, 9_999) * 1000)            # multiple of 1000 (decimals=-3)
    if dt == "DECIMAL":
        return f"{random.uniform(0, 9999):.2f}"
    if dt == "PERCENTAGE":
        return f"{random.uniform(0, 1):.4f}"
    if dt == "INTEGER":
        return str(random.randint(0, 100_000))
    if dt == "BOOLEAN":
        return random.choice(("true", "false"))
    if dt == "DATE":
        return f"{random.randint(2018, 2026):04d}-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
    if dt == "ENUMERATION":
        if enum_values:
            v = random.choice(enum_values)
            return v["qname"] if isinstance(v, dict) else v
        return ""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


_NUMERIC = {"MONETARY", "DECIMAL", "PERCENTAGE", "INTEGER"}
_DECIMALS = {"MONETARY": "-3", "DECIMAL": "2", "PERCENTAGE": "4", "INTEGER": "0"}


def _ctx_key(period_type: str, dims: dict) -> tuple:
    return (period_type, tuple(sorted(dims.items())))


def build_instance(extracted_dir: str, model: dict, module_info: dict,
                   datapoints: list, opts: dict | None = None) -> dict:
    """Build one instance for one module.

    datapoints: [{concept: 'pfx:loc', dims: {dim_qname: member_qname}, datatype, value, table}]
      (value already chosen by the caller; rows without a value are skipped).
    Returns {filename, xml, facts, contexts, tables}.
    """
    opts = opts or {}
    lei = opts.get("lei") or DEFAULT_LEI
    scheme = opts.get("scheme") or LEI_SCHEME
    date = opts.get("date") or DEFAULT_DATE
    namespaces = model.get("namespaces", {})
    dim_defaults = model.get("dim_defaults", {})
    metrics = model.get("metrics", {})
    dimensions = model.get("dimensions", {})

    def dim_typed_domain(dim_qname: str):
        """(is_typed, typed_domain_qname) for a dimension qname; (False, None) if explicit."""
        info = dimensions.get(dim_qname.split(":")[-1], {})
        return bool(info.get("typed")), info.get("typedDomain")

    # ---- collect the prefixes actually used, to declare on the root ----
    nsmap = dict(_BASE_NS)
    nsmap["eba_model"] = namespaces.get("eba_model", "http://www.eba.europa.eu/xbrl/ext/model")

    def add_prefix(qn: str):
        if qn and ":" in qn:
            p = qn.split(":", 1)[0]
            if p not in nsmap and p in namespaces:
                nsmap[p] = namespaces[p]

    used_dps = []
    for dp in datapoints:
        if dp.get("value") in (None, ""):
            continue
        used_dps.append(dp)
        add_prefix(dp["concept"])
        # an ENUMERATION fact value is itself a member qname -> declare its prefix too
        if (dp.get("datatype") or "").upper() == "ENUMERATION":
            add_prefix(str(dp["value"]))
        for d, m in (dp.get("dims") or {}).items():
            add_prefix(d)
            typed, td = dim_typed_domain(d)
            if typed:
                add_prefix(td or "")          # declare the typed-domain element prefix (e.g. eba_typ)
            else:
                add_prefix(m)                 # explicit member is itself a qname

    root = etree.Element(f"{{{XBRLI}}}xbrl", nsmap=nsmap)
    etree.SubElement(root, f"{{{LINK}}}schemaRef", {
        f"{{{XLINK}}}type": "simple", f"{{{XLINK}}}href": module_info["schemaRef"]})

    # ---- units ----
    upure = etree.SubElement(root, f"{{{XBRLI}}}unit", {"id": "uPURE"})
    etree.SubElement(upure, f"{{{XBRLI}}}measure").text = "xbrli:pure"
    ugbp = etree.SubElement(root, f"{{{XBRLI}}}unit", {"id": "uGBP"})
    etree.SubElement(ugbp, f"{{{XBRLI}}}measure").text = "iso4217:GBP"

    # ---- contexts (deduped) ----
    def make_context(cid: str, period_type: str, dims: dict):
        ctx = etree.SubElement(root, f"{{{XBRLI}}}context", {"id": cid})
        ent = etree.SubElement(ctx, f"{{{XBRLI}}}entity")
        etree.SubElement(ent, f"{{{XBRLI}}}identifier", {"scheme": scheme}).text = lei
        per = etree.SubElement(ctx, f"{{{XBRLI}}}period")
        if period_type == "duration":
            etree.SubElement(per, f"{{{XBRLI}}}startDate").text = f"{date[:4]}-01-01"
            etree.SubElement(per, f"{{{XBRLI}}}endDate").text = date
        else:
            etree.SubElement(per, f"{{{XBRLI}}}instant").text = date
        if dims:
            scen = etree.SubElement(ctx, f"{{{XBRLI}}}scenario")
            for d, m in sorted(dims.items()):
                typed, td = dim_typed_domain(d)
                if typed and td:
                    tm = etree.SubElement(scen, f"{{{XBRLDI}}}typedMember", {"dimension": d})
                    p, ln = (td.split(":", 1) + [td])[:2] if ":" in td else (None, td)
                    tns = nsmap.get(p) if p else None
                    el = etree.SubElement(tm, f"{{{tns}}}{ln}" if tns else ln)
                    el.text = m
                else:
                    em = etree.SubElement(scen, f"{{{XBRLDI}}}explicitMember", {"dimension": d})
                    em.text = m
        return ctx

    contexts: "OrderedDict[tuple, str]" = OrderedDict()
    # filing-indicator context (no dimensions, instant) is always present
    fi_key = ("instant", ())
    contexts[fi_key] = "cFI"

    def context_for(period_type: str, dims: dict) -> str:
        # drop dimensions whose member is the dimension default
        clean = {d: m for d, m in dims.items() if dim_defaults.get(d) != m}
        key = _ctx_key(period_type, clean)
        if key not in contexts:
            contexts[key] = f"c{len(contexts)}"
        return contexts[key], clean

    # assign context ids first (so they appear before facts), then emit.
    # dedup by (concept, context): the same metric+dimensions reported twice would be a
    # duplicate fact (the row x col x z product can revisit a (concept, dims) pair).
    fact_specs = []
    seen_facts = set()
    for dp in used_dps:
        local = dp["concept"].split(":")[-1]
        ptype = (metrics.get(local, {}) or {}).get("period_type") or "instant"
        cid, clean = context_for(ptype, dp.get("dims") or {})
        fkey = (dp["concept"], cid)
        if fkey in seen_facts:
            continue
        seen_facts.add(fkey)
        fact_specs.append((dp, cid))

    for key, cid in contexts.items():
        make_context(cid, key[0], dict(key[1]))

    # ---- filing indicators ----
    find_el = etree.SubElement(root, f"{{{FIND}}}fIndicators")
    templates = []
    for t in dict.fromkeys(dp.get("table") for dp in used_dps if dp.get("table")):
        tpl = _template(t)
        if tpl not in templates:
            templates.append(tpl)
    for tpl in templates:
        fi = etree.SubElement(find_el, f"{{{FIND}}}filingIndicator", {"contextRef": "cFI"})
        fi.text = tpl

    # ---- facts ----  (also record cell→fact mapping so offline-solved values can be reflected back)
    n_facts = 0
    fact_map = []
    for dp, cid in fact_specs:
        prefix, local = dp["concept"].split(":", 1)
        ns = nsmap.get(prefix)
        if not ns:
            continue
        dt = (dp.get("datatype") or "STRING").upper()
        attrs = {"contextRef": cid}
        if dt in _NUMERIC:
            attrs["unitRef"] = "uGBP" if dt == "MONETARY" else "uPURE"
            attrs["decimals"] = _DECIMALS.get(dt, "2")
        fact = etree.SubElement(root, f"{{{ns}}}{local}", attrs)
        fact.text = str(dp["value"])
        n_facts += 1
        if dp.get("key") is not None:
            fact_map.append({"table": dp.get("table"), "key": dp.get("key"),
                             "local": local, "cid": cid})

    xml = b"\xef\xbb\xbf" + etree.tostring(
        etree.ElementTree(root), xml_declaration=True, encoding="utf-8", pretty_print=True)
    fname = f"{lei}_{module_info['module']}_{date}.xbrl"
    return {"filename": fname, "module": module_info["module"],
            "framework": module_info["framework"], "schemaRef": module_info["schemaRef"],
            "modpath": module_info.get("path"),
            "xml": xml, "facts": n_facts, "contexts": len(contexts),
            "fact_map": fact_map,
            "tables": list(dict.fromkeys(dp.get("table") for dp in used_dps if dp.get("table")))}


import subprocess
import sys
import tempfile

_DIM_ERR_RE = re.compile(r"Fact (\S+) context (\S+) dimensionally not valid")
_TRAIL_RE = re.compile(r"\s+-\s+\S+\.xbrl\b.*$")     # strip ' - instance.xbrl 444, ... vr-*.xml 9'
_SEV_RE = re.compile(r"^\[(\w+)")


def validate(xml_bytes: bytes, package_zip: str, timeout: int = 600) -> str:
    """Run Arelle offline (--validate) against the package zip; return the log text."""
    tmpdir = tempfile.mkdtemp(prefix="dpstudio_")
    inst = os.path.join(tmpdir, "instance.xbrl")
    log = os.path.join(tmpdir, "validate.log")
    with open(inst, "wb") as fh:
        fh.write(xml_bytes)
    cmd = [sys.executable, "-m", "arelle.CntlrCmdLine", "--packages", package_zip,
           "--validate", "-f", inst, "--logFile", log]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        pass
    try:
        with open(log, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def parse_report(log_text: str) -> dict:
    """Summarize an Arelle validation log into a structured report."""
    dim_invalid, value_errors, other = [], [], []
    assertions: dict = {}
    for line in log_text.splitlines():
        m = _DIM_ERR_RE.search(line)
        if m:
            dim_invalid.append({"fact": m.group(1), "context": m.group(2)})
            continue
        if "[xmlSchema:" in line and "value error" in line:
            value_errors.append(line.split(" - ")[0])
            continue
        if line.startswith("[message:"):
            rid = line[len("[message:"):line.index("]")]
            msg = _TRAIL_RE.sub("", line[line.index("]") + 1:]).strip()
            slot = assertions.setdefault(rid, {"id": rid, "count": 0, "message": msg})
            slot["count"] += 1
            continue
        sev = _SEV_RE.match(line)
        if sev and sev.group(1) not in ("info",) and "message:" not in line:
            other.append(line.split(" - ")[0])
    return {
        "dimInvalid": dim_invalid, "valueErrors": value_errors,
        "assertionsUnsatisfied": list(assertions.values()), "otherErrors": other,
        "ok": not dim_invalid and not value_errors and not other,
    }


def prune_invalid(xml_bytes: bytes, log_text: str) -> tuple:
    """Drop facts flagged dimensionally-invalid (or value-error by line) from the instance.
    Returns (new_xml_bytes, removed_count)."""
    invalid = {(d["fact"].split(":")[-1], d["context"])
               for d in parse_report(log_text)["dimInvalid"]}
    if not invalid:
        return xml_bytes, 0
    body = xml_bytes[3:] if xml_bytes[:3] == b"\xef\xbb\xbf" else xml_bytes
    root = etree.fromstring(body)
    removed = 0
    for el in list(root):
        if el.get("contextRef") is None:
            continue
        ln = etree.QName(el).localname
        if (ln, el.get("contextRef")) in invalid:
            root.remove(el)
            removed += 1
    out = b"\xef\xbb\xbf" + etree.tostring(
        etree.ElementTree(root), xml_declaration=True, encoding="utf-8", pretty_print=True)
    return out, removed


def build_instances(extracted_dir: str, model: dict, selection: dict, opts: dict | None = None) -> dict:
    """Group selected tables by module and build one instance per module.

    selection: {TABLE_CODE: [datapoint, ...]} where datapoint = {concept, dims, datatype, value}.
    Returns {instances: [build_instance result...], unmapped: [tables with no module]}.
    """
    idx = module_index(extracted_dir)
    by_module: "OrderedDict[str, dict]" = OrderedDict()
    unmapped = []
    for table, dps in selection.items():
        mods = idx.get(table.upper())
        if not mods:
            unmapped.append(table)
            continue
        info = mods[0]                                   # first module that imports this table
        slot = by_module.setdefault(info["module"], {"info": info, "dps": []})
        for dp in dps:
            d = dict(dp)
            d["table"] = table.upper()
            slot["dps"].append(d)

    instances, errors = [], []
    for slot in by_module.values():
        try:
            instances.append(build_instance(extracted_dir, model, slot["info"], slot["dps"], opts))
        except Exception as e:                      # one bad module must not sink the whole build
            errors.append({"module": slot["info"]["module"], "error": str(e)})
    return {"instances": instances, "unmapped": unmapped, "errors": errors}
