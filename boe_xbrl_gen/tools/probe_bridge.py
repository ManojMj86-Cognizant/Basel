"""Investigate the two offline-tooling bugs:
 (1) show raw expressions of v0226_m / boe_b0826 (coefficient-before-sum parse bug);
 (2) for the cells our bridge resolved to ABSENT (C04 r0131 c0010; OF22 r0050 c0090), print what our
     rc-code bridge maps them to (concept+dims) and search v2 for the fact TDG reported (556000 / 548800)
     to see its ACTUAL concept+dims — the mismatch is the bridge gap."""
import sys
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
V2 = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v2.xbrl"
X = "http://www.xbrl.org/2003/instance"

raw = open(V2, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
root = etree.fromstring(raw); cd = {}
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
    cd[c.get("id")] = dd
byval = []          # (concept-local, dims-dict, value)
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    try:
        v = float((el.text or "").strip())
    except (ValueError, TypeError):
        continue
    byval.append((dim_drs.local(etree.QName(el).localname), cd.get(cr, {}), v))

rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
for code in ("v0226_m", "boe_b0826"):
    r = next(x for x in rules if x["code"] == code)
    print(f"\n===== {code} RAW EXPRESSION =====")
    print(" ", r["expression"])
    pe = workbook_rules.parse_expression(r["expression"])
    if pe:
        for side in ("lhs", "rhs"):
            for t in pe[side]:
                print(f"    {side}: coef={t['coef']} sum={t['cell'].get('sum')} "
                      f"r={t['cell'].get('r')} c={t['cell'].get('c')}")

res = workbook_rules.CellResolver(EXT)
print("\n\n===== BRIDGE resolution of the 'absent' cells =====")
for tbl, rr, cc, tdgval in (("C04.00.01.01", "0131", "0010", 556000),
                            ("C04.00.01.01", "0120", "0010", 9335000),
                            ("OF22.00.01.01", "0050", "0090", 548800)):
    dps = res.resolve({"table": tbl, "r": rr, "c": cc, "z": []})
    print(f"\n  {tbl} r{rr} c{cc}: bridge -> {[(dim_drs.local(d['concept']), {dim_drs.local(k):dim_drs.local(v) for k,v in d['dims'].items()}) for d in dps]}")
    hits = [(cl, dd, v) for cl, dd, v in byval if abs(v - tdgval) < 0.5]
    print(f"    facts in v2 with value {tdgval}: {len(hits)}")
    for cl, dd, v in hits[:3]:
        print(f"       {cl}  dims={ {dim_drs.local(k): dim_drs.local(x) for k,x in dd.items()} }")
