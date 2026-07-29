"""Phase 0 of the coordinated-regeneration build — derivation-DAG + consistency report (NO generation).

Over the 35-table OF08 cluster, parse every ADDITIVE rule (single + cross) into `aggregate = Σ sources`
(aggregate = the lone-single-term 'total' side), keying cells default-dropped (+ CEG=x1 for OF09.x country-
agg tables, matching how leaves/aggregates would be tagged). Then report:
  * leaves (never an aggregate) vs aggregates vs intermediates
  * multi-defined aggregates (defined by >1 rule) and how many have DIFFERING source sets (over-determination
    / genuine-conflict candidates)
  * cycles (would block topological derivation)
  * relational rules with no single 'total' side (can't drive a derivation)
This quantifies how much of the cluster is cleanly leaf-first-derivable BEFORE building the generator.
"""
import sys, json, os
sys.path.insert(0, "src"); sys.path.insert(0, ".")
import workbook_rules
from src import dim_drs, instance_build
from collections import defaultdict

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
CEG_TABLES = {"OF09.01.01.01", "OF09.02.01.01"}       # country-agg: cells carry CEG (add x1)

DEF = {}
for d, m in dim_drs.localize_defaults(json.load(open(f"{BASE}/model.json", encoding="utf-8")).get("dim_defaults", {})).items():
    DEF[d] = dim_drs.local(m)


def dimset(items):
    return frozenset((k, v) for k, v in items if DEF.get(k) != v)


# 35-table cluster
idx = instance_build.module_index(EXT)
tset = {t.upper() for t, infos in idx.items() for i in infos if i["module"] == "pra001"}
R = workbook_rules.load_workbook_rules(WB, "banking_reporting")
adj = defaultdict(set)
for r in R:
    ts = {t.upper() for t in r["tables"]}
    if len(ts) > 1 and ts <= tset and not r.get("deactivated"):
        for a in ts:
            for b in ts:
                if a != b:
                    adj[a].add(b)
seen = set(); stack = ["OF08.01.01.01"]
while stack:
    x = stack.pop()
    if x in seen:
        continue
    seen.add(x); stack += [y for y in adj[x] if y not in seen]
CLUSTER = seen
print(f"cluster tables: {len(CLUSTER)}")

res = workbook_rules.CellResolver(EXT)


def key(dp):
    d = {dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}
    if dp.get("table", "").upper() in CEG_TABLES:
        d["CEG"] = "x1"
    return (dim_drs.local(dp["concept"]), dimset(d.items()))


defined_by = defaultdict(list)      # aggregate cell -> [(rule, frozenset(source keys))]
is_source = set()
all_cells = set()
n_add = n_eq = n_relational = 0
for r in R:
    ts = {t.upper() for t in r["tables"]}
    if not (ts <= CLUSTER) or r.get("deactivated"):
        continue
    pe = workbook_rules.parse_expression(r.get("expression", ""))
    if not (pe and pe.get("op") == "i="):
        continue
    n_add += 1
    for a in workbook_rules.expand_scoped_asts(r):
        if a["op"] != "i=":
            continue
        n_eq += 1
        side = "lhs" if len(a["lhs"]) == 1 else ("rhs" if len(a["rhs"]) == 1 else None)
        cells = {}
        for s in ("lhs", "rhs"):
            for t in a[s]:
                for dp in res.resolve(t["cell"]):
                    cells.setdefault(s, []).append(key(dp))
        for s in cells:
            for k in cells[s]:
                all_cells.add(k)
        if side is None:
            n_relational += 1
            for s in ("lhs", "rhs"):
                for k in cells.get(s, []):
                    is_source.add(k)
            continue
        agg_keys = cells.get(side, [])
        src_keys = [k for s in ("lhs", "rhs") if s != side for k in cells.get(s, [])]
        for k in src_keys:
            is_source.add(k)
        if len(agg_keys) == 1:
            defined_by[agg_keys[0]].append((r["code"], frozenset(src_keys)))
        else:
            for k in agg_keys:
                is_source.add(k)

aggregates = set(defined_by)
leaves = {c for c in all_cells if c not in aggregates}
intermediates = {c for c in aggregates if c in is_source}
pure_agg = aggregates - intermediates
multi = {c: v for c, v in defined_by.items() if len(v) > 1}
multi_conflict = {c: v for c, v in multi.items() if len({fs for _, fs in v}) > 1}

# cycle detection over aggregate->source (only among defined cells)
graph = {c: {s for _, fs in defined_by[c] for s in fs if s in aggregates} for c in aggregates}
WHITE, GREY, BLACK = 0, 1, 2
color = defaultdict(int); cyc = [0]
def visit(n, stackset):
    color[n] = GREY
    for m in graph.get(n, ()):
        if color[m] == GREY:
            cyc[0] += 1
        elif color[m] == WHITE:
            visit(m, stackset)
    color[n] = BLACK
sys.setrecursionlimit(100000)
for c in list(aggregates):
    if color[c] == WHITE:
        visit(c, set())

print(f"\nadditive rules in cluster: {n_add}   concrete equations: {n_eq}   relational (no lone total): {n_relational}")
print(f"distinct cells: {len(all_cells)}")
print(f"  LEAVES (never an aggregate): {len(leaves)}")
print(f"  aggregates: {len(aggregates)}  (pure {len(pure_agg)} / intermediate {len(intermediates)})")
print(f"  multi-defined aggregates (>1 rule): {len(multi)}")
print(f"     of which DIFFERING source sets (over-determination/conflict candidates): {len(multi_conflict)}")
print(f"  back-edges in aggregate->source graph (cycle indicators): {cyc[0]}")
frac = 100.0 * (len(all_cells) - len(multi_conflict)) / max(1, len(all_cells))
print(f"\nESTIMATE: {frac:.1f}% of cells cleanly leaf-derivable (rest = conflict candidates needing review)")

# refine: benign (all defining rules single-table, i.e. row/col totals of same grid) vs cross-table (risk)
rule_tabs = {r["code"]: {t.upper() for t in r["tables"]} for r in R}
benign = risky = 0
for c, v in multi_conflict.items():
    tabs = set()
    for code, _ in v:
        tabs |= rule_tabs.get(code, set())
    if len(tabs) == 1:
        benign += 1                      # same-table over-determination (2D row+col) — consistent under leaf-first
    else:
        risky += 1                       # multi-table definitions — genuine reconciliation risk
print(f"  of the {len(multi_conflict)} conflict candidates: benign same-table 2D = {benign}, "
      f"CROSS-TABLE (real risk) = {risky}")
print(f"  → refined clean estimate: {100.0*(len(all_cells)-risky)/max(1,len(all_cells)):.1f}% "
      f"(only cross-table multi-definitions are genuine conflicts)")
