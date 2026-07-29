"""Generate downloadable XBRL instances for selected tables (Phase 2 — Generate/Create).

**Build only** — assembles one instance per module from the package + the DPM model + the
posted datapoint values (no sample needed) and returns them immediately. There is NO Arelle here:
validation is a separate, async step (see `validate_store.py` / the Validation tab), so a slow or
failing Arelle run can never block or mask generation. Built files are cached under
`<hash>/generated/`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import config, model_store

if str(config.ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(config.ENGINE_DIR))
from src import instance_build  # noqa: E402


def _dir(pkg_id: str) -> Path:
    return config.CACHE_DIR / pkg_id


def _gen_dir(pkg_id: str) -> Path:
    return _dir(pkg_id) / "generated"


def source_zip(pkg_id: str) -> str | None:
    p = _dir(pkg_id) / "source.zip"
    return str(p) if p.exists() else None


def generate(pkg_id: str, selection: dict, opts: dict) -> dict:
    """Build instance(s) for the selected tables and write them to the cache. Synchronous +
    fast (no Arelle). Raises ValueError for bad input; per-module build errors are reported,
    not fatal."""
    if not (_dir(pkg_id) / ".extracted").exists():
        raise ValueError("Package not found / not extracted.")
    if not selection:
        raise ValueError("No tables/values supplied.")
    model = model_store._active_model(pkg_id)
    if model is None:
        raise ValueError("Dictionary model not built yet; open the Dictionary tab first.")

    built = instance_build.build_instances(str(_dir(pkg_id)), model, selection, opts)
    gen = _gen_dir(pkg_id)
    gen.mkdir(parents=True, exist_ok=True)
    results = []
    for inst in built["instances"]:
        (gen / inst["filename"]).write_bytes(inst["xml"])
        results.append({
            "filename": inst["filename"], "module": inst["module"],
            "framework": inst["framework"], "schemaRef": inst["schemaRef"],
            "tables": inst["tables"], "facts": inst["facts"], "contexts": inst["contexts"],
        })
    result = {
        "instances": results,
        "unmapped": built.get("unmapped", []),
        "errors": built.get("errors", []),
        "opts": {"lei": opts.get("lei") or instance_build.DEFAULT_LEI,
                 "date": opts.get("date") or instance_build.DEFAULT_DATE},
    }
    (gen / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def last_result(pkg_id: str) -> dict | None:
    rp = _gen_dir(pkg_id) / "result.json"
    return json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else None


def list_generated(pkg_id: str) -> list[str]:
    gen = _gen_dir(pkg_id)
    if not gen.exists():
        return []
    return sorted(p.name for p in gen.glob("*.xbrl"))


def get_file(pkg_id: str, filename: str) -> Path | None:
    name = Path(filename).name                       # basename guard against traversal
    p = _gen_dir(pkg_id) / name
    return p if p.exists() else None
