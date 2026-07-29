# ClaudeLearning — Project Context

## What this is
Tooling around the **Bank of England Banking XBRL taxonomy v4.0.0**. Two efforts live here:
1. **`boe_xbrl_gen/`** — a proven engine that generates business-rule-valid BoE Banking
   XBRL instances with random values (Arelle-verified). See its `ARCHITECTURE.md`,
   `SESSION_STATUS.md`, `USER_GUIDE.md`, `README.md`.
2. **`boe_xbrl_gen/studio/`** — *(in progress)* **Datapoint Studio**: a local web UI to
   analyse and amend the datapoints of XBRL. First input = the taxonomy package zip. See
   `studio/PLAN.md` (design) and `studio/SESSION_STATUS.md` (live status + resume plan).
   Done: **Phase 0** Ingest, **Phase 1a** Dictionary (per-package model built from the zip via
   Arelle + DPM-Excel/zip reconcile), **Phase 1b** Tables (per-table datapoints from the table
   linkbase), **Phase 2** Amend (editable grid: datatype-restricted cells, Generate Data, Create
   XBRL, upload-instance populate/edit/save incl. open axes), **Phase A** real members for explicit
   open dimensions, **Phase B** the **business-rule solver** (Solve in the Validate tab), plus
   **Rules** (browse business rules), **Validate** (async Arelle), and **Framework ▸ Entry-point**
   scoping across Dictionary/Tables/Rules.
   Taxonomy-agnostic (banking + insurance verified; Phase-2 generate/solve exercised on banking 4.0.0).
   Nav: Home · Ingest · Dictionary · Tables · Amend · Rules · Validate.
   **Amend** does **Generate Data** + **Create XBRL** (build-only, instant) and, when an `.xbrl` is
   uploaded (Tables tab), populates/edits the grids (open axes expanded from the data) + writes edits
   back. Amend tables are a **union** of user-**selected** (Edit, amber = author fresh) and
   **uploaded** (green = populated from the instance) tables, each with a ✕ close and a 🔒 lock;
   **row/column/cell locking** (yellow) is skipped by Generate Data. **Rules** browses the package's
   business rules per module. **Validate** runs Arelle (async) on a built/uploaded instance → report
   + cleaned file, and **⚙ Solve business rules** iterates validate→solve→re-validate to satisfy the
   formula assertions (writes a solved `.xbrl`). (Build, validate, and solve are deliberately split.)

## Inputs on disk (BoE v4.0.0 release)
- `boebanking400.zip` (56 MB) — **taxonomy package** (the primary input). Extracted at
  `boebanking400/Banking_4.0.0/` with `META-INF/taxonomyPackage.xml` (manifest + URL
  catalog → Arelle resolves instances offline).
- `boebankingtaxonomydpmv400/` — DPM workbooks: **DPM dictionary** (metrics/dimensions/
  domains/members, with datatypes) + **Annotated Templates** (per-table datapoints).
- `boebankingtaxonomysampleinstancesv400/` — official sample `.xbrl` per module.
- `boebankingtaxonomyvalidationsv400/` — validation (business) rules workbooks.
- `tools/` — ad-hoc inspection/diagnostic scripts.

## Engine map (`boe_xbrl_gen/src/`)
- `analyzer.py` — templates + rules, and the per-table join (UI/analysis core).
- `dpm_model.py` — DPM dictionary → metrics/dims/domains/members (cached to
  `model/dpm_model.json`; 1,098 metrics, 374 dims, 53 domains, 43 member sets).
- `instance.py` — parse an instance into mutable lxml facts/contexts (basis for amend).
- `generate.py` — clone a sample + type-correct random values.
- `instance_build.py` — build a valid XBRL instance **from the package alone** (no sample): map
  selected tables → module entry point, emit contexts/units/filing-indicators/facts, validate +
  prune dim-invalid facts via Arelle, report formula assertions. (Studio Phase-2 Generate/Create.)
- `solve.py` / `solve_loop.py` / `feedback.py` — business-rule solving + Arelle feedback.
  (Studio Phase-B Solve wraps `solve_loop.run` per package; needs `src/` on `sys.path` since
  these modules use bare imports `import solve` / `from instance import Instance`.)
- `taxonomy_model.py` — also emits `dim_members` (`build_dimension_domains`: real domain members
  per EXPLICIT dimension, from both `dim.xsd`) so open explicit axes offer valid members, not ints.
- `table_model.py` — `table_grid` enriches each open-axis record with `typed` + `members`; adds
  `rc_codes(rend)` (BoE row/col/z codes from `<table>-lab-codes.xml`) + `node` on positions — the
  **rc-code bridge** mapping a workbook cell ref to its `(metric, dims)` datapoint.
- `workbook_rules.py` — **rule-driven generation engine** (the path to valid data on dimensioned
  modules; `solve`/`bind` does NOT bind to studio-built facts). Loads the BoE **validations workbook**
  (cell-ref rules), `parse_expression` (additive (in)equality: `i=`, `i+/-`, `i* k`, `isum`),
  `CellResolver` (cell ref → `(metric,dims)` via the rc-code bridge), `solve_cells` (cell-space
  solver: pick derived cell, compute from inputs so equations balance). Proven: v7380/v7381 (the
  only two 4-table PRA001 rules, `Include in XBRL=no`) balance exactly.
- `solve_all.py`, `sweep.py`, `pipeline.py` — batch/large-module runners.
- `ui_app.py` — the **old** Streamlit UI (Analyze + Generate). Superseded by `studio/`.

## Datapoint Studio (`studio/`)
- `backend/` — FastAPI app wrapping the engine. Run:
  `cd boe_xbrl_gen/studio/backend && python -m uvicorn app.main:app --port 8201`
  (port 8201; avoid `--reload` — on Windows the reloader respawns workers and can leave a
  zombie socket holding the port).
- `frontend/` — React + Vite + TypeScript. Run: `cd studio/frontend && npm run dev`
  (Vite proxies `/api` → `http://localhost:8201`; open http://localhost:5173).
- Endpoints: `GET /api/health`, `GET /api/packages`, `POST /api/package` (upload zip),
  `GET /api/package/{id}`, `DELETE /api/package/{id}` (remove cached package; allows re-upload),
  `GET /api/package/job/{id}` (extraction progress). **Phase 1a (per-package dictionary, from
  the zip via Arelle):** `POST /api/package/{id}/model/build`, `GET …/model/status`,
  `GET …/model?section=&q=&page=&pageSize=`, `POST …/model/reconcile` (upload DPM xlsx → diff/merge).
- Engine for Phase 1a: `src/taxonomy_model.py` (build dict model from the package via Arelle —
  now also resolves ENUMERATION allowed values, dimension defaults, and typed-dimension domain
  elements; ~60–110 s, cached) + `src/reconcile.py` (diff/merge vs the DPM-dictionary Excel). Backend
  `app/model_store.py` builds/caches/serves it.
- Design + phase plan: `studio/PLAN.md`. Amend = edit **fact values**; input = **upload
  zip**; stack = **FastAPI + React**.
- **Phase 2 Generate (build only):** `POST /api/package/{id}/generate` (selected-table datapoint
  values → build instance(s) from the package, **no Arelle**, instant), `GET …/generate/file/{name}`.
  Engine `src/instance_build.py`, backend `app/instance_store.py`. **Validate (separate, async):**
  `GET …/validate/files`, `POST …/validate`, `GET …/validate/status`, `GET …/validate/file/{name}`
  — backend `app/validate_store.py` (Arelle validate → prune → report). **Upload-instance binding:**
  `POST/GET/DELETE …/instance`, `GET …/instance/grid/{code}` (open axes expanded from the data) +
  `…/instance/save` (write edits back). Upload persists `<hash>/source.zip` for offline Arelle.
- **Validation Rules tab:** `GET /api/package/{id}/rules/modules`, `POST …/rules/build?module=`,
  `GET …/rules/status?module=`, `GET …/rules?module=&q=&table=&page=`. Engine `src/rules_model.py`
  (lean iterparse of the package's assertion sets + value rules — read-only, no Arelle), backend
  `app/rules_store.py` (per-module job+cache). PRA001 = 1448 rules, ~2 min one-time then cached.
- **Scope (Framework ▸ Entry-point) + Rules-by-Table:** `GET …/scope`, `…/scope/resolve?table=`
  scope Dictionary/Tables/Rules; engine `app/scope_store.py`. **Upload-instance binding (Section C):**
  `POST/GET/DELETE …/instance`, `GET …/instance/values/{code}`, `POST …/instance/save` — populate the
  grids from an uploaded `.xbrl`, edit, write back into that file. Engine reuses `src/instance.py`;
  backend `app/instance_data_store.py`.
- **Phase B — business-rule solver (async):** `POST /api/package/{id}/solve` {source,filename,iters?},
  `GET …/solve/status`, `GET …/solve/file/{name}`. Backend `app/solve_store.py` wraps the engine
  `solve_loop.run` (validate→solve→re-validate to fixpoint/iter-cap), reports before→after
  unsatisfied-assertion counts, writes `<hash>/solved/<name>.solved.xbrl`, and lists it as a
  `solved` source in `…/validate/files` (so it can be re-validated). Verified: a generated pra_mem
  instance went 2 assertions → 0. Gated to banking 4.0.0 (rule-URL→local-file mapping).
- **Generate VALID data (rule-driven, the valid-PRA001 path):** `app/genvalid_store.py` builds a
  module's tables → **hypercube filter** (only dimensionally-valid cells) → **rule-driven override**
  (`workbook_rules` computes values so business rules pass) → reflect to grid. Endpoints:
  `POST …/generate-valid` (selection) + `POST …/generate-valid-module {entryPoint}` (whole module) +
  `…/generate-valid/status`. UI: Amend **⚖ Generate valid data**, Tables **⚖ Generate Full Valid
  Data** (entry-point scoped → opens populated in Amend). **`app/hypercube_store.py`** extracts a
  module's valid-cell set via one Arelle pass, cached `<hash>/hypercube-<module>.json`
  (`POST …/hypercube {module}`, `…/hypercube/status`) — needed once before full-module generation.
  PROVEN on the C13/C14/OF19/OF20 cluster: **0 dimInvalid + 0 assertions**. Full-PRA001 acceptance
  (one-time ~46-min hypercube build, then generate) is the outstanding run — see `studio/SESSION_STATUS.md`.
- **Phase 0 dropdown speed:** `package_store.list_packages` caches the four dropdown fields in
  `<hash>/list.json` and `_find_manifest` does a shallow lookup (not a recursive `rglob`), so the
  package list returns in ~25 ms cold instead of ~2.8 s. `model_store._active_model` splices the
  Arelle-only extras (`enumerations`, `dim_members`, `dim_defaults`, `namespaces`) into a reconciled
  model.

## Environment (verified 2026-06-16)
- Windows 11, PowerShell primary shell, Git Bash available.
- Python 3.13.1 — fastapi 0.115, uvicorn 0.34, arelle-release, lxml, openpyxl, pandas.
- Node v22.17, npm 11.
- Arelle runs **offline** against `boebanking400.zip`:
  `python -m arelle.CntlrCmdLine --packages ..\boebanking400.zip --validate -f X.xbrl --logFile X.log`
- Encoding gotcha: set `PYTHONIOENCODING=utf-8`; read `dpm_model.json` with `encoding="utf-8"`.

## Conventions
- Don't re-extract the 56 MB zip needlessly — cache by hash.
- Arelle validation is the time sink (small ~30 s, PRA001 ~46 min) — always async.
- Engine functions currently hardcode `ROOT = C:\Users\177069\ClaudeLearning`.
