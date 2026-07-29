"""Hypercube extraction — learn each table's **valid dimensional cells**, once, cached.

A workbook cell ref `(table, r, c)` under-specifies the full dimensional context; the naive
row×col×z cartesian over-generates invalid (greyed) cells. The valid-cell set is cached per
package+module (`<hash>/hypercube-<module>.json`) as `{module, tables, cells:[ "concept|dim=mem,…" ]}`,
and generation then emits only valid cells (no `dimInvalid`).

Two extractors produce the identical cache:
  * `_run` (DEFAULT, offline) — resolves each table's definition linkbase (`<table>-def.xml`)
    dimensional relationship set in-process via `src/dim_drs.py`; ~40 s for PRA001. Verified to
    match Arelle exactly (0 disagreements over the 61,498-fact official PRA001 sample).
  * `_run_arelle` (fallback/parity) — the original authority: build the cartesian, let Arelle flag
    `xbrldie:PrimaryItemDimensionallyInvalid`, record the rest. Correct but slow (PRA001 ~46 min).
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

from lxml import etree

from . import config, instance_store, model_store, table_store

if str(config.ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(config.ENGINE_DIR))
from src import dim_drs, instance_build  # noqa: E402

_XBRLI = "http://www.xbrl.org/2003/instance"
_XBRLDI = "http://xbrl.org/2006/xbrldi"
_JOBS: dict[str, dict] = {}


def _dir(pkg_id: str) -> Path:
    return config.CACHE_DIR / pkg_id


def _hc_path(pkg_id: str, module: str) -> Path:
    return _dir(pkg_id) / f"hypercube-{module}.json"


def _cell_key(concept: str, dims: dict) -> str:
    """Stable key 'localname|dimlocal=memlocal,...' (local names)."""
    def loc(s):
        return s.rsplit("}", 1)[-1].split(":")[-1] if s else s
    parts = ",".join(f"{loc(d)}={loc(m)}" for d, m in sorted(dims.items()))
    return f"{loc(concept)}|{parts}"


def cell_key(concept: str, dims: dict, defaults: dict | None = None) -> str:
    """Key for a datapoint, dropping default members first so it matches a built instance's
    context (build omits dimension defaults). Use this on BOTH sides for consistent matching."""
    defaults = defaults or {}
    clean = {d: m for d, m in (dims or {}).items() if defaults.get(d) != m}
    return _cell_key(concept, clean)


def module_tables(pkg_id: str, module: str) -> list:
    idx = instance_build.module_index(str(_dir(pkg_id)))
    return sorted({t for t, infos in idx.items() for i in infos if i["module"] == module})


def _cartesian_selection(pkg_id: str, tables: list) -> dict:
    """Full row×col×z cartesian per table (datatype-random values; we only need the cells)."""
    sel: dict = {}
    for t in tables:
        try:
            g = table_store.grid(pkg_id, t)
        except Exception:
            g = None
        if not g:
            continue
        cols = g["columns"] or [{"concept": None, "dims": {}}]
        rows = g["rows"] or [{"concept": None, "dims": {}}]
        zs = g["zPositions"]
        zlen = len(zs) if len(zs) > 1 else 1
        dps = []
        for z in range(zlen):
            zp = zs[z] if len(zs) > 1 else (zs[0] if zs else None)
            for r in rows:
                for c in cols:
                    concept = r.get("concept") or c.get("concept") or (zp or {}).get("concept")
                    if not concept:
                        continue
                    dt = r.get("datatype") or c.get("datatype") or (zp or {}).get("datatype")
                    dims = {**((zp or {}).get("dims") or {}), **r.get("dims", {}), **c.get("dims", {})}
                    dps.append({"concept": concept, "dims": dims, "datatype": dt,
                                "value": instance_build.gen_value(dt, None), "table": t.upper()})
        if dps:
            sel[t] = dps
    return sel


def _ctx_dims(xml_bytes: bytes) -> dict:
    """{contextId -> {dimQname-local -> memberQname-local}} from a built instance."""
    body = xml_bytes[3:] if xml_bytes[:3] == b"\xef\xbb\xbf" else xml_bytes
    root = etree.fromstring(body)
    out: dict = {}
    for ctx in root.findall(f"{{{_XBRLI}}}context"):
        cid = ctx.get("id")
        dims = {}
        scen = ctx.find(f"{{{_XBRLI}}}scenario")
        if scen is not None:
            for em in scen:
                dim = em.get("dimension")
                if dim is None:
                    continue
                d = dim.split(":")[-1]
                if etree.QName(em).localname == "explicitMember":
                    dims[d] = (em.text or "").split(":")[-1]
                else:  # typedMember
                    child = next(iter(em), None)
                    dims[d] = (child.text or "") if child is not None else ""
        out[cid] = dims
    return out


def _offline_valid_cells(pkg_id: str, tables: list, defaults: dict, job: dict | None = None) -> dict:
    """Derive each table's valid dimensional cells from its `<table>-def.xml` (offline DRS) —
    the fast replacement for the Arelle round-trip. Builds the same row×col×z cartesian, then
    keeps a cell iff its `(metric, dims)` is dimensionally valid per the table's closed hypercubes.

    Returns {"cells": sorted-keys, "facts": n_total, "invalid": n_dropped, "noDef": [tables]}.
    Keys are produced with `cell_key` (default-dropped, local) — identical to the Arelle path and
    to what `genvalid_store` tests membership against.
    """
    ext = str(_dir(pkg_id))
    defaults_local = dim_drs.localize_defaults(defaults)
    sel = _cartesian_selection(pkg_id, tables)
    valid: set = set()
    n_total = n_invalid = 0
    no_def: list = []
    for t, dps in sel.items():
        if job is not None:
            job["phase"] = f"offline DRS: {t} ({len(dps)} cells)…"
        def_path = dim_drs.def_path_for(ext, t)
        drs = dim_drs.TableDRS(def_path) if def_path else None
        if drs is None:
            no_def.append(t)                       # flat table (no dimensions) — every cell valid
        for dp in dps:
            n_total += 1
            if drs is not None:
                dims_local = dim_drs.localize_dims(dp.get("dims") or {}, defaults)
                if not drs.is_valid(dim_drs.local(dp["concept"]), dims_local, defaults_local):
                    n_invalid += 1
                    continue
            valid.add(cell_key(dp["concept"], dp.get("dims") or {}, defaults))
    return {"cells": sorted(valid), "facts": n_total, "invalid": n_invalid, "noDef": no_def}


def _run(pkg_id: str, module: str) -> None:
    """Offline DRS extraction (default). Parses each table's definition linkbase instead of
    asking Arelle — seconds instead of ~46 min for PRA001. Output JSON is byte-compatible with
    the Arelle path (`_run_arelle`), which remains available for parity checks."""
    job = _JOBS[pkg_id]
    try:
        tables = module_tables(pkg_id, module)
        if not tables:
            raise RuntimeError(f"No tables for module '{module}'.")
        model = model_store._active_model(pkg_id) or {}
        defaults = model.get("dim_defaults", {})
        job["phase"] = f"offline DRS for {module} ({len(tables)} tables)…"
        res = _offline_valid_cells(pkg_id, tables, defaults, job)
        out = {"module": module, "tables": tables, "cells": res["cells"]}
        _hc_path(pkg_id, module).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        job.update({"status": "ready", "module": module, "tables": len(tables), "method": "offline",
                    "validCells": len(res["cells"]), "facts": res["facts"], "invalid": res["invalid"],
                    "noDef": res["noDef"], "elapsedMs": round((time.time() - job["t0"]) * 1000)})
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


def _run_arelle(pkg_id: str, module: str) -> None:
    job = _JOBS[pkg_id]
    try:
        tables = module_tables(pkg_id, module)
        if not tables:
            raise RuntimeError(f"No tables for module '{module}'.")
        model = model_store._active_model(pkg_id) or {}
        zip_path = instance_store.source_zip(pkg_id)
        if not zip_path:
            raise RuntimeError("Package source zip not cached.")
        job["phase"] = f"building cartesian for {module} ({len(tables)} tables)…"
        sel = _cartesian_selection(pkg_id, tables)
        built = instance_build.build_instances(str(_dir(pkg_id)), model, sel, {})
        valid: set = set()             # module-level set of valid cell keys (default-dropped, local)
        n_total = n_invalid = 0
        for inst in built["instances"]:
            xml = inst["xml"]
            job["phase"] = f"Arelle validating {inst['module']}…"
            report = instance_build.parse_report(instance_build.validate(xml, zip_path))
            ctxd = _ctx_dims(xml)       # context dims already have defaults dropped (build omits them)
            invalid = {(d["fact"].split(":")[-1], d["context"]) for d in report["dimInvalid"]}
            body = xml[3:] if xml[:3] == b"\xef\xbb\xbf" else xml
            root = etree.fromstring(body)
            for el in root:
                cref = el.get("contextRef")
                if cref is None:
                    continue
                local = etree.QName(el).localname
                n_total += 1
                if (local, cref) in invalid:
                    n_invalid += 1
                    continue
                valid.add(_cell_key(local, ctxd.get(cref, {})))
        out = {"module": module, "tables": tables, "cells": sorted(valid)}
        _hc_path(pkg_id, module).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        job.update({"status": "ready", "module": module, "tables": len(tables), "method": "arelle",
                    "validCells": len(valid), "facts": n_total, "invalid": n_invalid,
                    "elapsedMs": round((time.time() - job["t0"]) * 1000)})
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


def start(pkg_id: str, module: str) -> dict:
    if not (_dir(pkg_id) / ".extracted").exists():
        return {"status": "error", "error": "Package not found / not extracted."}
    job = _JOBS.get(pkg_id)
    if job and job["status"] == "building":
        return {"status": "building"}
    _JOBS[pkg_id] = {"status": "building", "t0": time.time(), "module": module}
    threading.Thread(target=_run, args=(pkg_id, module), daemon=True).start()
    return {"status": "building", "module": module}


def status(pkg_id: str) -> dict:
    job = _JOBS.get(pkg_id)
    if job:
        keys = ("status", "module", "tables", "validCells", "facts", "invalid",
                "method", "noDef", "elapsedMs", "error", "phase")
        return {k: job[k] for k in keys if k in job}
    return {"status": "absent"}


def valid_cells(pkg_id: str, module: str) -> set | None:
    """Module-level set of valid cell keys from cache, or None if not extracted yet."""
    p = _hc_path(pkg_id, module)
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    return set(raw.get("cells", []))
