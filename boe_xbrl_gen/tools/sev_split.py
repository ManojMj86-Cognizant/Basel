"""Split one or more TDG logs by SEVERITY (ERROR vs WARNING per the workbook 'Severity and modules' column).
Counts both distinct failing RULES and total INSTANCES (AssertionUnsatisfied lines) per severity.
The blocking metric is ERROR-severity; WARNING is advisory.
Usage: python tools/sev_split.py <log1> [log2 ...]"""
import sys, re
sys.path.insert(0, "src"); sys.path.insert(0, ".")
import workbook_rules as w
from collections import Counter

WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
R = w.load_workbook_rules(WB, "banking_reporting")
SEV = {}
for x in R:
    SEV[x["code"]] = "ERROR" if str(x.get("severity", "")).upper().startswith("ERROR") else "WARNING"


def scan(path):
    inst = Counter(); xpty = 0
    for ln in open(path, encoding="utf-8", errors="replace"):
        s = ln.strip()
        if re.match(r"xbrl\.xiif\.err:", s):
            xpty += 1; continue
        m = re.match(r"xbrl\.xiif\.AssertionUnsatisfied\.boe_(\S+)", s)
        if m:
            inst[m.group(1)] += 1
    return inst, xpty


for path in sys.argv[1:]:
    inst, xpty = scan(path)
    by = {"ERROR": [0, 0], "WARNING": [0, 0], "unknown": [0, 0]}   # sev -> [rules, instances]
    for code, n in inst.items():
        s = SEV.get(code, "unknown")
        by[s][0] += 1; by[s][1] += n
    name = path.split("\\")[-1]
    print(f"\n=== {name} ===")
    print(f"  XPTY tool-errors: {xpty}")
    for s in ("ERROR", "WARNING", "unknown"):
        print(f"  {s:8}: {by[s][0]:4d} rules / {by[s][1]:5d} instances")
    print(f"  TOTAL   : {len(inst):4d} rules / {sum(inst.values()):5d} instances")
