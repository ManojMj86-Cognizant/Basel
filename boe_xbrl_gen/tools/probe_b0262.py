"""Diagnose the fix paths for b0262 (conditional activation) and b0834 (OF34.07 internal, 48 inst).
Reports each rule's expression/scope, its cells' current v15 values, and whether the key cells are
defined by an additive (i=) rule (=> derivable) or need leaf/overwrite work."""
import sys, json
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs, instance_build
from collections import defaultdict

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
V15 = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v15.xbrl"
X = "http://www.xbrl.org/2003/instance"
CEG_TABLES = {"OF09.01.01.01", "OF09.02.01.01"}
DEF = {d: dim_drs.local(m) for d, m in dim_drs.localize_defaults(
    json.load(open(f"{BASE}/model.json", encoding="utf-8")).get("dim_defaults", {})).items()}


def dset(items):
    return frozenset((k, v) for k, v in items if DEF.get(k) != v)


R = workbook_rules.load_workbook_rules(WB, "banking_reporting")
res = workbook_rules.CellResolver(EXT)


def ck(dp):
    d = {dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}
    if dp.get("table", "").upper() in CEG_TABLES:
        d["CEG"] = "x1"
    return (dim_drs.local(dp["concept"]), dset(d.items()))


# v15 facts
raw = open(V15, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
root = etree.fromstring(raw); cd = {}
for c in root.findall(f"{{{X}}}context"):
    dd = {}; sc = c.find(f"{{{X}}}scenario")
    if sc is not None:
        for em in sc:
            if em.get("dimension") and etree.QName(em).localname == "explicitMember":
                dd[dim_drs.local(em.get("dimension"))] = dim_drs.local((em.text or "").strip())
    cd[c.get("id")] = dd
facts = {}
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    try:
        facts[(dim_drs.local(etree.QName(el).localname), dset(cd.get(cr, {}).items()))] = float((el.text or "").strip())
    except (ValueError, TypeError):
        pass

# all additive-rule lone targets (key -> list of defining rule codes)
target_of = defaultdict(list)
for r in R:
    if r.get("deactivated"):
        continue
    pe = workbook_rules.parse_expression(r.get("expression", ""))
    if not (pe and pe.get("op") == "i="):
        continue
    for a in workbook_rules.expand_scoped_asts(r):
        if a["op"] != "i=":
            continue
        for side in ("lhs", "rhs"):
            if len(a[side]) == 1:
                for dp in res.resolve(a[side][0]["cell"]):
                    target_of[ck(dp)].append(r["code"])


def show(code):
    r = next((x for x in R if code in x["code"]), None)
    if not r:
        print(f"\n### {code}: NOT FOUND"); return
    print(f"\n### {r['code']}  tables={r['tables']}  sev={r.get('severity')}")
    print(f"expr: {r.get('expression','')[:260]}")
    print(f"scope: {r.get('scope','')[:160]}")


show("b0262")
print("  -- OF09.01 r0170 c0010/c0020 [CEG=x1] current values + derivability --")
for cc in ("0010", "0020"):
    for dp in res.resolve({"table": "OF09.01.01.01", "r": "0170", "c": cc, "z": []}):
        k = ck(dp)
        print(f"   c{cc}: present={k in facts} val={facts.get(k)}  additive-defined-by={target_of.get(k, [])[:4]}")

# evaluate b0729 to get the derived value of OF09.01 r0170 c0020 [CEG=x1]
print("\n  -- b0729 derivation of c0020 (is it > 0?) --")
rr9 = next((x for x in R if "b0729" in x["code"]), None)
if rr9:
    print(f"   b0729 expr: {rr9.get('expression','')[:200]}")
    tgt = None
    for dp in res.resolve({"table": "OF09.01.01.01", "r": "0170", "c": "0020", "z": []}):
        tgt = ck(dp)
    for a in workbook_rules.expand_scoped_asts(rr9):
        keys = {"lhs": [], "rhs": []}
        eqval = {"lhs": 0.0, "rhs": 0.0}
        for side in ("lhs", "rhs"):
            for t in a[side]:
                for dp in res.resolve(t["cell"]):
                    keys[side].append(ck(dp)); eqval[side] += t["coef"] * facts.get(ck(dp), 0.0)
        if tgt in keys["lhs"] + keys["rhs"]:
            other = "rhs" if tgt in keys["lhs"] else "lhs"
            print(f"   -> c0020 would derive to Σ(other side) = {eqval[other]}  (present={tgt in facts})")
            break

show("b0834")
print("  -- b0834 cells (OF34.07) current values --")
rr = next((x for x in R if "b0834" in x["code"]), None)
if rr:
    seen = 0
    for a in workbook_rules.expand_scoped_asts(rr):
        for side in ("lhs", "rhs"):
            for t in a[side]:
                for dp in res.resolve(t["cell"]):
                    k = ck(dp)
                    if seen < 20:
                        print(f"   {side} coef={t['coef']} {dp['table']} val={facts.get(k)} defby={target_of.get(k, [])[:3]}")
                        seen += 1
        break  # first concrete AST only
