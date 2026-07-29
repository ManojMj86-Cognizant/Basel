"""
Instance model: parse a BoE XBRL instance into facts + contexts with QNames in
Clark notation ('{ns}local') so they match the (prefix-independent) rule selectors.
Keeps the live lxml element on each fact so the solver can rewrite values in place.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from lxml import etree

XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
FIND = "http://www.eurofiling.info/xbrl/ext/filing-indicators"
XSI = "http://www.w3.org/2001/XMLSchema-instance"


def _resolve_qname(text, nsmap):
    text = (text or "").strip()
    if not text:
        return text
    if ":" in text:
        prefix, local = text.split(":", 1)
    else:
        prefix, local = None, text
    ns = nsmap.get(prefix)
    return f"{{{ns}}}{local}" if ns else text


@dataclass
class Fact:
    concept: str                       # clark qname
    ctxref: str
    dims: dict = field(default_factory=dict)     # dim clark -> member clark (explicit)
    typed: dict = field(default_factory=dict)    # dim clark -> typed value text
    unit: str | None = None
    decimals: str | None = None
    el: object = None

    @property
    def value(self):
        return (self.el.text or "").strip() if self.el is not None else None

    @value.setter
    def value(self, v):
        self.el.text = str(v)


class Instance:
    def __init__(self, path):
        parser = etree.XMLParser(remove_blank_text=False, remove_comments=False)
        self.tree = etree.parse(path, parser)
        self.root = self.tree.getroot()
        self.path = path
        self.contexts = {}     # id -> {"dims": {...}, "typed": {...}, "period": str}
        self.facts = []
        self.by_concept = defaultdict(list)   # concept clark -> [Fact]  (scale index)
        self._parse()

    def _parse(self):
        # contexts
        for ctx in self.root.iter(f"{{{XBRLI}}}context"):
            cid = ctx.get("id")
            dims, typed = {}, {}
            for em in ctx.iter(f"{{{XBRLDI}}}explicitMember"):
                d = _resolve_qname(em.get("dimension"), em.nsmap)
                m = _resolve_qname(em.text, em.nsmap)
                dims[d] = m
            for tm in ctx.iter(f"{{{XBRLDI}}}typedMember"):
                d = _resolve_qname(tm.get("dimension"), tm.nsmap)
                # typed value = text of the single child element
                child = next((c for c in tm), None)
                typed[d] = (child.text if child is not None else None)
            period = None
            inst = ctx.find(f"{{{XBRLI}}}period/{{{XBRLI}}}instant")
            if inst is not None:
                period = inst.text
            self.contexts[cid] = {"dims": dims, "typed": typed, "period": period}

        # facts: elements with contextRef that are not filing indicators
        for el in self.root.iter():
            if el.get("contextRef") is None:
                continue
            if etree.QName(el).namespace == FIND:
                continue
            q = etree.QName(el)
            concept = f"{{{q.namespace}}}{q.localname}"
            ctxref = el.get("contextRef")
            ctx = self.contexts.get(ctxref, {"dims": {}, "typed": {}})
            fact = Fact(
                concept=concept, ctxref=ctxref,
                dims=dict(ctx["dims"]), typed=dict(ctx["typed"]),
                unit=el.get("unitRef"), decimals=el.get("decimals"), el=el,
            )
            self.facts.append(fact)
            self.by_concept[concept].append(fact)

    def remove_fact(self, fact):
        """Delete a fact element from the document and the indices (used to satisfy
        existence rules of the form empty($v) — the cell must not be reported)."""
        el = fact.el
        if el is not None:
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
            fact.el = None
        try:
            self.facts.remove(fact)
        except ValueError:
            pass
        lst = self.by_concept.get(fact.concept)
        if lst:
            try:
                lst.remove(fact)
            except ValueError:
                pass

    def write(self, out_path):
        from pathlib import Path
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        xml_bytes = etree.tostring(self.tree, xml_declaration=True, encoding="utf-8")
        with open(out_path, "wb") as fh:
            fh.write(b"\xef\xbb\xbf")
            fh.write(xml_bytes)
