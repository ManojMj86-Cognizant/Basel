"""Scope the OF09.02/OF34.07 cross-table total-row GENERATION on v5. For every cross-table rule linking
OF09.02 or OF34.07 to OF08.01, resolve the TARGET cell + SOURCE cells (default-dropped keys), and report:
 - target PRESENT (edit) vs ABSENT (generate)
 - required value = Σ coef·source (from v5 present facts)
 - target (concept, dims) and whether a context with those dims already exists in v5 (reuse vs create).
Read-only analysis to design the generator."""
import sys, json, os
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs
from collections import Counter

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
V5 = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v5.xbrl"
X = "http://www.xbrl.org/2003/instance"

mp = os.path.join(BASE, "model.merged.json")
if not os.path.exists(mp):
    mp = os.path.join(BASE, "model.json")
DEF = {}
for d, m in dim_drs.localize_defaults(json.load(open(mp, encoding="utf-8")).get("dim_defaults", {})).items():
    DEF[d] = dim_drs.local(m)


def dimset(items):
    return frozenset((k, v) for k, v in items if DEF.get(k) != v)


raw = open(V5, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
root = etree.fromstring(raw); ctxdims = {}
for c in root.findall(f"{{{X}}}context"):
    dd = {}; sc = c.find(f"{{{X}}}scenario")
    if sc is not None:
        for em in sc:
            if not em.get("dimension"):
                continue
            ln = etree.QName(em).localname
            if ln == "explicitMember":
                dd[dim_drs.local(em.get("dimension"))] = dim_drs.local((em.text or "").strip())
            elif ln == "typedMember":
                dd[dim_drs.local(em.get("dimension"))] = "typed:" + "".join(em.itertext()).strip()
    ctxdims[c.get("id")] = dd
facts = {}
ctx_sigs = set()
for cid, dd in ctxdims.items():
    ctx_sigs.add(dimset(dd.items()))
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    try:
        facts[(dim_drs.local(etree.QName(el).localname), dimset(ctxdims.get(cr, {}).items()))] = float((el.text or "").strip())
    except (ValueError, TypeError):
        pass

rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
res = workbook_rules.CellResolver(EXT)


def fk(dp):
    return (dim_drs.local(dp["concept"]), dimset((dim_drs.local(k), dim_drs.local(v)) for k, v in dp["dims"].items()))


TARGETS = {"OF09.02.01.01", "OF34.07.01.01"}
stats = Counter()
ctx_reuse = Counter()
examples = {"OF09.02.01.01": [], "OF34.07.01.01": []}

for r in rules:
    ts = {t.upper() for t in r["tables"]}
    if not (ts & TARGETS) or not (ts & {"OF08.01.01.01", "OF08.01.01.02"}):
        continue
    for a in workbook_rules.expand_scoped_asts(r):
        if a["op"] != "i=":
            continue
        # lone side = target (the OF09.02/OF34.07 total); other side = OF08.01 sources
        for side, other in (("lhs", "rhs"), ("rhs", "lhs")):
            if len(a[side]) != 1:
                continue
            tdps = res.resolve(a[side][0]["cell"])
            if not tdps:
                continue
            tdp = tdps[0]
            ttab = tdp.get("table", "")
            if ttab.upper() not in TARGETS:
                continue
            tkey = fk(tdp)
            present = tkey in facts
            # required value = Σ coef·source (other side), sources from OF08.01 present facts
            rhs = 0.0; missing_src = False
            for t in a[other]:
                for dp in res.resolve(t["cell"]):
                    v = facts.get(fk(dp))
                    if v is None:
                        missing_src = True
                    else:
                        rhs += v * t["coef"]
            # our-side coefficient (should be 1)
            tag = "PRESENT" if present else "ABSENT"
            key = ttab.upper()
            stats[(key, tag)] += 1
            ctx_exists = tkey[1] in ctx_sigs
            ctx_reuse[(key, tag, "ctx" if ctx_exists else "noctx")] += 1
            if len(examples[key]) < 4 and not present:
                examples[key].append((r["code"], tkey[0], dict(tkey[1]), round(rhs), ctx_exists))
            break

print("== target present/absent counts ==")
for k, n in sorted(stats.items()):
    print(f"  {k[0]:16s} {k[1]:8s}: {n}")
print("\n== context availability for the target dims ==")
for k, n in sorted(ctx_reuse.items()):
    print(f"  {k[0]:16s} {k[1]:8s} {k[2]:6s}: {n}")
print("\n== sample ABSENT targets (need generation) ==")
for tbl, exs in examples.items():
    for code, concept, dims, val, ctx in exs:
        print(f"  {tbl} {code}: {concept} val={val} ctx_exists={ctx}  dims={dims}")
