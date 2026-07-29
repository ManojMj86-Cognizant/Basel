"""Scope the OF08 cross-table cluster on v3: for representative rules of each family, resolve the TARGET
(aggregate) cell and the SOURCE cells and report whether each is PRESENT (editable) or ABSENT (must be
generated). This decides whether a surgical edit-only aggregation pass can fix them or we need to add facts.
Uses the SAME keying as the (fixed) solver: default members dropped."""
import sys, json, os
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
V3 = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v3.xbrl"
X = "http://www.xbrl.org/2003/instance"
CODES = sys.argv[1:] or ["boe_b1068", "boe_b0872", "boe_b0276", "boe_b0304", "boe_b0735", "boe_b0816"]

mp = os.path.join(BASE, "model.merged.json")
if not os.path.exists(mp):
    mp = os.path.join(BASE, "model.json")
DEF = {}
for d, m in dim_drs.localize_defaults(json.load(open(mp, encoding="utf-8")).get("dim_defaults", {})).items():
    DEF[d] = dim_drs.local(m)


def dimset(items):
    return frozenset((k, v) for k, v in items if DEF.get(k) != v)


raw = open(V3, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
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
facts = {}
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    try:
        facts[(dim_drs.local(etree.QName(el).localname), dimset(ctx.get(cr, {}).items()))] = float((el.text or "").strip())
    except (ValueError, TypeError):
        pass

rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
res = workbook_rules.CellResolver(EXT)


def fk(dp):
    return (dim_drs.local(dp["concept"]), dimset((dim_drs.local(k), dim_drs.local(v)) for k, v in dp["dims"].items()))


for code in CODES:
    r = next((x for x in rules if x["code"] == code), None)
    if not r:
        print(f"\n{code}: NOT FOUND"); continue
    print(f"\n===== {code}  tables={r['tables']}")
    print(f"  {r['expression'][:150]}")
    for a in workbook_rules.expand_scoped_asts(r)[:1]:
        for side, lbl in (("lhs", "TARGET/LHS"), ("rhs", "SOURCE/RHS")):
            for t in a[side]:
                for dp in res.resolve(t["cell"]):
                    k = fk(dp)
                    v = facts.get(k)
                    tag = f"={v:.0f}" if v is not None else "ABSENT"
                    print(f"    [{lbl}] {k[0]} coef={t['coef']} {sorted(dict(k[1]).items())[:3]} -> {tag}")
