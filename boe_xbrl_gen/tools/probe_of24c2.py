"""Find the failing b0363 instance's facts by value and print their context dims, to see how the target
(27135454) differs from its 5 inputs (6356000/5425000/225000/5819000/9989000) beyond LQH."""
import sys
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
from src import dim_drs

V15 = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v15.xbrl"
X = "http://www.xbrl.org/2003/instance"
TARGETS = {"27135454": "TARGET r0180", "6356000": "in r0190", "5425000": "in r0200",
           "225000": "in r0210", "5819000": "in r0220", "9989000": "in r0230"}

raw = open(V15, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
root = etree.fromstring(raw); cd = {}
for ctx in root.findall(f"{{{X}}}context"):
    dd = {}; sc = ctx.find(f"{{{X}}}scenario")
    if sc is not None:
        for em in sc:
            if em.get("dimension") and etree.QName(em).localname == "explicitMember":
                dd[dim_drs.local(em.get("dimension"))] = dim_drs.local((em.text or "").strip())
    cd[ctx.get("id")] = dd

for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    v = (el.text or "").strip()
    if v in TARGETS:
        print(f"{TARGETS[v]:14} val={v:>10}  concept={dim_drs.local(etree.QName(el).localname)}  dims={cd.get(cr)}")
