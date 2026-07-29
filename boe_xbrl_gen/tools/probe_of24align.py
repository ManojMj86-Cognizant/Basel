"""Decide whether the b0365/b0366 XPTY errors are OUR data or the taxonomy: for OF24.02.01.01, compare
(v2 vs official sample) the open-dim signatures where the TARGET cell c0010/c0050 (mi184) is present but
a required SUMMAND cell (mi10032/mi10033/mi10034) is ABSENT — 'orphan targets' that make the custom
numeric functions atomize an absent operand → XPTY string error. If the sample has 0 orphans and we have
some, it's our over-reporting; if both have them, it's a taxonomy/tool issue."""
import sys
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs
from collections import defaultdict

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
V2 = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v2.xbrl"
SAMPLE = ("../boebankingtaxonomysampleinstancesv400/"
          "ABCDEFGHIJ0123456789_GB_banking_PRA001_2026-02-28_20260220142410000.xbrl")
X = "http://www.xbrl.org/2003/instance"


def load(path):
    raw = open(path, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
    root = etree.fromstring(raw); ctx = {}
    for c in root.findall(f"{{{X}}}context"):
        dd = {}; sc = c.find(f"{{{X}}}scenario")
        if sc is not None:
            for em in sc:
                if not em.get("dimension"):
                    continue
                ln = etree.QName(em).localname
                if ln == "explicitMember":
                    dd[dim_drs.local(em.get("dimension"))] = dim_drs.local((em.text or "").strip())
                elif ln == "typedMember":
                    dd[dim_drs.local(em.get("dimension"))] = "typed:" + "".join(em.itertext()).strip()
        ctx[c.get("id")] = dd
    byc = defaultdict(list)
    for el in root:
        if el.get("contextRef") is None:
            continue
        byc[dim_drs.local(etree.QName(el).localname)].append(ctx.get(el.get("contextRef"), {}))
    return byc


res = workbook_rules.CellResolver(EXT)
rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")


def cell_closed(table, r, c):
    dps = res.resolve({"table": table, "r": r, "c": c, "z": []})
    if not dps:
        return None
    dp = dps[0]
    return dim_drs.local(dp["concept"]), {dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}


for code, tgt_rc, summ_rc in (("boe_b0365", ("0010", "0010"),
                               [("0010", "0020"), ("0010", "0030"), ("0030", "0040"), ("0040", "0040")]),
                              ("boe_b0366", ("0010", "0050"),
                               [("0010", "0060"), ("0010", "0070"), ("0030", "0080"), ("0040", "0080")])):
    T = "OF24.02.01.01"
    tgt = cell_closed(T, *tgt_rc)
    summs = [cell_closed(T, r, c) for r, c in summ_rc]
    pinned = set(tgt[1])
    for s in summs:
        if s:
            pinned |= set(s[1])

    def sigs(byc, cc):
        out = set()
        concept, cd = cc
        for dims in byc.get(concept, []):
            if all(dims.get(k) == v for k, v in cd.items()):
                out.add(tuple(sorted((k, v) for k, v in dims.items() if k not in pinned)))
        return out

    print(f"\n===== {code}  ({T})  pinned={sorted(pinned)}")
    for label, path in (("v2", V2), ("sample", SAMPLE)):
        try:
            byc = load(path)
        except Exception as e:
            print(f"  {label}: load failed {e}"); continue
        tsig = sigs(byc, tgt)
        ssig = [sigs(byc, s) if s else set() for s in summs]
        # orphan = target signature with NO summand present at all
        anysum = set().union(*ssig) if ssig else set()
        orphans = tsig - anysum
        print(f"  {label:6s}: target(c{tgt_rc[1]}) sigs={len(tsig)}  "
              f"any-summand sigs={len(anysum)}  ORPHAN targets(no summand)={len(orphans)}")
