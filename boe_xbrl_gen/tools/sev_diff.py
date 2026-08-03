"""Diff two TDG logs by ERROR-severity rule set (per workbook severity). Shows which ERROR rules were
FIXED (in base, not new) vs newly BROKEN (in new, not base = activation/regression).
Usage: python tools/sev_diff.py <base_log> <new_log>"""
import sys, re
sys.path.insert(0, "src"); sys.path.insert(0, ".")
import workbook_rules as w

WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
R = w.load_workbook_rules(WB, "banking_reporting")
SEV = {x["code"]: ("ERROR" if str(x.get("severity", "")).upper().startswith("ERROR") else "WARNING") for x in R}


def err_codes(path):
    out = set()
    for ln in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"xbrl\.xiif\.AssertionUnsatisfied\.boe_(\S+)", ln.strip())
        if m and SEV.get(m.group(1)) == "ERROR":
            out.add(m.group(1))
    return out


base, new = err_codes(sys.argv[1]), err_codes(sys.argv[2])
print(f"base ERROR rules: {len(base)}   new ERROR rules: {len(new)}   net {len(new)-len(base):+d}")
print(f"\nFIXED (ERROR in base, gone in new): {len(base - new)}\n  {sorted(base - new)}")
print(f"\nNEWLY BROKEN (ERROR in new, not in base = activation/regression): {len(new - base)}\n  {sorted(new - base)}")
