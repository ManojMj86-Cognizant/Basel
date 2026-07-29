"""Per-package table index + per-table datapoints (Phase 1b).

Wraps the engine module `src/table_model.py` (parse the XBRL Table Linkbase `*-rend.xml`).
The table index (every table's code/framework/datapoint-count) is built once from the
extracted package (~6 s for ~286 tables) and cached to `<hash>/tables.json`; per-table
datapoints are parsed on demand (a single small file, milliseconds) and enriched with
labels/datatypes from the dictionary model.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

from . import config, model_store

if str(config.ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(config.ENGINE_DIR))
from src import table_model  # noqa: E402

# pkg_id -> {status: building|ready|error, t0, elapsedMs?, error?}
_INDEX_JOBS: dict[str, dict] = {}


def _dir(pkg_id: str) -> Path:
    return config.CACHE_DIR / pkg_id


def _index_path(pkg_id: str) -> Path:
    return _dir(pkg_id) / "tables.json"


# ----------------------------------------------------------------- index building
def _run_index(pkg_id: str) -> None:
    job = _INDEX_JOBS[pkg_id]
    try:
        tables = []
        for t in table_model.list_tables(str(_dir(pkg_id))):
            parsed = table_model.parse_table(t["path"])
            tables.append({
                "code": parsed["code"] or t["code"],
                "framework": t["framework"],
                "path": t["path"],
                "nDatapoints": parsed["n_datapoints"],
                "nOpenAxes": len(parsed["open_axes"]),
            })
        tables.sort(key=lambda x: x["code"])
        elapsed = round((time.time() - job["t0"]) * 1000)
        _index_path(pkg_id).write_text(
            json.dumps({"tables": tables, "elapsedMs": elapsed, "builtAt": time.time()},
                       ensure_ascii=False), encoding="utf-8")
        job["elapsedMs"] = elapsed
        job["status"] = "ready"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


def start_index(pkg_id: str, force: bool = False) -> dict:
    if not (_dir(pkg_id) / ".extracted").exists():
        return {"status": "error", "error": "Package not found / not extracted."}
    job = _INDEX_JOBS.get(pkg_id)
    if job and job["status"] == "building":
        return {"status": "building"}
    if _index_path(pkg_id).exists() and not force:
        return {"status": "ready", **_meta(pkg_id)}
    if force:
        _index_path(pkg_id).unlink(missing_ok=True)
    _INDEX_JOBS[pkg_id] = {"status": "building", "t0": time.time()}
    threading.Thread(target=_run_index, args=(pkg_id,), daemon=True).start()
    return {"status": "building"}


def _meta(pkg_id: str) -> dict:
    try:
        d = json.loads(_index_path(pkg_id).read_text(encoding="utf-8"))
        return {"count": len(d.get("tables", [])), "elapsedMs": d.get("elapsedMs")}
    except Exception:
        return {}


def index_status(pkg_id: str) -> dict | None:
    if not (_dir(pkg_id) / ".extracted").exists():
        return None
    if _index_path(pkg_id).exists():
        return {"status": "ready", **_meta(pkg_id)}
    job = _INDEX_JOBS.get(pkg_id)
    if job:
        out = {"status": job["status"]}
        if job["status"] == "error":
            out["error"] = job.get("error")
        return out
    return {"status": "absent"}


def _load_index(pkg_id: str) -> dict | None:
    if not _index_path(pkg_id).exists():
        return None
    return json.loads(_index_path(pkg_id).read_text(encoding="utf-8"))


def get_tables(pkg_id: str, allowed_codes: set | None = None) -> dict | None:
    """Tables grouped by framework (without the on-disk path). None -> index not built.

    allowed_codes (optional): restrict to this set of table codes (scope filter)."""
    idx = _load_index(pkg_id)
    if idx is None:
        return None
    by_fw: dict[str, list] = {}
    for t in idx["tables"]:
        if allowed_codes is not None and t["code"].upper() not in allowed_codes:
            continue
        by_fw.setdefault(t["framework"] or "(other)", []).append(
            {"code": t["code"], "nDatapoints": t["nDatapoints"], "nOpenAxes": t["nOpenAxes"]})
    frameworks = [{"framework": fw, "tables": ts, "nTables": len(ts),
                   "nDatapoints": sum(x["nDatapoints"] for x in ts)}
                  for fw, ts in sorted(by_fw.items())]
    return {
        "frameworks": frameworks,
        "nTables": sum(f["nTables"] for f in frameworks),
        "nDatapoints": sum(f["nDatapoints"] for f in frameworks),
    }


# -------------------------------------------------------------- per-table datapoints
def datapoints(pkg_id: str, code: str, page: int = 1, page_size: int = 50) -> dict | None:
    """Parse one table's datapoints, enrich from the dictionary model, paginate.

    None -> table index not built yet (poll status). Raises KeyError -> unknown table code.
    """
    idx = _load_index(pkg_id)
    if idx is None:
        return None
    entry = next((t for t in idx["tables"] if t["code"].upper() == code.upper()), None)
    if entry is None:
        raise KeyError(code)
    model = model_store._active_model(pkg_id)  # None if dictionary not built yet (labels blank)
    parsed = table_model.table_datapoints(entry["path"], model)
    rows = parsed.get("rows", [])
    total = len(rows)
    page = max(1, page)
    start = (page - 1) * page_size
    return {
        "code": parsed["code"],
        "framework": entry["framework"],
        "axes": parsed["axes"],
        "openAxes": parsed["open_axes"],
        "modelReady": model is not None,
        "total": total,
        "page": page,
        "pageSize": page_size,
        "rows": rows[start:start + page_size],
    }


def grid(pkg_id: str, code: str) -> dict | None:
    """The 2-D (x/y) + z-layer grid layout for a table. None -> index not built.

    Raises KeyError -> unknown table code.
    """
    idx = _load_index(pkg_id)
    if idx is None:
        return None
    entry = next((t for t in idx["tables"] if t["code"].upper() == code.upper()), None)
    if entry is None:
        raise KeyError(code)
    model = model_store._active_model(pkg_id)
    g = table_model.table_grid(entry["path"], model)
    g["framework"] = entry["framework"]
    g["modelReady"] = model is not None
    return g
