"""Re-diagnose (correcting the false 'conflation' claim): confirm b0834's detail cells have DISTINCT keys
(full dims), and check whether the OF34.07 internal tree composes — i.e. do b0834's detail keys that are
internal-totals actually appear as parents in the tree built from b0830-33 (matching on the SAME col/z)?"""
import sys, json
sys.path.insert(0, "src"); sys.path.insert(0, ".")
import workbook_rules
from src import dim_drs

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
DEF = {dim_drs.local(d): dim_drs.local(m) for d, m in dim_drs.localize_defaults(json.load(open(f"{BASE}/model.json", encoding="utf-8")).get("dim_defaults", {})).items()}
res = workbook_rules.CellResolver(EXT)
R = workbook_rules.load_workbook_rules(WB, "banking_reporting")


def dset(items):
    return frozenset((k, v) for k, v in items if DEF.get(k) != v)


def key(dp):
    return (dim_drs.local(dp["concept"]), dset({dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}.items()))


b0834 = next(x for x in R if "b0834" in x["code"])
a = workbook_rules.expand_scoped_asts(b0834)[0]
print("b0834 first-instance detail keys (FULL dims):")
det_keys = []
for t in a["rhs"]:
    for dp in res.resolve(t["cell"]):
        k = key(dp); det_keys.append(k)
        print(f"  {k[0]}  {dict(sorted(k[1]))}")
print(f"distinct detail keys: {len(set(det_keys))} of {len(det_keys)}")

# build internal tree (OF34.07 = ΣOF34.07) and check overlap with b0834 details
tree = {}
for r in R:
    for aa in workbook_rules.expand_scoped_asts(r):
        if aa["op"] != "i=":
            continue
        ts = "lhs" if len(aa["lhs"]) == 1 else "rhs"
        os_ = "rhs" if ts == "lhs" else "lhs"
        td = res.resolve(aa[ts][0]["cell"])
        if len(td) != 1 or td[0]["table"].upper() != "OF34.07.01.01":
            continue
        kids = [key(dp) for x in aa[os_] for dp in res.resolve(x["cell"])]
        if kids and all(res.resolve(x["cell"]) and all(dp["table"].upper() == "OF34.07.01.01" for dp in res.resolve(x["cell"])) for x in aa[os_]):
            tree[key(td[0])] = kids
print(f"\ninternal-tree parents: {len(tree)}")
internal_details = [k for k in det_keys if k in tree]
print(f"b0834 detail keys that ARE internal-tree parents (should recurse): {len(internal_details)} of {len(det_keys)}")
for k in internal_details[:3]:
    print(f"  parent {k[0]} {dict(sorted(k[1]))} -> {len(tree[k])} children")
