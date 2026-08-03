"""P2.1 collapse-map gate. For each sub-core cross-view additive rule (total = Σ details), resolve the total
and detail cells and check whether the details differ from the total by exactly ONE dimension (the collapsed
axis) — i.e. total is a clean MARGINAL of the details. If most are clean single-axis marginals, one leaf
tensor exists and P2.2 is viable; if signatures are messy/multi-axis, the approach is blocked (accept v15).
Run from boe_xbrl_gen/ with PYTHONIOENCODING=utf-8."""
import sys, json
sys.path.insert(0, "src"); sys.path.insert(0, ".")
import workbook_rules
from src import dim_drs
from collections import Counter

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
CEG_TABLES = {"OF09.01.01.01", "OF09.02.01.01"}
DEF = {d: dim_drs.local(m) for d, m in dim_drs.localize_defaults(
    json.load(open(f"{BASE}/model.json", encoding="utf-8")).get("dim_defaults", {})).items()}
res = workbook_rules.CellResolver(EXT)
R = workbook_rules.load_workbook_rules(WB, "banking_reporting")

# representative sub-core cross-view rules (grade collapse, country, CCR, sub-table breakdowns)
CODES = ["b0752", "b0282", "b0283", "b0284", "b0834", "b0872", "b0735", "b0736", "b0739", "b0876"]


def sig(dp):
    """full dim signature (dim-local -> member-local), CEG injected for OF09.x, defaults kept (informative)."""
    d = {dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}
    if dp.get("table", "").upper() in CEG_TABLES:
        d["CEG"] = "x1"
    return d


clean = messy = 0
for code in CODES:
    r = next((x for x in R if x["code"] == "boe_" + code or x["code"] == code or code in x["code"]), None)
    if not r:
        print(f"\n[{code}] NOT FOUND"); continue
    asts = workbook_rules.expand_scoped_asts(r)
    if not asts:
        print(f"\n[{r['code']}] non-additive / unscoped (parse=None)"); continue
    a = asts[0]                                   # first concrete instance
    tot_side = "lhs" if len(a["lhs"]) == 1 else "rhs"
    det_side = "rhs" if tot_side == "lhs" else "lhs"
    tdps = res.resolve(a[tot_side][0]["cell"])
    if not tdps:
        print(f"\n[{r['code']}] total didn't resolve"); continue
    tsig = sig(tdps[0]); ttab = tdps[0]["table"]
    print(f"\n[{r['code']}] tables={r['tables']}")
    print(f"   TOTAL  {ttab}: {tsig}")
    diffdims = Counter()
    ndet = 0
    for t in a[det_side]:
        for dp in res.resolve(t["cell"]):
            dsig = sig(dp); ndet += 1
            added = {k: v for k, v in dsig.items() if tsig.get(k) != v}   # dims where detail != total
            removed = {k for k in tsig if k not in dsig}
            for k in list(added) + list(removed):
                diffdims[k] += 1
            if ndet <= 3:
                print(f"   detail {dp['table']}: differs on {sorted(set(added) | removed)}  ({dsig})")
    axes = [k for k, n in diffdims.items()]
    verdict = "CLEAN single-axis marginal" if len(axes) == 1 else ("MULTI-AXIS" if axes else "IDENTICAL?")
    print(f"   -> collapse axis/axes: {axes}   [{verdict}]  ({ndet} detail cells)")
    if len(axes) == 1:
        clean += 1
    else:
        messy += 1

print(f"\n==== P2.1 verdict: {clean} clean single-axis, {messy} multi-axis/messy (of {clean+messy} resolved) ====")
