"""Evaluate single-table INEQUALITY / comparison rules (plain <=, >=, abs, isum) against the output."""
import sys, json
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules, formula_eval
from src import dim_drs

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"; OUT = f"{BASE}/solved/_genvalid_pra001.xbrl"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
X = "http://www.xbrl.org/2003/instance"
CODES = sys.argv[1:] or ["boe_b1037", "boe_b1038", "boe_b1036", "boe_b0683", "boe_b0684",
                          "boe_b0380", "boe_b0379", "boe_b0378", "boe_b0306"]


def fkey(c, d):
    return (dim_drs.local(c), frozenset((dim_drs.local(k), dim_drs.local(v)) for k, v in d.items()))


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
    except ValueError:
        pass

rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
res = workbook_rules.CellResolver(EXT)


def make_cellval(tab, sr, sc, sz):
    def cellval(cref):
        rvals = workbook_rules._semi(cref.get("r")) or [cref.get("r") or sr]
        cvals = workbook_rules._semi(cref.get("c")) or [cref.get("c") or sc]
        zz = cref.get("z") or ([sz] if sz else [])
        tot = 0.0
        for rv in rvals:
            for cv in cvals:
                for dp in res.resolve({"table": cref.get("table") or tab, "r": rv, "c": cv, "z": zz}):
                    tot += facts.get(fkey(dp["concept"], dp["dims"])) or 0.0
        return tot
    return cellval


def ev(node, cellval):
    t = node[0]
    if t == "num":
        return node[1]
    if t == "cell":
        return cellval(node[1])
    if t == "neg":
        return -ev(node[1], cellval)
    if t == "bin":
        a, b = ev(node[2], cellval), ev(node[3], cellval)
        return {"+": a + b, "-": a - b, "*": a * b, "/": (a / b if b else 0.0)}[node[1]]
    if t == "call":
        nm, args = node[1], node[2]
        vals = [ev(a, cellval) for a in args]
        if nm in ("iabs", "abs"):
            return abs(vals[0]) if vals else 0.0
        if nm == "isum":
            return sum(vals)
        if nm in ("imax", "max"):
            return max(vals)
        if nm in ("imin", "min"):
            return min(vals)
        return 0.0
    return 0.0


for code in CODES:
    r = [x for x in rules if x["code"] == code]
    if not r:
        print(f"{code}: NOT FOUND"); continue
    r = r[0]
    try:
        ast = formula_eval._Parser(formula_eval._tokenize(r["expression"])).parse()
    except Exception as e:
        print(f"{code}: parse error {e}"); continue
    node = ast[2] if ast[0] == "if" else ast
    if not (isinstance(node, tuple) and node[0] == "cmp"):
        print(f"{code}: not a comparison (op={node[0] if isinstance(node,tuple) else '?'})"); continue
    op = node[1]
    sc = workbook_rules.parse_scope(r.get("scope", "")) or {"table": "", "rows": [], "cols": [], "z": []}
    tab = sc.get("table") or (r["tables"][0] if r["tables"] else "")
    ok = bad = 0; ex = []
    for sr in (sc["rows"] or [None]):
        for scl in (sc["cols"] or [None]):
            for sz in (sc["z"] or [None]):
                cv = make_cellval(tab, sr, scl, sz)
                a, b = ev(node[2], cv), ev(node[3], cv)
                good = {"<=": a <= b + 0.5, "<": a < b + 0.5, ">=": a >= b - 0.5,
                        ">": a > b - 0.5, "=": abs(a - b) < 0.5}.get(op, True)
                if good:
                    ok += 1
                else:
                    bad += 1
                    if len(ex) < 3:
                        ex.append(f"{a:.0f} {op} {b:.0f}")
    print(f"{code} [{op}]: satisfied={ok} VIOLATED={bad}   {ex}")
