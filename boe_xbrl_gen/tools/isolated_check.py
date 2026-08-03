"""Isolated-rule check: of v15's ERROR-severity failing rules, which are SINGLE-TABLE on a STANDALONE table
(NOT in the entangled 35-table OF08 cluster)? Those can be fixed in-place without cascading into the OF08
cross-table web. Classify every error rule into: SAFE (single-table, standalone, additive), single-table but
in-cluster, cross-table, or non-linear/taxonomy. Run from boe_xbrl_gen/ with PYTHONIOENCODING=utf-8."""
import sys, re, json
sys.path.insert(0, "src"); sys.path.insert(0, ".")
import workbook_rules
from src import dim_drs, instance_build
from collections import defaultdict

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
LOG = r"C:\Users\177069\ClaudeLearning\Errors on version 15_03 Aug.txt"

R = workbook_rules.load_workbook_rules(WB, "banking_reporting")
BY = {x["code"]: x for x in R}
SEV = {x["code"]: ("ERROR" if str(x.get("severity", "")).upper().startswith("ERROR") else "WARNING") for x in R}

# error-severity failing rule codes from the v15 log
failing = set()
for ln in open(LOG, encoding="utf-8", errors="replace"):
    m = re.match(r"xbrl\.xiif\.AssertionUnsatisfied\.boe_(\S+)", ln.strip())
    if m and SEV.get(m.group(1)) == "ERROR":
        failing.add(m.group(1))

# entangled OF08 cluster (35 tables)
idx = instance_build.module_index(EXT)
tset = {t.upper() for t, infos in idx.items() for i in infos if i["module"] == "pra001"}
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


def is_additive(r):
    pe = workbook_rules.parse_expression(r.get("expression", ""))
    return bool(pe and pe.get("op") in ("i=", "i<=", "i>=", "i<", "i>"))


def is_nonlinear(r):
    e = (r.get("expression", "") or "").lower()
    return any(t in e for t in ("exp(", "imax", "imin"))


buckets = defaultdict(list)
for code in sorted(failing):
    r = BY.get(code)
    if not r:
        buckets["unknown-code"].append(code); continue
    ts = {t.upper() for t in r["tables"]}
    if is_nonlinear(r):
        buckets["non-linear / taxonomy"].append((code, sorted(ts)))
    elif len(ts) > 1:
        buckets["cross-table (entangled)"].append((code, sorted(ts)))
    elif ts & CLUSTER:
        buckets["single-table but IN OF08 cluster (shared cells)"].append((code, sorted(ts)))
    else:
        tag = "additive" if is_additive(r) else "other"
        buckets[f"SAFE: single-table STANDALONE ({tag})"].append((code, sorted(ts)))

print(f"v15 ERROR-severity failing rules: {len(failing)}\n")
for b in sorted(buckets, key=lambda k: (not k.startswith("SAFE"), k)):
    items = buckets[b]
    print(f"== {b}: {len(items)} ==")
    for it in items[:30]:
        print(f"   {it}")
    print()
