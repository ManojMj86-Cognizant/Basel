"""Phase 2 in-memory PROOF: solve the cluster's COMBINED single+cross additive system JOINTLY per connected
component (least-squares over aggregate cells, leaves fixed) instead of phase1's pick-one-canonical derivation.
If the balanced-equation count beats phase1 (16014/16402), joint leaf-first reconciles the cluster and is worth
wiring into the emitter. Also reports negativity (aggregates that go <0, which the >=0 emit must handle)."""
import sys, json
sys.path.insert(0, "src"); sys.path.insert(0, ".")
import numpy as np
from lxml import etree
import workbook_rules
from src import dim_drs, instance_build
from collections import defaultdict, deque

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
V8 = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v15.xbrl"
X = "http://www.xbrl.org/2003/instance"
CEG_TABLES = {"OF09.01.01.01", "OF09.02.01.01"}
DEF = {d: dim_drs.local(m) for d, m in dim_drs.localize_defaults(
    json.load(open(f"{BASE}/model.json", encoding="utf-8")).get("dim_defaults", {})).items()}


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
res = workbook_rules.CellResolver(EXT)


def ck(dp):
    d = {dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}
    if dp.get("table", "").upper() in CEG_TABLES:
        d["CEG"] = "x1"
    return (dim_drs.local(dp["concept"]), dset(d.items()))


raw = open(V8, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
root = etree.fromstring(raw); cd = {}
for c in root.findall(f"{{{X}}}context"):
    dd = {}; sc = c.find(f"{{{X}}}scenario")
    if sc is not None:
        for em in sc:
            if em.get("dimension") and etree.QName(em).localname == "explicitMember":
                dd[dim_drs.local(em.get("dimension"))] = dim_drs.local((em.text or "").strip())
    cd[c.get("id")] = dd
val0 = {}
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    try:
        val0[(dim_drs.local(etree.QName(el).localname), dset(cd.get(cr, {}).items()))] = float((el.text or "").strip())
    except (ValueError, TypeError):
        pass

# equations + aggregate set
equations = []; defs = defaultdict(list); allcells = set()
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
        eq = defaultdict(float); sidecells = {"lhs": [], "rhs": []}
        for s, sgn in (("lhs", 1.0), ("rhs", -1.0)):
            for t in a[s]:
                for dp in res.resolve(t["cell"]):
                    k = ck(dp); eq[k] += sgn * t["coef"]; sidecells[s].append(k); allcells.add(k)
        eq = {k: c for k, c in eq.items() if abs(c) > 1e-9}
        if not eq:
            continue
        equations.append(eq)
        for s in ("lhs", "rhs"):
            if len(sidecells[s]) == 1 and sidecells[s][0] in eq:
                defs[sidecells[s][0]].append(1)
aggregates = set(defs); leaves = allcells - aggregates
print(f"cluster {len(CLUSTER)} tables | cells {len(allcells)} (leaves {len(leaves)}, aggregates {len(aggregates)}) | equations {len(equations)}")

# connected components over cells sharing an equation
parent = {k: k for k in allcells}
def find(a):
    while parent[a] != a:
        parent[a] = parent[parent[a]]; a = parent[a]
    return a
def union(a, b):
    parent[find(a)] = find(b)
for eq in equations:
    ks = list(eq)
    for k in ks[1:]:
        union(ks[0], k)
comp_cells = defaultdict(set); comp_eqs = defaultdict(list)
for k in allcells:
    comp_cells[find(k)].add(k)
for eq in equations:
    comp_eqs[find(next(iter(eq)))].append(eq)

val = dict(val0)
solved_neg = 0; big = []
for cid, cells in comp_cells.items():
    eqs = comp_eqs[cid]
    aggv = sorted(c for c in cells if c in aggregates)
    if not aggv or not eqs:
        continue
    col = {k: j for j, k in enumerate(aggv)}
    Mrows = []; b = []
    for eq in eqs:
        row = np.zeros(len(aggv)); rhs = 0.0
        for k, c in eq.items():
            if k in col:
                row[col[k]] += c
            else:
                rhs -= c * val.get(k, 0.0)      # leaf term -> RHS
        Mrows.append(row); b.append(rhs)
    if len(aggv) > 4000:
        big.append((len(aggv), len(eqs))); continue
    A = np.array(Mrows); bb = np.array(b)
    xsol, *_ = np.linalg.lstsq(A, bb, rcond=None)
    for k, j in col.items():
        val[k] = xsol[j]
        if xsol[j] < -0.5:
            solved_neg += 1

ok = bad = 0
for eq in equations:
    if abs(sum(c * val.get(k, 0.0) for k, c in eq.items())) < 0.5:
        ok += 1
    else:
        bad += 1
print(f"\nJOINT least-squares solve (single+cross together, per component):")
print(f"  balanced equations: {ok} / {len(equations)}  ({100.0*ok/max(1,len(equations)):.1f}%)")
print(f"  residual: {bad}   (phase1 pick-canonical was 244)")
print(f"  aggregates solved negative (<0, emit must clamp/redistribute): {solved_neg}")
if big:
    print(f"  SKIPPED {len(big)} big components (>4000 aggs): {big[:5]}")
