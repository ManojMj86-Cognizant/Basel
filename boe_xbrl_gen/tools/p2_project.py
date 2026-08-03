"""P2.2 projection proof (OF34.07 sub-core). Derive OF34.07 r0180 AND its determined detail rows ALL from the
SAME OF08.01 leaves (via the cross-table rules b0872 / b0830-33), then check the b0834 gap = r0180 - Σ(covered
details). If projecting from one consistent basis gives gap>=0 for (nearly) ALL instances — vs v15's 60/85 when
r0180 came from a different pass — the marginal projection reconciles b0834 BY CONSTRUCTION (free detail rows
absorb gap>=0). This is the core P2.2 evidence before building the full generator. Run from boe_xbrl_gen/."""
import sys, json
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs
from collections import defaultdict

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
V15 = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v15.xbrl"
X = "http://www.xbrl.org/2003/instance"
DEF = {d: dim_drs.local(m) for d, m in dim_drs.localize_defaults(json.load(open(f"{BASE}/model.json", encoding="utf-8")).get("dim_defaults", {})).items()}


def dset(items):
    return frozenset((k, v) for k, v in items if DEF.get(k) != v)


res = workbook_rules.CellResolver(EXT)
R = workbook_rules.load_workbook_rules(WB, "banking_reporting")


def ck(dp):
    return (dim_drs.local(dp["concept"]), dset({dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}.items()))


# v15 facts
raw = open(V15, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
root = etree.fromstring(raw); cd = {}
for c in root.findall(f"{{{X}}}context"):
    dd = {}; sc = c.find(f"{{{X}}}scenario")
    if sc is not None:
        for em in sc:
            if em.get("dimension") and etree.QName(em).localname == "explicitMember":
                dd[dim_drs.local(em.get("dimension"))] = dim_drs.local((em.text or "").strip())
    cd[c.get("id")] = dd
facts = {}
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    try:
        facts[(dim_drs.local(etree.QName(el).localname), dset(cd.get(cr, {}).items()))] = float((el.text or "").strip())
    except (ValueError, TypeError):
        pass


def derive_all_of3407_from_of08():
    """Scan ALL additive rules; wherever the lone target is an OF34.07 cell and EVERY source is OF08.01,
    record {OF34.07 target_key: Σ OF08.01 value from v15}. Captures the whole per-column/per-z family
    (b0872-0889 c0010, b1035 c0030, b1067/68 c0060, b0830-33 detail rows, …) automatically."""
    out = {}
    for r in R:
        if r.get("deactivated"):
            continue
        for a in workbook_rules.expand_scoped_asts(r):
            if a["op"] != "i=":
                continue
            tside = "lhs" if len(a["lhs"]) == 1 else "rhs"
            oside = "rhs" if tside == "lhs" else "lhs"
            tdps = res.resolve(a[tside][0]["cell"])
            if len(tdps) != 1 or tdps[0]["table"].upper() != "OF34.07.01.01":
                continue
            srcs = [dp for t in a[oside] for dp in res.resolve(t["cell"])]
            if not srcs or any(dp["table"].upper() != "OF08.01.01.01" for dp in srcs):
                continue                                # only pure OF34.07 = ΣOF08.01 rules
            s = 0.0
            for t in a[oside]:
                for dp in res.resolve(t["cell"]):
                    s += t["coef"] * facts.get(ck(dp), 0.0)
            out[ck(tdps[0])] = s
    return out


of3407 = derive_all_of3407_from_of08()
r0180 = of3407          # r0180 instances are keyed inside; detail rows too
det = of3407

# b0834: r0180 = Σ detail rows; classify determined (derived above) vs free; gap = r0180 - Σ determined
b0834 = next(x for x in R if "b0834" in x["code"])
ge = lt = nomatch = 0; gaps = []
for a in workbook_rules.expand_scoped_asts(b0834):
    if len(a["lhs"]) != 1:
        continue
    tdps = res.resolve(a["lhs"][0]["cell"])
    if not tdps:
        continue
    tk = ck(tdps[0])
    if tk not in r0180:                      # no b0872 derivation for this r0180 instance
        nomatch += 1; continue
    covered = 0.0
    for t in a["rhs"]:
        for dp in res.resolve(t["cell"]):
            k = ck(dp)
            if k in det:
                covered += det[k]
    gap = r0180[tk] - covered
    gaps.append(gap)
    if gap >= -0.5:
        ge += 1
    else:
        lt += 1

print(f"OF34.07 b0834 instances with a derived r0180 (b0872): {ge+lt}   (no b0872 match: {nomatch})")
print(f"  gap >= 0 (b0834 HOLDS by construction — free rows absorb): {ge}")
print(f"  gap <  0 (would still fail): {lt}")
print(f"  vs v15 (r0180 from a different pass) that was ~60/85 gap>=0")
if gaps:
    print(f"  gap min={min(gaps):.0f} max={max(gaps):.0f}")
