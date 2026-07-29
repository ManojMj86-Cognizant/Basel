"""Generate **rule-consistent** data OFFLINE (no Arelle) — Phase B, the cheap path.

Builds the selected tables into instance(s), then runs the engine's `solve` over each module's
full ruleset to enforce the offline-satisfiable rules (additivity/equality, inequality, sign,
format, existence) — exactly what `solve_all.py` does. The solved values are mapped back to the
grid cells (via the build's cell→fact map) and returned, so the UI can show rule-consistent
values *before* any Arelle. The cross-table aggregation tail still needs the Arelle Solve
(`solve_store`), and one Arelle validate confirms.

Async: parsing a framework's full ruleset (formula_rules) is seconds for small modules but a few
minutes for banking_reporting (PRA001's 4,344 vr files) — cached per framework via pickle.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from lxml import etree

from . import config, hypercube_store, model_store, table_store

_SRC = str(config.ENGINE_DIR / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
from src import instance_build  # noqa: E402
from src import dim_drs  # noqa: E402  (offline DRS validity oracle — for open-row synthesis)
import workbook_rules  # noqa: E402  (rule-driven engine; bare imports need src on path)
import formula_eval  # noqa: E402  (non-additive derivation rules: exp/imax/ratios)

_JOBS: dict[str, dict] = {}
_NUMERIC_DT = {"MONETARY", "DECIMAL", "PERCENTAGE", "INTEGER"}


def _fmt_value(value, dt: str | None) -> str:
    dtu = (dt or "MONETARY").upper()
    return str(int(round(value))) if dtu in ("MONETARY", "INTEGER") else str(round(value, 4))


def _apply_nonlinear(pkg_id: str, selection: dict) -> int:
    """Apply NON-additive single-table derivation rules (e.g. b0360–b0364 √Σcell², b0676–b0679
    factor·imax(num/den,1)) as a post-pass over the current selection: read the additive-solved
    input values, compute each rule's lone TARGET cell, and overwrite it. Returns count overridden."""
    framework = ""
    idx = instance_build.module_index(str(_dir(pkg_id)))
    for t in selection:
        for i in idx.get(t.upper(), []):
            if i.get("framework"):
                framework = i["framework"]; break
        if framework:
            break
    wbname = _WORKBOOK_BY_FRAMEWORK.get(framework)
    if not wbname or not (_VALIDATIONS_DIR / wbname).exists():
        return 0
    rules = workbook_rules.load_workbook_rules(str(_VALIDATIONS_DIR / wbname), framework)
    res = workbook_rules.CellResolver(str(_dir(pkg_id)))
    val: dict = {}
    dp_index: dict = {}
    for dps in selection.values():
        for dp in dps:
            k = (dp["concept"], tuple(sorted((dp.get("dims") or {}).items())))
            try:
                val[k] = float(dp.get("value"))
            except (TypeError, ValueError):
                val[k] = 0.0
            dp_index.setdefault(k, []).append(dp)
    value_of = lambda dp: val.get((dp["concept"], tuple(sorted((dp.get("dims") or {}).items()))), 0.0)  # noqa: E731

    def _single(r):
        return len(r["tables"]) == 1 and r["tables"][0] in selection and not r.get("deactivated")

    # Cells that ANY additive rule references — do NOT let the non-linear pass clobber them, or it
    # breaks totals the additive solver already balanced (a cell can't satisfy both a sum and a
    # non-linear formula with the same inputs). Additive keeps those; non-linear fills only the rest.
    additive_cells: set = set()
    for r in rules:
        if not _single(r):
            continue
        for a in workbook_rules.expand_scoped_asts(r):
            for side in ("lhs", "rhs"):
                for term in a[side]:
                    for dp in res.resolve(term["cell"]):
                        additive_cells.add((dp["concept"], tuple(sorted((dp.get("dims") or {}).items()))))

    overrides: dict = {}
    for r in rules:
        if not _single(r) or workbook_rules.parse_expression(r["expression"]):
            continue                              # additive — handled by the additive solver
        for k, v in formula_eval.derive_rule(r, res, value_of).items():
            if k not in additive_cells:           # protect additive-owned cells
                overrides[k] = v
    n = 0
    for k, v in overrides.items():
        for dp in dp_index.get(k, []):
            if (dp.get("datatype") or "").upper() in _NUMERIC_DT:
                dp["value"] = _fmt_value(v, dp.get("datatype")); n += 1
    return n

# framework code -> validations workbook file (BoE ships one workbook per framework).
_VALIDATIONS_DIR = config.ROOT / "boebankingtaxonomyvalidationsv400"
_WORKBOOK_BY_FRAMEWORK = {
    "banking_reporting": "Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx",
}

# Cross-table (multi-table) rule solving (Stage 2). The MAIN additive/LP solve is ALWAYS single-table:
# feeding multi-table rules into the exact fraction-RREF/LP solver fuses their cells into one connected
# component, and on PRA001 that is a 35-table mega-group (OF07+OF08+OF18+… ≈ 50k cells) — the solver
# chokes (denominator blow-up → hangs) AND it would re-solve those tables, destroying the single-table
# (Stage 1) result. So cross-table is handled by a SEPARATE, safe AGGREGATION POST-PASS instead:
# read Stage-1 source values as fixed, derive only the cross-table TARGET cells Stage 1 doesn't own,
# never touch a Stage-1 cell, never emit a negative. `GENVALID_CROSSTABLE=1` enables that post-pass.
_CROSSTABLE = os.environ.get("GENVALID_CROSSTABLE", "0").strip().lower() not in ("", "0", "false", "no")
# When the cross-table post-pass runs, allow it to OVERRIDE a Stage-1-owned target cell (only where no
# free cell can serve) — satisfies more cross-table rules at the cost of disturbing some single-table
# totals. User-opted-in 2026-06-26; default ON when _CROSSTABLE is on. No-negatives still enforced.
_CT_OVERRIDE = os.environ.get("GENVALID_CROSSTABLE_OVERRIDE", "1").strip().lower() not in ("", "0", "false", "no")


def _rule_in_scope(rule, tset: set) -> bool:
    """A rule's cells are all in the generated module, AND it is single-table. The main solve is
    single-table only (cross-table goes through `_crosstable_agg_values`, not this)."""
    if not rule["tables"] or rule.get("deactivated"):
        return False
    if not (set(rule["tables"]) <= tset):
        return False
    return len(rule["tables"]) == 1


def _crosstable_agg_values(pkg_id: str, framework: str, tables: list, current_values: dict,
                           fixed_keys: set, present_keys: set, rounds: int = 5,
                           allow_override: bool = False) -> dict:
    """Stage 2 — cross-table AGGREGATION post-pass (no table fusion → no hang).

    For every MULTI-table ADDITIVE rule (e.g. b0844 `OF34.07 r0180 = isum(OF08 …)`) derive ONE cell of
    the equation from the others' current values, picking the cell that hurts Stage 1 least:

      * `s1_inc[cell]` = how many SINGLE-table additive equations reference that cell — i.e. how many
        single-table rules it would BREAK if we move it without re-deriving (0 = a free leaf that
        "doesn't affect other tables", so setting it keeps Stage 1 fully satisfied — the user's idea).
      * `helps[cell]` = how many cross-table equations would be satisfied by choosing it as target.
      * We always take a free-leaf target (s1_inc==0). For a Stage-1 cell we override ONLY when
        `allow_override` AND it is NET-POSITIVE (`helps > s1_inc` — fixes more cross-table rules than
        the single-table rules it breaks). Otherwise the cross-table rule is left unsatisfied.
      * the target must be generated (`present_keys`); a derived value < 0 is SKIPPED (no negatives).
    Conditional / boolean / non-additive cross-table rules don't parse as additive → skipped here.
    Returns {dp_key -> {concept, dims, value}} for the derived cross-table targets."""
    wbname = _WORKBOOK_BY_FRAMEWORK.get(framework)
    if not wbname:
        return {}
    xlsx = _VALIDATIONS_DIR / wbname
    if not xlsx.exists():
        return {}
    from collections import Counter
    ext = str(_dir(pkg_id))
    tset = set(tables)
    rules = workbook_rules.load_workbook_rules(str(xlsx), framework)
    res = workbook_rules.CellResolver(ext)

    # SINGLE-table incidence: how many single-table additive equations reference each cell (= how many
    # would break if we move it). This is the cost of overriding that cell.
    s1_inc: Counter = Counter()
    for r in rules:
        ts = set(r.get("tables") or [])
        if len(ts) == 1 and ts <= tset and not r.get("deactivated"):
            for ast in workbook_rules.expand_scoped_asts(r):
                p = workbook_rules.plan_equality(ast, res)
                if p and p.get("agg"):
                    for k in p["agg"]:
                        s1_inc[k] += 1

    # CROSS-table plans + a provisional target per plan (lowest-cost present cell) to count `helps`.
    plans = []
    for r in rules:
        ts = set(r.get("tables") or [])
        if len(ts) > 1 and ts <= tset and not r.get("deactivated"):
            for ast in workbook_rules.expand_scoped_asts(r):
                p = workbook_rules.plan_equality(ast, res)
                if p and p.get("agg"):
                    plans.append(p)
    if not plans:
        return {}

    def pick(p):
        agg = p["agg"]; preferred = set(p.get("preferred") or [])
        pool = [k for k in agg if k in present_keys and abs(agg[k]) > 1e-9]
        if not pool:
            return None
        # cheapest first: free leaf (s1_inc 0) > low incidence; tie-break to the lone-'total' side.
        pool.sort(key=lambda k: (s1_inc.get(k, 0), k not in preferred, k))
        return pool[0]

    helps: Counter = Counter()
    for p in plans:
        t = pick(p)
        if t is not None:
            helps[t] += 1

    val = dict(current_values)
    derived: dict = {}
    for _ in range(rounds):
        changed = False
        for p in plans:
            tgt = pick(p)
            if tgt is None:
                continue
            cost = s1_inc.get(tgt, 0)
            if cost > 0 and not (allow_override and helps[tgt] > cost):
                continue                                        # would break Stage 1 net-negatively
            tc = p["agg"][tgt]
            s = sum(c * val.get(k, 0.0) for k, c in p["agg"].items() if k != tgt)
            nv = -s / tc
            if nv < 0:                                          # never introduce a negative datapoint
                continue
            if abs(nv - val.get(tgt, 0.0)) > 1e-6:
                val[tgt] = nv
                changed = True
            dp = p["dp"][tgt]
            derived[tgt] = {"concept": dp["concept"], "dims": dp["dims"], "value": nv}
        if not changed:
            break
    return {k: v for k, v in derived.items() if k in present_keys}


_NUMRE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*$")


def _constant_sum_values(pkg_id: str, framework: str, selection: dict, fixed_keys: set) -> dict:
    """`Σ cells = constant` rules (e.g. b0778: c0030+c0040+c0050 = 1 per row — a 'shares sum to 1'
    constraint). The current additive parser rejects a constant RHS, so these are never solved.
    Per scoped instance, assign the row's cells a value summing EXACTLY to the constant (one-hot:
    first cell = k, the rest 0 — exact, ≥0, datatype-valid), but ONLY when every cell is free
    (not Stage-1-owned `fixed_keys`) so Stage 1 is preserved. Returns {key -> {concept,dims,value}}."""
    wbname = _WORKBOOK_BY_FRAMEWORK.get(framework)
    if not wbname:
        return {}
    xlsx = _VALIDATIONS_DIR / wbname
    if not xlsx.exists():
        return {}
    ext = str(_dir(pkg_id))
    tset = set(selection)
    rules = workbook_rules.load_workbook_rules(str(xlsx), framework)
    res = workbook_rules.CellResolver(ext)
    present = {(dp["concept"], tuple(sorted((dp.get("dims") or {}).items())))
               for dps in selection.values() for dp in dps}
    out: dict = {}
    for r in rules:
        ts = set(r.get("tables") or [])
        if not ts or not (ts <= tset) or r.get("deactivated"):
            continue
        e = r.get("expression", "")
        m = workbook_rules._REL_RE.search(e)
        if not m:
            continue
        if ("i" + (m.group(1) or m.group(2))) != "i=":
            continue
        lhs, rhs = e[:m.start()], e[m.end():]
        if ("{" in lhs) == ("{" in rhs):
            continue                                       # not the cells-vs-constant shape
        cellside, constside = (lhs, rhs) if "{" in lhs else (rhs, lhs)
        cm = _NUMRE.match(constside)
        if not cm:
            continue
        k = float(cm.group(1))
        sc = workbook_rules.parse_scope(r.get("scope", "")) or {"table": "", "rows": [], "cols": [], "z": []}
        tab = sc.get("table") or next(iter(ts))
        cellrefs = [workbook_rules._parse_cell(b) for b in workbook_rules._CELL_RE.findall(cellside)]
        for srow in (sc["rows"] or [None]):
            for scol in (sc["cols"] or [None]):
                for sz in (sc["z"] or [None]):
                    dps = []
                    for cr in cellrefs:
                        rows = workbook_rules._semi(cr.get("r")) or [cr.get("r") or srow]
                        cols = workbook_rules._semi(cr.get("c")) or [cr.get("c") or scol]
                        zz = cr.get("z") or ([sz] if sz else [])
                        for rv_ in rows:
                            for cv in cols:
                                dps += res.resolve({"table": cr.get("table") or tab,
                                                    "r": rv_, "c": cv, "z": zz})
                    keys = [(dp["concept"], tuple(sorted((dp.get("dims") or {}).items())), dp) for dp in dps]
                    kk = [(c, d) for c, d, _ in keys]
                    if not kk:
                        continue
                    if any(key not in present for key in kk):
                        continue                           # cells absent → can't satisfy here
                    if any(key in fixed_keys for key in kk):
                        continue                           # Stage-1-owned → leave it (preserve Stage 1)
                    if k < 0:
                        continue
                    for i, (c, d, dp) in enumerate(keys):  # one-hot: first cell = k, rest 0 (exact, ≥0)
                        out[(c, d)] = {"concept": c, "dims": dp.get("dims") or {}, "value": k if i == 0 else 0.0}
    return out


# Tables solved by the exact NON-NEGATIVE additive LP (over-determined 2-D exposure tables whose
# random-free solve would need negatives). Solved JOINTLY as one LP (so cross-table inequalities among
# them — b0367/b0368/b0369 OF08.01.01.02 ≤ OF08.01.01.01 — can be enforced). Extend via env (comma list).
_NONNEG_TABLES = {t.strip() for t in os.environ.get(
    "GENVALID_NONNEG_TABLES", "OF08.01.01.01,OF08.01.01.02").split(",") if t.strip()}


def _crosstable_le_rows(res, rules: list, tset: set, present: set) -> list:
    """Extract MULTI-table `≤`/`≥` inequality rules whose cells all lie in `tset` (e.g. b0367/b0368/
    b0369 `OF08.01.01.02 cell ≤ OF08.01.01.01 cell`), as `Σ coef·x ≤ rhs` over `present` cell-keys.
    Cells ≥ 0 so `iabs`/`abs` are dropped; absent cells contribute 0. Scope-expanded per (row,col,z)."""
    def dkey(dp):
        return (dp["concept"], tuple(sorted((dp.get("dims") or {}).items())))

    def linexpr(node, sr, sc, sz, tab):
        t = node[0]
        if t == "num":
            return {}, float(node[1])
        if t == "cell":
            c = node[1]
            rvals = workbook_rules._semi(c.get("r")) or [c.get("r") or sr]
            cvals = workbook_rules._semi(c.get("c")) or [c.get("c") or sc]
            zz = c.get("z") or ([sz] if sz else [])
            cd = {}
            for rv in rvals:
                for cv in cvals:
                    for dp in res.resolve({"table": c.get("table") or tab, "r": rv, "c": cv, "z": zz}):
                        k = dkey(dp)
                        if k in present:
                            cd[k] = cd.get(k, 0.0) + 1.0
            return cd, 0.0
        if t == "neg":
            cd, k = linexpr(node[1], sr, sc, sz, tab)
            return {x: -v for x, v in cd.items()}, -k
        if t == "bin" and node[1] in ("+", "-"):
            a = linexpr(node[2], sr, sc, sz, tab); b = linexpr(node[3], sr, sc, sz, tab)
            s = 1.0 if node[1] == "+" else -1.0
            cd = dict(a[0])
            for x, v in b[0].items():
                cd[x] = cd.get(x, 0.0) + s * v
            return cd, a[1] + s * b[1]
        if t == "call" and node[1] == "isum":
            cd = {}; k = 0.0
            for arg in node[2]:
                a = linexpr(arg, sr, sc, sz, tab)
                for x, v in a[0].items():
                    cd[x] = cd.get(x, 0.0) + v
                k += a[1]
            return cd, k
        if t == "call" and node[1] in ("iabs", "abs") and node[2]:
            return linexpr(node[2][0], sr, sc, sz, tab)     # |x| → x (cells ≥ 0)
        return {}, 0.0

    out = []
    for r in rules:
        ts = set(r.get("tables") or [])
        if len(ts) < 2 or not (ts <= tset) or r.get("deactivated") or "{" not in r["expression"]:
            continue
        try:
            ast = formula_eval._Parser(formula_eval._tokenize(r["expression"])).parse()
        except Exception:
            continue
        node = ast[2] if ast[0] == "if" else ast
        if not (isinstance(node, tuple) and node[0] == "cmp" and node[1] in ("<=", "<", ">=", ">")):
            continue
        sc = workbook_rules.parse_scope(r.get("scope", "")) or {"table": "", "rows": [], "cols": [], "z": []}
        tab = sc.get("table") or next(iter(ts))
        for sr in (sc["rows"] or [None]):
            for scl in (sc["cols"] or [None]):
                for sz in (sc["z"] or [None]):
                    L = linexpr(node[2], sr, scl, sz, tab); R = linexpr(node[3], sr, scl, sz, tab)
                    cd = dict(L[0])
                    for x, v in R[0].items():
                        cd[x] = cd.get(x, 0.0) - v
                    rhs = R[1] - L[1]
                    if node[1] in (">=", ">"):
                        cd = {x: -v for x, v in cd.items()}; rhs = -rhs
                    cd = {x: v for x, v in cd.items() if abs(v) > 1e-12}
                    if cd:
                        out.append((cd, rhs))
    return out


def _nonneg_additive_solve(pkg_id: str, framework: str, tables: set, selection: dict,
                           le_constraints: list | None = None) -> dict:
    """Solve a table's SINGLE-table additive rules with ALL cells ≥ 0, exactly (integer).

    The random-free exact solve derives some cells as `total − others`, which can go negative on
    over-determined 2-D tables (row-sums AND column-sums of the same totals, e.g. OF08.01.01.01 /
    b0745 + 21 siblings). Instead we solve the equality system as an LP: variables = the table's
    generated numeric cells (≥ 0), isNull cells fixed to 0, every additive equation `Σ coef·x = 0`
    as an exact constraint, objective = L1-close to varied positive targets (realistic, non-trivial
    values). The LP's ≥0 feasible region is non-empty (proven), so every additive rule holds with
    NO negatives; the solution rounds to integers exactly (±1 additive structure). Returns
    {dp_key -> {concept,dims,value}} for the solved cells. {} if scipy is unavailable."""
    linprog = workbook_rules._get_linprog()          # scipy import behind watchdog (or None)
    if linprog is None:
        return {}
    import numpy as np
    import random as rnd
    from scipy.sparse import csr_matrix
    wbname = _WORKBOOK_BY_FRAMEWORK.get(framework)
    if not wbname:
        return {}
    xlsx = _VALIDATIONS_DIR / wbname
    if not xlsx.exists():
        return {}
    ext = str(_dir(pkg_id))
    tset = set(tables)
    rules = workbook_rules.load_workbook_rules(str(xlsx), framework)
    res = workbook_rules.CellResolver(ext)

    def dkey(dp):
        return (dp["concept"], tuple(sorted((dp.get("dims") or {}).items())))

    # variables = the tables' generated NUMERIC cells; fixed-to-0 = their isNull cells
    present: dict = {}
    for code, dps in selection.items():
        if code not in tset:
            continue
        for dp in dps:
            if (dp.get("datatype") or "").upper() in _NUMERIC_DT:
                present[dkey(dp)] = dp
    tbl_rules = [r for r in rules if len(set(r.get("tables") or [])) == 1
                 and (r["tables"][0] in tset) and not r.get("deactivated")]
    nullk: set = set()
    for r in tbl_rules:
        for cell in workbook_rules.isnull_cells(r):
            for dp in res.resolve(cell):
                nullk.add(dkey(dp))
    varlist = [k for k in present if k not in nullk]
    idx = {k: i for i, k in enumerate(varlist)}
    n = len(varlist)
    if n == 0:
        return {}
    # additive equations Σ coef·x = 0 (cells not generated / isNull ⇒ 0, dropped)
    rows_, cols_, data_, r = [], [], [], 0
    for rule in tbl_rules:
        for a in workbook_rules.expand_scoped_asts(rule):
            if a["op"] != "i=":
                continue
            row: dict = {}
            for side, sgn in (("lhs", 1.0), ("rhs", -1.0)):
                for t in a[side]:
                    for dp in res.resolve(t["cell"]):
                        k = dkey(dp)
                        if k in idx:
                            row[k] = row.get(k, 0.0) + sgn * t["coef"]
            row = {k: c for k, c in row.items() if abs(c) > 1e-12}
            if row:
                for k, c in row.items():
                    rows_.append(r); cols_.append(idx[k]); data_.append(c)
                r += 1
    if r == 0:
        return {}
    # linear INEQUALITY constraints on this table's cells (Σ coef·x ≤ rhs): the ≤0 pins b1037/b1038
    # (c0102/c0103 ≤ 0 → 0 with x≥0) and cross-cell ≤ (b1036 c0102≤c0103, b0683/b0684 |Σ|≤cell).
    # Only those referencing solely this table's variables. Without these, the additive solve pushes
    # ≤0 cells positive → b1037/b1038/b1036/b0683/b0684 fail (the regression the user hit).
    le_rows = [(cd, float(rhs)) for cd, rhs in (le_constraints or []) if cd and all(k in idx for k in cd)]
    # multi-table ≤ rules among the jointly-solved tables (b0367/b0368/b0369) — couples both tables'
    # cells in the same LP so "off-balance ≤ overall" holds (pushes the overall cells up as needed).
    le_rows += [(cd, rhs) for cd, rhs in _crosstable_le_rows(res, rules, tset, set(idx))
                if all(k in idx for k in cd)]

    g = rnd.Random(1)
    tgt = np.array([g.choice([1000, 5000, 20000, 100000, 500000, 2000000]) for _ in range(n)], float)
    timeout = float(os.environ.get("GENVALID_NONNEG_TIMEOUT", "600"))

    def _build(nslack):
        """L1-to-target LP; vars [x(n), s(n), sl(nslack)]. nslack>0 => soft le (penalised slack)."""
        W = 2 * n + nslack
        ur, uc, ud, bub = [], [], [], []
        ri = 0
        for i in range(n):
            ur += [ri, ri]; uc += [i, n + i]; ud += [1.0, -1.0]; bub.append(tgt[i]); ri += 1     # x−s≤t
            ur += [ri, ri]; uc += [i, n + i]; ud += [-1.0, -1.0]; bub.append(-tgt[i]); ri += 1    # −x−s≤−t
        for j, (cd, rhs) in enumerate(le_rows):        # Σ coef·x (− slack_j) ≤ rhs
            for k, co in cd.items():
                ur.append(ri); uc.append(idx[k]); ud.append(float(co))
            if nslack:
                ur.append(ri); uc.append(2 * n + j); ud.append(-1.0)
            bub.append(rhs); ri += 1
        Aub = csr_matrix((ud, (ur, uc)), shape=(ri, W))
        Aeq = csr_matrix((data_, (rows_, cols_)), shape=(r, W))
        obj = np.zeros(W); obj[n:2 * n] = 1.0
        if nslack:
            obj[2 * n:] = 1e6                          # heavily penalise inequality violation
        return linprog(obj, A_ub=Aub, b_ub=np.array(bub), A_eq=Aeq, b_eq=np.zeros(r),
                       bounds=[(0, None)] * W, method="highs", options={"time_limit": timeout})

    sol = _build(0)                                    # HARD: equalities + inequalities + ≥0
    if not sol.success and le_rows:
        sol = _build(len(le_rows))                     # SOFT: keep eq+≥0 hard, minimise le violation
    if not sol.success:
        return {}
    out: dict = {}
    for k, i in idx.items():
        v = max(0, int(round(sol.x[i])))               # ≥0 integers (exact for ±1 additivity)
        dp = present[k]
        out[k] = {"concept": dp["concept"], "dims": dp.get("dims") or {}, "value": float(v)}
    return out


def _crosstable_open_link(pkg_id: str, framework: str, selection: dict, model: dict,
                          rv: dict | None = None) -> dict:
    """Cross-table consistency where the SOURCE is an open (synth) table — e.g. b0814
    `OF08.01.01.01 r0070 cX = isum(OF08.02.01.01 cX)` per z. The rule resolves the OF08.02 cell to
    its CLOSED dims (no open OGR dim), which won't exact-match our synth cell (that carries OGR); so
    we match on closed dims (typed/open dims wildcarded) and DERIVE the open synth cell from the
    closed-table cell(s). Only the open synth cell moves — the closed (Stage-1) table is read-only.
    Returns {open_full_key -> {concept,dims,value}}. No negatives."""
    from collections import defaultdict
    wbname = _WORKBOOK_BY_FRAMEWORK.get(framework)
    if not wbname:
        return {}
    xlsx = _VALIDATIONS_DIR / wbname
    if not xlsx.exists():
        return {}
    ext = str(_dir(pkg_id))
    tset = set(selection)
    dims_info = model.get("dimensions", {})

    def typed(dq):
        return bool((dims_info.get(dim_drs.local(dq)) or {}).get("typed"))

    def closed_fs(dims):                               # dims minus open/typed dims (OGR, UDI, …)
        return frozenset((d, m) for d, m in (dims or {}).items() if not typed(d))

    # index selection: current numeric value per closed-key (summed), + the open synth cell per closed-key.
    # Prefer the rule-driven value (rv) over the raw selection value — rv holds the FINAL closed-table
    # totals (e.g. OF08.01 r0070) that this pass reads as the source of truth.
    rv = rv or {}
    closed_val: dict = defaultdict(float)
    closed_has: set = set()
    synth_closed: dict = {}
    for dps in selection.values():
        for dp in dps:
            if (dp.get("datatype") or "").upper() not in _NUMERIC_DT:
                continue
            ck = (dp["concept"], closed_fs(dp.get("dims")))
            fk = (dp["concept"], tuple(sorted((dp.get("dims") or {}).items())))
            if fk in rv:
                v = rv[fk]["value"]
            else:
                try:
                    v = float(dp.get("value"))
                except (TypeError, ValueError):
                    v = None
            if v is not None:
                closed_val[ck] += v
                closed_has.add(ck)
            if dp.get("synth"):
                synth_closed[ck] = fk

    rules = workbook_rules.load_workbook_rules(str(xlsx), framework)
    res = workbook_rules.CellResolver(ext)
    out: dict = {}
    for r in rules:
        ts = set(r.get("tables") or [])
        if len(ts) <= 1 or not (ts <= tset) or r.get("deactivated"):
            continue
        for a in workbook_rules.expand_scoped_asts(r):
            if a["op"] != "i=":
                continue
            agg: dict = defaultdict(float)
            for side, sgn in (("lhs", 1.0), ("rhs", -1.0)):
                for t in a[side]:
                    for dp in res.resolve(t["cell"]):
                        agg[(dp["concept"], closed_fs(dp.get("dims")))] += sgn * t["coef"]
            # need exactly one open (synth) target; every other cell readable
            targets = [ck for ck in agg if ck in synth_closed and abs(agg[ck]) > 1e-9]
            if len(targets) != 1:
                continue
            tgt = targets[0]
            s = 0.0
            good = True
            for ck, co in agg.items():
                if ck == tgt or abs(co) < 1e-9:
                    continue
                if ck not in closed_has:
                    good = False
                    break
                s += co * closed_val[ck]
            if not good:
                continue
            nv = -s / agg[tgt]
            if nv < 0:                                 # never introduce a negative datapoint
                continue
            fk = synth_closed[tgt]
            out[fk] = {"concept": fk[0], "dims": dict(fk[1]), "value": nv}
    return out


def _rule_driven_values(pkg_id: str, framework: str, tables: list,
                        present_keys: set | None = None, le_constraints: list | None = None) -> dict:
    """{(concept, sorted-dims) -> numeric value} computed by the rule-driven engine for the
    workbook rules that live entirely within `tables`. {} if no workbook for the framework.
    `present_keys` are the cells actually generated (others treated as absent=0); `le_constraints`
    are linear inequalities `Σ coef·value ≤ rhs` — both feed the exact linear / LP solver."""
    import random
    wbname = _WORKBOOK_BY_FRAMEWORK.get(framework)
    if not wbname:
        return {}
    xlsx = _VALIDATIONS_DIR / wbname
    if not xlsx.exists():
        return {}
    ext = str(_dir(pkg_id))
    model = model_store._active_model(pkg_id) or {}
    metrics = model.get("metrics", {})
    tset = set(tables)
    rules = workbook_rules.load_workbook_rules(str(xlsx), framework)
    # Expand each scoped additive rule into one concrete equation per (row × z) in its scope, so the
    # column-only expression is instantiated against the actual built facts (the previous code parsed
    # the expression but dropped the Scope clause, so column-only cells never matched any datapoint).
    # Rules fully within the generated module — INCLUDING multi-table (cross-table) rules, whose cells
    # carry their own table; the solver merges them into one connected component so cross-table
    # equalities (b0739/b0736) and inequalities (b0369/b0368) are solved together.
    def _single(r):
        return _rule_in_scope(r, tset)

    asts = []
    for r in rules:
        if _single(r):
            asts.extend(workbook_rules.expand_scoped_asts(r))
    if not asts:
        return {}
    res = workbook_rules.CellResolver(ext)
    # cells an isNull rule forces empty — the additive solver must treat these as 0 so totals it
    # derives stay correct once those cells are removed from the instance.
    null_keys = set()
    for r in rules:
        if not _single(r):
            continue
        for cellspec in workbook_rules.isnull_cells(r):
            for dp in res.resolve(cellspec):
                null_keys.add((dp["concept"], tuple(sorted((dp.get("dims") or {}).items()))))
    dt_of = lambda c: (metrics.get(c, {}) or {}).get("datatype")  # noqa: E731
    # Exact simultaneous solve (RREF per component) + LP for components touched by an inequality —
    # satisfies every consistent additive equation AND the A≤B inequalities (b0379/b0380) at once.
    # Absent cells (not in present_keys) are treated as 0, so 'missing-cell' rules (b0744/b0745) balance.
    return workbook_rules.solve_cells_lp(asts, res, random.Random(1), datatype_of=dt_of,
                                         null_keys=null_keys, present_keys=present_keys,
                                         le_constraints=le_constraints)


def _constraint_values(pkg_id: str, selection: dict) -> tuple:
    """Parse single-table INEQUALITY/DATE rules and return:
      * date_over {dp_key -> 'YYYY-MM-DD'} — 'startDate ≤ endDate' (b0890): start early / end late;
      * le_constraints [(coef_dict {dp_key->coef}, rhs)] — each means `Σ coef·value ≤ rhs`. Covers
        A≤B (b0960/b0379), A≤0 (b1037), |A|≤|B| (b0380, cells forced ≥0), A≥B+C (b1011/b1017). An
        absent/const cell is folded into `rhs` (b0960 r0343≤r0341 with r0341 absent → r0343 ≤ 0)."""
    ext = str(_dir(pkg_id))
    model = model_store._active_model(pkg_id) or {}
    metrics = model.get("metrics", {})
    framework = ""
    idx = instance_build.module_index(ext)
    for t in selection:
        for i in idx.get(t.upper(), []):
            if i.get("framework"):
                framework = i["framework"]; break
        if framework:
            break
    wbname = _WORKBOOK_BY_FRAMEWORK.get(framework)
    if not wbname or not (_VALIDATIONS_DIR / wbname).exists():
        return {}, []
    rules = workbook_rules.load_workbook_rules(str(_VALIDATIONS_DIR / wbname), framework)
    res = workbook_rules.CellResolver(ext)
    present = {(dp["concept"], tuple(sorted((dp.get("dims") or {}).items())))
               for dps in selection.values() for dp in dps}
    date_over: dict = {}
    le_constraints: list = []

    def linexpr(node, sr, scl, sz, tab):
        """AST node -> (coef_dict {present_key->coef}, const). Absent cells contribute 0 (dropped).
        Returns None if non-linear (cell×cell). iabs() is dropped (cells are forced ≥0)."""
        t = node[0]
        if t == "num":
            return {}, float(node[1])
        if t == "cell":
            c = node[1]
            rvals = workbook_rules._semi(c.get("r")) or [c.get("r")]   # 'r: 0050; 0060' (isum) -> sum
            cvals = workbook_rules._semi(c.get("c")) or [c.get("c")]
            cd = {}
            for rv in rvals:
                for cv in cvals:
                    cell = {"table": c.get("table") or tab, "r": rv or sr,
                            "c": cv or scl, "z": c.get("z") or ([sz] if sz else [])}
                    dps = res.resolve(cell)
                    if dps:
                        k = (dps[0]["concept"], tuple(sorted(dps[0]["dims"].items())))
                        if k in present:                               # absent → value 0 (dropped)
                            cd[k] = cd.get(k, 0.0) + 1.0
            return cd, 0.0
        if t == "neg":
            r = linexpr(node[1], sr, scl, sz, tab)
            return None if r is None else ({x: -v for x, v in r[0].items()}, -r[1])
        if t == "bin" and node[1] in ("+", "-"):
            r1 = linexpr(node[2], sr, scl, sz, tab); r2 = linexpr(node[3], sr, scl, sz, tab)
            if r1 is None or r2 is None:
                return None
            s = 1.0 if node[1] == "+" else -1.0
            cd = dict(r1[0])
            for x, v in r2[0].items():
                cd[x] = cd.get(x, 0.0) + s * v
            return cd, r1[1] + s * r2[1]
        if t == "bin" and node[1] == "*":                       # number × linear (coefficient)
            r1 = linexpr(node[2], sr, scl, sz, tab); r2 = linexpr(node[3], sr, scl, sz, tab)
            if r1 is None or r2 is None:
                return None
            if not r1[0]:
                return {x: r1[1] * v for x, v in r2[0].items()}, r1[1] * r2[1]
            if not r2[0]:
                return {x: r2[1] * v for x, v in r1[0].items()}, r1[1] * r2[1]
            return None                                         # cell × cell
        if t == "call" and node[1] == "isum":
            cd = {}; kk = 0.0
            for arg in node[2]:
                r = linexpr(arg, sr, scl, sz, tab)
                if r is None:
                    return None
                for x, v in r[0].items():
                    cd[x] = cd.get(x, 0.0) + v
                kk += r[1]
            return cd, kk
        if t == "call" and node[1] == "iabs" and node[2]:
            return linexpr(node[2][0], sr, scl, sz, tab)        # |x| → x  (cells ≥ 0)
        return {}, 0.0

    for r in rules:
        if not _rule_in_scope(r, set(selection)):
            continue                               # single-table; multi-table only if _CROSSTABLE
        if "{" not in r["expression"]:
            continue
        try:
            ast = formula_eval._Parser(formula_eval._tokenize(r["expression"])).parse()
        except Exception:
            continue
        node = ast[2] if ast[0] == "if" else ast
        if not isinstance(node, tuple) or node[0] != "cmp" or node[1] not in ("<=", "<", ">=", ">"):
            continue
        op, a, b = node[1], node[2], node[3]
        if op in (">=", ">"):                                   # normalise to  a ≤ b
            a, b = b, a
        tab = r["tables"][0]
        sc = workbook_rules.parse_scope(r["scope"]) or {"table": tab, "rows": [], "cols": [], "z": []}
        for srow in (sc["rows"] or [None]):
            for scol in (sc["cols"] or [None]):
                for sz in (sc["z"] or [None]):
                    # date case: resolve both, if metric is DATE handle via date_over
                    if a[0] == "cell" and b[0] == "cell":
                        ca, cb = a[1], b[1]
                        da = res.resolve({"table": ca.get("table") or tab, "r": ca.get("r") or srow,
                                          "c": ca.get("c") or scol, "z": ca.get("z") or ([sz] if sz else [])})
                        db = res.resolve({"table": cb.get("table") or tab, "r": cb.get("r") or srow,
                                          "c": cb.get("c") or scol, "z": cb.get("z") or ([sz] if sz else [])})
                        if da and db:
                            dt = str((metrics.get(da[0]["concept"].split(":")[-1], {}) or {}).get("datatype", "")).upper()
                            if dt == "DATE":
                                ka = (da[0]["concept"], tuple(sorted(da[0]["dims"].items())))
                                kb = (db[0]["concept"], tuple(sorted(db[0]["dims"].items())))
                                date_over[ka] = "2019-01-01"; date_over[kb] = "2024-12-31"
                                continue
                    # |x| ≤ |y| was linearised as x ≤ y assuming both ≥ 0 — so emit those ≥0 bounds
                    # explicitly (the solver no longer forces every cell ≥0).
                    for side in (a, b):
                        if side[0] == "call" and side[1] == "iabs" and side[2]:
                            cdi, _ = linexpr(side[2][0], srow, scol, sz, tab)
                            for x in (cdi or {}):
                                le_constraints.append(({x: -1.0}, 0.0))   # x ≥ 0
                    la = linexpr(a, srow, scol, sz, tab); lb = linexpr(b, srow, scol, sz, tab)
                    if la is None or lb is None:
                        continue
                    cd = dict(la[0])                            # a - b ≤ 0
                    for x, v in lb[0].items():
                        cd[x] = cd.get(x, 0.0) - v
                    cd = {x: v for x, v in cd.items() if abs(v) > 1e-12}
                    rhs = lb[1] - la[1]
                    if cd:
                        le_constraints.append((cd, rhs))
    return date_over, le_constraints


def _apply_isnull(pkg_id: str, selection: dict) -> int:
    """Remove from the selection every datapoint an `isNull` rule says must be empty (the cell is
    reportable only under a condition the generated row doesn't meet). Returns the count removed."""
    framework = ""
    idx = instance_build.module_index(str(_dir(pkg_id)))
    for t in selection:
        for i in idx.get(t.upper(), []):
            if i.get("framework"):
                framework = i["framework"]
                break
        if framework:
            break
    wbname = _WORKBOOK_BY_FRAMEWORK.get(framework)
    if not wbname or not (_VALIDATIONS_DIR / wbname).exists():
        return 0
    tset = set(selection)
    rules = workbook_rules.load_workbook_rules(str(_VALIDATIONS_DIR / wbname), framework)
    res = workbook_rules.CellResolver(str(_dir(pkg_id)))
    null_keys: set = set()
    for r in rules:
        if len(r["tables"]) != 1 or r["tables"][0] not in tset or r.get("deactivated"):
            continue                              # single-table isNull rules only
        for cell in workbook_rules.isnull_cells(r):
            for dp in res.resolve(cell):
                null_keys.add((dp["concept"], tuple(sorted((dp.get("dims") or {}).items()))))
    if not null_keys:
        return 0
    removed = 0
    for t in list(selection):
        kept = []
        for dp in selection[t]:
            if (dp["concept"], tuple(sorted((dp.get("dims") or {}).items()))) in null_keys:
                removed += 1
            else:
                kept.append(dp)
        selection[t] = kept
    return removed


def _build_module_selection(pkg_id: str, entry_point: str) -> dict:
    """Build a full selection (every datapoint of every table) for an entry-point/module,
    server-side, with random datatype-valid values + cell keys — so the browser needn't assemble
    tens of thousands of datapoints."""
    ext = str(_dir(pkg_id))
    idx = instance_build.module_index(ext)
    tables = sorted({t for t, infos in idx.items() for i in infos if i["module"] == entry_point})
    sel: dict = {}
    for t in tables:
        try:
            g = table_store.grid(pkg_id, t)
        except Exception:
            g = None
        if not g:
            continue
        cols = g["columns"] or [{"concept": None, "dims": {}}]
        rows = g["rows"] or [{"concept": None, "dims": {}}]
        zs = g["zPositions"]
        zlen = len(zs) if len(zs) > 1 else 1
        dps = []
        for z in range(zlen):
            zp = zs[z] if len(zs) > 1 else (zs[0] if zs else None)
            for ri, r in enumerate(rows):
                for ci, c in enumerate(cols):
                    concept = r.get("concept") or c.get("concept") or (zp or {}).get("concept")
                    if not concept:
                        continue
                    dt = r.get("datatype") or c.get("datatype") or (zp or {}).get("datatype")
                    ev = r.get("enumValues") or c.get("enumValues") or (zp or {}).get("enumValues")
                    dims = {**((zp or {}).get("dims") or {}), **r.get("dims", {}), **c.get("dims", {})}
                    dps.append({"concept": concept, "dims": dims, "datatype": dt,
                                "value": instance_build.gen_value(dt, ev), "key": f"{z}:{ri}:{ci}"})
        if dps:
            sel[t] = dps
    return sel


def _drs_ok(drs, concept: str, dims_qname: dict, defaults_local: dict) -> bool:
    """DRS validity for a cell whose dims are full qnames. Typed dims (synthesized value, no ':')
    map to a presence sentinel; explicit members map to domain-qualified localnames — matching
    dim_drs's own convention on both sides."""
    dl = {}
    for d, m in dims_qname.items():
        dl[dim_drs.local(d)] = dim_drs.qmem(m) if ":" in str(m) else "(typed)"
    return drs.is_valid(dim_drs.local(concept), dl, defaults_local)


_TYPED_XSD_TYPES: dict = {}   # cache: typed-domain element localname -> XSD type localname


def _typed_xsd_type(ext: str, typed_domain_qname: str) -> str | None:
    """XSD type localname of a typed-dimension domain element (e.g. eba_typ:DT -> 'date',
    eba_typ:ID -> 'integer', eba_typ:IS/LE -> 'string'). Parses the `**/typ.xsd` typed-domain
    schemas once (cached). Needed so synthesized typed values match the element's datatype — a
    date element rejects '1' (cvc-datatype-valid.1.2.1)."""
    if not _TYPED_XSD_TYPES:
        import glob
        for p in glob.glob(os.path.join(ext, "**", "typ.xsd"), recursive=True):
            try:
                root = etree.parse(p).getroot()
            except Exception:
                continue
            XS = "{http://www.w3.org/2001/XMLSchema}"
            for el in root.findall(f"{XS}element"):
                nm, ty = el.get("name"), el.get("type")
                if nm and ty:
                    _TYPED_XSD_TYPES.setdefault(nm, ty.split(":")[-1])
    return _TYPED_XSD_TYPES.get((typed_domain_qname or "").split(":")[-1])


def _typed_synth_value(ext: str, typed_domain_qname: str, opts: dict | None) -> str:
    """A schema-valid synthesized value for a typed-dimension element, per its XSD type."""
    t = (_typed_xsd_type(ext, typed_domain_qname) or "string").lower()
    date = ((opts or {}).get("date") or "2026-02-28")
    if t == "date":
        return date
    if t in ("datetime",):
        return date + "T00:00:00"
    if t in ("gyear",):
        return date[:4]
    if t in ("gyearmonth",):
        return date[:7]
    if t in ("boolean",):
        return "true"
    if t in ("integer", "int", "long", "short", "byte", "nonnegativeinteger",
             "positiveinteger", "unsignedint", "unsignedlong", "decimal", "double", "float"):
        return "1"
    return "1"                                     # string/token/normalizedString/anyURI/…


def _synth_open_rows(pkg_id: str, selection: dict, model: dict, opts: dict | None = None) -> int:
    """Generate the OPEN tables. Some tables have an empty closed ROW axis because the rows are an
    OPEN dimension (e.g. OF24.03.01.03 rows = boe_dim:UDI typed), so the builder emits no valid rows
    → 0 facts. Synthesize ONE dimensionally-valid row (first z only):
      * typed open dim  → a synthesized value MATCHING the element's XSD type (date/integer/string —
        the builder emits a typedMember; DRS needs only presence);
      * explicit open dim → a real member chosen so the cell passes the table DRS.
    Each synth cell is DRS-validated and tagged `synth=True` so it is EXEMPT from the hypercube filter
    (open tables contributed no cells to that cache). Returns the count of tables populated."""
    ext = str(_dir(pkg_id))
    defaults_local = dim_drs.localize_defaults(model.get("dim_defaults", {}))
    dim_members = model.get("dim_members", {})
    dims_info = model.get("dimensions", {})
    populated = 0
    for code in list(selection.keys()):
        try:
            g = table_store.grid(pkg_id, code)
        except Exception:
            g = None
        if not g:
            continue
        rows = g.get("rows") or []
        cols = g.get("columns") or []
        if rows or not cols:
            continue                              # already has closed rows, or no columns → skip
        yopen = [o for o in (g.get("openAxes") or []) if o.get("axis") == "y"]
        if not yopen:
            continue
        defp = dim_drs.def_path_for(ext, code)
        if not defp:
            continue
        try:
            drs = dim_drs.TableDRS(defp)
        except Exception:
            continue
        base_dims: dict = {}
        explicit: list = []
        for o in yopen:
            dimq = o["dimension"]
            if o.get("typed"):                    # synth a value matching the typed element's XSD type
                td = (dims_info.get(dim_drs.local(dimq)) or {}).get("typedDomain")
                base_dims[dimq] = _typed_synth_value(ext, td, opts)
            else:
                explicit.append((dimq, dim_drs.local(dimq)))
        # ONE synth row per z-layer (not just the first) — cross-table consistency rules (b0814)
        # sum an open source table PER z against a closed table that spans every z, so the open
        # table must exist in each referenced z-layer.
        zs = g.get("zPositions") or []
        zlist = list(range(len(zs))) if len(zs) > 1 else [0]
        dps = []
        for zi in zlist:
            zp = zs[zi] if (zs and len(zs) > 1) else (zs[0] if zs else None)
            zdims = (zp or {}).get("dims") or {}
            for ci, c in enumerate(cols):
                concept = c.get("concept") or (zp or {}).get("concept")
                if not concept:
                    continue
                full = {**zdims, **(c.get("dims") or {}), **base_dims}
                ok = True
                for dimq, dloc in explicit:       # pick a DRS-valid real member for each explicit dim
                    chosen = None
                    for m in (dim_members.get(dloc) or []):
                        if _drs_ok(drs, concept, {**full, dimq: m["qname"]}, defaults_local):
                            chosen = m["qname"]
                            break
                    if chosen is None:
                        ok = False
                        break
                    full[dimq] = chosen
                if not ok or not _drs_ok(drs, concept, full, defaults_local):
                    continue
                dt = c.get("datatype") or (zp or {}).get("datatype")
                ev = c.get("enumValues") or (zp or {}).get("enumValues")
                dps.append({"concept": concept, "dims": full, "datatype": dt,
                            "value": instance_build.gen_value(dt, ev), "key": f"{zi}:0:{ci}", "synth": True})
        if dps:
            selection[code] = dps
            populated += 1
    return populated


def _dir(pkg_id: str) -> Path:
    return config.CACHE_DIR / pkg_id


def _sdir(pkg_id: str) -> Path:
    return _dir(pkg_id) / "solved"


def _val_dir(modpath: str | None) -> str | None:
    """`…/<framework>/<date>/mod/<module>.xsd` -> `…/<framework>/<date>/val` (the vr-*.xml dir)."""
    if not modpath:
        return None
    d = os.path.dirname(os.path.dirname(modpath))   # drop /mod/<module>.xsd
    vd = os.path.join(d, "val")
    return vd if os.path.isdir(vd) else None


def _run(pkg_id: str, selection: dict, opts: dict, entry_point: str | None = None) -> None:
    job = _JOBS[pkg_id]
    try:
        import random
        import solve_all
        from solve import solve
        from instance import Instance

        if not selection and entry_point:
            job["phase"] = f"building all tables of {entry_point}…"
            selection = _build_module_selection(pkg_id, entry_point)
            if not selection:
                raise RuntimeError(f"No tables found for entry point '{entry_point}'.")

        model = model_store._active_model(pkg_id)
        if model is None:
            raise RuntimeError("Dictionary model not built yet; open the Dictionary tab first.")
        defaults = model.get("dim_defaults", {})
        ext = str(_dir(pkg_id))
        sdir = _sdir(pkg_id)
        sdir.mkdir(parents=True, exist_ok=True)
        rng = random.Random(1)

        # OPEN-ROW SYNTHESIS: tables whose row axis is an open/typed dimension have an empty closed
        # cartesian → 0 facts. Synthesize one DRS-valid row each (first z) so they generate. These
        # cells are tagged synth=True and exempt from the hypercube filter below.
        try:
            job["openRowsPopulated"] = _synth_open_rows(pkg_id, selection, model, opts)
        except Exception as e:
            job["openRowsError"] = str(e)

        # HYPERCUBE FILTER: if the module's valid-cell set has been extracted, drop the
        # dimensionally-invalid (greyed) cartesian cells up-front — no over-generation, and rule
        # cells then resolve to their unique valid fact. (Module = entry_point, else first table's.)
        module = entry_point
        if not module:
            idx0 = instance_build.module_index(ext)
            for t in selection:
                infos = idx0.get(t.upper(), [])
                if infos:
                    module = infos[0]["module"]
                    break
        vc = hypercube_store.valid_cells(pkg_id, module) if module else None
        if vc:
            kept = 0
            for t in list(selection):
                f = [dp for dp in selection[t]
                     if dp.get("synth")                       # DRS-validated open-row cells: keep
                     or hypercube_store.cell_key(dp["concept"], dp.get("dims") or {}, defaults) in vc]
                selection[t] = f
                kept += len(f)
            job["hypercube"] = {"module": module, "kept": kept}

        # RULE-DRIVEN VALUES: override the random values with values computed to satisfy the
        # workbook rules (parse expression -> resolve cells via rc-code bridge -> derive). This
        # is what actually makes the business rules pass (bind-based solve doesn't match our facts).
        job["phase"] = "computing rule-consistent values…"
        try:
            idx = instance_build.module_index(ext)
            framework = ""
            for t in selection:
                for i in idx.get(t.upper(), []):
                    if i.get("framework"):
                        framework = i["framework"]
                        break
                if framework:
                    break
            # INEQUALITY/DATE constraints: pin 'cell ≤ 0' cells negative (feeds the additive solver as
            # fixed leaves so totals stay consistent) and order start/end dates.
            try:
                date_over, le_constraints = _constraint_values(pkg_id, selection)
            except Exception as e:
                date_over, le_constraints = {}, []
                job["constraintError"] = str(e)
            present_keys = {(dp["concept"], tuple(sorted((dp.get("dims") or {}).items())))
                            for dps in selection.values() for dp in dps}
            rv = _rule_driven_values(pkg_id, framework, list(selection.keys()),
                                     present_keys=present_keys, le_constraints=le_constraints)
            metrics = model.get("metrics", {})

            # STAGE 2 — cross-table aggregation post-pass (safe; preserves Stage 1). Derive the
            # cross-table TARGET cells (e.g. b0844 OF34.07 = isum(OF08 …)) from the OTHER cells'
            # current values, without fusing tables into the solver. Stage-1 cells (rv) are the
            # fixed baseline and are never overridden; derived negatives are skipped.
            if _CROSSTABLE:
                try:
                    _CTNUM = {"MONETARY", "DECIMAL", "PERCENTAGE", "INTEGER"}
                    current_values: dict = {}
                    for dps in selection.values():
                        for dp in dps:
                            if (dp.get("datatype") or "").upper() not in _CTNUM:
                                continue
                            k = (dp["concept"], tuple(sorted((dp.get("dims") or {}).items())))
                            try:
                                current_values[k] = float(dp.get("value"))
                            except (TypeError, ValueError):
                                current_values[k] = 0.0
                    for k, vv in rv.items():                  # Stage-1 values are the fixed baseline
                        current_values[k] = vv["value"]
                    stage1_keys = set(rv)
                    ct = _crosstable_agg_values(pkg_id, framework, list(selection.keys()),
                                                current_values, stage1_keys, present_keys,
                                                allow_override=_CT_OVERRIDE)
                    overridden = sum(1 for k in ct if k in stage1_keys)
                    for k, v in ct.items():                   # add/override cross-table targets
                        rv[k] = v
                    job["crosstable"] = len(ct)
                    job["crosstableOverrode"] = overridden     # Stage-1 cells the cross-table pass moved
                except Exception as e:
                    job["crosstableError"] = str(e)

            # NON-NEGATIVE ADDITIVE SOLVE for over-determined 2-D tables (OF08.01.01.01 etc.): re-solve
            # their single-table additive rules with an LP so EVERY rule holds AND all cells ≥ 0 (the
            # random-free solve would need negatives). AUTHORITATIVE for these tables — runs AFTER the
            # cross-table aggregation (so that pass can't clobber the b0745-consistent values) and
            # BEFORE the open-link (so OF08.02 calibrates to the FINAL OF08.01 r0070).
            tset_nn = _NONNEG_TABLES & set(selection)
            if tset_nn:
                try:
                    na = _nonneg_additive_solve(pkg_id, framework, tset_nn, selection, le_constraints)
                    for k, v in na.items():
                        rv[k] = v
                    job["nonnegSolve"] = len(na)
                except Exception as e:
                    job["nonnegError"] = str(e)

            # CONSTANT-SUM rules (Σ cells = k, e.g. b0778 'shares sum to 1'): assign free cells to
            # sum exactly to the constant. Stage-1-owned cells are left untouched.
            try:
                cs = _constant_sum_values(pkg_id, framework, selection, set(rv))
                for k, v in cs.items():
                    if k not in rv:                           # don't disturb a rule-driven cell
                        rv[k] = v
                job["constSum"] = len(cs)
            except Exception as e:
                job["constSumError"] = str(e)

            # CROSS-TABLE OPEN-SOURCE LINK (b0814): derive open (synth) source cells from the closed
            # target they must sum to (e.g. OF08.02 cX = OF08.01 r0070 cX), matched on closed dims.
            # Only the open synth cell moves; the closed Stage-1 table is read-only.
            try:
                ol = _crosstable_open_link(pkg_id, framework, selection, model, rv)
                for k, v in ol.items():
                    rv[k] = v                                 # open synth cells (not Stage-1-owned)
                job["openLink"] = len(ol)
            except Exception as e:
                job["openLinkError"] = str(e)

            def _fmt(value, dt):
                dtu = (dt or "MONETARY").upper()
                return str(int(round(value))) if dtu in ("MONETARY", "INTEGER") else str(round(value, 4))

            # Override any built cell a rule references. (We deliberately do NOT *add* bridge
            # cells that the cartesian didn't produce: a workbook cell ref (table,r,c) often
            # underspecifies the full dimensional context — the extra dims come from the table's
            # hypercube — so emitting it standalone is dimensionally invalid. Pinning rule cells
            # to their unique valid fact requires hypercube extraction; matched cells are valid.)
            _NUMERIC_DT = {"MONETARY", "DECIMAL", "PERCENTAGE", "INTEGER"}
            n_over = 0
            for dps in selection.values():
                for dp in dps:
                    # Only override NUMERIC cells: a rule's additive expression can resolve to a
                    # boolean/enum/string metric (e.g. bi10007) via the rc-code bridge, and writing a
                    # numeric sum there produces an xmlSchema:valueError. Leave non-numerics as generated.
                    if (dp.get("datatype") or "").upper() not in _NUMERIC_DT:
                        continue
                    key = (dp["concept"], tuple(sorted((dp.get("dims") or {}).items())))
                    if key in rv:
                        dp["value"] = _fmt(rv[key]["value"], dp.get("datatype"))
                        n_over += 1
            job["ruleDriven"] = n_over

            # Apply date-ordering directly to the selection (dates aren't numeric / not in the LP).
            n_con = 0
            for dps in selection.values():
                for dp in dps:
                    key = (dp["concept"], tuple(sorted((dp.get("dims") or {}).items())))
                    if key in date_over:
                        dp["value"] = date_over[key]; n_con += 1
            job["constraints"] = n_con
        except Exception as e:
            job["ruleDrivenError"] = str(e)

        # NON-additive derivation rules (exp/imax/ratios) — derive their target cells from the
        # additive-solved inputs. (Toggle off via GENVALID_NONLINEAR=0 for A/B measurement.)
        try:
            job["nonlinear"] = (_apply_nonlinear(pkg_id, selection)
                                if os.environ.get("GENVALID_NONLINEAR", "1") == "1" else 0)
        except Exception as e:
            job["nonlinearError"] = str(e)

        # isNull rules: drop cells the rules require to be EMPTY (e.g. b1039 — columns 0101/0102/0103
        # are null for non-slotting exposure classes). Removing them from the selection means no fact
        # is emitted there, satisfying the assertion.
        try:
            n_null = _apply_isnull(pkg_id, selection)
            job["isNullRemoved"] = n_null
        except Exception as e:
            job["isNullError"] = str(e)

        built = instance_build.build_instances(ext, model, selection, opts)
        values: dict[str, dict] = {}
        per_module = []
        for inst_info in built["instances"]:
            module = inst_info["module"]
            tmp = sdir / f"_genvalid_{module}.xbrl"
            tmp.write_bytes(inst_info["xml"])
            val_dir = _val_dir(inst_info.get("modpath"))
            stats = {}
            if val_dir:
                cache = str(sdir / f"rules-{inst_info.get('framework') or module}.pkl")
                rules = solve_all.parse_all_rules(val_dir, cache=cache)
                inst = Instance(str(tmp))
                stats = solve(inst, rules, defaults, rng)
                inst.write(str(tmp))
            else:
                stats = {"skipped": "no val dir for module"}
            # index solved facts by (concept local, contextRef) and reflect onto grid cells
            solved = Instance(str(tmp))
            idx = {}
            for f in solved.facts:
                if f.el is None:
                    continue
                idx[(etree.QName(f.el).localname, f.el.get("contextRef"))] = f.value
            for fm in inst_info.get("fact_map", []):
                v = idx.get((fm["local"], fm["cid"]))
                if v is not None and fm.get("table") and fm.get("key") is not None:
                    values.setdefault(fm["table"], {})[fm["key"]] = v
            per_module.append({"module": module, "framework": inst_info.get("framework"),
                               "tables": inst_info.get("tables", []), "stats": stats,
                               "ruleCount": len(rules) if val_dir else 0})

        tables = sorted({t for inst in built["instances"] for t in inst.get("tables", [])})
        result = {
            "status": "ready",
            "values": values,
            "tables": tables,
            "modules": per_module,
            "ruleDriven": job.get("ruleDriven", 0),
            "ruleDrivenError": job.get("ruleDrivenError"),
            "unmapped": built.get("unmapped", []),
            "errors": built.get("errors", []),
            "elapsedMs": round((time.time() - job["t0"]) * 1000),
        }
        (sdir / "genvalid.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        job.update(result)
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


def start(pkg_id: str, selection: dict, opts: dict) -> dict:
    if not (_dir(pkg_id) / ".extracted").exists():
        return {"status": "error", "error": "Package not found / not extracted."}
    if not selection:
        return {"status": "error", "error": "No tables/values supplied."}
    job = _JOBS.get(pkg_id)
    if job and job["status"] == "solving":
        return {"status": "solving"}
    _JOBS[pkg_id] = {"status": "solving", "t0": time.time()}
    threading.Thread(target=_run, args=(pkg_id, selection, opts), daemon=True).start()
    return {"status": "solving"}


def start_module(pkg_id: str, entry_point: str, opts: dict) -> dict:
    """Generate full valid data for EVERY table of an entry-point/module (server builds the
    selection). Async — for a big module the build + rule parse takes a while."""
    if not (_dir(pkg_id) / ".extracted").exists():
        return {"status": "error", "error": "Package not found / not extracted."}
    if not entry_point:
        return {"status": "error", "error": "No entry point supplied."}
    job = _JOBS.get(pkg_id)
    if job and job["status"] == "solving":
        return {"status": "solving"}
    _JOBS[pkg_id] = {"status": "solving", "t0": time.time(), "entryPoint": entry_point}
    threading.Thread(target=_run, args=(pkg_id, {}, opts, entry_point), daemon=True).start()
    return {"status": "solving"}


def status(pkg_id: str) -> dict:
    job = _JOBS.get(pkg_id)
    if job:
        keys = ("status", "values", "tables", "modules", "ruleDriven", "ruleDrivenError",
                "hypercube", "unmapped", "errors", "elapsedMs", "error", "phase", "entryPoint")
        return {k: job[k] for k in keys if k in job}
    return {"status": "absent"}
