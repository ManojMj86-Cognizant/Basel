# Datapoint Studio — Fresh-Start Design

A local web UI to **analyse and amend the datapoints** of Bank of England Banking
XBRL, where the **first input is the taxonomy package zip** (`boebanking400.zip`).

> Fresh viewpoint, but **not a rewrite of the engine**. The existing Python engine in
> `boe_xbrl_gen/src` (analyzer, dpm_model, instance, generate, solve, solve_loop,
> feedback) is the backend's library. The new code is a thin API + a React UI + a
> fact↔datapoint serializer for the edit grid.

## Decisions (locked 2026-06-16)
- **Amend = edit fact values in an instance** (not taxonomy definitions, not scope).
- **Input = upload the zip**; the app extracts and caches it (keyed by SHA-256).
- **Stack = FastAPI (backend) + React/Vite/TypeScript (frontend)**.
- Local, single-user, no auth.

## Mental model
The zip is the **source of truth** (what datapoints exist + what is valid). An instance
is a **document of facts**; one fact = one datapoint occurrence = a metric × a set of
dimension members × a value. Workflow: **ingest zip → explore datapoint universe →
open/build an instance → edit fact values safely → validate**.

## Architecture
```
React SPA (Vite + TS)  ──REST/JSON (+SSE for long jobs)──>  FastAPI (thin)
  Ingest · Explore · Amend · Validate                        wraps engine in src/
                                                             + package_store, sessions
                                              ───>  extracted-package cache (by hash)
                                              ───>  Arelle (offline validation)
```
Principle: the backend adds almost no logic — it exposes the proven engine. New pieces:
(a) zip extract + cache, (b) fact↔datapoint serializer, (c) session/instance state.

## Screens
1. **Ingest** — drop the zip; extract once (cache by hash); show package summary
   (name/version/publisher, entry points → frameworks, model counts).
2. **Explore datapoints** — framework→table tree; per table show datapoints
   (row/metric/dimension members) joined with the validation rules that touch it
   (`analyzer.analyze` + `template_datapoints`). Global metric/dimension/member search.
3. **Amend** — upload an `.xbrl` or generate a draft; parse to an editable datapoint grid
   (one row per fact: table/metric · dimensions · datatype · current → new value · rules
   affected). **Type-aware editing** from the DPM datatype: monetary/integer numeric
   (rounded to `decimals`), percentage/pure 0..1, boolean toggle, **enum → member
   dropdown**, date picker, format-ruled text regex-validated. Apply writes back through
   `instance`; optional "re-solve dependents" keeps derived totals consistent.
4. **Validate & download** — run Arelle (`solve_loop.run_arelle`), parse violations,
   show a table (id, expression, severity, fact lines) **deep-linked to the grid**;
   download the corrected instance.

## API surface (target)
| Method | Endpoint | Engine call |
|---|---|---|
| POST | `/api/package` (upload zip) | extract+cache, load model |
| GET | `/api/package/{id}` | summary |
| GET | `/api/package/{id}/templates` | `analyzer.analyze` |
| GET | `/api/package/{id}/templates/{code}/datapoints` | `template_datapoints` |
| POST | `/api/instance` (upload xbrl **or** generate) | `instance.Instance` / `generate` |
| GET | `/api/instance/{id}/facts?table=&metric=&q=` | new serializer |
| PATCH | `/api/instance/{id}/facts` (batch edits) | mutate lxml (+ optional `solve`) |
| POST | `/api/instance/{id}/validate` (SSE) | `solve_loop.run_arelle` + parse |
| GET | `/api/instance/{id}/download` | `Instance.write` |

## Build phases
- **Phase 0 — skeleton (THIS STEP):** FastAPI wrapping the engine + React shell; zip
  upload → extract-cache → package summary card. Proves the zip-first flow end to end.
- **Phase 1 — Explore (read-only):** templates tree + datapoints + rules.
- **Phase 2 — Amend (centerpiece):** load instance → fact grid → type-aware edit →
  write back → download. Start with upload-existing-instance.
- **Phase 3 — Validate loop:** Arelle + violations table deep-linked to the grid.
- **Phase 4 — niceties:** in-UI generate, scope/filing-indicator editing, batch/sweep.

Phases 0–3 = the "basic UI" (full upload→explore→amend→validate loop).

## Risks to design around
- **Fact→table mapping:** facts carry metric+context(dims) but not their table; the
  reverse index from annotated templates is the one non-trivial new piece (MVP: group by
  metric+dims + filing indicators; precise reverse-map later).
- **Edit consistency:** manual leaf edits break additivity — default to "re-solve
  dependents".
- **Scale:** PRA001 ~61k facts → server-paginated/virtualized grid, never load-all.
- **Arelle latency:** 30 s small → ~46 min PRA001 → always async + cancelable.

## Phase 0 scope & explicit deferrals
**In:** zip upload, SHA-256 cache, extract, parse `taxonomyPackage.xml`
(name/version/publisher/entry points/frameworks), read counts from prebuilt
`model/dpm_model.json`, React page that uploads and renders the summary.
**Deferred (honest):** building the DPM model + rule index *per uploaded package*
(heavy openpyxl); all of Explore/Amend/Validate.

## Phase 1 — Explore (per-package, hybrid model)  *(decisions locked 2026-06-17)*

**Goal:** make the datapoint/metric model work for **any** uploaded package, built **from
the zip by code (Arelle)** — not from hardcoded on-disk Excel. Optionally let the user upload
the DPM Excel for **reconciliation** (diff + refine). Split into **1a (dictionary + reconcile)**
now and **1b (per-table datapoints from the table linkbase)** next.

### Why hybrid (measured 2026-06-17)
Loading one module's DTS from `boebanking400.zip` via Arelle took **~3 s** and already exposed
the **whole shared dictionary**: 1,098 metric concepts, 392 dimensions, 5,304 member/domain
concepts, 6,837 EN labels resolved in 0.5 s. (The "Arelle = 46 min" warning is about
*validation*, not *model loading*, which is cheap.) So the zip is a complete, taxonomy-agnostic
source — **except** numeric subtype: the XSD type cleanly gives BOOLEAN/DATE/STRING/ENUM/
MONETARY, but **PERCENTAGE vs DECIMAL vs INTEGER is ambiguous** from the schema, and DPM-only
metadata (balance, referenced domain) isn't all in the schema. The optional **DPM dictionary
Excel** carries the precise DPM datatype + that metadata → reconciliation refines exactly the
ambiguous bits and reports the diff.

### Phase 1a — dictionary model + reconciliation
**Build (automatic, after extraction; cached per package hash; ~5–15 s):**
- New engine module `src/taxonomy_model.py` — load the package DTS via Arelle (reuse the
  `tools/dump_dim_defaults.py` Cntlr/PackageManager pattern), walk `qnameConcepts` + label
  linkbase, emit `{metrics,dimensions,domains,members}` in the **exact `dpm_model.json` shape**
  so `generate.py`/`solve.py` consume it unchanged (they only need `metrics[code].datatype`).
  Map XSD item type → DPM datatype (best-effort; flag numeric ones `needsRefine`). Cache to
  `studio/backend/.cache/packages/<hash>/model.json`.
- **Reconcile (optional, on Excel upload):** `src/reconcile.py` parses the uploaded workbook
  with the **existing `dpm_model.py`** parser (DPM dictionary) and joins to the Arelle model by
  code across **metrics + dimensions + members**. Diff buckets: *only-in-schema*, *only-in-Excel*,
  *datatype mismatch*, *label diff*. Merge policy: **Arelle authoritative for existence; Excel
  authoritative for DPM datatype refinement + extra metadata** (UI-overridable).
- Accept **either** workbook kind on upload (sniff by sheet names): a **DPM dictionary** →
  reconcile now; an **Annotated Templates** workbook → stash for the Phase 1b table view.

**API (1a)**
| Method | Endpoint | Notes |
|---|---|---|
| POST | `/api/package/{id}/model/build` | build or return cached Arelle dictionary model (auto-triggered post-extract; idempotent) |
| GET | `/api/package/{id}/model?section=&q=&page=` | paginated/searchable metrics/dims/domains/members |
| POST | `/api/package/{id}/model/reconcile` (upload xlsx) | diff report + merged model; persists the chosen merge |

**UI (Explore → Dictionary)**
- Searchable grid over metrics/dimensions/members (code · label · datatype · domain), section
  tabs, server-paginated.
- An **"Upload DPM dictionary (optional)"** box → on upload, a **diff panel** (bucket counts +
  a mismatch table) and the grid switches to reconciled values with a source/override badge.

### Phase 1b — per-table datapoints (table linkbase)  *(next; one number to confirm first)*
A "datapoint" = row × metric × dimension-members of a table. The zip's **XBRL Table Linkbase**
(`*-rend.xml`, ns `http://xbrl.org/2014/table`) defines these (`table:ruleNode` →
`formula:concept` + `formula:explicitDimension`). Parse per table (lazy) and join to the 1a
model for labels. **TODO before committing 1b:** measure table-linkbase extraction time (the one
cost not yet benchmarked); `*-rend.xml` files are small so expected fast. The optional Annotated
Templates upload reconciles against this per-table view (human row codes/titles).

### Honest deferrals
- 1b table-linkbase parse + exact entry-point→table membership (until 1b lands, Explore = the
  per-package **dictionary**, which is already taxonomy-agnostic and unblocks generation).
- Validation-rule reconciliation (the friendlier "Simplified Expression" lives only in the
  Validations Excel; the zip has machine formula linkbases) — fold into Phase 3.
