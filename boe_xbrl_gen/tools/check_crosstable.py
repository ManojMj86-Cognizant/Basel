"""Additive-rule satisfaction split by single-table vs MULTI-table (cross-table) over the output."""
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
tables = json.load(open(f"{BASE}/generated/result.json", encoding="utf-8"))["instances"][0]["tables"]
tset = set(tables)


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


def val(dp):
    return facts.get(fkey(dp["concept"], dp["dims"]))


def tally(multi):
    total = balanced = unbal = incomplete = 0
    for r in rules:
        if not r["tables"] or not (set(r["tables"]) <= tset) or r.get("deactivated"):
            continue
        if (len(set(r["tables"])) > 1) != multi:
            continue
        for a in workbook_rules.expand_scoped_asts(r):
            if a["op"] != "i=":
                continue
            total += 1
            lhs = sum((val(dp) or 0) * t["coef"] for t in a["lhs"] for dp in res.resolve(t["cell"]))
            rhs = sum((val(dp) or 0) * t["coef"] for t in a["rhs"] for dp in res.resolve(t["cell"]))
            missing = any(val(dp) is None for side in ("lhs", "rhs") for t in a[side] for dp in res.resolve(t["cell"]))
            if missing:
                incomplete += 1; continue
            if abs(lhs - rhs) < 0.5:
                balanced += 1
            else:
                unbal += 1
    return total, balanced, unbal, incomplete


for label, multi in (("SINGLE-table", False), ("MULTI-table (cross)", True)):
    t, b, u, i = tally(multi)
    print(f"{label:22s} additive eqs: {t:6d}  balanced {b:6d}  UNBAL {u:5d}  incomplete {i:5d}")
