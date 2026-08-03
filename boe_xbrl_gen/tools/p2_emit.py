"""P2.3 emit — project OF34.07 + OF09.02 from the OF08.01 leaf basis and write them into the instance.

For every additive rule whose lone target is an OF34.07 or OF09.02 cell and whose sources are all OF08.01,
set target = Σ OF08.01 (the marginal). For OF34.07's internal b0834 total (r0180 = Σ detail rows), set the
FREE detail rows (no cross-rule) = gap = r0180 - Σ(cross-derived details) so b0834 holds (gap>=0 proven).
Overwrite present cells; generate absent OF09.02 CEG=x1 cells (DRS-valid). Never touches OF08.01 (the basis)
so it can't break OF08.01-internal rules. Env FIX_IN/FIX_OUT (v15 -> v16). Run from boe_xbrl_gen/."""
import os, sys, json, copy
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs
from collections import defaultdict

ROOT = r"C:\Users\177069\ClaudeLearning"
BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
XBRLI = "http://www.xbrl.org/2003/instance"; XBRLDI = "http://xbrl.org/2006/xbrldi"
CEG_TABLES = {"OF09.01.01.01", "OF09.02.01.01"}
CEG_DIM, CEG_MEM = "eba_dim:CEG", "eba_GA:x1"
TARGET_TABLES = {"OF34.07.01.01", "OF09.02.01.01"}
FIX_IN = os.environ.get("FIX_IN", os.path.join(ROOT, "ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v15.xbrl"))
FIX_OUT = os.environ.get("FIX_OUT", os.path.join(ROOT, "ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v16.xbrl"))

model = json.load(open(f"{BASE}/model.json", encoding="utf-8"))
DEF = {d: dim_drs.local(m) for d, m in dim_drs.localize_defaults(model.get("dim_defaults", {})).items()}
defaults_local = dim_drs.localize_defaults(model.get("dim_defaults", {}))
res = workbook_rules.CellResolver(EXT)
R = workbook_rules.load_workbook_rules(WB, "banking_reporting")


def dset(items):
    return frozenset((k, v) for k, v in items if DEF.get(k) != v)


def ck_meta(dp):
    dq = dict(dp["dims"]); tab = dp.get("table", "").upper()
    if tab in CEG_TABLES:
        dq[CEG_DIM] = CEG_MEM
    dl = {dim_drs.local(k): dim_drs.local(v) for k, v in dq.items()}
    return (dim_drs.local(dp["concept"]), dset(dl.items())), (dp["concept"], dq, tab)


# ---- load instance ----
raw = open(FIX_IN, "rb").read(); bom = raw[:3] == b"\xef\xbb\xbf"
root = etree.fromstring(raw[3:] if bom else raw)
entity_el = period_el = None; ctx_by_sig = {}; cdims = {}
for c in root.findall(f"{{{XBRLI}}}context"):
    dd = {}; sc = c.find(f"{{{XBRLI}}}scenario")
    if sc is not None:
        for em in sc:
            if em.get("dimension") and etree.QName(em).localname == "explicitMember":
                dd[dim_drs.local(em.get("dimension"))] = dim_drs.local((em.text or "").strip())
    cdims[c.get("id")] = dd
    ctx_by_sig.setdefault(dset(dd.items()), c.get("id"))
    if entity_el is None:
        entity_el = c.find(f"{{{XBRLI}}}entity"); period_el = c.find(f"{{{XBRLI}}}period")
facts = {}; el_by_key = {}; concept_tpl = {}
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    ln = dim_drs.local(etree.QName(el).localname); k = (ln, dset(cdims.get(cr, {}).items()))
    try:
        facts[k] = float((el.text or "").strip()); el_by_key[k] = el
    except (ValueError, TypeError):
        pass
    concept_tpl.setdefault(ln, (el.tag, el.get("unitRef"), el.get("decimals")))

drs_cache = {}
def drs_for(table):
    if table not in drs_cache:
        p = dim_drs.def_path_for(EXT, table)
        drs_cache[table] = dim_drs.TableDRS(p) if p else None
    return drs_cache[table]

# ---- project: target(OF34.07/OF09.02) = Σ OF08.01 ----
override = {}; meta = {}
for r in R:
    if r.get("deactivated"):
        continue
    for a in workbook_rules.expand_scoped_asts(r):
        if a["op"] != "i=":
            continue
        tside = "lhs" if len(a["lhs"]) == 1 else "rhs"
        oside = "rhs" if tside == "lhs" else "lhs"
        tdps = res.resolve(a[tside][0]["cell"])
        if len(tdps) != 1 or tdps[0]["table"].upper() not in TARGET_TABLES:
            continue
        srcs = [dp for t in a[oside] for dp in res.resolve(t["cell"])]
        if not srcs or any(dp["table"].upper() != "OF08.01.01.01" for dp in srcs):
            continue
        s = 0.0
        for t in a[oside]:
            for dp in res.resolve(t["cell"]):
                s += t["coef"] * facts.get(ck_meta(dp)[0], 0.0)
        k, m = ck_meta(tdps[0]); override[k] = s; meta[k] = m

# ---- b0834 free detail rows = gap ----
b0834 = next(x for x in R if "b0834" in x["code"])
free_set = 0
for a in workbook_rules.expand_scoped_asts(b0834):
    if len(a["lhs"]) != 1:
        continue
    tdps = res.resolve(a["lhs"][0]["cell"])
    if not tdps:
        continue
    tk = ck_meta(tdps[0])[0]
    if tk not in override:                       # r0180 not cross-derived here -> b0834 trivial
        continue
    covered = 0.0; frees = []
    for t in a["rhs"]:
        for dp in res.resolve(t["cell"]):
            k, m = ck_meta(dp)
            if k in override:
                covered += override[k]
            else:
                frees.append((k, m))
    gap = override[tk] - covered
    if gap < -0.5 or not frees:
        continue
    k, m = frees[0]; override[k] = gap; meta[k] = m; free_set += 1
    for k2, _ in frees[1:]:
        override[k2] = 0.0; meta[k2] = _

# ---- emit ----
QI, QD = f"{{{XBRLI}}}", f"{{{XBRLDI}}}"; seq = 0
n_over = n_gen = n_skip = 0
for k, v in override.items():
    concept_q, dims_q, tab = meta[k]
    newv = str(int(round(v)))
    if k in el_by_key:
        if abs(v - facts.get(k, 0.0)) >= 0.5:
            el_by_key[k].text = newv; n_over += 1
        continue
    # generate absent (mainly OF09.02 CEG=x1)
    drs = drs_for(tab)
    dl = {dim_drs.local(kk): (dim_drs.qmem(mm) if ":" in str(mm) else "(typed)") for kk, mm in dims_q.items()}
    if v < 0.5 or drs is None or not drs.is_valid(dim_drs.local(concept_q), dl, defaults_local):
        n_skip += 1; continue
    sig = k[1]; cid = ctx_by_sig.get(sig)
    if cid is None:
        seq += 1; cid = f"p2e_{seq}"
        ctx = etree.SubElement(root, f"{QI}context"); ctx.set("id", cid)
        ctx.append(copy.deepcopy(entity_el)); ctx.append(copy.deepcopy(period_el))
        scen = etree.SubElement(ctx, f"{QI}scenario")
        for d, mm in dims_q.items():
            if DEF.get(dim_drs.local(d)) == dim_drs.local(mm):
                continue
            em = etree.SubElement(scen, f"{QD}explicitMember"); em.set("dimension", d); em.text = mm
        ctx_by_sig[sig] = cid
    tag, unit, dec = concept_tpl.get(dim_drs.local(concept_q), (None, "uGBP", "-3"))
    if tag is None:
        uri = root.nsmap.get(concept_q.split(":")[0]); tag = f"{{{uri}}}{dim_drs.local(concept_q)}"
    fe = etree.SubElement(root, tag); fe.set("contextRef", cid)
    if unit:
        fe.set("unitRef", unit)
    fe.set("decimals", dec or "-3"); fe.text = newv; n_gen += 1

print(f"projected targets: {len(override)}  (OF34.07/OF09.02 from OF08.01) | b0834 free rows set: {free_set}")
print(f"emit: overwrote {n_over} present, generated {n_gen} absent, skipped {n_skip}")
out = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
if bom:
    out = b"\xef\xbb\xbf" + out
open(FIX_OUT, "wb").write(out)
print(f"APPLIED -> {FIX_OUT}")
