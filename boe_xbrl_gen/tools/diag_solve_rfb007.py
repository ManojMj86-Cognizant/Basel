"""Trace what solve() does with b1129/b1130 (conditional-empty) on RFB007."""
import sys, json
from pathlib import Path
ROOT = r"C:\Users\177069\ClaudeLearning"
sys.path.insert(0, fr"{ROOT}\boe_xbrl_gen\src")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import solve_all, solve as S, expr as E
from instance import Instance
from resolver import bind

GEN = fr"{ROOT}\boe_xbrl_gen\out\sweep\RFB007.gen.xbrl"
VAL = fr"{ROOT}\boebanking400\Banking_4.0.0\www.bankofengland.co.uk\data\xbrl\fws\banking\structural_reform\2021-07-31\val"
CACHE = fr"{ROOT}\boe_xbrl_gen\out\sweep\rules_structural_reform_2021-07-31.pkl"
DEFAULTS = json.loads(Path(fr"{ROOT}\boe_xbrl_gen\model\dim_defaults.json").read_text(encoding="utf-8"))

inst = Instance(GEN)
rules = solve_all.parse_all_rules(VAL, cache=CACHE)
by_id = {r.id: r for r in rules}

r = by_id["boe_boe_b1129_m"]
ast = E.parse(r.test)
cond, core = S._unwrap(ast)
print("unwrap cond:", cond)
print("unwrap core:", core)
print("empty_var:", S._empty_var(core))
print("ev in rule.variables:", S._empty_var(core) in r.variables)

# what value does v0 (ei6017) hold, and what does the guard evaluate to?
bs = bind(r, inst, DEFAULTS)
nonempty = [b for b in bs if b["vars"].get("v0")]
print(f"\nbindings with v0: {len(nonempty)}")
v0vals = set()
guard_true = 0
for b in nonempty[:40]:
    v0f = b["vars"]["v0"]
    val = v0f[0].value if len(v0f) == 1 else [f.value for f in v0f]
    v0vals.add(str(val))
    cond_facts = {"v0": v0f}
    if S._cond_holds(cond, cond_facts):
        guard_true += 1
print("distinct v0 values:", sorted(v0vals)[:10])
print("guard True count (of shown):", guard_true)

# QName node + how it evaluates
qn = core  # not used
print("\ncondition AST:", cond)
