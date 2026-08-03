"""Probe OF24.01.01.01 structure for the Group C sqrt fix (b0361 r0070<-r0080..0120, b0363 r0180<-r0190..0230).
Print concept+dims for target and input rows at one column, and how the open axis is carried, so the fix can
match inputs to each target instance correctly."""
import sys, json
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
V15 = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v15.xbrl"
X = "http://www.xbrl.org/2003/instance"
res = workbook_rules.CellResolver(EXT)


def show(r, c):
    dps = res.resolve({"table": "OF24.01.01.01", "r": r, "c": c, "z": []})
    for dp in dps:
        dd = {dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}
        print(f"  r{r} c{c}: concept={dim_drs.local(dp['concept'])}  dims={dd}")
    if not dps:
        print(f"  r{r} c{c}: (no datapoint)")


print("=== b0363 target r0180 + inputs r0190..0230 at c0050 ===")
for r in ("0180", "0190", "0200", "0210", "0220", "0230"):
    show(r, "0050")
print("=== b0361 target r0070 + inputs r0080..0120 at c0050 ===")
for r in ("0070", "0080", "0090", "0100", "0110", "0120"):
    show(r, "0050")

# how many contexts carry the r0180 concept, and what dims vary (the open axis)?
raw = open(V15, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
root = etree.fromstring(raw); cd = {}
for ctx in root.findall(f"{{{X}}}context"):
    dd = {}; sc = ctx.find(f"{{{X}}}scenario")
    if sc is not None:
        for em in sc:
            if em.get("dimension") and etree.QName(em).localname == "explicitMember":
                dd[dim_drs.local(em.get("dimension"))] = dim_drs.local((em.text or "").strip())
    cd[ctx.get("id")] = dd
tgt = res.resolve({"table": "OF24.01.01.01", "r": "0180", "c": "0050", "z": []})
if tgt:
    tconcept = dim_drs.local(tgt[0]["concept"])
    ctxs = [(el.get("contextRef"), (el.text or "").strip()) for el in root
            if dim_drs.local(etree.QName(el).localname) == tconcept and el.get("contextRef")]
    print(f"\nr0180 concept '{tconcept}' appears in {len(ctxs)} facts")
    for cr, tx in ctxs[:6]:
        print(f"   ctx {cr} dims={cd.get(cr)} value={tx}")
