"""Did generating the 39 OF09.02 CEG=x1 cells (v7) ACTIVATE any OF09.02 single-table (internal) rules?
Evaluate every OF09.02-only additive + comparison rule with CEG=x1 forced onto each cell (our new cells
carry CEG=x1; the rc-code bridge omits it), TDG absent=0 + half-ULP tolerance. Run on a file; diff v6 vs v7.
Usage: python tools/check_of0902_internal.py <file.xbrl>"""
import sys, json, os
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules, formula_eval
from src import dim_drs

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
F = sys.argv[1]
X = "http://www.xbrl.org/2003/instance"
CEG = ("CEG", "x1")

DEF = {}
for d, m in dim_drs.localize_defaults(json.load(open(f"{BASE}/model.json", encoding="utf-8")).get("dim_defaults", {})).items():
    DEF[d] = dim_drs.local(m)


def dimset(items):
    return frozenset((k, v) for k, v in items if DEF.get(k) != v)


raw = open(F, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
root = etree.fromstring(raw); cd = {}
for c in root.findall(f"{{{X}}}context"):
    dd = {}; sc = c.find(f"{{{X}}}scenario")
    if sc is not None:
        for em in sc:
            if em.get("dimension") and etree.QName(em).localname == "explicitMember":
                dd[dim_drs.local(em.get("dimension"))] = dim_drs.local((em.text or "").strip())
    cd[c.get("id")] = dd
facts = {}; decs = {}
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    k = (dim_drs.local(etree.QName(el).localname), dimset(cd.get(cr, {}).items()))
    try:
        facts[k] = float((el.text or "").strip())
    except (ValueError, TypeError):
        continue
    decs[k] = None
    try:
        decs[k] = int(el.get("decimals"))
    except (TypeError, ValueError):
        pass

rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
res = workbook_rules.CellResolver(EXT)


def fk(dp):                                   # add CEG=x1, default-dropped local key
    d = {dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}
    d[CEG[0]] = CEG[1]
    return (dim_drs.local(dp["concept"]), dimset(d.items()))


def hu(k):
    d = decs.get(k)
    return 0.5 * (10.0 ** (-d)) if d is not None else 0.5


fails = []
for r in rules:
    ts = {t.upper() for t in r["tables"]}
    if ts != {"OF09.02.01.01"} or r.get("deactivated"):
        continue                              # single-table OF09.02 only
    pe = workbook_rules.parse_expression(r.get("expression", ""))
    if pe and pe.get("op") == "i=":
        for a in workbook_rules.expand_scoped_asts(r):
            if a["op"] != "i=":
                continue
            lhs = rhs = 0.0; tol = 0.0; touched_new = False
            for side, sgn in (("lhs", 1.0), ("rhs", -1.0)):
                for t in a[side]:
                    for dp in res.resolve(t["cell"]):
                        k = fk(dp); v = facts.get(k)
                        if v is None:
                            v = 0.0
                        else:
                            tol += abs(t["coef"]) * hu(k)
                            if CEG in k[1]:
                                touched_new = True
                        (lhs, rhs) = (lhs + v * t["coef"], rhs) if side == "lhs" else (lhs, rhs + v * t["coef"])
            if abs(lhs - rhs) > max(tol, 0.5):
                fails.append((r["code"], round(lhs), round(rhs), touched_new))

print(f"{os.path.basename(F)}: OF09.02 single-table additive fails @CEG=x1: {len(fails)}")
for code, l, rr, tn in fails[:20]:
    print(f"   {code}: {l} != {rr}   involves-new-cell={tn}")
