"""Phase 1b — coordinated-regeneration EMITTER (leaf-first).

Over the 35-table OF08 cluster: keep v8's LEAF values, derive every additive aggregate topologically
(aggregate = canonical single-table 'own total' Σ sources), then EMIT into the instance — overwrite present
aggregates, generate absent ones (DRS-valid contexts) — so the additive web holds by construction. Non-neg
clamped. (Non-additive OF24 / inequality layers are added on top in later passes.)

Run from boe_xbrl_gen/:  python -m src.coregen --file v8.xbrl --out v10.xbrl [--dry-run]
"""
from __future__ import annotations
import argparse, json, os, sys, copy
from lxml import etree
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import workbook_rules            # noqa: E402
from src import dim_drs, instance_build  # noqa: E402

XBRLI = "http://www.xbrl.org/2003/instance"; XBRLDI = "http://xbrl.org/2006/xbrldi"
ROOT = r"C:\Users\177069\ClaudeLearning"
BASE = os.path.join(ROOT, "boe_xbrl_gen", "studio", "backend", ".cache", "packages",
                    "50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181")
EXT = os.path.join(BASE, "Banking_4.0.0")
WB = os.path.join(ROOT, "boebankingtaxonomyvalidationsv400",
                  "Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx")
CEG_TABLES = {"OF09.01.01.01", "OF09.02.01.01"}
CEG_DIM, CEG_MEM = "eba_dim:CEG", "eba_GA:x1"


def L(q):
    return dim_drs.local(q)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True); ap.add_argument("--out", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    model = json.load(open(os.path.join(BASE, "model.json"), encoding="utf-8"))
    DEF = {d: L(m) for d, m in dim_drs.localize_defaults(model.get("dim_defaults", {})).items()}
    defaults_local = dim_drs.localize_defaults(model.get("dim_defaults", {}))

    def dset(items):
        return frozenset((k, v) for k, v in items if DEF.get(k) != v)

    # ---- cluster ----
    idx = instance_build.module_index(EXT)
    tset = {t.upper() for t, infos in idx.items() for i in infos if i["module"] == "pra001"}
    R = workbook_rules.load_workbook_rules(WB, "banking_reporting")
    adj = defaultdict(set)
    for r in R:
        ts = {t.upper() for t in r["tables"]}
        if len(ts) > 1 and ts <= tset and not r.get("deactivated"):
            for a in ts:
                adj[a] |= ts - {a}
    seen = set(); st = ["OF08.01.01.01"]
    while st:
        x = st.pop()
        if x in seen:
            continue
        seen.add(x); st += [y for y in adj[x] if y not in seen]
    CLUSTER = seen

    # ---- load v8 ----
    raw = open(args.file, "rb").read(); bom = raw[:3] == b"\xef\xbb\xbf"
    root = etree.fromstring(raw[3:] if bom else raw)
    cdims = {}; entity_el = period_el = None; ctx_by_sig = {}
    for c in root.findall(f"{{{XBRLI}}}context"):
        dd = {}; sc = c.find(f"{{{XBRLI}}}scenario")
        if sc is not None:
            for em in sc:
                if em.get("dimension") and etree.QName(em).localname == "explicitMember":
                    dd[L(em.get("dimension"))] = L((em.text or "").strip())
        cdims[c.get("id")] = dd
        ctx_by_sig.setdefault(dset(dd.items()), c.get("id"))
        if entity_el is None:
            entity_el = c.find(f"{{{XBRLI}}}entity"); period_el = c.find(f"{{{XBRLI}}}period")
    val0 = {}; el_by_key = {}; concept_tpl = {}
    for el in root:
        cr = el.get("contextRef")
        if cr is None:
            continue
        ln = L(etree.QName(el).localname); k = (ln, dset(cdims.get(cr, {}).items()))
        try:
            val0[k] = float((el.text or "").strip()); el_by_key[k] = el
        except (ValueError, TypeError):
            pass
        concept_tpl.setdefault(ln, (el.tag, el.get("unitRef"), el.get("decimals")))

    res = workbook_rules.CellResolver(EXT)
    drs_cache = {}

    def drs_for(table):
        if table not in drs_cache:
            p = dim_drs.def_path_for(EXT, table)
            drs_cache[table] = dim_drs.TableDRS(p) if p else None
        return drs_cache[table]

    def ck_meta(dp):
        dq = dict(dp["dims"]); tab = dp.get("table", "").upper()
        if tab in CEG_TABLES:
            dq[CEG_DIM] = CEG_MEM
        dl = {L(k): L(v) for k, v in dq.items()}
        return (L(dp["concept"]), dset(dl.items())), (dp["concept"], dq, tab)

    # ---- build additive DAG ----
    defs = defaultdict(list); meta = {}; allc = set()
    for r in R:
        ts = {t.upper() for t in r["tables"]}
        if not (ts <= CLUSTER) or r.get("deactivated"):
            continue
        pe = workbook_rules.parse_expression(r.get("expression", ""))
        if not (pe and pe.get("op") == "i="):
            continue
        single = len(ts) == 1
        for a in workbook_rules.expand_scoped_asts(r):
            if a["op"] != "i=":
                continue
            eq = defaultdict(float); sc_keys = {"lhs": [], "rhs": []}
            for s, sgn in (("lhs", 1.0), ("rhs", -1.0)):
                for t in a[s]:
                    for dp in res.resolve(t["cell"]):
                        k, m = ck_meta(dp); eq[k] += sgn * t["coef"]; sc_keys[s].append(k); meta[k] = m; allc.add(k)
            eq = {k: c for k, c in eq.items() if abs(c) > 1e-9}
            side = "lhs" if len(a["lhs"]) == 1 else ("rhs" if len(a["rhs"]) == 1 else None)
            if side and len(sc_keys[side]) == 1 and sc_keys[side][0] in eq:
                agg = sc_keys[side][0]
                defs[agg].append((single, eq[agg], {k: eq[k] for k in eq if k != agg}))
    aggregates = set(defs)
    canon = {a: sorted(ds, key=lambda d: (0 if d[0] else 1, len(d[2])))[0] for a, ds in defs.items()}

    # SPARSITY guards (v10 lesson): the BoE report is intentionally sparse — do NOT populate cells that
    # (a) an isNull rule requires EMPTY, or (b) no CROSS-table rule references. Mass-generating every
    # derivable aggregate activated ~650 isNull warnings + broad errors and stalled TDG. So restrict the
    # emit to cross-table-referenced, non-isNull cells only.
    isnull_keys = set()
    xref = set()                                     # cells referenced by a multi-table additive rule
    for r in R:
        ts = {t.upper() for t in r["tables"]}
        if not (ts <= CLUSTER) or r.get("deactivated"):
            continue
        for cell in workbook_rules.isnull_cells(r):
            for dp in res.resolve(cell):
                isnull_keys.add(ck_meta(dp)[0])
        if len(ts) > 1:
            pe2 = workbook_rules.parse_expression(r.get("expression", ""))
            if pe2 and pe2.get("op") == "i=":
                for a in workbook_rules.expand_scoped_asts(r):
                    if a["op"] != "i=":
                        continue
                    for s in ("lhs", "rhs"):
                        for t in a[s]:
                            for dp in res.resolve(t["cell"]):
                                xref.add(ck_meta(dp)[0])

    # ---- topological derivation ----
    indeg = defaultdict(int); children = defaultdict(set)
    for a in aggregates:
        for s in canon[a][2]:
            if s in aggregates:
                children[s].add(a); indeg[a] += 1
    q = deque([a for a in aggregates if indeg[a] == 0]); order = []
    while q:
        n = q.popleft(); order.append(n)
        for ch in children[n]:
            indeg[ch] -= 1
            if indeg[ch] == 0:
                q.append(ch)
    val = dict(val0); neg = 0
    for a in list(order) + [a for a in aggregates if a not in set(order)]:
        _, ac, src = canon[a]
        v = -sum(co * val.get(k, 0.0) for k, co in src.items()) / ac
        if v < 0:
            neg += 1; v = 0.0                      # non-neg clamp
        val[a] = v

    # ---- emit ----
    n_over = n_gen = n_skip = 0
    QI, QD = f"{{{XBRLI}}}", f"{{{XBRLDI}}}"; seq = 0
    n_isnull = n_notxref = 0
    for a in aggregates:
        if a not in val:
            continue
        if a in isnull_keys:                        # must stay EMPTY — never populate
            n_isnull += 1; continue
        if a not in xref:                           # only touch cross-table-referenced cells (targeted)
            n_notxref += 1; continue
        v = val[a]
        if a not in el_by_key and v < 0.5:          # don't generate a 0/near-0 aggregate (sparse report)
            continue
        if a in el_by_key:                          # overwrite present aggregate
            if abs(v - val0.get(a, 0.0)) < 0.5:
                continue
            el = el_by_key[a]
            dec = el.get("decimals")
            el.text = str(int(round(v))) if (dec is None or int(dec) <= 0) else str(round(v, 4))
            n_over += 1
        else:                                       # generate absent aggregate
            concept_q, dims_q, tab = meta[a]
            drs = drs_for(tab)
            dl = {L(k): (dim_drs.qmem(m) if ":" in str(m) else "(typed)") for k, m in dims_q.items()}
            if drs is None or not drs.is_valid(L(concept_q), dl, defaults_local):
                n_skip += 1; continue
            if args.dry_run:
                n_gen += 1; continue
            sig = a[1]; cid = ctx_by_sig.get(sig)
            if cid is None:
                seq += 1; cid = f"ccg_{seq}"
                ctx = etree.SubElement(root, f"{QI}context"); ctx.set("id", cid)
                ctx.append(copy.deepcopy(entity_el)); ctx.append(copy.deepcopy(period_el))
                scen = etree.SubElement(ctx, f"{QI}scenario")
                for d, mm in dims_q.items():
                    if DEF.get(L(d)) == L(mm):
                        continue
                    em = etree.SubElement(scen, f"{QD}explicitMember"); em.set("dimension", d); em.text = mm
                ctx_by_sig[sig] = cid
            tag, unit, dec = concept_tpl.get(L(concept_q), (None, "uGBP", "-3"))
            if tag is None:
                uri = root.nsmap.get(concept_q.split(":")[0]); tag = f"{{{uri}}}{L(concept_q)}"
            fe = etree.SubElement(root, tag); fe.set("contextRef", cid)
            if unit:
                fe.set("unitRef", unit)
            fe.set("decimals", dec or "-3")
            fe.text = str(int(round(v))) if (dec is None or int(dec) <= 0) else str(round(v, 4))
            n_gen += 1

    print(f"cluster {len(CLUSTER)} tbl | aggregates {len(aggregates)} | neg-clamped {neg}")
    print(f"guards: skipped {n_isnull} isNull-forbidden, {n_notxref} not-cross-table-referenced")
    print(f"emit: overwrote {n_over} present, generated {n_gen} absent, skipped {n_skip} (DRS-invalid)")
    if args.dry_run:
        print("(dry-run — no file written)")
        return
    out = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
    if bom:
        out = b"\xef\xbb\xbf" + out
    outp = args.out or (os.path.splitext(args.file)[0] + "_coregen.xbrl")
    open(outp, "wb").write(out)
    print(f"APPLIED -> {outp}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
