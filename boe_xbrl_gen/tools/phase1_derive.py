"""Phase 1 — leaf-first DERIVER + offline validation (no file emit yet).

Over the 35-table cluster: build the additive derivation DAG, read LEAF values from v8, then derive every
aggregate topologically (aggregate = the canonical rule's Σ sources; canonical = a single-table 'own total'
where available). Then re-evaluate EVERY additive equation with the leaf+derived values and report how many
balance. This is the computational proof of leaf-first: it quantifies the true additive floor (satisfied vs
residual = genuine cross-table conflicts + cycles) before we build the emit/DRS/context machinery (Phase 1b).
"""
import sys, json
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs, instance_build
from collections import defaultdict, deque

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
V8 = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v8.xbrl"
CEG_TABLES = {"OF09.01.01.01", "OF09.02.01.01"}
X = "http://www.xbrl.org/2003/instance"

DEF = {}
for d, m in dim_drs.localize_defaults(json.load(open(f"{BASE}/model.json", encoding="utf-8")).get("dim_defaults", {})).items():
    DEF[d] = dim_drs.local(m)


def dimset(items):
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


def ckey(dp):
    d = {dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}
    if dp.get("table", "").upper() in CEG_TABLES:
        d["CEG"] = "x1"
    return (dim_drs.local(dp["concept"]), dimset(d.items()))


# load v8 facts (leaf + existing values)
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
        val0[(dim_drs.local(etree.QName(el).localname), dimset(cd.get(cr, {}).items()))] = float((el.text or "").strip())
    except (ValueError, TypeError):
        pass

# build equations + aggregate definitions
equations = []                       # list of {cells: {key: coef}}  (Σ coef·cell = 0)
defs = defaultdict(list)             # agg key -> [(single_table?, agg_coef, {src: coef})]
allcells = set()
for r in R:
    ts = {t.upper() for t in r["tables"]}
    if not (ts <= CLUSTER) or r.get("deactivated"):
        continue
    pe = workbook_rules.parse_expression(r.get("expression", ""))
    if not (pe and pe.get("op") == "i="):
        continue
    single = len(ts) == 1
    for a in workbook_rules.expand_scoped_asts(r):
        if a["op"] != "i=":
            continue
        eq = defaultdict(float); side_cells = {"lhs": [], "rhs": []}
        for s, sgn in (("lhs", 1.0), ("rhs", -1.0)):
            for t in a[s]:
                for dp in res.resolve(t["cell"]):
                    k = ckey(dp); eq[k] += sgn * t["coef"]; side_cells[s].append(k); allcells.add(k)
        eq = {k: c for k, c in eq.items() if abs(c) > 1e-9}
        if eq:
            equations.append(eq)
        side = "lhs" if len(a["lhs"]) == 1 else ("rhs" if len(a["rhs"]) == 1 else None)
        if side and len(side_cells[side]) == 1:
            agg = side_cells[side][0]
            src = {k: eq[k] for k in eq if k != agg}
            if agg in eq:
                defs[agg].append((single, eq[agg], src))

aggregates = set(defs)
leaves = allcells - aggregates

# canonical definition per aggregate: prefer a single-table rule
canon = {}
for agg, ds in defs.items():
    ds_sorted = sorted(ds, key=lambda d: (0 if d[0] else 1, len(d[2])))
    canon[agg] = ds_sorted[0]           # (single, agg_coef, {src:coef})

# topological derivation (Kahn) over agg -> source-aggregates
indeg = defaultdict(int); children = defaultdict(set)
for agg in aggregates:
    for s in canon[agg][2]:
        if s in aggregates:
            children[s].add(agg); indeg[agg] += 1
q = deque([a for a in aggregates if indeg[a] == 0])
order = []
while q:
    n = q.popleft(); order.append(n)
    for c in children[n]:
        indeg[c] -= 1
        if indeg[c] == 0:
            q.append(c)
cyclic = [a for a in aggregates if a not in set(order)]

val = dict(val0)                        # start from v8 (leaves keep their values)
derived = 0
for agg in order:
    _, ac, src = canon[agg]
    s = sum(co * val.get(k, 0.0) for k, co in src.items())
    val[agg] = -s / ac; derived += 1
for agg in cyclic:                      # best-effort for cycle members
    _, ac, src = canon[agg]
    val[agg] = -sum(co * val.get(k, 0.0) for k, co in src.items()) / ac

# evaluate all equations with leaf+derived values
ok = bad = 0
for eq in equations:
    if abs(sum(c * val.get(k, 0.0) for k, c in eq.items())) < 0.5:
        ok += 1
    else:
        bad += 1

print(f"cluster {len(CLUSTER)} tables | cells {len(allcells)} (leaves {len(leaves)}, aggregates {len(aggregates)})")
print(f"topo-derivable aggregates: {len(order)}   cyclic (best-effort): {len(cyclic)}")
print(f"\nadditive equations: {len(equations)}")
print(f"  BALANCED after leaf-first derivation: {ok}")
print(f"  residual (unbalanced = genuine conflicts/cycles): {bad}")
print(f"  → {100.0*ok/max(1,len(equations)):.1f}% of additive equations satisfied by leaf-first")
