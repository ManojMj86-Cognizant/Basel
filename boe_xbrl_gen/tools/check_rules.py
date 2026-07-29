"""Evaluate specific workbook rules (by code) against the current generated instance."""
import sys, json
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
OUT = f"{BASE}/solved/_genvalid_pra001.xbrl"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
X = "http://www.xbrl.org/2003/instance"
CODES = [c for c in sys.argv[1:]] or ["b0745", "b0778"]

tables = set(json.load(open(f"{BASE}/generated/result.json", encoding="utf-8"))["instances"][0]["tables"])


def fkey(concept, dims):
    return (dim_drs.local(concept), frozenset((dim_drs.local(k), dim_drs.local(v)) for k, v in dims.items()))


data = open(OUT, "rb").read(); data = data[3:] if data[:3] == b"\xef\xbb\xbf" else data
root = etree.fromstring(data); cd = {}
for ctx in root.findall(f"{{{X}}}context"):
    dd = {}; sc = ctx.find(f"{{{X}}}scenario")
    if sc is not None:
        for em in sc:
            if em.get("dimension") and etree.QName(em).localname == "explicitMember":
                dd[dim_drs.local(em.get("dimension"))] = dim_drs.local((em.text or "").strip())
    cd[ctx.get("id")] = dd
facts = {}
for el in root:
    cref = el.get("contextRef")
    if cref is None:
        continue
    try:
        v = float((el.text or "").strip())
    except ValueError:
        continue
    facts[(dim_drs.local(etree.QName(el).localname), frozenset(cd.get(cref, {}).items()))] = v

rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
res = workbook_rules.CellResolver(EXT)
by_code = {r["code"]: r for r in rules}


def val(dp):
    return facts.get(fkey(dp["concept"], dp["dims"]))


for code in CODES:
    r = by_code.get(code)
    print("=" * 80)
    if not r:
        print(f"{code}: NOT FOUND in workbook")
        continue
    print(f"{code}  tables={r['tables']}  include={r['include']}  deactivated={r['deactivated']}")
    print(f"  expression: {(r['expression'] or '')[:300]}")
    print(f"  scope: {(r['scope'] or '')[:160]}")
    print(f"  precondition: {(r['precondition'] or '')[:160]}")
    in_scope = bool(r["tables"]) and set(r["tables"]) <= tables and not r["deactivated"]
    print(f"  tables in generated module? {in_scope}")
    asts = workbook_rules.expand_scoped_asts(r)
    if not asts:
        print("  -> NOT parseable as additive (conditional/non-linear/unscoped) — not evaluated here")
        continue
    bal = unbal = incomp = 0
    examples = []
    for a in asts:
        op = a["op"]
        lhs_dps = [(dp, t["coef"]) for t in a["lhs"] for dp in res.resolve(t["cell"])]
        rhs_dps = [(dp, t["coef"]) for t in a["rhs"] for dp in res.resolve(t["cell"])]
        miss = any(val(dp) is None for dp, _ in lhs_dps + rhs_dps)
        if miss:
            incomp += 1
            if len(examples) < 4:
                missing = [(dp["concept"], dp["dims"]) for dp, _ in lhs_dps + rhs_dps if val(dp) is None]
                examples.append(("INCOMPLETE", missing[:2]))
            continue
        lhs = sum((val(dp) or 0) * c for dp, c in lhs_dps)
        rhs = sum((val(dp) or 0) * c for dp, c in rhs_dps)
        ok = (abs(lhs - rhs) < 0.5) if op == "i=" else (
            lhs <= rhs + 0.5 if op == "i<=" else lhs >= rhs - 0.5 if op == "i>=" else None)
        if ok:
            bal += 1
        else:
            unbal += 1
            if len(examples) < 4:
                examples.append((f"FAIL {op}", f"lhs={lhs:.1f} rhs={rhs:.1f}"))
    print(f"  equations: {len(asts)}  satisfied={bal}  FAILED={unbal}  incomplete(missing cell)={incomp}")
    for tag, d in examples:
        print(f"      {tag}: {d}")
