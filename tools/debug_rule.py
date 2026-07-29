import json, sys
sys.path.insert(0, r"C:\Users\177069\ClaudeLearning\boe_xbrl_gen\src")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import random
import formula_rules as fr
from instance import Instance
from resolver import bind
import solve as S
import expr as E

inst_path, rule_file = sys.argv[1], sys.argv[2]
defaults = json.load(open(r"C:\Users\177069\ClaudeLearning\boe_xbrl_gen\model\dim_defaults.json", encoding="utf-8"))
inst = Instance(inst_path)
rules = fr.parse_file(rule_file)
for rule in rules:
    print(f"RULE {rule.id} test={rule.test}")
    ast = S._safe_parse(rule.test)
    print(f"  parsed AST ok: {ast is not None}")
    cond, core = S._unwrap(ast)
    print(f"  equality_sides: {S._equality_sides(core)}")
    for b in bind(rule, inst, defaults):
        vals = {n: [f.value for f in b['vars'][n]] for n in rule.variables}
        print(f"  group vals BEFORE: {vals}")

# now run solve on just this rule and recheck
S.solve(inst, rules, defaults, random.Random(1))
print("---- after solve ----")
for rule in rules:
    for b in bind(rule, inst, defaults):
        vals = {n: [f.value for f in b['vars'][n]] for n in rule.variables}
        print(f"  group vals AFTER: {vals}")
