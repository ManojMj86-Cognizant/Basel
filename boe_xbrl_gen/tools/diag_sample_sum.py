"""Examine how b1042's cross-table sum holds in the OFFICIAL valid sample:
dump v0 (total) and v1 (breakdown) facts with typed dims + values to find the pairing."""
import sys, json
from pathlib import Path
ROOT = r"C:\Users\177069\ClaudeLearning"
sys.path.insert(0, fr"{ROOT}\boe_xbrl_gen\src")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import solve_all
from instance import Instance
from resolver import _concepts_for, _dim_filters_for, _fact_matches

SAMPLE = fr"{ROOT}\boebankingtaxonomysampleinstancesv400\ABCDEFGHIJ0123456789_GB_banking_RFB007_2021-11-30_20211025144410000.xbrl"
VAL = fr"{ROOT}\boebanking400\Banking_4.0.0\www.bankofengland.co.uk\data\xbrl\fws\banking\structural_reform\2021-07-31\val"
CACHE = fr"{ROOT}\boe_xbrl_gen\out\sweep\rules_structural_reform_2021-07-31.pkl"
DEFAULTS = json.loads(Path(fr"{ROOT}\boe_xbrl_gen\model\dim_defaults.json").read_text(encoding="utf-8"))

inst = Instance(SAMPLE)
rules = solve_all.parse_all_rules(VAL, cache=CACHE)
r = {x.id: x for x in rules}["boe_boe_b1042_m"]

def short(d):
    return {k.split('}')[-1]: (v.split('}')[-1] if isinstance(v,str) else v) for k,v in d.items()}

def cands(var):
    v = r.variables[var]
    concepts = _concepts_for(r, v)
    df = _dim_filters_for(r, v)
    pool = []
    for c in (concepts or []):
        pool.extend(inst.by_concept.get(c, ()))
    return [f for f in pool if _fact_matches(f, concepts, df, DEFAULTS)]

v0 = cands("v0"); v1 = cands("v1")
print(f"v0 (total) facts={len(v0)}   v1 (breakdown) facts={len(v1)}")
print("\n--- v0 facts (CTI=x6001, CUP=x0): the totals ---")
for f in v0:
    print(f"  val={f.value:>12}  dims={short(f.dims)}  typed={short(f.typed)}")
print("\n--- v1 facts (first 12): the per-currency breakdown ---")
for f in v1[:12]:
    print(f"  val={f.value:>12}  dims={short(f.dims)}  typed={short(f.typed)}")

# Try the hypothesis: group both by shared aspects {APA,BAS,LEC,period} (ignore ISE/ISF/LEP/LER/CUP/CTI)
SHARED = {"APA", "BAS"}  # explicit shared + we add LEC typed + period
from collections import defaultdict
def shared_key(f):
    ex = tuple(sorted((d.split('}')[-1], m) for d, m in f.dims.items() if d.split('}')[-1] in SHARED))
    lec = tuple(sorted((d.split('}')[-1], t) for d, t in f.typed.items() if d.split('}')[-1] == "LEC"))
    per = inst.contexts.get(f.ctxref, {}).get("period")
    return (ex, lec, per)

g0 = defaultdict(list); g1 = defaultdict(list)
for f in v0: g0[shared_key(f)].append(f)
for f in v1: g1[shared_key(f)].append(f)
print("\n--- shared-key {APA,BAS,LEC,period} join ---")
for k in sorted(set(g0) | set(g1)):
    tot = [float(x.value) for x in g0.get(k, [])]
    brk = [float(x.value) for x in g1.get(k, [])]
    print(f"  key={k}: v0(n={len(tot)})={tot}  sum(v1 n={len(brk)})={sum(brk)}  match={any(abs(t-sum(brk))<1 for t in tot)}")
