"""Diagnostics: (1) dump v4814-v4816 (+ siblings) expression/precondition/scope + per-cell resolution
and current values, to explain the huge-negative 'fails'; (2) re-evaluate ADDITIVE 'incomplete'
instances treating an absent cell as 0 (TDG semantics) to see how many become genuine fails."""
import sys, os
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules, formula_eval
from src import dim_drs
from src import instance_build

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
OUT = os.environ.get("CLASSIFY_FILE",
                     r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID.xbrl")
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
X = "http://www.xbrl.org/2003/instance"
TOL = 0.5
MODULE = "pra001"


def fkey(c, d):
    return (dim_drs.local(c), frozenset((dim_drs.local(k), dim_drs.local(v)) for k, v in d.items()))


idx = instance_build.module_index(EXT)
tset = {t.upper() for t, infos in idx.items() for i in infos if i["module"] == MODULE}

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
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    try:
        facts[(dim_drs.local(etree.QName(el).localname), frozenset(cd.get(cr, {}).items()))] = float((el.text or "").strip())
    except (ValueError, TypeError):
        pass

rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
res = workbook_rules.CellResolver(EXT)


def val(dp):
    return facts.get(fkey(dp["concept"], dp["dims"]))


# ============ (1) v4814-v4816 forensics ============
print("=" * 70)
print("(1) v4814_m / v4815_m / v4816_m forensics")
print("=" * 70)
for code in ("v4814_m", "v4815_m", "v4816_m"):
    r = next((x for x in rules if x["code"] == code), None)
    if not r:
        print(f"{code}: NOT FOUND"); continue
    print(f"\n----- {code}  tables={r['tables']} include={r['include']} deact={r['deactivated']}")
    print(f"  Expression : {r['expression']}")
    print(f"  Precondit. : {r.get('precondition')!r}")
    print(f"  Scope      : {r.get('scope')!r}")
    try:
        ast = formula_eval._Parser(formula_eval._tokenize(r["expression"])).parse()
    except Exception as e:
        print(f"  parse error: {e}"); continue
    print(f"  AST top    : {ast[0]}  (if→has precondition the classifier IGNORED)")
    node = ast[2] if ast[0] == "if" else ast
    # resolve every cell ref in the expression and print value
    for m in workbook_rules._CELL_RE.finditer(r["expression"]):
        c = workbook_rules._parse_cell(m.group(1))
        dps = res.resolve({"table": c.get("table"), "r": c.get("r"), "c": c.get("c"), "z": c.get("z")})
        vs = [(dp["concept"].split(":")[-1], val(dp)) for dp in dps]
        print(f"    cell t={c.get('table')} r={c.get('r')} c={c.get('c')} z={c.get('z')} "
              f"-> {len(dps)} dp {vs[:4]}")


# ============ (2) incomplete additive re-eval with absent=0 ============
print("\n" + "=" * 70)
print("(2) ADDITIVE 'incomplete' instances re-evaluated with absent=0 (TDG semantics)")
print("=" * 70)


def rule_multi(r):
    return len({t.upper() for t in r["tables"]}) > 1


for label, want_multi in (("SINGLE-table", False), ("CROSS-table", True)):
    n_incomplete = n_would_fail = n_would_pass = 0
    fail_codes = {}
    for r in rules:
        if not r["tables"] or r.get("deactivated") or not ({t.upper() for t in r["tables"]} <= tset):
            continue
        if rule_multi(r) != want_multi:
            continue
        pe = workbook_rules.parse_expression(r.get("expression", ""))
        if not (pe and pe.get("op") == "i="):
            continue
        for a in workbook_rules.expand_scoped_asts(r):
            if a["op"] != "i=":
                continue
            any_missing = False
            lhs = rhs = 0.0
            for side in ("lhs", "rhs"):
                for tterm in a[side]:
                    for dp in res.resolve(tterm["cell"]):
                        v = val(dp)
                        if v is None:
                            any_missing = True
                            v = 0.0
                        if side == "lhs":
                            lhs += v * tterm["coef"]
                        else:
                            rhs += v * tterm["coef"]
            if not any_missing:
                continue                      # already counted in the main classifier
            n_incomplete += 1
            if abs(lhs - rhs) >= TOL:
                n_would_fail += 1
                fail_codes[r["code"]] = fail_codes.get(r["code"], 0) + 1
            else:
                n_would_pass += 1
    print(f"\n{label}: incomplete additive instances = {n_incomplete}")
    print(f"   would PASS with absent=0 : {n_would_pass}")
    print(f"   would FAIL with absent=0 : {n_would_fail}   (hidden TDG risk)")
    top = sorted(fail_codes.items(), key=lambda kv: -kv[1])[:25]
    for code, n in top:
        print(f"       {code:14s} {n}")
