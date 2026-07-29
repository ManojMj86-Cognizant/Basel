"""Diff two classify_fails reports: which failing rule codes were ADDED / REMOVED per level."""
import json, sys
a = json.load(open(sys.argv[1], encoding="utf-8"))   # baseline
b = json.load(open(sys.argv[2], encoding="utf-8"))   # after-fix
for lvl in ("L1_single_additive", "L2_single_cmp", "L3_cross_additive", "L4_cross_cmp"):
    sa = {f["code"] for f in a["failing"].get(lvl, [])}
    sb = {f["code"] for f in b["failing"].get(lvl, [])}
    added = sb - sa; removed = sa - sb
    if added or removed:
        print(f"{lvl}:  +added {sorted(added)}   -removed {sorted(removed)}")
    else:
        print(f"{lvl}:  (no change)")
