"""Member-hierarchy extractor (Phase-2 collapse-map component).

Parses every domain CALCULATION linkbase `dict/dom/<domain>/hier-cal.xml` (Eurofiling breakdown arcs) into
parent -> [(child, weight)] sum-trees, keyed by member local code (e.g. 'x309'). A `complete-breakdown`
parent equals Σ (weight·child) EXACTLY → usable for the marginal collapse; `partial-breakdown` is only a
lower bound (parent ≥ Σ children) → recorded but not treated as an exact identity. This is what the marginal
map needs: which fine-grain members sum into a reported total member. (hier-def.xml = plain domain-member
containment with no weights; hier-pre.xml = presentation order — neither is the aggregation source.)

Public API:
  load_hierarchies(ext_dir) -> {domain: {parent_code: {"complete": bool, "children": [(code, weight), ...]}}}
  descendants(tree, code)   -> set of leaf-descendant codes of `code` (code itself if it's a leaf)
"""
from __future__ import annotations
import os, glob
from lxml import etree

XLINK = "http://www.w3.org/1999/xlink"
LB = "http://www.xbrl.org/2003/linkbase"
BREAKDOWN = {
    "http://www.eurofiling.info/xbrl/arcrole/complete-breakdown": "complete",
    "http://www.eurofiling.info/xbrl/arcrole/partial-breakdown": "partial",
    "http://www.eurofiling.info/xbrl/arcrole/superset-breakdown": "superset",
}


def _member_code(href: str) -> str | None:
    """`.../eba_MC.xsd#eba_MC_x309` or `#x309` -> 'x309' (trailing code of the element id)."""
    if not href or "#" not in href:
        return None
    return href.split("#", 1)[1].split("_")[-1]


def _parse_one(path: str) -> dict:
    """One hier-cal.xml -> {parent_code: {"complete": bool, "children": [(child_code, weight), ...]}}.
    Unions all calculationLink roles; a parent flagged complete iff ANY of its arcs is complete-breakdown."""
    try:
        root = etree.parse(path).getroot()
    except (OSError, etree.XMLSyntaxError):
        return {}
    tree: dict = {}
    for link in root.iter(f"{{{LB}}}calculationLink"):
        label_to_code = {}
        for loc in link.iter(f"{{{LB}}}loc"):
            lab = loc.get(f"{{{XLINK}}}label"); code = _member_code(loc.get(f"{{{XLINK}}}href"))
            if lab and code:
                label_to_code[lab] = code
        for arc in link.iter(f"{{{LB}}}calculationArc"):
            kind = BREAKDOWN.get(arc.get(f"{{{XLINK}}}arcrole"))
            if not kind:
                continue
            pc = label_to_code.get(arc.get(f"{{{XLINK}}}from"))
            cc = label_to_code.get(arc.get(f"{{{XLINK}}}to"))
            if not (pc and cc) or pc == cc:
                continue
            try:
                w = float(arc.get("weight", "1"))
            except ValueError:
                w = 1.0
            node = tree.setdefault(pc, {"complete": False, "children": []})
            node["children"].append((cc, w))
            if kind == "complete":
                node["complete"] = True
    return tree


def load_hierarchies(ext_dir: str) -> dict:
    """{domain: {parent_code: {"complete", "children"}}} over all dict/dom/*/hier-cal.xml (EBA + BoE)."""
    out = {}
    for f in glob.glob(os.path.join(ext_dir, "**", "dict", "dom", "*", "hier-cal.xml"), recursive=True):
        dom = os.path.basename(os.path.dirname(f))          # e.g. 'mc' or 'eba_mc'
        tree = _parse_one(f)
        if not tree:
            continue
        # union EBA + BoE copies of the same domain
        merged = out.setdefault(dom.replace("eba_", ""), {})
        for p, node in tree.items():
            m = merged.setdefault(p, {"complete": False, "children": []})
            have = set(m["children"])
            m["children"].extend(c for c in node["children"] if c not in have)   # dedup EBA+BoE overlap
            m["complete"] = m["complete"] or node["complete"]
    return out


def descendants(tree: dict, code: str) -> set:
    """Leaf descendants of `code` in one domain's tree (code itself if it has no children)."""
    if code not in tree:
        return {code}
    out = set(); stack = [c for c, _ in tree[code]["children"]]
    while stack:
        c = stack.pop()
        if c in tree:
            stack.extend(ch for ch, _ in tree[c]["children"])
        else:
            out.add(c)
    return out or {code}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    EXT = ("studio/backend/.cache/packages/"
           "50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181/Banking_4.0.0")
    H = load_hierarchies(EXT)
    print(f"domains with a hierarchy: {len(H)}")
    ncomplete = sum(1 for t in H.values() for n in t.values() if n["complete"])
    print(f"total members: {sum(len(t) for t in H.values())}  (complete-breakdown totals: {ncomplete})")
    mc = H.get("mc", {})
    print(f"\nMC domain: {len(mc)} parent/total members")
    for code in ("x309", "x311", "x100", "x310"):
        n = mc.get(code)
        if n:
            print(f"  {code}: complete={n['complete']} children={n['children']}  leaves={sorted(descendants(mc, code))}")
        else:
            print(f"  {code}: (leaf — not a total)")
