"""Probe the open-dimension structure of OF08.02.01.01: for a failing rule, resolve its cells (which
the rc-code bridge gives with CLOSED dims only) and show the instance facts that share those closed
dims — revealing the extra open/typed dimension + its values. This is the info needed to design
closed-dim matching for solve_existing."""
import sys, os
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules, formula_eval
from src import dim_drs

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
F = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID.xbrl"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
X = "http://www.xbrl.org/2003/instance"
CODES = sys.argv[1:] or ["boe_b0385", "boe_b0309", "boe_b0760"]

# load facts with FULL dims (explicit + typed)
raw = open(F, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
root = etree.fromstring(raw); ctx = {}
for c in root.findall(f"{{{X}}}context"):
    dd = {}; sc = c.find(f"{{{X}}}scenario")
    if sc is not None:
        for em in sc:
            if not em.get("dimension"):
                continue
            ln = etree.QName(em).localname
            if ln == "explicitMember":
                dd[dim_drs.local(em.get("dimension"))] = dim_drs.local((em.text or "").strip())
            elif ln == "typedMember":
                dd[dim_drs.local(em.get("dimension"))] = "typed:" + "".join(em.itertext()).strip()
    ctx[c.get("id")] = dd
# concept-local -> list of (full-dims-dict, value)
by_concept = {}
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    try:
        v = float((el.text or "").strip())
    except (ValueError, TypeError):
        continue
    ln = dim_drs.local(etree.QName(el).localname)
    by_concept.setdefault(ln, []).append((ctx.get(cr, {}), v))

rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
res = workbook_rules.CellResolver(EXT)


def closed_of(dp):
    return dim_drs.local(dp["concept"]), {dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}


for code in CODES:
    r = next((x for x in rules if x["code"] == code), None)
    if not r:
        print(f"\n{code}: NOT FOUND"); continue
    print(f"\n===== {code}  tables={r['tables']}  scope={r.get('scope','')[:50]}")
    print(f"  expr: {r['expression'][:150]}")
    # resolve each cell ref in the expression
    seen = set()
    for m in workbook_rules._CELL_RE.finditer(r["expression"]):
        cref = workbook_rules._parse_cell(m.group(1))
        for dp in res.resolve({"table": cref.get("table"), "r": cref.get("r"),
                               "c": cref.get("c"), "z": cref.get("z")}):
            cl, cdims = closed_of(dp)
            keyid = (cl, tuple(sorted(cdims.items())))
            if keyid in seen:
                continue
            seen.add(keyid)
            # find instance facts matching this concept + the closed dims as a SUBSET
            matches = [(fd, v) for fd, v in by_concept.get(cl, [])
                       if all(fd.get(dk) == dv for dk, dv in cdims.items())]
            extra_dims = set()
            for fd, v in matches:
                extra_dims |= (set(fd) - set(cdims))
            print(f"  cell r={cref.get('r')} c={cref.get('c')} -> {cl} closed={cdims}")
            print(f"      {len(matches)} instance fact(s); EXTRA (open) dims present: {sorted(extra_dims)}")
            for fd, v in matches[:4]:
                ex = {k: fd[k] for k in fd if k not in cdims}
                print(f"        val={v:.0f}  open={ex}")
