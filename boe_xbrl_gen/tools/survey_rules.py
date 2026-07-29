"""Survey ALL in-scope PRA001 rules: bucket by shape + current satisfaction. Finds rule families
like b0778 (Σ cells = constant) and b0745 (additive with missing cells)."""
import sys, json, re
from collections import Counter, defaultdict
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"; OUT = f"{BASE}/solved/_genvalid_pra001.xbrl"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
X = "http://www.xbrl.org/2003/instance"
tabs = set(json.load(open(f"{BASE}/generated/result.json", encoding="utf-8"))["instances"][0]["tables"])


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
        v = float((el.text or "").strip())
    except ValueError:
        continue
    facts[(dim_drs.local(etree.QName(el).localname), frozenset(cd.get(cr, {}).items()))] = v

rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
res = workbook_rules.CellResolver(EXT)
inscope = [r for r in rules if r["tables"] and set(r["tables"]) <= tabs and not r["deactivated"]]


def classify_unhandled(r):
    """Classify a rule NOT parsed by the current additive engine — i.e. one needing a new handler."""
    e = (r["expression"] or "")
    el = e.lower()
    if not e.strip():
        return "empty"
    if "isnull" in el:
        return "isnull/existence"
    if " then " in el or el.strip().startswith("if ") or el.strip().startswith("if("):
        return "conditional(if/then)"
    if any(t in el for t in ("exp(", "imax", "imin")):
        return "nonlinear(exp/imax)"
    m = workbook_rules._REL_RE.search(e)
    rel = (m.group(1) or m.group(2)) if m else None
    rel = ("i" + rel) if rel else ""
    if rel in ("i<=", "i>=", "i<", "i>", "i!="):
        return f"inequality({rel})"
    if rel == "i=":
        lhs, rhs = e[:m.start()], e[m.end():]
        if ("{" in lhs) != ("{" in rhs):
            return "additive=CONSTANT (b0778 class)"
        if "}*{" in e or re.search(r"\}\s*/\s*\{", e):
            return "cell*cell / ratio"
        return "additive=cells (parser-rejected: coef/format?)"
    return "other"


parsed = []          # handled by expand_scoped_asts
unhandled = []       # need a new handler
for r in inscope:
    (parsed if workbook_rules.expand_scoped_asts(r) else unhandled).append(r)

print(f"in-scope PRA001 rules: {len(inscope)}")
print(f"  handled by current additive parser: {len(parsed)}")
print(f"  NOT handled (need work):            {len(unhandled)}")
buckets = Counter(); examples = defaultdict(list)
for r in unhandled:
    cls = classify_unhandled(r)
    buckets[cls] += 1
    if len(examples[cls]) < 3:
        examples[cls].append(r["code"])
print("--- UNHANDLED rules by shape ---")
for cls, n in buckets.most_common():
    print(f"  {n:4d}  {cls:40s} e.g. {examples[cls]}")

# Among parseable-additive rules, how many currently have missing-cell (incomplete) eqs (b0745 class)?
add_missing = add_clean_fail = add_ok = 0
missing_codes = []
for r in inscope:
    asts = workbook_rules.expand_scoped_asts(r)
    if not asts:
        continue
    inc = fail = 0
    for a in asts:
        if a["op"] != "i=":
            continue
        dps = [dp for side in ("lhs", "rhs") for t in a[side] for dp in res.resolve(t["cell"])]
        if any(facts.get(fkey(dp["concept"], dp["dims"])) is None for dp in dps):
            inc += 1; continue
        lhs = sum((facts.get(fkey(dp["concept"], dp["dims"])) or 0) * t["coef"] for t in a["lhs"] for dp in res.resolve(t["cell"]))
        rhs = sum((facts.get(fkey(dp["concept"], dp["dims"])) or 0) * t["coef"] for t in a["rhs"] for dp in res.resolve(t["cell"]))
        if abs(lhs - rhs) >= 0.5:
            fail += 1
    if inc:
        add_missing += 1; missing_codes.append((r["code"], r["tables"], inc))
    elif fail:
        add_clean_fail += 1
    else:
        add_ok += 1
print(f"\n--- parseable additive(=cells) rules by satisfaction ---")
print(f"  fully satisfied:        {add_ok}")
print(f"  fail (cells present):   {add_clean_fail}")
print(f"  has MISSING cells (b0745 class): {add_missing}")
missing_codes.sort(key=lambda x: -x[2])
print("  top missing-cell rules (code, tables, #incomplete eqs):")
for c, t, n in missing_codes[:15]:
    print(f"     {c:12s} {n:5d}  {t}")
