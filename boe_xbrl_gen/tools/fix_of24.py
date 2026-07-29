"""OF24 quick-win fixer  —  PIPELINE STEP: v11 -> v12  (deterministic, minimal-perturbation).

Repairs the OF24 nonlinear/date assertion families that the additive cell-solver structurally
cannot touch. Reads an EXISTING built instance, overwrites ONLY the specific target facts, writes
a new versioned instance. Re-running on the same input always yields an identical output
(no randomness) so the version sequence is reproducible.

Groups handled (A + B):
  A. b0899 / b0900  (date):  OF700.00.01.01 r0050 c0010 (concept boe_met:di6004) is the
     "general reporting-period end date of this submission". In v11 it was a stray random date
     (2018-03-04) < the stress-period end dates it must bound, so every
        <stress-period-end-date>  <=  di6004
     failed. Fix: set di6004 to the instance reporting-period end date (mode of xbrli:instant).
  B. b0676..b0679 (imax ratio):  on OF24.01.01.01 r0010, per column-quartet
        if {denom} != 0 then {target} = {factor} * imax({num}/{denom}, 1)
     Recompute {target} PER CONTEXT (each metric has one fact per open-dim member) and round to
     the fact's @decimals precision. Skipped when denom is absent/0 (precondition false).

NOT handled here (separate tracks): C = b0361/b0363 sqrt-sum-of-squares (tolerance TBD),
the XPTY0004 type rules b0365/b0366 (intentionally ignored), and the isNull/exposure-class family.

Run from boe_xbrl_gen/ with PYTHONIOENCODING=utf-8:
    python tools/fix_of24.py
Env overrides: FIX_IN, FIX_OUT (default v11 -> v12).
"""
import sys, os, re
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from collections import Counter, defaultdict
from lxml import etree
import workbook_rules
from src import dim_drs

ROOT = r"C:\Users\177069\ClaudeLearning"
BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
X = "http://www.xbrl.org/2003/instance"

FIX_IN = os.environ.get("FIX_IN", os.path.join(ROOT, "ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v11.xbrl"))
FIX_OUT = os.environ.get("FIX_OUT", os.path.join(ROOT, "ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v12.xbrl"))

# Group B rule specs: (code, num_col, denom_col, factor_col, target_col) on OF24.01.01.01 r0010.
TABLE_B = "OF24.01.01.01"
ROW_B = "0010"
B_RULES = [
    ("b0676", "0010", "0020", "0030", "0040"),
    ("b0677", "0050", "0060", "0070", "0080"),
    ("b0678", "0100", "0110", "0120", "0130"),
    ("b0679", "0140", "0150", "0160", "0170"),
]

# Group B2: additive cells DERIVED from the Group-B imax targets. Must be recomputed AFTER Group B
# or they regress (b0551/b0552 are the only OF24.01 r0010 rules consuming c0040/c0080/c0130/c0170,
# and their outputs c0090/c0180 feed no further OF24.01 r0010 rule, so one pass converges).
#   (code, target_col, [(coef, source_col), ...])
B2_RULES = [
    ("b0551", "0090", [(0.5, "0040"), (0.5, "0080")]),
    ("b0552", "0180", [(0.5, "0130"), (0.5, "0170")]),
]

# --------------------------------------------------------------------------------------------
res = workbook_rules.CellResolver(EXT)

# dim-local -> default member-local. XBRL omits default members from contexts, so we drop them from
# the resolved canonical too; both sides then carry ONLY explicit non-default members and can be
# compared for exact equality (see ctx_matches).
import json as _json
_mp = os.path.join(BASE, "model.merged.json")
if not os.path.exists(_mp):
    _mp = os.path.join(BASE, "model.json")
_DEFAULTS = {}
if os.path.exists(_mp):
    for _d, _m in dim_drs.localize_defaults(_json.load(open(_mp, encoding="utf-8")).get("dim_defaults", {})).items():
        _DEFAULTS[_d] = dim_drs.local(_m)


def resolve_cell(table, r, c):
    """Resolve a workbook cell (table,r,c) to (concept_localname, canonical_dims).

    canonical_dims is the cell's dimension signature (dim-local -> member-local), default members
    dropped. A rule scoped to a single row governs ONLY the facts whose context signature EQUALS
    this — used to exclude the same metric reused on other rows/periods (e.g. mi10022 is shared by
    c0040 and c0130, split solely by the APA dimension)."""
    dps = res.resolve({"table": table, "r": r, "c": c, "z": []})
    if len(dps) != 1:
        raise SystemExit(f"expected 1 datapoint for {table} r{r} c{c}, got {len(dps)}")
    dp = dps[0]
    loc = dim_drs.local(dp["concept"]).split(":")[-1]
    canon = {dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()
             if _DEFAULTS.get(dim_drs.local(k)) != dim_drs.local(v)}
    return loc, canon


# --------------------------------------------------------------------------------------------
# Load the instance, preserving the tree so we write back the same file with only target edits.
raw = open(FIX_IN, "rb").read()
had_bom = raw[:3] == b"\xef\xbb\xbf"
if had_bom:
    raw = raw[3:]
root = etree.fromstring(raw)

# reporting-period end date = mode of the context instants (endDates fall back)
inst = Counter()
for ctx in root.findall(f"{{{X}}}context"):
    per = ctx.find(f"{{{X}}}period")
    if per is None:
        continue
    for tag in ("instant", "endDate"):
        e = per.find(f"{{{X}}}{tag}")
        if e is not None and (e.text or "").strip():
            inst[e.text.strip()] += 1
REPORT_END = inst.most_common(1)[0][0]

# context id -> {dim_local: member_local}  (explicit members only; defaults are omitted from XBRL)
ctx_dims = {}
for ctx in root.findall(f"{{{X}}}context"):
    dd = {}
    sc = ctx.find(f"{{{X}}}scenario")
    if sc is not None:
        for em in sc:
            if em.get("dimension") and etree.QName(em).localname == "explicitMember":
                dd[dim_drs.local(em.get("dimension"))] = dim_drs.local((em.text or "").strip())
    ctx_dims[ctx.get("id")] = dd

# index every fact element by (concept_local, contextRef)
by_cc = {}
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    loc = etree.QName(el).localname
    by_cc[(loc, cr)] = el


def ctx_matches(cr, canon):
    """True iff the context's explicit non-default dim-set EQUALS the cell's canonical signature.
    Exact equality (not subset) is required: b0676-b0679 have no open axis, and a subset test would
    let a rule whose canonical drops a defaulted dim (e.g. APA) leak onto a context that carries a
    NON-default member on that same dim — a different datapoint. (Group C, which does have an open
    axis, will need a subset test restricted to a known open-axis whitelist.)"""
    return ctx_dims.get(cr, {}) == canon


def fnum(el):
    try:
        return float((el.text or "").strip())
    except (TypeError, ValueError):
        return None


def round_dec(value, decimals):
    """Round to the fact's @decimals grid (decimals=-3 -> nearest 1000). Returns an int-valued
    float on the grid so serialization matches the sibling facts (which are whole thousands)."""
    if decimals is None:
        return value
    q = 10.0 ** (-decimals)
    return round(value / q) * q


def fmt(value):
    """Serialize like the existing monetary facts: no trailing .0 for whole numbers."""
    if value == int(value):
        return str(int(value))
    return repr(value)


changes = []   # (group, code, contextRef, concept, old, new)

# ---- GROUP A: date bound -------------------------------------------------------------------
di_local, _ = resolve_cell("OF700.00.01.01", "0050", "0010")   # -> 'di6004'
a_fixed = 0
for (loc, cr), el in by_cc.items():
    if loc == di_local:
        old = (el.text or "").strip()
        if old != REPORT_END:
            el.text = REPORT_END
            changes.append(("A", "b0899/b0900", cr, loc, old, REPORT_END))
            a_fixed += 1

# ---- GROUP B: imax ratio recompute (r0010 canonical signature only) ------------------------
b_fixed = 0
b_skipped_denom = 0
for code, num_c, den_c, fac_c, tgt_c in B_RULES:
    num_l, _ = resolve_cell(TABLE_B, ROW_B, num_c)
    den_l, _ = resolve_cell(TABLE_B, ROW_B, den_c)
    fac_l, _ = resolve_cell(TABLE_B, ROW_B, fac_c)
    tgt_l, tgt_canon = resolve_cell(TABLE_B, ROW_B, tgt_c)
    # only contexts whose closed-dim signature IS the r0010 datapoint (open axis free)
    for (loc, cr), tgt_el in list(by_cc.items()):
        if loc != tgt_l or not ctx_matches(cr, tgt_canon):
            continue
        den_el = by_cc.get((den_l, cr))
        fac_el = by_cc.get((fac_l, cr))
        num_el = by_cc.get((num_l, cr))
        denom = fnum(den_el) if den_el is not None else None
        factor = fnum(fac_el) if fac_el is not None else None
        num = fnum(num_el) if num_el is not None else None
        # precondition: denom present and != 0 (TDG: absent = 0 -> not asserted)
        if not denom:                      # None or 0.0
            b_skipped_denom += 1
            continue
        if factor is None or num is None:
            b_skipped_denom += 1
            continue
        want = factor * max(num / denom, 1.0)
        try:
            dec = int(tgt_el.get("decimals"))
        except (TypeError, ValueError):
            dec = None
        want_r = round_dec(want, dec)
        old = (tgt_el.text or "").strip()
        new = fmt(want_r)
        if old != new:
            tgt_el.text = new
            changes.append(("B", code, cr, tgt_l, old, new))
            b_fixed += 1

# ---- GROUP B2: recompute additive cells derived from the imax targets ----------------------
b2_fixed = 0
for code, tgt_c, terms in B2_RULES:
    tgt_l, tgt_canon = resolve_cell(TABLE_B, ROW_B, tgt_c)
    src = [(coef, resolve_cell(TABLE_B, ROW_B, sc)[0]) for coef, sc in terms]
    for (loc, cr), tgt_el in list(by_cc.items()):
        if loc != tgt_l or not ctx_matches(cr, tgt_canon):
            continue
        total = 0.0
        for coef, sl in src:
            sel = by_cc.get((sl, cr))
            total += coef * (fnum(sel) or 0.0)          # TDG: absent source = 0
        try:
            dec = int(tgt_el.get("decimals"))
        except (TypeError, ValueError):
            dec = None
        new = fmt(round_dec(total, dec))
        old = (tgt_el.text or "").strip()
        if old != new:
            tgt_el.text = new
            changes.append(("B2", code, cr, tgt_l, old, new))
            b2_fixed += 1

# --------------------------------------------------------------------------------------------
# write output (same declaration/encoding as a normally-built instance)
out_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
if had_bom:
    out_bytes = b"\xef\xbb\xbf" + out_bytes
with open(FIX_OUT, "wb") as fh:
    fh.write(out_bytes)

# --------------------------------------------------------------------------------------------
print(f"IN : {os.path.basename(FIX_IN)}")
print(f"OUT: {os.path.basename(FIX_OUT)}")
print(f"reporting-period end date (di target) = {REPORT_END}")
print(f"\nGroup A (b0899/b0900 date bound): {a_fixed} fact(s) set to {REPORT_END}")
print(f"Group B (b0676-b0679 imax ratio): {b_fixed} target fact(s) recomputed, "
      f"{b_skipped_denom} context(s) skipped (denom absent/0)")
print(f"Group B2 (b0551/b0552 derived averages): {b2_fixed} fact(s) recomputed")
print(f"\n{'grp':3} {'code':12} {'context':9} {'concept':10} {'old':>18} -> {'new':<18}")
for g, code, cr, loc, old, new in changes:
    print(f"{g:3} {code:12} {cr:9} {loc:10} {old:>18} -> {new:<18}")
print(f"\nTOTAL fact edits: {len(changes)}")
