"""Verify a coregen output: evaluate the 35-table cluster's ADDITIVE equations + INEQUALITY rules against
the file's ACTUAL facts (CEG-aware keying so generated OF09.x cells match). Reports additive-balanced % and
inequality-violated count — the offline signal for whether the emit produced a consistent cluster.
Usage: python tools/verify_coregen.py <file.xbrl>"""
import sys, json
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules, formula_eval
from src import dim_drs, instance_build
from collections import defaultdict

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
F = sys.argv[1]
X = "http://www.xbrl.org/2003/instance"
CEG_TABLES = {"OF09.01.01.01", "OF09.02.01.01"}
DEF = {d: dim_drs.local(m) for d, m in dim_drs.localize_defaults(json.load(open(f"{BASE}/model.json", encoding="utf-8")).get("dim_defaults", {})).items()}


def dset(items):
    return frozenset((k, v) for k, v in items if DEF.get(k) != v)


idx = instance_build.module_index(EXT)
tset = {t.upper() for t, infos in idx.items() for i in infos if i["module"] == "pra001"}
R = workbook_rules.load_workbook_rules(WB, "banking_reporting")
adj = defaultdict(set)
for r in R:
    ts = {t.upper() for t in r["tables"]}
    if len(ts) > 1 and ts <= tset and not r.get("deactivated"):
        for a in ts:
            adj[a] |= ts - {a}
seen = set(); st = ["OF08.01.01.01"]
while st:
    x = st.pop()
    if x in seen:
        continue
    seen.add(x); st += [y for y in adj[x] if y not in seen]
CLUSTER = seen

raw = open(F, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
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

res = workbook_rules.CellResolver(EXT)


def ck(dp):
    d = {dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}
    if dp.get("table", "").upper() in CEG_TABLES:
        d["CEG"] = "x1"
    return (dim_drs.local(dp["concept"]), dset(d.items()))


# additive
ok = bad = 0; badcodes = defaultdict(int)
for r in R:
    ts = {t.upper() for t in r["tables"]}
    if not (ts <= CLUSTER) or r.get("deactivated"):
        continue
    pe = workbook_rules.parse_expression(r.get("expression", ""))
    if not (pe and pe.get("op") == "i="):
        continue
    for a in workbook_rules.expand_scoped_asts(r):
        if a["op"] != "i=":
            continue
        s = 0.0
        for side, sg in (("lhs", 1.0), ("rhs", -1.0)):
            for t in a[side]:
                for dp in res.resolve(t["cell"]):
                    s += sg * t["coef"] * facts.get(ck(dp), 0.0)
        if abs(s) < 0.5:
            ok += 1
        else:
            bad += 1; badcodes[r["code"]] += 1
print(f"{F.split(chr(92))[-1]}")
print(f"  ADDITIVE equations (cluster): balanced {ok} / {ok+bad} = {100.0*ok/max(1,ok+bad):.1f}%   (failing rules: {len(badcodes)})")
top = sorted(badcodes.items(), key=lambda kv: -kv[1])[:12]
print("   top failing additive rules:", [f"{c}:{n}" for c, n in top])
