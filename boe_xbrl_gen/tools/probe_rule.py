"""For a given additive rule, evaluate it on v2 EXACTLY as our classifier/solver does (rc-code bridge →
concept+dims → fact value) and print LHS/RHS/tol/verdict, so we can compare against TDG's reported values.
If our resolved values differ from TDG's 'reported as' numbers, the rc-code bridge maps these cells to
different facts than TDG's formula — explaining why our offline check says pass while TDG says fail."""
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
CODES = sys.argv[1:] or ["v0226_m", "boe_b0826", "v0627_m", "v4160_m"]

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
facts = {}; decs = {}
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    k = (dim_drs.local(etree.QName(el).localname), frozenset(cd.get(cr, {}).items()))
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


def fkey(dp):
    return (dim_drs.local(dp["concept"]),
            frozenset((dim_drs.local(k), dim_drs.local(v)) for k, v in dp["dims"].items()))


def hu(k):
    d = decs.get(k)
    return 0.5 * (10.0 ** (-d)) if d is not None else 0.5


for code in CODES:
    r = next((x for x in rules if x["code"] == code), None)
    if not r:
        print(f"\n{code}: NOT FOUND"); continue
    print(f"\n===== {code}  tables={r['tables']}")
    asts = workbook_rules.expand_scoped_asts(r)
    print(f"  {len(asts)} concrete equation instance(s)")
    for a in asts[:4]:
        lhs = rhs = 0.0; tol = 0.0; nfac = nabs = 0; parts = []
        for side, sgn in (("lhs", 1.0), ("rhs", -1.0)):
            for t in a[side]:
                for dp in res.resolve(t["cell"]):
                    k = fkey(dp)
                    v = facts.get(k)
                    if v is None:
                        nabs += 1; v = 0.0; parts.append(f"{side}:{k[0]}=ABSENT*{t['coef']}")
                    else:
                        nfac += 1; tol += abs(t["coef"]) * hu(k)
                        parts.append(f"{side}:{k[0]}={v:.0f}*{t['coef']}")
                    if side == "lhs":
                        lhs += v * t["coef"]
                    else:
                        rhs += v * t["coef"]
        verdict = "PASS" if abs(lhs - rhs) <= max(tol, 0.5) else "FAIL"
        print(f"    LHS={lhs:.0f} RHS={rhs:.0f} diff={abs(lhs-rhs):.0f} tol={tol:.0f} "
              f"facts={nfac} absent={nabs} -> {verdict}")
        print(f"       {parts}")
