"""Module-level dimensional validity + boolean check on the SHIPPABLE output file."""
import json, sys, time
from collections import Counter

ROOT = r"C:\Users\177069\ClaudeLearning\boe_xbrl_gen"
sys.path.insert(0, ROOT)
import os
os.chdir(ROOT)
from lxml import etree
from src import dim_drs

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
PKG = f"{BASE}/Banking_4.0.0"
MODEL = f"{BASE}/model.json"
RESULT = f"{BASE}/generated/result.json"
OUT = f"{BASE}/solved/_genvalid_pra001.xbrl"
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
                else:
                    dims[dim_drs.local(em.get("dimension"))] = "(typed)"
        cd[ctx.get("id")] = dims
    out = []
    for el in root:
        cref = el.get("contextRef")
        if cref is not None:
            out.append((dim_drs.local(etree.QName(el).localname), cd.get(cref, {}), (el.text or "").strip()))
    return out


def main():
    model = json.load(open(MODEL, encoding="utf-8"))
    tables = json.load(open(RESULT, encoding="utf-8"))["instances"][0]["tables"]
    defaults = dim_drs.localize_defaults(model.get("dim_defaults", {}))
    metrics = model.get("metrics", {})

    t0 = time.time()
    drs_by_table = {}
    for t in tables:
        p = dim_drs.def_path_for(PKG, t)
        if p:
            try:
                drs_by_table[t] = dim_drs.TableDRS(p)
            except Exception as e:
                print("  parse-fail", t, e)
    tables_by_primary = {}
    for t, d in drs_by_table.items():
        for prim in d.by_primary:
            tables_by_primary.setdefault(prim, []).append(t)
    print(f"built DRS for {len(drs_by_table)}/{len(tables)} tables in {time.time()-t0:.1f}s")

    facts = load_facts(OUT)
    total = len(facts)
    no_primary = valid = invalid = 0
    bad_bool = 0
    invalid_examples = Counter()
    for concept, dims, text in facts:
        # boolean check
        dt = (metrics.get(concept, {}) or {}).get("datatype")
        if dt == "BOOLEAN" and text not in ("true", "false", "1", "0", ""):
            bad_bool += 1
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
    print(f"\n[OUT] facts={total}  metric-not-primary={no_primary}  "
          f"valid(some table)={valid}  DIM-INVALID(no table)={invalid}  bad-boolean={bad_bool}")
    for k, v in invalid_examples.most_common(10):
        print(f"    {v:4d}x  {k[:110]}")


if __name__ == "__main__":
    main()
