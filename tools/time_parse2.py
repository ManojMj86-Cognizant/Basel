import sys, time, os
sys.path.insert(0, r"C:\Users\177069\ClaudeLearning\boe_xbrl_gen\src")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import formula_rules as fr

val = r"C:\Users\177069\ClaudeLearning\boebanking400\Banking_4.0.0\www.bankofengland.co.uk\data\xbrl\fws\banking"
# correctness check
ss = val + r"\capital_plus_sddt\2026-02-27\val\vr-boe_b0013_ss.xml"
r = fr.parse_file(ss)[0]
print("b0013_ss test:", r.test, "| vars:", list(r.variables), "| common dims:", list(r.common.dims))

# time the monster files
for name in ["banking_reporting\\2026-02-27\\val\\vr-boe_b0658.xml",
             "banking_reporting\\2026-02-27\\val\\vr-boe_b0733.xml",
             "banking_reporting\\2026-02-27\\val\\vr-boe_b0192.xml"]:
    f = os.path.join(val, name)
    sz = os.path.getsize(f)
    t0 = time.time()
    rules = fr.parse_file(f)
    dt = time.time() - t0
    nvars = len(rules[0].variables) if rules else 0
    print(f"{os.path.basename(f)}  size={sz/1e6:.1f}MB  rules={len(rules)}  vars={nvars}  parse={dt:.2f}s")
