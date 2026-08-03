"""Structural vs value-driven test for the b0834 residual.
For each b0834 (col,z): A = the OF08.01 source-cell set that pins r0180 (via cross-rule b0872); D = the union
of OF08.01 source cells that pin the determined detail rows (b0830-33). If D subseteq A, then Σdetail<=Σr0180
for ANY >=0 leaves => gap>=0 under fresh consistent leaves => VALUE-DRIVEN (regen fixes it). If D has cells
OUTSIDE A, the instance is STRUCTURAL (irreducible). Counts each."""
import sys, json
sys.path.insert(0, "src"); sys.path.insert(0, ".")
import workbook_rules
from src import dim_drs, instance_build
from collections import defaultdict

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
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


# cross-table (multi-table) additive defs: target key -> set of source keys (from OF08.01 etc.)
cross_src = defaultdict(set)
for r in R:
    ts = {t.upper() for t in r["tables"]}
    if len(ts) <= 1 or r.get("deactivated"):
        continue
    pe = workbook_rules.parse_expression(r.get("expression", ""))
    if not (pe and pe.get("op") == "i="):
        continue
    for a in workbook_rules.expand_scoped_asts(r):
        if a["op"] != "i=":
            continue
        for side, other in (("lhs", "rhs"), ("rhs", "lhs")):
            if len(a[side]) == 1:
                tgts = res.resolve(a[side][0]["cell"])
                if len(tgts) != 1:
                    continue
                tk = ck(tgts[0])
                for t in a[other]:
                    for dp in res.resolve(t["cell"]):
                        cross_src[tk].add(ck(dp))

rr = next((x for x in R if "b0834" in x["code"]), None)
struct = value = nocross = 0
examples = []
for a in workbook_rules.expand_scoped_asts(rr):
    if len(a["lhs"]) != 1:
        continue
    tot = res.resolve(a["lhs"][0]["cell"])
    if not tot:
        continue
    A = cross_src.get(ck(tot[0]))
    if not A:
        nocross += 1; continue                     # r0180 has no cross-table (b0872) def here
    D = set()
    for t in a["rhs"]:
        for dp in res.resolve(t["cell"]):
            D |= cross_src.get(ck(dp), set())        # determined detail rows' cross sources
    if D <= A:
        value += 1
    else:
        struct += 1
        if len(examples) < 3:
            examples.append(len(D - A))

print(f"b0834 instances with a cross-table r0180 def (b0872): {struct+value}  (no-cross: {nocross})")
print(f"  VALUE-DRIVEN  (detail sources subseteq r0180 sources -> fresh leaves give gap>=0): {value}")
print(f"  STRUCTURAL    (detail sources exceed r0180 sources -> irreducible):               {struct}")
if examples:
    print(f"  (structural examples: #detail-source cells outside r0180 set = {examples})")
