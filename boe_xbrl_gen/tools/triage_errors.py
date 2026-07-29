"""Triage the TDG error dump: categorise every error by type (XPTY tool-error vs AssertionUnsatisfied),
rule code, and primary table; bucket into families (non-linear OF24, cross-table OF09.02/OF34.07↔OF08.01,
OF02/C24 mega-component, other); and flag any error on a table we already 'fixed' in v2 (regression check)."""
import re, sys
from collections import Counter, defaultdict

F = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\177069\ClaudeLearning\Errors on version 2_23 July.txt"
lines = open(F, encoding="utf-8", errors="replace").read().splitlines()

FIXED = {"C04.00.01.01", "C32.02.01.01", "C32.02.01.03", "C32.03.01.01", "C32.04.01.01",
         "OF22.00.01.01", "OF09.01.01.01", "C34.03.01.01", "C34.01.01.01", "C34.02.01.01",
         "OF08.07.01.01", "OF23.00.01.01", "C03.00.01.01", "C06.01.01.01", "OF21.00.01.01",
         "OF02.00.01.01"}  # OF02 was DEFERRED not fixed, but list to see

xpty = Counter()
assertion_rule = Counter()          # rule code -> count of unsatisfied instances (header lines)
rule_tables = defaultdict(Counter)  # rule code -> Counter(table)
table_hits = Counter()
zero_lhs = Counter()                # rules where our side "reported as 0 =" (absent/zero cross-table)

cur_code = None
for i, ln in enumerate(lines):
    m = re.match(r"xbrl\.xiif\.err:(\S+)", ln)
    if m:
        xpty[m.group(1)] += 1
        cur_code = None
        continue
    m = re.match(r"xbrl\.xiif\.AssertionUnsatisfied\.boe_(\S+)", ln)
    if m:
        code = m.group(1)
        assertion_rule[code] += 1
        cur_code = code
        continue
    # detail line for the current assertion: extract tables + zero-lhs pattern
    if cur_code and ("[" in ln or "t:" in ln):
        tabs = set(re.findall(r"t:\s*([A-Z]{1,3}\d[\w.]*)", ln))
        for t in tabs:
            rule_tables[cur_code][t] += 1
            table_hits[t] += 1
        # our-side-zero cross-table: "reported as 0 = ("  (LHS 0, RHS a real OF08 value)
        if re.search(r"reported as 0\s*=", ln):
            zero_lhs[cur_code] += 1
        cur_code = None

print(f"total lines: {len(lines)}")
print(f"\n== TYPE/TOOL errors (XPTY etc.) ==")
for k, n in xpty.most_common():
    print(f"  err:{k}: {n}")

print(f"\n== AssertionUnsatisfied: {sum(assertion_rule.values())} instances across {len(assertion_rule)} distinct rules ==")

# family bucketing by primary table
def primary_table(code):
    return rule_tables[code].most_common(1)[0][0] if rule_tables[code] else "?"

fam = Counter(); fam_rules = defaultdict(set)
for code, n in assertion_rule.items():
    tabs = set(rule_tables[code])
    if any(t.startswith("OF24") for t in tabs):
        f = "non-linear OF24 (exp/imax)"
    elif "OF09.02.01.01" in tabs and any(t.startswith("OF08") for t in tabs):
        f = "cross-table OF09.02<->OF08.01"
    elif "OF34.07.01.01" in tabs and any(t.startswith("OF08") for t in tabs):
        f = "cross-table OF34.07<->OF08.01"
    elif "OF02.00.01.01" in tabs or "C24.00.01.01" in tabs:
        f = "OF02/C24 mega-component"
    elif len(tabs) > 1:
        f = "other cross-table"
    else:
        f = "other single-table: " + (primary_table(code))
    fam[f] += n; fam_rules[f].add(code)

print("\n== families (by unsatisfied-instance count) ==")
for f, n in fam.most_common():
    print(f"  {n:5d} inst / {len(fam_rules[f]):3d} rules  {f}")

print("\n== distinct tables referenced (top 25) ==")
for t, n in table_hits.most_common(25):
    tag = "  <-- we 'fixed' this in v2!" if t in FIXED else ""
    print(f"  {n:5d}  {t}{tag}")

print("\n== cross-table rules where OUR side is 0 (absent → we don't generate OF09.02/OF34.07 total rows) ==")
print(f"  {sum(zero_lhs.values())} instances across {len(zero_lhs)} rules")

print("\n== any error on a table we FIXED in v2? (regression check) ==")
hit_fixed = {t: n for t, n in table_hits.items() if t in FIXED}
print(" ", hit_fixed if hit_fixed else "NONE")
