"""Package ingestion for Phase 0.

Responsibilities:
  * hash an uploaded taxonomy-package zip (SHA-256) -> stable package id
  * extract it once into a per-hash cache dir (idempotent; re-upload is instant)
  * parse META-INF/taxonomyPackage.xml -> name/version/publisher/entry points
  * derive frameworks from entry-point hrefs
  * attach prebuilt DPM model counts (per-package model build is deferred)

Heavy work (rule index, per-package DPM build) is intentionally NOT done here.

Extraction of a brand-new 56 MB package is slow (~4.5 min, thousands of small
files), so the upload endpoint does NOT block on it: `start_ingest` returns
immediately, either with a cache-hit summary or with an extraction *job* whose
progress the frontend polls via `job_status`.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path

from lxml import etree

from . import config

# Entry-point hrefs vary by taxonomy domain, e.g.
#   banking:   .../data/xbrl/fws/banking/<framework>/<date>/mod/<mod>.xsd
#   insurance: .../data/xbrl/md/fws/insurance/<framework>/<date>/mod/<mod>.xsd
# So parse generically as /fws/<domain>/<framework>/<date>/mod/.
_FW_RE = re.compile(r"/fws/([^/]+)/([^/]+)/([^/]+)/mod/", re.IGNORECASE)
_TP_NS = {"tp": "http://xbrl.org/2016/taxonomy-package"}

# In-memory registry of ingested packages this process knows about: id -> summary dict.
_REGISTRY: dict[str, dict] = {}

# In-flight / finished extraction jobs: pkg_id -> progress dict.
_JOBS: dict[str, dict] = {}


def _autobuild_model(pkg_id: str) -> None:
    """Fire-and-forget the per-package dictionary build (best-effort; never blocks ingest)."""
    try:
        from . import model_store
        model_store.start_build(pkg_id)
    except Exception:
        pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _find_manifest(root: Path) -> Path | None:
    # The manifest sits at the package root: <root>/<pkg-folder>/META-INF/taxonomyPackage.xml
    # (or, rarely, directly under <root>). Check those shallow spots first — a recursive
    # rglob over a 56 MB extracted tree (thousands of files) costs seconds on a cold
    # filesystem cache, which is exactly the launch-time delay we want to avoid.
    rel = Path("META-INF") / "taxonomyPackage.xml"
    if (root / rel).exists():
        return root / rel
    for sub in root.iterdir():
        if sub.is_dir() and (sub / rel).exists():
            return sub / rel
    hits = list(root.rglob("META-INF/taxonomyPackage.xml"))   # fallback: unknown layout
    return hits[0] if hits else None


def _marker_filename(dest: Path) -> str | None:
    """First line of the .extracted marker holds the original uploaded filename."""
    marker = dest / ".extracted"
    if not marker.exists():
        return None
    try:
        first = marker.read_text(encoding="utf-8").splitlines()
        return first[0] if first else None
    except Exception:
        return None


def _parse_manifest(manifest: Path) -> dict:
    tree = etree.parse(str(manifest))
    r = tree.getroot()

    def text(tag: str) -> str:
        el = r.find(f"tp:{tag}", _TP_NS)
        return el.text.strip() if el is not None and el.text else ""

    entry_points = []
    frameworks: dict[str, int] = {}
    for ep in r.findall(".//tp:entryPoint", _TP_NS):
        name_el = ep.find("tp:name", _TP_NS)
        desc_el = ep.find("tp:description", _TP_NS)
        doc_el = ep.find("tp:entryPointDocument", _TP_NS)
        href = doc_el.get("href") if doc_el is not None else ""
        m = _FW_RE.search(href or "")
        domain = m.group(1) if m else ""
        framework = m.group(2) if m else "(unknown)"
        version = m.group(3) if m else ""
        if framework != "(unknown)":
            frameworks[framework] = frameworks.get(framework, 0) + 1
        entry_points.append({
            "name": (name_el.text.strip() if name_el is not None and name_el.text else ""),
            "description": (desc_el.text.strip() if desc_el is not None and desc_el.text else ""),
            "domain": domain,
            "framework": framework,
            "frameworkVersion": version,
            "href": href or "",
        })

    return {
        "name": text("name"),
        "version": text("version"),
        "publisher": text("publisher"),
        "publicationDate": text("publicationDate"),
        "identifier": text("identifier"),
        "entryPoints": entry_points,
        "frameworks": dict(sorted(frameworks.items())),
        "entryPointCount": len(entry_points),
    }


def _model_counts(pkg_id: str) -> dict | None:
    """Per-package dictionary counts from the Arelle-built model (`<hash>/model.meta.json`).

    Returns None until *this* package's model is built, so the Ingest summary never shows
    another taxonomy's numbers (the prebuilt banking `dpm_model.json` is no longer used here).
    The Dictionary tab is the live source of truth.
    """
    meta = config.CACHE_DIR / pkg_id / "model.meta.json"
    if not meta.exists():
        return None
    try:
        counts = json.loads(meta.read_text(encoding="utf-8")).get("counts", {})
    except Exception:
        return None
    if not counts:
        return None
    return {
        "metrics": counts.get("metrics", 0),
        "dimensions": counts.get("dimensions", 0),
        "domains": counts.get("domains", 0),
        "members": counts.get("members", 0),
        "source": "this package (built via Arelle)",
    }


def _build_summary(
    pkg_id: str,
    filename: str | None,
    dest: Path,
    manifest: Path,
    *,
    cached: bool,
    fresh: bool = False,
    size_bytes: int | None = None,
    file_count: int | None = None,
    elapsed_ms: int = 0,
) -> dict:
    return {
        "id": pkg_id,
        "filename": filename,
        "sizeBytes": size_bytes,
        "cached": cached,            # True = already on disk (extraction skipped)
        "freshlyExtracted": fresh,   # True only for the response right after a real extract
        "fileCount": file_count,
        "extractedPath": str(dest),
        "elapsedMs": elapsed_ms,
        "package": _parse_manifest(manifest),
        "model": _model_counts(pkg_id),
    }


def _extract_with_progress(zip_bytes: bytes, dest: Path, job: dict) -> int:
    """Extract every member, updating job['extracted']/['total'] as we go."""
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        members = zf.infolist()
        job["total"] = sum(1 for m in members if not m.is_dir())
        dest_root = str(dest.resolve())
        for member in members:
            # guard against path traversal
            target = (dest / member.filename).resolve()
            if not str(target).startswith(dest_root):
                continue
            zf.extract(member, dest)
            if not member.is_dir():
                n += 1
                job["extracted"] = n
    return n


def _run_ingest_job(zip_bytes: bytes, filename: str, pkg_id: str) -> None:
    """Background-thread target: extract a new package and build its summary."""
    job = _JOBS[pkg_id]
    dest = config.CACHE_DIR / pkg_id
    try:
        file_count = _extract_with_progress(zip_bytes, dest, job)
        (dest / ".extracted").write_text(f"{filename}\n{file_count} files\n", encoding="utf-8")
        # keep the original zip so Arelle can validate generated instances offline (--packages)
        try:
            (dest / "source.zip").write_bytes(zip_bytes)
        except Exception:
            pass
        manifest = _find_manifest(dest)
        if manifest is None:
            raise ValueError("No META-INF/taxonomyPackage.xml found in the uploaded zip.")
        summary = _build_summary(
            pkg_id, filename, dest, manifest,
            cached=False, fresh=True, size_bytes=len(zip_bytes),
            file_count=file_count, elapsed_ms=round((time.time() - job["t0"]) * 1000),
        )
        _REGISTRY[pkg_id] = summary
        job["summary"] = summary
        job["status"] = "ready"
        _autobuild_model(pkg_id)            # kick off the dictionary build (auto after extract)
    except Exception as e:  # surface to the poller instead of crashing the thread silently
        job["status"] = "error"
        job["error"] = str(e)
        # leave a half-extracted dir behind? drop it so a retry re-extracts cleanly.
        shutil.rmtree(dest, ignore_errors=True)


def start_ingest(zip_bytes: bytes, filename: str) -> dict:
    """Hash the zip; return either a cache-hit summary or a started extraction job.

    Returns one of:
      {"status": "ready",      "summary": {...}}                  # cache hit (instant)
      {"status": "extracting", "jobId", "id", "filename", ...}    # new -> poll job_status
    """
    if not zip_bytes:
        raise ValueError("Uploaded file is empty.")
    pkg_id = _sha256(zip_bytes)
    dest = config.CACHE_DIR / pkg_id

    if (dest / ".extracted").exists():
        manifest = _find_manifest(dest)
        if manifest is None:
            raise ValueError("Cached package is missing its manifest; delete and re-upload.")
        summary = _build_summary(
            pkg_id, filename or _marker_filename(dest), dest, manifest,
            cached=True, size_bytes=len(zip_bytes),
        )
        _REGISTRY[pkg_id] = summary
        _autobuild_model(pkg_id)            # ensure the dictionary model exists for cache hits
        return {"status": "ready", "summary": summary}

    # New package: extract in the background; the frontend polls job_status(pkg_id).
    job = {
        "status": "extracting", "extracted": 0, "total": 0,
        "id": pkg_id, "filename": filename, "summary": None, "error": None,
        "t0": time.time(),
    }
    _JOBS[pkg_id] = job
    threading.Thread(
        target=_run_ingest_job, args=(zip_bytes, filename, pkg_id), daemon=True
    ).start()
    return {"status": "extracting", "jobId": pkg_id, "id": pkg_id,
            "filename": filename, "total": 0, "extracted": 0}


def job_status(job_id: str) -> dict | None:
    """Progress of an extraction job. None -> unknown job id (404)."""
    job = _JOBS.get(job_id)
    if job is None:
        # The job may already be done and only the persisted package remains.
        s = get(job_id)
        return {"status": "ready", "summary": s} if s is not None else None
    out = {"status": job["status"], "extracted": job["extracted"], "total": job["total"]}
    if job["status"] == "ready":
        out["summary"] = job["summary"]
    elif job["status"] == "error":
        out["error"] = job["error"]
    return out


def get(pkg_id: str) -> dict | None:
    """Return a known summary; rehydrate from the cache dir if this process forgot it.

    Anything returned here is by definition on disk, so it is reported as cached
    (and never `freshlyExtracted`) — that distinction belongs only to the immediate
    post-extraction response.
    """
    dest = config.CACHE_DIR / pkg_id
    if not (dest / ".extracted").exists():
        return None
    if pkg_id in _REGISTRY:
        s = dict(_REGISTRY[pkg_id])
        s["cached"] = True
        s["freshlyExtracted"] = False
        return s
    manifest = _find_manifest(dest)
    if manifest is None:
        return None
    summary = _build_summary(pkg_id, _marker_filename(dest), dest, manifest, cached=True)
    _REGISTRY[pkg_id] = summary
    return summary


def delete(pkg_id: str) -> tuple[bool, Path | None]:
    """Make a package disappear immediately, deferring the slow disk delete.

    Removing the extracted package = deleting thousands of small files (slow on Windows),
    so instead we *rename* the dir aside to `.trash-<id>` (atomic, instant) and forget it.
    The dir vanishes from listings at once; the caller purges the trash in the background.

    Returns (found, trash_path_to_purge). found=False -> unknown id (404).
    """
    dest = config.CACHE_DIR / pkg_id
    _REGISTRY.pop(pkg_id, None)
    _JOBS.pop(pkg_id, None)
    # confine to the cache dir (defend against a malformed id like '..')
    if dest.resolve().parent != config.CACHE_DIR.resolve() or not dest.exists():
        return False, None
    trash = config.CACHE_DIR / f".trash-{pkg_id}"
    if trash.exists():
        shutil.rmtree(trash, ignore_errors=True)
    try:
        dest.rename(trash)
        return True, trash
    except OSError:
        # rename failed (e.g. a file is locked) -> fall back to synchronous delete
        shutil.rmtree(dest, ignore_errors=True)
        return True, None


def purge(path: Path) -> None:
    """Background-task target: actually remove a trashed dir from disk."""
    shutil.rmtree(path, ignore_errors=True)


def purge_trash() -> None:
    """Sweep leftover `.trash-*` dirs from a previous run (best-effort, at startup)."""
    if not config.CACHE_DIR.exists():
        return
    for d in config.CACHE_DIR.iterdir():
        if d.is_dir() and d.name.startswith(".trash-"):
            shutil.rmtree(d, ignore_errors=True)


def _list_entry(d: Path) -> dict | None:
    """Lightweight dropdown entry {id, filename, name, version}, cached in <hash>/list.json.

    The package list only needs these four fields, but computing them via get() pays for a
    manifest search + full XML parse + model-count read every time. We cache them once so the
    dropdown loads instantly on launch (and across backend restarts)."""
    cache = d / "list.json"
    if cache.exists():
        try:
            e = json.loads(cache.read_text(encoding="utf-8"))
            if e.get("name"):
                return {"id": d.name, "filename": e.get("filename"),
                        "name": e["name"], "version": e.get("version", "")}
        except Exception:
            pass                              # corrupt cache -> fall through and rebuild
    s = get(d.name)                           # cold path: compute once, then cache
    if not s:
        return None
    entry = {"id": s["id"], "filename": s["filename"],
             "name": s["package"]["name"], "version": s["package"]["version"]}
    try:
        cache.write_text(json.dumps({"filename": entry["filename"], "name": entry["name"],
                                     "version": entry["version"]}, ensure_ascii=False),
                         encoding="utf-8")
    except Exception:
        pass                                  # cache is best-effort; never fail the list
    return entry


def list_packages() -> list[dict]:
    out = []
    for d in config.CACHE_DIR.iterdir() if config.CACHE_DIR.exists() else []:
        if d.name.startswith("."):          # skip .trash-* and other dotfiles
            continue
        if (d / ".extracted").exists():
            e = _list_entry(d)
            if e:
                out.append(e)
    return out
