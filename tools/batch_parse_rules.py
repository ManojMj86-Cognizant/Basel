import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, r"C:\Users\177069\ClaudeLearning\boe_xbrl_gen\src")
import formula_rules as fr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
val_dir = sys.argv[1]
files = sorted(Path(val_dir).glob("vr-*.xml"))
n_rules = 0
complex_common = 0
complex_var = 0
no_test = 0
sev = Counter()
errors = []
multi_var = Counter()
for f in files:
    try:
        rules = fr.parse_file(f)
    except Exception as e:
        errors.append((f.name, repr(e)))
        continue
    for r in rules:
        n_rules += 1
        sev[r.severity] += 1
        if r.test is None:
            no_test += 1
        if r.common.complex:
            complex_common += 1
        if any(v.selector.complex for v in r.variables.values()):
            complex_var += 1
        multi_var[len(r.variables)] += 1

print(f"files: {len(files)}  rules: {n_rules}")
print(f"severities: {dict(sev)}")
print(f"rules w/ complex common selector: {complex_common}")
print(f"rules w/ a complex variable selector: {complex_var}")
print(f"rules w/o test: {no_test}")
print(f"variable-count distribution: {dict(sorted(multi_var.items()))}")
print(f"parse errors: {len(errors)}")
for name, e in errors[:10]:
    print(f"  {name}: {e}")
