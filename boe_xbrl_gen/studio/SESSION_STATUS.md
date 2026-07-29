# Datapoint Studio — Session Status & Handoff

**Last updated:** 2026-07-24
**Scope:** the new web UI (`boe_xbrl_gen/studio/`) — *not* the generator engine (that has
its own `../SESSION_STATUS.md`). Design + phase plan: `PLAN.md`. Test checklist: `TEST_SCENARIOS.md`.

> Goal: a local web UI to **analyse and amend the datapoints** of BoE Banking XBRL.
> First input = the **taxonomy package zip**. Amend = edit **fact values**. Stack =
> **FastAPI + React/Vite/TS**. Build in phases 0→4; phases 0–3 = the "basic UI".

---

## ▶ PRA001 valid-instance thread (2026-07-22 → 2026-07-24) — MOVED to the engine status file
The surgical/coordinated-regeneration work to make a generated **PRA001** pass TDG Beacon (v2 → **v12**,
`src/solve_existing.py` / `src/coregen.py` / `src/gen_of0902.py` / `tools/*`) is **generator-engine work**
and now lives in **`boe_xbrl_gen/SESSION_STATUS.md`** (see "PRA001 valid-instance drive"). Full blow-by-blow
trail = memory `pra001-valid-instance-progress.md`. Headline: **v8 = last TDG-confirmed best (75 error
rules)**, **v12 = newest candidate awaiting TDG**. The 06-24 → 07-02 genvalid/hypercube entries below stay
here because they interleave with studio genvalid work.

## ▶ 2026-07-02 (cont.) — OF08.01.01.01 + OF08.01.01.02 cluster FULLY satisfied (joint solve)
- **Cross-table inequalities b0367/b0368/b0369 FIXED** (all 16 codes, 0 violations) by solving OF08.01.01.01
  + OF08.01.01.02 JOINTLY in one non-negative LP with the cross-table `≤` rules as constraints
  (`_crosstable_le_rows`). `_NONNEG_TABLES` = OF08.01.01.01,OF08.01.01.02. Combined LP feasible.
- **Whole OF08.01 cluster now clean:** additive (b0745 652/652, b0744 635/635), single-table inequalities
  (b1037…b0306, 0 viol), cross-table inequalities (b0367/8/9, 0 viol), cross-table additive (b0814/b0752 17/17),
  0 neg / 0 dim-invalid. File shipped (36 MB, 50,101 facts). Regen ~810 s.
- **NEXT / watch:** any remaining TDG classes from re-upload; if OF07 (same 2-D over-determined shape) is
  flagged, add it to `GENVALID_NONNEG_TABLES` (joint with its off-balance sibling if a cross-table ineq links them).
- Tools: `tools/check_ineq.py` (plain ≤/abs/isum), `tools/check_rules.py` (additive), `tools/check_crosstable.py`.

## 2026-07-02 — OF08.01.01.01 FULL rule set satisfied; b0368 (cross-table ineq) via joint solve above
- **OF08.01.01.01 now satisfies its ENTIRE single-table rule set** (additive + inequalities) with 0 neg /
  0 dim-invalid, and cross-table b0814/b0752 preserved. Fix: `_nonneg_additive_solve` now takes
  `le_constraints` → adds the table's ≤ rules (b1037/b1038/b1036/b0306 ≤0 pins, b0378/b0379 row≤row,
  b0380/b0684 |·|≤|·|, b0683 |Σ|≤cell) as LP inequality rows (hard, soft-slack fallback). Combined LP feasible.
  Verified 0 violations on all of them + b0745 652/652 + b0744 635/635. File shipped (36 MB, 50,101 facts).
- Tool: `tools/check_ineq.py` verifies plain `<=`/`abs`/`isum` comparison rules (check_rules.py can't).
- **STILL NEXT: b0368/b0369** — CROSS-table inequality (OF08.01.01.02 ≤ OF08.01.01.01). c0110 confirmed NOT
  wrongly greyed; fix = cap the off-balance LHS ≤ its (often absent=0) overall ceiling.
- Regen ~600–700 s (nonneg LP). `GENVALID_NONNEG_TABLES` (default OF08.01.01.01) — extend to OF07 etc. if TDG flags.

## 2026-07-01 (cont. 2) — b0745 FIXED (non-negative additive solve); b0368 = cross-table inequality next
- **b0745 FIXED** (652/652, 0 fail) via NEW `_nonneg_additive_solve` — LP over OF08.01's additive rules, all
  cells ≥0, integer-exact. Earlier "needs 1,902 negatives / unfixable" was WRONG (artifact of random-free
  exact solve; LP proved a 0-negative solution exists). **ORDER matters:** nonneg runs AFTER cross-table agg,
  BEFORE open-link. Cross-table additive balanced 288 → **1,286**. Env `GENVALID_NONNEG_TABLES` (default
  OF08.01.01.01). Regen now ~695 s (LP). File shipped (36 MB, **50,101 facts**, 0 neg / 0 dim-invalid / 0 bool).
- **c0110 NOT wrongly greyed** — `tools/drs_parity_all.py`: 0 over-pruning vs official sample (all 61,498 facts
  valid). b0368 RHS correctly absent; the bug is a positive LHS (OF08.01.01.02 c0120) over a 0 ceiling.
- **NEXT: b0368/b0369 cross-table INEQUALITY handler** — cap `A ≤ B` across tables (lower the off-balance LHS).
- Extend `_NONNEG_TABLES` to OF07.00.01.01 etc. if TDG flags their additive clusters (same over-determined shape).

## 2026-07-01 (cont.) — OF08 cross-table b0814/b0752 FIXED; b0745 (was wrongly "accepted"); b0368 next
- **b0814 (21) + b0752_NN cross-table (`OF08.01 r0070 = isum(OF08.02)`) FIXED:** multi-z open synth
  (`_synth_open_rows` row-per-z) + `_crosstable_open_link` (derive open source from closed target, closed-dim
  match). Verified 17/17 each; **50,101 facts, 0 neg, 0 dim-invalid**; b0745 unchanged. File shipped (36 MB).
- **b0745 (+ 22-rule r0010 cluster): ACCEPTED as no-negatives tradeoff** — exact fix needs 1,902 negatives
  (→ ~1,902 TDG ≥0 failures). Proper fix = coordinated matrix generation (deferred).
- **NEXT: b0368/b0369** — cross-table INEQUALITY (`OF08.01.01.02 ≤ OF08.01.01.01`, two closed tables). New
  class; needs cross-table inequality handling (both sides Stage-1-owned → harder).
- Regen: `GENVALID_CROSSTABLE=1 python tools/regen_pra001.py` (cwd=studio/backend). Verify: `tools/check_rules.py <codes>`.

## 2026-07-01 — TDG schema error FIXED (typed-date); re-upload the refreshed file
**Fixed:** open-row synthesis emitted `'1'` for every typed dim, but `eba_typ:DT` (RDT on OF24.03.01.03) is
`xs:date` → TDG `cvc-datatype-valid.1.2.1 '1' not valid for 'date'`. Now synthesizes a value matching each
typed element's XSD type (DT→`2026-02-28`, ID=integer→`1`, IS/LE=string→`1`). Regenerated + verified: DT emits
`2026-02-28`; **49,181 facts, 0 dim-invalid, 0 negatives, 0 boolean**. Handoff file refreshed.
**Next:** re-upload to TDG; expect the two schema errors gone. Then use the breakdown to pick the rule levers
below (from cont. 6). Regen: `GENVALID_CROSSTABLE=1 python tools/regen_pra001.py` (cwd=studio/backend).

## 2026-06-27 — was: AWAITING TDG breakdown of the current file
**State:** shipped `ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID.xbrl` (35 MB, **49,181 facts**, 0 dim-invalid,
0 negatives, 0 boolean, 18 open tables now populated, cross-table net-positive + const-sum handler in place).
**User is re-uploading to TDG; resume when the breakdown arrives.** Use it to confirm which classes ACTUALLY
fail (our offline check OVERSTATES — it can't replicate TDG's absent-input=0 semantics). Then pull the matching
lever (all scoped + ready in cont. 6):
- **b0778** (shares=1, singleton) → flip const-sum to override Stage-1-owned cells (net-positive guard).
- **273 plain `>=`/`<=` sign rules** → extend parser beyond `i`-prefixed relations (many `>=0` likely already pass).
- **b0745 / 232 "missing-cell" family (OF07/OF08)** → likely ARTIFACTS (isNull removed inputs + over-scoped greyed
  cells; TDG absent=0). Only build the isNull↔additive "force total=0" fix if TDG actually flags them.
- **18 open tables** → if TDG trips their (un-solved random) values, make the rc-code bridge match synthesized
  typed cells so their values get rule-solved.
Regen cmd (cwd backend, env `GENVALID_CROSSTABLE=1`): run scratchpad `regen_pra001.py` (or `gv._run(PKG,{},{...},entry_point="pra001")`). Pkg hash `50c2f2d9…`. Measure offline: scratchpad `count_neg.py` / `validate_out.py` / `check_crosstable.py` / `check_rules.py` / `survey_rules.py`.

## 2026-06-26 — scipy fixed by reboot; full-quality PRA001 shipped
Full detail in **`SESSION_2026-06-24_dimensions_and_rules.md`** (bottom: "2026-06-26 (cont.)"). Headlines:
- **scipy `linprog` deadlock GONE after reboot** (the 06-26 blocker) — imports in 5.76 s.
- **Found + fixed a cap regression.** The 06-26 `_LP_CELL_CAP=2500` skipped the ≥0 LP on PRA001's big
  components → 2,362 negatives. Raised the **default to 20000** in `src/workbook_rules.py` (covers OF07/OF08);
  regen now runs ~177 s and ships the good file. Cap still guards scipy-broken hangs (`linprog is None`).
- **NO-NEGATIVES fix (cont. 2):** TDG b0655 failed on the 144 negatives. Root cause = `solve_cells_lp`
  snapping free vars to 1000s AFTER the ≥0 LP, so derived cells went negative (worst with coefficient rules,
  e.g. −200/−300). Fixed: accept snapped values only if all cells stay ≥0, else continuous ≥0 LP, else clamp.
- **Shippable file refreshed:** `ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID.xbrl` (34 MB, **47,268 facts**) —
  **0 negatives**, **0 dim-invalid**, 0 bad booleans; single-table additive 11,155/17,939 balanced (224
  unbalanced + 6,560 incomplete = open/typed-axis generation gap). Additive 213→224 = the ≥0-over-additivity trade.
- **NO-NEGATIVES fix (cont. 2):** snap-after-LP broke ≥0; now snapped-only-if-≥0 else continuous, else clamp.
- **STAGE 2 cross-table (cont. 3–4):** the 452 multi-table rules fuse into a 35-table mega-group → DON'T
  feed the solver (hang + Stage-1 churn). Instead a **safe aggregation post-pass** (`_crosstable_agg_values`,
  `GENVALID_CROSSTABLE=1`) derives cross-table targets from fixed sources. Refined to **net-positive override**
  (`GENVALID_CROSSTABLE_OVERRIDE=1`): edit free-leaf cells first (0 Stage-1 impact), override a Stage-1 cell
  only when it fixes more cross-table rules than it breaks. Best file: total additive fails 199→**192**,
  only 4 single-table eqs disturbed, **0 neg / 0 dim-invalid / 0 boolean**.
- **Cross-table frontier:** 1,093 of 1,533 cross-table additive eqs are "incomplete" — they reference cells
  we DON'T GENERATE (open/typed axes). Next real lever = **generate the missing cells**. Conditional/boolean
  cross-table rules also unhandled (don't parse as additive).
- **OPEN-ROW SYNTHESIS (cont. 5):** 18 PRA001 tables generated 0 facts (rows = open/typed dim, e.g. OF24.03.01.03–.09
  on UDI). NEW `_synth_open_rows` synthesizes ONE DRS-valid row each (typed→synth value, explicit→valid member),
  first z only, tagged `synth` + exempt from hypercube filter. Now **all 18 populated, 0 dim-invalid, 0 neg**;
  facts 47,268 → **49,181**. Trade: their cells carry un-solved random values (rc-code bridge can't match the
  synthesized typed value `UDI="1"` to rule cells), so ~75 additive eqs are now present-but-unbalanced.
- **Shippable file:** `ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID.xbrl` (35 MB, **49,181 facts**, 18 open tables now present).
- **NEXT lever:** make the rc-code bridge / solver match synthesized open-axis cells (typed-value-agnostic) so the
  18 tables' values get rule-solved too. Then re-upload to TDG for a fresh breakdown.

## 2026-06-24 — dimensions FIXED, business-rule solving (single-table)
Full detail in **`SESSION_2026-06-24_dimensions_and_rules.md`**. Headlines:
- **Dimensions solved** (Arelle-confirmed 0 `PrimaryItemDimensionallyInvalid`) via new offline DRS
  validator `src/dim_drs.py` (parses each `<table>-def.xml`; ~40 s vs the ~46-min Arelle pass). Three
  bugs fixed: localname collisions (domain-qualify members), required typed dims, boolean value error.
- **Business rules (single-table only):** the win was **scope-threading** — the workbook's `Scope`
  column was being dropped, so the rule solver never matched cells (overrides 384 → 43,031). Single-table
  **additive 407/454 rules** (~90%), **isNull 100%**. Remaining 47 = 32 over-determined (2D row+col;
  exact solve infeasible on big tables OF07/OF08) + 11 missing-cell + 4 mixed.
- **Upload file:** `C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID.xbrl`
  (46,809 facts, 0 dimInvalid, 0 boolean).
- **Next (user, tomorrow):** re-upload to TDG, share breakdown → then exact solve for SMALL tables
  (OF02/OF09/C32/OF19/OF21), then "other"/multi-table rules. See the dated doc's TODO.

## 2026-06-22 (cont.) — RULE-DRIVEN valid-data engine + HYPERCUBE extraction 🎯
Goal pursued: generate a **complete valid PRA001** instance — passes structural + dimensional +
**business-rule** validation. Major progress; the mechanism is **proven** on a 4-table cluster
(**0 dimInvalid + 0 unsatisfied assertions**). Full-PRA001 run is the remaining acceptance.

### The journey / key findings (important context)
1. **Offline "Generate valid data" added first** (`genvalid_store.py`): build selected tables →
   run engine `solve()` over the module rules **offline (no Arelle)** → reflect rule-consistent
   values to the grid. Endpoints `POST …/generate-valid` (+ `/status`), Amend button
   **⚖ Generate valid data**. **Proven on pra_mem → Arelle 0 assertions** (single-table additivity).
2. **"Generate Full Valid Data" (whole module) added** (`genvalid_store.start_module` + endpoint
   `POST …/generate-valid-module` + Tables button gated to the **entry-point** scope; results open
   populated in Amend). Built all 104 pra001 tables (81k facts) in ~98 s.
3. **CRITICAL FINDING — bind-based `solve()` does NOTHING on dimensioned modules.** On the built
   PRA001 instance the rules produced **0 bindings** (`resolver.bind`), because the studio's
   build-from-package **cartesian over-generates** ~45k contexts whose dimensional signatures don't
   match what the rules select. (pra_mem worked only because FS701 is dimensionless.) So `solve`/
   `bind` is the **wrong tool** here.
4. **Workbook ⊋ machine linkbase.** The validations workbook (`boebankingtaxonomyvalidationsv400/
   …Banking reporting v4.0.0.xlsx`, sheet `banking_reporting`, **1,490 rules**) is a superset of the
   package's machine formula linkbase (PRA001 = **1,448** rules Arelle evaluates). The **only two
   4-table rules** — `v7380_m`, `v7381_m` (C13·C14·OF19·OF20, with `×12.5` risk weights) — carry
   **`Include in XBRL = no`**, so Arelle never evaluates them (siblings v7382/v7383 = 3-table,
   `Include=yes`, are deployed). Workbook columns: Expression / Simplified Expression / Precondition
   / Include in XBRL / Deactivated / Severity / **T1–T4** (max 4 tables by design).
5. **rc-code bridge** (`table_model.rc_codes`): `<table>-lab-codes.xml` (eurofiling rc-code role)
   maps each BoE cell code (r/c/z, e.g. `0430`) → table-linkbase node → its `(metric, dims)`. Lets us
   resolve any workbook cell ref to a real datapoint. (Also added `node` to `parse_table` positions.)

### What was BUILT (the rule-driven engine + hypercube)
- **`src/workbook_rules.py` (NEW)** — Stage 1+2 of the engine, **proven**:
  - `load_workbook_rules(xlsx, sheet)`; `parse_expression()` parses the additive-(in)equality shape
    (`i=`, `i+/i-`, `i* const`, `isum(...)`) — **1,099/1,490 parse**.
  - `CellResolver(extracted_dir)` — resolves a cell ref `(t,r,c,z)` → `[(concept,dims)]` via the
    rc-code bridge (proven: v7380/v7381/v7382 all resolve).
  - `solve_cells(asts, resolver, rng, datatype_of)` — **cell-space solver**: pick the derived cell
    per equality, randomise inputs, compute so it balances; topo-orders across rules. **Proven:
    v7380/v7381 balance exactly (LHS==RHS).** Returns `{key -> {concept,dims,table,value}}`.
- **`app/genvalid_store.py`** — wired rule-driven: builds selection → (hypercube filter) →
  `_rule_driven_values()` overrides built cells with computed values → build. (Add-missing-cells was
  tried and reverted: a workbook cell ref under-specifies dims, so emitting a standalone bridge cell
  is dim-invalid — see hypercube below.) `_WORKBOOK_BY_FRAMEWORK` maps `banking_reporting` → the xlsx.
- **`app/hypercube_store.py` (NEW)** — extract a module's **valid dimensional cells** via **one Arelle
  pass**, cached `<hash>/hypercube-<module>.json` = `{module, tables, cells:[key,…]}` (key =
  `local|dim=mem,…`, **defaults dropped + localised**). `cell_key(concept,dims,defaults)` used on both
  sides. Endpoints `POST …/hypercube {module}` + `GET …/hypercube/status`. `genvalid` filters the
  cartesian to these valid cells (no over-generation) **iff** the cache exists, else falls back.

### VERIFIED (real Arelle runs)
- Engine cells: workbook 1,490 → parse 1,099; v7380/v7381 cells resolve + **balance exactly**.
- **Why hypercube is needed:** a workbook cell `OF20 r0050 c0050` (4 dims) maps to **144** build
  cells (extra `MCY/PRP/RWS` dims) — `SUPERSET 144 / SUBSET 0`. The (r,c) ref under-specifies; the
  full context needs the hypercube. So coverage **and** dim-validity are the *same* blocker.
- **4-table cluster (C13/C14/OF19/OF20), integrated pipeline:** cartesian 7,307 facts / 1,290
  dimInvalid → **hypercube filter keeps 6,017 (dimInvalid 0)** → rule-driven override → Arelle
  **dimInvalid = 0, assertionsUnsatisfied = 0**. ✅ (the fully-valid result)

### 🔜 RESUME PLAN (tomorrow)
```powershell
cd C:\Users\177069\ClaudeLearning\boe_xbrl_gen\studio\backend
$env:PYTHONIOENCODING="utf-8"; python -m uvicorn app.main:app --port 8201 --log-level warning
cd ..\frontend; npm run dev    # http://localhost:5173
```
**To produce the complete valid PRA001 (the goal):**
1. `POST /api/package/<hash>/hypercube {module:"pra001"}` → ~46-min Arelle pass, **cached** (extracts
   valid cells for all 104 tables). Poll `…/hypercube/status`.
2. Tables → Framework▸Entry-point = **banking_reporting ▸ pra001** → **⚖ Generate Full Valid Data**
   (now filters to valid cells + rule-driven values) → Create XBRL → **Validate** → expect 0/0.
- `<hash>` = `50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181`.
- NOTE: I removed a **partial** `hypercube-pra001.json` (only 4-table cells) used for the proof — so
  the cache is clean; the full hypercube must be (re)built per step 1 before full-module generation.

### ⚠ OUTSTANDING OBSERVATIONS & ISSUES (pick up here)
- **[BIG] Full-PRA001 acceptance NOT yet run** — needs the one-time hypercube build (~46 min) + a
  full Generate Full Valid Data + a full Validate (~46 min) to confirm 0/0 at 104-table scale.
- **No UI for the hypercube step** — it's API-only. Add a "Prepare valid cells (one-time)" button on
  the Tables tab next to Generate Full Valid Data (build + poll `…/hypercube/status`), and have
  Generate Full Valid Data prompt/auto-trigger it if the cache is missing.
- **Rule-cell coverage after hypercube filter dropped to 27** (from 47) — fewer cells remain to
  match; assertions still 0 for the cluster, but at full module verify enough enforced rules' cells
  are present+valued. Consider matching rule cells by **superset** against the valid set (a (r,c) ref
  → the unique surviving valid fact) to raise coverage.
- **Workbook-only rules (v7380/v7381 etc., `Include=no`)** are satisfied offline by the engine but
  Arelle won't confirm them — fine, but note in any "valid" claim.
- **`solve()`/`feedback` (Arelle Solve tab) is the OLD path** — kept for uploaded/instance solving,
  but for studio-built dimensioned instances it doesn't bind. The rule-driven engine supersedes it
  for generation. Don't conflate the two.
- **Engine parse cost:** `solve_all.parse_all_rules(banking_reporting)` ≈ 4,344 vr files → first parse
  a few min, **cached** `<hash>/solved/rules-banking_reporting.pkl`. workbook load is fast.
- **`_build_module_selection` doesn't emit open-axis rows** for open tables (e.g. C14 typed SIC) — only
  the closed cartesian; open rows would need synthesis (rare for the additivity cluster).
- **Frontend not rebuilt for a hypercube button yet**; existing buttons (Generate valid data, Generate
  Full Valid Data) are built and live.
- **Servers:** leave running or restart per the commands above. Backend restart needed after engine
  edits (no `--reload`). Detached start can take ~20-30 s — poll `/api/health`.

---

## 2026-06-22 — Phase A (real open-dim members) + Phase B (business-rule SOLVER) + UX ✅
Servers were left running (backend :8201, frontend :5173). All items below built clean
(`tsc --noEmit` + `vite build`) and verified at API/engine level; visual click-through pending.

### Headline
1. **Phase B — business-rule SOLVER (the big one).** New **⚙ Solve business rules** in the Validate
   tab: iterates **validate → solve → re-validate** via the engine `solve_loop` until the package's
   XBRL Formula assertions are satisfied (or iter-cap). **Verified E2E:** a generated **pra_mem**
   instance went **2 unsatisfied assertions → 0** in 2 iterations; solved file downloads + is
   re-validatable. Handles additivity/equality, inequality, sign, format, existence; cross-table
   aggregation tail + warm-Arelle worker remain future work. Gated to banking 4.0.0.
   - Backend `app/solve_store.py` (NEW): async job wrapping `solve_loop.run` (adds `src/` to
     `sys.path` for its bare imports; parses the loop's printed per-iter counts for before/after;
     remaining assertions from `<out>.validate.log`). Writes `<hash>/solved/<name>.solved.xbrl`.
   - Endpoints: `POST …/solve` {source,filename,iters?}, `GET …/solve/status`, `GET …/solve/file/{name}`.
     `…/validate/files` now also lists `solved` files; `validate_store._resolve` handles `solved`.
   - Frontend `Validate.tsx`: Solve button (shown when assertions unsatisfied) → progress → before→after
     + iterations + download. `api.ts` solve calls.
2. **Phase A — real members for EXPLICIT open dimensions.** Engine `taxonomy_model.build_dimension_domains`
   → `model["dim_members"]={dimLocal:[{qname,label}]}` (loads BOTH `dim.xsd` for 296 dim→domain links;
   289 explicit dims get members). `table_model.table_grid` enriches each open-axis record with
   `typed` + `members`. `model_store._active_model` splices `dim_members`/`dim_defaults`/`namespaces`
   into a reconciled model. Frontend: added open rows for an explicit dim render a **member dropdown**
   (real members) and default to a real member; typed dims keep the free input. **Proven:** the old
   synthesised integer → dim-invalid; a table-valid real member (`eba_BT:x15` for C06.02.01.01 IGS) →
   **0 dim-invalid**. *Known gap:* the global domain (16 members) is broader than a table's hypercube
   allows; auto-restricting to the table-valid subset needs per-table hypercube extraction (deferred).
3. **Amend = union of selected + uploaded tables, with functional ORIGIN.** Selecting tables (Edit,
   **amber** = author fresh) and an uploaded instance's tables (**green** = populated) now **merge**
   (deduped) instead of overwriting; each chip has a ✕ close. Origin is functional: amber tables are
   fresh/authorable even while an instance is loaded (fixes "can't create new values for a selected
   table that's also in the upload"); re-selecting an uploaded table flips it to fresh + clears its
   stale instance data once. App tracks `amendOrigins`; Amend uses `originOf`/`fromUpload`; only
   upload-origin codes are instance-seeded.
4. **Granular locking.** Beyond table lock (🔒 chip → Generate skips the table): **row / column / cell
   lock** (row & column header 🔓/🔒 toggles; select a rectangle → toolbar 🔒 Lock/🔓 Unlock cells).
   Locked = **yellow** + read-only; **Generate Data skips them**, Create XBRL still exports them.
5. **Amend populate is parallel.** Uploaded-instance grids now load with parallel `getInstanceGrid`
   (was a sequential await-loop) + per-chip ⏳; values appear as each table resolves.

### Defect fixes
- **Slow "Loaded packages" dropdown on launch** (`package_store`): `_find_manifest` was a recursive
  `rglob` over the whole extracted tree per package; `list_packages` rebuilt the full summary just
  for 4 fields. Fixed: shallow manifest lookup + a `<hash>/list.json` cache → `list_packages()`
  **~2.8 s cold → ~26 ms**.
- **Generate-then-upload only brought row 1's values** (C06.02.01.01, open axis): the Amend component
  isn't remounted on upload, so stale scratch state (extraRows/values) misaligned with the
  instance-expanded grid. Fixed: on a *new* instance, reset scratch state + seed values authoritatively
  (a `loadedFile` ref distinguishes new upload from same-instance re-render).
- **Selected tables not authorable under an upload** — see ORIGIN above.

### How to resume
```powershell
cd C:\Users\177069\ClaudeLearning\boe_xbrl_gen\studio\backend
$env:PYTHONIOENCODING="utf-8"; python -m uvicorn app.main:app --port 8201 --log-level warning
cd C:\Users\177069\ClaudeLearning\boe_xbrl_gen\studio\frontend; npm run dev   # http://localhost:5173
```
**Visual click-through still pending** (headless dev): Solve on a generated instance; member dropdown
on C06.02.01.01 open rows; row/col/cell lock (yellow) skipped by Generate; amber selected tables blank
while a green uploaded table is populated.

### Open follow-ups
- Per-table **hypercube** extraction → restrict open-dim dropdown to table-valid members (auto-valid
  open data without pruning). - Cross-table aggregation in Solve (engine `feedback.py`) + warm-Arelle
  worker (drop repeat validations from minutes to ~1 s). - Solve is banking-only (rule-URL mapping).

---

## 🛑 SESSION END 2026-06-18 — services stopped (8201 + 5173 down)

**Where we are:** Phases **0 (Ingest), 1a (Dictionary), 1b (Tables), 2 (Amend)** done, **plus**
Rules, Validate, Framework▸Entry-point scoping, upload-instance binding (incl. open axes), and
build/validate split. Everything below verified at API + build level; **a full visual click-through
is still pending** (headless dev env). Detailed dated logs are further down this file.

### Built today (2026-06-18) — headline list
1. Amend datatype restrictions (numeric/date/boolean/enum widgets + red-flag validation).
2. ENUMERATION allowed-value dropdowns (175/177 resolved from the taxonomy).
3. Generate Data (random, datatype-valid) + Create XBRL (build instance **from the package**, no sample).
4. Validation Rules tab (browse the package's formula assertions per module).
5. Framework ▸ Entry-point grouping on Dictionary/Tables/Rules + "View related rules" from a table.
6. Upload an `.xbrl` → populate/edit the grids (open axes expanded from data) → **save edits back**.
7. **Split** Create XBRL (instant build-only) from **Validate** (async Arelle, own tab) — fixed the
   C14 500.
8. Open-axis generate-from-scratch now valid (typedMember emission); Generate across all Z layers;
   add/edit open-dim value per row; **select + delete rows**.

### How to resume tomorrow
```powershell
# Backend (terminal 1) — port 8201, NO --reload
cd C:\Users\177069\ClaudeLearning\boe_xbrl_gen\studio\backend
$env:PYTHONIOENCODING="utf-8"; python -m uvicorn app.main:app --port 8201 --log-level warning
# Frontend (terminal 2)
cd C:\Users\177069\ClaudeLearning\boe_xbrl_gen\studio\frontend; npm run dev   # open http://localhost:5173
```
**First thing tomorrow:** run the visual click-through in `studio/TEST_SCENARIOS.md` (everything has
only been verified at API/build level so far). Cache holds banking 4.0.0 (model rebuilt with
enums + dim-defaults + typed-domains) and the insurance package.

### Open follow-ups (not blocking)
- **Business-rule *satisfaction*** (the solver) — currently we only *report* unsatisfied assertions.
- **Warm Arelle worker** — cache a module's DTS so repeat validations drop from minutes to ~1 s.
- **Explicit (non-typed) open dimensions** — added rows synthesise an int, not a real member (rare).
- **Add-new-fact on an empty cell** of an *uploaded* instance (needs a fresh context) — not written back.
- Per-instance reporting-context form (currently placeholder LEI/date for Create XBRL).

### New follow-ups from 2026-06-19 review (external-AI proposal cross-check)
Compared the Studio against an external AI's "taxonomy explorer MVP" proposal. Verdict: our
architecture (Arelle→FastAPI→JSON→React) and feature set already match and exceed its MVP
(we also Amend/Generate/Validate; it was read-only + export). Three net-new gaps it surfaced
that we do **not** have yet — pick up tomorrow:
- **Excel export (`.xlsx`)** — their core MVP item; we only export `.xbrl`. Likely quickest
  high-value add (dictionary rows / per-table datapoint grids → openpyxl workbook + a download
  endpoint). **Recommended starting point.**
- **Cross-version comparison** — diff package-A vs package-B (e.g. v3.0 vs v4.0): tables,
  datapoints, concepts, rules added/removed/changed. Distinct from current `reconcile.py`
  (which diffs Arelle-model vs DPM-Excel *within one package*).
- **Regulatory references / instruction text** per concept — surface instruction/reg cross-refs
  on a cell (not currently extracted).

---

## Where we are: **Phase 0 (Ingest) + 1a (Dictionary) + 1b (Tables) complete; Phase 2 (Amend) + more** ✅
*(The 2026-06-17 "first grid view UNVERIFIED" note below is superseded — those enhancements were
verified on 2026-06-18; see the dated logs.)*

## Phase 0 — complete + polished ✅ (Ingest)
Upload a taxonomy zip → extract once (cached by SHA-256) → parse manifest → show a
summary. Plus two enhancements (filename/disable/dropdown, and delete) and the 2026-06-17
polish below.

### Polish done 2026-06-17
- **Async extraction with real progress.** `POST /api/package` no longer blocks for ~4.5 min
  on a new zip: it hashes, and either returns a cache-hit summary (`{status:"ready"}`) or
  starts a background extraction thread and returns `{status:"extracting", jobId}`. New
  `GET /api/package/job/{id}` reports `{status, extracted, total, summary?, error?}`. The
  frontend polls it (~800 ms) and shows a real **`N / total files (P%)`** bar instead of an
  indeterminate spinner. A finished job resolves via the on-disk `get()` fallback; a failed
  extraction drops the half-written dir so a retry is clean.
- **`cached` chip semantic fixed.** Any package returned by `get()` (re-fetch / dropdown
  reselect) now reports `cached:true, freshlyExtracted:false` → chip correctly reads
  "cached". Only the immediate post-extraction response carries `freshlyExtracted:true`
  ("extracted now"). The old cosmetic "shows extracted-now on reselect" bug is gone.
- Stale `main.py` docstring (`--reload --port 8200`) corrected to the real `--port 8201`.
- Verified live: `tsc --noEmit` clean; banking re-fetch → `cached=true/fresh=false`, 10
  frameworks, 1098 metrics; job endpoint returns `ready` for an already-extracted id.

### Built today
- **Design docs:** `studio/PLAN.md` (fresh-start design, 4 screens, API, phases, risks);
  repo-root `CLAUDE.md` (project context, engine map, env, run commands).
- **Backend** (`studio/backend/`, FastAPI, wraps the engine in `../src`):
  - `GET /api/health`, `GET /api/packages`, `POST /api/package` (upload→hash→extract→
    cache→summary), `GET /api/package/{id}`, `DELETE /api/package/{id}`.
  - `package_store.py` — SHA-256 cache, path-traversal guard, manifest parse
    (name/version/publisher/entry points → frameworks), model counts from the prebuilt
    `model/dpm_model.json`. **Delete = rename-aside to `.trash-<id>` (instant) + background
    purge**; stale trash swept at startup. Filename stored in the `.extracted` marker and
    surfaced in the list/summary.
- **Frontend** (`studio/frontend/`, React+Vite+TS):
  - Drag-drop uploader with real upload progress; shows the **filename while manifesting**
    and **disables upload until done**.
  - Top-right **"Loaded packages" dropdown** (from cache) + **🗑 Delete** button.
  - **Optimistic delete** — dropdown entry + metrics/dimensions summary clear instantly.
  - Summary card: version/publisher/published/entry-point count, model count cards
    (metrics/dims/domains/members), framework chips, entry-points table.

### Fixes today
- **Defect: frameworks showed "(unknown)" for non-banking packages.** The framework parser
  was hardcoded to `/fws/banking/<framework>/<date>/mod/`. The **insurance** taxonomy uses
  `/data/xbrl/md/fws/insurance/<framework>/<date>/mod/` (extra `md/` segment + different
  domain), so nothing matched. **Fixed** in `package_store.py`: regex generalised to
  `/fws/<domain>/<framework>/<date>/mod/` (via `.search()`, so any path prefix is fine), and
  each entry point now also carries `domain`. No re-upload needed — restarting the backend
  re-parses cached manifests. Verified: insurance → 6 frameworks (`dis,imo,ir,mrs,sf,spv`)
  across 12 entry points; banking unchanged (10 frameworks) = no regression. The studio is
  now **taxonomy-agnostic** (banking + insurance both ingest correctly).

### Verified (real runs, not assumed)
| Check | Result |
|---|---|
| First upload of `boebanking400.zip` (56 MB) | `200`, extracted, **266 s** (one-time) |
| Cache-hit re-upload | `cached:true`, **5 s** (extraction skipped) |
| Manifest parse | BoE Banking Taxonomy 4.0.0 · 25 entry points · 10 frameworks |
| Model counts | 1,098 metrics · 374 dims · 53 domains · 5,406 members |
| `DELETE` unknown id | `404` |
| `DELETE` real package | **0.25 s**, gone from list immediately, trash purged in bg |
| Insurance package frameworks | 6 frameworks / 12 entry points (after regex fix) |
| Frontend `tsc` strict + `vite build` | pass |

---

## How to resume tomorrow

### Start the servers
```powershell
# Backend (terminal 1) — port 8201, NO --reload (see note below)
cd C:\Users\177069\ClaudeLearning\boe_xbrl_gen\studio\backend
$env:PYTHONIOENCODING="utf-8"
python -m uvicorn app.main:app --port 8201 --log-level warning

# Frontend (terminal 2) — port 5173
cd C:\Users\177069\ClaudeLearning\boe_xbrl_gen\studio\frontend
npm run dev
```
Open **http://localhost:5173** (Vite proxies `/api` → `http://localhost:8201`).

### Current cache contents (as of 2026-06-17)
`studio/backend/.cache/packages/` holds two extracted packages:
- `boebanking400.zip` — BoE Banking Taxonomy **4.0.0** (the working set; 10 frameworks)
- `boe-insurance-taxonomy-v201.zip` — BoE Insurance Taxonomy **2.0.1** (taxonomy-agnostic proof)

(First upload of a new zip re-extracts ~4.5 min, now with a live file-count progress bar;
cached re-use is instant.)

---

## Notes / decisions
- **Port is 8201, not 8200.** On Windows, `uvicorn --reload` respawns workers and left a
  **zombie socket** holding 8200. We dropped `--reload` and moved to 8201; Vite proxy +
  `CLAUDE.md` updated to match. If 8201 ever gets stuck, kill stale listeners:
  `Get-NetTCPConnection -LocalPort 8201 | %% { Stop-Process -Id $_.OwningProcess -Force }`.
- **First-extraction is slow (~4.5 min)** for the 56 MB package (thousands of small files);
  it's one-time per zip (cached). Possible future UX: lazy/background extract with progress,
  or detect the already-extracted `..\boebanking400\` copy.
- **Model counts are from the prebuilt `model/dpm_model.json`**, not built from the uploaded
  zip — per-package DPM/rule build is deliberately **deferred** to a later phase.
- Minor cosmetic: a package first ingested in the *current* process shows `cached:false` in
  the summary chip even though it's on disk (reflects ingest-time state). Harmless.

---

## Phase 1a — started 2026-06-17 (Arelle dictionary builder, **verified**)
Decision: **hybrid** — build the dictionary model from the **zip via Arelle** (taxonomy-
agnostic, no extra uploads), with an **optional DPM-Excel upload** that **reconciles** (diff +
refine) across metrics + dimensions + members. Build runs **auto after extraction**, cached.
Full design in `PLAN.md → Phase 1 — Explore (per-package, hybrid model)`.

**Built:** `src/taxonomy_model.py` — loads the package DTS via Arelle (reusing the
`tools/dump_dim_defaults.py` Cntlr/PackageManager pattern), walks `qnameConcepts` + labels,
emits the **exact `dpm_model.json` shape** (so `generate.py`/`solve.py` are untouched). XSD
item type → DPM datatype, with ambiguous numerics flagged `needs_refine`.

**Verified** (`python -m src.taxonomy_model`, one small module load, 6.6 s):
- metrics **1098 = 1098**, 0 only-in-zip / 0 only-in-Excel.
- datatype histogram matches Excel on all but **1 metric** (schema BOOLEAN vs Excel STRING).
  PERCENTAGE matched exactly (BoE uses a distinct percent item type); only `needs_refine` set
  = the 21 DECIMAL metrics (Excel agrees).
- ~~**Known gap:** members 5304 vs 5406~~ — **CLOSED 2026-06-17** (see below).

### Member gap closed (2026-06-17)
The fix is **not** to load module entry points: the big modules (pra001 182 s, pra110 142 s,
pra116 79 s) drag in heavy table/presentation linkbases — unioning all 10 frameworks gave full
coverage but took **545 s**. Instead, `build_model(extracted_dir)` now loads the **dictionary
concept schemas directly** — `met.xsd` + `dim.xsd` + every `dict/dom/*/mem.xsd` (both BoE and
EBA owner trees, ~72 files), unioned. Bare concept schemas still pull their label linkbases, so
labels resolve. Result: **metrics 1098, dims 376, domains 68, members 5442 (≥ 5406), ~37 s**,
datatypes matching Excel on all but 1 metric. Registers the **extracted dir** as the Arelle
package (studio needn't keep the zip); offline mode on. Build is one-time, cached, background.
*(Future optional optimization: a pure-lxml parse of schemas + label linkbases → a few seconds
instead of 37 s.)*

### Reconciliation built + verified (2026-06-17)
`src/reconcile.py` — diff/merge the Arelle `schema` model against the DPM dictionary Excel
(parsed via existing `dpm_model.load_dpm`). `sniff_workbook()` classifies an upload as
`dpm_dictionary` | `annotated_templates` | `unknown` (accept-either decision). Merge policy:
schema authoritative for *existence*; Excel refines **only** ambiguous numerics
(`needs_refine`), else the real XBRL type wins; Excel fills DPM-only metadata; every
disagreement still reported (UI-overridable). Output: `{summary, diffs, merged}`, `merged` in
`dpm_model.json` shape so generation is unaffected.

**Verified vs real DPM dictionary workbook:**
- metrics 1098=1098, **1 datatype conflict** (`ti761` schema BOOLEAN vs Excel STRING) → merge
  kept BOOLEAN (non-ambiguous, safe); dims 376 vs 374 (2 extra, 2 label diffs).
- members **5406=5406 distinct, 0/0 missing**, 1 label diff. Key insight: join members on a
  **normalized domain+code key** (`AP:x10003`), not raw qname — the schema redeclares **36**
  EBA-domain members under `boe_eba_XX` *and* `eba_XX` (BoE extensions); raw qname join falsely
  showed 981/945 diffs. `merged` keeps both qnames (both valid in instances); `diffs.members.
  redeclared` surfaces the 36 as a note, not "missing".

### Model API built + verified (2026-06-17)
`backend/app/model_store.py` wraps `taxonomy_model` + `reconcile` with the same background-job
+ on-disk-cache pattern as `package_store`. Cache under `<hash>/`: `model.json` (base),
`model.merged.json` (after reconcile), `model.meta.json`, `reconcile.json`, `uploads/`.
Endpoints (in `main.py`):
- `POST /api/package/{id}/model/build?force=` → start/`ready` (background thread, ~50 s server-side).
- `GET  /api/package/{id}/model/status` → `{status, counts?, elapsedMs?, reconciled, error?}`.
- `GET  /api/package/{id}/model?section=&q=&page=&pageSize=` → paginated/searchable rows
  (serves merged model if reconciled, else base); `425` while building.
- `POST /api/package/{id}/model/reconcile` (xlsx) → sniff → reconcile (dpm_dictionary) or stash
  (annotated_templates); persists merged + report. `GET` returns the saved report.
Build **auto-fires after extraction** and on cache-hit upload (`package_store._autobuild_model`).
**Verified live:** absent→building→ready (1098/376/68/5442); metric/member queries paginate;
reconcile returns the 1 datatype conflict + 36 redeclared, flips `status.reconciled→true`.

### Dictionary UI built (2026-06-17) — **Phase 1a complete** ✅
`frontend/src/Dictionary.tsx` + a header **Ingest / Dictionary** nav in `App.tsx` (Dictionary
tab enabled once a package is selected). The view:
- polls `/model/status` (kicks `/model/build` if absent) → shows a "building… ~40–50 s"
  indeterminate bar → renders when ready; count chips per section + a `reconciled` chip.
- section tabs (Metrics/Dimensions/Domains/Members), debounced search box, server-paginated
  grid (50/page, Prev/Next) via `/model?section=&q=&page=`. Metric rows show datatype with
  `refine`/`excel` tags; member rows show qname + usable/default flags.
- **Reconcile panel:** "Upload DPM workbook (.xlsx)" → `/model/reconcile`; renders per-section
  diff cards, a datatype-conflict table (with the safe-merge resolution per row), and the
  redeclared-members note. Annotated Templates uploads report "stashed for Phase 1b".
`api.ts` extended with model/status/build/query/reconcile. `tsc --noEmit` + `vite build` pass.
Merge-conflict UX = **auto-apply safe policy + show in diff panel** (no per-row flipping yet).

**Phase 1a DONE** (engine + API + UI). Servers: backend :8201 (new model endpoints),
frontend :5173 (Ingest + Dictionary).

### Insurance-package fixes (2026-06-17) — taxonomy-agnostic build
Retesting with the **insurance** package surfaced two bugs, both fixed:
- **Build produced 0 metrics for insurance.** `taxonomy_model` loaded dict schemas by canonical
  `http://` URL, which needs Arelle to register the package; registering an extracted *dir*
  is rejected ("Taxonomy package is not a zip file" → `addPackage` returns None), so the EIOPA
  schemas never remapped. **Fix:** load schemas by **local file path** (`_dict_schema_paths`),
  not URL — concepts load directly; imports/labels still resolve via META-INF/catalog.xml.
  Verified: insurance **4092 metrics / 328 dims / 72 domains / 5403 members** (labels OK,
  e.g. `s2hd_met:mi1`); banking unchanged (1098 / 5442) — no regression.
- **Phase 0 summary card showed banking counts for every package.** `package_store._model_counts`
  read the prebuilt banking `dpm_model.json`. **Fix:** it now reads the **per-package**
  `<hash>/model.meta.json` (returns None until that package's model is built), so it never shows
  another taxonomy's numbers. The Dictionary tab remains the live source of truth.

## Phase 1b — per-table datapoints (table linkbase) — engine built + validated (2026-06-17)
`src/table_model.py` parses the XBRL **Table Linkbase** (`*-rend.xml`) directly with lxml (no
heavy module-DTS load): walks breakdowns per axis (x/y/z) → `ruleNode` trees with **aspect
inheritance** (child overrides parent's concept/dimension) → datapoints = cartesian product of
axis positions (metric × dimension-members). `table:aspectNode` open axes are reported, not yet
expanded (MVP deferral). `list_tables(dir)`, `parse_table(path)`, `table_datapoints(path,model)`
(label/datatype enrichment from the dictionary model).

**Benchmarked + cross-validated (banking):**
- **286 tables parsed in ~6 s**, 182,009 datapoints total; 62 tables have open axes.
- C01.00.01.01 → **106 datapoints / 5 metrics**, *exactly* matching the independent Annotated-
  Templates Excel (`analyzer.template_datapoints`): 0 diffs either way. Inheritance verified.

### Tables API + UI built (2026-06-17)
`backend/app/table_store.py` wraps `table_model` with the job+cache pattern. Index of all
tables (code/framework/datapoint-count) built once from the extracted dir → `<hash>/tables.json`
(~6–33 s, cached); per-table datapoints parsed on demand (ms) + enriched from the dictionary
model. Endpoints: `POST …/tables/build`, `GET …/tables/status`, `GET …/tables` (grouped by
framework), `GET …/tables/{code}/datapoints?page=&pageSize=`.
Frontend: new **Tables** nav tab → `frontend/src/Tables.tsx`. Left = framework→table tree
(collapsible, per-table datapoint counts, `open` tag, filter box, totals); right = per-table
datapoint grid (Metric code+label · Datatype · one column per dimension, member codes w/ label
tooltip), paginated. Build-status poll with an "indexing…" banner. `tsc` + `vite build` pass.
**Verified live (banking):** index 286 tables / 182,009 datapoints / 10 frameworks;
C01.00.01.01 → 106 datapoints, model-enriched (e.g. mi81 MONETARY "Amount including
transitional provisions", BAS/MCY/OFS members).

### Reconcile via DPM-pack zip + top dropzone (2026-06-17)
Dictionary tab reconcile now accepts a **.zip DPM pack** (dictionary + all annotated templates),
not just a single .xlsx. `model_store.reconcile_upload` → `_reconcile_zip`: extract, sniff each
xlsx, reconcile against the DPM **dictionary** workbook, **stash the Annotated Templates** under
`<hash>/uploads/dpm/` for the Tables view. Endpoint accepts `.xlsx` or `.zip`. The upload moved
to a **prominent dropzone at the top** of the Dictionary tab (mirrors Ingest), with the diff
panel directly below; `ReconcilePanel` split into `ReconcileDrop` + `DiffPanel`.
**Verified:** posting a zip of `boebankingtaxonomydpmv400` → kind=zip, dictionary identified,
10 templates stashed, summary identical to single-file (1 datatype conflict, 36 redeclared).

### Fix: package-agnostic DPM parser (2026-06-17)
**Insurance reconcile 500'd**: `dpm_model._col_index` raised `KeyError` when a workbook lacked
a banking-only column — the Insurance Domains sheet has no `Is Nillable` → unhandled → 500.
**Fix:** `_col_index` now returns **None** for a missing column (tolerant), and the members
loop checks `c_code is None` explicitly. Missing optional columns become None fields instead of
crashing — the loader is now taxonomy-agnostic.
**Verified:** Insurance DPM dictionary parses (4093 metrics / 326 dims / 50 domains / 5403
members) and reconciles vs the Arelle insurance model — members 5403=5403 (0/0), metrics ~match
(5 only-schema, 6 only-excel, 10 datatype conflicts, 101 label diffs), 0 redeclared. No crash.

**Phase 1b optional polish (still open):** expand open (aspectNode) axes via dictionary members;
reconcile the stashed Annotated Templates against the per-table view (data now in place).

## Phase 2 — Amend: first grid view (2026-06-17)
**Select tables in Tables tab → Edit → Amend tab shows each as an editable grid.** Engine:
`table_model.table_grid(rend, model)` exposes per-axis positions (x→columns, y→rows, z→layers)
with labels; `parse_table` now also returns `axis_positions`. Backend: `table_store.grid()` +
`GET /api/package/{id}/tables/{code}/grid`. Axis-shape analysis (banking): 200 true-2D, 41
single-col, 40 single-row, **31 with a Z axis** (z up to 16, e.g. OF07.00=16).
Frontend: Tables tab gains a **checkbox per table** + sticky **"Edit N tables →"** bar (→
`onEdit(codes)`); new **Amend** nav tab (`Amend.tsx`): chip-tabs per selected table, header
(code/framework/RxC), a **Z-axis selector** (sheet picker) for z>1 tables, and the 2-D grid
(sticky row/col headers, horizontal scroll, rows paginated 25/page). **Value cells are empty
inputs for now** — binding to an uploaded instance is the next step. `tsc` + `vite build` pass.
**Verified live (banking):** C34.02 → 14×22 + 2 z-sheets; OF07.00 → 65×25 + 16 z-sheets; labels
populated from the model.

### Amend enhancements started end-of-day 2026-06-17 — ⚠ CODE WRITTEN, NOT YET VERIFIED
Edits made but **not** tsc-checked / `vite build` / backend-restarted / runtime-tested before
shutdown. **First thing tomorrow: verify these (tsc + build + restart + click through), they
may have errors.**
- **Engine** `table_model.py`: `parse_table` open-axis records now carry `axis` (x/y/z) — so the
  UI knows whether an open table needs row-adds or column-adds. (Backend restart needed.)
- **`Amend.tsx`** added: ⛶ **Full-screen** toggle (`.amend-table.full` fixed overlay);
  **white editable cells** (`.cell-input` now `#fff`/`#111`); **`+ Add row` / `+ Add column`**
  for open axes (client-side `extraRows`/`extraCols`); **wrapping row/column headers** (CSS
  `white-space: normal; overflow-wrap: anywhere`) so long labels are fully readable; **Z label
  echoed** below the dropdown (`.z-current`) since the `<select>` truncates long option text.
- **`styles.css`**: `.grid-toolbar`, `.amend-table.full`, white `.cell-input`, wrapping headers,
  `.z-current`.

---

## 2026-06-18 — Sections A & B done ✅
- **A. Amend enhancements verified.** The end-of-day edits had **one real bug**: `Amend.tsx`
  read `o.axis` on open-axis records but the `openAxes` TS type in `api.ts` lacked `axis` →
  `tsc` error TS2339 (×2). **Fixed:** added `axis?: string` to both `openAxes` type defs
  (TableDatapoints + TableGrid). `tsc --noEmit` + `vite build` now clean. Backend restarted;
  grid endpoint confirmed emitting the axis tag — `CL66.02.01.01` 230×107 (open **z**),
  `C14.01.01.01` 0×24 (open **y** → "+ Add row"), `OF07.00.01.01` 65×25×16 z-sheets.
- **B1. Pagination removed.** `Amend.tsx` no longer slices by `ROWS_PER_PAGE`/pager — renders
  **all rows** in the single scrollable `.grid-scroll` (sticky headers). Hint shows row count.
  *(Perf note: CL66 is 230×107 ≈ 24.6k `<input>`s — acceptable but a candidate for windowing
  if it feels sluggish in-browser.)*
- **B2. Resizable rows & columns.** Switched the grid to `table-layout: fixed` + a `<colgroup>`
  whose widths come from `colW`/`headW` state; drag handles (`.col-resizer` on every header
  edge, `.row-resizer` on each row header) update width/height via a shared `dragResize` mouse
  helper. Row-label text clips (`.rowhead-inner` maxHeight) when a row is shrunk, so long
  headers can be ignored. `cell-input` now `width:100%` to fill the fixed column.
- Servers running: backend :8201 (restarted), frontend :5173. **Visual click-through is the
  user's to do** (headless here): full-screen toggle, white cells, drag-resize, +Add on C14, Z
  selector on OF07.

## 2026-06-18 — Amend grid enhancements (3 user requests) ✅ built, awaiting visual check
1. **Header-row height resizable.** Corner cell now has *two* handles: `.col-resizer` (right edge →
   row-label width, existing) **and** a new `.row-resizer` (bottom edge → `headerH` state). Column
   header labels wrapped in `.th-inner` whose `maxHeight` clips when the header is shrunk.
2. **Multi-cell select + paste from Excel.** Cells are now **controlled** (`values` map keyed
   `${z}:${r}:${c}`, so each Z-sheet keeps its own values). Rectangular selection via mousedown
   anchor + mouse-enter focus drag (shift-click extends); highlighted via `td.cell-sel`. During a
   drag the grid sets `.selecting` (`user-select:none` + `pointer-events:none` on inputs) for clean
   rubber-banding. `onPaste` on `.grid-scroll` parses clipboard **TSV** (`\n` rows, `\t` cols),
   `preventDefault`s the default single-input paste, and fills from the selection's top-left,
   clamped to grid bounds; selection then expands to the pasted block.
3. **Datatype, hideable.** Engine `table_grid` now enriches every position with `datatype`
   (from `model.metrics[code].datatype`); `GridPosition.datatype?` added in `api.ts`. A **Show/Hide
   datatypes** toggle (shown only when a row- or column-axis carries a metric) renders the datatype
   as a `.dtype` sub-line **inside** the sticky column/row header — chosen over a literally separate
   grid row/column so it stays aligned + sticky without colgroup/index churn. **Verified via API:**
   C01.00.01.01 → metric on **rows** (row-dt MONETARY); C14.01.01.01 → metric on **columns**
   (col-dt STRING) — both header paths exercised.
- `tsc` + `vite build` clean; backend restarted (port 8201) to load the `table_model.py` datatype
  change; dev server HMR serving the new UI.
- ⚠ **Visual click-through still pending** (headless here): header-height drag, range-select +
  Ctrl+V paste from Excel, datatype toggle on C01 (rows) and C14 (cols). Perf watch: selection drag
  re-renders the whole grid each mouse-enter — fine on small tables, may lag on CL66 (230×107);
  windowing remains the noted follow-up.

## 2026-06-18 — Datatype input restrictions on Amend cells ✅ built + verified (engine/API)
**Distinct datatypes across packages = 8:** MONETARY, ENUMERATION, STRING, PERCENTAGE, INTEGER,
BOOLEAN, DATE, DECIMAL (same set in banking/insurance/DPM-Excel). Decisions: **hybrid**
enforcement + **build enumeration dropdowns now**.
- **Engine — enumeration allowed-values** (`taxonomy_model.build_enumerations`): BoE uses
  Extensible Enumerations **1.0** (`enum:` ns); each enum metric carries `enum:domain` (head) +
  `enum:linkrole` (the domain-member network whose usable members are its allowed values). Key
  finding: that network only attaches when the domain `hier.xsd` is loaded as a **primary entry**
  — a secondary `ModelDocument.load` of EBA schemas silently drops their linkbaseRefs (cost me a
  long debug; also: EBA domain dirs are **lowercase** `dom/as/` while role URIs are uppercase
  `/dom/AS/AS1`). So we map each enum→its domain hier.xsd by (host, domain-token) and load only
  those as primary entries. **Resolves 175/177 enums in ~30 s** (the 2 misses: a CU/currency enum
  on the standard link role, and a `model:met`-domain enum — both still typed ENUMERATION, just no
  dropdown). `model["enumerations"] = {metricCode:[{qname,label}]}`; `table_grid` attaches
  `enumValues` to positions; `model_store._active_model` splices enumerations from the base model
  into a reconciled/merged model (which has none).
- **Frontend — hybrid restrictions** (`Amend.tsx`): per-cell datatype = row ?? col ?? z position's
  datatype. Widgets: `<select>` for ENUMERATION (from `enumValues`, value = member qname) &
  BOOLEAN, `<input type=date>` for DATE, numeric-`inputMode` text for MONETARY/DECIMAL/PERCENTAGE/
  INTEGER, free text for STRING. `validateCell()` flags off-type / disallowed-enum values with a
  red outline + tooltip (blank always allowed); runs on edit **and paste**, so a bad Excel paste
  highlights offending cells. `GridPosition.enumValues` + `EnumValue` added to `api.ts`.
- **Verified:** model rebuilt (force) → 175 enumerations; live grid API returns enumValues
  (C06.02.01.01 "Type of entity" → 14 options incl. eba_ZZ:x44 "Credit institution"; BR01.00.01.01
  "Governing Law" → 252; C14.00.01.01 "Scope of issuance" → 3). `tsc` + `vite build` clean;
  backend restarted on 8201.
- ⚠ **Visual click-through pending** (headless): open an enum table (e.g. C06.02.01.01) → toggle a
  cell dropdown; type a bad number in a MONETARY cell → red outline; paste a bad value.
- *Build cost note:* model build is now ~37 s (dict) + ~30 s (enums) ≈ **~70–110 s**, one-time,
  cached, background.

## 2026-06-18 — Phase 2 Generate + Create XBRL (from the package, no sample) ✅ built + verified
User asked: (1) Generate random datatype-safe values for selected tables; (2) use the taxonomy's
own business rules via Arelle (NOT the separate validations workbook); (3) export a new .xbrl for
selected tables preserving package schema. **Decision (user): build the instance from the uploaded
package alone (no sample/seed file), type/structure-valid + Arelle report, placeholder reporting
context.** (The 25 on-disk sample instances were never an upload, so they're not used.)

### Where business rules come from (the #2 answer)
The package ships **XBRL Formula `valueAssertion` linkbases** (`…/val/aset-*.xml`, `vr-*.xml` —
11,376 files); Arelle evaluates them on `--validate`. (`src/formula_rules.py` already parses them;
`solve*/feedback.py` already satisfy them — full satisfaction deferred to a later phase.)

### Engine — `src/instance_build.py` (NEW)
Assembles an instance with **no sample**: `module_index()` parses `mod/*.xsd`
(`schemaLocation="../tab/<code>/…"`) → table→module + the http `schemaRef`. `build_instances()`
groups selected tables by module and builds one instance each: contexts deduped by (period, dims)
with **dimension-default members omitted**, units uGBP (MONETARY) / uPURE (other numerics), filing
indicators = template codes (table code minus the last `.NN`), facts (`@decimals`, enum value =
member qname). `validate()` runs Arelle offline against the cached `source.zip`; `prune_invalid()`
drops facts Arelle flags `xbrldie:PrimaryItemDimensionallyInvalidError` (the table cartesian
over-generates greyed cells); `parse_report()` → {dimInvalid, valueErrors, assertionsUnsatisfied
[{id,count,message}], otherErrors, ok}.
- **Model additions (taxonomy_model):** `namespaces` (prefix→URI, to emit valid XML),
  `dim_defaults` (dimension→default member, to omit). Model rebuilt (~62 s warm).
- **Gotchas solved:** enum FACT values are member qnames → their prefix must be declared too;
  the naive row×col×z cartesian yields ~48/207 dimensionally-invalid cells on dimensioned modules
  (e.g. lvr002) → pruned via Arelle; facts deduped by (concept, context).

### Backend — `app/instance_store.py` (NEW) + endpoints
Job pattern (Arelle is slow): `POST …/generate` {selection:{CODE:[{concept,dims,datatype,value}]},
lei?,scheme?,date?,validate?} → background build+validate+prune; `GET …/generate/status` →
{status, result{instances[],unmapped,validated,validationNote,opts}}; `GET …/generate/file/{name}`
→ downloadable .xbrl. `package_store` now persists the upload as `<hash>/source.zip` (existing
banking pkg migrated by copying the repo zip — its hash == the cache dir name).

### Frontend — `Amend.tsx` (values lifted to component level)
**Generate Data** fills every datapoint cell of all selected tables with datatype-valid random
values (enum→random allowed member, boolean, date, numeric, string), visible/editable; values now
persist per table across tab switches. **Create XBRL** builds the selection from grid positions
(metric + merged row/col/z dims), POSTs, polls, and shows a result panel per instance: module,
facts, dropped-invalid count, **download link**, ✓structurally-valid badge, and the list of
business-rule assertions not satisfied. `api.ts` extended (Datapoint/GenerateResult/…).

### Verified live (real Arelle runs)
| Module | built | pruned | final report |
|---|---|---|---|
| pra_mem (3 tbl) | 43 facts | 0 | ok=True, 2 assertions (b1_m,b2_m) |
| lvr002 (5 tbl, dimensioned) | 207 facts | 48 dim-invalid | ok=True, 15–22 assertions |
- Frontend-path (grid-based selection) E2E ✓; download endpoint returns BOM+decl .xbrl; `tsc` +
  `vite build` clean; both servers up (8201 / 5173).
- ⚠ **Visual click-through pending** (headless): Tables→tick→Edit→**Generate Data**→**Create XBRL**
  → download + read the report. Note: big modules (PRA001) build many facts → Arelle may take
  minutes (job is async). Gated to **banking 4.0.0** in practice (module/sample data); the builder
  itself is taxonomy-agnostic.

### Phase-2 follow-ups (not this pass)
Full business-rule *satisfaction* (the solve loop) as an opt-in; open-axis (typed-dimension) row
generation; per-instance reporting-context form (currently placeholder LEI/date); multi-module
download-all (each instance already downloads individually).

## 2026-06-18 — Validation Rules tab (browse the package's business rules) ✅ built + verified
User chose **Option B** (show the business rules in a tab) over Option A (solver-backed valid
data). New read-only **Rules** tab listing the package's XBRL Formula `valueAssertion`s — the rules
Arelle evaluates — per module, with the human message + formal XPath test + tables touched.
- **Engine — `src/rules_model.py` (NEW):** `mod/<module>.xsd` → its `aset-*.xml` assertion sets →
  each aset gives the **table(s)** it applies to (`../tab/<code>/<code>-rend.xml#…`) and the
  **rule(s)** (`vr-<id>.xml#<label>`). Rule `{id, test, severity}` read by a **lean `iterparse`**
  extractor (NOT `formula_rules.parse_file` — it builds the full variable/filter graph, far too slow
  on the 39 MB cross-table vr files); human message from `vr-<id>-err-en.xml`. Deduped by id; tables
  unioned. **PRA001 = 1448 rules (889 ERROR / 559 WARNING), all with messages, ~120 s** (lean parse,
  down from ~260–540 s with the full parser); small modules seconds. One-time, cached.
- **Backend — `app/rules_store.py` (NEW)** + endpoints: `GET …/rules/modules` (25 modules + framework
  + table count), `POST …/rules/build?module=`, `GET …/rules/status?module=`,
  `GET …/rules?module=&q=&table=&page=` (paginated, searchable by id/message/test, filterable by
  table). Job+cache per module (`<hash>/rules-<module>.json`).
- **Frontend — `Rules.tsx` (NEW)** + **Rules** nav tab: module dropdown → builds/loads (spinner while
  building) → table of rule id · severity badge · tables · human message + collapsible formal test;
  debounced search + table-code filter + pager.
- **Verified live:** modules=25; pra_mem build 0.8 s → 2 rules (b1_m/b2_m with messages/tables);
  search `q=b2` → 1 rule; table filter `FS701.00.01.02` → b2_m. PRA001 rules pre-warmed. `tsc` +
  `vite build` clean; backend + frontend up.
- ⚠ **Visual click-through pending:** Rules tab → pick `pra001` (≈2 min first time, then instant) →
  browse/search the 1448 rules; expand "formal test" to see the XPath. *Perf note:* PRA001's ~2 min
  is dominated by three 19–39 MB vr files; could early-exit iterparse after the assertion element as
  a future optimization.

### Deferred (was Option A) — solver-backed "Generate valid data"
Make Generate produce rule-satisfying data (offline additivity/sign propagation via `solve.solve`
over the now-collectible ruleset + bounded Arelle feedback for the cross-table tail). Plan is in the
conversation; the Rules tab makes its pass/fail report meaningful. Also still open: a persistent
warm-Arelle worker (cache the module DTS so repeat validations drop from ~40 s to ~1 s).

## 2026-06-18 — Framework ▸ Entry-point grouping on Dictionary / Tables / Rules ✅ built + verified
A reusable **Framework (group 1) ▸ Entry-point/module (group 2)** picker (each with "All") scopes
the three tabs. Decisions: Dictionary filters to **concepts USED by the scope**; Rules keeps a
**required entry-point** (framework just filters the module list).
- **Shared scope index — `app/scope_store.py` (NEW) + engine reuse:** parses every table once
  (~30 s, cached `<hash>/scope.json`) → `framework → entry-points(modules) → {tables, and the
  metric/dimension/domain/member codes those tables USE}`. Module mapping from
  `instance_build.module_index`; used-concepts from `table_model.parse_table` datapoints.
  Endpoints: `GET …/scope` (framework▸entry-point tree), `…/scope/build`, `…/scope/status`.
  Verified: **10 frameworks**; e.g. leverage = 13 tables, lvr002 = 6.
- **Scope filters wired into existing endpoints:** `GET …/model?framework=&entryPoint=` filters the
  dictionary rows to the scope's used codes (verified: full 1098 metrics → pra_mem 12; full 5442
  members → lvr002 22); `GET …/tables?framework=&entryPoint=` filters the table tree (286 → leverage
  13 → lvr002 6) — fixed `nTables`/`nDatapoints` totals to reflect the filtered set.
- **Frontend — `ScopePicker.tsx` (NEW)** (two dropdowns, "All …" options; entry-point list follows
  the chosen framework; `requireEntryPoint` mode for Rules) wired into **Dictionary** (filters +
  "showing only concepts used by …" note), **Tables** (reloads the framework-grouped tree for the
  scope), and **Rules** (replaced its bespoke module dropdown — entry-point = the module). `api.ts`:
  `getScope` + scope params on `queryModel`/`getTables`.
- `tsc` + `vite build` clean; backend + frontend up. ⚠ **Visual click-through pending:** on each tab
  pick a framework → entry-point and confirm the data scopes; Dictionary "All/All" = full dictionary.

## 2026-06-18 — "View related rules" (table → its rules) + Table filter on Rules ✅ built + verified
From the **Tables** tab, a selected table gets a **⚖ View related rules** button → jumps to the
**Rules** tab pre-filtered to that table; cross-table rules also surface the *other* tables they
impact. Rules gains a **Table** filter as a third grouping level (Framework ▸ Entry-point ▸ Table).
- **Backend:** scope tree now carries each entry-point's `tables` (rebuilt at read-time from
  scope.json `modules`, no rebuild needed); new `GET …/scope/resolve?table=CODE` →
  `{framework, entryPoint, table}` (a table's primary = largest module containing it). The existing
  `/rules?...&table=` filter does the touch-matching.
- **Frontend:** `ScopePicker` gained an optional **Table** dropdown (`showTable`, scoped to the
  chosen entry-point's tables). `Rules` accepts `initialTable`, resolves it via `/scope/resolve`,
  pre-sets Framework ▸ Entry-point ▸ Table, and highlights the focus table in each rule's table list.
  `Tables` got the **View related rules** button (passed `onViewRules` from `App`); App routes
  table→Rules and keys `Rules` by table so re-clicks re-focus.
- **Verified live:** resolve `C01.00.01.01`→pra001, `FS701.00.01.01`→pra_mem; pra001 rules touching
  **C01.00.01.01 = 38 (12 cross-table)**, e.g. `boe_b0787` → {OF02, C03, C01}. `tsc` + `vite build`
  clean; backend + frontend up. ⚠ visual click-through pending.

## 2026-06-18 — Section C: bind an uploaded XBRL instance to the grids ✅ built + verified
Upload an `.xbrl` (for the selected package) → its real reported values populate the table grids,
viewable + **editable**, and edits **write back into the uploaded file** (entity/period/contexts/
units preserved). Decision: write-back (faithful), not fresh re-export.
- **Backend — `app/instance_data_store.py` (NEW):** parses the upload via engine `instance.py`;
  builds a fact index keyed by `(metric code, {dim code → member code})` with dimension defaults
  dropped (instances omit them); resolves module (schemaRef) + reported tables (filing indicators →
  module tables). `table_values(code)` matches each grid cell's `(metric × row/col/z members)` →
  `{value, fi}` keyed `z:r:c`. `save(edits {fi→value})` re-parses the stored file, sets those facts'
  values in place, writes, returns bytes. Endpoints: `POST/GET/DELETE …/instance`,
  `GET …/instance/values/{code}`, `POST …/instance/save` (download).
- **Frontend:** `Tables` got an **⬆ Upload data (.xbrl)** control → on success auto-opens the
  reported tables in **Amend**. `Amend` pre-fills cell values from `…/instance/values/{code}`
  (remembers each cell's `fi` + original value), and a **💾 Save edited instance** button posts only
  the changed cells (those backed by an existing fact) and downloads the edited file. `api.ts`:
  upload/info/clear/values/save.
- **Verified live (against the real on-disk PRAMEM sample):** upload → module pra_mem, 43 facts/43
  indexed/0 typed, reported FS700/FS701 tables; `FS701.00.01.01` → **19 matched cells** with real
  values; save edit (mi170 9072000→999999) → downloaded file has the new value with unit/decimals/
  contextRef intact and all 72 contexts + entity scheme preserved. `tsc` + `vite build` clean; test
  instance cleared. ⚠ visual click-through pending.
- **Limitations (v1):** editing an **empty** cell (no existing fact) isn't written back (adding
  a fact needs a new context — use Create XBRL for a fresh instance, or a follow-up).

### 2026-06-18 — OPEN-AXIS expansion from the uploaded instance ✅ (was the show-stopper)
Open (typed/explicit) axes are now expanded from the **instance's own facts**: their distinct
typed/open-dimension value-tuples become the rows/cols, so filed data on open tables populates.
- Engine/backend (`instance_data_store`): `upload` now merges typed members into each fact's
  `{dim→value}` map and stores `facts.json`; new `instance_grid(code)` takes the closed grid
  (`table_store.grid`) and, for each open axis, derives positions = distinct open-dim tuples among
  the table's facts (cartesian with any closed positions), then matches every cell → `{value, fi}`.
  Endpoint `GET …/instance/grid/{code}` returns the expanded grid (TableGrid shape) + values.
- Frontend: `Amend` pre-fetches `instance/grid` per table (instead of values-only) and passes the
  **instance-expanded grid** to `AmendTable` via a new `presetGrid` prop (skips the closed
  `getTableGrid` fetch when an instance is loaded). Save write-back unchanged (by `fi`).
- **Verified live (RFB002 sample, 160 typed facts):** `SR802.01.02.01` → 2 rows (INC=1,2);
  `SR802.02.02.01` → 4 rows (INC×GCC); `SR99.01.01.01` → **16 rows** (4 typed dims), all cells
  matched; closed `SR800.00.02.01` still works; write-back on an open-table fact (2558→7777777)
  preserved all 84 typed members + structure. `tsc` + `vite build` clean; servers up; instance cleared.

### (legacy) C — bind value cells to an uploaded instance: ✅ DONE (see entry above)
Load `.xbrl` → map facts to grid cells (metric × row/col/z aspects) → edit → write back →
download. Reuse engine `instance.py`. See section C below + `PLAN.md`.

### 2026-06-18 — Split Create XBRL (build) from Validate (Arelle) + Validate tab ✅
Root cause of the C14 "generate status 500": the generate job did build **and** Arelle
validate+prune+confirm inline; for C14 (module = the huge `pra001`) the Arelle step dominated/failed
and surfaced through the status read. Fix = separate them.
- **Backend:** `instance_store.generate` is now **build-only, synchronous, no Arelle** (instant; per-
  module build errors reported via `errors`, never fatal — `build_instances` wraps each module).
  New `app/validate_store.py` runs Arelle **async** on a chosen file (generated or uploaded):
  validate → prune dim-invalid → parse report → cache report + cleaned file. Endpoints: `POST
  …/generate` (returns built instances immediately), `GET …/validate/files`, `POST …/validate`,
  `GET …/validate/status`, `GET …/validate/file/{name}`. All status paths return status:"error" with
  a message — no 500s.
- **Frontend:** Amend **Create XBRL** = instant build-only (download links, no Arelle wait). New
  **Validate** nav tab (`Validate.tsx`): pick a built/uploaded file → Validate → persistent progress
  (survives tab switches; job is server-side) → report (✓valid / dim-invalid / value-errors /
  business-rule assertions) + cleaned-file download.
- **Verified live:** C14 (pra001) **build-only in 7.6 s, no 500**; separate validate of a pra_mem
  build → ready, 2 assertions; validate/files lists generated + uploaded. `tsc` + `vite build` clean.
- **Known gap (next):** open-axis **generate-from-scratch** — "+ Add row" adds a blank row without the
  open dimension's value, so generated open rows aren't valid datapoints. Needs a synthesized/entered
  open-dim value per added row + typedMember emission in `instance_build`. (Upload→populate already
  handles open axes.)

## 2026-06-18 — Z/open-axis generate fixes + row select/delete ✅
- **Bug: Generate Data filled only "Row 1" for added open rows.** "+ Add row" stored rows in
  AmendTable-local state, but Generate ran at the parent over the base grid only. **Fixed:** lifted
  extra rows/cols to `Amend` (per code); Generate Data + Create XBRL now include added rows/cols
  **across every Z layer** (and merge over existing edits).
- **Open-axis generate-from-scratch now produces VALID datapoints.** Engine: `taxonomy_model` captures
  each typed dimension's **typed-domain element** (`dimensions[D].typedDomain`, e.g. INC→`eba_typ:CC`;
  85/85 typed dims); model rebuilt. `instance_build` emits `<xbrldi:typedMember>` (vs explicitMember)
  for typed dims, declaring the typed-element prefix. Frontend: "+ Add row/col" **synthesises an
  editable open-dimension value** per open dim (sequential int; shown as `INC=1` inputs in the row
  header) → flows into `buildSelection` → valid facts. **Verified:** SR802 + added row INC=1 → emits
  the typedMember and Arelle reports **0 dim-invalid / 0 value errors / 0 assertions**.
- **Select + delete rows.** Checkbox per row + "🗑 Delete N rows" (toolbar); deleted display-rows are
  hidden and excluded from Generate Data + Create XBRL (`deletedRows` set lifted to `Amend`).
- `tsc` + `vite build` clean; backend restarted + model rebuilt (typedDomain); servers up.
- **Remaining open-axis edge:** explicit (non-typed) open dimensions synthesise a sequential int
  rather than a real member (rare in banking; user can edit). Typed open dims (the common case) fully
  handled.

## 🛑 SESSION END 2026-06-17 — servers stopped (8201 + 5173). RESUME PLAN:

### A. First: verify the un-verified Amend enhancements (above)
`cd studio/frontend && npx tsc --noEmit && npm run build`; restart backend (port 8201, no
--reload); restart `npm run dev`; open Tables → tick a table (try open one like
`C14.01.01.01`/`CL66.02.01.01`, and a Z one like `OF07.00.01.01`) → Edit → check full-screen,
white cells, +add on open axes, wrapping headers, Z label.

### B. Bugs to FIX tomorrow (reported by user)
1. **No pagination in the Amend table** — remove the 25/page pager; render **all rows/datapoints
   in a single scrollable view** (the grid already has `overflow:auto` + sticky headers, so drop
   `ROWS_PER_PAGE` slicing in `Amend.tsx` and show every row). Watch perf on big tables
   (CL66 ~230×107, OF07 65×25×16) — may need windowing/virtualization if sluggish.
2. **User-resizable rows & columns (both directions)** — let the user drag to resize column
   widths and row heights in the Amend grid, so they can shrink cells and ignore long header
   text. (CSS `resize`/drag handles, or a lightweight approach: `th { resize: horizontal }` +
   row-height control; verify cross-cell alignment with sticky headers.)

### C. Then continue Phase 2 development
Bind value cells to an **uploaded instance** (the actual amend): load `.xbrl` → map facts to
grid cells (metric × row/col/z aspects) → edit → write back → download. Reuse engine
`instance.py`. Also still open from 1b: friendlier row/col headers via the stashed Annotated
Templates; expand open-axis member enumeration; reconcile templates vs per-table view.

Also: Home guide softened to not name specific taxonomies; build banner now names the actual
package being built (was confusingly mentioning "Insurance").

## Next up
1. **Phase 1 — Explore (read-only)** *(recommended next, now fully designed)*: see
   **`PLAN.md` → "Phase 1 — Explore: all datapoints for a Template / entry point"**.
   Frameworks→tables tree; per table show datapoints (row/metric/dimension members, labelled
   + datatyped via `dpm_model.json`) joined with the validation rules that touch it. Reuses
   `analyzer.analyze` + `template_datapoints`. New API: `GET /api/package/{id}/templates`,
   `GET /api/package/{id}/templates/{code}/datapoints`. **Key caveat:** those engine
   functions read on-disk banking 4.0.0 workbooks (hardcoded), not the uploaded zip — so
   gate Explore to banking 4.0.0 and label it as reference data (per-package ingest deferred).
2. ~~Phase 0 polish~~ — **done 2026-06-17** (async extraction progress + `cached` chip fix).
3. Later: Phase 2 (Amend — editable fact grid), Phase 3 (Validate loop), Phase 4 (niceties).

## File map (studio/)
```
studio\
  PLAN.md             design + phases
  SESSION_STATUS.md   this handoff
  backend\
    requirements.txt
    app\  main.py  config.py  package_store.py  __init__.py
    .cache\packages\<sha256>\   extracted packages (gitignore-worthy)
  frontend\
    package.json  vite.config.ts  tsconfig.json  index.html
    src\  main.tsx  App.tsx  api.ts  styles.css
```
