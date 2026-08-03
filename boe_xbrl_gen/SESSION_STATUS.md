# Session Status & Outstanding Items — BoE Banking XBRL Generator

**Last updated:** 2026-07-24
**Repo:** GitHub `https://github.com/ManojMj86-Cognizant/Basel.git` (branch `main`). No servers running.

**▶ 2026-08-03 — PHASE 2 first increment MEASURED at TDG: `v15` is the NEW BEST (70 err rules / 103 warn).**
Built the SAFE increment **`src/coregen.py --no-overwrite`** (absent-only): derives the 81 missing cross-table
cells from the leaf closure using the file's ACTUAL present values, and NEVER overwrites a present cell.
`v15` = v13 (v8+OF24) + 81 absent cells; `v14` = v8 + 81 absent (verification artifact).
- **v15 TDG (errors+warnings log `Errors on version 15_03 Aug.txt`, split by `tools/sev_split.py`):**
  ERROR **70 rules / 320 inst** · WARNING **48 rules / 103 inst** · 2 XPTY. vs v8 (75 err) / v12 (121 err) /
  v13 (~69 err, **184 warn**): **warnings 184 → 103 (−44%)**, errors at/near the floor. **v15 = best file.**
- **v8→v15 ERROR-set diff (`tools/sev_diff.py`):** FIXED 6 (`b0676-79` imax + `b0899/b0900` date = the OF24
  fix from v13), NEWLY BROKEN **1 = `b0262`** (activation). So the 81 absent cells' net = **−81 warnings, +1
  error**; the error wins came from OF24. Offline additive 131→51 held (`verify_coregen`, `diff_cluster_additive`).
- **`b0262` (the one activation) — understood:** conditional cross-table — *if* OF07 default-exposure total >0
  AND OF09.01 r0170 c0010 [CEG=x1] >0 *then* OF09.01 r0170 c0020 [CEG=x1] >0. We generated c0010 (total) but
  not its sibling c0020 (exposures-in-default total) → antecedent true, consequent 0 → fails. Same class as
  the gen_of0902 sibling-pairing gap.

**▶ DIAGNOSIS 2026-08-03 (`tools/probe_b0262.py`) — remaining errors need OF08.01 LEAF REGEN, not patches:**
- **`b0262`** consequent OF09.01 r0170 c0020 [CEG=x1] IS additive-defined (b0729) but **derives to 0** (no
  "exposures-in-default" leaves were ever generated). Rule needs it >0 → not fixable by derivation; needs a
  default sub-population in the leaves.
- **`b0834` (48 inst)** genuine over-determination: r0180 pinned by cross-rule b0872 to Σ OF08.01 (=620000)
  while its detail rows are pinned by b0830-33 to OTHER OF08.01 sums (Σ=2,461,000) — no value satisfies both
  on v8's leaves. Same for **`b0735-39`/`b0760`/`b0824`** (OF08.01↔03/06).
- **ROOT:** all trace to the OF08.01 exposures **leaf basis**. Fixable ONLY by regenerating those leaves once
  (incl. default columns) and deriving EVERY view (OF08.01 totals + detail, OF08.02/03/06, OF09.01/02 country,
  OF34.07 CCR) from that single basis → all reconcile by construction. = the full coordinated-generation
  endgame (scope §2.1). Big: regenerates the whole exposures core; open-dim pairing (§4.1) is the risk.

**▶ DECISION 2026-08-03: BUILD the leaf-basis regeneration (user chose the endgame). Tracked as tasks 1-6.**

**Engine map (task 1 done, via subagent) — genvalid_store.py `_run` pipeline:**
- It is **"random-then-solve"**: `_build_module_selection` fills every hypercube-valid cartesian cell with a
  RANDOM value, then `_rule_driven_values`→`workbook_rules.solve_cells_lp` solves each **single-table**
  connected component (RREF free/pivot split is ARBITRARY, not grain-based), then **cross-table additive is a
  SEPARATE greedy post-pass** (`_crosstable_agg_values`) that OVERRIDES target cells. **That greedy override
  is exactly what breaks `b0834`:** the cross-pass sets OF34.07 r0180 = ΣOF08.01, but the single-table solve
  set the detail rows independently → Σdetail ≠ r0180.
- Reusable as-is: `_build_module_selection`, `_synth_open_rows`, hypercube filter (cache present, 57,407
  cells), `_constraint_values`/`le_constraints` (≤ rules), `_apply_nonlinear`, `_apply_isnull`,
  `build_instances`, and `workbook_rules._toposort` (:709). Regen invocation: `tools/regen_pra001.py`
  (cwd `studio/backend`, ~3 min, build-only, no Arelle).

**Design (task 2) — LEAF-FIRST JOINT per-component solve:**
1. Build the additive DAG over **single + cross-table** rules TOGETHER, so OF34.07 detail + r0180 + its
   OF08.01 links form ONE connected component (not solved separately then patched).
2. Per component: pick leaves (no rule's target) as free ≥0; **topologically derive all aggregates** (reuse
   `_toposort`). Where an aggregate is defined two ways (b0834 =Σdetail AND b0872 =ΣOF08.01), the free detail
   leaves (r0040/0050/0060/0170 — currently 0) ABSORB the coupling via a small per-component ≥0 solve → both
   hold. **REPLACES** the RREF-random frees + `_crosstable_agg_values` + `_nonneg_additive_solve`.
3. **`b0834`/`b0739` are CLOSED cells (no open-dim breadth needed) → tractable.** Prior joint-LP over the
   WHOLE 35-table cluster was intractable, but PER-COMPONENT (e.g. OF34.07↔OF08.01) is feasible (the
   OF08.01 pair, 10.6k cells, solved before). Open-dim breadth (OF09.02 country CEG, OF08.02 obligor ladder,
   b0262 default sub-population) is the harder §4.1 track — deferred to a later increment.

**▶ FEASIBILITY (task 3, `tools/probe_of3407_feasible.py`) — leaf-first fixes ~70% of `b0834`, ~30% residual:**
Of b0834's 85 (col×z) instances: **60 gap≥0 (fixable** — free detail leaves r0040/50/60/170 absorb the
coupling), **25 gap<0** (r0180 < Σ determined detail rows; min gap −15.8M) → NOT fixable by filling free leaves;
need the OF08.01 leaves generated so the detail-row subsets NEST under r0180's subset (the §4.1 hard part).
So the leaf-first mechanism is validated for the majority but has a real structural residual — consistent with
scope §4.2. **RESOLVED (`tools/probe_of3407_struct.py`): the residual is VALUE-DRIVEN, 0 STRUCTURAL.** Of the
51 b0834 instances with a cross-table r0180 def (b0872), ALL 51 have their determined detail rows' OF08.01
source cells ⊆ r0180's OF08.01 source cells → gap≥0 for ANY ≥0 leaves; the other 34 have no cross-pin on
r0180 → r0180=Σdetail trivially. **So b0834 is FULLY fixable under a fresh consistent leaf-first regen** (the
25 gap<0 on v15 were just v15's inconsistent leaves). Ceiling ≈ 100%, not 70%. Same nesting logic should hold
for b0739/b0735-38. **Green light for the full build.**

**▶ INTRACTABILITY RE-CONFIRMED (task 3/4, `tools/phase2_solve.py`):** the naive full-cluster JOINT solve does
NOT work. Per-component least-squares over the combined single+cross system on v15's leaves → **85.2% balanced
(residual 2,405), WORSE than phase1's 244** — because on existing leaves the over-determined system is
INCONSISTENT, so lstsq compromises (satisfies no equation exactly); + one 5,050-agg component too big to solve.
A clean solve needs CHOOSING fresh leaves that make the whole system consistent with aggregates ≥0 = an LP over
the combined nullspace, which the 2026-07-23 joint-LP attempt already found INTRACTABLE at full-cluster scale
(feasible only per small sub-cluster). So the clean full-cluster regeneration is NOT tractable — matches scope
§4.2. **What IS achievable:** TARGETED free-absorb for specific over-determined patterns — e.g. b0834: set the
free detail leaves r0040/50/60/170 = gap where gap≥0 (60/85 instances on v15). Bounded partial win, but
populating those rows carries activation risk (only TDG confirms). 

**▶ TARGETED b0834 ATTEMPT (task 3, `tools/fix_b0834.py`) — MARGINAL, not worth shipping.** User chose to try
it → v16 = v15 + free-detail-leaf absorb. Result: only 26 (col,z) instances had a usable free cell (34 had all
detail rows already determined = no free cell; 25 gap<0), and overwriting those 26 CCR rows cleared just
**+9 b0834 instances offline (48→39), balanced 16137→16146**. 0 additive-rule regressions, BUT the 26 rows got
artificial balancing values → real non-additive activation risk (TDG-only). Poor trade (9 inst for 26 artificial
edits + risk). **v16-as-built is NOT recommended for submission.**

**▶ CLEAN WIN REMAINING + RECOMMENDATION:** rebuild v16 = **v15 + OF24 Group C** only (b0361/b0363 sqrt-sum-of-
squares, ~7 inst) — deterministic recompute `target = sqrt(Σ wᵢ·inputᵢ²)`, w=[1,1,2,2,6], like the fix_of24
imax pass; safe, no artificial cells. Needs OF24's open-axis subset matching (fix_of24 Group A/B are closed;
Group C has an open axis). Then v16 ≈ 68 err / 103 warn. **v15 remains the practical best; the b0834/b0739
cluster is confirmed not economically fixable** (intractable clean solve; marginal+risky targeted fix).
Diagnostics: `probe_b0262/of3407_feasible/of3407_struct`, `phase2_solve`, `fix_b0834`.

**v13 TDG background (2026-07-31):** 321 error instances + 184 warnings (warnings up from ~94). The warning
jump was the SPARSE-base effect — v8/v13 lacks the cross-table cells coregen populates; v15 fixes exactly
that, safely. Offline v13 classifier: L1 10 / L2 21 / L3 85 / L4 22.

**Files on disk:** **`v15` = current BEST (TDG-measured: 70 err / 103 warn)** = v8 + OF24 + 81 absent cells;
`v8` (75 err baseline), `v13` (v8+OF24, 69 err / 184 warn), `v14` (v8+absent, verification). v6/v11/v12
`.xbrl` deleted to tidy (kept as `.zip`). Package hash `50c2f2d9…`. git history ~8 MB — no storage action needed.

**Goal:** Generate BoE Banking XBRL v4.0.0 instances shaped like the official samples, with
random values that are **business-rule valid** (Arelle-verified), reusable across all
banking returns. Target: zero violations across all modules.

> Read `USER_GUIDE.md` for prerequisites/usage, `ARCHITECTURE.md` for design, `README.md`
> for commands. This file is the **"where we are / what's left"** handoff.

---

## How to resume (quick commands)
```powershell
$env:PYTHONIOENCODING="utf-8"
cd C:\Users\177069\ClaudeLearning\boe_xbrl_gen
# one module (small/medium):
python src\pipeline.py --sample "..\boebankingtaxonomysampleinstancesv400\<sample>.xbrl" --out out\X.xbrl --seed 1
# one large module (offline solve + 1 validation):
python src\solve_all.py --in <gen> --out <out> --val-dir "<framework val dir>" --pkg ..\boebanking400.zip --defaults model\dim_defaults.json --validate
# all modules under N MB, with validation:
python src\sweep.py --validate --max-mb 2
# validate any instance:
python -m arelle.CntlrCmdLine --packages ..\boebanking400.zip --validate -f out\X.xbrl --logFile out\v.log --logLevel info
```
Model artifacts in `model\` (dpm_model.json, dim_defaults.json). Rule caches in `out\` /
`out\sweep\` (`rules_<framework>_<date>.pkl`). Outputs in `out\` and `out\sweep\`.

---

## PRA001 valid-instance drive (2026-06-24 → 2026-07-31) — moved here from `studio/SESSION_STATUS.md`
*This is the generator-engine thread (making a generated PRA001 pass TDG Beacon). It lived in the studio
status file by accident; its natural home is here. **Full blow-by-blow trail = memory
`pra001-valid-instance-progress.md`.** The dated studio entries below (06-24 → 07-02) also belong to this
thread but are left in the studio file for now as they interleave with genvalid/hypercube studio work.*

### ▶ 2026-07-31 — v12 TDG result measured; **v13 = v8 + OF24 fix** built (awaiting TDG)
v12 was submitted to TDG (errors-only log `Errors on version 12_31 July`). Triaged
(`tools/triage_errors.py`): **320 unsatisfied instances / 121 rules + 2 XPTY0004** (the ignored taxonomy
errors). Comparison (all errors-only, same tool): **v8 = 329 inst / 75 rules**, **v11 = 466 / 168**,
**v12 = 320 / 121**.
- **The v12 OF24 fix worked** (v11→v12: −146 inst, −47 rules). The `di6004` date correction had broad
  reach — cleared OF08.05 (24), C14 (~30), and most OF24 non-linear (18→7). Only `b0361/b0363` (sqrt-sum,
  the deliberately-deferred Group C) remain in OF24.
- **But v12 still trails v8 on distinct rules (121 vs 75)** because it rides the **v11 coregen line**, whose
  cross-table regressions (OF08.03/06 hub, OF34.07↔OF08.01 back to 48) outweigh the OF24 gains.
- **→ Built `v13` = apply the same `tools/fix_of24.py` directly on `v8`** (`FIX_IN`/`FIX_OUT` env). 7 fact
  edits (v8 had the identical stray `2018-03-04` date → set to 2026-02-28; 4 imax b0676–b0679; 2 averages
  b0551/b0552). Diff vs v8 = **7 facts only** → cannot regress v8's 75 rules.
- **v13 TDG result (measured):** **321 error instances + 184 warnings** (warnings up from ~94). Offline
  classifier: L1 10 / L2 21 / **L3 85** / L4 22 → L3 cross-table **−44 rules vs v12 (129)**: v13 has fewer
  error rules than v12, close to v8. The warning rise = v8/v13 being a SPARSER report than coregen v11/v12
  (~90 absent OF09.02/OF34.07 cross-table cells fire completeness warnings). See the PAUSED banner at top for
  the tension and the resume plan. **v13 = current best candidate; full v13 log + Phase 2 are the next steps.**
- Remaining frontier unchanged: the OF08-hub cross-table cluster (~135 "other cross-table" + 48 OF34.07 +
  77 OF08.02 instances) needs **Phase 2 common-basis regeneration** — surgical/greedy edits proven to cascade.



### ▶ 2026-07-24 — v2 → **v12** (surgical → coordinated regen → OF24)
Files on disk (repo root): `ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v{6,8,11,12}.xbrl` (~34.8 MB each).
v1–v5, v7, v9, v10 were interim/discarded; **v12** (2026-07-24 17:59) is the newest candidate. **v8 = last
TDG-CONFIRMED baseline (75 error rules).** 0 dimensional / 0 schema errors throughout.
- **v2/v3 (surgical, `src/solve_existing.py`):** capped closed L1/L2 sweep on the shipped file; fixed a
  **parser bug** (leading/paren coefficients `1.2*isum`, `(0.9*{cell})`) + a **default-member bridge-drop
  bug** that had masked true fails.
- **v5:** b0471 paren-coef class fixed (OF07 clean at TDG). **Surgical ceiling** — cross-table edits cascade
  (OF08-hub cells shared) and the offline classifier can't see cross-table breakage (only TDG verifies).
- **v6:** OF34.07↔OF08.01 aggregation → **157 → 111 error rules** (after severity re-assessment).
- **v8 (BEST / last TDG-confirmed = 75):** OF09.02↔OF08.01 CEG-total generation (`src/gen_of0902.py`,
  2-phase). Journey **157 → 75 error rules (−52%)**.
- **v9:** OF08.01↔03/06 surgical cross → cascaded, DISCARDED offline before any TDG cycle.
- **Coordinated-regen scope + Phase 0/1 proof** (`COORDINATED_REGEN_SCOPE.md`, `tools/phase0_dag.py`,
  `tools/phase1_derive.py`): OF08.01 component = **35 tables, 385 cross + 643 single-table rules**;
  leaf-first balances **~98.5%** of additive equations by construction.
- **v10 (`src/coregen.py`):** regressed at TDG (~650 warnings — populated isNull cells); DELETED.
- **v11:** coregen + **sparsity guards** (165 targeted changes). TDG: **332 errors + 95 warnings**.
- **v12 (newest, AWAITING TDG):** `tools/fix_of24.py` — deterministic OF24 non-linear quick-win, **7 fact
  edits** (date b0899/b0900; imax b0676–b0679; averages b0551/b0552). No offline regression.

**🔜 RESUME PLAN:** (1) **Submit v12 to TDG** → measure vs v11 (332) / v8 (75). (2) Group C b0361/b0363
(sqrt-sum-of-squares, 14 inst) pending — check formula tolerance first. (3) **0 errors NOT reachable**: 2
XPTY0004 rules (b0365/b0366) are taxonomy/tool errors (fire on BoE's own sample) + ~88 genuine
over-determinations → target = MINIMISE. (4) Real frontier = OF08-hub cross-table cluster → **Phase 2
common-basis regeneration** (`COORDINATED_REGEN_SCOPE.md`). Safe fallback = **v8**. Package hash `50c2f2d9…`.
Tools: `classify_fails.py`, `diff_reports.py`, `triage_errors.py`, `sev_reassess.py`, `gen_of0902.py`,
`coregen.py`, `verify_coregen.py`, `phase0_dag.py`, `fix_of24.py`.

### ▶ 2026-07-23 — surgical L1/L2 sweep (capped, SAFE) + open-table support (negative for OF08)
Continued `src/solve_existing.py` (no generation run; verified on copies). L1/L2 sweep exposed a **6,503-cell
mega-component fusing OF02/OF07/C24 + 7 tables** via cell-sharing → added **`--max-comp` (default 400)** to
solve only small components. Capped sweep SAFE (L1 −5/0, L2 −5/0, L3 +2 expected, L4 0 = 10 rules fixed, 0
regressions). Open-table `--open` (`expand_to_full()` per-signature) mechanically works but regressed OF08.02
(shares facts with OF08.01/C04/OF34.07) → the OF08 hypercube cluster needs JOINT L1+L2+L3 solving (genvalid's
`_nonneg_additive_solve`). *(Its "apply capped sweep → `_VALID_v2.xbrl`" plan was executed the same day, then
iterated to v12 — see the 2026-07-24 entry above.)*

### ▶ 2026-07-22 — STRATEGY SHIFT: surgical, minimal-perturbation rule-fixing
Stopped regenerating all datapoints; instead fix still-failing rules level-by-level, touching only cells
coupled to a failing rule. Built **`tools/classify_fails.py`** (offline per-level fail classifier: L1
single-additive / L2 single-comparison / L3 cross-additive / L4 cross-comparison / NONLINEAR / OTHER; TDG
absent=0 semantics, `if…then` preconditions, half-ULP `@decimals` tolerance), **`tools/diff_reports.py`**
(diff two classify reports), and **`src/solve_existing.py`** (keys facts by (concept-local, dim-local
frozenset); single-table additive eqs + ≤/= constraints module-wide; union-find components; re-solve only
dirty components via MILP min Σ|x−cur| with tolerance bands; dry-run default). Key findings: 43,796/50k facts
are `decimals=-3` (±500) so ±1–9 "fails" were rounding NOISE; cell-sharing across tables is real (components
must be module-wide); C04.00.01.01 proof = 2 cells changed, 0 regressions; OF07/OF08 pathological (route to
genvalid).

## Update 2026-06-15 (evening) — `true()` parser fix + cross-table feedback solver
- **Parser bug fixed (global, high-impact):** the expr grammar treated `true`/`false` as
  bare keyword literals, so any test ending `else (true())` — the standard conditional
  shape — **failed to parse and was silently skipped** (`_safe_parse` -> None). `expr.py`
  now parses `true()`/`false()` as function calls, and adds `QName(ns,local)` ->
  Clark-notation evaluation; `solve.py` resolves enumeration fact values
  (`boe_eba_CT:x6004`) to Clark so guards like `$v = QName(...)` compare correctly.
  - This unblocked the **conditional-empty** class (`if ($v=member) then empty($w)`) and
    conditional equalities everywhere. RFB007 b1129/b1130: **38 violations -> 0**.
  - Sub-2MB re-sweep total: **335 -> 300**. One minor regression (LVR001 39->45, a newly
    active leverage conditional) — fully absorbed by the feedback solver below.
- **Cross-table aggregation feedback solver (`src/feedback.py`):** the hard tail
  `{T1,c} = sum({T2,c})` couples open tables with *mismatched* typed dims, so offline
  implicit filtering can't reproduce Arelle's exact fact set (verified vs the official
  sample — a shared-aspect join gives 76M, not the 6.3M total). Instead we read the pairing
  straight from **Arelle's unsatisfied-assertion message**, which lists the bound fact line
  numbers; map line -> Fact (`el.sourceline`), classify target (non-seq var) vs summands
  (seq var) by selector, and set `target = sum(summands)`. Wired into `sweep.py --feedback`
  (validate -> feedback -> re-validate). Confirmed (Arelle):
  - **RFB007 52 -> 0** (now fully clean), **RFB004 64 -> 20**, **RFB008 15 -> 9**,
    **RFB003 4 -> 2**, **LVR001 45 -> 30**; RFB001 19 -> 19 (different class).
- **Net this session: sub-2MB 335 -> 175** (authoritative `--feedback` re-sweep, confirmed).
  Per-module viol: PRAMEM/PRA118/PRA114/PRAMEM/RFB002/RFB005/RFB006/LVR002/**RFB007**=0;
  PRAGAAP 2, RFB003 2, MRL001 2, PRA115 5, PRAIFRS 6, RFB008 9, PRA117 10, PRA113 10, MRL003
  11, RFB001 19, PRA112 20, RFB004 20, LVR001 29, MRL002 30. RFB007 joins the clean set.
- **PRA001 (COREP giant, 61,498 facts) regenerated + validated 2026-06-15 evening = 0 formula
  violations (CONFIRMED, not assumed).** Offline solve: 8,965 derived, 5,952 const/sign adj,
  3,700 ineq adj, 10,120 facts removed (existence). Arelle 2,429 s. Only b0599/b0600 skipped
  (`xfm:log` custom fn missing in this Arelle — environment limit). Files: out\PRA001_v2.xbrl,
  out\PRA001_v2.validate.log. The 11 reported assertions (b0360-b0364, b0676-b0679, b0890,
  b1039) all pass now.
- **Remaining residuals** are non-aggregation classes: RFB001 19 (coupled?), capital_plus
  b0010_ss nested or/andFilter additivity, mrel, financialstatements. Next: classify
  RFB001's 19, and extend feedback to non-sum aggregates if any appear.

### PRA001 (12-June giant) — the 11 reported violations were NOT calc errors
`b0360-b0364` (conditional sum-of-squares equalities, `... else (true())`) and
`b0676-b0679` (`if ($v3!=0) then numeric-equal($v0, $v1*max($v2/$v3,1)) else (true())`)
were skipped by the **`true()` parser bug** above -> never enforced. `b1039` (`empty($v0)`)
needed **existence rules**, added 15-June *after* PRA001 was generated on 12-June. `b0890`
(`$v0 <= $v1`) is a downstream inequality whose operands feed from those unsolved calcs.
All are solver-coverage gaps now closed; **regenerating PRA001 with the current solver
cleared them — re-validated 2026-06-15 to 0 formula violations (see evening update above).**

## Update 2026-06-15 (later) — capital_plus diagnosis + sign-rule fix
- **Constant-bound / sign rules** (`$v <= 0`, `$v >= N`) now handled: clamp a leaf to a
  random value satisfying the bound (`_const_bound`/`_sat_const` in solve.py). Previously
  skipped because the collector required both sides to be variables.
- **capital_plus cluster: 609 -> 45 (-93%)**: PRA117 145->15, PRA113 150->10, PRA112 314->20.
  Dominant cause was `b0007_ss` = `$v <= 0` (130/145 on PRA117).
- Remaining capital_plus ~45 = hard tail: `b0010_ss` additivity over **nested boolean
  (orFilter/andFilter) filters across columns** (resolver approximates these), and coupled
  inequalities (`v0216/v0217`: a cell must be `>= sum` AND `<= 0`). Both are the
  complex-selector / coupled-constraint cases noted as open.
- **Combined re-sweep total: 335 violations** (was 2,057 baseline -> 1,142 after existence
  -> **335** after sign rules = **-84%**), 7 modules at 0. Sign fix also helped beyond
  capital_plus: RFB001 82->22, RFB004 181->64, LVR001 97->39.
- **Remaining residuals (335):** structural_reform 195 (RFB007 **90**, RFB004 64, RFB001 22,
  RFB008 15, RFB003 4) = biggest; mrel 43; capital_plus(+sddt) 45; leverage-2026 39
  (LVR001); financialstmts 8; step-in-risk 5.
- **Next target:** RFB007 (90, derived=0 -> not equality/sign; likely the complex
  boolean-selector / coupled class). Then the broader complex-orFilter handling, which also
  unblocks b0010_ss (capital_plus) and similar.

## Update 2026-06-15
- **Existence rules** (`empty($v)` -> remove the matching fact) implemented in solver +
  `Instance.remove_fact`. Re-sweep (sub-2MB, 22 modules): **2,057 -> 1,142 violations (-44%)**,
  **7 modules now 0** (PRAMEM, PRA118, PRA114, LVR002, RFB002, RFB005, RFB006).
- Remaining residuals by framework: **capital_plus 609** (PRA112 314, PRA113 150, PRA117 145)
  = biggest cluster; **structural_reform 372** (RFB004 181, RFB007 90, RFB001 82, RFB008 15,
  RFB003 4) = a 2nd rule class; leverage-2026 LVR001 97; mrel 43; financialstmts 16; step-in 5.
- **Enhancements:** Package Analyzer (`src/analyzer.py`) + **Streamlit UI** (`src/ui_app.py`,
  `streamlit run src\ui_app.py`, http://localhost:8501) — analyze templates+rules, generate,
  validate. NEXT enhancement: Phase 3 sample-free generation (tasks #11/#12).
- **Next solver target:** diagnose capital_plus residuals (PRA117 smallest at 145), then
  the structural_reform 2nd class.

## Current results (Arelle-validated, 2026-06-12 baseline; see Update above for 06-15)

### Fully clean — 0 violations ✅
| Module | Framework |
|--------|-----------|
| PRA118 | capital_plus_sddt |
| PRA114 | capital_plus |
| LVR002 | leverage (2023-05-11) |
| PRAMEM | financialstatements |
| **PRA001** | banking_reporting — **0 formula violations** (the 1,448-rule COREP target; date-corruption schema bug fixed; re-validation was assumed-pass, not re-confirmed) |

### Near-clean (≤11 violations) 🟡
MRL001 (2), PRA115 (5), PRAGAAP (6), PRAIFRS (10), MRL003 (11)

### Solver-tail needed (significant residuals) 🔴
| Module | Framework | facts | violations |
|--------|-----------|------:|------:|
| MRL002 | mrel | 524 | 30 |
| RFB005/002/006 | structural_reform | ~150 | 112 each |
| LVR001 | leverage (2026-02-27) | 328 | 97 |
| RFB003 | structural_reform | 250 | 116 |
| RFB008 | structural_reform | 522 | 127 |
| PRA117 | capital_plus_sddt | 534 | 145 |
| PRA113 | capital_plus | 782 | 150 |
| RFB001 | structural_reform | 411 | 194 |
| RFB007 | structural_reform | 500 | 202 |
| RFB004 | structural_reform | 1249 | 293 |
| PRA112 | capital_plus | 1670 | 314 |

### Not yet validated ⏭️
PRA116 (17.8 MB, banking_reporting_sddt), PRA110 (89 MB, liquidity_pillarii).

---

## What's done (engine capabilities)
- **Data creation:** clone sample structure (contexts/dims/units/filing indicators) +
  type-correct random values per DPM datatype. Structurally/dimensionally valid by design.
- **Business-rule solving (Arelle formula linkbase):**
  - Equality / additivity (derived totals computed bottom-up via fact dependency graph)
  - Scaled (`× / ÷`), tolerance (`exp`), `imax`/`imin`/`abs` over XPath sequences
  - Pairwise inequality / sign (nudge a leaf, re-propagate)
  - Conditional (`if cond then …` — enforce consequent only when guard holds)
  - Format (`matches` regex)
  - Implicit filtering (per-group of uncovered dims) + dimension defaults
- **Validation:** Arelle, offline, against the v4.0.0 package.
- **Scale/robustness fixes:** concept index, O(1) arc lookups (40 MB rule files), rule
  parse cache (keyed by framework+date), numeric-only write guard (no date corruption).

---

## Outstanding items (prioritized)

1. **(b) Solver tail — biggest cluster: `structural_reform` (RFB*, 112–293 viol).**
   Several RFB modules share the same ~112 failing assertions → likely 1–2 fixable classes.
   Next action: validate RFB002, read `out\sweep\RFB002.validate.log`, categorize the
   failing assertion test-shapes, then extend the solver. **Est. ~2–4 hrs iterative.**
   Likely needs: `isNull`/existence rules, more conditional coverage, precise
   `orFilter`/`general`/`aspectCover` selectors, coupled inequalities (both operands derived).

2. **`capital_plus` large (PRA112/113/117) and `leverage-2026` (LVR001).** Same tail as above.

3. **Validate the giants** PRA116, PRA110 (each one slow Arelle pass: ~15–60 min).

4. **PRA001 re-confirmation** (optional): re-run the single validation on the date-fixed
   `out\SOLVED_PRA001.xbrl` to formally confirm 0 formula + 0 schema (~46 min). Currently
   assumed-pass (first full validation showed 0 formula; date fix verified by spot check).

## UI (Streamlit `src/ui_app.py`) — status & future enhancements
**Status:** working, run with `streamlit run src\ui_app.py` (http://localhost:8501). Two tabs:
**Analyze** (templates + their rules, drill into datapoints/rules) and **Generate & validate**
(pick module → clone+randomize → solve → Arelle → violation count + download). A Streamlit
server has typically been left running during dev sessions — check `ui_app` in the process
list before starting a new one (avoid double-binding port 8501).

**Future enhancements (not started — documented for later):**
1. **Wire in the feedback solver** (highest value now): in the Generate tab, after the first
   Arelle pass, if violations remain run `feedback.apply_feedback` (same as
   `sweep.py --feedback`) and re-validate, showing before/after counts. Currently the UI
   solve path = offline `solve()` only, so it under-reports what the full pipeline achieves
   (e.g. RFB007 would show 52 in the UI but the pipeline gets it to 0).
2. **Violations drill-down:** parse the validate log and show a table of failing assertions
   (id, expression, severity, fact lines), not just the count — reuse
   `feedback.parse_assertion_bindings` + `solve_loop.parse_violations`.
3. **Phase 3 — sample-free generation (tasks #11/#12):** generate an instance without an
   official sample by building contexts/dims/typed members from the DPM model + table
   linkbase directly (the engine currently clones a sample's structure). Surface as a
   "no-sample" mode in the Generate tab.
4. **Batch/sweep view + giants:** expose `sweep.py` (multi-module table) and progress for the
   large returns (PRA116 17.8 MB, PRA110 89 MB) with cancel/async.

## Known blockers / limitations
- **`xfm:log` rules** (`b0599`/`b0600` in banking_reporting, possibly elsewhere): the
  taxonomy uses a custom function Arelle can't evaluate in this install → those assertions
  are skipped (neither pass nor fail). Environment limitation, not a solver gap.
- **True zero across all returns is not guaranteed** — cross-table consistency, `isNull`
  with absent facts, and custom-function rules may remain.
- Validation wall-clock is the time sink (small ~30 s, PRA001 ~46 min, PRA110 likely longer).

## File map
```
boe_xbrl_gen\
  src\  dpm_model.py  generate.py  formula_rules.py  instance.py  resolver.py
        expr.py  solve.py  solve_loop.py  solve_all.py  pipeline.py  sweep.py
  model\  dpm_model.json  dim_defaults.json
  out\    SOLVED_*.xbrl  *.validate.log  rules_banking_reporting.pkl  sweep\
  ARCHITECTURE.md  README.md  USER_GUIDE.md  SESSION_STATUS.md (this file)
tools\   (inspection/diagnostic scripts)
```
