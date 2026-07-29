"""Reassess v5 vs v6 TDG logs SPLIT BY SEVERITY (ERROR vs WARNING per the workbook 'Severity and modules'
column). The blocking metric is ERROR-severity failing rules; WARNING failures are advisory."""
import sys, re
sys.path.insert(0, "src"); sys.path.insert(0, ".")
import workbook_rules as w

WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
V5 = r"C:\Users\177069\ClaudeLearning\Errors on version 5_23 July.txt"
V6 = r"C:\Users\177069\ClaudeLearning\Errors on version 6_24 July.txt"

R = w.load_workbook_rules(WB, "banking_reporting")
SEV = {}
for x in R:
    s = "ERROR" if str(x.get("severity", "")).upper().startswith("ERROR") else "WARNING"
    SEV[x["code"]] = s


def codes(path):
    out = set()
    for ln in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"xbrl\.xiif\.AssertionUnsatisfied\.boe_(\S+)", ln.strip())
        if m:
            out.add(m.group(1))
    return out


def split(cs):
    e = {c for c in cs if SEV.get(c) == "ERROR"}
    warn = {c for c in cs if SEV.get(c) == "WARNING"}
    unk = {c for c in cs if c not in SEV}
    return e, warn, unk


v5, v6 = codes(V5), codes(V6)
for lbl, cs in (("v5", v5), ("v6", v6)):
    e, wn, u = split(cs)
    print(f"{lbl}: total {len(cs)} rules  ->  ERROR {len(e)} | WARNING {len(wn)} | unknown {len(u)}")

print("\n== v5 -> v6 diff, by severity ==")
added, removed = v6 - v5, v5 - v6
for lbl, cs in (("ADDED (broken in v6)", added), ("REMOVED (fixed in v6)", removed)):
    e, wn, u = split(cs)
    print(f"  {lbl}: {len(cs)}  ->  ERROR {len(e)} | WARNING {len(wn)} | unknown {len(u)}")
    if e:
        print(f"     ERROR codes: {sorted(e)[:40]}")

print("\n== NET ERROR-severity change (the blocking metric) ==")
e5, _, _ = split(v5); e6, _, _ = split(v6)
print(f"  v5 ERROR rules: {len(e5)}   v6 ERROR rules: {len(e6)}   net: {len(e6)-len(e5):+d}")
print(f"  ERROR added: {len(e6-e5)}   ERROR removed: {len(e5-e6)}")
print(f"  added-ERROR codes: {sorted(e6-e5)}")
print(f"  removed-ERROR codes: {sorted(e5-e6)[:50]}")
