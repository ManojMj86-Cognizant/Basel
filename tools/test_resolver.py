import sys
sys.path.insert(0, r"C:\Users\177069\ClaudeLearning\boe_xbrl_gen\src")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import formula_rules as fr
from instance import Instance
from resolver import bind

inst_path = sys.argv[1]
rule_files = sys.argv[2:]

try:
    with open(r"C:\Users\177069\ClaudeLearning\boe_xbrl_gen\model\dim_defaults.json", encoding="utf-8") as fh:
        defaults = json.load(fh)
except FileNotFoundError:
    defaults = {}
print(f"dimension defaults loaded: {len(defaults)}")

inst = Instance(inst_path)
print(f"instance: {len(inst.facts)} facts, {len(inst.contexts)} contexts\n")

for rf in rule_files:
    rules = fr.parse_file(rf)
    for rule in rules:
        print(f"=== {rule.id}  test={rule.test}")
        bindings = bind(rule, inst, defaults)
        nonempty = [b for b in bindings if any(b["vars"][n] for n in rule.variables)]
        print(f"  groups with facts: {len(nonempty)}")
        for b in nonempty[:4]:
            desc = []
            for n in rule.variables:
                facts = b["vars"][n]
                vals = [f"{f.value}" for f in facts]
                desc.append(f"${n}={vals}")
            # show uncovered key briefly
            print(f"    group {b['key'][0]}: " + "  ".join(desc))
        print()
