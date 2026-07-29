"""Test the open-dimension PAIRING model for b0385 (OF08.02.01.01: c0100 ≤ c0090).

Hypothesis: TDG pairs facts across the two cells by their OPEN-dim signature (= all dims except the
dims the rc-code bridge pins for the cells — here BAS + the column selector MCY). For each signature
present in BOTH cells, assert c0100 ≤ c0090. Report: #common signatures, #violations, and whether the
fan-out per Z layer is tractable."""
import sys
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs
from collections import defaultdict

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
F = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID.xbrl"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
X = "http://www.xbrl.org/2003/instance"

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
by_concept = defaultdict(list)
for el in root:
    cr = el.get("contextRef")
    if cr is None:
        continue
    try:
        v = float((el.text or "").strip())
    except (ValueError, TypeError):
        continue
    by_concept[dim_drs.local(etree.QName(el).localname)].append((ctx.get(cr, {}), v))

rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
res = workbook_rules.CellResolver(EXT)
r = next(x for x in rules if x["code"] == "boe_b0385")
sc = workbook_rules.parse_scope(r["scope"])
print("scope z:", sc["z"][:6], "..." if len(sc["z"]) > 6 else "", "total z:", len(sc["z"]))

# resolve the two cells -> closed dims
cells = [workbook_rules._parse_cell(m.group(1)) for m in workbook_rules._CELL_RE.finditer(r["expression"])]
resolved = []
for cref in cells:
    dps = res.resolve({"table": cref.get("table"), "r": cref.get("r"), "c": cref.get("c"), "z": cref.get("z")})
    if dps:
        dp = dps[0]
        resolved.append((dim_drs.local(dp["concept"]),
                         {dim_drs.local(k): dim_drs.local(v) for k, v in dp["dims"].items()}))
print("resolved cells:", resolved)

pinned = set()
for _, d in resolved:
    pinned |= set(d)
print("pinned dim keys (excluded from signature):", sorted(pinned))


def sig(fd):
    return tuple(sorted((k, v) for k, v in fd.items() if k not in pinned))


def matches(concept, cdims):
    out = {}
    for fd, v in by_concept.get(concept, []):
        if all(fd.get(dk) == dv for dk, dv in cdims.items()):
            out.setdefault(sig(fd), 0.0)
            out[sig(fd)] += v            # sum if >1 fact per signature
    return out


lhs = matches(*resolved[0])   # c0100
rhs = matches(*resolved[1])   # c0090
common = set(lhs) & set(rhs)
viol = [(s, lhs[s], rhs[s]) for s in common if lhs[s] > rhs[s] + 0.5]
print(f"\nc0100 signatures: {len(lhs)}   c0090 signatures: {len(rhs)}   COMMON: {len(common)}")
print(f"violations (c0100 > c0090): {len(viol)}")
for s, a, b in viol[:6]:
    print(f"   {a:.0f} > {b:.0f}   sig={dict(s)}")
# how many common signatures fall in the first z layer only?
z_first = [s for s in common if any(k in ('OGR',) for k, _ in s)]  # rough
