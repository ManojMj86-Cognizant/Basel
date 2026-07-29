"""
One-command pipeline: clone a module sample -> randomize values -> solve business
rules -> validate. The reusable entry point for generating a valid BoE banking XBRL
instance for any module.

  python pipeline.py --sample <module sample.xbrl> --out <out.xbrl> [--seed N] [--iters 6]

Paths to the taxonomy package, extracted package root, DPM model and dimension defaults
default to the locations under C:\\Users\\177069\\ClaudeLearning.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import generate
import solve_loop

ROOT = r"C:\Users\177069\ClaudeLearning"
DEF = {
    "pkg": fr"{ROOT}\boebanking400.zip",
    "pkg_root": fr"{ROOT}\boebanking400",
    "model": fr"{ROOT}\boe_xbrl_gen\model\dpm_model.json",
    "defaults": fr"{ROOT}\boe_xbrl_gen\model\dim_defaults.json",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--iters", type=int, default=6)
    ap.add_argument("--lei", default=None)
    ap.add_argument("--period", default=None)
    for k, v in DEF.items():
        ap.add_argument(f"--{k.replace('_','-')}", default=v)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    gen_path = str(Path(args.out).with_name(Path(args.out).stem + ".gen.xbrl"))
    model = generate.load_model(args.model)
    stats = generate.generate(args.sample, gen_path, model, seed=args.seed,
                              lei=args.lei, period=args.period)
    print(f"[generate] {gen_path}  facts={stats['facts']} {stats['replaced_by_type']}")

    final = solve_loop.run(gen_path, args.out, args.pkg, args.pkg_root,
                           args.defaults, iters=args.iters, seed=args.seed)
    print(f"\n[pipeline] final violations: {final}  -> {args.out}")


if __name__ == "__main__":
    main()
