"""Per-package DPM dictionary model: build (Arelle), cache, serve, reconcile.

Wraps the engine modules `src/taxonomy_model.py` (build the model from the extracted
package via Arelle) and `src/reconcile.py` (diff/merge against an uploaded DPM-dictionary
Excel). Mirrors `package_store`'s background-job + on-disk cache pattern.

Cache layout under `<CACHE_DIR>/<pkg_id>/`:
  model.json          base schema model (taxonomy_model shape == dpm_model.json shape)
  model.meta.json     {counts, elapsedMs, builtAt}
  model.merged.json   reconciled+merged model (present only after a reconcile)
  reconcile.json      {kind, filename, summary, diffs}
  uploads/            stashed Annotated-Templates workbooks (for Phase 1b)

The model build is slow (~37 s — loads ~72 dictionary schemas), so it runs in a background
thread and the frontend polls `build_status`.
"""
from __future__ import annotations

import glob
import io
import json
import shutil
import sys
import threading
import time
import zipfile
from pathlib import Path

from . import config

# Make the engine package importable: boe_xbrl_gen/ on sys.path -> `from src import ...`.
if str(config.ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(config.ENGINE_DIR))
from src import reconcile, taxonomy_model  # noqa: E402

# pkg_id -> {status: building|ready|error, t0, elapsedMs?, error?}
_BUILD_JOBS: dict[str, dict] = {}
# in-process cache of the active (merged-or-base) model: pkg_id -> (mtime, model)
_LOADED: dict[str, tuple[float, dict]] = {}


def _dir(pkg_id: str) -> Path:
    return config.CACHE_DIR / pkg_id


def _model_path(pkg_id: str) -> Path:
    return _dir(pkg_id) / "model.json"


def _merged_path(pkg_id: str) -> Path:
    return _dir(pkg_id) / "model.merged.json"


def _meta_path(pkg_id: str) -> Path:
    return _dir(pkg_id) / "model.meta.json"


def _reconcile_path(pkg_id: str) -> Path:
    return _dir(pkg_id) / "reconcile.json"


def _counts(model: dict) -> dict:
    return {
        "metrics": len(model.get("metrics", {})),
        "dimensions": len(model.get("dimensions", {})),
        "domains": len(model.get("domains", {})),
        "members": sum(len(v) for v in model.get("members", {}).values()),
    }


# ------------------------------------------------------------------------- build
def _run_build(pkg_id: str) -> None:
    job = _BUILD_JOBS[pkg_id]
    try:
        model = taxonomy_model.build_model(str(_dir(pkg_id)))
        if not model.get("metrics"):
            raise ValueError("Built model has no metrics (is this a valid taxonomy package?)")
        _model_path(pkg_id).write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        elapsed = round((time.time() - job["t0"]) * 1000)
        _meta_path(pkg_id).write_text(
            json.dumps({"counts": _counts(model), "elapsedMs": elapsed,
                        "builtAt": time.time()}, ensure_ascii=False), encoding="utf-8")
        _LOADED.pop(pkg_id, None)
        job["elapsedMs"] = elapsed
        job["status"] = "ready"
    except Exception as e:  # surface to the poller
        job["status"] = "error"
        job["error"] = str(e)


def start_build(pkg_id: str, force: bool = False) -> dict:
    """Build the model in the background (or return the cached one). Idempotent."""
    if not (_dir(pkg_id) / ".extracted").exists():
        return {"status": "error", "error": "Package not found / not extracted."}
    job = _BUILD_JOBS.get(pkg_id)
    if job and job["status"] == "building":
        return {"status": "building"}
    if _model_path(pkg_id).exists() and not force:
        return {"status": "ready", **_read_meta(pkg_id)}
    if force:
        _model_path(pkg_id).unlink(missing_ok=True)
        _merged_path(pkg_id).unlink(missing_ok=True)
        _reconcile_path(pkg_id).unlink(missing_ok=True)
        _LOADED.pop(pkg_id, None)
    _BUILD_JOBS[pkg_id] = {"status": "building", "t0": time.time()}
    threading.Thread(target=_run_build, args=(pkg_id,), daemon=True).start()
    return {"status": "building"}


def _read_meta(pkg_id: str) -> dict:
    try:
        return json.loads(_meta_path(pkg_id).read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_status(pkg_id: str) -> dict | None:
    """None -> unknown package. Else {status, counts?, elapsedMs?, reconciled, error?}."""
    if not (_dir(pkg_id) / ".extracted").exists():
        return None
    reconciled = _merged_path(pkg_id).exists()
    job = _BUILD_JOBS.get(pkg_id)
    if _model_path(pkg_id).exists():
        out = {"status": "ready", "reconciled": reconciled, **_read_meta(pkg_id)}
        return out
    if job:
        out = {"status": job["status"], "reconciled": reconciled}
        if job["status"] == "error":
            out["error"] = job.get("error")
        return out
    return {"status": "absent", "reconciled": False}


# ----------------------------------------------------------------- serve / query
def _active_model(pkg_id: str) -> dict | None:
    """Reconciled-merged model if present, else the base schema model. Cached by mtime."""
    path = _merged_path(pkg_id) if _merged_path(pkg_id).exists() else _model_path(pkg_id)
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    cached = _LOADED.get(pkg_id)
    if cached and cached[0] == mtime:
        return cached[1]
    model = json.loads(path.read_text(encoding="utf-8"))
    # the reconciled/merged model is built from the DPM Excel and lacks the Arelle-derived
    # extras (enumerations, dimension members/defaults, namespaces); carry them over from the
    # base schema model so enum/member dropdowns + instance build still work.
    if path == _merged_path(pkg_id) and _model_path(pkg_id).exists():
        try:
            base = json.loads(_model_path(pkg_id).read_text(encoding="utf-8"))
            for key in ("enumerations", "dim_members", "dim_defaults", "namespaces"):
                if not model.get(key) and base.get(key):
                    model[key] = base[key]
        except Exception:
            pass
    _LOADED[pkg_id] = (mtime, model)
    return model


def _section_rows(model: dict, section: str) -> list[dict]:
    if section == "members":
        rows = []
        for mems in model.get("members", {}).values():
            rows.extend(mems)
        return rows
    return [{"code": code, **entry} for code, entry in model.get(section, {}).items()]


def query(pkg_id: str, section: str, q: str = "", page: int = 1, page_size: int = 50,
          scope_codes: dict | None = None) -> dict | None:
    """Paginated/searchable rows for a section. None -> model not ready.

    scope_codes (optional): {metrics,dimensions,domains,members} -> sets of codes/qnames; rows
    are filtered to that section's set (used to scope the dictionary to a framework/entry-point).
    """
    if section not in ("metrics", "dimensions", "domains", "members"):
        raise ValueError("section must be metrics|dimensions|domains|members")
    model = _active_model(pkg_id)
    if model is None:
        return None
    rows = _section_rows(model, section)
    if scope_codes is not None:
        allowed = scope_codes.get(section) or set()
        if section in ("dimensions", "members"):
            rows = [r for r in rows if r.get("qname") in allowed]
        else:  # metrics, domains -> keyed by code
            rows = [r for r in rows if r.get("code") in allowed]
    if q:
        ql = q.strip().lower()
        rows = [r for r in rows
                if ql in str(r.get("code", "")).lower()
                or ql in str(r.get("label", "")).lower()
                or ql in str(r.get("qname", "")).lower()]
    rows.sort(key=lambda r: str(r.get("qname") or r.get("code") or ""))
    total = len(rows)
    page = max(1, page)
    start = (page - 1) * page_size
    return {
        "section": section,
        "total": total,
        "page": page,
        "pageSize": page_size,
        "reconciled": _merged_path(pkg_id).exists(),
        "rows": rows[start:start + page_size],
    }


# --------------------------------------------------------------------- reconcile
def _persist_reconcile(pkg_id: str, dict_path: str, report_base: dict) -> dict:
    """Reconcile the base model against a DPM-dictionary workbook; persist merged + report."""
    base = json.loads(_model_path(pkg_id).read_text(encoding="utf-8"))
    rec = reconcile.reconcile_with_excel(base, dict_path)
    _merged_path(pkg_id).write_text(json.dumps(rec["merged"], ensure_ascii=False), encoding="utf-8")
    report = {**report_base, "summary": rec["summary"], "diffs": rec["diffs"]}
    _reconcile_path(pkg_id).write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    _LOADED.pop(pkg_id, None)
    return report


def _reconcile_zip(pkg_id: str, data: bytes, filename: str, uploads: Path) -> dict:
    """A DPM pack zip = the DPM dictionary + the Annotated Templates workbooks.

    Extract, find the dictionary workbook (reconcile against it), and stash the Annotated
    Templates for the per-table view (Phase 1b).
    """
    dest = uploads / "dpm"
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    root = str(dest.resolve())
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for m in zf.infolist():
            if (dest / m.filename).resolve().as_posix().startswith(root.replace("\\", "/")):
                zf.extract(m, dest)

    xlsxs = [p for p in glob.glob(str(dest / "**" / "*.xlsx"), recursive=True)
             if not Path(p).name.startswith("~$")]
    if not xlsxs:
        raise ValueError("The zip contains no .xlsx workbooks.")

    dict_path = None
    templates = []
    for p in sorted(xlsxs):
        kind = reconcile.sniff_workbook(p)
        if kind == "dpm_dictionary" and dict_path is None:
            dict_path = p
        elif kind == "annotated_templates":
            templates.append(Path(p).name)
    if dict_path is None:
        raise ValueError("The zip has no DPM dictionary workbook "
                         "(a sheet set with Metrics/Dimensions/Domains).")

    return _persist_reconcile(pkg_id, dict_path, {
        "kind": "zip", "filename": filename,
        "dictionary": Path(dict_path).name,
        "annotatedTemplates": sorted(templates),
    })


def reconcile_upload(pkg_id: str, data: bytes, filename: str) -> dict:
    """Reconcile an uploaded DPM workbook (.xlsx) or DPM pack (.zip) against the model.

    Raises ValueError (-> 422) for unknown content or when the base model isn't built.
    """
    if not _model_path(pkg_id).exists():
        raise ValueError("Build the dictionary model first, then upload for reconciliation.")
    uploads = _dir(pkg_id) / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    if filename.lower().endswith(".zip"):
        return _reconcile_zip(pkg_id, data, filename, uploads)

    tmp = uploads / filename
    tmp.write_bytes(data)
    kind = reconcile.sniff_workbook(str(tmp))
    if kind == "annotated_templates":
        return {"kind": kind, "stashed": str(tmp),
                "message": "Annotated Templates stashed for the per-table view (Phase 1b)."}
    if kind != "dpm_dictionary":
        tmp.unlink(missing_ok=True)
        raise ValueError("Unrecognised file: expected a DPM dictionary / Annotated Templates "
                         ".xlsx, or a .zip DPM pack.")
    return _persist_reconcile(pkg_id, str(tmp), {"kind": kind, "filename": filename})


def get_reconcile_report(pkg_id: str) -> dict | None:
    if not _reconcile_path(pkg_id).exists():
        return None
    try:
        return json.loads(_reconcile_path(pkg_id).read_text(encoding="utf-8"))
    except Exception:
        return None
