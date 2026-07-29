"""Diagnostic: inspect how bind() groups the RFB007 cross-table-sum and
conditional-empty rules, to confirm the row-merge root cause."""
import sys
from pathlib import Path

ROOT = r"C:\Users\177069\ClaudeLearning"
sys.path.insert(0, fr"{ROOT}\boe_xbrl_gen\src")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import solve_all
from instance import Instance
from resolver import bind

GEN = fr"{ROOT}\boe_xbrl_gen\out\sweep\RFB007.gen.xbrl"
VAL = fr"{ROOT}\boebanking400\Banking_4.0.0\www.bankofengland.co.uk\data\xbrl\fws\banking\structural_reform\2021-07-31\val"
CACHE = fr"{ROOT}\boe_xbrl_gen\out\sweep\rules_structural_reform_2021-07-31.pkl"
import json
DEFAULTS = json.loads(Path(fr"{ROOT}\boe_xbrl_gen\model\dim_defaults.json").read_text(encoding="utf-8"))

inst = Instance(GEN)
rules = solve_all.parse_all_rules(VAL, cache=CACHE)
by_id = {r.id: r for r in rules}
print(f"instance facts={len(inst.facts)}  rules={len(rules)}")

for rid in ("boe_boe_b1042_m", "boe_boe_b1129_m"):
    r = by_id.get(rid)
    if not r:
        print(f"!! {rid} not found"); continue
    print(f"\n===== {rid}  test={r.test}")
    bs = bind(r, inst, DEFAULTS)
    nonempty = [b for b in bs if any(b["vars"][n] for n in r.variables)]
    print(f"  total groups={len(bs)}  groups-with-facts={len(nonempty)}")
    # histogram of per-variable fact counts across groups that have the target var
    from collections import Counter
    hist = {n: Counter() for n in r.variables}
    for b in nonempty:
        for n in r.variables:
            hist[n][len(b["vars"][n])] += 1
    for n in r.variables:
        print(f"  ${n} seq={r.variables[n].sequence}: count-per-group histogram "
              f"{{nfacts:ngroups}} = {dict(sorted(hist[n].items()))}")
    # groups where the (non-seq) target var is present AND the other var has facts
    both = [b for b in nonempty if len(b["vars"].get("v0", [])) == 1 and b["vars"].get("v1")]
    print(f"  groups with v0==1 AND v1 non-empty: {len(both)}")
    # dump full dims/typed of a v0 fact and a v1 fact to see what they share
    if rid == "boe_boe_b1042_m":
        v0f = next((b["vars"]["v0"][0] for b in nonempty if b["vars"].get("v0")), None)
        v1f = next((b["vars"]["v1"][0] for b in nonempty if b["vars"].get("v1")), None)
        for tag, f in (("v0", v0f), ("v1", v1f)):
            if f:
                print(f"  --- sample {tag} fact concept={f.concept.split('}')[-1]} "
                      f"val={f.value}")
                print(f"      dims={ {d.split('}')[-1]: m.split('}')[-1] for d,m in f.dims.items()} }")
                print(f"      typed={ {d.split('}')[-1]: t for d,t in f.typed.items()} }")
