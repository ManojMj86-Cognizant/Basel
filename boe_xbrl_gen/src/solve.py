"""
Constraint solver (Layer 3 core).

Given an Instance, a set of parsed Rules, and dimension defaults, mutate fact values so
that the rules are satisfied:

  * EQUALITY (v0 = sum/add/multiply/.. of other vars): the single-variable side is the
    DERIVED total; its value is computed from the other side. Facts form a dependency
    graph (a derived fact in one rule may be an input in another, e.g. b0014 feeds b0013);
    we topologically order and compute bottom-up so every equality holds simultaneously.
  * FORMAT (matches(v0, regex)): set v0 to a freshly generated string matching the regex.

Inequality/existence handling is stubbed for a later pass; the generate->Arelle loop in
solve_loop.py reports residuals. Leaf facts keep their type-correct random values.
"""
from __future__ import annotations

import re
from collections import defaultdict

import expr as E
from resolver import bind


# ---------- regex-conforming string generation (closed pattern set) ----------
def gen_matching(pattern, rng):
    """Generate a string matching simple ^...$ patterns of char-class + quantifier."""
    p = pattern
    if p.startswith("^"):
        p = p[1:]
    if p.endswith("$"):
        p = p[:-1]
    out = []
    i = 0
    while i < len(p):
        c = p[i]
        if c == "[":
            j = p.index("]", i)
            cls = p[i + 1:j]
            i = j + 1
        else:
            cls = c
            i += 1
        # quantifier
        n = 1
        if i < len(p) and p[i] == "{":
            k = p.index("}", i)
            q = p[i + 1:k]
            i = k + 1
            if "," in q:
                lo, hi = q.split(",")
                n = rng.randint(int(lo), int(hi or lo))
            else:
                n = int(q)
        out.append(_emit_class(cls, n, rng))
    return "".join(out)


def _emit_class(cls, n, rng):
    chars = []
    if "0-9" in cls:
        chars += list("0123456789")
    if "A-Z" in cls:
        chars += list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    if "a-z" in cls:
        chars += list("abcdefghijklmnopqrstuvwxyz")
    if not chars:                       # literal text
        return cls * n
    return "".join(rng.choice(chars) for _ in range(n))


# ---------- equality classification ----------
def _is_single_var(node):
    return node[0] == "var"


def _equality_sides(test_ast):
    """Return (lhs, rhs) AST nodes if the test is a top-level equality, else None."""
    t = test_ast
    if t[0] == "call" and t[1].split(":")[-1] == "numeric-equal":
        return t[2][0], t[2][1]
    if t[0] == "cmp" and t[1] == "=":
        return t[2], t[3]
    return None


def _vars_in(node, acc):
    if node[0] == "var":
        acc.add(node[1])
    elif node[0] == "seq":
        for k in node[1]:
            _vars_in(k, acc)
    elif node[0] in ("bin", "and", "or"):
        for k in node[2:]:
            _vars_in(k, acc)
    elif node[0] == "cmp":
        _vars_in(node[2], acc); _vars_in(node[3], acc)
    elif node[0] == "if":
        _vars_in(node[1], acc); _vars_in(node[2], acc); _vars_in(node[3], acc)
    elif node[0] == "call":
        for a in node[2]:
            _vars_in(a, acc)
    return acc


def _numeric_fact(f):
    """A fact is safe to overwrite with a numeric value only if it is numeric-typed.
    Monetary/decimal/percentage/integer facts carry @decimals and/or @unitRef; date,
    string, enumeration and boolean facts carry neither — never write numbers into those
    (writing -1000.0 into a date metric is a schema valueError)."""
    return f.decimals is not None or f.unit is not None


def _round_to_decimals(val, decimals):
    if decimals in (None, "INF", "inf"):
        return round(val, 2)
    d = int(decimals)
    if d <= 0:
        step = 10 ** (-d)
        return int(round(val / step) * step)
    return round(val, d)


_CMP_FNS = {
    "numeric-greater-equal-than": ">=", "numeric-less-equal-than": "<=",
    "numeric-greater-than": ">", "numeric-less-than": "<",
}


def _unwrap(ast):
    """If ast is `if cond then core else true()`, return (cond, core); else (None, ast)."""
    if ast and ast[0] == "if":
        return ast[1], ast[2]
    return None, ast


def _enum_val(f):
    """Resolve an enumeration fact's prefixed-QName value (e.g. 'boe_eba_CT:x6004') to
    Clark notation '{ns}local' so a guard like `$v = QName(ns,local)` compares equal.
    Non-QName values (numbers, plain strings) pass through unchanged."""
    v = f.value
    if v and ":" in v and f.el is not None:
        prefix, local = v.split(":", 1)
        ns = f.el.nsmap.get(prefix)
        if ns:
            return f"{{{ns}}}{local}"
    return v


def _cond_holds(cond, var_facts):
    """Evaluate a conditional precondition for a binding group; True if it currently holds
    (or if there is no condition)."""
    if cond is None:
        return True
    vs = _vars_in(cond, set())
    env = {}
    for vn in vs:
        fs = var_facts.get(vn, [])
        vals = [_enum_val(f) for f in fs]
        env[vn] = vals if len(fs) != 1 else (vals[0] if vals else None)
    try:
        return bool(E.evaluate(cond, env))
    except Exception:
        return True            # if we can't evaluate the guard, assume active (safe)


def _empty_var(ast):
    """If the test is empty($v0), return the var name; else None."""
    if ast and ast[0] == "call" and ast[1].split(":")[-1] == "empty" \
            and len(ast[2]) == 1 and ast[2][0][0] == "var":
        return ast[2][0][1]
    return None


def _comparison(ast):
    """Return (a_node, op, b_node) if the test is a single pairwise numeric comparison."""
    if ast[0] == "cmp" and ast[1] in (">=", "<=", ">", "<"):
        return ast[2], ast[1], ast[3]
    if ast[0] == "call":
        fn = ast[1].split(":")[-1]
        if fn in _CMP_FNS and len(ast[2]) == 2:
            return ast[2][0], _CMP_FNS[fn], ast[2][1]
    return None


def _const_bound(core):
    """Detect a variable-vs-constant bound: `$v op N` or `N op $v`.
    Returns (varname, op, N) normalized so the op applies as `var op N`."""
    cmp = _comparison(core)
    if not cmp:
        return None
    a, op, b = cmp
    if _is_single_var(a) and b[0] == "num":
        return (a[1], op, b[1])
    if _is_single_var(b) and a[0] == "num":
        flip = {">=": "<=", "<=": ">=", ">": "<", "<": ">"}[op]
        return (b[1], flip, a[1])
    return None


def _sat_const(op, n, decimals, rng):
    """Return a random value satisfying `value op n`, honoring the fact's @decimals."""
    d = None if decimals in (None, "INF", "inf") else int(decimals)
    if d is not None and d <= 0:
        step = 10 ** (-d)
        mag = rng.randint(0, 9999) * step
        eps = step
    else:
        mag = rng.uniform(0, 1)
        eps = 10 ** (-(d if d is not None else 2))
    if op == "<=":
        return _round_to_decimals(n - mag, decimals)
    if op == "<":
        return _round_to_decimals(n - mag - eps, decimals)
    if op == ">=":
        return _round_to_decimals(n + mag, decimals)
    if op == ">":
        return _round_to_decimals(n + mag + eps, decimals)
    return _round_to_decimals(n, decimals)


def solve(instance, rules, defaults, rng, rounds=8):
    """Mutate instance facts to satisfy FORMAT, EQUALITY and pairwise INEQUALITY rules.

    Equalities define derived facts (computed from leaves, topologically). Inequalities are
    enforced by nudging a *leaf* operand, after which equalities are re-propagated; this
    repeats to a fixpoint so derived totals stay consistent with adjusted leaves.
    """
    # ---- 1. format rules ----
    n_format = 0
    for rule in rules:
        ast = _safe_parse(rule.test)
        if ast is None:
            continue
        if ast[0] == "call" and ast[1].split(":")[-1] == "matches":
            var_node, pat_node = ast[2][0], ast[2][1]
            if var_node[0] == "var" and pat_node[0] == "str":
                for b in bind(rule, instance, defaults):
                    for f in b["vars"].get(var_node[1], []):
                        f.value = gen_matching(pat_node[1], rng)
                        n_format += 1

    # ---- 1b. existence rules: empty($v0) -> remove the matching fact(s) ----
    # Run before equality/inequality so derived totals are computed from remaining facts.
    n_removed = 0
    for rule in rules:
        ast = _safe_parse(rule.test)
        if ast is None:
            continue
        cond, core = _unwrap(ast)
        ev = _empty_var(core)
        if ev is None or ev not in rule.variables:
            continue
        cond_vars = _vars_in(cond, set()) if cond is not None else set()
        for b in bind(rule, instance, defaults):
            cond_facts = {vn: b["vars"].get(vn, []) for vn in cond_vars}
            if not _cond_holds(cond, cond_facts):
                continue
            for f in list(b["vars"].get(ev, [])):
                instance.remove_fact(f)
                n_removed += 1

    # ---- 2. collect equality (derived) relations (conditionals unwrapped + guarded) ----
    derived = {}               # tid -> (target_fact, defexpr, var_facts, cond, cond_facts)
    deps = defaultdict(set)
    for rule in rules:
        ast = _safe_parse(rule.test)
        if ast is None:
            continue
        cond, core = _unwrap(ast)
        sides = _equality_sides(core)
        if not sides:
            continue
        lhs, rhs = sides
        if _is_single_var(lhs):
            tvar, defexpr = lhs[1], rhs
        elif _is_single_var(rhs):
            tvar, defexpr = rhs[1], lhs
        else:
            continue
        if tvar not in rule.variables or rule.variables[tvar].sequence:
            continue
        rhs_vars = _vars_in(defexpr, set())
        cond_vars = _vars_in(cond, set()) if cond is not None else set()
        for b in bind(rule, instance, defaults):
            tfacts = b["vars"].get(tvar, [])
            if len(tfacts) != 1:
                continue
            tf = tfacts[0]
            var_facts = {vn: b["vars"].get(vn, []) for vn in rhs_vars}
            cond_facts = {vn: b["vars"].get(vn, []) for vn in cond_vars}
            derived[id(tf)] = (tf, defexpr, var_facts, cond, cond_facts)
            for fs in var_facts.values():
                for f in fs:
                    deps[id(tf)].add(id(f))

    order = _toposort(derived.keys(), deps)
    derived_ids = set(derived)

    def propagate():
        n = 0
        for tid in order:
            tf, defexpr, var_facts, cond, cond_facts = derived[tid]
            if not _numeric_fact(tf):          # never write a number into a date/string/etc.
                continue
            if not _cond_holds(cond, cond_facts):
                continue
            env = {}
            for vn, fs in var_facts.items():
                vals = [_to_num(f.value) for f in fs]
                env[vn] = vals if len(fs) != 1 else (vals[0] if vals else 0.0)
            try:
                val = E.evaluate(defexpr, env)
                if val is None or isinstance(val, bool):
                    continue
                tf.value = _round_to_decimals(E._num(val), tf.decimals)  # _num sums lists
                n += 1
            except Exception:
                continue
        return n

    # ---- 3. collect pairwise inequality constraints (a op b) over single facts ----
    ineqs = []                 # (a_fact, op, b_fact, cond, cond_facts)
    for rule in rules:
        ast = _safe_parse(rule.test)
        if ast is None:
            continue
        cond, core = _unwrap(ast)
        cmp = _comparison(core)
        if not cmp:
            continue
        a_node, op, b_node = cmp
        if not (_is_single_var(a_node) and _is_single_var(b_node)):
            continue
        av, bv = a_node[1], b_node[1]
        cond_vars = _vars_in(cond, set()) if cond is not None else set()
        for b in bind(rule, instance, defaults):
            af, bf = b["vars"].get(av, []), b["vars"].get(bv, [])
            if len(af) == 1 and len(bf) == 1:
                cond_facts = {vn: b["vars"].get(vn, []) for vn in cond_vars}
                ineqs.append((af[0], op, bf[0], cond, cond_facts))

    # ---- 3b. collect variable-vs-constant bounds: $v op N  (e.g. sign rules $v <= 0) ----
    const_bounds = []          # (fact, op, N, cond, cond_facts)
    for rule in rules:
        ast = _safe_parse(rule.test)
        if ast is None:
            continue
        cond, core = _unwrap(ast)
        cb = _const_bound(core)
        if not cb:
            continue
        var, op, nval = cb
        if var not in rule.variables:
            continue
        cond_vars = _vars_in(cond, set()) if cond is not None else set()
        for b in bind(rule, instance, defaults):
            cond_facts = {vn: b["vars"].get(vn, []) for vn in cond_vars}
            for f in b["vars"].get(var, []):
                const_bounds.append((f, op, nval, cond, cond_facts))

    # ---- 4. iterate: propagate equalities, then fix inequalities by nudging a leaf ----
    n_eq = propagate()
    n_ineq_fixed = 0
    n_const_fixed = 0
    for _ in range(rounds):
        changed = False
        # variable-vs-constant bounds (clamp a leaf to satisfy the bound)
        for f, op, nval, cond, cond_facts in const_bounds:
            if id(f) in derived_ids or not _numeric_fact(f):
                continue
            if not _cond_holds(cond, cond_facts):
                continue
            v = _to_num(f.value)
            ok = (v >= nval) if op == ">=" else (v <= nval) if op == "<=" else \
                 (v > nval) if op == ">" else (v < nval)
            if ok:
                continue
            f.value = _sat_const(op, nval, f.decimals, rng)
            changed = True
            n_const_fixed += 1
        for af, op, bf, cond, cond_facts in ineqs:
            if not _cond_holds(cond, cond_facts):
                continue
            a, b = _to_num(af.value), _to_num(bf.value)
            ok = (a >= b) if op == ">=" else (a <= b) if op == "<=" else \
                 (a > b) if op == ">" else (a < b)
            if ok:
                continue
            # only nudge a leaf that is numeric-typed (don't corrupt date/string facts)
            a_leaf = id(af) not in derived_ids and _numeric_fact(af)
            b_leaf = id(bf) not in derived_ids and _numeric_fact(bf)
            step = 10 ** 3
            if op in (">=", ">"):
                target = b + (step if op == ">" else 0)
                if a_leaf:
                    af.value = _round_to_decimals(target, af.decimals); changed = True
                elif b_leaf:
                    bf.value = _round_to_decimals(a - (step if op == ">" else 0), bf.decimals); changed = True
            else:  # <= or <
                target = b - (step if op == "<" else 0)
                if a_leaf:
                    af.value = _round_to_decimals(target, af.decimals); changed = True
                elif b_leaf:
                    bf.value = _round_to_decimals(a + (step if op == "<" else 0), bf.decimals); changed = True
            if changed:
                n_ineq_fixed += 1
        propagate()
        if not changed:
            break

    propagate()                # final reconciliation (e.g. imax targets after leaf nudges)
    return {"format_set": n_format, "equality_solved": n_eq,
            "derived_facts": len(derived), "inequalities": len(ineqs),
            "ineq_adjustments": n_ineq_fixed, "const_bounds": len(const_bounds),
            "const_adjustments": n_const_fixed, "facts_removed": n_removed}


def _toposort(nodes, deps):
    """Return nodes in dependency order (inputs before the facts that derive from them).
    Breaks cycles arbitrarily (best-effort; the Arelle loop mops up residuals)."""
    nodes = set(nodes)
    visited, order, instack = set(), [], set()

    def visit(n):
        if n in visited:
            return
        instack.add(n)
        for m in deps.get(n, ()):
            if m in nodes and m not in instack:
                visit(m)
        instack.discard(n)
        visited.add(n)
        order.append(n)

    for n in list(nodes):
        visit(n)
    return order


def _to_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _safe_parse(test):
    if not test:
        return None
    try:
        return E.parse(test)
    except Exception:
        return None
