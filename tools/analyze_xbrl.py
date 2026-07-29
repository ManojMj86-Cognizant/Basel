import sys
from collections import Counter
from lxml import etree

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
path = sys.argv[1]

XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
FIND = "http://www.eurofiling.info/xbrl/ext/filing-indicators"

n_ctx = n_unit = n_fact = n_fi = 0
elem_counts = Counter()
dims_used = Counter()
typed_dims = Counter()
unit_measures = Counter()
ctx_dim_count = Counter()
sample_ctx = []
sample_facts = []
nil_facts = 0

context = etree.iterparse(path, events=("end",))
root = None
for event, el in context:
    if root is None:
        r = el
        while r.getparent() is not None:
            r = r.getparent()
        root = r
    tag = etree.QName(el).localname
    ns = etree.QName(el).namespace
    if ns == XBRLI and tag == "context":
        n_ctx += 1
        dmembers = el.findall(f".//{{{XBRLDI}}}explicitMember")
        tmembers = el.findall(f".//{{{XBRLDI}}}typedMember")
        for m in dmembers:
            dims_used[m.get("dimension")] += 1
        for m in tmembers:
            typed_dims[m.get("dimension")] += 1
        ctx_dim_count[len(dmembers) + len(tmembers)] += 1
        if len(sample_ctx) < 3 and (dmembers or tmembers):
            sample_ctx.append(etree.tostring(el, pretty_print=True).decode())
    elif ns == XBRLI and tag == "unit":
        n_unit += 1
        for meas in el.findall(f".//{{{XBRLI}}}measure"):
            unit_measures[meas.text] += 1
    elif ns == FIND and tag == "filingIndicator":
        n_fi += 1
    elif el.get("contextRef") is not None:
        # a fact
        n_fact += 1
        elem_counts[f"{etree.QName(el).prefix or ''}:{tag}" if False else tag] += 1
        if el.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true":
            nil_facts += 1
        if len(sample_facts) < 8:
            sample_facts.append((etree.QName(el).namespace, tag, el.get("contextRef"),
                                 el.get("unitRef"), el.get("decimals"), (el.text or "")[:40]))
    # Only clear completed top-level subtrees, so context children survive until read.
    if el.getparent() is root:
        el.clear()
        while el.getprevious() is not None:
            del root[0]

print(f"contexts:          {n_ctx}")
print(f"units:             {n_unit}")
print(f"filingIndicators:  {n_fi}")
print(f"facts:             {n_fact}")
print(f"  nil facts:       {nil_facts}")
print(f"distinct fact elements (metrics): {len(elem_counts)}")
print(f"\nunit measures: {dict(unit_measures)}")
print(f"\ncontext dimension-count distribution (dims->#contexts): {dict(sorted(ctx_dim_count.items()))}")
print(f"\nexplicit dimensions used ({len(dims_used)}):")
for d, c in dims_used.most_common(40):
    print(f"  {d}: {c}")
print(f"\ntyped dimensions used ({len(typed_dims)}):")
for d, c in typed_dims.most_common():
    print(f"  {d}: {c}")
print(f"\ntop 25 metrics by fact count:")
for e, c in elem_counts.most_common(25):
    print(f"  {e}: {c}")
print(f"\nsample facts (ns, tag, ctx, unit, decimals, value):")
for s in sample_facts:
    print(f"  {s}")
print(f"\nsample contexts with dimensions:")
for s in sample_ctx:
    print(s)
