"""Framework ▸ Entry-point (module) scope index, shared by the Dictionary / Tables / Rules tabs.

Built once per package (parses every table once, ~30 s, cached to `<hash>/scope.json`):
  - framework -> entry-points(modules) -> tables, plus the set of metric/dimension/domain/member
    codes each module's tables actually USE (so the Dictionary can be filtered to a scope).
Module mapping comes from `instance_build.module_index` (table -> modules, parsed from mod/*.xsd);
the used-concept sets come from `table_model.parse_table` datapoints.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

from . import config

if str(config.ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(config.ENGINE_DIR))
from src import instance_build, table_model  # noqa: E402

_JOBS: dict[str, dict] = {}


def _dir(pkg_id: str) -> Path:
    return config.CACHE_DIR / pkg_id


def _path(pkg_id: str) -> Path:
    return _dir(pkg_id) / "scope.json"


def _domain_of(member_qname: str) -> str:
    """member qname 'eba_BA:x17' -> domain code 'BA'; 'boe_eba_SC:x1' -> 'eba_SC'."""
    pfx = member_qname.split(":", 1)[0]
    return pfx.split("_", 1)[1] if "_" in pfx else pfx


def _run(pkg_id: str) -> None:
    job = _JOBS[pkg_id]
    try:
        extracted = str(_dir(pkg_id))
        idx = instance_build.module_index(extracted)          # TABLE -> [{module, framework, ...}]
        rend = {t["code"]: t["path"] for t in table_model.list_tables(extracted)}

        # per-table used sets (parse each table once)
        per_table: dict[str, dict] = {}
        for code, path in rend.items():
            mets, dims, doms, mems = set(), set(), set(), set()
            try:
                for dp in table_model.parse_table(path)["datapoints"]:
                    if dp.get("concept"):
                        mets.add(dp["concept"].split(":")[-1])
                    for d, m in (dp.get("dims") or {}).items():
                        dims.add(d)
                        if m:
                            mems.add(m)
                            doms.add(_domain_of(m))
            except Exception:
                pass
            per_table[code.upper()] = {"metrics": mets, "dimensions": dims,
                                       "domains": doms, "members": mems}

        # module -> {framework, tables, used sets}
        modules: dict[str, dict] = {}
        for table, infos in idx.items():
            tc = table.upper()
            used = per_table.get(tc, {})
            for info in infos:
                mod = modules.setdefault(info["module"], {
                    "framework": info["framework"], "tables": set(),
                    "metrics": set(), "dimensions": set(), "domains": set(), "members": set()})
                mod["tables"].add(tc)
                for k in ("metrics", "dimensions", "domains", "members"):
                    mod[k] |= used.get(k, set())

        # framework -> entry-points (with each module's table codes, for the Rules Table filter)
        fw_eps: dict[str, list] = {}
        for mod_name, mod in sorted(modules.items()):
            fw_eps.setdefault(mod["framework"], []).append(
                {"module": mod_name, "nTables": len(mod["tables"]),
                 "tables": sorted(mod["tables"])})
        frameworks = [{"framework": fw, "entryPoints": eps,
                       "nTables": sum(e["nTables"] for e in eps)}
                      for fw, eps in sorted(fw_eps.items())]

        out = {
            "frameworks": frameworks,
            "modules": {m: {"framework": d["framework"],
                            "tables": sorted(d["tables"]),
                            "metrics": sorted(d["metrics"]),
                            "dimensions": sorted(d["dimensions"]),
                            "domains": sorted(d["domains"]),
                            "members": sorted(d["members"])}
                        for m, d in modules.items()},
            "elapsedMs": round((time.time() - job["t0"]) * 1000),
            "builtAt": time.time(),
        }
        _path(pkg_id).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        job["status"] = "ready"
        job["elapsedMs"] = out["elapsedMs"]
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


def start_build(pkg_id: str, force: bool = False) -> dict:
    if not (_dir(pkg_id) / ".extracted").exists():
        return {"status": "error", "error": "Package not found / not extracted."}
    job = _JOBS.get(pkg_id)
    if job and job["status"] == "building":
        return {"status": "building"}
    if _path(pkg_id).exists() and not force:
        return {"status": "ready"}
    if force:
        _path(pkg_id).unlink(missing_ok=True)
    _JOBS[pkg_id] = {"status": "building", "t0": time.time()}
    threading.Thread(target=_run, args=(pkg_id,), daemon=True).start()
    return {"status": "building"}


def _load(pkg_id: str) -> dict | None:
    p = _path(pkg_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def status(pkg_id: str) -> dict:
    if _path(pkg_id).exists():
        return {"status": "ready"}
    job = _JOBS.get(pkg_id)
    if job:
        out = {"status": job["status"]}
        if job["status"] == "error":
            out["error"] = job.get("error")
        return out
    return {"status": "absent"}


def tree(pkg_id: str) -> dict | None:
    """The framework ▸ entry-point ▸ tables navigation tree (no used-sets). None -> not built.
    Reconstructed from `modules` so it works regardless of when scope.json was built."""
    data = _load(pkg_id)
    if data is None:
        return None
    fw_eps: dict[str, list] = {}
    for m, d in sorted(data["modules"].items()):
        fw_eps.setdefault(d["framework"], []).append(
            {"module": m, "nTables": len(d.get("tables", [])), "tables": d.get("tables", [])})
    frameworks = [{"framework": fw, "entryPoints": eps,
                   "nTables": sum(e["nTables"] for e in eps)}
                  for fw, eps in sorted(fw_eps.items())]
    return {"frameworks": frameworks}


def resolve_table(pkg_id: str, code: str) -> dict | None:
    """Find the primary module/framework for a table code (largest module containing it), so the
    Rules tab can pre-select Framework ▸ Entry-point ▸ Table. None -> not built / not found."""
    data = _load(pkg_id)
    if data is None:
        return None
    cu = code.upper()
    hits = [(m, d) for m, d in data["modules"].items() if cu in d.get("tables", [])]
    if not hits:
        return {"framework": "", "entryPoint": "", "table": cu, "found": False}
    m, d = max(hits, key=lambda md: len(md[1].get("tables", [])))
    return {"framework": d["framework"], "entryPoint": m, "table": cu, "found": True}


def _scope_modules(data: dict, framework: str, entry_point: str) -> list[str]:
    if entry_point:
        return [entry_point] if entry_point in data["modules"] else []
    if framework:
        return [m for m, d in data["modules"].items() if d["framework"] == framework]
    return list(data["modules"].keys())


def used_codes(pkg_id: str, framework: str = "", entry_point: str = "") -> dict | None:
    """Union of used {metrics,dimensions,domains,members} for a scope. None -> not built.
    Empty framework AND entry_point => None-as-{} meaning 'no filter' is signalled by the caller."""
    data = _load(pkg_id)
    if data is None:
        return None
    out = {"metrics": set(), "dimensions": set(), "domains": set(), "members": set()}
    for m in _scope_modules(data, framework, entry_point):
        d = data["modules"].get(m, {})
        for k in out:
            out[k].update(d.get(k, []))
    return {k: v for k, v in out.items()}


def tables_for(pkg_id: str, framework: str = "", entry_point: str = "") -> set | None:
    """Set of table codes (upper) in a scope. None -> not built."""
    data = _load(pkg_id)
    if data is None:
        return None
    codes: set = set()
    for m in _scope_modules(data, framework, entry_point):
        codes.update(data["modules"].get(m, {}).get("tables", []))
    return codes
