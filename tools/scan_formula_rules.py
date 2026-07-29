"""Scan all formula/validation linkbase files in the taxonomy package and tally
assertion types, test-expression shapes, severities, and filter kinds — so the
constraint solver knows exactly which patterns to implement and at what frequency.
"""
import re
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
pkg_root = sys.argv[1] if len(sys.argv) > 1 else (
    r"C:\Users\177069\ClaudeLearning\boebanking400\Banking_4.0.0")

VA = "http://xbrl.org/2008/assertion/value"
EA = "http://xbrl.org/2008/assertion/existence"
CA = "http://xbrl.org/2008/assertion/consistency"

# locate candidate linkbase files (val dirs + any *.xml with assertions)
files = [p for p in Path(pkg_root).rglob("*.xml") if "/val/" in p.as_posix() or "\\val\\" in str(p)]
print(f"candidate val/*.xml files: {len(files)}")

assertion_types = Counter()
severities = Counter()
filter_kinds = Counter()
func_tokens = Counter()
shape_counts = Counter()
total_assertions = 0
examples = {}

FUNC_RE = re.compile(r"([a-zA-Z_][\w]*):([a-zA-Z_][\w\-]*)\s*\(")
BAREFUNC_RE = re.compile(r"(?<![:\w])(matches|sum|abs|not|min|max|count|exp|if|then|else|and|or)\s*\(")


def shape_of(test):
    if test is None:
        return "(none)"
    t = test
    # normalize variable names and numbers
    t = re.sub(r"\$v?\d+\w*", "$V", t)
    t = re.sub(r"\$[A-Za-z_]\w*", "$V", t)
    t = re.sub(r"\b\d+(\.\d+)?\b", "N", t)
    t = re.sub(r"\s+", " ", t).strip()
    # collapse repeated $V , $V
    t = re.sub(r"(\$V(, )?)+", "$V*", t)
    return t[:90]


for f in files:
    try:
        tree = etree.parse(str(f))
    except Exception as e:
        continue
    root = tree.getroot()
    for el in root.iter():
        q = etree.QName(el)
        ns, ln = q.namespace, q.localname
        if ns in (VA, EA, CA) and ln.endswith("Assertion"):
            total_assertions += 1
            assertion_types[f"{ln}"] += 1
            test = el.get("test")
            sh = shape_of(test)
            shape_counts[sh] += 1
            if sh not in examples and test:
                examples[sh] = (el.get("id"), test[:160])
            if test:
                for m in FUNC_RE.finditer(test):
                    func_tokens[f"{m.group(1)}:{m.group(2)}"] += 1
                for m in BAREFUNC_RE.finditer(test):
                    func_tokens[m.group(1)] += 1
        # filter element kinds (by namespace localname)
        if ns and ("filter" in ns or ns.endswith("/concept") or ns.endswith("/dimension")):
            filter_kinds[ln] += 1

print(f"\ntotal assertions: {total_assertions}")
print(f"\nassertion types: {dict(assertion_types)}")
print(f"\nseverities: (parsed separately)")
print(f"\nfilter element kinds (top 20):")
for k, c in filter_kinds.most_common(20):
    print(f"  {k}: {c}")
print(f"\nfunction/operator tokens in tests (top 30):")
for k, c in func_tokens.most_common(30):
    print(f"  {k}: {c}")
print(f"\ntop 25 test-expression SHAPES (normalized):")
for sh, c in shape_counts.most_common(25):
    print(f"  [{c:5d}] {sh}")
print(f"\nexamples for top shapes:")
for sh, c in shape_counts.most_common(12):
    eid, ex = examples.get(sh, ("", ""))
    print(f"  [{c}] {sh}\n        e.g. {eid}: {ex}")
