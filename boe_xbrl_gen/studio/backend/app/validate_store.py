"""Validate an XBRL instance with Arelle — a separate, async step from generation.

Runs Arelle offline (against the package's cached `source.zip`) on a chosen file (a generated
instance or the uploaded one), prunes dimensionally-invalid facts, and parses the report
(dimInvalid / valueErrors / unsatisfied business-rule assertions). One job slot per package;
the report + a cleaned file are cached under `<hash>/validation/` so the Validation tab can show
progress and survive navigation. Every failure is surfaced as status:"error" — never a 500.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

from . import config, instance_store

if str(config.ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(config.ENGINE_DIR))
from src import instance_build  # noqa: E402

# pkg_id -> {status, t0, filename, source, report?, cleaned?, removed?, elapsedMs?, error?}
_JOBS: dict[str, dict] = {}


def _dir(pkg_id: str) -> Path:
    return config.CACHE_DIR / pkg_id


def _vdir(pkg_id: str) -> Path:
    return _dir(pkg_id) / "validation"


def _resolve(pkg_id: str, source: str, filename: str) -> Path | None:
    name = Path(filename).name
    if source == "uploaded":
        p = _dir(pkg_id) / "instance" / "uploaded.xbrl"
    elif source == "solved":
        p = _dir(pkg_id) / "solved" / name
    else:
        p = _dir(pkg_id) / "generated" / name
    return p if p.exists() else None


def _run(pkg_id: str, source: str, filename: str) -> None:
    job = _JOBS[pkg_id]
    try:
        src = _resolve(pkg_id, source, filename)
        if src is None:
            raise RuntimeError(f"File not found: {filename}")
        zip_path = instance_store.source_zip(pkg_id)
        if not zip_path:
            raise RuntimeError("Package source zip not cached — re-upload the package to enable Arelle validation.")
        xml = src.read_bytes()
        log = instance_build.validate(xml, zip_path)
        cleaned, removed = instance_build.prune_invalid(xml, log)
        if removed:
            log = instance_build.validate(cleaned, zip_path)   # confirm the cleaned file
        report = instance_build.parse_report(log)

        vdir = _vdir(pkg_id)
        vdir.mkdir(parents=True, exist_ok=True)
        cleaned_name = ""
        if removed:
            cleaned_name = Path(filename).stem + ".cleaned.xbrl"
            (vdir / cleaned_name).write_bytes(cleaned)
        out = {
            "status": "ready", "filename": filename, "source": source,
            "report": report, "removed": removed, "cleaned": cleaned_name,
            "elapsedMs": round((time.time() - job["t0"]) * 1000),
        }
        (vdir / "result.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        job.update(out)
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


def start(pkg_id: str, source: str, filename: str) -> dict:
    if not (_dir(pkg_id) / ".extracted").exists():
        return {"status": "error", "error": "Package not found / not extracted."}
    if not filename:
        return {"status": "error", "error": "No file specified."}
    job = _JOBS.get(pkg_id)
    if job and job["status"] == "building":
        return {"status": "building"}
    _JOBS[pkg_id] = {"status": "building", "t0": time.time(), "filename": filename, "source": source}
    threading.Thread(target=_run, args=(pkg_id, source, filename), daemon=True).start()
    return {"status": "building", "filename": filename}


def status(pkg_id: str) -> dict:
    job = _JOBS.get(pkg_id)
    if job:
        keys = ("status", "filename", "source", "report", "removed", "cleaned", "elapsedMs", "error")
        return {k: job[k] for k in keys if k in job}
    rp = _vdir(pkg_id) / "result.json"
    if rp.exists():
        try:
            return json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            return {"status": "absent"}
    return {"status": "absent"}


def get_cleaned(pkg_id: str, filename: str) -> Path | None:
    p = _vdir(pkg_id) / Path(filename).name
    return p if p.exists() else None
