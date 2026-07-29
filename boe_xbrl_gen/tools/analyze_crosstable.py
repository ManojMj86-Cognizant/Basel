"""Analyze multi-table (cross-table) rules for PRA001: which tables fuse, rule shapes, sizes."""
import sys, os, json
ROOT = r"C:\Users\177069\ClaudeLearning\boe_xbrl_gen"
os.chdir(ROOT)
sys.path.insert(0, "src"); sys.path.insert(0, ".")
import workbook_rules

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
RESULT = f"{BASE}/generated/result.json"

selection = set(json.load(open(RESULT, encoding="utf-8"))["instances"][0]["tables"])
rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")

# multi-table rules fully inside the selection
multi = [r for r in rules if r.get("tables") and len(set(r["tables"])) > 1
         and set(r["tables"]) <= selection and not r.get("deactivated")]
print(f"selection tables: {len(selection)}")
print(f"multi-table rules in selection: {len(multi)}  (of {len(rules)} total)")

# union-find over tables linked by a multi-table rule
parent = {}
def find(x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]; x = parent[x]
    return x
def union(a, b): parent[find(a)] = find(b)
for r in multi:
    ts = list(set(r["tables"]))
    for t in ts[1:]:
        union(ts[0], t)

from collections import defaultdict, Counter
groups = defaultdict(set)
for r in multi:
    for t in set(r["tables"]):
        groups[find(t)].add(t)
print(f"\nfused table-groups: {len(groups)}")
for g, ts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    print(f"  [{len(ts)} tables] {sorted(ts)}")

# shape histogram by op + pair count
ops = Counter()
twotab = 0
for r in multi:
    ops[r.get("op", "?")] += 1
    if len(set(r["tables"])) == 2:
        twotab += 1
print(f"\nrule ops: {dict(ops)}")
print(f"exactly-2-table rules: {twotab}  | >2-table: {len(multi)-twotab}")

# sample a few rules of each op
print("\n--- samples ---")
seen = set()
for r in multi:
    op = r.get("op", "?")
    if op in seen:
        continue
    seen.add(op)
    print(f"[{op}] {r.get('id')}  tables={set(r['tables'])}")
    print(f"      expr: {(r.get('expression') or '')[:160]}")
    print(f"      scope: {r.get('scope')}")
