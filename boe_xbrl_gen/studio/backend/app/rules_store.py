"""Per-module business (formula) validation rules, for the Validation Rules tab.

Wraps `src/rules_model.py` (parse the package's assertion sets + value rules — read-only, no
Arelle). Rules for a module are collected once (parsing its ~150 assertion sets can take a
little while for big modules like PRA001) and cached to `<hash>/rules-<module>.json`.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path

from . import config

if str(config.ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(config.ENGINE_DIR))
from src import instance_build, rules_model  # noqa: E402

# (pkg_id, module) -> {status, t0, elapsedMs?, error?}
_JOBS: dict[tuple[str, str], dict] = {}
_SAFE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _dir(pkg_id: str) -> Path:
    return config.CACHE_DIR / pkg_id


def _rules_path(pkg_id: str, module: str) -> Path:
    return _dir(pkg_id) / f"rules-{module}.json"


def modules(pkg_id: str) -> list[dict]:
    """Distinct modules in the package + framework + table count (for the module selector)."""
    idx = instance_build.module_index(str(_dir(pkg_id)))
    mods: dict[str, dict] = {}
    for table, infos in idx.items():
        for info in infos:
            m = mods.setdefault(info["module"],
                                {"module": info["module"], "framework": info["framework"], "nTables": 0})
            m["nTables"] += 1
    return sorted(mods.values(), key=lambda x: x["module"])


def _run(pkg_id: str, module: str) -> None:
    job = _JOBS[(pkg_id, module)]
    try:
        out = rules_model.collect_module_rules(str(_dir(pkg_id)), module)
        out["builtAt"] = time.time()
        out["elapsedMs"] = round((time.time() - job["t0"]) * 1000)
        _rules_path(pkg_id, module).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        job["elapsedMs"] = out["elapsedMs"]
        job["status"] = "ready"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


def start_build(pkg_id: str, module: str, force: bool = False) -> dict:
    if not _SAFE.match(module):
        return {"status": "error", "error": "bad module name"}
    if not (_dir(pkg_id) / ".extracted").exists():
        return {"status": "error", "error": "Package not found / not extracted."}
    job = _JOBS.get((pkg_id, module))
    if job and job["status"] == "building":
        return {"status": "building"}
    if _rules_path(pkg_id, module).exists() and not force:
        return {"status": "ready", **_meta(pkg_id, module)}
    if force:
        _rules_path(pkg_id, module).unlink(missing_ok=True)
    _JOBS[(pkg_id, module)] = {"status": "building", "t0": time.time()}
    threading.Thread(target=_run, args=(pkg_id, module), daemon=True).start()
    return {"status": "building"}


def _meta(pkg_id: str, module: str) -> dict:
    try:
        d = json.loads(_rules_path(pkg_id, module).read_text(encoding="utf-8"))
        return {"nRules": d.get("nRules", 0), "elapsedMs": d.get("elapsedMs")}
    except Exception:
        return {}


def status(pkg_id: str, module: str) -> dict:
    if _rules_path(pkg_id, module).exists():
        return {"status": "ready", **_meta(pkg_id, module)}
    job = _JOBS.get((pkg_id, module))
    if job:
        out = {"status": job["status"]}
        if job["status"] == "error":
            out["error"] = job.get("error")
        return out
    return {"status": "absent"}


def query(pkg_id: str, module: str, q: str = "", table: str = "",
          page: int = 1, page_size: int = 50) -> dict | None:
    """Paginated/searchable rules for a module. None -> not built yet (poll status)."""
    p = _rules_path(pkg_id, module)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    rules = data.get("rules", [])
    ql = q.lower().strip()
    tu = table.upper().strip()
    if ql:
        rules = [r for r in rules
                 if ql in r["id"].lower() or ql in (r.get("message") or "").lower()
                 or ql in (r.get("test") or "").lower()]
    if tu:
        rules = [r for r in rules if any(tu in t for t in r.get("tables", []))]
    total = len(rules)
    page = max(1, page)
    start = (page - 1) * page_size
    return {
        "module": module, "total": total, "nRulesModule": data.get("nRules", 0),
        "page": page, "pageSize": page_size, "rules": rules[start:start + page_size],
    }
