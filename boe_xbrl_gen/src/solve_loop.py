"""
Generate->solve->validate loop driver (Layer 3 integration).

Iterates:
  1. Validate the instance with Arelle -> capture unsatisfied assertions + their rule URLs.
  2. Map rule URLs to local package files, parse them.
  3. Solve (equality dependency graph + format rules) and rewrite the instance.
  4. Re-validate; repeat until zero violations, max iters, or no further improvement.

Run:
  python solve_loop.py --in gen.xbrl --out solved.xbrl --pkg <taxonomy.zip>
                       --defaults dim_defaults.json [--iters 6] [--seed 1]
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import formula_rules as fr
from instance import Instance
from solve import solve

PKG_WEB_ROOT_NAME = "Banking_4.0.0"
MSG_RE = re.compile(r"^\[message:([^\]]+)\]")
URL_RE = re.compile(r"(https?://[^\s]+\.xml)")


def run_arelle(instance_path, pkg, log_path):
    # Arelle appends to --logFile; remove any prior log so we only parse THIS run.
    try:
        Path(log_path).unlink()
    except FileNotFoundError:
        pass
    cmd = [sys.executable, "-m", "arelle.CntlrCmdLine",
           "--packages", pkg, "--validate", "-f", instance_path,
           "--logFile", log_path, "--logLevel", "info"]
    subprocess.run(cmd, capture_output=True, text=True, timeout=3600)


def parse_violations(log_path):
    """Return list of (assertion_id, rule_url) for unsatisfied assertions."""
    out = []
    text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        m = MSG_RE.match(line.strip())
        if not m:
            continue
        u = URL_RE.search(line)
        out.append((m.group(1), u.group(1) if u else None))
    return out


def url_to_local(url, pkg_extract_root):
    """Map a taxonomy URL to its local file inside the extracted package."""
    if not url:
        return None
    host_path = re.sub(r"^https?://", "", url)
    local = Path(pkg_extract_root) / PKG_WEB_ROOT_NAME / host_path
    return local if local.exists() else None


def run(inp, out, pkg, pkg_root, defaults_path, iters=6, seed=1):
    rng = random.Random(seed)
    defaults = json.loads(Path(defaults_path).read_text(encoding="utf-8"))

    work = inp
    log = str(Path(out).with_suffix(".validate.log"))
    rule_cache = {}
    final_viol = None

    prev = None
    for it in range(1, iters + 1):
        run_arelle(work, pkg, log)
        viols = parse_violations(log)
        ids = sorted(set(a for a, _ in viols))
        final_viol = len(viols)
        print(f"[iter {it}] violations: {len(viols)} (distinct assertions: {len(ids)})")
        if not viols:
            print("  -> ZERO violations. done.")
            break
        no_improve = prev is not None and len(viols) >= prev
        prev = len(viols)

        rule_urls = sorted(set(u for _, u in viols if u))
        rules = []
        for u in rule_urls:
            local = url_to_local(u, pkg_root)
            if not local:
                continue
            if local not in rule_cache:
                try:
                    rule_cache[local] = fr.parse_file(local)
                except Exception:
                    rule_cache[local] = []
            rules.extend(rule_cache[local])
        print(f"  parsed {len(rules)} failing rules from {len(rule_urls)} files")
        if no_improve:
            print(f"  -> no improvement; remaining {len(ids)} assertions unsolved: {ids[:12]}")
            break

        inst = Instance(work)
        stats = solve(inst, rules, defaults, rng)
        inst.write(out)
        print(f"  solved: {stats}")
        work = out

    print(f"\nfinal instance: {out}\nlog: {log}")
    return final_viol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pkg", required=True)
    ap.add_argument("--pkg-root", required=True, help="extracted package root (has Banking_4.0.0)")
    ap.add_argument("--defaults", required=True)
    ap.add_argument("--iters", type=int, default=6)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    run(args.inp, args.out, args.pkg, args.pkg_root, args.defaults, args.iters, args.seed)


if __name__ == "__main__":
    main()
