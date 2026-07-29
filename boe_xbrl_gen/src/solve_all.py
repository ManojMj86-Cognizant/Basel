"""
Offline whole-framework solver — built for large returns (e.g. PRA001) where validating
in Arelle every iteration is too slow. Parses ALL rules in a framework's val directory
once, solves them comprehensively against the instance (the solver does internal
dependency-ordered rounds), writes the result, then validates ONCE with Arelle.

  python solve_all.py --in gen.xbrl --out solved.xbrl --val-dir <framework val dir>
                      --pkg <taxonomy.zip> --defaults dim_defaults.json
                      [--rounds 10] [--validate]
"""
from __future__ import annotations

import argparse
import json
import pickle
import random
import sys
import time
from pathlib import Path

import formula_rules as fr
from instance import Instance
from solve import solve
import solve_loop


def log(msg):
    print(msg, flush=True)


def parse_all_rules(val_dir, cache=None):
    if cache and Path(cache).exists():
        with open(cache, "rb") as fh:
            rules = pickle.load(fh)
        log(f"loaded {len(rules)} rules from cache {cache}")
        return rules
    files = sorted(Path(val_dir).glob("vr-*.xml"))
    rules, n_files, n_parsed = [], 0, 0
    t0 = time.time()
    for f in files:
        n_files += 1
        # fast pre-filter: only files that actually contain a value assertion need parsing
        try:
            data = f.read_bytes()
        except OSError:
            continue
        if b"valueAssertion" not in data:
            continue
        n_parsed += 1
        try:
            rules.extend(fr.parse_file(f))
        except Exception:
            pass
        if n_parsed % 250 == 0:
            log(f"  parsed {n_parsed} assertion files ({n_files}/{len(files)} scanned), "
                f"{len(rules)} rules ({time.time()-t0:.0f}s)")
    log(f"parsed {len(rules)} assertions from {n_parsed} assertion files "
        f"({len(files)} scanned) in {time.time()-t0:.0f}s")
    if cache:
        with open(cache, "wb") as fh:
            pickle.dump(rules, fh)
        log(f"cached rules -> {cache}")
    return rules


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--val-dir", required=True)
    ap.add_argument("--pkg", required=True)
    ap.add_argument("--pkg-root", default=r"C:\Users\177069\ClaudeLearning\boebanking400")
    ap.add_argument("--defaults", required=True)
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    rng = random.Random(args.seed)
    defaults = json.loads(Path(args.defaults).read_text(encoding="utf-8"))

    log("[1] parsing all framework rules ...")
    cache = str(Path(args.out).parent / "rules_banking_reporting.pkl")
    rules = parse_all_rules(args.val_dir, cache=cache)

    log("[2] loading instance ...")
    t0 = time.time()
    inst = Instance(args.inp)
    log(f"  {len(inst.facts)} facts, {len(inst.contexts)} contexts ({time.time()-t0:.0f}s)")

    log("[3] solving ...")
    t0 = time.time()
    stats = solve(inst, rules, defaults, rng, rounds=args.rounds)
    log(f"  solve stats: {stats} ({time.time()-t0:.0f}s)")

    log("[4] writing ...")
    inst.write(args.out)
    log(f"  wrote {args.out}")

    if args.validate:
        log("[5] validating once with Arelle (slow for large instances) ...")
        t0 = time.time()
        vlog = str(Path(args.out).with_suffix(".validate.log"))
        solve_loop.run_arelle(args.out, args.pkg, vlog)
        viols = solve_loop.parse_violations(vlog)
        ids = sorted(set(a for a, _ in viols))
        log(f"  VIOLATIONS: {len(viols)} (distinct assertions: {len(ids)}) "
            f"({time.time()-t0:.0f}s)")
        if ids:
            log(f"  distinct: {ids[:40]}")


if __name__ == "__main__":
    main()
