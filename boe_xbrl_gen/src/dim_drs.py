"""Offline XBRL-Dimensions validity from a table's definition linkbase (`<table>-def.xml`).

This replaces the slow Arelle round-trip used to learn a table's valid dimensional cells
(`hypercube_store` was building the full cartesian, emitting an instance and letting Arelle flag
`xbrldie:PrimaryItemDimensionallyInvalid` — ~46 min for PRA001). The valid-cell information is
fully present in the definition linkbase, so we resolve the dimensional relationship set (DRS)
directly and decide validity in-process (seconds).

Model (verified for BoE/EBA banking v4.0.0): every table cell is a **closed positive hypercube**
(`xbrldt:closed="true"`, `contextElement="scenario"`; no `notAll`). Each extended-link role with
an `all` arc pins, for that cell region:
  * a primary-item domain  — the `all` arc source plus its `domain-member` descendants (metrics);
  * one hypercube `model:hyp` whose `hypercube-dimension` arcs list the dimensions, each resolving
    to a domain (`dimension-domain`) and its usable members (`domain-member`).
Member subtrees are shared across roles via `xbrldt:targetRole`, so a dimension's members may be
defined in a *different* role than the one that references it (those fragment roles carry no
`all` arc).

A fact `(metric, {dim: member})` is dimensionally valid iff some hypercube role admits the metric
as a primary AND, for every dimension, the fact's member — or the dimension's default member when
the dimension is absent — lies in that role's allowed member set, with no dimension outside the
hypercube (closed). Typed dimensions (no `dimension-domain`, hence an empty allowed set) are
treated as wildcards so we never over-prune.
"""
from __future__ import annotations

import glob
import os

from lxml import etree

_LINK = "http://www.xbrl.org/2003/linkbase"
_XLINK = "http://www.w3.org/1999/xlink"
_XBRLDT = "http://xbrl.org/2005/xbrldt"
_ARC = "http://xbrl.org/int/dim/arcrole/"
_ALL = _ARC + "all"
_HC_DIM = _ARC + "hypercube-dimension"
_DIM_DOM = _ARC + "dimension-domain"
_DOM_MEM = _ARC + "domain-member"

# leading id tokens that mirror namespace prefixes (longest first so 'boe_eba_' wins over 'eba_').
_PREFIXES = ("boe_eba_", "eba_", "boe_")


def local(s: str | None) -> str | None:
    """Localname used for matching on BOTH sides — strips namespace prefix from a qname
    ('eba_dim:CQI' -> 'CQI', 'eba_CQ:x51' -> 'x51') or from a linkbase id ('eba_mi230' -> 'mi230',
    'boe_eba_x10023' -> 'x10023'). Mirrors `hypercube_store._cell_key`'s `loc()` for qnames and
    additionally peels id prefixes for `#fragment` ids."""
    if not s:
        return s
    s = s.rsplit("}", 1)[-1].split(":")[-1]   # qname/clark -> localname
    changed = True
    while changed:                            # linkbase id -> peel eba_/boe_/boe_eba_ prefixes
        changed = False
        for p in _PREFIXES:
            if s.startswith(p):
                s = s[len(p):]
                changed = True
                break
    return s


def qmem(qname: str | None) -> str | None:
    """Domain-qualified member localname: 'eba_CQ:x51' -> 'CQ:x51', 'eba_GA:x0' -> 'GA:x0',
    'boe_eba_CT:x10023' -> 'CT:x10023'. Member localnames like 'x0' collide across dozens of
    domains, so dimensional matching MUST qualify by domain — the member's qname prefix encodes it
    ('eba_<DOMAIN>' / 'boe_eba_<DOMAIN>'). Falls back to the bare localname when there is no prefix."""
    if not qname:
        return qname
    s = qname.rsplit("}", 1)[-1]
    if ":" in s:
        prefix, loc = s.split(":", 1)
        dom = local(prefix)
        return f"{dom}:{loc}" if dom else loc
    return local(s)


def localize_dims(dims: dict, defaults: dict | None = None) -> dict:
    """{dimQname: memQname} -> {dimLocal: 'DOMAIN:memLocal'}, dropping members equal to their
    default (build omits default members, so contexts/keys never carry them)."""
    defaults = defaults or {}
    out = {}
    for d, m in (dims or {}).items():
        if defaults.get(d) == m:
            continue
        out[local(d)] = qmem(m)
    return out


def localize_defaults(defaults: dict | None) -> dict:
    """{dimQname: memQname} dimension defaults -> {dimLocal: 'DOMAIN:memLocal'}."""
    return {local(d): qmem(m) for d, m in (defaults or {}).items()}


def _frag(href: str) -> str:
    return href.split("#", 1)[1] if "#" in href else href


def _cid_local(cid: str) -> str:
    """Localname of a concept id (full locator href). 'http://…/ga/mem.xsd#eba_x0' -> 'x0'."""
    return local(_frag(cid))


def _parse_def(path: str) -> dict:
    """Parse a `<table>-def.xml` into {roleURI: {all:[primaryCid], hd:{hypCid:[(dimCid,tr)]},
    dd:{dimCid:[(domainCid,tr)]}, dm:{parentCid:[(childCid,tr)]}}}.

    Concepts are keyed by their FULL locator href (`cid`), NOT localname: member localnames like
    'x0' / fragment ids like 'eba_x0' collide across every domain's `mem.xsd`, so a localname-keyed
    graph cross-contaminates closures (e.g. GA's domain wrongly absorbing EC's 'x0'). The full href
    is unique; localnames are derived only when emitting the allowed-member sets."""
    root = etree.parse(path).getroot()
    roles: dict = {}
    for dl in root.iter(f"{{{_LINK}}}definitionLink"):
        role = dl.get(f"{{{_XLINK}}}role")
        loc: dict = {}  # xlink:label -> concept id (full href, unique)
        for el in dl:
            if etree.QName(el).localname == "loc":
                loc[el.get(f"{{{_XLINK}}}label")] = el.get(f"{{{_XLINK}}}href", "")
        R = roles.setdefault(role, {"all": [], "hd": {}, "dd": {}, "dm": {}})
        for el in dl:
            if etree.QName(el).localname != "definitionArc":
                continue
            arc = el.get(f"{{{_XLINK}}}arcrole")
            frm = loc.get(el.get(f"{{{_XLINK}}}from"))
            to = loc.get(el.get(f"{{{_XLINK}}}to"))
            if frm is None or to is None:
                continue
            tr = el.get(f"{{{_XBRLDT}}}targetRole")
            if arc == _ALL:
                R["all"].append(frm)                       # frm = primary root, to = hyp
            elif arc == _HC_DIM:
                R["hd"].setdefault(frm, []).append((to, tr))   # frm = hyp, to = dimension
            elif arc == _DIM_DOM:
                R["dd"].setdefault(frm, []).append((to, tr))   # frm = dimension, to = domain
            elif arc == _DOM_MEM:
                R["dm"].setdefault(frm, []).append((to, tr))   # frm = parent, to = child member
    return roles


def _members(roles: dict, start: str, start_role: str) -> set:
    """Usable members = `domain-member` descendants of `start` (the domain head itself is not a
    usable member), following `targetRole` across roles. Cycle-safe on (concept, role)."""
    out: set = set()
    seen: set = set()
    stack = [(start, start_role)]
    while stack:
        c, r = stack.pop()
        for child, tr in roles.get(r, {}).get("dm", {}).get(c, []):
            nr = tr or r
            if (child, nr) in seen:
                continue
            seen.add((child, nr))
            out.add(child)
            stack.append((child, nr))
    return out


class TableDRS:
    """Dimensional-validity oracle for one table, built from its `<table>-def.xml`."""

    def __init__(self, def_path: str):
        self.roles = _parse_def(def_path)
        self.specs: list[dict] = []           # [{primaries:set, dims:{dimLocal: allowedMembers}}]
        for role, R in self.roles.items():
            if not R["all"]:
                continue                       # fragment role (targetRole target) — no hypercube
            primaries: set = set()
            for rootc in R["all"]:                          # metric localnames (unique, no collision)
                primaries.add(_cid_local(rootc))
                primaries |= {_cid_local(c) for c in _members(self.roles, rootc, role)}
            dims: dict = {}
            for _hyp, arcs in R["hd"].items():
                for dim, tr in arcs:
                    search = tr or role
                    members: set = set()
                    for domain, dd_tr in self.roles.get(search, {}).get("dd", {}).get(dim, []):
                        # qualify each member by its domain root so 'GA:x0' != 'CQ:x0' (member
                        # localnames collide across domains). The instance side is qualified the
                        # same way via `qmem`, so the default-member check is collision-safe.
                        dom = _cid_local(domain)
                        members |= {f"{dom}:{_cid_local(m)}"
                                    for m in _members(self.roles, domain, dd_tr or search)}
                    dims[_cid_local(dim)] = members
            self.specs.append({"primaries": primaries, "dims": dims})
        self.by_primary: dict = {}
        for s in self.specs:
            for p in s["primaries"]:
                self.by_primary.setdefault(p, []).append(s)

    @staticmethod
    def _fits(spec: dict, dims_local: dict, defaults_local: dict) -> bool:
        hyp = spec["dims"]
        for d, m in dims_local.items():
            allowed = hyp.get(d)
            if allowed is None:
                return False                    # closed: dimension not in this hypercube
            if allowed and m not in allowed:
                return False                    # explicit member not admitted (empty=typed: skip)
        for d, allowed in hyp.items():
            if d in dims_local:
                continue                        # present (checked above)
            if not allowed:
                return False                    # typed dim: no default, required by closed hypercube
            if defaults_local.get(d) not in allowed:
                return False                    # absent explicit dim must fall back to an admitted default
        return True

    def is_valid(self, concept_local: str, dims_local: dict, defaults_local: dict) -> bool:
        cands = self.by_primary.get(concept_local)
        if not cands:
            return False                        # metric is no hypercube's primary in this table
        return any(self._fits(s, dims_local, defaults_local) for s in cands)


def def_path_for(extracted_dir: str, table_code: str) -> str | None:
    """Locate `<table>-def.xml` for a table code (e.g. 'C13.01.01.01') in an extracted package."""
    stem = table_code.lower()
    hits = glob.glob(os.path.join(extracted_dir, "**", stem, f"{stem}-def.xml"), recursive=True)
    if not hits:
        hits = glob.glob(os.path.join(extracted_dir, "**", f"{stem}-def.xml"), recursive=True)
    return hits[0] if hits else None
