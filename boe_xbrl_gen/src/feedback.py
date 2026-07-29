"""
Arelle-feedback solver for cross-table aggregation rules (Layer 3, hard tail).

Some additivity assertions sum a column of one open table into a single cell of
another (e.g. structural_reform b1040-b1052: `{T1,c} = sum({T2,c})`). The two tables
use *mismatched* open (typed) dimensions, so offline implicit-filtering can't reliably
reproduce the exact fact set Arelle pairs — neither global grouping nor a shared-aspect
join matches (verified against the official sample).

But Arelle's unsatisfied-assertion message ALREADY lists the bound fact line numbers:

    ... - RFB007.xbrl 190, 1725, 1752, ..., 2346, http://.../vr-boe_b1042_m.xml 9
                       ^^^ target (single var)  ^^^ summands (sequence var)

So after one validation pass we read the pairing straight from the log, map line numbers
back to facts, classify each as the target (the non-sequence variable) or a summand (the
sequence variable) via the rule's own selectors, and set `target = aggregate(summands)`.
A second validation confirms. This is exact (Arelle's own binding) rather than inferred.

Currently handles equality-of-aggregate rules: `numeric-equal($t, iaf:sum($s))` and the
bare `$t = sum($s)` shape (sum is the only aggregate these cross-table rules use).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import expr as E
import solve as S
import solve_all
from instance import Instance
from resolver import _concepts_for, _dim_filters_for, _fact_matches

# "<file>.xbrl <int>, <int>, ... , <int>, https://..."  -> capture the int run.
_FACTS_RE = re.compile(r"\.xbrl\s+([\d,\s]+?)\s*,?\s*https?://")
_MSG_RE = re.compile(r"^\[message:([^\]]+)\]")


def parse_assertion_bindings(log_path):
    """Yield (assertion_id, [line_numbers]) for each unsatisfied-assertion message that
    carries instance fact line numbers."""
    out = []
    text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        m = _MSG_RE.match(line.strip())
        if not m:
            continue
        fm = _FACTS_RE.search(line)
        if not fm:
            continue
        lns = [int(x) for x in re.findall(r"\d+", fm.group(1))]
        if lns:
            out.append((m.group(1), lns))
    return out


def _agg_equality(test):
    """If `test` is `numeric-equal($t, sum($s))` / `$t = sum($s)` (optionally wrapped in
    `if cond then ... else true()`), return (target_var, seq_var, fn); else None."""
    ast = S._safe_parse(test)
    if ast is None:
        return None
    _, core = S._unwrap(ast)
    sides = S._equality_sides(core)
    if not sides:
        return None
    lhs, rhs = sides
    # find the single-var side (target) and the aggregate-call side (summands)
    for single, agg in ((lhs, rhs), (rhs, lhs)):
        if single[0] == "var" and agg[0] == "call":
            fn = agg[1].split(":")[-1]
            if fn in ("sum",) and len(agg[2]) == 1 and agg[2][0][0] == "var":
                return single[1], agg[2][0][1], fn
    return None


def _matches_var(fact, rule, var, defaults):
    return _fact_matches(fact, _concepts_for(rule, var), _dim_filters_for(rule, var), defaults)


def apply_feedback(instance, rules_by_id, bindings, defaults):
    """Mutate facts so each failing aggregation assertion holds, using Arelle's own pairing.
    Returns stats dict."""
    line2fact = {}
    for f in instance.facts:
        if f.el is not None and f.el.sourceline is not None:
            line2fact[f.el.sourceline] = f

    n_rules = n_set = n_skip = 0
    for aid, lines in bindings:
        rule = rules_by_id.get(aid)
        if rule is None:
            continue
        info = _agg_equality(rule.test)
        if not info:
            continue
        tvar, svar, _ = info
        tv, sv = rule.variables.get(tvar), rule.variables.get(svar)
        if tv is None or sv is None:
            continue
        facts = [line2fact[ln] for ln in lines if ln in line2fact]
        targets = [f for f in facts if _matches_var(f, rule, tv, defaults)]
        summands = [f for f in facts if _matches_var(f, rule, sv, defaults)
                    and not _matches_var(f, rule, tv, defaults)]
        # the target variable is non-sequence: exactly one target fact must be identifiable
        if len(targets) != 1 or not summands:
            n_skip += 1
            continue
        tf = targets[0]
        if not S._numeric_fact(tf):
            n_skip += 1
            continue
        total = sum(S._to_num(f.value) for f in summands)
        tf.value = S._round_to_decimals(total, tf.decimals)
        n_rules += 1
        n_set += 1
    return {"assertions_fixed": n_rules, "facts_set": n_set, "skipped": n_skip}


def run(in_path, out_path, log_path, val_dir, defaults_path, cache=None):
    defaults = json.loads(Path(defaults_path).read_text(encoding="utf-8"))
    rules = solve_all.parse_all_rules(val_dir, cache=cache)
    rules_by_id = {r.id: r for r in rules}
    inst = Instance(in_path)
    bindings = parse_assertion_bindings(log_path)
    stats = apply_feedback(inst, rules_by_id, bindings, defaults)
    inst.write(out_path)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--log", required=True, help="Arelle validate log of the --in instance")
    ap.add_argument("--val-dir", required=True)
    ap.add_argument("--defaults", required=True)
    ap.add_argument("--cache", default=None)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    stats = run(args.inp, args.out, args.log, args.val_dir, args.defaults, cache=args.cache)
    print(f"[feedback] {stats} -> {args.out}")


if __name__ == "__main__":
    main()
