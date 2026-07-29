"""Diagnose the TDG XPTY0004 type errors on boe_b0365 / boe_b0366: dump each rule's expression and
resolve every cell it references to its concept + DATATYPE, then check whether our v2 instance (and the
official PRA001 sample) actually report a fact there. A string/enum concept fed into a numeric formula
(e.g. cell*cell in a √Σcell² rule) is the culprit."""
import sys, json, os
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from lxml import etree
import workbook_rules
from src import dim_drs

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
WB = "../boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx"
V2 = r"C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v2.xbrl"
SAMPLE = ("../boebankingtaxonomysampleinstancesv400/"
          "ABCDEFGHIJ0123456789_GB_banking_PRA001_2026-02-28_20260220142410000.xbrl")
X = "http://www.xbrl.org/2003/instance"
CODES = sys.argv[1:] or ["boe_b0365", "boe_b0366", "boe_b0360", "boe_b0364"]

# model datatypes
mp = os.path.join(BASE, "model.merged.json")
if not os.path.exists(mp):
    mp = os.path.join(BASE, "model.json")
metrics = (json.load(open(mp, encoding="utf-8")).get("metrics", {})) if os.path.exists(mp) else {}


def dtype(concept_local):
    return (metrics.get(concept_local, {}) or {}).get("datatype", "?")


def load_present(path):
    raw = open(path, "rb").read(); raw = raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw
    root = etree.fromstring(raw)
    present = {}
    for el in root:
        if el.get("contextRef") is None:
            continue
        present.setdefault(dim_drs.local(etree.QName(el).localname), []).append((el.text or "").strip())
    return present


v2 = load_present(V2)
try:
    samp = load_present(SAMPLE)
except Exception as e:
    samp = {}; print("(sample load failed:", e, ")")

rules = workbook_rules.load_workbook_rules(WB, "banking_reporting")
res = workbook_rules.CellResolver(EXT)

for code in CODES:
    r = next((x for x in rules if x["code"] == code), None)
    if not r:
        print(f"\n{code}: NOT FOUND"); continue
    print(f"\n===== {code}  tables={r['tables']}")
    print(f"  precondition: {r.get('precondition','')!r}")
    print(f"  FULL expr: {r['expression']}")
    for m in workbook_rules._CELL_RE.finditer(r["expression"]):
        cref = workbook_rules._parse_cell(m.group(1))
        dps = res.resolve({"table": cref.get("table"), "r": cref.get("r"),
                           "c": cref.get("c"), "z": cref.get("z")})
        if not dps:
            print(f"    r={cref.get('r')} c={cref.get('c')} -> UNRESOLVED (bridge miss)")
            continue
        for dp in dps:
            cl = dim_drs.local(dp["concept"])
            dt = dtype(cl)
            flag = "  <-- NON-NUMERIC!" if dt.upper() not in (
                "MONETARY", "DECIMAL", "PERCENTAGE", "INTEGER", "?") else ""
            nv2 = len(v2.get(cl, [])); nsp = len(samp.get(cl, []))
            print(f"    r={cref.get('r')} c={cref.get('c')} -> {cl:10s} dtype={dt:12s} "
                  f"v2_facts={nv2:4d} sample_facts={nsp:4d}{flag}")
