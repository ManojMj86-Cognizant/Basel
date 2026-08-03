"""P2.3 emit v2 — MINIMAL top-down projection of OF34.07 r0180 + OF09.02 from the OF08.01 basis.

OF34.07 is a nested tree (r0180 = Σ detail rows [b0834]; some detail rows = Σ sub-rows [b0830-33]). To make
b0834 AND b0872 (r0180 = ΣOF08.01) hold WITHOUT breaking the internal sub-totals, for each b0834 instance:
  new_r0180 = Σ OF08.01 (the OF08.01-link);  delta = new_r0180 − Σ(current detail rows);
  add delta to ONE true-free leaf detail row (a row that is no rule's target — r0040/50/60/170), leaving the
  b0830-33 sub-totals (and all their sub-rows) at their v15 values. Then Σ details = new_r0180 = r0180.
OF09.02 CEG=x1 cells are overwritten = Σ OF08.01 (separate country view). OF08.01 (the basis) is never touched.
Env FIX_IN/FIX_OUT (v15 -> v16). Run from boe_xbrl_gen/."""
import os, sys, json, copy
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs

ROOT = r"C:\Users\177069\ClaudeLearning"
BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
XBRLI = "http://www.xbrl.org/2003/instance"; XBRLDI = "http://xbrl.org/2006/xbrldi"
CEG_TABLES = {"OF09.01.01.01", "OF09.02.01.01"}
CEG_DIM, CEG_MEM = "eba_dim:CEG", "eba_GA:x1"
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

# ---- override: OF34.07/OF09.02 cell = Σ OF08.01 (pins) ; determined = every lone additive target ----
override = {}; meta = {}; determined = set()
for r in R:
    if r.get("deactivated"):
        continue
    for a in workbook_rules.expand_scoped_asts(r):
        if a["op"] != "i=":
            continue
        for side in ("lhs", "rhs"):
            if len(a[side]) == 1:
                for dp in res.resolve(a[side][0]["cell"]):
                    determined.add(ck_meta(dp)[0])
        tside = "lhs" if len(a["lhs"]) == 1 else "rhs"
        oside = "rhs" if tside == "lhs" else "lhs"
        tdps = res.resolve(a[tside][0]["cell"])
        if len(tdps) != 1 or tdps[0]["table"].upper() not in {"OF34.07.01.01", "OF09.02.01.01"}:
            continue
        srcs = [dp for t in a[oside] for dp in res.resolve(t["cell"])]
        if not srcs or any(dp["table"].upper() != "OF08.01.01.01" for dp in srcs):
            continue
        s = sum(t["coef"] * facts.get(ck_meta(dp)[0], 0.0) for t in a[oside] for dp in res.resolve(t["cell"]))
        k, m = ck_meta(tdps[0]); override[k] = s; meta[k] = m

# ---- OF34.07 INTERNAL tree (parent_key -> [child_key]) from OF34.07=ΣOF34.07 additive rules ----
tree = {}
for r in R:
    if r.get("deactivated"):
        continue
    for a in workbook_rules.expand_scoped_asts(r):
        if a["op"] != "i=":
            continue
        tside = "lhs" if len(a["lhs"]) == 1 else "rhs"
        oside = "rhs" if tside == "lhs" else "lhs"
        tdps = res.resolve(a[tside][0]["cell"])
        if len(tdps) != 1 or tdps[0]["table"].upper() != "OF34.07.01.01":
            continue
        kids = [ck_meta(dp) for t in a[oside] for dp in res.resolve(t["cell"])]
        if kids and all(m[2] == "OF34.07.01.01" for _, m in kids):     # internal (all children OF34.07)
            tk, tm = ck_meta(tdps[0]); meta[tk] = tm
            tree[tk] = kids
            for k, m in kids:
                meta[k] = m

# ---- TOP-DOWN distribute r0180 (= ΣOF08.01) down the tree with INTEGER-EXACT shares (Σ children == parent
# exactly, so every additive rule in the tree holds with 0 residual), proportional to v15 shape, all >=0 ----
changes = {}
def distribute(key, value):                        # value is int
    changes[key] = value
    kids = tree.get(key)
    if not kids:
        return                                     # leaf
    w = [max(int(round(facts.get(k, 0.0))), 0) for k, _ in kids]
    tot = sum(w)
    if tot > 0:
        shares = [value * wi // tot for wi in w]
    else:
        base = value // len(kids); shares = [base] * len(kids)
    rem = value - sum(shares)                       # integer remainder -> spread 1 each so Σ == value EXACTLY
    for i in range(int(round(rem))):
        shares[i % len(shares)] += 1
    for (k, _), s in zip(kids, shares):
        distribute(k, s)

b0834 = next(x for x in R if "b0834" in x["code"])
n_roots = n_skip = 0
for a in workbook_rules.expand_scoped_asts(b0834):
    if len(a["lhs"]) != 1:
        continue
    tdps = res.resolve(a["lhs"][0]["cell"])
    if not tdps:
        continue
    tk = ck_meta(tdps[0])[0]
    if tk not in override or tk not in tree:       # need an OF08.01 pin + a tree to distribute
        n_skip += 1; continue
    distribute(tk, int(round(override[tk])))
    n_roots += 1
n_r0180 = n_roots; n_skip_nofree = n_skip; n_skip_neg = 0

# ---- OF09.02 CEG=x1 cells = Σ OF08.01 ----
n_of0902 = 0
for k, v in override.items():
    if meta[k][2] == "OF09.02.01.01":
        changes[k] = v; n_of0902 += 1

# ---- emit ----
QI, QD = f"{{{XBRLI}}}", f"{{{XBRLDI}}}"; seq = 0
n_over = n_gen = n_skip = 0
for k, v in changes.items():
    concept_q, dims_q, tab = meta[k]
    newv = str(int(round(v)))
    if k in el_by_key:
        el_by_key[k].text = newv; n_over += 1     # write EVERY distributed cell (keep the tree consistent)
        continue
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

print(f"OF34.07 r0180 pinned+absorbed: {n_r0180}  (skip no-free {n_skip_nofree}, skip neg-leaf {n_skip_neg})")
print(f"OF09.02 cells set: {n_of0902}")
print(f"emit: overwrote {n_over} present, generated {n_gen} absent, skipped {n_skip}")
out = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
if bom:
    out = b"\xef\xbb\xbf" + out
open(FIX_OUT, "wb").write(out)
print(f"APPLIED -> {FIX_OUT}")
