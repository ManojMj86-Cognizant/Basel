"""Solve business rules on an instance (Phase B).

Iteratively **validate → solve + feedback → re-validate** until the package's XBRL Formula
assertions are satisfied or the iteration budget is exhausted, then writes a *solved* instance.
Each iteration runs the engine's single-table `solve` (additivity/sign/format/…) AND the
cross-table `feedback.apply_feedback` (aggregation tail) — the same combination the engine's
`sweep.py --feedback` uses for fully-clean modules. Async — each iteration is a full Arelle run
(slow). We reuse the proven engine solvers unchanged and only orchestrate + report.

Note: `solve_loop` (and `solve`/`feedback`) import `solve`, `instance`, `formula_rules` as
TOP-LEVEL modules, so `src/` must be importable directly — added below in addition to the repo
root the other stores use for `from src import …`. URL→local rule mapping in `solve_loop` is
keyed to the banking web root, so solving is exercised on banking 4.0.0 (the generate target).
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

from . import config, instance_store, model_store

_SRC = str(config.ENGINE_DIR / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
import solve_loop  # noqa: E402  (run_arelle / parse_violations / url_to_local)
from src import instance_build  # noqa: E402

# pkg_id -> job dict
_JOBS: dict[str, dict] = {}


def _solve_with_feedback(work: str, out: str, pkg: str, ext: str, defaults: dict, iters: int) -> tuple[list, str]:
    """Iterate validate → (single-table solve + cross-table feedback) → re-validate, to a
    fixpoint / no-improvement / iter cap. Mirrors the engine's `sweep.py --feedback` clean
    pipeline (`solve` for additivity/sign/etc. + `feedback.apply_feedback` for cross-table
    aggregation, which reads Arelle's own fact-line pairing from the validate log).

    Returns (counts, log_path) where counts[i] = {violations, assertions} observed at each
    validation. Re-validates the final file only if it wasn't the last thing validated, so a
    big module (PRA001 ~46 min/pass) isn't validated twice for nothing."""
    import random
    import feedback
    import formula_rules
    import instance as inst_mod
    from solve import solve

    rng = random.Random(1)
    log = str(Path(out).with_suffix(".validate.log"))
    counts: list = []
    cur = work
    last_validated = None
    prev = None
    for _ in range(max(1, iters)):
        solve_loop.run_arelle(cur, pkg, log)
        last_validated = cur
        viols = solve_loop.parse_violations(log)            # [(assertion_id, rule_url)]
        counts.append({"violations": len(viols), "assertions": len({a for a, _ in viols})})
        if not viols:
            break
        if prev is not None and len(viols) >= prev:
            break                                           # no improvement -> stop
        prev = len(viols)
        # parse only the FAILING rules (efficient) for both solvers
        rules = []
        for u in sorted({u for _, u in viols if u}):
            loc = solve_loop.url_to_local(u, ext)
            if loc:
                try:
                    rules += formula_rules.parse_file(loc)
                except Exception:
                    pass
        rules_by_id = {r.id: r for r in rules}
        inst = inst_mod.Instance(cur)
        try:
            solve(inst, rules, defaults, rng)               # single-table (additivity/sign/format/…)
        except Exception:
            pass
        try:
            bindings = feedback.parse_assertion_bindings(log)   # cross-table aggregation tail
            feedback.apply_feedback(inst, rules_by_id, bindings, defaults)
        except Exception:
            pass
        inst.write(out)
        cur = out
    if last_validated != cur:                               # final file not yet validated -> do it once
        solve_loop.run_arelle(cur, pkg, log)
        viols = solve_loop.parse_violations(log)
        counts.append({"violations": len(viols), "assertions": len({a for a, _ in viols})})
    return counts, log


def _dir(pkg_id: str) -> Path:
    return config.CACHE_DIR / pkg_id


def _sdir(pkg_id: str) -> Path:
    return _dir(pkg_id) / "solved"


def _resolve(pkg_id: str, source: str, filename: str) -> Path | None:
    name = Path(filename).name
    if source == "uploaded":
        p = _dir(pkg_id) / "instance" / "uploaded.xbrl"
    elif source == "solved":
        p = _sdir(pkg_id) / name
    else:
        p = _dir(pkg_id) / "generated" / name
    return p if p.exists() else None


def _run(pkg_id: str, source: str, filename: str, iters: int) -> None:
    job = _JOBS[pkg_id]
    try:
        src = _resolve(pkg_id, source, filename)
        if src is None:
            raise RuntimeError(f"File not found: {filename}")
        zip_path = instance_store.source_zip(pkg_id)
        if not zip_path:
            raise RuntimeError("Package source zip not cached — re-upload the package to enable solving.")
        model = model_store._active_model(pkg_id) or {}
        defaults = model.get("dim_defaults", {})
        ext = str(_dir(pkg_id))
        sdir = _sdir(pkg_id)
        sdir.mkdir(parents=True, exist_ok=True)
        solved_name = Path(filename).stem + ".solved.xbrl"
        out = sdir / solved_name

        counts, log = _solve_with_feedback(str(src), str(out), zip_path, ext, defaults, iters)

        before = counts[0] if counts else {"violations": None, "assertions": None}
        # remaining unsatisfied assertions from the final validate log
        remaining: list = []
        try:
            remaining = instance_build.parse_report(
                Path(log).read_text(encoding="utf-8", errors="replace"))["assertionsUnsatisfied"]
        except Exception:
            pass
        after = {"violations": counts[-1]["violations"] if counts else None,
                 "assertions": len({a["id"] for a in remaining}), "list": remaining}

        result = {
            "status": "ready", "filename": filename, "source": source,
            "solved": solved_name if out.exists() else "",   # no file if input was already valid
            "iterations": len(counts),
            "before": before, "after": after,
            "elapsedMs": round((time.time() - job["t0"]) * 1000),
        }
        (sdir / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        job.update(result)
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


def start(pkg_id: str, source: str, filename: str, iters: int = 4) -> dict:
    if not (_dir(pkg_id) / ".extracted").exists():
        return {"status": "error", "error": "Package not found / not extracted."}
    if not filename:
        return {"status": "error", "error": "No file specified."}
    job = _JOBS.get(pkg_id)
    if job and job["status"] == "solving":
        return {"status": "solving"}
    _JOBS[pkg_id] = {"status": "solving", "t0": time.time(), "filename": filename, "source": source}
    threading.Thread(target=_run, args=(pkg_id, source, filename, max(1, min(iters, 8))), daemon=True).start()
    return {"status": "solving", "filename": filename}


def status(pkg_id: str) -> dict:
    job = _JOBS.get(pkg_id)
    if job:
        keys = ("status", "filename", "source", "solved", "iterations", "before", "after", "elapsedMs", "error")
        return {k: job[k] for k in keys if k in job}
    rp = _sdir(pkg_id) / "result.json"
    if rp.exists():
        try:
            return json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            return {"status": "absent"}
    return {"status": "absent"}


def get_file(pkg_id: str, filename: str) -> Path | None:
    p = _sdir(pkg_id) / Path(filename).name
    return p if p.exists() else None


def list_solved(pkg_id: str) -> list[str]:
    sdir = _sdir(pkg_id)
    return sorted(p.name for p in sdir.glob("*.xbrl")) if sdir.exists() else []
