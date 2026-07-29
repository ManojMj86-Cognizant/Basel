"""Module-level parity for src/dim_drs.py (no Arelle).

A fact in the Arelle-valid SAMPLE must be dimensionally valid in AT LEAST ONE module table.
If a fact is rejected by EVERY table whose hypercube admits its metric -> real over-prune bug.
For the BROKEN file, facts rejected by every candidate table are the genuine dimInvalid ones.
"""
import json
import sys
import time
from collections import Counter

sys.path.insert(0, ".")
from lxml import etree
from src import dim_drs

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
PKG = f"{BASE}/Banking_4.0.0"
MODEL = f"{BASE}/model.json"
RESULT = f"{BASE}/generated/result.json"
SAMPLE = "../boebankingtaxonomysampleinstancesv400/ABCDEFGHIJ0123456789_GB_banking_PRA001_2026-02-28_20260220142410000.xbrl"
BROKEN = f"{BASE}/generated/ABCDEFGHIJ0123456789_pra001_2026-02-28.xbrl"
XBRLI = "http://www.xbrl.org/2003/instance"


def load_facts(path):
    data = open(path, "rb").read()
    data = data[3:] if data[:3] == b"\xef\xbb\xbf" else data
    root = etree.fromstring(data)
    cd = {}
    for ctx in root.findall(f"{{{XBRLI}}}context"):
        dims = {}
        scen = ctx.find(f"{{{XBRLI}}}scenario")
        if scen is not None:
            for em in scen:
                if not em.get("dimension"):
                    continue
                if etree.QName(em).localname == "explicitMember":
                    dims[dim_drs.local(em.get("dimension"))] = dim_drs.qmem((em.text or "").strip())
                else:  # typedMember — only presence matters for dimensional validity
                    dims[dim_drs.local(em.get("dimension"))] = "(typed)"
        cd[ctx.get("id")] = dims
    out = []
    for el in root:
        cref = el.get("contextRef")
        if cref is not None:
            out.append((dim_drs.local(etree.QName(el).localname), cd.get(cref, {})))
    return out


def main():
    tables = json.load(open(RESULT, encoding="utf-8"))["instances"][0]["tables"]
    defaults = dim_drs.localize_defaults(json.load(open(MODEL, encoding="utf-8")).get("dim_defaults", {}))

    t0 = time.time()
    drs_by_table = {}
    for t in tables:
        p = dim_drs.def_path_for(PKG, t)
        if p:
            try:
                drs_by_table[t] = dim_drs.TableDRS(p)
            except Exception as e:
                print("  parse-fail", t, e)
    # index: metric local -> [tables admitting it as primary]
    tables_by_primary = {}
    for t, d in drs_by_table.items():
        for prim in d.by_primary:
            tables_by_primary.setdefault(prim, []).append(t)
    print(f"built DRS for {len(drs_by_table)}/{len(tables)} tables in {time.time()-t0:.1f}s; "
          f"{len(tables_by_primary)} distinct primary metrics")

    for tag, path in (("SAMPLE(valid)", SAMPLE), ("BROKEN", BROKEN)):
        facts = load_facts(path)
        total = len(facts)
        no_primary = valid = invalid = 0
        invalid_examples = Counter()
        for concept, dims in facts:
            cand = tables_by_primary.get(concept)
            if not cand:
                no_primary += 1
                continue
            if any(drs_by_table[t].is_valid(concept, dims, defaults) for t in cand):
                valid += 1
            else:
                invalid += 1
                key = ",".join(f"{d}={m}" for d, m in sorted(dims.items())) or "(no dims)"
                invalid_examples[f"{concept}|{key}"] += 1
        print(f"\n[{tag}] facts={total}  metric-not-primary={no_primary}  "
              f"valid(some table)={valid}  INVALID(no table)={invalid}")
        for k, v in invalid_examples.most_common(10):
            print(f"    {v:4d}x  {k[:110]}")


if __name__ == "__main__":
    main()
