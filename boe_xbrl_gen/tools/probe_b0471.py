"""Why does TDG report 100+ b0471 failures on v4 while our classifier's L1 count is tiny? Evaluate b0471
on v4 with the SAME logic as the (fixed) classifier — default members dropped, coefficient parsing — and
print the raw expression, parsed coefficients, and per-instance LHS/RHS/tol/verdict counts."""
import sys, json, os
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
F = os.environ.get("PROBE_FILE", r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v4.xbrl")
X = "http://www.xbrl.org/2003/instance"
CODE = sys.argv[1] if len(sys.argv) > 1 else "boe_b0471"

mp = os.path.join(BASE, "model.merged.json")
if not os.path.exists(mp):
    mp = os.path.join(BASE, "model.json")
DEF = {}
for d, m in dim_drs.localize_defaults(json.load(open(mp, encoding="utf-8")).get("dim_defaults", {})).items():
    DEF[d] = dim_drs.local(m)


def dimset(items):
    return frozenset((k, v) for k, v in items if DEF.get(k) != v)


raw = open(F, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
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
facts = {}; decs = {}
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    k = (dim_drs.local(etree.QName(el).localname), dimset(ctx.get(cr, {}).items()))
    try:
        facts[k] = float((el.text or "").strip())
    except (ValueError, TypeError):
        continue
    try:
        decs[k] = int(el.get("decimals"))
    except (TypeError, ValueError):
        decs[k] = None

rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
res = workbook_rules.CellResolver(EXT)
r = next(x for x in rules if x["code"] == CODE)
print(f"=== {CODE}  tables={r['tables']}")
print("RAW:", r["expression"][:300])
pe = workbook_rules.parse_expression(r["expression"])
if pe:
    for side in ("lhs", "rhs"):
        for t in pe[side]:
            print(f"  parsed {side}: coef={t['coef']} sum={t['cell'].get('sum')} r={t['cell'].get('r')} c={t['cell'].get('c')}")


def fk(dp):
    return (dim_drs.local(dp["concept"]), dimset((dim_drs.local(k), dim_drs.local(v)) for k, v in dp["dims"].items()))


def hu(k):
    d = decs.get(k)
    return 0.5 * (10.0 ** (-d)) if d is not None else 0.5


asts = workbook_rules.expand_scoped_asts(r)
npass = nfail = nabsent_tgt = 0
examples = []
for a in asts:
    lhs = rhs = 0.0; tol = 0.0; tgt_absent = True
    for side, sgn in (("lhs", 1.0), ("rhs", -1.0)):
        for t in a[side]:
            for dp in res.resolve(t["cell"]):
                k = fk(dp); v = facts.get(k)
                if side == "lhs" and v is not None:
                    tgt_absent = False
                if v is None:
                    v = 0.0
                else:
                    tol += abs(t["coef"]) * hu(k)
                if side == "lhs":
                    lhs += v * t["coef"]
                else:
                    rhs += v * t["coef"]
    if tgt_absent:
        nabsent_tgt += 1
    if abs(lhs - rhs) > max(tol, 0.5):
        nfail += 1
        if len(examples) < 5:
            examples.append(f"{lhs:.0f} != {rhs:.0f} (tol {tol:.0f})")
    else:
        npass += 1
print(f"\ninstances={len(asts)}  PASS={npass}  FAIL={nfail}  (target cell absent in {nabsent_tgt})")
for e in examples:
    print("  fail e.g.", e)
