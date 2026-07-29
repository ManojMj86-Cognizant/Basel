"""Per-table datapoints from the XBRL **Table Linkbase** (`*-rend.xml`) in the package.

Phase 1b. A table's `*-rend.xml` defines breakdowns per axis (x/y/z); each axis is a tree of
`table:ruleNode`s carrying aspects — `formula:concept` (the metric) and `formula:explicit
Dimension` (dimension -> member). Aspects **inherit down the tree** (a child overrides/adds to
its parent). A datapoint = the cartesian product of one concrete position from each axis, with
the aspect sets merged. Some axes are *open* (`table:aspectNode` over a dimension) — those are
reported as open axes rather than expanded (an MVP-honest deferral).

These files are small, so we parse them directly with lxml — far cheaper than loading the
module DTS through Arelle's rendering resolver (the big modules take minutes to load).
"""
from __future__ import annotations

import glob
import os
import re
import time
from pathlib import Path

from lxml import etree

_NS = {
    "link": "http://www.xbrl.org/2003/linkbase",
    "table": "http://xbrl.org/2014/table",
    "formula": "http://xbrl.org/2008/formula",
    "xlink": "http://www.w3.org/1999/xlink",
}
_XLINK = _NS["xlink"]
_FW_RE = re.compile(r"/fws/[^/]+/([^/]+)/", re.IGNORECASE)


# ----------------------------------------------------------------- table discovery
def list_tables(extracted_dir: str) -> list[dict]:
    """Every table in the package: {code, framework, path}, sorted by code."""
    out = []
    for p in glob.glob(os.path.join(extracted_dir, "**", "*-rend.xml"), recursive=True):
        rel = p.replace("\\", "/")
        m = _FW_RE.search(rel)
        stem = os.path.basename(p)[: -len("-rend.xml")]
        out.append({"code": stem.upper(), "framework": m.group(1) if m else "", "path": p})
    out.sort(key=lambda t: t["code"])
    return out


# ------------------------------------------------------------------- table parsing
def _qname_text(el) -> str | None:
    q = el.find("formula:qname", _NS)
    return q.text.strip() if q is not None and q.text else None


def _rulenode_aspects(node) -> dict:
    """Aspects declared directly on a ruleNode: {'concept': qname?, 'dims': {dim: member}}."""
    aspects = {"concept": None, "dims": {}}
    c = node.find("formula:concept", _NS)
    if c is not None:
        aspects["concept"] = _qname_text(c)
    for ed in node.findall("formula:explicitDimension", _NS):
        dim = ed.get("dimension")
        mem = ed.find("formula:member", _NS)
        if dim and mem is not None:
            aspects["dims"][dim] = _qname_text(mem)
    return aspects


_RC_ROLE = "http://www.eurofiling.info/xbrl/role/rc-code"


def rc_codes(rend_path: str) -> dict:
    """{node_id -> BoE rc-code} from the sibling `<table>-lab-codes.xml` (eurofiling rc-code
    labels). Bridges the validations-workbook cell refs (t/r/c/z codes like '0430') to the
    table-linkbase nodes (and thus to metric+dimension aspects → facts)."""
    lc = rend_path.replace("-rend.xml", "-lab-codes.xml")
    out: dict = {}
    if not os.path.exists(lc):
        return out
    root = etree.parse(lc).getroot()
    loc_to_node, res_to_rc = {}, {}
    for el in root.iter():
        ln = etree.QName(el).localname
        if ln == "loc":
            href = el.get(f"{{{_XLINK}}}href", "")
            loc_to_node[el.get(f"{{{_XLINK}}}label")] = href.split("#", 1)[1] if "#" in href else ""
        elif ln == "label" and el.get(f"{{{_XLINK}}}role") == _RC_ROLE:
            res_to_rc[el.get(f"{{{_XLINK}}}label")] = (el.text or "").strip()
    for el in root.iter():
        if etree.QName(el).localname == "arc":
            frm, to = el.get(f"{{{_XLINK}}}from"), el.get(f"{{{_XLINK}}}to")
            if frm in loc_to_node and to in res_to_rc:
                out[loc_to_node[frm]] = res_to_rc[to]
    return out


def parse_table(rend_path: str) -> dict:
    """Parse one *-rend.xml into {code, datapoints, axes, open_axes, n_datapoints}.

    datapoints: list of {concept, dims:{dim:member}} (qnames). open_axes: dimensions whose
    axis is open (aspectNode) and therefore not enumerated here.
    """
    tree = etree.parse(rend_path)
    root = tree.getroot()

    # rc-codes (node -> BoE r/c/z code). A non-abstract ruleNode that carries an rc-code is a
    # REPORTABLE position even when it declares no aspects of its own — these are the "total"
    # rows/cols (e.g. OF34.07 r0180) that inherit everything from the breakdown root. Without this
    # they were dropped (concept/dims both empty), so the cell was never generated or resolvable,
    # and any rule referencing it (incl. cross-table aggregations like b0844–b0851) silently failed.
    codes = rc_codes(rend_path)

    table_el = root.find(".//table:table", _NS)
    code = ""
    if table_el is not None:
        tid = table_el.get("id", "")
        code = re.sub(r"^.*?_t", "", tid)  # 'boe_tC01.00.01.01' -> 'C01.00.01.01'

    # label -> element, for ruleNodes and aspectNodes
    nodes = {}
    for tag in ("ruleNode", "aspectNode"):
        for el in root.findall(f".//table:{tag}", _NS):
            nodes[el.get(f"{{{_XLINK}}}label")] = el

    # arcs: table->breakdown (axis), breakdown->rootNode, parent->child
    breakdown_axis: dict[str, str] = {}
    breakdown_root: dict[str, list] = {}
    children: dict[str, list] = {}
    for arc in root.findall(".//table:tableBreakdownArc", _NS):
        breakdown_axis[arc.get(f"{{{_XLINK}}}to")] = arc.get("axis", "")
    for arc in root.findall(".//table:breakdownTreeArc", _NS):
        breakdown_root.setdefault(arc.get(f"{{{_XLINK}}}from"), []).append(
            (float(arc.get("order", "0")), arc.get(f"{{{_XLINK}}}to")))
    for arc in root.findall(".//table:definitionNodeSubtreeArc", _NS):
        children.setdefault(arc.get(f"{{{_XLINK}}}from"), []).append(
            (float(arc.get("order", "0")), arc.get(f"{{{_XLINK}}}to")))

    open_axes: list[dict] = []

    def walk(label, inherited, positions, axis):
        """DFS a definition-node subtree, accumulating inherited aspects."""
        el = nodes.get(label)
        if el is None:
            return
        local = etree.QName(el).localname
        if local == "aspectNode":                       # open dimension axis
            dim = None
            da = el.find("table:dimensionAspect", _NS)
            if da is not None and da.text:
                dim = da.text.strip()
            open_axes.append({"node": label, "dimension": dim, "axis": axis})
            cur = inherited
        else:
            asp = _rulenode_aspects(el)
            cur = {"concept": asp["concept"] or inherited["concept"],
                   "dims": {**inherited["dims"], **asp["dims"]}}
            is_abstract = el.get("abstract") == "true"
            if not is_abstract and (cur["concept"] or cur["dims"] or codes.get(label)):
                positions.append({"concept": cur["concept"], "dims": dict(cur["dims"]), "node": label})
        for _, child in sorted(children.get(label, [])):
            walk(child, cur, positions, axis)

    # positions per axis (merge breakdowns that share an axis)
    axis_positions: dict[str, list] = {}
    for bd_label, axis in breakdown_axis.items():
        positions: list = []
        for _, rootlabel in sorted(breakdown_root.get(bd_label, [])):
            walk(rootlabel, {"concept": None, "dims": {}}, positions, axis)
        axis_positions.setdefault(axis, []).extend(positions)

    # datapoints = cartesian product across axes that actually carry aspects
    axes = [pos for pos in axis_positions.values() if pos]
    datapoints: list[dict] = []
    if axes:
        combos = [{"concept": None, "dims": {}}]
        for positions in axes:
            combos = [
                {"concept": p["concept"] or base["concept"],
                 "dims": {**base["dims"], **p["dims"]}}
                for base in combos for p in positions
            ]
        # keep only datapoints that resolved a metric (concept)
        seen = set()
        for dp in combos:
            if not dp["concept"]:
                continue
            key = (dp["concept"], tuple(sorted(dp["dims"].items())))
            if key in seen:
                continue
            seen.add(key)
            datapoints.append(dp)

    return {
        "code": code or os.path.basename(rend_path)[: -len("-rend.xml")].upper(),
        "axes": {ax: len(pos) for ax, pos in axis_positions.items()},
        "axis_positions": axis_positions,   # {axis -> [{concept, dims}]} for the grid layout
        "open_axes": open_axes,
        "datapoints": datapoints,
        "n_datapoints": len(datapoints),
    }


def table_grid(rend_path: str, model: dict | None = None) -> dict:
    """The table laid out for editing: x positions -> columns, y -> rows, z -> selectable
    layers. Each position carries a human label (from the dictionary model) plus its raw
    aspects (concept + dimension members), so a cell = merge(row, column, selected z)."""
    p = parse_table(rend_path)
    ap = p["axis_positions"]

    met_label, met_datatype, mem_label = {}, {}, {}
    enums = {}
    if model:
        met_label = {c: m.get("label") for c, m in model.get("metrics", {}).items()}
        met_datatype = {c: m.get("datatype") for c, m in model.get("metrics", {}).items()}
        enums = model.get("enumerations", {})
        for mems in model.get("members", {}).values():
            for m in mems:
                mem_label[m.get("qname")] = m.get("label")

    def label(pos: dict) -> str:
        parts = []
        if pos.get("concept"):
            code = pos["concept"].split(":")[-1]
            parts.append(met_label.get(code) or code)
        for dim, mem in sorted(pos.get("dims", {}).items()):
            parts.append(mem_label.get(mem) or (mem.split(":")[-1] if mem else dim))
        return " · ".join(parts)

    def datatype_of(pos: dict):
        c = pos.get("concept")
        return met_datatype.get(c.split(":")[-1]) if c else None

    def enum_of(pos: dict):
        c = pos.get("concept")
        return enums.get(c.split(":")[-1]) if c else None

    def positions(axis: str) -> list:
        out = []
        for pos in ap.get(axis, []):
            ev = enum_of(pos)
            entry = {"label": label(pos) or "(value)",
                     "concept": pos.get("concept"),
                     "datatype": datatype_of(pos),
                     "dims": pos.get("dims", {})}
            if ev:
                entry["enumValues"] = ev
            out.append(entry)
        return out

    # enrich each OPEN axis with typed flag + (for explicit dims) the real domain members,
    # so the UI can offer a member dropdown for added rows instead of a synthesised integer.
    dim_members = model.get("dim_members", {}) if model else {}
    dims_meta = model.get("dimensions", {}) if model else {}

    def enrich_open(o: dict) -> dict:
        local = (o.get("dimension") or "").split(":")[-1]
        typed = bool(dims_meta.get(local, {}).get("typed"))
        e = {**o, "typed": typed}
        if not typed and dim_members.get(local):
            e["members"] = dim_members[local]
        return e

    return {
        "code": p["code"],
        "axes": p["axes"],
        "openAxes": [enrich_open(o) for o in p["open_axes"]],
        "columns": positions("x"),
        "rows": positions("y"),
        "zPositions": positions("z"),
    }


def table_datapoints(rend_path: str, model: dict | None = None) -> dict:
    """parse_table + label/datatype enrichment from a dictionary model (taxonomy_model shape)."""
    parsed = parse_table(rend_path)
    if model is None:
        return parsed

    def metric_of(qname):
        code = qname.split(":")[-1] if qname else None
        return model.get("metrics", {}).get(code)

    dim_label = {d.get("qname"): d.get("label") for d in model.get("dimensions", {}).values()}
    mem_label = {}
    for mems in model.get("members", {}).values():
        for m in mems:
            mem_label[m.get("qname")] = m.get("label")

    rows = []
    for dp in parsed["datapoints"]:
        met = metric_of(dp["concept"]) or {}
        rows.append({
            "metric": dp["concept"],
            "metricLabel": met.get("label"),
            "datatype": met.get("datatype"),
            "dimensions": [
                {"dimension": dim, "dimLabel": dim_label.get(dim),
                 "member": mem, "memberLabel": mem_label.get(mem)}
                for dim, mem in sorted(dp["dims"].items())
            ],
        })
    parsed["rows"] = rows
    return parsed


# ----------------------------------------------------------------------- verify main
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    base = r"C:\Users\177069\ClaudeLearning\boebanking400"

    tables = list_tables(base)
    print(f"tables found: {len(tables)}")
    fw = {}
    for t in tables:
        fw[t["framework"]] = fw.get(t["framework"], 0) + 1
    print(f"by framework: {dict(sorted(fw.items()))}")

    # parse a dimensioned table
    c01 = next(t for t in tables if t["code"] == "C01.00.01.01")
    p = parse_table(c01["path"])
    print(f"\nC01.00.01.01: axes={p['axes']} open={len(p['open_axes'])} datapoints={p['n_datapoints']}")
    for dp in p["datapoints"][:4]:
        print(f"  {dp['concept']}  dims={dp['dims']}")

    # benchmark: parse ALL tables
    t0 = time.time()
    total_dp = 0
    open_tables = 0
    for t in tables:
        try:
            r = parse_table(t["path"])
            total_dp += r["n_datapoints"]
            if r["open_axes"]:
                open_tables += 1
        except Exception as e:
            print(f"  ERR {t['code']}: {e}")
    dt = time.time() - t0
    print(f"\nparsed ALL {len(tables)} tables in {dt:.2f}s  "
          f"(total datapoints={total_dp}, tables with open axes={open_tables})")
