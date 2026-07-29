"""Histogram of @decimals across the shipped file, plus the decimals used by OF07's mi125/mi132."""
import os
from lxml import etree
from collections import Counter
F = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID.xbrl"
raw = open(F, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
root = etree.fromstring(raw)
hist = Counter(); per_local = {}
for el in root:
    d = el.get("decimals")
    if d is None:
        continue
    hist[d] += 1
    ln = etree.QName(el).localname
    per_local.setdefault(ln, Counter())[d] += 1
print("decimals histogram (all facts):")
for d, n in hist.most_common():
    print(f"  decimals={d:>4} : {n}")
print("\nmi125 / mi132 (OF07 monetary):")
for ln in ("mi125", "mi132", "mi119", "mi116"):
    print(f"  {ln}: {dict(per_local.get(ln, {}))}")
