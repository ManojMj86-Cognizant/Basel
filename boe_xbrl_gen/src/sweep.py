"""
Multi-module sweep (task #8). For every official sample instance: generate a random
instance, solve all of its framework's business rules offline, optionally validate once
with Arelle, and tabulate the results.

Each module's framework `val` directory is derived from its own schemaRef, so this works
across all returns without per-module configuration.

  python sweep.py [--validate] [--max-mb 20] [--only PRA118,LVR002] [--seed 1]

By default it solves + reports stats for every module WITHOUT validating (fast). Add
--validate to also run the (slow) single Arelle pass per module and report violation counts.
--max-mb skips modules larger than the given size (e.g. to defer the 50-85 MB returns).
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import generate
import solve_all
import solve_loop

ROOT = r"C:\Users\177069\ClaudeLearning"
SAMPLES = fr"{ROOT}\boebankingtaxonomysampleinstancesv400"
PKG = fr"{ROOT}\boebanking400.zip"
PKG_ROOT = fr"{ROOT}\boebanking400"
MODEL = fr"{ROOT}\boe_xbrl_gen\model\dpm_model.json"
DEFAULTS = fr"{ROOT}\boe_xbrl_gen\model\dim_defaults.json"
OUT = fr"{ROOT}\boe_xbrl_gen\out\sweep"

SCHEMAREF_RE = re.compile(r'schemaRef[^>]*href="([^"]+)"')
FWS_RE = re.compile(r"/fws/banking/([^/]+)/([^/]+)/mod/")


def val_dir_for(sample_path):
    """Derive the local framework val/ directory from a sample's schemaRef."""
    with open(sample_path, encoding="utf-8-sig") as fh:
        head = fh.read(8000)
    m = SCHEMAREF_RE.search(head)
    if not m:
        return None, None
    href = m.group(1)
    fw = FWS_RE.search(href)
    framework = fw.group(1) if fw else "?"
    host_path = re.sub(r"^https?://", "", href)
    host_path = re.sub(r"/mod/[^/]+\.xsd$", "/val", host_path)
    local = Path(PKG_ROOT) / "Banking_4.0.0" / host_path
    return (local if local.exists() else None), framework


def module_of(name):
    m = re.search(r"_banking_([A-Z0-9]+)_", name)
    return m.group(1) if m else name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--max-mb", type=float, default=1e9)
    ap.add_argument("--only", default=None, help="comma-separated module codes")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--feedback", action="store_true",
                    help="after the first validation, fix cross-table aggregation rules "
                         "from Arelle's reported fact pairing, then re-validate")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    Path(OUT).mkdir(parents=True, exist_ok=True)

    only = set(args.only.split(",")) if args.only else None
    samples = sorted(Path(SAMPLES).glob("*.xbrl"), key=lambda p: p.stat().st_size)
    model = generate.load_model(MODEL)
    rows = []
    for s in samples:
        mod = module_of(s.name)
        mb = s.stat().st_size / 1e6
        if only and mod not in only:
            continue
        if mb > args.max_mb:
            print(f"SKIP {mod} ({mb:.1f} MB > max)", flush=True)
            continue
        val_dir, fw = val_dir_for(s)
        if not val_dir:
            print(f"SKIP {mod}: no val dir resolved", flush=True)
            continue
        print(f"\n=== {mod} [{fw}] {mb:.2f} MB ===", flush=True)
        t0 = time.time()
        gen = f"{OUT}\\{mod}.gen.xbrl"
        out = f"{OUT}\\{mod}.xbrl"
        generate.generate(str(s), gen, model, seed=args.seed)
        # cache key MUST include the framework date — a framework can have multiple dated
        # versions (e.g. leverage 2023-05-11 vs 2026-02-27) with different rule sets.
        date = Path(val_dir).parent.name
        cache = f"{OUT}\\rules_{fw}_{date}.pkl"
        rules = solve_all.parse_all_rules(str(val_dir), cache=cache)
        from instance import Instance
        from solve import solve
        import random
        inst = Instance(gen)
        stats = solve(inst, rules, DEFAULTS_JSON(), random.Random(args.seed), rounds=args.rounds)
        inst.write(out)
        viol = None
        if args.validate:
            vlog = f"{OUT}\\{mod}.validate.log"
            solve_loop.run_arelle(out, PKG, vlog)
            viol = len(solve_loop.parse_violations(vlog))
            if args.feedback and viol:
                # fix cross-table aggregation rules using Arelle's own fact pairing
                import feedback
                rules_by_id = {r.id: r for r in rules}
                bindings = feedback.parse_assertion_bindings(vlog)
                inst2 = Instance(out)
                fstats = feedback.apply_feedback(inst2, rules_by_id, bindings, DEFAULTS_JSON())
                if fstats["facts_set"]:
                    inst2.write(out)
                    solve_loop.run_arelle(out, PKG, vlog)
                    viol = len(solve_loop.parse_violations(vlog))
                    print(f"  feedback {fstats} -> violations={viol}", flush=True)
        dt = time.time() - t0
        rows.append((mod, fw, round(mb, 2), len(inst.facts), stats.get("derived_facts"),
                     stats.get("ineq_adjustments"), viol, round(dt)))
        print(f"  facts={len(inst.facts)} derived={stats.get('derived_facts')} "
              f"ineq_adj={stats.get('ineq_adjustments')} violations={viol} ({dt:.0f}s)", flush=True)

    print("\n==== SWEEP SUMMARY ====")
    print(f"{'module':9}{'framework':24}{'MB':>7}{'facts':>8}{'derived':>9}"
          f"{'ineqAdj':>9}{'viol':>7}{'secs':>7}")
    for r in rows:
        viol = "-" if r[6] is None else r[6]
        print(f"{r[0]:9}{r[1]:24}{r[2]:>7}{r[3]:>8}{r[4]:>9}{r[5]:>9}{str(viol):>7}{r[7]:>7}")


_DEF_CACHE = None
def DEFAULTS_JSON():
    global _DEF_CACHE
    if _DEF_CACHE is None:
        import json
        _DEF_CACHE = json.loads(Path(DEFAULTS).read_text(encoding="utf-8"))
    return _DEF_CACHE


if __name__ == "__main__":
    main()
