"""Bind an uploaded XBRL **instance** to the table grids (Phase 2 — Section C).

The user uploads an `.xbrl` for the selected package; we parse it (engine `instance.py`), build a
fact index keyed by (metric code, {dimension code → member code}) with dimension *defaults*
dropped (instances omit them), and resolve the instance's module + reported tables from its
schemaRef + filing indicators. The Tables/Amend grids then fill each cell `(metric × row/col/z
members)` by looking up the same key. Editing writes the changed values **back into the uploaded
file** (preserving its entity/period/contexts/units) for download.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from . import config, model_store, table_store

if str(config.ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(config.ENGINE_DIR))
from src import instance as inst_mod  # noqa: E402
from src import instance_build, table_model  # noqa: E402

_FIND = "http://www.eurofiling.info/xbrl/ext/filing-indicators"
_LINK = "http://www.xbrl.org/2003/linkbase"
_XLINK = "http://www.w3.org/1999/xlink"


def _dir(pkg_id: str) -> Path:
    return config.CACHE_DIR / pkg_id


def _idir(pkg_id: str) -> Path:
    return _dir(pkg_id) / "instance"


def _local(clark_or_qname: str) -> str:
    s = clark_or_qname
    if "}" in s:
        return s.rsplit("}", 1)[-1]
    return s.split(":")[-1]


def _norm_dims_clark(dims: dict) -> dict:
    return {_local(d): _local(m) for d, m in dims.items()}


def _keystr(metric_local: str, dim_map: dict) -> str:
    return metric_local + "|" + ",".join(f"{d}={m}" for d, m in sorted(dim_map.items()))


# --------------------------------------------------------------------------- upload
def _module_and_tables(inst: "inst_mod.Instance", pkg_id: str) -> tuple[str, str, list]:
    """(module, framework, reported_tables) from schemaRef + filing indicators."""
    module, framework = "", ""
    ref = inst.root.find(f"{{{_LINK}}}schemaRef")
    if ref is not None:
        href = ref.get(f"{{{_XLINK}}}href", "")
        m = re.search(r"/mod/([^/]+)\.xsd$", href)
        if m:
            module = m.group(1)
    # filing-indicator template codes
    templates = []
    for fi in inst.root.iter(f"{{{_FIND}}}filingIndicator"):
        if fi.text and fi.text.strip():
            templates.append(fi.text.strip().upper())

    # reported tables = the module's tables whose code matches a filing-indicator template
    reported = []
    try:
        idx = instance_build.module_index(str(_dir(pkg_id)))
        mod_tables = {t for t, infos in idx.items()
                      for info in infos if info["module"] == module}
        for info in idx.values():
            for i in info:
                if i["module"] == module:
                    framework = i["framework"]
                    break
        for t in sorted(mod_tables):
            if any(t == tpl or t.startswith(tpl + ".") for tpl in templates) or not templates:
                reported.append(t)
    except Exception:
        pass
    return module, framework, reported


def upload(pkg_id: str, filename: str, data: bytes) -> dict:
    idir = _idir(pkg_id)
    idir.mkdir(parents=True, exist_ok=True)
    path = idir / "uploaded.xbrl"
    path.write_bytes(data)

    inst = inst_mod.Instance(str(path))
    index: dict[str, dict] = {}
    facts_rich: list[dict] = []
    n_typed = 0
    for fi, f in enumerate(inst.facts):
        # merge explicit members (local code) + typed values into one {dim_local -> value} map,
        # so closed AND open (typed) dimensions match uniformly
        dims = _norm_dims_clark(f.dims)
        if f.typed:
            n_typed += 1
            for d, val in f.typed.items():
                dims[_local(d)] = val if val is not None else ""
        metric = _local(f.concept)
        facts_rich.append({"fi": fi, "metric": metric, "dims": dims})
        index.setdefault(_keystr(metric, dims), {"value": f.value, "fi": fi})

    module, framework, reported = _module_and_tables(inst, pkg_id)
    meta = {
        "filename": filename, "module": module, "framework": framework,
        "tables": reported, "nFacts": len(inst.facts), "nTyped": n_typed,
        "nIndexed": len(index),
    }
    (idir / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    (idir / "facts.json").write_text(json.dumps(facts_rich, ensure_ascii=False), encoding="utf-8")
    (idir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


def info(pkg_id: str) -> dict | None:
    p = _idir(pkg_id) / "meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def clear(pkg_id: str) -> None:
    import shutil
    shutil.rmtree(_idir(pkg_id), ignore_errors=True)


def _index(pkg_id: str) -> dict | None:
    p = _idir(pkg_id) / "index.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _facts(pkg_id: str) -> list | None:
    p = _idir(pkg_id) / "facts.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _rend_path(pkg_id: str, code: str) -> str | None:
    for t in table_model.list_tables(str(_dir(pkg_id))):
        if t["code"].upper() == code.upper():
            return t["path"]
    return None


# --------------------------------------------- instance-expanded grid (handles OPEN axes)
def instance_grid(pkg_id: str, code: str) -> dict | None:
    """Frontend grid for a table, with OPEN axes expanded from the uploaded instance's facts
    (their typed/open-dimension values become the rows/cols), plus matched values per cell.
    None -> no instance uploaded; {building:True} -> table index still building."""
    index = _index(pkg_id)
    facts = _facts(pkg_id)
    if index is None or facts is None:
        return None
    base = table_store.grid(pkg_id, code)
    if base is None:
        return {"building": True}
    model = model_store._active_model(pkg_id) or {}
    defaults = model.get("dim_defaults", {})
    rend = _rend_path(pkg_id, code)
    parsed = table_model.parse_table(rend) if rend else {"open_axes": []}
    open_by_axis: dict[str, list] = {}
    for o in parsed.get("open_axes", []):
        open_by_axis.setdefault(o["axis"], []).append(o["dimension"])

    def closed_local(dimsq: dict) -> dict:
        return {_local(d): _local(m) for d, m in (dimsq or {}).items() if defaults.get(d) != m}

    metrics = {_local(p["concept"]) for ax in ("columns", "rows", "zPositions")
               for p in base[ax] if p.get("concept")}

    def open_positions(open_qnames: list) -> list:
        locals_ = [_local(d) for d in open_qnames]
        seen, out = set(), []
        for f in facts:
            if metrics and f["metric"] not in metrics:
                continue
            if not all(dl in f["dims"] for dl in locals_):
                continue
            t = tuple((dl, f["dims"][dl]) for dl in locals_)
            if t in seen:
                continue
            seen.add(t)
            out.append({"label": " · ".join(f"{dl}={v}" for dl, v in t),
                        "concept": None, "datatype": None, "dims": {}, "_key": dict(t)})
        return out

    axis_map = {"columns": "x", "rows": "y", "zPositions": "z"}
    grid_axes: dict[str, list] = {}
    for ax, akey in axis_map.items():
        closed = base[ax]
        oq = open_by_axis.get(akey)
        if not oq:
            grid_axes[ax] = [{**p, "_key": closed_local(p.get("dims", {}))} for p in closed]
            continue
        ops = open_positions(oq)
        if closed:
            merged = []
            for cp in closed:
                ck = closed_local(cp.get("dims", {}))
                for op in ops:
                    merged.append({
                        "label": (cp.get("label", "") + " · " + op["label"]) if cp.get("label") else op["label"],
                        "concept": cp.get("concept"), "datatype": cp.get("datatype"),
                        "enumValues": cp.get("enumValues"), "dims": cp.get("dims", {}),
                        "_key": {**ck, **op["_key"]}})
            grid_axes[ax] = merged
        else:
            grid_axes[ax] = ops

    cols = grid_axes["columns"] or [{"label": "Value", "concept": None, "dims": {}, "_key": {}}]
    rows = grid_axes["rows"] or [{"label": "(row)", "concept": None, "dims": {}, "_key": {}}]
    zs = grid_axes["zPositions"]
    zlen = len(zs) if len(zs) > 1 else 1

    values: dict[str, dict] = {}
    matched = 0
    for z in range(zlen):
        zp = zs[z] if len(zs) > 1 else (zs[0] if zs else None)
        for ri, r in enumerate(rows):
            for ci, c in enumerate(cols):
                concept = r.get("concept") or c.get("concept") or ((zp or {}).get("concept"))
                if not concept:
                    continue
                kd = {**((zp or {}).get("_key") or {}), **r.get("_key", {}), **c.get("_key", {})}
                hit = index.get(_keystr(_local(concept), kd))
                if hit:
                    values[f"{z}:{ri}:{ci}"] = hit
                    matched += 1

    def clean(ps):
        return [{k: v for k, v in p.items() if k != "_key"} for p in ps]

    return {
        "code": base.get("code", code), "framework": base.get("framework", ""),
        "axes": base.get("axes", {}),
        "modelReady": base.get("modelReady", False), "openAxes": base.get("openAxes", []),
        "columns": clean(grid_axes["columns"]), "rows": clean(grid_axes["rows"]),
        "zPositions": clean(grid_axes["zPositions"]),
        "values": values, "nMatched": matched,
    }


# ------------------------------------------------------------- per-table cell values
def table_values(pkg_id: str, code: str) -> dict | None:
    """{cellKey 'z:r:c' -> {value, fi}} for a table, matched against the uploaded instance.
    None -> no instance uploaded. Raises KeyError via table_store for an unknown table."""
    index = _index(pkg_id)
    if index is None:
        return None
    grid = table_store.grid(pkg_id, code)        # None if table index not built
    if grid is None:
        return {"building": True}
    model = model_store._active_model(pkg_id) or {}
    defaults = model.get("dim_defaults", {})      # dim_qname -> default member qname

    cols = grid["columns"] or [{"concept": None, "dims": {}}]
    rows = grid["rows"] or [{"concept": None, "dims": {}}]
    zs = grid["zPositions"]
    zlen = len(zs) if len(zs) > 1 else 1
    values: dict[str, dict] = {}
    matched = 0
    for z in range(zlen):
        zp = zs[z] if len(zs) > 1 else (zs[0] if zs else None)
        for ri, r in enumerate(rows):
            for ci, c in enumerate(cols):
                concept = r.get("concept") or c.get("concept") or ((zp or {}).get("concept"))
                if not concept:
                    continue
                dims = {**((zp or {}).get("dims") or {}), **r.get("dims", {}), **c.get("dims", {})}
                # drop dimension defaults (instances omit them), then normalize to local codes
                clean = {d: m for d, m in dims.items() if defaults.get(d) != m}
                key = _keystr(_local(concept), _norm_dims_clark(clean))
                hit = index.get(key)
                if hit:
                    values[f"{z}:{ri}:{ci}"] = hit
                    matched += 1
    return {"code": code, "values": values, "nMatched": matched}


# ------------------------------------------------------------------ save (write-back)
def save(pkg_id: str, edits: dict) -> bytes | None:
    """Apply {fi -> value} edits to the uploaded instance (in place) and return the bytes.
    None -> no instance uploaded."""
    path = _idir(pkg_id) / "uploaded.xbrl"
    if not path.exists():
        return None
    inst = inst_mod.Instance(str(path))
    for fi_str, val in (edits or {}).items():
        try:
            fi = int(fi_str)
        except (TypeError, ValueError):
            continue
        if 0 <= fi < len(inst.facts):
            inst.facts[fi].value = val
    out = _idir(pkg_id) / "edited.xbrl"
    inst.write(str(out))
    return out.read_bytes()
