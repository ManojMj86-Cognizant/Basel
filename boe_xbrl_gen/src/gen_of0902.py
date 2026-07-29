"""Generate the OF09.02 'all-countries total' (CEG=x1) cells that are missing from the instance and that
the cross-table rules (b0276-b0304, b1051-b1071) reconcile against OF08.01.

Mechanism: for each OF09.02↔OF08.01 additive rule, the OF09.02 cell resolves via the rc-code bridge to a
(metric, row+col dims) that is DRS-INVALID on its own but becomes DRS-VALID once the open country dimension
`eba_dim:CEG = eba_GA:x1` is added. So we: resolve the OF09.02 target, add CEG=x1, compute value = Σ OF08.01
(from present facts), DRS-validate, then emit a new fact (+ context) into the instance. New facts reuse the
reporting entity/period; contexts drop default members (XBRL omits them). Read-only until --apply.

Run from boe_xbrl_gen/:  python -m src.gen_of0902 --file <in.xbrl> [--apply --out <out.xbrl>]
"""
from __future__ import annotations
import argparse
import json
import os
import sys

from lxml import etree

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import workbook_rules            # noqa: E402
from src import dim_drs          # noqa: E402

XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
ROOT = r"C:\Users\177069\ClaudeLearning"
BASE = os.path.join(ROOT, "boe_xbrl_gen", "studio", "backend", ".cache", "packages",
                    "50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181")
EXT = os.path.join(BASE, "Banking_4.0.0")
WB = os.path.join(ROOT, "boebankingtaxonomyvalidationsv400",
                  "Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx")
CEG_DIM = "eba_dim:CEG"
CEG_MEM = "eba_GA:x1"
TARGET_TABLE = "OF09.02.01.01"


def L(q):
    return dim_drs.local(q)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    model = json.load(open(os.path.join(BASE, "model.json"), encoding="utf-8"))
    DEF = {}                                   # dim-local -> default member-local
    for d, m in dim_drs.localize_defaults(model.get("dim_defaults", {})).items():
        DEF[d] = L(m)
    defaults_local = dim_drs.localize_defaults(model.get("dim_defaults", {}))

    raw = open(args.file, "rb").read()
    bom = raw[:3] == b"\xef\xbb\xbf"
    root = etree.fromstring(raw[3:] if bom else raw)

    def dimset(items):                         # frozenset of (dim-local, mem-local), defaults dropped
        return frozenset((k, v) for k, v in items if DEF.get(k) != v)

    # contexts: local-dim-signature -> ctxid, + a template (entity+period) to clone
    ctx_by_sig = {}
    entity_el = period_el = None
    for c in root.findall(f"{{{XBRLI}}}context"):
        dd = {}
        sc = c.find(f"{{{XBRLI}}}scenario")
        if sc is not None:
            for em in sc:
                if em.get("dimension") and etree.QName(em).localname == "explicitMember":
                    dd[L(em.get("dimension"))] = L((em.text or "").strip())
        ctx_by_sig.setdefault(dimset(dd.items()), c.get("id"))
        if entity_el is None:
            entity_el = c.find(f"{{{XBRLI}}}entity")
            period_el = c.find(f"{{{XBRLI}}}period")

    # present numeric facts (default-dropped local keys) + per-concept element template
    facts = {}
    concept_tpl = {}                           # concept-local -> (QName, unitRef, decimals)
    for el in root:
        if el.get("contextRef") is None:
            continue
        ln = L(etree.QName(el).localname)
        if ln not in concept_tpl:
            concept_tpl[ln] = (el.tag, el.get("unitRef"), el.get("decimals"))
    # context-dims lookup for building the facts map
    cdims = {}
    for c in root.findall(f"{{{XBRLI}}}context"):
        dd = {}
        sc = c.find(f"{{{XBRLI}}}scenario")
        if sc is not None:
            for em in sc:
                if em.get("dimension") and etree.QName(em).localname == "explicitMember":
                    dd[L(em.get("dimension"))] = L((em.text or "").strip())
        cdims[c.get("id")] = dd
    for el in root:
        cref = el.get("contextRef")
        if cref is None:
            continue
        try:
            v = float((el.text or "").strip())
        except (ValueError, TypeError):
            continue
        facts[(L(etree.QName(el).localname), dimset(cdims.get(cref, {}).items()))] = v

    # DRS for OF09.02
    drs = dim_drs.TableDRS(dim_drs.def_path_for(EXT, TARGET_TABLE))

    def drs_ok(concept_q, dims_q):
        dl = {}
        for d, mm in dims_q.items():
            dl[L(d)] = dim_drs.qmem(mm) if ":" in str(mm) else "(typed)"
        return drs.is_valid(L(concept_q), dl, defaults_local)

    rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
    res = workbook_rules.CellResolver(EXT)

    def fkey_q(concept_q, dims_q):             # default-dropped local key for a qname cell
        return (L(concept_q), dimset((L(k), L(v)) for k, v in dims_q.items()))

    targets = {}                               # (concept_q, tuple sorted dims_q items) -> {value, concept_q, dims_q}
    skipped_invalid = 0
    for r in rules:
        ts = {t.upper() for t in r["tables"]}
        if TARGET_TABLE not in ts or not (ts & {"OF08.01.01.01", "OF08.01.01.02"}) or r.get("deactivated"):
            continue
        for a in workbook_rules.expand_scoped_asts(r):
            if a["op"] != "i=":
                continue
            # aggregate signed coefs per resolved cell; identify the OF09.02 target dp
            agg = {}                            # key -> [coef, concept_q, dims_q, table]
            for side, sgn in (("lhs", 1.0), ("rhs", -1.0)):
                for t in a[side]:
                    for dp in res.resolve(t["cell"]):
                        k = (dp["concept"], tuple(sorted(dp["dims"].items())))
                        e = agg.get(k)
                        if e:
                            e[0] += sgn * t["coef"]
                        else:
                            agg[k] = [sgn * t["coef"], dp["concept"], dict(dp["dims"]), dp.get("table", "")]
            tgt = [k for k, e in agg.items() if e[3].upper() == TARGET_TABLE and abs(e[0]) > 1e-9]
            if len(tgt) != 1:
                continue
            tk = tgt[0]; tcoef, tconcept, tdims, _ = agg[tk]
            # value = -(Σ others)/tcoef, using present OF08.01 facts
            s = 0.0; ok = True
            for k, e in agg.items():
                if k == tk:
                    continue
                v = facts.get(fkey_q(e[1], e[2]))
                if v is None:
                    ok = False; break
                s += e[0] * v
            if not ok:
                continue
            val = -s / tcoef
            if val < 0:
                continue
            dims_q = dict(tdims); dims_q[CEG_DIM] = CEG_MEM
            if not drs_ok(tconcept, dims_q):
                skipped_invalid += 1
                continue
            key = (tconcept, tuple(sorted(dims_q.items())))
            targets.setdefault(key, {"value": val, "concept": tconcept, "dims": dims_q})

    # PHASE 2 — derive the OF09.02 internal total/subtotal rows that are ABSENT (e.g. b0786 Total = Σ
    # class rows, b0785 Corporates = Σ sub-classes). Generate a target ONLY if it is absent AND all its
    # summands are present (in the instance or already-derived), = Σ others. Do NOT overwrite a cell the
    # cross-table pass set (that would just move a conflict, e.g. b0785 where OF08.01 itself is
    # internally inconsistent). Iterate so Total(→subtotals→leaves) settles.
    work = dict(facts)
    for t in targets.values():
        work[fkey_q(t["concept"], t["dims"])] = t["value"]
    n2_valid = 0
    for _ in range(6):
        changed = False
        for r in rules:
            if {t.upper() for t in r["tables"]} != {TARGET_TABLE} or r.get("deactivated"):
                continue
            pe = workbook_rules.parse_expression(r.get("expression", ""))
            if not (pe and pe.get("op") == "i="):
                continue
            for a in workbook_rules.expand_scoped_asts(r):
                if a["op"] != "i=":
                    continue
                side = "lhs" if len(a["lhs"]) == 1 else ("rhs" if len(a["rhs"]) == 1 else None)
                if side is None:
                    continue
                tdp = None
                for dp in res.resolve(a[side][0]["cell"]):
                    tdp = dp
                if tdp is None:
                    continue
                tdims = dict(tdp["dims"]); tdims[CEG_DIM] = CEG_MEM
                tkey_l = fkey_q(tdp["concept"], tdims)
                if tkey_l in work:
                    continue                    # target already present (leaf/cross-table) — don't touch
                other = "rhs" if side == "lhs" else "lhs"
                s = 0.0; ok = True
                for term in a[other]:
                    for dp in res.resolve(term["cell"]):
                        dq = dict(dp["dims"]); dq[CEG_DIM] = CEG_MEM
                        v = work.get(fkey_q(dp["concept"], dq))
                        if v is None:
                            ok = False; break
                        s += term["coef"] * v
                    if not ok:
                        break
                if not ok or s < 0:
                    continue
                if not drs_ok(tdp["concept"], tdims):
                    continue
                key = (tdp["concept"], tuple(sorted(tdims.items())))
                if key not in targets:
                    targets[key] = {"value": s, "concept": tdp["concept"], "dims": tdims}
                    work[tkey_l] = s
                    n2_valid += 1; changed = True
        if not changed:
            break
    print(f"OF09.02 internal totals/subtotals derived (phase 2): {n2_valid}")

    # drop targets already present in the instance
    to_make = []
    for key, t in targets.items():
        if fkey_q(t["concept"], t["dims"]) in facts:
            continue
        to_make.append(t)

    print(f"OF09.02 targets: resolved {len(targets)} valid, {skipped_invalid} DRS-invalid (skipped), "
          f"{len(to_make)} to generate ({len(targets) - len(to_make)} already present)")
    for t in to_make[:6]:
        print(f"  {L(t['concept'])} = {t['value']:.0f}  dims={[(L(k), L(v)) for k, v in t['dims'].items()]}")

    if not args.apply:
        print("\n(dry-run — no file written; pass --apply)")
        return

    # ---- create contexts + facts ----
    QI = f"{{{XBRLI}}}"; QD = f"{{{XBRLDI}}}"
    made_ctx = 0; nfact = 0; nctx_seq = 0
    # map full qname -> prefixed string for dimension/member attrs, using root nsmap
    uri2pfx = {v: k for k, v in root.nsmap.items()}

    def pfx(qname):                            # 'eba_dim:CEG' -> ensure prefix in nsmap; return as-is
        return qname                            # instance already declares eba_dim/eba_GA/... prefixes

    for t in to_make:
        dims_q = t["dims"]
        sig = dimset((L(k), L(v)) for k, v in dims_q.items())
        cid = ctx_by_sig.get(sig)
        if cid is None:                        # create a new context
            nctx_seq += 1
            cid = f"cof0902_{nctx_seq}"
            ctx = etree.SubElement(root, f"{QI}context"); ctx.set("id", cid)
            import copy
            ctx.append(copy.deepcopy(entity_el))
            ctx.append(copy.deepcopy(period_el))
            scen = etree.SubElement(ctx, f"{QI}scenario")
            for d, mm in dims_q.items():
                if DEF.get(L(d)) == L(mm):     # default member -> omit
                    continue
                em = etree.SubElement(scen, f"{QD}explicitMember"); em.set("dimension", pfx(d))
                em.text = pfx(mm)
            ctx_by_sig[sig] = cid; made_ctx += 1
        # fact
        tag, unit, dec = concept_tpl.get(L(t["concept"]), (None, "uGBP", "-3"))
        if tag is None:                        # concept has no existing fact; build tag from qname
            uri = root.nsmap.get(t["concept"].split(":")[0])
            tag = f"{{{uri}}}{L(t['concept'])}"
        fe = etree.SubElement(root, tag); fe.set("contextRef", cid)
        if unit:
            fe.set("unitRef", unit)
        fe.set("decimals", dec or "-3")
        fe.text = str(int(round(t["value"])))
        nfact += 1

    out = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
    if bom:
        out = b"\xef\xbb\xbf" + out
    outp = args.out or (os.path.splitext(args.file)[0] + "_of0902.xbrl")
    open(outp, "wb").write(out)
    print(f"\nAPPLIED: +{nfact} facts, +{made_ctx} contexts -> {outp}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
