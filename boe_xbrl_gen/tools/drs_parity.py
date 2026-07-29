"""Parity check for src/dim_drs.py against ground-truth instances (no Arelle).

  * official SAMPLE instance is valid -> every C13-shaped fact must be accepted (else over-prune)
  * user's BROKEN instance -> the dimensionally-invalid C13 facts must be rejected (else under-prune)
"""
import json
import sys
from collections import Counter

sys.path.insert(0, ".")
from lxml import etree
from src import dim_drs

MODEL = ("studio/backend/.cache/packages/"
         "50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181/model.json")

PKG = ("studio/backend/.cache/packages/"
       "50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181/Banking_4.0.0")
SAMPLE = "../boebankingtaxonomysampleinstancesv400/ABCDEFGHIJ0123456789_GB_banking_PRA001_2026-02-28_20260220142410000.xbrl"
BROKEN = ("studio/backend/.cache/packages/"
          "50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181/"
          "generated/ABCDEFGHIJ0123456789_pra001_2026-02-28.xbrl")
XBRLI = "http://www.xbrl.org/2003/instance"


def ctx_dims(root):
    out = {}
    for ctx in root.findall(f"{{{XBRLI}}}context"):
        dims = {}
        scen = ctx.find(f"{{{XBRLI}}}scenario")
        if scen is not None:
            for em in scen:
                dim = em.get("dimension")
                if dim is None:
                    continue
                if etree.QName(em).localname == "explicitMember":
                    dims[dim_drs.local(dim)] = dim_drs.local((em.text or "").strip())
        out[ctx.get("id")] = dims
    return out


def facts(path):
    data = open(path, "rb").read()
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    root = etree.fromstring(data)
    cd = ctx_dims(root)
    for el in root:
        cref = el.get("contextRef")
        if cref is None:
            continue
        yield dim_drs.local(etree.QName(el).localname), cd.get(cref, {})


def main():
    defp = dim_drs.def_path_for(PKG, "C13.01.01.01")
    print("def file:", defp)
    drs = dim_drs.TableDRS(defp)
    print(f"hypercube roles: {len(drs.specs)}   distinct primaries: {len(drs.by_primary)}")
    dim_union = set()
    for s in drs.specs:
        dim_union |= set(s["dims"])
    print(f"C13 dimensions: {sorted(dim_union)}")
    model = json.load(open(MODEL, encoding="utf-8"))
    defaults = dim_drs.localize_defaults(model.get("dim_defaults", {}))

    for tag, path in (("SAMPLE(valid)", SAMPLE), ("BROKEN", BROKEN)):
        cand = ok = bad = 0
        bad_examples = Counter()
        for concept, dims in facts(path):
            if concept not in drs.by_primary:
                continue
            # scope to C13-shaped facts: only dims C13 knows about
            if not set(dims) <= dim_union:
                continue
            cand += 1
            if drs.is_valid(concept, dims, defaults):
                ok += 1
            else:
                bad += 1
                # which present member is not admitted anywhere for this concept?
                for d, m in sorted(dims.items()):
                    if all(m not in s["dims"].get(d, {m}) for s in drs.by_primary[concept]):
                        bad_examples[f"{concept}: {d}={m}"] += 1
        print(f"\n[{tag}] C13-shaped facts={cand}  accepted={ok}  rejected={bad}")
        for k, v in bad_examples.most_common(12):
            print(f"    rejected {v:4d}x  {k}")


if __name__ == "__main__":
    main()
