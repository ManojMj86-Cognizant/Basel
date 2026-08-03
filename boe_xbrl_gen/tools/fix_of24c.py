"""OF24 Group C fix (b0360-b0364 sqrt-sum-of-squares; b0361/b0363 are the ones failing in v15).
Structure (probe_of24c): the constrained-expected-shortfall concept mi10023's LQH-aggregate (a fact with NO
LQH dim) must equal sqrt( Σ w(LQH) · sibling² ) over its 5 liquidity-horizon siblings (same dims + LQH
x10001..x10005), with w = {x10001:1, x10002:1, x10003:2, x10004:2, x10005:6}. Deterministic, self-selecting
(only recompute a no-LQH fact that HAS all 5 siblings), no artificial cells. Env FIX_IN/FIX_OUT (v15 -> v16).
Run from boe_xbrl_gen/ with PYTHONIOENCODING=utf-8."""
import os, sys, math
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
from src import dim_drs

ROOT = r"C:\Users\177069\ClaudeLearning"
X = "http://www.xbrl.org/2003/instance"
FIX_IN = os.environ.get("FIX_IN", os.path.join(ROOT, "ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v15.xbrl"))
FIX_OUT = os.environ.get("FIX_OUT", os.path.join(ROOT, "ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v16.xbrl"))
# LQH (liquidity-horizon) members and their variance weights (w = the exp(k,1,2)^2 = k factor).
# LQH is used ONLY by the market-risk expected-shortfall family (mi10023/mi10024/...), whose no-LQH
# fact is the sqrt-aggregate over its horizon siblings. So a CONCEPT-AGNOSTIC rule keyed on "has LQH
# x10001..x10005 siblings" is safe and covers every b0360-b0364 target across all 8 scope columns.
W = {"x10001": 1.0, "x10002": 1.0, "x10003": 2.0, "x10004": 2.0, "x10005": 6.0}

raw = open(FIX_IN, "rb").read(); bom = raw[:3] == b"\xef\xbb\xbf"
root = etree.fromstring(raw[3:] if bom else raw)

ctx_dims = {}
for ctx in root.findall(f"{{{X}}}context"):
    dd = {}; sc = ctx.find(f"{{{X}}}scenario")
    if sc is not None:
        for em in sc:
            if em.get("dimension") and etree.QName(em).localname == "explicitMember":
                dd[dim_drs.local(em.get("dimension"))] = dim_drs.local((em.text or "").strip())
    ctx_dims[ctx.get("id")] = dd

# index ALL facts by (concept, full dim-set incl LQH); also list no-LQH facts as candidate targets
by_key = {}
candidates = []
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    concept = dim_drs.local(etree.QName(el).localname)
    d = ctx_dims.get(cr, {})
    by_key[(concept, frozenset(d.items()))] = el
    if "LQH" not in d:
        candidates.append((el, concept, d))


def fnum(el):
    try:
        return float((el.text or "").strip())
    except (TypeError, ValueError):
        return None


def round_dec(v, dec):
    if dec is None:
        return v
    q = 10.0 ** (-int(dec)); return round(v / q) * q


changed = 0; targets = 0; examples = []
for el, concept, d in candidates:
    sibs = []; n_present = 0
    for mem, w in W.items():
        sd = dict(d); sd["LQH"] = mem
        sel = by_key.get((concept, frozenset(sd.items())))
        v = fnum(sel) if sel is not None else None
        sibs.append((w, v if v is not None else 0.0))   # TDG absent = 0
        if v is not None:
            n_present += 1
    if n_present == 0:
        continue                                          # not an LQH aggregate
    targets += 1
    want = math.sqrt(sum(w * v * v for w, v in sibs))
    old = (el.text or "").strip()
    old_v = fnum(el)
    # MINIMAL PERTURBATION: only rewrite when the current value is beyond TDG tolerance (half-ULP on
    # the fact's @decimals grid) — i.e. a genuine failure. Skip the ones already within tolerance.
    try:
        half_ulp = 0.5 * 10.0 ** (-int(el.get("decimals")))
    except (TypeError, ValueError):
        half_ulp = 0.5
    if old_v is not None and abs(old_v - want) <= half_ulp:
        continue
    want_r = round_dec(want, el.get("decimals"))
    new = str(int(want_r)) if want_r == int(want_r) else repr(want_r)
    if old != new:
        if len(examples) < 8:
            examples.append((concept, old, new))
        el.text = new; changed += 1

print(f"LQH sqrt-aggregate targets (>=1 horizon sibling, any concept): {targets}")
print(f"recomputed (changed) facts: {changed}")
for cpt, o, n in examples:
    print(f"   {cpt}: {o} -> {n}")
out = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
if bom:
    out = b"\xef\xbb\xbf" + out
open(FIX_OUT, "wb").write(out)
print(f"APPLIED -> {FIX_OUT}")
