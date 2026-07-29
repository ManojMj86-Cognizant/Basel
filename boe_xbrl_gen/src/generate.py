"""
Hybrid BoE Banking XBRL instance generator (Layer 1 clone + Layer 3 value engine).

Strategy: take an official module sample as the structural skeleton (root namespaces,
schemaRef, units, contexts incl. all dimensions, filing indicators) and re-emit it with
type-correct RANDOM fact values. Structure is preserved verbatim, so the output is
structurally and dimensionally valid by construction (same guarantee the BoE samples have).

Datatype handling (authoritative datatype from the DPM model, keyed by metric code):
  MONETARY / DECIMAL  -> number formatted to the fact's @decimals
  PERCENTAGE          -> fraction in [0,1] to @decimals (or 4)
  INTEGER             -> random non-negative integer
  BOOLEAN             -> "true" / "false"
  DATE                -> random ISO date near the reporting period
  ENUMERATION         -> a member QName drawn from the pool of values that the sample
                         already uses for that metric (guarantees valid member + prefix)
  STRING              -> random alnum token (format-rule-aware generation is Layer 3)

Business-rule satisfaction (additivity, signs, cross-table) is layered on separately
(see business_rules.py) using Arelle's assertion feedback; this module produces the
structurally-valid, randomly-valued base instance.

Usage:
  python generate.py --sample <in.xbrl> --out <out.xbrl> [--seed N]
                     [--lei XX;optional] [--period YYYY-MM-DD] [--randomize-strings]
"""
from __future__ import annotations

import argparse
import json
import random
import re
import string
from collections import defaultdict
from pathlib import Path

from lxml import etree

XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
FIND = "http://www.eurofiling.info/xbrl/ext/filing-indicators"
XSI = "http://www.w3.org/2001/XMLSchema-instance"

DEFAULT_MODEL = r"C:\Users\177069\ClaudeLearning\boe_xbrl_gen\model\dpm_model.json"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_QNAME_RE = re.compile(r"^[A-Za-z_][\w.\-]*:[A-Za-z_][\w.\-]*$")


def load_model(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def infer_datatype(localname, text, has_unit, model):
    """DPM datatype is authoritative; fall back to value-shape inference."""
    m = model["metrics"].get(localname)
    if m and m["datatype"]:
        return m["datatype"]
    t = (text or "").strip()
    if t in ("true", "false"):
        return "BOOLEAN"
    if _QNAME_RE.match(t):
        return "ENUMERATION"
    if _DATE_RE.match(t):
        return "DATE"
    if has_unit:
        return "MONETARY"
    return "STRING"


def _fmt_number(decimals, low, high, frac=False):
    """Format a random number honoring an XBRL @decimals value."""
    if decimals in (None, "INF", "inf"):
        d = 2
    else:
        d = int(decimals)
    if frac:                       # percentage as fraction in [0,1]
        dd = max(d, 4)
        return f"{random.uniform(0, 1):.{dd}f}"
    if d <= 0:                     # round to 10^(-d): e.g. d=-3 -> multiples of 1000
        step = 10 ** (-d)
        return str(random.randint(low // step or 1, high // step) * step)
    return f"{random.uniform(low, high):.{d}f}"


def gen_value(dtype, decimals, enum_pool, rng_period_year):
    if dtype in ("MONETARY", "DECIMAL"):
        return _fmt_number(decimals, 1, 9_999_000)
    if dtype == "PERCENTAGE":
        return _fmt_number(decimals, 0, 1, frac=True)
    if dtype == "INTEGER":
        return str(random.randint(0, 100_000))
    if dtype == "BOOLEAN":
        return random.choice(("true", "false"))
    if dtype == "DATE":
        y = rng_period_year + random.randint(-2, 3)
        mth = random.randint(1, 12)
        day = random.randint(1, 28)
        return f"{y:04d}-{mth:02d}-{day:02d}"
    if dtype == "ENUMERATION":
        return random.choice(enum_pool) if enum_pool else None
    # STRING
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def is_fact(el):
    if el.get("contextRef") is None:
        return False
    ns = etree.QName(el).namespace
    return ns not in (FIND,)  # filingIndicator also has contextRef but lives in FIND ns


def generate(sample_path, out_path, model, seed=None, lei=None, period=None,
             randomize_strings=False):
    if seed is not None:
        random.seed(seed)
    parser = etree.XMLParser(remove_blank_text=False, remove_comments=False)
    tree = etree.parse(sample_path, parser)
    root = tree.getroot()

    # period year hint for date generation
    period_year = 2026
    for inst in root.iter(f"{{{XBRLI}}}instant"):
        if inst.text and _DATE_RE.match(inst.text.strip()):
            period_year = int(inst.text.strip()[:4])
            break

    # ---- pass 1: collect enum value pools per metric (localname) ----
    enum_pools = defaultdict(list)
    facts = []
    for el in root.iter():
        if not is_fact(el):
            continue
        facts.append(el)
        ln = etree.QName(el).localname
        txt = (el.text or "").strip()
        if _QNAME_RE.match(txt):
            dtype = infer_datatype(ln, txt, el.get("unitRef") is not None, model)
            if dtype == "ENUMERATION" and txt not in enum_pools[ln]:
                enum_pools[ln].append(txt)

    # ---- optional: rewrite entity LEI and/or period ----
    if lei:
        for ident in root.iter(f"{{{XBRLI}}}identifier"):
            ident.text = lei
    if period:
        for inst in root.iter(f"{{{XBRLI}}}instant"):
            inst.text = period
        for end in root.iter(f"{{{XBRLI}}}endDate"):
            end.text = period

    # ---- pass 2: replace fact values ----
    counts = defaultdict(int)
    for el in facts:
        if el.get(f"{{{XSI}}}nil") == "true":
            continue
        ln = etree.QName(el).localname
        txt = (el.text or "").strip()
        dtype = infer_datatype(ln, txt, el.get("unitRef") is not None, model)
        if dtype == "STRING" and not randomize_strings:
            continue  # keep sample's strings (often format-constrained); see Layer 3
        new = gen_value(dtype, el.get("decimals"), enum_pools.get(ln), period_year)
        if new is not None:
            el.text = new
            counts[dtype] += 1

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    # write with declaration + BOM to match BoE sample style
    xml_bytes = etree.tostring(tree, xml_declaration=True, encoding="utf-8")
    with open(out_path, "wb") as fh:
        fh.write(b"\xef\xbb\xbf")
        fh.write(xml_bytes)

    return {"facts": len(facts), "replaced_by_type": dict(counts),
            "enum_metrics": len(enum_pools)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--lei", default=None)
    ap.add_argument("--period", default=None)
    ap.add_argument("--randomize-strings", action="store_true")
    args = ap.parse_args()

    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    model = load_model(args.model)
    stats = generate(args.sample, args.out, model, seed=args.seed, lei=args.lei,
                     period=args.period, randomize_strings=args.randomize_strings)
    print(f"wrote {args.out}")
    print(f"facts: {stats['facts']}  enum-metrics: {stats['enum_metrics']}")
    print(f"replaced by type: {stats['replaced_by_type']}")


if __name__ == "__main__":
    main()
