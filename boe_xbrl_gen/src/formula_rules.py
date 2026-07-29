"""
Formula-linkbase parser for the BoE/EBA banking taxonomy validation rules.

Parses XBRL Formula `va:valueAssertion` linkbases (the val/vr-*.xml files Arelle
evaluates) into structured Rule objects the solver can reason about:

  Rule:
    id            assertion id (e.g. "boe_boe_b0013_ss")
    severity      ERROR | WARNING | ... (from assertion-unsatisfied-severity arc)
    test          raw XPath test string
    common        Selector applied to every variable (variable-set filters)
    variables     {name: Variable}      keyed by the @name on the variable-set arc
  Variable:
    name          e.g. "v0"
    fallback      fallbackValue attr (e.g. "0", "()", None)
    sequence      bindAsSequence == "true"
    selector      Selector (this variable's own filters, ANDed with `common`)
  Selector:
    concepts      set of concept qnames (empty = any)
    dims          {dimension_qname: set(member_qnames)}   explicit dimension constraints
    typed         {dimension_qname: None}                  typed dimension presence
    complex       True if an or/general/aspect filter was seen (selector is approximate)

Filter members within one explicitDimension filter are OR (fact matches if its member
for that dimension is any listed). Multiple filters AND together. andFilter children are
flattened; orFilter / general / aspectCover mark the selector `complex` (handled best-effort).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

# arcroles
AR_VAR_SET = "http://xbrl.org/arcrole/2008/variable-set"
AR_VAR_FILTER = "http://xbrl.org/arcrole/2008/variable-filter"
AR_VARSET_FILTER = "http://xbrl.org/arcrole/2008/variable-set-filter"
AR_BOOL_FILTER = "http://xbrl.org/arcrole/2008/boolean-filter"
AR_SEVERITY = "http://xbrl.org/arcrole/2016/assertion-unsatisfied-severity"

# filter namespaces
NS_DF = "http://xbrl.org/2008/filter/dimension"
NS_CF = "http://xbrl.org/2008/filter/concept"
NS_BF = "http://xbrl.org/2008/filter/boolean"
XLINK = "http://www.w3.org/1999/xlink"


@dataclass
class Selector:
    concepts: set = field(default_factory=set)
    dims: dict = field(default_factory=dict)        # dim_qname -> set(member_qnames)
    typed: dict = field(default_factory=dict)       # dim_qname -> None
    complex: bool = False

    def merged(self, other: "Selector") -> "Selector":
        s = Selector(set(self.concepts), {k: set(v) for k, v in self.dims.items()},
                     dict(self.typed), self.complex or other.complex)
        s.concepts |= other.concepts
        for d, m in other.dims.items():
            s.dims[d] = (s.dims.get(d, set()) | set(m)) if d in s.dims else set(m)
        s.typed.update(other.typed)
        return s


@dataclass
class Variable:
    name: str
    fallback: str | None = None
    sequence: bool = False
    selector: Selector = field(default_factory=Selector)


@dataclass
class Rule:
    id: str
    test: str | None
    severity: str = "ERROR"
    common: Selector = field(default_factory=Selector)
    variables: dict = field(default_factory=dict)
    source: str = ""


def _local(el):
    return etree.QName(el).localname


def _qtext(el):
    """Resolve a df:qname / cf:qname child to Clark notation '{ns}local'
    using the element's own namespace map (prefix-independent matching)."""
    raw = (el.text or "").strip()
    if not raw:
        return raw
    if ":" in raw:
        prefix, local = raw.split(":", 1)
    else:
        prefix, local = None, raw
    ns = el.nsmap.get(prefix)
    return f"{{{ns}}}{local}" if ns else raw


def _parse_filter(res, label_index, seen=None):
    """Turn a filter resource into a Selector. Recurses into boolean filters."""
    if seen is None:
        seen = set()
    sel = Selector()
    ns = etree.QName(res).namespace
    ln = _local(res)

    if ns == NS_DF and ln == "explicitDimension":
        dim = None
        members = set()
        for child in res:
            cln = _local(child)
            if cln == "dimension":
                q = child.find(f"{{{NS_DF}}}qname")
                if q is not None:
                    dim = _qtext(q)
            elif cln == "member":
                q = child.find(f"{{{NS_DF}}}qname")
                if q is not None:
                    members.add(_qtext(q))
        if dim:
            sel.dims[dim] = members
    elif ns == NS_DF and ln == "typedDimension":
        q = res.find(f"{{{NS_DF}}}dimension/{{{NS_DF}}}qname")
        if q is not None:
            sel.typed[_qtext(q)] = None
    elif ns == NS_CF and ln == "conceptName":
        for q in res.iter(f"{{{NS_CF}}}qname"):
            sel.concepts.add(_qtext(q))
    elif ns == NS_BF and ln == "andFilter":
        # children linked via boolean-filter arcs from this resource's label
        my = res.get(f"{{{XLINK}}}label")
        for child in _arc_targets(label_index, my, AR_BOOL_FILTER):
            if id(child) in seen:
                continue
            seen.add(id(child))
            sel = sel.merged(_parse_filter(child, label_index, seen))
    elif ns == NS_BF and ln == "orFilter":
        sel.complex = True
        my = res.get(f"{{{XLINK}}}label")
        for child in _arc_targets(label_index, my, AR_BOOL_FILTER):
            if id(child) in seen:
                continue
            seen.add(id(child))
            # union members best-effort
            sel = sel.merged(_parse_filter(child, label_index, seen))
    else:
        # general / aspectCover / match / unknown -> approximate
        sel.complex = True
    return sel


def _arcs_from(label_index, from_label, arcrole):
    # O(1) lookup via the (from_label, arcrole) index built in parse_file.
    return label_index["arc_index"].get((from_label, arcrole), ())


def _arc_targets(label_index, from_label, arcrole):
    """Return resources that are `to` of arcs with given arcrole from `from_label`."""
    out = []
    res = label_index["res"]
    for arc in _arcs_from(label_index, from_label, arcrole):
        for r in res.get(arc.get(f"{{{XLINK}}}to"), ()):
            out.append(r)
    return out


def parse_file(path) -> list[Rule]:
    tree = etree.parse(str(path))
    root = tree.getroot()

    # index resources by xlink:label and arcs by (from_label, arcrole) for O(1) lookup
    # (critical: some rule files are ~40MB with thousands of arcs -> avoid O(arcs) scans).
    res_by_label = {}
    arc_index = {}
    assertions = []
    a_from = f"{{{XLINK}}}from"
    a_role = f"{{{XLINK}}}arcrole"
    a_type = f"{{{XLINK}}}type"
    a_label = f"{{{XLINK}}}label"
    for el in root.iter():
        typ = el.get(a_type)
        if typ == "resource":
            lbl = el.get(a_label)
            res_by_label.setdefault(lbl, []).append(el)
            if _local(el) == "valueAssertion":
                assertions.append(el)
        elif typ == "arc":
            arc_index.setdefault((el.get(a_from), el.get(a_role)), []).append(el)
        elif typ == "locator":
            lbl = el.get(a_label)
            res_by_label.setdefault(lbl, []).append(el)
    idx = {"res": res_by_label, "arc_index": arc_index}

    rules = []
    for a in assertions:
        aid = a.get(f"{{{XLINK}}}label")
        rule = Rule(id=a.get("id") or aid, test=a.get("test"), source=Path(path).name)

        # severity (locator target href ends with #ERROR etc.)
        for arc in _arcs_from(idx, aid, AR_SEVERITY):
            to = arc.get(f"{{{XLINK}}}to")
            for loc in res_by_label.get(to, []):
                href = loc.get(f"{{{XLINK}}}href", "")
                if "#" in href:
                    rule.severity = href.split("#")[-1]

        # common (variable-set) filters
        for arc in _arcs_from(idx, aid, AR_VARSET_FILTER):
            to = arc.get(f"{{{XLINK}}}to")
            for r in res_by_label.get(to, []):
                rule.common = rule.common.merged(_parse_filter(r, idx))

        # variables
        for arc in _arcs_from(idx, aid, AR_VAR_SET):
            name = arc.get("name")
            to = arc.get(f"{{{XLINK}}}to")
            for fv in res_by_label.get(to, []):
                if _local(fv) != "factVariable":
                    continue
                var = Variable(
                    name=name,
                    fallback=fv.get("fallbackValue"),
                    sequence=(fv.get("bindAsSequence") == "true"),
                )
                fv_lbl = fv.get(f"{{{XLINK}}}label")
                for farc in _arcs_from(idx, fv_lbl, AR_VAR_FILTER):
                    fto = farc.get(f"{{{XLINK}}}to")
                    for r in res_by_label.get(fto, []):
                        var.selector = var.selector.merged(_parse_filter(r, idx))
                rule.variables[name] = var
        rules.append(rule)
    return rules


def _fmt_sel(s: Selector):
    parts = []
    if s.concepts:
        parts.append("concept=" + "|".join(sorted(s.concepts)))
    for d, m in sorted(s.dims.items()):
        parts.append(f"{d}={{{','.join(sorted(m))}}}")
    for d in sorted(s.typed):
        parts.append(f"{d}=<typed>")
    if s.complex:
        parts.append("(complex)")
    return "; ".join(parts) if parts else "(any)"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    path = sys.argv[1]
    rules = parse_file(path)
    for r in rules:
        print(f"RULE {r.id}  [{r.severity}]")
        print(f"  test: {r.test}")
        print(f"  common: {_fmt_sel(r.common)}")
        for name, v in r.variables.items():
            print(f"  ${name}  seq={v.sequence} fallback={v.fallback!r}: {_fmt_sel(v.selector)}")
        print()


if __name__ == "__main__":
    main()
