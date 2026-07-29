# Session 2026-06-24 — PRA001 valid-instance: dimensions fixed, business-rule solving (single-table)

**Goal:** produce a PRA001 XBRL instance that uploads clean to **TDG Beacon** — first dimensionally
valid, then satisfying as many **business (formula) rules** as feasible.

**User workflow:** I (Claude) generate + measure locally; user uploads to TDG and shares the error
breakdown. **Next: user uploads the current file tomorrow and shares results.**

---

## 2026-07-01 (cont.) — OF08 cross-table: b0745 diagnosis + b0814/b0752 FIXED
**TDG breakdown (real) on OF08 template.** Findings + fixes:
- **b0745 (& 22-rule r0010 cluster) — DIAGNOSED, not fixed (accepted).** Exact RREF solve satisfies ALL 697
  b0745 eqs → system IS consistent, but that solution needs **1,902 negatives (21.5%)** in OF08.01. The
  93 failures are the deliberate **no-negatives-over-additivity** tradeoff (r0010 shared by 22 rules; can't
  satisfy b0745 without negatives, which TDG's own ≥0 rules would flag as ~1,902 NEW errors). Root cause:
  r0010 has multiple decompositions → random generation can't produce a consistent cross-classification.
  Proper fix = coordinated matrix generation (deferred). **Recommendation: keep no-negatives; accept the 93.**
- **b0814 (21 cross-table) + b0752_NN — FIXED.** Pattern `OF08.01 r0070 cX = isum(OF08.02 cX)` per z. Failed
  because open synth was single-z (OF08.01 spans all z) + open-dim key mismatch (rule resolves OF08.02 cell
  without the OGR dim; synth cell carries it). Fix (2 parts): **(1) multi-z open synth** — `_synth_open_rows`
  now emits one row PER z-layer; **(2) `_crosstable_open_link`** — derives the open (synth) source cell from
  the closed target, matching on CLOSED dims (typed/open dims wildcarded), no negatives, only the open synth
  cell moves (closed Stage-1 table read-only). **VERIFIED: b0814_08/20 17/17, b0752_36 17/17; b0745 unchanged;
  50,101 facts, 0 neg, 0 dim-invalid.** File shipped (36 MB).
- **b0368/b0369 — NOT fixed (next class).** Cross-table INEQUALITY (`OF08.01.01.02 ≤ OF08.01.01.01`) between
  two CLOSED tables. Needs cross-table inequality handling; both sides Stage-1-owned → harder.

### Files changed 2026-07-01 (cont.)
- `studio/backend/app/genvalid_store.py` — `_synth_open_rows` multi-z (row per z); NEW `_crosstable_open_link`
  (closed-dim-matched open-source derivation, prefers rv values); wired into `_run` (`job["openLink"]`).

## 2026-07-02 (cont.) — JOINT OF08.01.01.01+02 solve → cross-table inequalities b0367/b0368/b0369 FIXED
TDG surfaced cross-table inequalities `OF08.01.01.02 (off-balance/CCR) ≤ OF08.01.01.01 (overall)` (b0367/
b0368/b0369). Both are CLOSED tables solved independently, so magnitudes didn't line up (overall came out
1k–5k while off-balance was millions). Fix: solve the two tables **JOINTLY** in one non-negative LP with the
cross-table `≤` rules as constraints spanning both tables' cells — the LP raises the overall cells to cover
off-balance while keeping BOTH tables' internal additive + inequality rules and 0 negatives.
- NEW `_crosstable_le_rows`: extracts multi-table `≤`/`≥` rules whose cells ⊆ the solved-table set (scope-
  expanded, iabs dropped since ≥0), as `Σ coef·x ≤ rhs`. Added to `_nonneg_additive_solve`'s `le_rows`.
- `_NONNEG_TABLES` default now `OF08.01.01.01,OF08.01.01.02` (joint).

### VERIFIED (regen ~811 s) — combined LP FEASIBLE, whole OF08.01 cluster clean
| Class | Result |
|---|---|
| Cross-table ineq b0367/b0368/b0369 (all 16 codes) | **0 violations** ✅ (incl. b0368, earlier deferred) |
| Additive b0745 / b0744 (TDG) | 652/652 · 635/635 ✅ |
| Single-table ineq (b1037…b0306) | 0 violations ✅ |
| Cross-table b0814 / b0752 | 17/17 ✅ |
| Negatives · dim-invalid · booleans | 0 · 0 · 0 |
File shipped (36 MB, 50,101 facts). nonnegSolve 10,413 → 10,606 (OF08.01.01.02 folded in).

### Files changed 2026-07-02 (cont.)
- `studio/backend/app/genvalid_store.py` — NEW `_crosstable_le_rows`; `_nonneg_additive_solve` adds cross-table
  ≤ rows to the joint LP; `_NONNEG_TABLES` default += OF08.01.01.02.

## 2026-07-02 — OF08.01 FULL rule set satisfied (added inequalities to the non-negative solve)
TDG on the b0745-fixed file surfaced OF08.01 INEQUALITY failures — the non-negative solve satisfied the
additive EQUALITIES but ignored the ≤ rules the old pipeline had handled: ≤0 pins (b1037 c0102, b1038 c0103,
b0306 many cols), cell≤cell (b1036), row≤row (b0378 r0017≤r0010, b0379 r0200≤r0190), |cell|≤|cell|
(b0684, b0380), |Σ|≤cell (b0683).

### Fix
`_nonneg_additive_solve` now takes `le_constraints` (from `_constraint_values`) and adds those referencing
only the table's cells as LP inequality rows `Σ coef·x ≤ rhs` (≤0 pins → x=0 with x≥0). HARD solve of
{equalities + inequalities + ≥0}; SOFT-slack fallback (penalised) if a component is infeasible so additivity
+ ≥0 stay hard. Passed `le_constraints` through the `_run` call.

### VERIFIED (regen ~600 s) — OF08.01.01.01 satisfies its ENTIRE rule set, all at once
| Class | Result |
|---|---|
| Additive b0745 / b0744 | 652/652 · 635/635 ✅ |
| Inequalities b1037/b1038/b1036/b0683/b0684/b0380/b0379/b0378/b0306 | **ALL 0 violations** ✅ |
| Cross-table b0814_08 / b0752_36 | 17/17 ✅ |
| Negatives · dim-invalid · booleans | 0 · 0 · 0 |
Combined LP was FEASIBLE (no soft fallback). File shipped (36 MB, 50,101 facts). New tool `tools/check_ineq.py`
(evaluates plain `<=`/`abs`/`isum` comparison rules — `check_rules.py` only reads `i`-prefixed additive).

### Files changed 2026-07-02
- `studio/backend/app/genvalid_store.py` — `_nonneg_additive_solve(…, le_constraints)`: inequality rows +
  soft-slack fallback; `_run` passes `le_constraints`.

## 2026-07-01 (cont. 2) — b0745 FIXED via NON-NEGATIVE additive solve (earlier "unfixable" was WRONG)
**CORRECTION of a prior wrong conclusion.** I had claimed b0745 needed 1,902 negatives / was unfixable
without a matrix redesign. That was WRONG — the 1,902 negatives were an artifact of the exact solver's
random-free-variable + arbitrary-pivot choice, NOT a necessity. Proven with an LP: a NON-TRIVIAL all-≥0
solution satisfying EVERY OF08.01 additive rule exists (total 1.095e9, 0 negatives).

### Fix (implemented)
NEW `_nonneg_additive_solve` (`genvalid_store.py`): for the over-determined 2-D exposure tables
(`_NONNEG_TABLES`, default `OF08.01.01.01`), solve their single-table additive rules as an LP —
variables = the table's generated numeric cells (≥0), isNull cells fixed 0, each additive equation exact,
objective = L1-close to varied positive targets. Feasible region is non-empty → all rules hold, 0 negatives;
rounds to integers exactly (±1 additivity). scipy HiGHS, ~264 s.
**CRITICAL ORDERING:** runs AFTER the cross-table aggregation (so that net-positive-override pass can't
clobber the b0745-consistent values — that mistake made b0745 WORSE, 93→134, in the first attempt) and
BEFORE the open-link (so OF08.02 calibrates to the FINAL OF08.01 r0070).

### VERIFIED (regen ~695 s)
| Rule | Result |
|---|---|
| **b0745** | **652 / 652 satisfied, 0 FAILED** (was 93 failing) ✅ |
| b0744 | 635 / 635, 0 FAILED ✅ | b0814_08 | 17/17 ✅ | b0752_36 | 17/17 ✅ |
| Cross-table additive balanced | 288 → **1,286** (incomplete 1,033 → 68) |
| Negatives | **0** · Dim-invalid | **0 / 50,101** · Booleans | **0** |
File shipped (36 MB, 50,101 facts).

### b0368 investigation (cross-table inequality) — c0110 is NOT wrongly greyed
Verified via module-level parity (`tools/drs_parity_all.py`): **ALL 61,498 official-sample facts are
dim-valid in our model — 0 over-pruning.** (My interim "352 mi119 rejected = over-prune" was a false alarm:
mi119 is a SHARED metric; those facts belong to OTHER tables. The "dims ⊆ table dimset" filter was too loose.)
So `OF08.01.01.01 r0070 c0110`'s signature is correctly absent → b0368 RHS = 0 is correct. The real b0368
bug: we GENERATE a positive LHS (`OF08.01.01.02 r0070 c0120` = 1.24M) exceeding its legitimately-0 ceiling.
Fix = cross-table INEQUALITY handler (cap A ≤ B); the correct action is LOWERING the off-balance LHS, not
un-greying the RHS. (Next class.)

### Files changed 2026-07-01 (cont. 2)
- `studio/backend/app/genvalid_store.py` — NEW `_nonneg_additive_solve` + `_NONNEG_TABLES` (env
  `GENVALID_NONNEG_TABLES`, default OF08.01.01.01; `GENVALID_NONNEG_TIMEOUT`); wired into `_run` AFTER
  cross-table agg, BEFORE open-link (`job["nonnegSolve"]`).

## ✅ CONSOLIDATED CHANGELOG — 2026-06-26 (all changes SAVED; DO NOT redo)
Single source of truth for what was changed today. Full narrative in the dated sub-sections below
(cont. 1–6). All edits are written to disk; both modules parse clean. Not a git repo → no commit.

### Code changes (persisted)
1. **`src/workbook_rules.py`**
   - `_LP_CELL_CAP` default **2500 → 20000** (line ~32) — LP covers OF07/OF08 big components → 144→0 negs.
   - `solve_cells_lp` (line ~660): **no-negatives fix** — try snapped-to-1000 free vars, accept ONLY if all
     cells stay ≥0, else use the continuous integer ≥0 LP solution, else clamp residual to 0. no-LP fallback
     floors derived pivots at 0. (Snapping after the LP was creating negatives.)
2. **`studio/backend/app/genvalid_store.py`**
   - `import re`; `from src import dim_drs`.
   - **2026-07-01 typed-date fix:** `_typed_xsd_type` (parse `**/typ.xsd`) + `_typed_synth_value`;
     `_synth_open_rows(…, opts)` now synthesizes a typed value MATCHING the element's XSD type
     (eba_typ:DT=date→`2026-02-28`, ID=integer→`1`, IS/LE=string→`1`). Fixes TDG schema error
     `cvc-datatype-valid.1.2.1 '1' not valid for 'date'` on RDT (OF24.03.01.03). `_run` passes `opts`.
   - `_rule_in_scope` → **single-table ONLY** (main solve never fuses cross-table).
   - `_CROSSTABLE` (env `GENVALID_CROSSTABLE`, default 0) + `_CT_OVERRIDE` (env `GENVALID_CROSSTABLE_OVERRIDE`,
     default 1).
   - NEW **`_crosstable_agg_values`** — Stage-2 cross-table aggregation post-pass; `s1_inc`/`helps` incidence;
     free-leaf-first target, net-positive Stage-1 override only; no negatives. Wired in `_run` (gated `_CROSSTABLE`).
   - NEW **`_synth_open_rows`** + **`_drs_ok`** — open-axis row synthesis (1 DRS-valid row/open table, first z;
     typed→synth value, explicit→valid member); tagged `synth=True`; `_run` calls it before the hypercube
     filter; filter keeps `dp.get("synth") or cell_key in vc`.
   - NEW **`_constant_sum_values`** + `_NUMRE` — `Σcells = k` handler (one-hot, free cells only); wired in `_run`
     after the cross-table merge (`job["constSum"]`). (b0778's cells are additive-owned → currently skipped.)

### Diagnostic/measurement scripts — PERSISTED in `boe_xbrl_gen/tools/` (run with cwd = `boe_xbrl_gen`)
- `regen_pra001.py` — regen full PRA001 + print counts (self-locates backend; runs `gv._run`).
- `count_neg.py` — count negative numeric facts in the output.
- `validate_out.py` — module-level DRS dim-validity + boolean check on the output (the 0-dim-invalid proof).
- `check_crosstable.py` — additive satisfaction split SINGLE-table vs MULTI-table (cross).
- `check_rules.py boe_b0745 boe_b0778 …` — per-rule eval (expression, scope, satisfied/failed/incomplete).
- `survey_rules.py` — whole-file rule-class survey (handled vs unhandled, by shape + satisfaction).
- `analyze_crosstable.py` — union-find table-fusion groups for cross-table rules (the 35-table mega-group).
(All read pkg hash `50c2f2d9…`; reusable next session.)

### Current shipped artifact
`C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID.xbrl` — 35 MB, **49,181 facts**,
**0 dim-invalid · 0 negatives · 0 boolean**, 18 open tables populated, cross-table net-positive + const-sum
handler. Pkg hash `50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181`.

### Regenerate (one line; cwd = `studio/backend`)
`GENVALID_CROSSTABLE=1 PYTHONIOENCODING=utf-8 python <scratchpad>/regen_pra001.py` — then re-copy
`<pkg>/solved/_genvalid_pra001.xbrl` to the root `…_VALID.xbrl`. ~200–270 s. No hypercube rebuild needed
(dimensional logic unchanged today).

---

## TL;DR current state

- **Dimensions: SOLVED** — Arelle-confirmed **0 `PrimaryItemDimensionallyInvalid`**, 0 value errors
  (complete Arelle run, 2,751 s, finished naturally).
- **Business rules (single-table focus):**
  - Single-table **additive** rules: **407 / 454 pass** (~90%); **92%** of the 16,633 expanded
    equations balance.
  - Single-table **isNull** rules: **100%** (0 / 10,499 forbidden cells populated).
  - Booleans: 0 bad.
- **File to upload (refreshed this session):**
  `C:\Users\177069\ClaudeLearning\ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID.xbrl`
  — 46,809 facts. (Copy of `<pkg>/solved/_genvalid_pra001.xbrl`.)

**Package hash (cache dir):** `50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181`
Cache root: `boe_xbrl_gen/studio/backend/.cache/packages/<hash>/`

---

## Phase 1 — Dimensional validity (DONE)

### Root cause of the original 1000+ TDG dimension errors
The file had been built with the **plain "Generate Data"** path (no hypercube filter). It assigned
each dimension a member from the **whole domain**, but each table cell's **closed hypercube** only
admits a subset. C13.01.01.01 (heavily dimensioned) → thousands of `PrimaryItemDimensionallyInvalid`.

### Fix: offline DRS validator — `src/dim_drs.py` (NEW)
Replaces a ~46-min Arelle "hypercube extraction" with an in-process parse of each table's
`<table>-def.xml` definition linkbase (the dimensional relationship set). ~40 s for PRA001.
- Resolves `all` (has-hypercube) → `hypercube-dimension` → `dimension-domain` → `domain-member`,
  following `xbrldt:targetRole` across the fragment roles; closed hypercubes, `contextElement=scenario`.
- `TableDRS.is_valid(metric, dims, defaults)` = closed-hypercube validity (absent explicit dim ⇒
  must fall back to an admitted default; absent **typed** dim ⇒ invalid since typed dims have no default).

### Three real bugs found & fixed (parity-tested vs Arelle + official sample)
1. **Localname collisions** — matching members by bare localname let `GA:x0` (an open *country* axis)
   match a foreign `x0` from another domain, so cells that omitted a required open axis looked valid.
   → Key the DRS graph by **full locator href** (unique) and **domain-qualify** members (`GA:x0` ≠ `CQ:x0`).
2. **Required typed dimensions** (e.g. `SIC` on C14) treated as optional. → absent typed dim = invalid.
3. **Boolean value error** — a numeric rule value written onto boolean metric `bi10007`. → only override
   NUMERIC datatypes in the rule-driven step (`genvalid_store`).

### Parity proof (no over/under-pruning)
- Official **valid** PRA001 sample: **0 / 61,498 facts rejected** (no over-pruning).
- Arelle's flagged set on the broken file ⊆ my validator's set (no under-pruning).

### Integration
`backend/app/hypercube_store.py`: `_run` = **offline DRS** (default); `_run_arelle` kept as
fallback/parity. Output JSON byte-compatible; `genvalid_store` consumes `hypercube-<module>.json`.

### Caveat — Arelle timeouts
`instance_build.validate(timeout=…)` defaulted to 600 s; PRA001 validation needs ~2,750 s. Early runs
were **killed mid-validation** → partial/misleading counts (833, 164, 980). Always use a long timeout.

---

## Phase 2 — Business (formula) rules — APPROACH (in progress)

### Where the rules live
`boebankingtaxonomyvalidationsv400/Bank of England Banking Taxonomy Validations Banking reporting v4.0.0.xlsx`
(1,490 rules for `banking_reporting`). Columns that matter: **Scope, Where, Join, Expression, T1..T5,
Include in XBRL, Deactivated**.

### Rule landscape (single-table = exactly T1 set, T2/T3/T4 blank)
- **Single-table: 1,036** | multi-table: 453 | none: 1.
- Single-table by kind: **additive-scoped 504**, additive-inline(no Scope) 176, **isNull 35**,
  isNull-ish/compound 27, other (comparison/existence/format) ~294.

### The solving model (user-endorsed: "keep RHS inputs, revise LHS totals")
Engine: `src/workbook_rules.py` + `backend/app/genvalid_store.py`.
1. **Generate ALL module tables** (104 for PRA001), hypercube-filtered (dimensionally valid cells).
2. **Rule-driven values** (`_rule_driven_values` → `workbook_rules.solve_cells`): build a linear
   equation per rule, randomise leaf/input cells, **derive total cells** so equations balance.
3. **isNull removal** (`_apply_isnull`): drop cells a rule forces empty (e.g. b1039 cols 0101/0102/0103
   for non-slotting rows). The additive solver is told these are **0** (`null_keys`) so derived totals
   stay correct after removal.

### KEY FIX that unlocked the rules — **Scope threading**
The workbook puts the **rows × z** (or **cols × z**) the equation iterates over in the **Scope** column;
the Expression has only the *other* axis (e.g. `c0090 = c0020+c0070+c0080`). The old loader **dropped
Scope**, so column-only cells never matched a built fact → every such rule silently skipped (only 384
overrides). Now:
- `parse_scope()` extracts rows/cols/z; `expand_scoped_asts()` instantiates **one concrete equation per
  (scope-row × scope-col × scope-z)**, filling each term's missing axis from scope, expanding
  multi-cell `isum` terms. Handles **column-relation** rules (scope=rows×z, e.g. b0746) AND
  **row-relation** rules (scope=cols×z, e.g. b0745) AND **inline** rules (r&c in the expression, no Scope).
- Result: overrides jumped **384 → 43,031**; additive coverage **11,166 → 17,759** equations.

### Solver target assignment (`solve_cells`)
- `plan_equality` aggregates each equation to `{cell: coef}`.
- Greedy: derive the lone **'total'** cell; if already derived elsewhere, fall back **only to a genuine
  leaf** (a cell that is no equation's total) — never overwrite another subtotal. Redundant equations
  then hold by **consistency** (row- and column-sums trace to the same inner leaves).
- `rounds=8` to settle chained totals. `null_keys` (isNull) fixed at 0, never derived.

### SINGLE-TABLE restriction (this session's main change)
`_rule_driven_values`, its null-key pass, and `_apply_isnull` now only consider rules with
`len(tables)==1` (T1 only). Rationale: **no cross-table cascades → each table's data is
self-contained and stable across revisions** (user's explicit requirement: don't churn passed values /
don't lose data points). Multi-table rules (453) deferred.

> Note on data-point counts: drops are **removals of illegal cells only** —
> 24,513 dimensionally-invalid + 10,131 isNull-forbidden. No *valid* datapoint is discarded.
> 81,441 (raw) → 56,928 (dim-filtered) → 46,809 (isNull-removed, stable).

---

## Current numbers (this session's file)

| Check | Result |
|---|---|
| Dimensions (offline validator) | 0 invalid |
| Booleans | 0 bad |
| Single-table additive equations | 15,375 / 16,633 (92%) |
| Single-table additive **rules** (all eqs balance) | **407 / 454** |
| Single-table isNull cells | 0 / 10,499 populated (100% satisfied) |
| Facts | 46,809 |

### The 47 failing single-table additive rules — breakdown
- **32 over-determined, all cells present** — a cell is both a row-subtotal and a column-subtotal (2D
  additivity). Needs an **exact linear solve**. INFEASIBLE for big tables: OF07.00.01.01 = 17,770 cells ×
  6,576 eqs; OF08.01.01.01 = 11,679 × 3,722.
- **11 missing-cell (generation gap)** — rule references a cell we don't generate (open/typed axis or
  dim-dropped). e.g. b0744 (261 missing eqs), b0745 (494 missing eqs). Needs *generation*, not solving.
- **4 mixed.**
- Failing tables: OF08(8), OF21(6), OF02(5), OF07(4), OF18(4), OF09(3), OF19(3), OF22(2), C32(2), …

### Feasibility of exact per-table solve (for the over-determined 32)
Feasible (small): **OF02** 8×12, **OF09** 30×187, **C32** 45×150, **OF21** 208×768, **OF19** 361×549.
Infeasible (large): OF18 666×3,128, **OF08** 3,722×11,679, **OF07** 6,576×17,770.

---

## Files changed this session

- `src/dim_drs.py` — NEW offline DRS validator (Phase 1).
- `src/workbook_rules.py` — `load_workbook_rules` now captures Scope/Where/Join; added `parse_scope`,
  `expand_scoped_asts` (scope threading, row/col/inline), `isnull_cells`; `plan_equality` aggregates to
  `{cell:coef}` with `preferred`; `solve_cells` greedy-with-leaf-only-fallback + `null_keys`.
- `backend/app/hypercube_store.py` — offline `_run` (Phase 1) + Arelle fallback `_run_arelle`.
- `backend/app/genvalid_store.py` — single-table rule filter; `_apply_isnull`; numeric-only override
  guard; `null_keys` into `solve_cells`; `rounds=8`.
- `tools/drs_parity.py`, `tools/drs_parity_all.py`, `tools/check_additive.py` — measurement/parity (NEW).

---

## How to regenerate & measure (resume commands)

```bash
# (cwd = boe_xbrl_gen/studio/backend) regenerate full PRA001 (~40s; rebuild hypercube cache only if
# the dimensional logic changed — see hypercube_store._run)
python - <<'PY'
import time; from app import genvalid_store as gv
PKG="50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
gv._JOBS[PKG]={"status":"solving","t0":time.time(),"entryPoint":"pra001"}
gv._run(PKG, {}, {"lei":"ABCDEFGHIJ0123456789","date":"2026-02-28"}, entry_point="pra001")
print("ruleDriven", gv._JOBS[PKG].get("ruleDriven"), "isNullRemoved", gv._JOBS[PKG].get("isNullRemoved"))
PY

# (cwd = boe_xbrl_gen) measure additive balance offline (Arelle can't — see xfm:log caveat)
python tools/check_additive.py        # equations balanced / unbalanced / incomplete
```
Output file: `<pkg>/solved/_genvalid_pra001.xbrl`. Copy to the root upload name when handing off.

### Arelle caveat (why we measure offline)
Arelle **aborts its entire formula phase** on `xbrlve:noCustomFunctionSignature` for the BoE custom
function **`xfm:log`** (used by rules b0599/b0600). So local Arelle reports 0 formula failures even when
many exist. We measure rule satisfaction **offline** via the rc-code bridge (`workbook_rules` +
`dim_drs.local`). TDG is the real authority. To validate formulas locally we'd need to register `xfm:log`.

---

## 2026-06-25 addendum — non-additive (non-linear) rules

TDG breakdown after the single-table additive file: failures concentrated in **2 tables** — OF24.01.01.01
(10 rules) and OF08.01.01.01 (9 rules). Two changes this session:

1. **Correctness fix in `parse_expression`** — it was MIS-PARSING non-additive rules as additive and
   emitting garbage equations (b0360 `r0020=exp(Σcell²,1,2)` → parsed `r0030=r0030`; b0676
   `if c0020≠0 then c0040=c0030·imax(c0010/c0020,1)` → harmful `c0020=c0030`). Now rejects any expr
   containing `exp( / imax / imin / i/ / if / then / else / cell*cell`. **Consequence:** the honest
   single-table additive count is **345 rules** (not yesterday's 407 — that was inflated by these
   bogus trivially-true/force-satisfied equations that TDG never actually saw as additive).
2. **New `src/formula_eval.py`** — tokenizer + recursive-descent parser + evaluator for the BoE
   formula language (`{cell}`, `exp(x,p,q)=x^(p/q)`, `imax/imin`, `i+ i- i* i/`, comparisons,
   `if/then/else`). `derive_rule(rule, resolver, value_of)` finds the lone TARGET cell of
   `[if COND then] TARGET = EXPR` and computes it from the (kept) inputs, scope-threaded like the
   additive solver. Wired into `genvalid_store._apply_nonlinear` (post-additive pass).
   **Guard:** skip any target cell that an additive rule references, so non-linear never clobbers an
   additive-balanced cell (without the guard additive fell 345→307; with it, additive stays 345).
   Toggle: `GENVALID_NONLINEAR=0`.

**Result:** OF24 b0360–b0364 (√ weighted sum-of-squares) + b0676–b0679 (factor·imax(ratio,1)) now
satisfied at **40/44** target locations (4 conflict with additive-owned cells). Additive unchanged at
345. File refreshed (46,809 facts, 0 dimInvalid, 0 boolean).

### 2026-06-25 (cont.) — date + inequality rules DONE
- **`solve_cells` += `fixed_values`** (cells pinned by a constraint pre-pass; held, never derived, so
  additive totals stay consistent with them — like `null_keys` but with a value).
- **`genvalid_store._constraint_values`** parses single-table INEQUALITY/DATE rules via `formula_eval`:
  - `cell ≤ 0` (b1037/b1038) → pin the cell to **0** (satisfies `≤0`; sibling `c0102 ≤ c0103` (b1036)
    holds since both are 0). **Pin value = 0, NOT a big negative** — 0 is benign inside additive sums
    (≈ absent), so additive stays at 346 rules; `-1,000,000` had regressed it to 322.
  - `startDate ≤ endDate` (b0890) → start=`2019-01-01`, end=`2024-12-31` (dates aren't additive, applied
    directly to the selection).
  - Fixed numerics are also fed to the additive solver via `fixed_values` so e.g. b1040
    (`c0104=c0090+c0101+c0102`) derives consistently with the pinned c0102.
- **Verified:** b1036/b1037/b1038 = 26/26 satisfied; b0890 date order satisfied; additive **346** (no
  regression vs 345 baseline); dims 0; boolean 0. File refreshed (46,809 facts).

**Still failing from the TDG file (next):**
- OF24 **4/44** non-linear targets that are additive-owned cells (inherent additive↔non-linear conflict).
- OF08 **b0747–b0751, b1040, b0314** — additive over-determined (2D row+col) on a large table; exact
  solve infeasible (OF08 = 11,679 cells). The hard tail.

## 2026-06-25 (cont. 2) — EXACT linear solver; OF08 over-determined cluster SOLVED
TDG "Errors 2" breakdown: 16 rules, almost all **OF08.01.01.01** (additive over-determined + 2
inequalities) + a small **OF24** residual.

- **`workbook_rules.solve_cells_linear`** (NEW) — exact simultaneous solve of the additive equality
  system via sparse Gaussian elimination → **RREF over `Fraction`s**. Satisfies EVERY consistent
  equation at once (the greedy `solve_cells` can't, for 2D row+col over-determination). Free vars get
  datatype-valid randoms; dependents derived exactly. Constants held out of the variable set + moved
  to RHS: `null_keys` (=0), `fixed_values` (inequality ≤0 pins), and — via `present_keys` — any
  referenced cell NOT generated (absent ⇒ 0, so b0744/b0745 'missing-cell' rules balance too).
  Wired into `_rule_driven_values` (replaces greedy); `_run` passes `present_keys` = selection keys.
  ~75 s for PRA001. Verified standalone: **OF08 additive 0/3722 unsatisfied**.
- **Result:** single-table additive **346 → 373 / 389 rules** (96%); **OF08 entirely cleared** of
  additive failures; OF24 ES (b0361/b0363) now 8/8. dims 0, boolean 0, isNull 100%, ≤0-ineq + dates
  still pass. File refreshed (46,809 facts, 34 MB).

**Remaining (the hard frontier):**
- OF08 **b0379** (`r0200 ≤ r0190`, ~248) and **b0380** (`|c0280| ≤ |c0020|`, ~68) — inequalities whose
  cells are additive-coupled (b0380 c0280 = 272/272 additive-referenced). Satisfying them needs the
  additive EQUALITIES + these INEQUALITIES solved together = (integer) linear programming. Not a pure
  linear-algebra solve. NEXT BIG LEVER.
- OF24 **b0676–b0679** ratio — 4 locations whose target is additive-owned (guard skips → additive value
  kept). Inherent additive↔non-linear conflict.
- **16 scattered additive rules** (OF34.07 ×5, OF07 ×4, OF22 ×2, C32 ×2, OF02/OF09/C06 ×1) — likely
  genuinely inconsistent (RREF dropped them) or coef/rounding (non-±1 coefficients).
- OF08 **b0314** — code not in the workbook (EBA-side / different sheet?); investigate.

## 2026-06-25 (cont. 3) — LP solver: additive equalities + inequalities TOGETHER
"Errors 2" residual was OF08 inequalities **b0379** (`r0200 ≤ r0190`) and **b0380** (`|c0280| ≤ |c0020|`),
whose cells are additive-coupled (can't pin without breaking sums).

- **`workbook_rules.solve_cells_lp`** (NEW, scipy HiGHS) — per connected component: RREF gives the free
  variables (the additive solution space); for components touched by an `A ≤ B` inequality it solves an
  **LP over the free vars** (objective = L1-close to a random target, so values stay varied) with: every
  cell ≥ 0 (so `|·|` in b0380 reduces to `c0280 ≤ c0020`), and `value(A) ≤ value(B)` per pair. Equalities
  stay EXACT (derived from the free vars); inequalities are met. Other components use random frees.
  Free vars snapped to multiples of 1000. ~110 s for PRA001.
- `_constraint_values` now also returns **`le_pairs`** (`A ≤ B`, with `iabs()` unwrapped); `_run` passes
  them through `_rule_driven_values` → `solve_cells_lp`. (Must iterate `comp_eqs ∪ comp_le` so le-only
  components — cells in no additive equation — are solved too; that closed the last b0379 violations.)
- **Result:** b0379 **0 bad** (was 248), b0380 **0 bad** (was 68). Single-table additive **377/389**.
  dims 0, boolean 0, isNull 100%, ≤0-ineq + dates still pass. File refreshed (46,809 facts).

**Remaining (small tail):**
- **12 scattered additive rules** (OF34.07 ×5, OF07 ×3, OF02/OF22/OF09/C06 ×1) — likely genuinely
  inconsistent (RREF/LP dropped them) or non-±1 coefficients / snap-to-1000 rounding.
- OF24 **b0676–b0679** ratio — 4 locations whose target is additive-owned (inherent conflict).

## 2026-06-25 (cont. 4) — global non-negativity + coefficient rules
"Errors 2 1" added: OF07 `≥0` rules (b0662/b0655/b0667), more cell-cell `≤` (b0961/b0960/b0378),
coefficient additive (b0471 `c0200 = c0150 − 0.9·c0160 − …`), and sum/bin inequalities (b1011/b1017).

- **Global non-negativity:** `solve_cells_lp` now runs the LP (every cell ≥ 0, L1-to-random objective)
  for **every** component, not just inequality ones. The exact RREF derivations were producing **1,751
  negative** values → violating all the `cell ≥ 0` rules. Now **107** (the rest are LP-infeasible
  components that fall back to random). Fixes b0662/b0667/b0598 (0 bad) and most of b0655.
- **Coefficient rules:** `parse_expression` previously banned every `*` (to reject cell×cell); now it
  rejects only `}*{` (cell×cell) and extracts numeric coefficients from `k * {cell}` / `i* k`. So
  b0471 (0.9/0.8/0.6/0.5 coefficients) is solved — **311 → 25** violations. (Fractions keep equalities
  exact; 0.9 × multiple-of-1000 stays integer.)
- **Result:** single-table additive **385/389**; b0961/b0378 0 bad, b0662/b0667/b0598 0 bad. dims 0.
  File refreshed (46,809 facts).

**Remaining tail (~tens of violations):**
- **LP-infeasible components** → random fallback leaves negatives: b0655 (41), part of b0471 (25). The
  `≥0` + equalities + `≤` constraints are jointly infeasible there; would need a relaxation (drop ≥0 on
  unruled cells) or ILP.
- **Sum/bin inequalities** b1011 (1), b1017 (3): `cell ≥ cell ± cell` — `le_pairs` only models cell≤cell;
  generalise to linear `Σcoef·cell ≤ 0` constraints.
- OF24 **b0676–b0679** ratio + b0361/b0363 (~10) — additive-owned non-linear targets.
- ~11 scattered additive (OF07 ×6, OF22 ×2, …) — inconsistent / snap-rounding.

## 2026-06-25 (cont. 5) — general linear inequalities + coefficients + blanket ≥0
"Errors 2 1" classes: OF07 `≥0` (b0655/b0658/b0662/b0667), cell-cell `≤` with an ABSENT side
(b0960 r0343≤r0341 where r0341 isn't generated), sum/bin inequalities (b1011/b1017 `cell ≥ cell±cell`),
coefficient additive (b0471 `c = c − 0.9·c − …`).

- **General linear inequalities:** `_constraint_values` now returns `le_constraints` = list of
  `(coef_dict, rhs)` meaning `Σ coef·value ≤ rhs`, built by a linear-expression extractor over the
  comparison AST (cell, num, +/−, `isum`, `k*cell`, `iabs`→drop). An absent/const cell folds into
  `rhs` — so b0960 with r0341 absent becomes `r0343 ≤ 0`. `solve_cells_lp` takes `le_constraints`
  (replaces `le_pairs`); fixed b0960/b0961/b0379/b0380/b1011/b0598 (0 bad).
- **Coefficients:** `parse_expression` rejects only `}*{` (cell×cell) now and extracts `k*cell` coefs
  → b0471 (0.9/0.8/0.6/0.5) solved, 311 → ~17 bad. Fractions keep equalities exact.
- **Blanket ≥0:** LP forces every cell ≥0 (most have/imply `≥0` rules); negatives 1,751 → **111**.
  Tested alternatives and reverted: dropping the blanket → 2,175 negatives; relaxing free-var bounds →
  worse; soft-slack LP → worse + much slower. Blanket-≥0 + random fallback is the best balance.
- **Result:** single-table additive **390/396**; dims 0; b0379/b0380/b0961/b0667/b1011/b0598 0 bad;
  b0960 ~1, b0662 ~1. File refreshed (46,809 facts).

**Hard tail (~110 instances, needs ILP — out of scope for the LP):**
- `≥0` negatives b0658 (~52) / b0655 (~44): a few densely-constrained components have NO all-≥0
  solution consistent with the exact equalities → random fallback leaves negatives.
- b0471 (~17), b1017 (~3), b0960 (1): LP-infeasibility / snap-to-1000 rounding on tight cells.
- OF24 b0676–b0679 ratio + scattered additive — additive↔non-linear conflict.
- b0314: not in the workbook (EBA-side?).

## 2026-06-25 (cont. 6) — multi-row isum in inequalities (b0597)
b0597 `r0010 ≥ isum({r: 0050; 0060})`: the `isum` arg is ONE cell with a **multi-row** `r="0050; 0060"`.
`_constraint_values.linexpr` didn't split it → the cell failed to resolve → the constraint collapsed to
`r0010 ≥ 0` (sum lost). Fixed: `linexpr`'s cell branch now expands semicolon `r`/`c` (via `_semi`) and
sums them. b0597 → 201 ok / 7 bad (was ~all failing); b0598 0 bad. additive 390/396, dims 0, neg ~128.
File refreshed. (Residual b0597 ×7 etc. are the same LP-infeasible hard tail.)

## 2026-06-25 (cont. 7) — ILP soft-fallback + NEW cross-table class
- **ILP pass** in `solve_cells_lp`: try the HARD LP per component; if infeasible, retry a SOFT LP with a
  penalised slack per constraint (minimise total violation) instead of the random fallback. Helped
  (b0655 48→35, b0314_6 → 4 bad) but **b0658 ~57 persists**: those components are genuinely infeasible
  (equalities force some `≥0` cell negative) AND the **snap-to-1000** pushes near-zero derived cells to
  ±1000 (the literal `-1000` violations). additive 385–390/396, dims 0, neg ~107. File refreshed.
- Residual `≥0` (~100) is now a real floor for the float-LP-then-snap approach. To go further: an
  integer LP that enforces ≥0 on the SNAPPED values, or datatype-aware snapping.

### NEW class this batch: CROSS-TABLE rules (not yet handled)
- **b0369_5 / b0368_2** `OF08.01.01.02 cell ≤ OF08.01.01.01 cell`; **b0739 / b0736**
  `OF08.01.01.01 cell − Σ = Σ OF08.03.01.01 cells` (equality). These span TWO tables, so the
  single-table filter (`len(tables)==1`) skips them. Handling needs the solver to merge cells across
  tables into one component — reintroduces cross-table coupling the user earlier chose to avoid →
  a scope decision before building.
- **b0356** `if c0110>0 then c0010 ≥ 0.0005` — conditional PERCENTAGE floor; extractor takes the
  then-branch fine, but snap-to-1000 mangles a percentage → needs datatype-aware snap.
- **v6571_s** `{multi-cell} ≤ 0` (C32.02.01.01) — ≤0 class; check capture.

## Remaining work / TODO (priority order for next sessions)

1. **Re-upload current file to TDG** (user, tomorrow) → confirm single-table additive + isNull class is
   gone; get the fresh breakdown.
2. **Exact per-table linear solve for SMALL failing tables** (OF02, OF09, C32, OF19, OF21) → clears their
   over-determined additive rules. Feasible now.
3. **Generation gaps (11 missing-cell rules, e.g. b0744/b0745)** — decide: generate the missing cells
   (needs open/typed-axis values) or accept as unsatisfiable.
4. **Single-table "other" rules (~294)** — comparison (`A≥B`), existence, sign, format. Triage by
   sub-type from the TDG breakdown; handle the common shapes.
5. **Compound/conditional isNull (27)** — `not(isNull(x))` (must be present), `if X=[member] then isNull(Y)`.
   Need conditional logic; deferred (blind removal would break the "must be present" ones).
6. **Multi-table rules (453)** — deferred; cross-table cascades. Tackle after single-table is maxed.
7. **Big over-determined tables (OF07/OF08/OF18)** — exact solve infeasible at 17k vars; revisit only if
   TDG shows these dominate (would need sparse/iterative numerical methods).
8. **`xfm:log`** — register the custom function so local Arelle can validate formulas end-to-end.

## Engine notes / gotchas
- `PYTHONIOENCODING=utf-8` always. Read `model.json` with `encoding="utf-8"`.
- `workbook_rules`/`solve` use bare imports → need `src/` on `sys.path` (genvalid handles this).
- The correct validations workbook is the one WITHOUT "for SDDTs" in the name.
- Matching uses **localnames** (`dim_drs.local`) for dims/concepts and **domain-qualified** members
  (`dim_drs.qmem`) on both instance and rule sides.

## 2026-06-26 — cross-table rules: root-cause parser fix + scipy-import BLOCKER

TDG breakdown this session surfaced **cross-table** rules (b0844–b0851: `OF34.07 r0180 c0030 = isum(OF08
r0040;0050;0060 c0300)` per z) plus more ≥0/≤0 inequalities. User chose to extend to **all 412 two-table
rules**. Findings + changes:

1. **The multi-table code path already existed** (`_rule_driven_values`/`_constraint_values` used
   `set(tables)⊆selection`, not `len==1`) — added in an earlier (undocumented, crash-interrupted) session.
2. **ROOT CAUSE of b0844–b0851 failing = a parser bug, not a missing feature.** `table_model.parse_table`
   dropped any non-abstract `ruleNode` with no own aspects — but those include **"total" rows** (e.g.
   OF34.07 **r0180** = `boe_c26`, inherits everything from the breakdown root, carries rc-code 0180). So
   the cell was never generated or resolvable → every rule referencing it silently failed. Confirmed real:
   the **official sample reports 42 `eba_met:ii177` facts** with exactly that no-IMS/PDR total-cell shape.
   - **FIX (done):** `parse_table` now keeps a non-abstract ruleNode if `concept or dims or codes.get(label)`
     (rc-code ⇒ reportable). `codes = rc_codes(rend_path)`. **No regression** (C01 still 106 dps — dedup).
   - DRS needed NO change — `is_valid` accepts the total cell once defaults are localized (IMS default
     `IM:x0`, PDR `PC:x0`, both admitted). Impact: **459 reportable total cells across 81/104 pra001 tables**
     were missing. **Hypercube rebuilt offline (~26s): 56948 → 57407 valid cells.**
   - VERIFIED: OF34.07 r0180 now resolves + DRS-valid; regen has **47,268 facts (+459)**, **342 no-IMS
     total-cell ii177 facts** (was 0).
3. **Cross-table coupling is computationally heavy** — solving all 412 at once merges OF07/OF08 (15–17k
   cells) into giant components. Added a **toggle** `GENVALID_CROSSTABLE` (default **OFF** = single-table;
   prevents accidental hangs) via `_rule_in_scope()`, and a **component size cap** `GENVALID_LP_CELL_CAP`
   (default 2500) in `solve_cells_lp` — oversized components keep exact RREF but skip the dense per-cell LP.
4. **🛑 BLOCKER — scipy import DEADLOCKS on this machine today (worked 2026-06-25).** `from scipy.optimize
   import linprog` hangs (0.4 CPU-s, frozen); `-X importtime` stalls right after `socket`/`selectors`
   (scipy→multiprocessing→socket on Windows). Likely a wedged OS resource (mp resource-tracker / AV socket
   hook). **REBOOT is the expected fix.** Mitigation added so the pipeline degrades gracefully:
   `_get_linprog()` imports scipy behind a watchdog thread + timeout (env `GENVALID_SCIPY_IMPORT_TIMEOUT`,
   default 25s); `GENVALID_NO_LP=1` skips it entirely. **No-LP path = exact RREF additive + random
   non-negative frees, but inequality LP NOT enforced → the no-LP file has ~6,803 negatives (fails ≥0
   rules). NOT shippable.** Full quality needs scipy back.

### Files changed 2026-06-26
- `src/table_model.py` — `parse_table` keeps rc-coded aspectless "total" nodes (`codes=rc_codes(...)`).
- `src/workbook_rules.py` — `_LP_CELL_CAP`, `_NO_LP_ENV`, `_get_linprog()` (watchdog import), size-cap +
  scipy-optional branch in `solve_cells_lp`.
- `studio/backend/app/genvalid_store.py` — `_CROSSTABLE` flag + `_rule_in_scope()` helper (gates multi-table).

### RESUME 2026-06-26 (do first)
1. **Reboot to restore scipy**, then verify: `python -c "from scipy.optimize import linprog; print('ok')"`.
2. With scipy healthy, regenerate WITHOUT the no-LP flag (full quality) and confirm negatives → ~100 tail,
   single-table additive back to ~390/396. Pkg hash `50c2f2d9...`; regen via the script in scratchpad or
   `gv._run(PKG,{},{...},entry_point="pra001")`.
3. **Stage 2 cross-table:** set `GENVALID_CROSSTABLE=1`. b0844–b0851 should then solve (totals now generate).
   If big-component hangs, lower `GENVALID_LP_CELL_CAP` or add an aggregation post-pass (derive
   target=isum(sources) topologically, no LP).

## 2026-06-26 (cont.) — REBOOT FIXED scipy; full quality restored; cap default raised ✅
Machine rebooted. Outcome of the RESUME plan above:
1. **scipy healthy** — `from scipy.optimize import linprog` imports in 5.76 s (was a deadlock). Blocker gone.
2. **Found a NEW regression from the 06-26 cap.** First full regen (default `_LP_CELL_CAP=2500`) finished in
   80.8 s but left **2,362 negatives** (not the ~100 tail) — the cap skips the dense ≥0 LP on PRA001's big
   components (OF07 ~17.8k cells, OF08 ~11.7k), so their RREF-derived cells go negative. Re-ran with
   `GENVALID_LP_CELL_CAP=20000` (LP covers them) in **177 s** → **negatives 144** (the real hard tail).
3. **DURABLE FIX:** raised the `_LP_CELL_CAP` **default 2500 → 20000** in `src/workbook_rules.py` (with a note),
   so the normal regen path now ships the good file. The cap still protects against scipy-broken hangs via the
   `linprog is None` branch (unchanged).
4. **Shippable file refreshed:** `<pkg>/solved/_genvalid_pra001.xbrl` → copied to repo root
   `ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID.xbrl` (34 MB, **47,268 facts**).

### Verified numbers (this file)
| Check | Result |
|---|---|
| Dimensions (offline DRS, all 104 tables) | **0 / 47,268 invalid** |
| Booleans | **0 bad** |
| Negatives (≥0 rules) | **144** (hard tail; was 2,362 capped / ~6,803 no-LP) |
| Single-table additive equations | **11,166 balanced / 213 unbalanced / 6,560 incomplete** (of 17,939) |
| `ruleDriven` overrides / `isNullRemoved` | 43,868 / 10,131 |

The 213 unbalanced + 6,560 incomplete = the known single-table tail (incomplete = rule references an
open/typed-axis cell we don't generate). **Cross-table (Stage 2, `GENVALID_CROSSTABLE=1`) NOT run** — user
chose to stop after the durable cap fix and re-upload to TDG. Next session can pick up Stage 2.

### Files changed 2026-06-26 (cont.)
- `src/workbook_rules.py` — `_LP_CELL_CAP` default 2500 → 20000 (comment explains the verified rationale).

## 2026-06-26 (cont. 2) — NO-NEGATIVES fix (TDG b0655 etc.) ✅
TDG re-upload of the 144-negative file failed **b0655** (reported values like −200/−300). User's hard rule:
**no negative datapoint unless a rule mandates `< 0`.** The 144 "hard tail" was NOT acceptable.

### Root cause (in `solve_cells_lp`)
The LP forces every cell ≥ 0 at its continuous optimum, but the code then **snapped free vars to
multiples of 1000** (cosmetic) and re-derived the dependent (pivot) cells from the perturbed frees.
A pivot `= nb − Σ coef·free` then goes negative — worst with **fractional coefficients** (b0471's
0.9/0.8/… → −100s, i.e. the −200/−300 TDG saw). Snapping destroyed the LP's ≥0 guarantee.

### Fix
`solve_cells_lp` now: build the snapped (clean) values AND the continuous integer ≥0 values; **accept
the snapped set only if every cell (free + derived) stays ≥ 0**, else use the continuous ≥0 solution;
if a component is genuinely infeasible (soft-slack), **clamp any residual negative to 0**. The no-LP
fallback path (scipy down / component > cap) also floors derived pivots at 0. **≥0 always wins over
clean/exact values.**

### Verified (regenerated, 196.9 s)
| Check | Result |
|---|---|
| **Negatives** | **0 / 47,199 numeric facts** (was 144) ✅ |
| Dimensions (offline DRS, 104 tables) | **0 / 47,268 invalid** ✅ |
| Booleans | **0 bad** ✅ |
| Single-table additive equations | 11,155 balanced / **224 unbalanced** / 6,560 incomplete |

Trade-off: additive unbalanced 213 → **224** (~11 equations) — preferring ≥0 over exact additivity on
the few snap/infeasible components. Acceptable per the user's priority (no negatives > additivity > clean).
File refreshed → repo root `ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID.xbrl` (34 MB, 47,268 facts).

### Files changed 2026-06-26 (cont. 2)
- `src/workbook_rules.py` — `solve_cells_lp`: snapped-then-verify-≥0 with continuous-≥0 fallback + clamp;
  no-LP fallback floors derived pivots at 0.

## 2026-06-26 (cont. 3) — STAGE 2 cross-table: SAFE aggregation post-pass (no fusion) ✅ modest
User asked to move to Stage 2 (cross-table) while preserving Stage 1. **Analysis first** (`tools`/scratch):
the 452 multi-table rules in PRA001 fuse via union-find into a **35-table mega-group** (OF07+OF08+OF18+
OF24+… ≈ 50k cells). So the old `_CROSSTABLE`→solver-fusion path would **hang the RREF/LP AND re-solve
those tables (destroying Stage 1)**. Confirmed: do NOT fuse.

### Design (implemented)
Repurposed `GENVALID_CROSSTABLE=1` to run a **separate aggregation POST-PASS** (`_crosstable_agg_values`
in `genvalid_store.py`), NOT solver fusion. `_rule_in_scope` is now **single-table only** (main solve
never fuses). The post-pass, after Stage 1:
- expands each multi-table ADDITIVE rule (e.g. b0844 `OF34.07 r0180 = isum(OF08 …)`) and, per equation,
  derives the lone cross-table TARGET from the OTHER cells' current values (`plan_equality` + a few rounds);
- **never overrides a Stage-1 cell** (`fixed_keys = set(rv)`), target must be **present**, and a
  **derived negative is skipped** (no-negatives rule wins). Conditional/boolean cross-table rules don't
  parse as additive → skipped.

### Result (regen 210 s — NO hang; Stage 1 fully preserved)
| Check | Result |
|---|---|
| Negatives | **0** ✅ | Dim-invalid | **0 / 47,268** ✅ | Bad booleans | **0** ✅ |
| SINGLE-table additive eqs | 16,406 → balanced 10,903 / **UNBAL 36** / incomplete 5,467 (unchanged) |
| MULTI-table (cross) additive eqs | 1,533 → balanced **277** / UNBAL 163 / incomplete **1,093** |
| Cross-table cell overrides added | ~21 (ruleDriven 43,868 → 43,889) → net **~+25 equations balanced** |

**Honest read:** safe and strictly-better, but a **modest** cross-table win. The bulk of the 1,256 still-
failing cross-table additive eqs are **1,093 incomplete** (reference cells we don't GENERATE — open/typed
axes) and **163 unbalanced** (target is Stage-1-owned → skipped to preserve Stage 1, or not cleanly
derivable). Real further levers: (a) GENERATE the missing cells, or (b) allow cross-table to override
Stage-1 cells (relaxes "preserve Stage 1"). File refreshed (34 MB, 47,268 facts).

### Files changed 2026-06-26 (cont. 3)
- `studio/backend/app/genvalid_store.py` — `_rule_in_scope` single-table only; NEW `_crosstable_agg_values`
  (safe aggregation post-pass); wired into `_run` under `_CROSSTABLE`, merged into `rv` before override.

## 2026-06-26 (cont. 4) — Stage 2: NET-POSITIVE cross-table override ✅ (the shippable Stage 2)
User asked to (a) let cross-table override Stage 1, then (b) refined: prefer cells that "don't affect other
tables" so Stage 1 stays satisfied. Implemented an incidence-driven target picker in `_crosstable_agg_values`:
- `s1_inc[cell]` = # SINGLE-table additive equations referencing the cell (= single-table rules it breaks
  if moved). `helps[cell]` = # cross-table equations it would satisfy as target.
- Always take a **free-leaf** target (`s1_inc==0`, zero Stage-1 impact — the user's idea). Override a
  Stage-1 cell ONLY when `allow_override` and **net-positive** (`helps > s1_inc`). No negatives ever.
- Flags: `GENVALID_CROSSTABLE=1` (run the pass), `GENVALID_CROSSTABLE_OVERRIDE=1` (default — allow
  net-positive overrides; set 0 for the strictly-safe pass).

### Result — best of the three (regen 196 s; 0 neg / 0 dim-invalid / 0 boolean)
| Additive eqs UNBALANCED | safe | blanket-override | **net-positive (shipped)** |
|---|---|---|---|
| Single-table | 36 | 219 | **40** |
| Cross-table | 163 | 72 | **152** |
| **Total** | 199 | 291 | **192** |
303 cross-table targets derived, 283 net-positive Stage-1 overrides; only **4** single-table eqs disturbed.
File shipped → repo root `…_VALID.xbrl` (34 MB, 47,268 facts).

**Frontier (why cross-table can't go much further without a bigger move):** of 1,533 cross-table additive
eqs, **1,093 are "incomplete"** — they reference cells we DON'T GENERATE (open/typed axes). The aggregation
pass can't fix those; the next real lever is GENERATING the missing cells. The 152 unbalanced are equations
with no net-positive target (all cells single-table-pinned). Conditional/boolean cross-table rules are also
not handled (don't parse as additive).

### Files changed 2026-06-26 (cont. 4)
- `studio/backend/app/genvalid_store.py` — `_crosstable_agg_values` rewritten: `s1_inc`/`helps` incidence,
  free-leaf-first + net-positive-override target picker; `_CT_OVERRIDE` flag.

## 2026-06-26 (cont. 5) — OPEN-ROW SYNTHESIS: generate the 18 empty open tables ✅
User observed OF24.03.01.03–.09 (and others) generate NOTHING. Root cause: **18 of 104 PRA001 tables have an
EMPTY closed row axis** because the rows are an OPEN/typed dimension (UDI, SIC, LGS, OGR, RAN, RAC, CPT, PDT,
FXI, FXC, RDT; + explicit IGS/CLR), and `_build_module_selection` only emits the closed cartesian → 0 facts.
This is the dominant chunk of the 1,093 cross-table "incomplete" eqs (cells absent).

### Implemented (user spec: one row per open table, first z only)
NEW `_synth_open_rows` (+ `_drs_ok`) in `genvalid_store.py`: for each table with empty rows + an open y-dim,
synthesize ONE row — **typed** dim → a synthesized value (`"1"`; builder emits a `typedMember`, DRS needs only
presence); **explicit** dim → a real member chosen so the cell passes the table DRS. Every synth cell is
DRS-validated and tagged `synth=True` → **exempt from the hypercube filter** (open tables contributed no cells
to it). Wired into `_run` before the filter; filter keeps `dp.get("synth") or cell_key in vc`.

### Result (regen 270 s)
| Check | Result |
|---|---|
| Total facts | 47,268 → **49,181** (+1,913) |
| Open tables populated | **18 / 18** (all typed dims + explicit IGS/CLR present) |
| **DIM-INVALID** | **0 / 49,181** ✅ (synth cells all DRS-valid) |
| Negatives | **0** ✅ | Booleans | **0** ✅ |
| Cross-table additive incomplete | 1,093 → **1,033** (−60 now present) |
| Cross-table additive unbalanced | 152 → **212** | single-table unbalanced 40 → **55** |

**Trade / known gap:** populating the cells moved ~75 eqs from "incomplete" (absent) to "complete but
UNBALANCED" — because the synth cells carry random (un-solved) values. The rule engine can't solve them: the
**rc-code bridge resolves a rule's cell to dims WITHOUT the synthesized typed value** (`UDI="1"`), so rule
cells don't match the synth cell keys → not balanced. So the 18 tables are now PRESENT + dim-valid (regulators
generally require non-blank mandatory tables) but their own additive rules aren't satisfied yet. **Next lever:**
make the rc-code bridge / solver match synthesized open-axis cells (typed-value-agnostic match) so their values
get rule-solved too. Flags: open-row synth always runs; `GENVALID_CROSSTABLE`/`_OVERRIDE` as before.

### Files changed 2026-06-26 (cont. 5)
- `studio/backend/app/genvalid_store.py` — NEW `_synth_open_rows` + `_drs_ok`; `from src import dim_drs`;
  `_run` calls synth before the hypercube filter; filter exempts `synth` cells.

## 2026-06-26 (cont. 6) — RULE SURVEY + b0778/b0745 verdicts + const-sum handler
User asked: do b0745 & b0778 satisfy? if not, plan — and survey the whole rules file for similar classes.

### Verdicts (current dataset)
- **boe_b0745** (OF08.01.01.01 `r0010 = isum(r0070,0080,0170,0180)`): ❌ NOT satisfied offline — 674/697 eqs
  "incomplete". **Root cause is NOT a generation gap:** of 1,421 missing cells, 1,016 are dim-INVALID (greyed
  cells the rule formally over-scopes — TDG won't flag) and the 405 dim-valid ones are ALL in the hypercube
  cache but were **removed by the isNull pass** (validly empty). So in XBRL (absent input = 0) most of these
  eqs likely hold; the offline "incomplete" count **overstates** the failure. Real fix if needed: force the
  total to 0 when its inputs are isNull-removed (additive↔isNull interaction), not generation.
- **boe_b0778** (OF08.07.01.01 `c0030+c0040+c0050 = 1` per row, shares-sum-to-1): ❌ NOT satisfied — cells hold
  random values. Its cells (`eba_met:pi824`) are **also referenced by single-table additive rules** → Stage-1-
  owned, so satisfying b0778 requires OVERRIDING a Stage-1 cell (a trade). Built a general `_constant_sum_values`
  handler (one-hot to sum=k, free cells only) — correct + safe, but it skips b0778 (owned) → `constSum=0`.

### Survey — 1,487 in-scope PRA001 rules
- Handled by additive parser: **984** → 666 satisfied, 86 fail (values), **232 have missing cells (b0745 class)**
  — dominated by OF07.00.01.01 + OF08.01.01.01; same isNull/over-scope story as b0745 (mostly not real failures).
- NOT handled (**503**): **273 plain `>=`/`<=`/sign comparisons** (e.g. `{table} >= 0`, `<= 0` — many `>=0`
  already pass since 0 negatives; parser only reads `i`-prefixed relations), 114 conditional(if/then),
  90 isnull/existence, 20 nonlinear(exp/imax), **1 const-sum (b0778)**, 6 edge inequalities.

### Takeaways / plan
- The **const-sum "Σ=k" class is a singleton (b0778)** — low ROI as a family; satisfying it needs a Stage-1
  override or feeding it as a solver `fixed_value` (consistent but more plumbing).
- The **232 "missing-cell" additive rules are largely measurement artifacts** (TDG treats absent=0) + the
  isNull interaction — verify against TDG before engineering.
- **Biggest genuinely-unhandled class = 273 sign/comparison rules** — extend the parser to plain `>=`/`<=`;
  many likely already pass. **TDG upload is the right next step** to confirm which classes actually fail.
- Invariants intact: 49,181 facts, **0 dim-invalid, 0 negatives, 0 boolean**. (openRows reported 17 this run vs
  18 — same fact total; cosmetic count, not investigated.)

### Files changed 2026-06-26 (cont. 6)
- `studio/backend/app/genvalid_store.py` — `import re`, `_NUMRE`, NEW `_constant_sum_values` (Σ=k handler,
  one-hot, free-cells-only); wired into `_run` after the cross-table merge (`job["constSum"]`).
