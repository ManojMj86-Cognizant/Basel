"""Feasibility test for the leaf-first fix of b0834 (OF34.07 r0180 = Σ detail rows).
For each (col,z) instance: r0180 is pinned by cross-rule b0872 (=ΣOF08.01); some detail rows are pinned by
b0830-33 (=ΣOF08.01 subsets); the rest (r0040/0050/0060/0170) are FREE leaves (currently 0). b0834 holds iff
the free leaves can be set to gap = r0180 - Σ(determined detail) with gap>=0. Count gap>=0 (fixable) vs <0."""
import sys, json
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs, instance_build
from collections import defaultdict

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
V15 = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v15.xbrl"
X = "http://www.xbrl.org/2003/instance"
CEG_TABLES = {"OF09.01.01.01", "OF09.02.01.01"}
DEF = {d: dim_drs.local(m) for d, m in dim_drs.localize_defaults(
    json.load(open(f"{BASE}/model.json", encoding="utf-8")).get("dim_defaults", {})).items()}


def dset(items):
    return frozenset((k, v) for k, v in items if DEF.get(k) != v)


R = workbook_rules.load_workbook_rules(WB, "banking_reporting")
res = workbook_rules.CellResolver(EXT)


def ck(dp):
    d = {dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}
    if dp.get("table", "").upper() in CEG_TABLES:
        d["CEG"] = "x1"
    return (dim_drs.local(dp["concept"]), dset(d.items()))


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

# which cells are additive-defined (determined) anywhere?
determined = set()
for r in R:
    if r.get("deactivated"):
        continue
    pe = workbook_rules.parse_expression(r.get("expression", ""))
    if not (pe and pe.get("op") == "i="):
        continue
    for a in workbook_rules.expand_scoped_asts(r):
        if a["op"] != "i=":
            continue
        for side in ("lhs", "rhs"):
            if len(a[side]) == 1:
                for dp in res.resolve(a[side][0]["cell"]):
                    determined.add(ck(dp))

rr = next((x for x in R if "b0834" in x["code"]), None)
ge = lt = miss = 0; gaps = []
for a in workbook_rules.expand_scoped_asts(rr):
    # lhs = r0180 (single total), rhs = detail rows
    lhs = a["lhs"]; rhs = a["rhs"]
    if len(lhs) != 1:
        continue
    tot_dps = res.resolve(lhs[0]["cell"])
    if not tot_dps:
        miss += 1; continue
    r0180 = facts.get(ck(tot_dps[0]))
    if r0180 is None:
        miss += 1; continue
    det_sum = 0.0; free_cur = 0.0; nfree = 0
    for t in rhs:
        for dp in res.resolve(t["cell"]):
            k = ck(dp)
            if k in determined and k != ck(tot_dps[0]):
                det_sum += facts.get(k, 0.0)
            else:
                free_cur += facts.get(k, 0.0); nfree += 1
    gap = r0180 - det_sum
    gaps.append((gap, nfree))
    if gap >= -0.5:
        ge += 1
    else:
        lt += 1

print(f"b0834 concrete instances evaluated: {ge+lt} (missing {miss})")
print(f"  gap >= 0 (FIXABLE: free leaves absorb the coupling): {ge}")
print(f"  gap <  0 (needs reducing determined rows too): {lt}")
if gaps:
    import statistics
    print(f"  gap stats: min={min(g for g,_ in gaps):.0f} max={max(g for g,_ in gaps):.0f} "
          f"median={statistics.median(g for g,_ in gaps):.0f}")
    print(f"  avg #free detail cells per instance: {statistics.mean(n for _,n in gaps):.1f}")
