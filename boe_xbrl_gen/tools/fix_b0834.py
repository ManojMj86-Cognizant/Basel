"""Targeted fix for b0834 (OF34.07 r0180 = Σ detail rows) — free-detail-leaf ABSORB.
For each concrete (col,z): gap = r0180 - Σ(determined detail rows, pinned by b0830-33). Where gap>=0, set a
FREE detail row (r0040/0050/0060/0170 — no additive def) = gap so Σdetail == r0180 and b0834 holds. Only
touches free detail cells (overwrite if present, else generate DRS-valid); never changes r0180 or the
determined rows, so it cannot break b0872/b0830-33. Env FIX_IN/FIX_OUT (default v15 -> v16).
Run from boe_xbrl_gen/ with PYTHONIOENCODING=utf-8."""
import os, sys, json, copy
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs, instance_build
from collections import defaultdict

ROOT = r"C:\Users\177069\ClaudeLearning"
BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
XBRLI = "http://www.xbrl.org/2003/instance"; XBRLDI = "http://xbrl.org/2006/xbrldi"
FIX_IN = os.environ.get("FIX_IN", os.path.join(ROOT, "ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v15.xbrl"))
FIX_OUT = os.environ.get("FIX_OUT", os.path.join(ROOT, "ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v16.xbrl"))

model = json.load(open(os.path.join(BASE, "model.json"), encoding="utf-8"))
DEF = {d: dim_drs.local(m) for d, m in dim_drs.localize_defaults(model.get("dim_defaults", {})).items()}
defaults_local = dim_drs.localize_defaults(model.get("dim_defaults", {}))


def dset(items):
    return frozenset((k, v) for k, v in items if DEF.get(k) != v)


res = workbook_rules.CellResolver(EXT)
R = workbook_rules.load_workbook_rules(WB, "banking_reporting")


def ck(dp):
    return (dim_drs.local(dp["concept"]), dset({dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}.items()))


# cells that are the lone target of ANY additive rule = "determined"
determined = set()
for r in R:
    if r.get("deactivated"):
        continue
    pe = workbook_rules.parse_expression(r.get("expression", ""))
    if not (pe and pe.get("op") == "i="):
        continue
    for a in workbook_rules.expand_scoped_asts(r):
        if a["op"] != "i=":
            continue
        for side in ("lhs", "rhs"):
            if len(a[side]) == 1:
                for dp in res.resolve(a[side][0]["cell"]):
                    determined.add(ck(dp))

# load instance
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
val = {}; el_by_key = {}; concept_tpl = {}
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    ln = dim_drs.local(etree.QName(el).localname); k = (ln, dset(cdims.get(cr, {}).items()))
    try:
        val[k] = float((el.text or "").strip()); el_by_key[k] = el
    except (ValueError, TypeError):
        pass
    concept_tpl.setdefault(ln, (el.tag, el.get("unitRef"), el.get("decimals")))

drs = None
_p = dim_drs.def_path_for(EXT, "OF34.07.01.01")
if _p:
    drs = dim_drs.TableDRS(_p)

b = next((x for x in R if "b0834" in x["code"]), None)
QI, QD = f"{{{XBRLI}}}", f"{{{XBRLDI}}}"; seq = 0
fixable = gap_neg = no_free = 0; emitted = 0; overwrote = 0

for a in workbook_rules.expand_scoped_asts(b):
    if len(a["lhs"]) != 1:
        continue
    tot = res.resolve(a["lhs"][0]["cell"])
    if not tot:
        continue
    tk = ck(tot[0])
    if tk not in val:
        continue
    r0180 = val[tk]
    det_sum = 0.0; free = []                # free = [(key, concept_q, dims_q)]
    for t in a["rhs"]:
        for dp in res.resolve(t["cell"]):
            k = ck(dp)
            if k in determined and k != tk:
                det_sum += val.get(k, 0.0)
            else:
                free.append((k, dp["concept"], dp["dims"]))
    gap = r0180 - det_sum
    if gap < -0.5:
        gap_neg += 1; continue
    if not free:
        no_free += 1; continue
    # choose a DRS-valid free cell; overwrite if present else generate. Put the whole gap on one cell.
    chosen = None
    for k, cq, dq in free:
        dl = {dim_drs.local(kk): (dim_drs.qmem(vv) if ":" in str(vv) else "(typed)") for kk, vv in dq.items()}
        if k in el_by_key or (drs and drs.is_valid(dim_drs.local(cq), dl, defaults_local)):
            chosen = (k, cq, dq); break
    if not chosen:
        no_free += 1; continue
    fixable += 1
    k, cq, dq = chosen
    newv = int(round(gap))
    if k in el_by_key:
        el_by_key[k].text = str(newv); overwrote += 1
        # zero the other present free cells so Σfree == gap
        for k2, _, _ in free:
            if k2 != k and k2 in el_by_key:
                el_by_key[k2].text = "0"
    else:
        sig = k[1]; cid = ctx_by_sig.get(sig)
        if cid is None:
            seq += 1; cid = f"cb834_{seq}"
            ctx = etree.SubElement(root, f"{QI}context"); ctx.set("id", cid)
            ctx.append(copy.deepcopy(entity_el)); ctx.append(copy.deepcopy(period_el))
            scen = etree.SubElement(ctx, f"{QI}scenario")
            for d, mm in dq.items():
                if DEF.get(dim_drs.local(d)) == dim_drs.local(mm):
                    continue
                em = etree.SubElement(scen, f"{QD}explicitMember"); em.set("dimension", d); em.text = mm
            ctx_by_sig[sig] = cid
        tag, unit, dec = concept_tpl.get(dim_drs.local(cq), (None, "uGBP", "-3"))
        if tag is None:
            uri = root.nsmap.get(cq.split(":")[0]); tag = f"{{{uri}}}{dim_drs.local(cq)}"
        fe = etree.SubElement(root, tag); fe.set("contextRef", cid)
        if unit:
            fe.set("unitRef", unit)
        fe.set("decimals", dec or "-3"); fe.text = str(newv)
        emitted += 1

print(f"b0834 concrete instances: fixable(gap>=0) {fixable} | gap<0 skipped {gap_neg} | no-valid-free {no_free}")
print(f"  emitted {emitted} new free-detail facts, overwrote {overwrote} present free cells")
out = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
if bom:
    out = b"\xef\xbb\xbf" + out
open(FIX_OUT, "wb").write(out)
print(f"APPLIED -> {FIX_OUT}")
