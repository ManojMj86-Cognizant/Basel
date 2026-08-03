"""P2.1 FINAL gate: hierarchy- and default-aware collapse test on the sub-core cross-view rules.
A rule total = Σ details is a CLEAN MARGINAL if, for every dimension where details differ from the total,
EITHER (a) the total omits it / holds its DEFAULT member (= aggregates over all of that dim), OR (b) the
total holds a member M whose complete-breakdown leaves (member_hier) cover the details' members on that dim.
Any dimension not explained by (a)/(b) is a genuine residual (messy). If all sub-core rules are clean, P2.1
passes → proceed to P2.2. Run from boe_xbrl_gen/ with PYTHONIOENCODING=utf-8."""
import sys, json
sys.path.insert(0, "src"); sys.path.insert(0, ".")
import workbook_rules
from src import dim_drs, member_hier

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
model = json.load(open(f"{BASE}/model.json", encoding="utf-8"))
DEF = {dim_drs.local(d): dim_drs.local(m) for d, m in dim_drs.localize_defaults(model.get("dim_defaults", {})).items()}
H = member_hier.load_hierarchies(EXT)
res = workbook_rules.CellResolver(EXT)
R = workbook_rules.load_workbook_rules(WB, "banking_reporting")
CODES = ["b0752", "b0282", "b0283", "b0284", "b0834", "b0872", "b0735", "b0736", "b0739", "b0876"]


def dom_of(qname):
    if not qname or ":" not in qname:
        return None
    return qname.split(":")[0].replace("boe_eba_", "").replace("boe_", "").replace("eba_", "").lower()


def sig(dp):
    return {dim_drs.local(dk): mv for dk, mv in dp["dims"].items()}      # dim_local -> member qname


def leaves(domain, mem_local):
    return member_hier.all_descendants(H.get(domain, {}), mem_local)   # incl. intermediate sub-totals


clean = messy = 0
for code in CODES:
    r = next((x for x in R if x["code"] == "boe_" + code or code in x["code"]), None)
    if not r:
        print(f"[{code}] NOT FOUND"); continue
    asts = workbook_rules.expand_scoped_asts(r)
    if not asts:
        print(f"[{r['code']}] non-additive/unscoped"); continue
    a = asts[0]
    tside = "lhs" if len(a["lhs"]) == 1 else "rhs"
    dside = "rhs" if tside == "lhs" else "lhs"
    tdps = res.resolve(a[tside][0]["cell"])
    if not tdps:
        print(f"[{r['code']}] total unresolved"); continue
    tsig = sig(tdps[0])
    dsigs = [sig(dp) for t in a[dside] for dp in res.resolve(t["cell"])]
    if not dsigs:
        print(f"[{r['code']}] no details"); continue
    dims = set(tsig) | {k for d in dsigs for k in d}
    resid = []
    for dim in dims:
        tq = tsig.get(dim)
        tmem = dim_drs.local(tq) if tq else DEF.get(dim)
        dmems = set()
        for d in dsigs:
            dq = d.get(dim)
            dmems.add(dim_drs.local(dq) if dq else DEF.get(dim))
        if dmems == {tmem}:
            continue                                             # shared dim, not collapsed
        # collapse axis — is it explained?
        if tmem == DEF.get(dim):
            continue                                             # (a) total aggregates over all of dim
        domain = dom_of(tq) or next((dom_of(d.get(dim)) for d in dsigs if d.get(dim)), None)
        lv = leaves(domain, tmem) if domain else {tmem}
        realdmems = {m for m in dmems if m != DEF.get(dim)}
        if realdmems <= lv:
            continue                                             # (b) hierarchy: total member covers details
        resid.append((dim, tmem, sorted(dmems)[:5]))
    if resid:
        messy += 1
        print(f"[{r['code']}] MESSY residual dims: {resid}")
    else:
        clean += 1
        print(f"[{r['code']}] CLEAN marginal ✓")

print(f"\n==== P2.1 FINAL: {clean} clean / {messy} messy (of {clean+messy}) ====")
print("GATE PASS → proceed to P2.2" if messy == 0 else "GATE: residuals remain — inspect before P2.2")
