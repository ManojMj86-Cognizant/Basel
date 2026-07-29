"""Datapoint Studio API — Phase 0.

Endpoints:
  GET  /api/health             -> liveness + environment summary
  GET  /api/packages           -> list ingested packages (from cache)
  POST /api/package            -> upload a taxonomy zip; cache hit returns a summary,
                                  a new zip starts a background extraction job
  GET  /api/package/job/{id}   -> poll extraction progress for a started job
  GET  /api/package/{id}       -> return a known package summary
  DELETE /api/package/{id}     -> drop a cached package

Run (port 8201, no --reload; see CLAUDE.md for the Windows zombie-socket note):
  cd boe_xbrl_gen/studio/backend
  python -m uvicorn app.main:app --port 8201 --log-level warning
"""
from __future__ import annotations

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from fastapi import Body
from fastapi.responses import Response

from . import (config, genvalid_store, hypercube_store, instance_data_store, instance_store,
               model_store, package_store, rules_store, scope_store, solve_store, table_store,
               validate_store)

app = FastAPI(title="Datapoint Studio API", version="0.1.0")


@app.on_event("startup")
def _startup():
    package_store.purge_trash()  # remove any leftover .trash-* from a prior run

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.DEV_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "phase": 0,
        "modelPresent": config.MODEL_JSON.exists(),
        "cacheDir": str(config.CACHE_DIR),
    }


@app.get("/api/packages")
def list_packages():
    return {"packages": package_store.list_packages()}


@app.post("/api/package")
async def upload_package(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Please upload a .zip taxonomy package.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Uploaded file is empty.")
    try:
        return package_store.start_ingest(data, file.filename)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/package/job/{job_id}")
def package_job(job_id: str):
    status = package_store.job_status(job_id)
    if status is None:
        raise HTTPException(404, "Unknown extraction job id.")
    return status


@app.get("/api/package/{pkg_id}")
def get_package(pkg_id: str):
    summary = package_store.get(pkg_id)
    if summary is None:
        raise HTTPException(404, "Unknown package id (not in cache).")
    return summary


@app.delete("/api/package/{pkg_id}")
def delete_package(pkg_id: str, background_tasks: BackgroundTasks):
    found, trash = package_store.delete(pkg_id)
    if not found:
        raise HTTPException(404, "Unknown package id (not in cache).")
    if trash is not None:
        background_tasks.add_task(package_store.purge, trash)
    return {"deleted": pkg_id}


# --------------------------------------------------------------- Phase 1a: model
@app.post("/api/package/{pkg_id}/model/build")
def build_model(pkg_id: str, force: bool = Query(False)):
    status = model_store.start_build(pkg_id, force=force)
    if status.get("status") == "error" and "not found" in (status.get("error") or "").lower():
        raise HTTPException(404, status["error"])
    return status


@app.get("/api/package/{pkg_id}/model/status")
def model_status(pkg_id: str):
    status = model_store.build_status(pkg_id)
    if status is None:
        raise HTTPException(404, "Unknown package id (not in cache).")
    return status


def _scope_codes_or_425(pkg_id: str, framework: str, entryPoint: str):
    """None if no scope selected; else the used-codes dict. Raises 425 if scope still building."""
    if not framework and not entryPoint:
        return None
    codes = scope_store.used_codes(pkg_id, framework, entryPoint)
    if codes is None:
        scope_store.start_build(pkg_id)
        raise HTTPException(425, "Scope index is building; poll /scope/status.")
    return codes


@app.get("/api/package/{pkg_id}/model")
def get_model(pkg_id: str,
              section: str = Query("metrics"),
              q: str = Query(""),
              framework: str = Query(""),
              entryPoint: str = Query(""),
              page: int = Query(1, ge=1),
              pageSize: int = Query(50, ge=1, le=500)):
    if model_store.build_status(pkg_id) is None:
        raise HTTPException(404, "Unknown package id (not in cache).")
    scope_codes = _scope_codes_or_425(pkg_id, framework, entryPoint)
    try:
        result = model_store.query(pkg_id, section, q=q, page=page, page_size=pageSize,
                                   scope_codes=scope_codes)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if result is None:
        # model not built yet -> kick a build and tell the client to poll
        model_store.start_build(pkg_id)
        raise HTTPException(425, "Model is building; poll /model/status.")
    return result


@app.post("/api/package/{pkg_id}/model/reconcile")
async def reconcile_model(pkg_id: str, file: UploadFile = File(...)):
    if model_store.build_status(pkg_id) is None:
        raise HTTPException(404, "Unknown package id (not in cache).")
    fn = (file.filename or "").lower()
    if not (fn.endswith(".xlsx") or fn.endswith(".zip")):
        raise HTTPException(400, "Please upload a DPM workbook (.xlsx) or a DPM pack (.zip).")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Uploaded file is empty.")
    try:
        return model_store.reconcile_upload(pkg_id, data, file.filename)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/package/{pkg_id}/model/reconcile")
def get_reconcile(pkg_id: str):
    report = model_store.get_reconcile_report(pkg_id)
    if report is None:
        raise HTTPException(404, "No reconciliation has been run for this package.")
    return report


# --------------------------------------------------- Phase 1b: tables / datapoints
@app.post("/api/package/{pkg_id}/tables/build")
def build_tables(pkg_id: str, force: bool = Query(False)):
    status = table_store.start_index(pkg_id, force=force)
    if status.get("status") == "error" and "not found" in (status.get("error") or "").lower():
        raise HTTPException(404, status["error"])
    return status


@app.get("/api/package/{pkg_id}/tables/status")
def tables_status(pkg_id: str):
    status = table_store.index_status(pkg_id)
    if status is None:
        raise HTTPException(404, "Unknown package id (not in cache).")
    return status


@app.get("/api/package/{pkg_id}/tables")
def get_tables(pkg_id: str, framework: str = Query(""), entryPoint: str = Query("")):
    if table_store.index_status(pkg_id) is None:
        raise HTTPException(404, "Unknown package id (not in cache).")
    allowed = None
    if framework or entryPoint:
        allowed = scope_store.tables_for(pkg_id, framework, entryPoint)
        if allowed is None:
            scope_store.start_build(pkg_id)
            raise HTTPException(425, "Scope index is building; poll /scope/status.")
    result = table_store.get_tables(pkg_id, allowed_codes=allowed)
    if result is None:
        table_store.start_index(pkg_id)
        raise HTTPException(425, "Table index is building; poll /tables/status.")
    return result


# -------------------------------------------------- scope (framework ▸ entry-point) for tabs
@app.post("/api/package/{pkg_id}/scope/build")
def scope_build(pkg_id: str, force: bool = Query(False)):
    res = scope_store.start_build(pkg_id, force=force)
    if res.get("status") == "error":
        raise HTTPException(404, res.get("error", "Could not start scope build."))
    return res


@app.get("/api/package/{pkg_id}/scope/status")
def scope_status(pkg_id: str):
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    return scope_store.status(pkg_id)


@app.get("/api/package/{pkg_id}/scope")
def get_scope(pkg_id: str):
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    t = scope_store.tree(pkg_id)
    if t is None:
        scope_store.start_build(pkg_id)
        raise HTTPException(425, "Scope index is building; poll /scope/status.")
    return t


@app.post("/api/package/{pkg_id}/instance")
async def upload_instance(pkg_id: str, file: UploadFile = File(...)):
    """Upload an XBRL instance for the selected package; parse + index its facts."""
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    fn = (file.filename or "").lower()
    if not (fn.endswith(".xbrl") or fn.endswith(".xml")):
        raise HTTPException(400, "Please upload an XBRL instance (.xbrl).")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Uploaded file is empty.")
    try:
        return instance_data_store.upload(pkg_id, file.filename, data)
    except Exception as e:
        raise HTTPException(422, f"Could not parse instance: {e}")


@app.get("/api/package/{pkg_id}/instance")
def instance_info(pkg_id: str):
    inf = instance_data_store.info(pkg_id)
    if inf is None:
        raise HTTPException(404, "No instance uploaded for this package.")
    return inf


@app.delete("/api/package/{pkg_id}/instance")
def instance_clear(pkg_id: str):
    instance_data_store.clear(pkg_id)
    return {"status": "cleared"}


@app.get("/api/package/{pkg_id}/instance/values/{code}")
def instance_values(pkg_id: str, code: str):
    try:
        res = instance_data_store.table_values(pkg_id, code)
    except KeyError:
        raise HTTPException(404, f"Unknown table code: {code}")
    if res is None:
        raise HTTPException(404, "No instance uploaded for this package.")
    if res.get("building"):
        table_store.start_index(pkg_id)
        raise HTTPException(425, "Table index is building; poll /tables/status.")
    return res


@app.get("/api/package/{pkg_id}/instance/grid/{code}")
def instance_grid(pkg_id: str, code: str):
    try:
        res = instance_data_store.instance_grid(pkg_id, code)
    except KeyError:
        raise HTTPException(404, f"Unknown table code: {code}")
    if res is None:
        raise HTTPException(404, "No instance uploaded for this package.")
    if res.get("building"):
        table_store.start_index(pkg_id)
        raise HTTPException(425, "Table index is building; poll /tables/status.")
    return res


@app.post("/api/package/{pkg_id}/instance/save")
def instance_save(pkg_id: str, payload: dict = Body(...)):
    data = instance_data_store.save(pkg_id, payload.get("edits") or {})
    if data is None:
        raise HTTPException(404, "No instance uploaded for this package.")
    name = (instance_data_store.info(pkg_id) or {}).get("filename") or "edited.xbrl"
    if not name.lower().endswith(".xbrl"):
        name = "edited.xbrl"
    return Response(content=data, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/package/{pkg_id}/scope/resolve")
def scope_resolve(pkg_id: str, table: str = Query(...)):
    """Resolve a table code -> {framework, entryPoint, table} (its primary module), so 'View
    related rules' can pre-select the Rules tab's Framework ▸ Entry-point ▸ Table."""
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    res = scope_store.resolve_table(pkg_id, table)
    if res is None:
        scope_store.start_build(pkg_id)
        raise HTTPException(425, "Scope index is building; poll /scope/status.")
    return res


@app.get("/api/package/{pkg_id}/tables/{code}/datapoints")
def table_datapoints(pkg_id: str, code: str,
                     page: int = Query(1, ge=1),
                     pageSize: int = Query(50, ge=1, le=500)):
    if table_store.index_status(pkg_id) is None:
        raise HTTPException(404, "Unknown package id (not in cache).")
    try:
        result = table_store.datapoints(pkg_id, code, page=page, page_size=pageSize)
    except KeyError:
        raise HTTPException(404, f"Unknown table code: {code}")
    if result is None:
        table_store.start_index(pkg_id)
        raise HTTPException(425, "Table index is building; poll /tables/status.")
    return result


@app.get("/api/package/{pkg_id}/tables/{code}/grid")
def table_grid(pkg_id: str, code: str):
    if table_store.index_status(pkg_id) is None:
        raise HTTPException(404, "Unknown package id (not in cache).")
    try:
        result = table_store.grid(pkg_id, code)
    except KeyError:
        raise HTTPException(404, f"Unknown table code: {code}")
    if result is None:
        table_store.start_index(pkg_id)
        raise HTTPException(425, "Table index is building; poll /tables/status.")
    return result


# ----------------------------------------------------------- Phase 2: generate (build only)
@app.post("/api/package/{pkg_id}/generate")
def generate_instance(pkg_id: str, payload: dict = Body(...)):
    """Build downloadable XBRL instance(s) for the selected tables. Build only (no Arelle) —
    returns immediately. Body: { selection: {CODE:[{concept,dims,datatype,value}]}, lei?, date? }"""
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    selection = payload.get("selection") or {}
    opts = {k: payload.get(k) for k in ("lei", "scheme", "date") if payload.get(k)}
    try:
        return instance_store.generate(pkg_id, selection, opts)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Build failed: {e}")


@app.get("/api/package/{pkg_id}/generate/file/{filename}")
def generate_file(pkg_id: str, filename: str):
    p = instance_store.get_file(pkg_id, filename)
    if p is None:
        raise HTTPException(404, "Generated file not found; (re)generate first.")
    return Response(
        content=p.read_bytes(), media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{p.name}"'})


# ----------------------------------------------------------- Phase 2: validate (separate, async)
@app.get("/api/package/{pkg_id}/validate/files")
def validate_files(pkg_id: str):
    """Files available to validate: generated instances + the uploaded instance (if any)."""
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    files = [{"filename": f, "source": "generated"} for f in instance_store.list_generated(pkg_id)]
    up = instance_data_store.info(pkg_id)
    if up:
        files.append({"filename": up["filename"], "source": "uploaded"})
    files += [{"filename": f, "source": "solved"} for f in solve_store.list_solved(pkg_id)]
    return {"files": files, "hasSourceZip": instance_store.source_zip(pkg_id) is not None}


@app.post("/api/package/{pkg_id}/validate")
def validate_start(pkg_id: str, payload: dict = Body(...)):
    res = validate_store.start(pkg_id, payload.get("source", "generated"), payload.get("filename", ""))
    if res.get("status") == "error":
        raise HTTPException(400, res.get("error", "Could not start validation."))
    return res


@app.get("/api/package/{pkg_id}/validate/status")
def validate_status(pkg_id: str):
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    return validate_store.status(pkg_id)


@app.get("/api/package/{pkg_id}/validate/file/{filename}")
def validate_cleaned_file(pkg_id: str, filename: str):
    p = validate_store.get_cleaned(pkg_id, filename)
    if p is None:
        raise HTTPException(404, "Cleaned file not found.")
    return Response(content=p.read_bytes(), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{p.name}"'})


# ----------------------------------------------------------- Phase B: solve business rules (async)
@app.post("/api/package/{pkg_id}/solve")
def solve_start(pkg_id: str, payload: dict = Body(...)):
    """Iteratively validate→solve→re-validate the chosen instance until its business-rule
    assertions are satisfied (or the iteration cap). Body: {source, filename, iters?}."""
    res = solve_store.start(pkg_id, payload.get("source", "generated"),
                            payload.get("filename", ""), int(payload.get("iters", 4)))
    if res.get("status") == "error":
        raise HTTPException(400, res.get("error", "Could not start solving."))
    return res


@app.get("/api/package/{pkg_id}/solve/status")
def solve_status(pkg_id: str):
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    return solve_store.status(pkg_id)


@app.get("/api/package/{pkg_id}/solve/file/{filename}")
def solve_file(pkg_id: str, filename: str):
    p = solve_store.get_file(pkg_id, filename)
    if p is None:
        raise HTTPException(404, "Solved file not found; (re)solve first.")
    return Response(content=p.read_bytes(), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{p.name}"'})


# ----------------------------------------------- Phase B: generate rule-consistent data (OFFLINE)
@app.post("/api/package/{pkg_id}/generate-valid")
def generate_valid_start(pkg_id: str, payload: dict = Body(...)):
    """Build the selected tables and OFFLINE-solve their rules (no Arelle); returns solved cell
    values per table. Body: { selection: {CODE:[{concept,dims,datatype,value,key,table}]}, lei?, date? }."""
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    selection = payload.get("selection") or {}
    opts = {k: payload.get(k) for k in ("lei", "scheme", "date") if payload.get(k)}
    res = genvalid_store.start(pkg_id, selection, opts)
    if res.get("status") == "error":
        raise HTTPException(400, res.get("error", "Could not start."))
    return res


@app.get("/api/package/{pkg_id}/generate-valid/status")
def generate_valid_status(pkg_id: str):
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    return genvalid_store.status(pkg_id)


# --------------------------------------------- hypercube extraction (valid-cell set, cached)
@app.post("/api/package/{pkg_id}/hypercube")
def hypercube_build(pkg_id: str, payload: dict = Body(...)):
    """Extract a module's valid dimensional cells via Arelle (one slow pass, cached). Body:
    { module: 'pra001' }. Generate Full Valid Data then emits only valid cells (no dim-invalid)."""
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    res = hypercube_store.start(pkg_id, payload.get("module", ""))
    if res.get("status") == "error":
        raise HTTPException(400, res.get("error", "Could not start."))
    return res


@app.get("/api/package/{pkg_id}/hypercube/status")
def hypercube_status(pkg_id: str):
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    return hypercube_store.status(pkg_id)


@app.post("/api/package/{pkg_id}/generate-valid-module")
def generate_valid_module(pkg_id: str, payload: dict = Body(...)):
    """Generate full valid data for EVERY table of an entry-point/module (server builds the
    selection, offline-solves the rules). Body: { entryPoint: 'pra001', lei?, date? }."""
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    opts = {k: payload.get(k) for k in ("lei", "scheme", "date") if payload.get(k)}
    res = genvalid_store.start_module(pkg_id, payload.get("entryPoint", ""), opts)
    if res.get("status") == "error":
        raise HTTPException(400, res.get("error", "Could not start."))
    return res


# ------------------------------------------------- Phase B: business validation rules (browse)
@app.get("/api/package/{pkg_id}/rules/modules")
def rules_modules(pkg_id: str):
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    return {"modules": rules_store.modules(pkg_id)}


@app.post("/api/package/{pkg_id}/rules/build")
def rules_build(pkg_id: str, module: str = Query(...), force: bool = Query(False)):
    res = rules_store.start_build(pkg_id, module, force)
    if res.get("status") == "error":
        raise HTTPException(400, res.get("error", "Could not start rules build."))
    return res


@app.get("/api/package/{pkg_id}/rules/status")
def rules_status(pkg_id: str, module: str = Query(...)):
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    return rules_store.status(pkg_id, module)


@app.get("/api/package/{pkg_id}/rules")
def rules_list(pkg_id: str, module: str = Query(...), q: str = Query(""),
               table: str = Query(""), page: int = Query(1), pageSize: int = Query(50)):
    if not (config.CACHE_DIR / pkg_id / ".extracted").exists():
        raise HTTPException(404, "Unknown package id (not in cache).")
    result = rules_store.query(pkg_id, module, q, table, page, pageSize)
    if result is None:
        rules_store.start_build(pkg_id, module)
        raise HTTPException(425, "Rules are building; poll /rules/status.")
    return result
