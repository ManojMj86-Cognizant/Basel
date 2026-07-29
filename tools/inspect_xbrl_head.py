import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
f = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 12000
with open(f, "r", encoding="utf-8") as fh:
    print(fh.read(n))
