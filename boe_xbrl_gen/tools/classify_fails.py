"""Offline per-level fail classifier for an EXISTING instance (no Arelle) — HARDENED.

Loads a built .xbrl and evaluates every in-scope workbook rule against its current fact values,
using TDG semantics (an ABSENT cell counts as 0) and honouring `if <precondition> then …` gates.
Each rule is bucketed into a LEVEL:
  L1 single-table additive (i=)          L2 single-table comparison (<=,>=,<,>,=,!=)
  L3 cross-table  additive (i=)          L4 cross-table  comparison
  NONLINEAR = imax/imin/exp/cell×cell  -> handled by the non-linear pass, NOT this solver
  OTHER     = in-scope rules that parse into none of the above (isNull/existence/format/string)

Emits counts + the list of FAILING rule codes per level and writes a JSON report.
Run from boe_xbrl_gen/ with PYTHONIOENCODING=utf-8.
"""
import sys, json, os, re
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules, formula_eval
from src import dim_drs
from src import instance_build

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
OUT = os.environ.get("CLASSIFY_FILE",
                     r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID.xbrl")
MODULE = os.environ.get("CLASSIFY_MODULE", "pra001")
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
X = "http://www.xbrl.org/2003/instance"
TOL = 0.5


# dim-local -> default member-local; dropped from keys because XBRL omits default members from contexts
# (so the rc-code bridge's default-member cells match the real, default-free instance facts).
import json as _json
_mp = os.path.join(BASE, "model.merged.json")
if not os.path.exists(_mp):
    _mp = os.path.join(BASE, "model.json")
_DEFAULTS = {}
if os.path.exists(_mp):
    for _d, _m in dim_drs.localize_defaults(_json.load(open(_mp, encoding="utf-8")).get("dim_defaults", {})).items():
        _DEFAULTS[_d] = dim_drs.local(_m)


def _dimset(items):
    return frozenset((k, v) for k, v in items if _DEFAULTS.get(k) != v)


def fkey(c, d):
    return (dim_drs.local(c), _dimset((dim_drs.local(k), dim_drs.local(v)) for k, v in d.items()))


# ---- table set for the module (scope filter) ----
idx = instance_build.module_index(EXT)
tset = {t.upper() for t, infos in idx.items() for i in infos if i["module"] == MODULE}
print(f"module {MODULE}: {len(tset)} tables in scope")


def in_scope(r):
    return bool(r["tables"]) and not r.get("deactivated") and {t.upper() for t in r["tables"]} <= tset


# ---- load facts (absent => not in map => treated as 0 by cellval) ----
data = open(OUT, "rb").read(); data = data[3:] if data[:3] == b"\xef\xbb\xbf" else data
root = etree.fromstring(data); cd = {}
for ctx in root.findall(f"{{{X}}}context"):
    dd = {}; sc = ctx.find(f"{{{X}}}scenario")
    if sc is not None:
        for em in sc:
            if em.get("dimension") and etree.QName(em).localname == "explicitMember":
                dd[dim_drs.local(em.get("dimension"))] = dim_drs.local((em.text or "").strip())
    cd[ctx.get("id")] = dd
facts = {}
decs = {}
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    k = (dim_drs.local(etree.QName(el).localname), _dimset(cd.get(cr, {}).items()))
    try:
        facts[k] = float((el.text or "").strip())
    except (ValueError, TypeError):
        continue
    try:
        decs[k] = int(el.get("decimals"))
    except (TypeError, ValueError):
        decs[k] = None
print(f"loaded {len(facts)} numeric facts from {os.path.basename(OUT)}")


def halfulp(k):
    """Half-ULP tolerance from @decimals (decimals=-3 → ±500). TDG rounds to reported precision
    before comparing, so a ±1 residual on thousands-reported facts is NOT a real failure."""
    d = decs.get(k)
    return 0.5 * (10.0 ** (-d)) if d is not None else 0.5

rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
res = workbook_rules.CellResolver(EXT)


def val(dp):
    return facts.get(fkey(dp["concept"], dp["dims"]))


# ---- non-linear detector: route these OUT of the comparison buckets ----
def is_nonlinear(expr: str) -> bool:
    el = expr.lower()
    if any(t in el for t in ("exp(", "imax", "imin")):
        return True
    # cell/group  ×or÷  cell/group  ->  a '*'/'/' with '{' or '(' on BOTH sides (coef 'i* 12.5' is
    # a number, so it has a digit — not '{'/'(' — on the right, and won't match).
    if re.search(r"[\}\)]\s*i?[*/]\s*[\{\(]", expr):
        return True
    return False


# ---- value / boolean evaluator with absent=0 (TDG) ----
def make_cellval(tab, sr, sc, sz, touched):
    def cellval(cref):
        rvals = workbook_rules._semi(cref.get("r")) or [cref.get("r") or sr]
        cvals = workbook_rules._semi(cref.get("c")) or [cref.get("c") or sc]
        zz = cref.get("z") or ([sz] if sz else [])
        tot = 0.0; present = False
        for rv in rvals:
            for cv in cvals:
                for dp in res.resolve({"table": cref.get("table") or tab, "r": rv, "c": cv, "z": zz}):
                    k = fkey(dp["concept"], dp["dims"])
                    v = facts.get(k)
                    if v is not None:
                        tot += v; present = True; touched.add(k)
        return tot, present
    return cellval


def ev_num(node, cv):
    """AST -> (value float [absent=0], any_present bool)."""
    t = node[0]
    if t == "num":
        return float(node[1]), True
    if t == "cell":
        return cv(node[1])
    if t == "neg":
        v, p = ev_num(node[1], cv); return -v, p
    if t == "bin":
        a, ap = ev_num(node[2], cv); b, bp = ev_num(node[3], cv)
        r = {"+": a + b, "-": a - b, "*": a * b, "/": (a / b if b else 0.0)}[node[1]]
        return r, ap or bp
    if t == "call":
        nm, args = node[1], node[2]
        vs = [ev_num(a, cv) for a in args]; vals = [v for v, _ in vs]; p = any(pp for _, pp in vs)
        if nm in ("iabs", "abs"):
            return (abs(vals[0]) if vals else 0.0), p
        if nm == "isum":
            return sum(vals), p
        if nm in ("imax", "max"):
            return (max(vals) if vals else 0.0), p
        if nm in ("imin", "min"):
            return (min(vals) if vals else 0.0), p
        return 0.0, p
    return 0.0, False


def ev_bool(node, cv):
    """Evaluate a precondition to bool. Defaults to True (evaluate the rule) when unrecognised —
    conservative: better to over-report a fail than silently hide one."""
    if not isinstance(node, tuple):
        return True
    t = node[0]
    if t == "if":                                  # nested if: gate on its own precond
        return ev_bool(node[1], cv) and ev_bool(node[2], cv)
    if t == "cmp":
        a, _ = ev_num(node[2], cv); b, _ = ev_num(node[3], cv); op = node[1]
        return {"<=": a <= b + TOL, "<": a < b + TOL, ">=": a >= b - TOL, ">": a > b - TOL,
                "=": abs(a - b) < TOL, "!=": abs(a - b) >= TOL}.get(op, True)
    if t in ("and",):
        return all(ev_bool(x, cv) for x in node[1:])
    if t in ("or",):
        return any(ev_bool(x, cv) for x in node[1:])
    if t in ("not",):
        return not ev_bool(node[1], cv)
    if t in ("bool",):
        return bool(node[1])
    if t == "call" and node[1] in ("true", "false"):
        return node[1] == "true"
    return True


# ---- classify ----
buckets = {"L1_single_additive": [], "L2_single_cmp": [], "L3_cross_additive": [],
           "L4_cross_cmp": [], "NONLINEAR": [], "OTHER_in_scope": []}
counts = {k: {"rules": 0, "failing": 0, "instances": 0, "fail_instances": 0,
              "fail_with_absent": 0} for k in buckets}

for r in rules:
    if not in_scope(r):
        continue
    code = r["code"]; expr = r.get("expression", "")
    multi = len({t.upper() for t in r["tables"]}) > 1

    # NON-LINEAR first — never let these reach the additive/comparison buckets.
    if is_nonlinear(expr):
        counts["NONLINEAR"]["rules"] += 1
        buckets["NONLINEAR"].append({"code": code, "tables": r["tables"], "expr": expr[:90]})
        continue

    # ADDITIVE equality (i=)
    pe = workbook_rules.parse_expression(expr)
    if pe and pe.get("op") == "i=":
        lvl = "L3_cross_additive" if multi else "L1_single_additive"
        c = counts[lvl]; c["rules"] += 1
        fail_inst = 0; fail_absent = 0; examples = []
        for a in workbook_rules.expand_scoped_asts(r):
            if a["op"] != "i=":
                continue
            c["instances"] += 1
            lhs = rhs = 0.0; had_absent = False; tol = 0.0
            for side in ("lhs", "rhs"):
                for tterm in a[side]:
                    for dp in res.resolve(tterm["cell"]):
                        k = fkey(dp["concept"], dp["dims"])
                        v = facts.get(k)
                        if v is None:
                            had_absent = True; v = 0.0        # TDG: absent = 0
                        else:
                            tol += abs(tterm["coef"]) * halfulp(k)
                        if side == "lhs":
                            lhs += v * tterm["coef"]
                        else:
                            rhs += v * tterm["coef"]
            if abs(lhs - rhs) > max(tol, TOL):
                fail_inst += 1
                if had_absent:
                    fail_absent += 1
                if len(examples) < 3:
                    examples.append(f"{lhs:.0f} != {rhs:.0f}")
        c["fail_instances"] += fail_inst; c["fail_with_absent"] += fail_absent
        if fail_inst:
            c["failing"] += 1
            buckets[lvl].append({"code": code, "tables": r["tables"],
                                 "fail_instances": fail_inst, "fail_with_absent": fail_absent,
                                 "examples": examples})
        continue

    # COMPARISON (<=,>=,<,>,=,!=), possibly gated by an if-precondition
    cmp_node = None; precond = None
    if "{" in expr:
        try:
            ast = formula_eval._Parser(formula_eval._tokenize(expr)).parse()
            if ast[0] == "if":
                precond = ast[1]; node = ast[2]
            else:
                node = ast
            if isinstance(node, tuple) and node[0] == "cmp":
                cmp_node = node
        except Exception:
            pass
    if cmp_node is not None:
        lvl = "L4_cross_cmp" if multi else "L2_single_cmp"
        c = counts[lvl]; c["rules"] += 1
        op = cmp_node[1]
        sc = workbook_rules.parse_scope(r.get("scope", "")) or {"table": "", "rows": [], "cols": [], "z": []}
        tab = sc.get("table") or (r["tables"][0] if r["tables"] else "")
        fail_inst = 0; examples = []
        for sr in (sc["rows"] or [None]):
            for scl in (sc["cols"] or [None]):
                for sz in (sc["z"] or [None]):
                    touched = set()
                    cv = make_cellval(tab, sr, scl, sz, touched)
                    if precond is not None and not ev_bool(precond, cv):
                        continue                              # precondition false -> rule not asserted
                    c["instances"] += 1
                    a, _ = ev_num(cmp_node[2], cv); b, _ = ev_num(cmp_node[3], cv)
                    tol = sum(halfulp(k) for k in touched) or TOL
                    good = {"<=": a <= b + tol, "<": a < b + tol, ">=": a >= b - tol, ">": a > b - tol,
                            "=": abs(a - b) <= tol, "!=": abs(a - b) > tol}.get(op, True)
                    if not good:
                        fail_inst += 1
                        if len(examples) < 3:
                            examples.append(f"{a:.0f} {op} {b:.0f}")
        c["fail_instances"] += fail_inst
        if fail_inst:
            c["failing"] += 1
            buckets[lvl].append({"code": code, "op": op, "tables": r["tables"],
                                 "fail_instances": fail_inst, "examples": examples})
        continue

    counts["OTHER_in_scope"]["rules"] += 1
    buckets["OTHER_in_scope"].append({"code": code, "tables": r["tables"], "expr": expr[:80]})

# ---- print summary ----
print("\n==== per-level classification (TDG absent=0, precond-gated, non-linear split out) ====")
for lvl in ("L1_single_additive", "L2_single_cmp", "L3_cross_additive", "L4_cross_cmp",
            "NONLINEAR", "OTHER_in_scope"):
    c = counts[lvl]
    print(f"\n{lvl}:  rules={c['rules']}  FAILING_rules={c['failing']}  "
          f"instances={c['instances']} fail_instances={c['fail_instances']} "
          f"(of which involve an absent cell: {c['fail_with_absent']})")
    fails = buckets[lvl]
    if lvl in ("OTHER_in_scope", "NONLINEAR"):
        print(f"  ({len(fails)} rules — {'deferred to non-linear pass' if lvl=='NONLINEAR' else 'solver blind spot'})")
        for f in fails[:15]:
            print(f"    {f['code']:14s} {','.join(f['tables'])[:34]:34s} {f.get('expr','')[:60]}")
        continue
    for f in sorted(fails, key=lambda x: -x["fail_instances"])[:50]:
        print(f"    {f['code']:14s} tables={','.join(f['tables'])[:38]:38s} "
              f"fails={f['fail_instances']:5d}  e.g. {f.get('examples')}")

report = {"file": OUT, "module": MODULE, "counts": counts, "failing": buckets}
outp = "tools/classify_fails_report.json"
json.dump(report, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\nwrote {outp}")
