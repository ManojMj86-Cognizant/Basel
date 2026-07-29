import sys, time, glob, os
sys.path.insert(0, r"C:\Users\177069\ClaudeLearning\boe_xbrl_gen\src")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import formula_rules as fr

val = r"C:\Users\177069\ClaudeLearning\boebanking400\Banking_4.0.0\www.bankofengland.co.uk\data\xbrl\fws\banking\banking_reporting\2026-02-27\val"
# find a few assertion files and time parsing
files = sorted(glob.glob(os.path.join(val, "vr-*.xml")))
picked = []
for f in files:
    with open(f, "rb") as fh:
        if b"valueAssertion" in fh.read():
            picked.append(f)
    if len(picked) >= 5:
        break
for f in picked:
    sz = os.path.getsize(f)
    t0 = time.time()
    rules = fr.parse_file(f)
    dt = time.time() - t0
    print(f"{os.path.basename(f)}  size={sz}B  rules={len(rules)}  parse={dt*1000:.0f}ms")
