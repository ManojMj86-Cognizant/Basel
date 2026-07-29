"""Surgical, minimal-perturbation business-rule fixer for an EXISTING instance.

Unlike the genvalid path (regenerate every datapoint → global solve), this seeds from an already-built
`.xbrl`, classifies which rules still fail OFFLINE (TDG absent=0 semantics), and re-solves ONLY the
connected components of cells that a failing rule touches — leaving every other cell byte-identical.

The safe unit of change is the connected component (a cell is shared across many rules), NOT the single
rule. Within a dirty component we solve an LP whose objective MINIMISES deviation from the current values,
subject to ALL of that component's rules (passing + failing) as hard constraints. Cells in a clean
component are never entered into a solve.

Architecture mirrors genvalid's split:
  * SINGLE-table additive + inequality  -> fused per-table LP (components are small & safe).
  * CROSS-table additive                -> aggregation post-pass (derive the aggregate/total cell from
                                           the others; never fuse tables into one giant LP).

Keyspace: everything is keyed by the instance's own fact identity
    key = (concept-localname, frozenset((dim-local, member-local)))
so a solved value maps DIRECTLY back to its fact element for write-back — no qname/local reconciliation.

Runs OFFLINE (no Arelle). Defaults to --dry-run (reports the diff, writes nothing).

Usage (from boe_xbrl_gen/, PYTHONIOENCODING=utf-8):
    python -m src.solve_existing --tables OF08.02.01.01            # dry-run one table
    python -m src.solve_existing --tables all --level L1,L2        # dry-run all single-table levels
    python -m src.solve_existing --tables all --cross --apply --out fixed.xbrl
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

from lxml import etree

sys.path.insert(0, os.path.dirname(__file__))          # bare imports (workbook_rules, formula_eval)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import workbook_rules            # noqa: E402
import formula_eval              # noqa: E402
from src import dim_drs          # noqa: E402
from src import instance_build   # noqa: E402

XBRLI = "http://www.xbrl.org/2003/instance"
TOL = 0.5
_NUM = {"MONETARY", "DECIMAL", "PERCENTAGE", "INTEGER"}

ROOT = r"C:\Users\177069\ClaudeLearning"
BASE = (r"C:\Users\177069\ClaudeLearning\boe_xbrl_gen\studio\backend\.cache\packages"
        r"\50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181")
EXT = os.path.join(BASE, "Banking_4.0.0")
WB = os.path.join(ROOT, "boebankingtaxonomyvalidationsv400",
                  "Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx")
DEFAULT_FILE = os.path.join(ROOT, "ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID.xbrl")

# The OF08 cross-table cluster for the joint-LP solve. OF09.02 is EXCLUDED on purpose: its CEG-total
# target rows are ABSENT in the instance (must be GENERATED, not edited), so its cross-table rules would
# degenerate to 'Σ OF08.01 sources = 0' and corrupt the LP. Handle OF09.02 with a separate fact-gen pass.
DEFAULT_CLUSTER = ("OF08.01.01.01,OF08.01.01.02,OF08.02.01.01,OF08.03.01.01,"
                   "OF08.06.01.01,OF08.07.01.01,OF34.07.01.01")


def local(q):
    return dim_drs.local(q)


# dim-local -> default member-local. XBRL omits a dimension from a context when its member is the
# dimension's DEFAULT, so instance facts never carry defaults — but the rc-code bridge does. We drop
# defaults from every key so resolved cells match the real facts (fixes the C04 r0131 / OF22 r0050
# "absent" false-passes). Populated from model.dim_defaults in run().
_DEFAULTS: dict = {}


def _dimset(items):
    """frozenset of (dim-local, member-local), dropping default members."""
    return frozenset((k, v) for k, v in items if _DEFAULTS.get(k) != v)


def fkey(concept, dims):
    return (local(concept), _dimset((local(k), local(v)) for k, v in (dims or {}).items()))


# --------------------------------------------------------------------- instance load
class Facts:
    """Current numeric facts of the instance, keyed by fact identity, with the lxml element for
    write-back and the concept datatype for formatting/rounding."""

    def __init__(self, path: str, metrics: dict):
        raw = open(path, "rb").read()
        self.bom = raw[:3] == b"\xef\xbb\xbf"
        self.tree = etree.fromstring(raw[3:] if self.bom else raw)
        self.metrics = metrics
        ctx = {}
        for c in self.tree.findall(f"{{{XBRLI}}}context"):
            dd = {}
            sc = c.find(f"{{{XBRLI}}}scenario")
            if sc is not None:
                for em in sc:
                    if not em.get("dimension"):
                        continue
                    ln = etree.QName(em).localname
                    if ln == "explicitMember":
                        dd[local(em.get("dimension"))] = local((em.text or "").strip())
                    elif ln == "typedMember":        # open/typed dim: include the typed value so
                        inner = "".join(em.itertext()).strip()   # facts don't collapse to one key
                        dd[local(em.get("dimension"))] = "typed:" + inner
            ctx[c.get("id")] = dd
        self.val: dict = {}
        self.el: dict = {}
        self.dec: dict = {}
        self.collisions = 0
        for el in self.tree:
            cref = el.get("contextRef")
            if cref is None:
                continue
            try:
                v = float((el.text or "").strip())
            except (ValueError, TypeError):
                continue
            k = (local(etree.QName(el).localname), _dimset(ctx.get(cref, {}).items()))
            if k in self.val:
                self.collisions += 1        # two facts collapse to one key (e.g. a typed/open dim
                continue                     # not captured) — keep the first; DON'T write-back either.
            self.val[k] = v
            self.el[k] = el
            try:
                self.dec[k] = int(el.get("decimals"))
            except (TypeError, ValueError):
                self.dec[k] = None

    def datatype_of(self, key) -> str:
        return str((self.metrics.get(key[0], {}) or {}).get("datatype", "MONETARY")).upper()

    def index(self) -> dict:
        """concept-local -> [(full-dims-dict, full-key)] for signature matching on open tables."""
        idx = defaultdict(list)
        for k in self.val:                       # k = (concept-local, frozenset dim-local items)
            idx[k[0]].append((dict(k[1]), k))
        return idx

    def halfulp(self, key) -> float:
        """Half a unit-in-the-last-place for this fact, from @decimals: decimals=-3 → ±500,
        decimals=0 → ±0.5, decimals=4 → ±5e-5. Absent/unknown → ±0.5."""
        d = self.dec.get(key)
        return 0.5 * (10.0 ** (-d)) if d is not None else 0.5

    def tol_of(self, coefs: dict) -> float:
        """XBRL-interval tolerance for `Σ coef·x  (?)  0`: Σ |coef|·halfULP(cell). A ±1 residual on
        decimals=-3 facts (±500 each) is absorbed — matching how TDG compares rounded values."""
        return sum(abs(c) * self.halfulp(k) for k, c in coefs.items()) or 0.5

    def is_int_like(self, key) -> bool:
        return self.datatype_of(key) in ("MONETARY", "INTEGER")

    def fmt(self, key, value) -> str:
        return str(int(round(value))) if self.is_int_like(key) else str(round(value, 4))

    def write(self, path: str):
        out = etree.tostring(self.tree, xml_declaration=True, encoding="UTF-8")
        if self.bom:
            out = b"\xef\xbb\xbf" + out
        open(path, "wb").write(out)


# ------------------------------------------------------- open-dimension signature expansion
def expand_to_full(closed_coefs: dict, fidx: dict):
    """Turn a CLOSED-key constraint `Σ coef·closed_cell (?) rhs` into per-open-signature FULL-fact-key
    constraints. On a hypercube (open) table one closed cell (e.g. mi116{BAS,MCY}) maps to many facts
    that carry extra open dims (APR,PRP,OGR,…); TDG asserts the rule PER open-dim signature (all dims
    except the ones the cells pin). We pin = union of the constraint's closed dim KEYS, group each
    closed cell's facts by signature (dims minus pinned), and for every signature emit one constraint
    over the actual facts at that signature. Closed tables: each closed key == its one fact, signature
    empty → a single constraint (identical to the closed path). Yields {full_key: coef} dicts.

    closed_coefs: {(concept-local, frozenset closed-dim items): coef}; fidx = Facts.index()."""
    pinned = set()
    for ck in closed_coefs:
        pinned |= {dk for dk, _ in ck[1]}
    per = []                                     # [(coef, {sig: [full_key,...]})]
    sigs: set = set()
    for ck, coef in closed_coefs.items():
        concept = ck[0]; cdims = dict(ck[1])
        sm = defaultdict(list)
        for dims, fk in fidx.get(concept, []):
            if all(dims.get(dk) == dv for dk, dv in cdims.items()):      # fact ⊇ the cell's closed dims
                sig = tuple(sorted((k, v) for k, v in dims.items() if k not in pinned))
                sm[sig].append(fk)
        per.append((coef, sm)); sigs |= set(sm)
    for sig in sigs:
        coefs: dict = {}
        for coef, sm in per:
            for fk in sm.get(sig, []):
                coefs[fk] = coefs.get(fk, 0.0) + coef
        coefs = {k: v for k, v in coefs.items() if abs(v) > 1e-12}
        if coefs:
            yield coefs


def _first_z(rule):
    sc = workbook_rules.parse_scope(rule.get("scope", ""))
    zs = sc["z"] if sc else []
    return zs[0] if zs else None


# --------------------------------------------------------------------- rule -> equations
def module_tables(module: str) -> set:
    idx = instance_build.module_index(EXT)
    return {t.upper() for t, infos in idx.items() for i in infos if i["module"] == module}


def additive_equations(rules, res, tset, single_only: bool, want: set | None = None,
                        single_z: bool = False):
    """Yield (rule_code, tables, [(key, coef)], multi) for each concrete additive equation whose
    cells all resolve. Absent cells stay in the term list (value 0) so the caller can treat them as
    constants; the caller drops non-present keys from the variable set. `single_z` restricts to the
    first scope z-layer (open-table fan-out control)."""
    for r in rules:
        rt = {t.upper() for t in r["tables"]}
        if not r["tables"] or r.get("deactivated") or not (rt <= tset):
            continue
        if want and not (rt & want):
            continue
        multi = len(rt) > 1
        if single_only and multi:
            continue
        if (not single_only) and (not multi):
            continue
        pe = workbook_rules.parse_expression(r.get("expression", ""))
        if not (pe and pe.get("op") == "i="):
            continue
        zf = _first_z(r) if single_z else None
        for a in workbook_rules.expand_scoped_asts(r):
            if a["op"] != "i=":
                continue
            if zf is not None:                        # keep only the first scope z-layer
                zc = next((t["cell"]["z"] for side in ("lhs", "rhs") for t in a[side]
                           if t["cell"].get("z")), None)
                if zc and zf not in zc:
                    continue
            # Include EVERY resolved cell; an unresolvable/absent cell just contributes 0 — matching
            # the classifier exactly. (Do NOT drop the whole rule on an unresolved cell: then the LP
            # wouldn't constrain a rule the classifier checks, and moving cells could break it.)
            terms = []
            pref = []                                  # keys on a lone single-term side = the 'total'
            for side, sgn in (("lhs", 1.0), ("rhs", -1.0)):
                lone = len(a[side]) == 1
                for t in a[side]:
                    for dp in res.resolve(t["cell"]):
                        k = fkey(dp["concept"], dp["dims"])
                        terms.append((k, sgn * t["coef"]))
                        if lone:
                            pref.append(k)
            if terms:
                yield r["code"], r["tables"], terms, multi, pref


def _linexpr(node, cv):
    """formula_eval AST -> (coefs{key:coef}, const) over present cells; None if non-linear.
    cv(cellref) -> list of keys. Absent cells contribute nothing (=0)."""
    t = node[0]
    if t == "num":
        return {}, float(node[1])
    if t == "cell":
        cd = {}
        for k in cv(node[1]):
            cd[k] = cd.get(k, 0.0) + 1.0
        return cd, 0.0
    if t == "neg":
        r = _linexpr(node[1], cv)
        return None if r is None else ({k: -v for k, v in r[0].items()}, -r[1])
    if t == "bin" and node[1] in ("+", "-"):
        a = _linexpr(node[2], cv); b = _linexpr(node[3], cv)
        if a is None or b is None:
            return None
        s = 1.0 if node[1] == "+" else -1.0
        cd = dict(a[0])
        for k, v in b[0].items():
            cd[k] = cd.get(k, 0.0) + s * v
        return cd, a[1] + s * b[1]
    if t == "bin" and node[1] == "*":
        a = _linexpr(node[2], cv); b = _linexpr(node[3], cv)
        if a is None or b is None:
            return None
        if not a[0]:
            return {k: a[1] * v for k, v in b[0].items()}, a[1] * b[1]
        if not b[0]:
            return {k: b[1] * v for k, v in a[0].items()}, a[1] * b[1]
        return None                                       # cell × cell
    if t == "call" and node[1] == "isum":
        cd = {}; c = 0.0
        for arg in node[2]:
            r = _linexpr(arg, cv)
            if r is None:
                return None
            for k, v in r[0].items():
                cd[k] = cd.get(k, 0.0) + v
            c += r[1]
        return cd, c
    if t == "call" and node[1] in ("iabs", "abs") and node[2]:
        return _linexpr(node[2][0], cv)                   # |x| -> x (cells ≥ 0)
    return None                                           # imax/imin/exp/other -> non-linear


def comparison_constraints(rules, res, tset, present, single_only: bool, want: set | None = None,
                           single_z: bool = False):
    """Yield (code, kind, tables, coefs{key:coef}, rhs) for linear comparison rules:
      kind='le' meaning `Σ coef·x ≤ rhs`  (from <=,<,>=,>  normalised to ≤),
      kind='eq' meaning `Σ coef·x  = rhs` (from `=`, e.g. b0529 'cell = 0').
    Skips non-linear, preconditioned-as-false, `!=`, date, and absent-only constraints."""
    for r in rules:
        rt = {t.upper() for t in r["tables"]}
        if not r["tables"] or r.get("deactivated") or not (rt <= tset):
            continue
        if want and not (rt & want):
            continue
        if single_only == (len(rt) > 1):
            continue
        expr = r.get("expression", "")
        if "{" not in expr:
            continue
        try:
            ast = formula_eval._Parser(formula_eval._tokenize(expr)).parse()
        except Exception:
            continue
        node = ast[2] if ast[0] == "if" else ast
        if not (isinstance(node, tuple) and node[0] == "cmp" and node[1] in ("<=", "<", ">=", ">", "=")):
            continue
        op, A, B = node[1], node[2], node[3]
        kind = "eq" if op == "=" else "le"
        if op in (">=", ">"):
            A, B = B, A
        sc = workbook_rules.parse_scope(r.get("scope", "")) or {"table": "", "rows": [], "cols": [], "z": []}
        tab = sc.get("table") or (r["tables"][0] if r["tables"] else "")
        zlist = (sc["z"] or [None])
        if single_z and sc["z"]:
            zlist = sc["z"][:1]                        # first z-layer only (open-table fan-out control)
        for sr in (sc["rows"] or [None]):
            for scl in (sc["cols"] or [None]):
                for sz in zlist:
                    def cv(cref, _sr=sr, _sc=scl, _sz=sz):
                        rvals = workbook_rules._semi(cref.get("r")) or [cref.get("r") or _sr]
                        cvals = workbook_rules._semi(cref.get("c")) or [cref.get("c") or _sc]
                        zz = cref.get("z") or ([_sz] if _sz else [])
                        keys = []
                        for rv in rvals:
                            for cvl in cvals:
                                for dp in res.resolve({"table": cref.get("table") or tab, "r": rv,
                                                       "c": cvl, "z": zz}):
                                    k = fkey(dp["concept"], dp["dims"])
                                    if present is None or k in present:   # None = don't filter (open path)
                                        keys.append(k)
                        return keys
                    la = _linexpr(A, cv); lb = _linexpr(B, cv)
                    if la is None or lb is None:
                        continue
                    cd = dict(la[0])
                    for k, v in lb[0].items():
                        cd[k] = cd.get(k, 0.0) - v
                    cd = {k: v for k, v in cd.items() if abs(v) > 1e-12}
                    if cd:
                        yield r["code"], kind, r["tables"], cd, lb[1] - la[1]


# --------------------------------------------------------------------- union-find
class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        r = x
        while self.p[r] != r:
            r = self.p[r]
        while self.p[x] != r:
            self.p[x], x = r, self.p[x]
        return r

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


# --------------------------------------------------------------------- single-table LP
def solve_component(cells, cur, eqs, les, facts: Facts):
    """Minimal-perturbation MILP for one component. vars = present cells (int-like cells forced INTEGER
    so the solution is exact — no post-rounding drift that would tip tight equations over). Objective:
    minimise Σ|x−cur|. Constraints (all with XBRL rounding tolerance): additive equalities as two-sided
    bands `rhs−tol ≤ Σcoef·x ≤ rhs+tol`, comparisons `Σcoef·x ≤ rhs+tol`, cells ≥ 0.
    Returns {key: new_value}. {} if infeasible / scipy missing / time-limited with no incumbent."""
    try:
        import numpy as np
        from scipy.optimize import milp, LinearConstraint, Bounds
        from scipy.sparse import csr_matrix
    except Exception:
        return {}
    INF = np.inf
    varlist = sorted(cells)
    idx = {k: i for i, k in enumerate(varlist)}
    n = len(varlist)
    if n == 0:
        return {}
    # variables [x(n), d(n)]; minimise Σ d, with d ≥ |x − cur| (two rows), x ≥ 0.
    W = 2 * n
    ar, ac, av, lo, hi = [], [], [], [], []
    ri = 0
    for i in range(n):
        ar += [ri, ri]; ac += [i, n + i]; av += [1.0, -1.0]; lo.append(-INF); hi.append(cur[varlist[i]]); ri += 1   # x−d ≤ cur
        ar += [ri, ri]; ac += [i, n + i]; av += [-1.0, -1.0]; lo.append(-INF); hi.append(-cur[varlist[i]]); ri += 1  # −x−d ≤ −cur
    for coefs, rhs, tol in eqs:                        # equality band:  rhs−tol ≤ Σcoef·x ≤ rhs+tol
        row = [(idx[k], float(co)) for k, co in coefs.items() if k in idx]
        if not row:
            continue
        for j, co in row:
            ar.append(ri); ac.append(j); av.append(co)
        lo.append(float(rhs) - float(tol)); hi.append(float(rhs) + float(tol)); ri += 1
    for cd, rhs, tol in les:                           # comparison:  Σcoef·x ≤ rhs+tol
        row = [(idx[k], float(co)) for k, co in cd.items() if k in idx]
        if not row:
            continue
        for j, co in row:
            ar.append(ri); ac.append(j); av.append(co)
        lo.append(-INF); hi.append(float(rhs) + float(tol)); ri += 1
    A = csr_matrix((av, (ar, ac)), shape=(ri, W))
    c = np.zeros(W); c[n:] = 1.0
    integ = np.zeros(W)
    for k, i in idx.items():
        if facts.is_int_like(k):
            integ[i] = 1                               # exposures/counts are integer → exact solve
    bounds = Bounds(np.zeros(W), np.full(W, INF))
    tl = float(os.environ.get("SOLVE_MILP_TIMEOUT", "120"))
    try:
        res = milp(c, constraints=LinearConstraint(A, np.array(lo), np.array(hi)),
                   integrality=integ, bounds=bounds, options={"time_limit": tl})
    except Exception:
        return {}
    if res.x is None:
        return {}
    out = {}
    for k, i in idx.items():
        v = res.x[i]
        v = int(round(v)) if facts.is_int_like(k) else round(v, 4)
        out[k] = float(v)
    return out


def solve_joint(cells, cur, eqs, les, facts: Facts):
    """CONTINUOUS-LP joint solve for a whole cross-table CLUSTER (scales to thousands of cells, unlike the
    MILP). Minimises Σ|x−cur| subject to ALL cluster rules at once — additive equalities as tolerance bands
    `rhs−tol ≤ Σcoef·x ≤ rhs+tol`, comparisons `Σcoef·x ≤ rhs+tol`, x ≥ 0 — so the cross-table rules are
    satisfied JOINTLY (no greedy per-rule breakage). If the HARD system is infeasible (the cluster's rules
    over-determine each other), retry with a penalised SLACK per rule constraint so the LP always solves and
    minimises TOTAL violation (genvalid's approach). Values round to integers (≪ the ±500 monetary tol)."""
    linprog = workbook_rules._get_linprog()
    if linprog is None:
        return {}
    import numpy as np
    from scipy.sparse import csr_matrix
    varlist = sorted(cells)
    idx = {k: i for i, k in enumerate(varlist)}
    n = len(varlist)
    if n == 0:
        return {}
    # rule constraint rows over x only (Σ coef·x ≤ rhs), as {xindex: coef}; eq becomes two banded rows
    crows = []
    for cd, rhs, tol in les:
        row = {}
        for k, co in cd.items():
            if k in idx:
                row[idx[k]] = row.get(idx[k], 0.0) + float(co)
        if row:
            crows.append((row, float(rhs) + float(tol)))
    for coefs, rhs, tol in eqs:
        row = {}
        for k, co in coefs.items():
            if k in idx:
                row[idx[k]] = row.get(idx[k], 0.0) + float(co)
        if not row:
            continue
        crows.append((dict(row), float(rhs) + float(tol)))
        crows.append(({j: -c for j, c in row.items()}, float(tol) - float(rhs)))
    ncr = len(crows)
    tl = float(os.environ.get("JOINT_LP_TIMEOUT", "600"))

    def build(with_slack):
        S = ncr if with_slack else 0
        W = 2 * n + S                                    # [x(n), d(n), slack(S)]
        ur, uc, ud, bub = [], [], [], []
        ri = 0
        for i in range(n):                               # d ≥ |x − cur|
            ur += [ri, ri]; uc += [i, n + i]; ud += [1.0, -1.0]; bub.append(cur[varlist[i]]); ri += 1
            ur += [ri, ri]; uc += [i, n + i]; ud += [-1.0, -1.0]; bub.append(-cur[varlist[i]]); ri += 1
        for j, (row, rhs) in enumerate(crows):           # Σ coef·x (− slack_j) ≤ rhs
            for xi, co in row.items():
                ur.append(ri); uc.append(xi); ud.append(co)
            if with_slack:
                ur.append(ri); uc.append(2 * n + j); ud.append(-1.0)
            bub.append(rhs); ri += 1
        Aub = csr_matrix((ud, (ur, uc)), shape=(ri, W))
        obj = np.zeros(W); obj[n:2 * n] = 1.0
        if with_slack:
            obj[2 * n:] = 1e6                            # heavily penalise any rule violation
        try:
            return linprog(obj, A_ub=Aub, b_ub=np.array(bub), bounds=[(0, None)] * W,
                           method="highs", options={"time_limit": tl})
        except Exception:
            return None

    sol = build(False)
    if not (sol is not None and getattr(sol, "success", False)):
        sol = build(True)                                # soft-slack fallback
    if sol is None or not getattr(sol, "success", False) or sol.x is None:
        return {}
    out = {}
    for k, i in idx.items():
        v = sol.x[i]
        v = int(round(v)) if facts.is_int_like(k) else round(v, 4)
        out[k] = float(max(0.0, v))
    return out


# --------------------------------------------------------------------- driver
def run(args):
    import json
    model_path = os.path.join(BASE, "model.merged.json")
    if not os.path.exists(model_path):
        model_path = os.path.join(BASE, "model.json")
    model = json.load(open(model_path, encoding="utf-8")) if os.path.exists(model_path) else {}
    metrics = model.get("metrics", {})

    _DEFAULTS.clear()
    for dloc, mem in dim_drs.localize_defaults(model.get("dim_defaults", {})).items():
        _DEFAULTS[dloc] = dim_drs.local(mem)          # "IM:x0" -> "x0"

    facts = Facts(args.file, metrics)
    print(f"loaded {len(facts.val)} numeric facts from {os.path.basename(args.file)} "
          f"({facts.collisions} key-collision facts skipped for write-back)")

    tset_module = module_tables(args.module)
    if args.tables and args.tables != "all":
        want = {t.strip().upper() for t in args.tables.split(",")}
    else:
        want = set(tset_module)
    levels = set((args.level or "L1,L2,L3,L4").split(","))

    rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
    res = workbook_rules.CellResolver(EXT)
    present = set(facts.val)

    changes: dict = {}          # key -> new value (accumulated across passes)

    def curval(k):
        return changes.get(k, facts.val.get(k, 0.0))

    # ---------------- JOINT-LP CLUSTER solve (entangled cross-table clusters, e.g. OF08) ----------------
    # Solve ALL of a cluster's rules (single-table L1/L2 + cross-table L3/L4) TOGETHER in one continuous LP,
    # minimally perturbed from current values. This is the only thing that works for clusters whose cells
    # are shared across many cross-table rules (greedy per-rule derivation trades one fix for another).
    if args.joint:
        cluster = {t.strip().upper() for t in (args.cluster or DEFAULT_CLUSTER).split(",") if t.strip()}
        fidx = facts.index()

        def _numkeep(k):
            return k in present and facts.datatype_of(k) in _NUM

        j_eq = []; j_le = []

        sz = not args.all_z            # single z-layer by default (all-Z is intractable for the soft LP)

        def _collect(single_only):
            for code, tables, terms, _m, _p in additive_equations(rules, res, tset_module,
                                                                   single_only=single_only, single_z=sz):
                if not ({t.upper() for t in tables} <= cluster):
                    continue
                for coefs in expand_to_full(_agg(terms), fidx):
                    coefs = {k: c for k, c in coefs.items() if _numkeep(k)}
                    if coefs:
                        j_eq.append((coefs, 0.0))
            for code, kind, tables, cd, rhs in comparison_constraints(rules, res, tset_module, None,
                                                                      single_only=single_only, single_z=sz):
                if not ({t.upper() for t in tables} <= cluster):
                    continue
                for coefs in expand_to_full(cd, fidx):
                    coefs = {k: c for k, c in coefs.items() if _numkeep(k)}
                    if coefs:
                        (j_eq if kind == "eq" else j_le).append((coefs, rhs))
        _collect(True); _collect(False)
        cells = set()
        for coefs, _rhs in j_eq + j_le:
            cells |= set(coefs)
        cur = {k: facts.val[k] for k in cells}
        eqs = [(c, r, facts.tol_of(c)) for c, r in j_eq]
        les = [(c, r, facts.tol_of(c)) for c, r in j_le]
        print(f"\nJOINT-LP cluster {sorted(cluster)}:\n  {len(cells)} cells, {len(eqs)} equalities, "
              f"{len(les)} inequalities")
        sol = solve_joint(cells, cur, eqs, les, facts)
        if not sol:
            print("  LP infeasible / scipy missing — no changes")
        n_ch = 0
        for k, v in sol.items():
            if abs(v - facts.val.get(k, 0.0)) >= (0.5 if facts.is_int_like(k) else 1e-4):
                changes[k] = v; n_ch += 1
        print(f"  {n_ch} cell(s) changed")

    # ---------------- SINGLE-TABLE (L1 additive + L2 inequality), per component ----------------
    if not args.joint and ("L1" in levels or "L2" in levels):
        uf = UF()

        def keep(k):
            return k in present and facts.datatype_of(k) in _NUM

        # Build constraints over the WHOLE module (want=None), not just the requested tables: a cell
        # can be SHARED across tables (same concept+dims = same fact), so a rule in another table may
        # reference an OF07 cell. If we scoped constraints to OF07 only, moving a shared cell would
        # silently break that other table's rule. `want` is applied later — only to SELECT which dirty
        # components to solve — and each solved component carries every rule touching its cells.
        want_all = (not args.tables) or args.tables == "all"
        raw_eq = []   # (coefs, rhs, in_want)  — additive i= AND comparison '='
        raw_le = []   # (coefs, rhs, in_want)  — comparison ≤
        cell_tables: dict = defaultdict(set)      # cell key -> set of tables whose rules reference it

        def _add(kind, tables, coefs, rhs):
            coefs = {k: c for k, c in coefs.items() if keep(k)}
            if not coefs:
                return
            inw = want_all or bool({t.upper() for t in tables} & want)
            (raw_le if kind == "le" else raw_eq).append((coefs, rhs, inw))
            for k in coefs:
                cell_tables[k] |= {t.upper() for t in tables}

        if not args.open:
            # CLOSED path (proven): each cell → its single fact; closed key == full key.
            if "L1" in levels:
                for code, tables, terms, _m, _p in additive_equations(rules, res, tset_module, single_only=True):
                    _add("eq", tables, _agg(terms), 0.0)
            if "L2" in levels:
                for code, kind, tables, cd, rhs in comparison_constraints(rules, res, tset_module, present,
                                                                          single_only=True):
                    _add(kind, tables, cd, rhs)
        else:
            # OPEN path: expand each closed constraint to per-open-signature FULL-fact-key constraints
            # (hypercube tables) and restrict to a single z-layer (fan-out control).
            fidx = facts.index()
            if "L1" in levels:
                for code, tables, terms, _m, _p in additive_equations(rules, res, tset_module,
                                                                       single_only=True, single_z=True):
                    for coefs in expand_to_full(_agg(terms), fidx):
                        _add("eq", tables, coefs, 0.0)
            if "L2" in levels:
                for code, kind, tables, cd, rhs in comparison_constraints(rules, res, tset_module, None,
                                                                          single_only=True, single_z=True):
                    for coefs in expand_to_full(cd, fidx):
                        _add(kind, tables, coefs, rhs)

        comp_eq = defaultdict(list); comp_le = defaultdict(list); comp_cells = defaultdict(set)
        want_cells: set = set()
        for coefs, rhs, inw in raw_eq + raw_le:
            ks = list(coefs)
            for k in ks[1:]:
                uf.union(ks[0], k)
            if inw:
                want_cells |= set(coefs)
        for coefs, rhs, _inw in raw_eq:
            root = uf.find(next(iter(coefs)))
            comp_eq[root].append((coefs, rhs, facts.tol_of(coefs)))
            comp_cells[root] |= set(coefs)
        for coefs, rhs, _inw in raw_le:
            root = uf.find(next(iter(coefs)))
            comp_le[root].append((coefs, rhs, facts.tol_of(coefs)))
            comp_cells[root] |= set(coefs)

        # dirty = component with a constraint violated BEYOND its tolerance
        dirty = set()
        for root, eqs in comp_eq.items():
            for coefs, rhs, tol in eqs:
                if abs(sum(c * curval(k) for k, c in coefs.items()) - rhs) > tol:
                    dirty.add(root)
        for root, les in comp_le.items():
            for cd, rhs, tol in les:
                if sum(c * curval(k) for k, c in cd.items()) > rhs + tol:
                    dirty.add(root)

        # solve only DIRTY components that touch a wanted table's cells
        selected = {root for root in dirty if want_all or (comp_cells[root] & want_cells)}
        print(f"\nSINGLE-table: {len(comp_cells)} components, {len(dirty)} dirty, "
              f"{len(selected)} selected for wanted tables "
              f"(eqs={sum(len(v) for v in comp_eq.values())} les={sum(len(v) for v in comp_le.values())})")
        comp_report = []; deferred = []
        for root in selected:
            cells = {k for k in comp_cells[root] if keep(k)}
            tbls = sorted({t for k in cells for t in cell_tables.get(k, ())})
            # SIZE CAP: a huge fused/over-determined component (OF02/OF07 mega, OF18-20, OF21) can't be
            # solved reliably by MILP within the time limit — it returns non-minimal, non-deterministic,
            # sometimes-regressing incumbents. Defer those to genvalid's nonneg-LP; solve only the small
            # components surgically here (fast, exact, minimal, deterministic).
            if len(cells) > args.max_comp:
                deferred.append((len(cells), tbls))
                continue
            cur = {k: curval(k) for k in cells}
            sol = solve_component(cells, cur, comp_eq.get(root, []), comp_le.get(root, []), facts)
            nch = 0
            for k, v in sol.items():
                if abs(v - curval(k)) >= (0.5 if facts.is_int_like(k) else 1e-4):
                    changes[k] = v; nch += 1
            comp_report.append((len(cells), nch, tbls))
        print(f"  solved {len(comp_report)} components (cap {args.max_comp} cells), "
              f"deferred {len(deferred)} too-large → route to genvalid:")
        for ncell, nch, tbls in sorted(comp_report, key=lambda x: -x[0]):
            tl = ",".join(tbls[:4]) + (f" +{len(tbls) - 4}" if len(tbls) > 4 else "")
            print(f"    solved   cells={ncell:5d} changed={nch:5d}  {tl}")
        for ncell, tbls in sorted(deferred, key=lambda x: -x[0]):
            tl = ",".join(tbls[:4]) + (f" +{len(tbls) - 4}" if len(tbls) > 4 else "")
            print(f"    DEFERRED cells={ncell:5d}                {tl}")

    # ---------------- CROSS-TABLE additive (L3): aggregation post-pass ----------------
    # Derive the AGGREGATE/total cell of each failing cross-table equation from the others, editing ONLY
    # a present, lone-'total'-side cell that no SINGLE-table rule owns — i.e. a pure cross-table SINK
    # like OF34.07 r0180 (= Σ OF08.01). This never moves an OF08.01 source (preserving L1/L2) and skips
    # equations whose target is ABSENT (e.g. the OF09.02 CEG-total rows, which must be GENERATED, not
    # edited — deferred to a fact-generation pass).
    if not args.joint and "L3" in levels and args.cross:
        s1_cells: set = set()                            # cells any single-table additive rule references
        for code, tables, terms, _m, _p in additive_equations(rules, res, tset_module, single_only=True):
            for k, _c in terms:
                s1_cells.add(k)
        ctset = ({t.strip().upper() for t in args.cross_tables.split(",") if t.strip()}
                 if args.cross_tables else None)
        n_ct = 0; n_absent = 0
        for _ in range(6):
            moved = False
            for code, tables, terms, _m, pref in additive_equations(rules, res, tset_module, single_only=False):
                if ctset is not None and not ({t.upper() for t in tables} <= ctset):
                    continue                              # restrict to allowed cross-table rule sets
                agg = {k: c for k, c in _agg(terms).items() if abs(c) > 1e-9}
                if not agg or abs(sum(c * curval(k) for k, c in agg.items())) <= facts.tol_of(agg):
                    continue                              # empty / already satisfied within tolerance
                cand = [k for k in pref if k in agg and k in present
                        and facts.datatype_of(k) in _NUM and (args.cross_force or k not in s1_cells)]
                if not cand:
                    if not any(k in present for k in pref):
                        n_absent += 1                    # target row absent → needs generation, not edit
                    continue
                tgt = cand[0]
                s = sum(c * curval(k) for k, c in agg.items() if k != tgt)
                nv = -s / agg[tgt]
                if nv < 0:
                    continue
                nv = round(nv) if facts.is_int_like(tgt) else round(nv, 4)
                if abs(nv - curval(tgt)) >= (0.5 if facts.is_int_like(tgt) else 1e-4):
                    changes[tgt] = float(nv); moved = True; n_ct += 1
            if not moved:
                break
        print(f"CROSS-table additive: {n_ct} target-cell derivations "
              f"({n_absent} skipped: target row absent → needs generation)")

    # ---------------- report / write ----------------
    print(f"\n=== {len(changes)} cell(s) would change "
          f"({sum(1 for k in changes if abs(changes[k]-facts.val.get(k,0.0))>=0.5)} beyond ±0.5) ===")
    for k in list(changes)[:25]:
        print(f"  {k[0]:10s} {sorted(dict(k[1]).items())[:2]} : {facts.val.get(k)} -> {changes[k]}")

    if args.apply:
        for k, v in changes.items():
            el = facts.el.get(k)
            if el is not None:
                el.text = facts.fmt(k, v)
        outp = args.out or (os.path.splitext(args.file)[0] + "_fixed.xbrl")
        facts.write(outp)
        print(f"\nAPPLIED → wrote {outp}")
    else:
        print("\n(dry-run — no file written; pass --apply to write)")


def _agg(terms):
    d = {}
    for k, c in terms:
        d[k] = d.get(k, 0.0) + c
    return d


def _absent_rhs(terms, keep):
    """Additive eq Σcoef·x = 0; absent cells are constant 0 so rhs stays 0. (Kept for clarity/future
    non-zero-const handling.)"""
    return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT_FILE)
    ap.add_argument("--module", default="pra001")
    ap.add_argument("--tables", default="all", help="'all' or comma-separated table codes")
    ap.add_argument("--level", default="L1,L2", help="comma list of L1,L2,L3,L4")
    ap.add_argument("--cross", action="store_true", help="enable cross-table (L3) aggregation pass")
    ap.add_argument("--open", action="store_true", dest="open",
                    help="open-table mode: signature-expand cells to full facts, single z-layer")
    ap.add_argument("--joint", action="store_true",
                    help="joint-LP solve of a cross-table CLUSTER (all its rules together, continuous LP)")
    ap.add_argument("--cluster", default=None,
                    help="comma-separated cluster tables for --joint (default: the OF08 cluster)")
    ap.add_argument("--all-z", action="store_true", dest="all_z",
                    help="--joint: solve every z-layer (default: first z only — all-Z is intractable)")
    ap.add_argument("--cross-tables", default=None, dest="cross_tables",
                    help="--cross: only process cross-table rules whose tables ⊆ this comma set (leaf-safe)")
    ap.add_argument("--cross-force", action="store_true", dest="cross_force",
                    help="--cross: allow editing single-table-owned target cells (may break single-table)")
    ap.add_argument("--max-comp", type=int, default=400, dest="max_comp",
                    help="skip (defer) components larger than this many cells (route to genvalid)")
    ap.add_argument("--apply", action="store_true", help="write the fixed file (default: dry-run)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    run(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
