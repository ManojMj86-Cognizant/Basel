# BoE Banking XBRL Instance Generator — Architecture

## Goal
A **reusable, strategic** tool that generates Bank of England Banking XBRL instance
documents (v4.0.0 taxonomy) shaped like the official sample instances, with **randomly
generated data values**, for **all banking returns**, that are **business-rule valid**
(pass EBA/BoE validation formulas), verified with **Arelle**.

This is a generator/harness, not a one-off script.

## What we learned from the v4.0.0 package (verified)

### Inputs available locally
- `boebanking400.zip` (56 MB) — **taxonomy package** with `META-INF/taxonomyPackage.xml`
  + URL catalog. Arelle resolves the instance `schemaRef`
  (`http://www.bankofengland.co.uk/data/xbrl/fws/banking/.../mod/pra001.xsd`) to local
  files via this package — fully offline.
- `boebankingtaxonomydpmv400/` — DPM workbooks:
  - **DPM dictionary** (48 sheets): `Metrics` (1,099 rows, with datatypes), `Dimensions`
    (383), `Domains`, and one sheet **per domain** (`eba_BA`, `eba_MC`, …) listing every
    enumerated member. This is the source of truth for *what values are valid*.
  - **Annotated templates** (108 sheets, one per table): each reportable cell =
    a **metric** (`eba_met:miNN`) + its **explicit dimension members**
    (`eba_BA:x11`, `eba_BT:x4`, …). Source of truth for *which datapoints exist per table*.
- `boebankingtaxonomysampleinstancesv400/` — official sample `.xbrl` per module
  (PRA001/110/112…, LVR, MREL, RFB, …). Source of truth for *instance shape*.
- `boebankingtaxonomyvalidationsv400.zip` — the validation rules (business rules).

### Instance anatomy (from PRA001 sample, 50 MB)
- Root `xbrli:xbrl` with ~70 namespace decls (eba_* / boe_* dictionaries).
- `link:schemaRef` → module entry-point xsd (the DTS root).
- `xbrli:unit` — `uGBP` (`iso4217:GBP`) and `uPURE` (`xbrli:pure`).
- `xbrli:context` — entity `identifier` (ISO-17442 LEI scheme), `period/instant`,
  and `xbrli:scenario` holding 0–12 `xbrldi:explicitMember` and/or `xbrldi:typedMember`.
  - 42,998 contexts; 105 distinct explicit dims, 11 typed dims.
- `find:fIndicators` / `find:filingIndicator` — 83 indicators = which tables are reported.
- Facts: `eba_met:*` / `boe_met:*` elements with `contextRef`, `unitRef`, `decimals`.
  - 61,498 facts; 294 distinct metrics. Monetary facts use `decimals="-3"`.
  - Metric prefix → datatype family: `mi`=monetary, `ii`=integer/number, `pi`=percentage,
    plus boolean/enum/date/string (authoritative datatype is in the DPM `Metrics` sheet).

## Strategy: hybrid, three layers

```
        DPM dictionary + annotated templates        sample instance (per module)
                  │ (what is valid)                       │ (the shape)
                  ▼                                        ▼
        ┌───────────────────┐                   ┌────────────────────┐
        │  Layer 2: DPM model│                   │ Layer 1: skeleton   │
        │  metrics/dims/doms │                   │ contexts/units/FI   │
        └─────────┬─────────┘                   └─────────┬──────────┘
                  └──────────────┬───────────────────────┘
                                 ▼
                   ┌──────────────────────────┐
                   │ Layer 3: value engine     │  type-correct random values,
                   │ + constraint solver       │  then satisfy business rules
                   └────────────┬─────────────┘
                                ▼
                        emit .xbrl instance
                                ▼
                   ┌──────────────────────────┐
                   │ Arelle validate (offline) │  structural + dimensional + formula
                   │  → failing assertions      │──┐ feedback loop
                   └────────────┬─────────────┘  │
                                └─────────────────┘ adjust generation, repeat
```

### Layer 1 — Structural skeleton (clone mode) — quick win, all modules
Parse a module's official sample, **keep contexts, units, filing indicators verbatim**
(guarantees a dimensionally valid shape), and re-emit. This immediately yields a
structurally valid instance for every module without solving the dimensional model.

### Layer 2 — DPM model loader
Build a reusable JSON/in-memory model from the DPM workbooks:
- `metrics[code] = {datatype, domain?, decimals_hint}`
- `dimensions[code] = {typed|explicit, domain}`
- `domains[code] = [member codes]` (valid enum values)
- `datapoints[table] = [{metric, {dim: member}}]` from annotated templates
This lets us (a) assign correct random value types, and (b) eventually generate contexts
from scratch (full taxonomy-driven mode) and choose which tables to file.

### Layer 3 — Value engine + business-rule satisfaction
- **Type-correct random values** by datatype:
  monetary → rounded to `decimals` (e.g. thousands), pure/percentage → 0..1,
  integer → counts, enum → pick a valid domain member, boolean/date/string → sensible.
- **Constraint satisfaction** (the hard part) driven by Arelle's formula results:
  1. **Additivity**: compute total/subtotal cells = Σ components (don't randomize totals).
  2. **Sign rules**: cells defined as deductions emitted negative.
  3. **Ratio/bound rules**: keep ratios in [0,1] etc.
  4. **Cross-table consistency**: shared datapoints reuse the same value.
  Iterate generate → Arelle → parse failed assertion ids → refine → repeat until clean.

## Validation harness (Arelle)
- `arelle-release` 2.41.4 installed (CLI: `python -m arelle.CntlrCmdLine`).
- Register taxonomy package with `--packages boebanking400.zip`.
- `--validate -f <instance> --logFile <log>` → structural + dimensional + formula results.
- Used both as the **gate** (is the output valid?) and as the **introspection source**
  (enumerate formula assertions to know the constraints to satisfy).

## Layer 3 design (business rules) — concrete plan
**Rule source (verified):** the validations workbooks (one per framework, e.g.
`...Validations Banking reporting v4.0.0.xlsx`, 1,491 rules) expose a **"Simplified
Expression"** column in a regular grammar:
- datapoint reference `{t: TABLE, r: ROW, c: COL}` (+ dimensional scope on the row/`Scope` col)
- operators `+ - = >= <=`, `if/then/else`, `exp(value, lo, hi)` = tolerance interval,
  `i=`/`=` equality, `true()/false()`.

**Cell → fact mapping (the bridge):** annotated templates map `(table, rowCode, colCode)`
→ `(metric, {dimension: member})`. Combined with the table's fixed dimensions, that
identifies the exact instance context+metric for each `{t,r,c}` reference.

**Solver pipeline:**
1. Parse validations workbook → list of constraints (scope, condition, LHS dp, op, RHS expr).
2. Resolve every `{t,r,c}` to instance fact(s) via the annotated-template mapping.
3. Build a dependency DAG: a datapoint that is the LHS of an `=`/additivity rule is
   *derived*; its RHS datapoints are inputs. Everything else is a *leaf*.
4. Assign random values to leaves (existing value engine), then evaluate derived
   datapoints in topological order, honoring tolerances and sign/`>=` bounds.
5. Format/regex rules (e.g. `b1073 ^[0-9]{6,8}$`, `b1074 ^[A-Z0-9]{18}[0-9]{2}$`) →
   generate conforming string/typed values.
6. Emit → Arelle validate → parse residual unsatisfied assertions → refine → repeat
   until zero business-rule messages.

**Scope reality:** this is the largest component. Recommended sequencing: prove the full
solver on a small module first (PRA118/Capital-Plus-SDDT fails only `b0013_ss`,
`b0014_ss`, `b1073`, `b1074`), reach **zero** assertions, then generalize module-by-module.
Cross-table / cross-return rules are the hardest tail.

## Results (verified 2026-06-12)
End-to-end pipeline (`src/pipeline.py`): clone sample -> randomize -> solve -> Arelle.
- **PRA118 (Capital Plus SDDT): 0 violations** (additivity solved bottom-up via the
  fact dependency graph + 2 format rules). Fully business-rule valid.
- **LVR002 (Leverage): 0 violations** — reached after adding `imax`/XPath-sequence support,
  the inequality-adjustment pass, and fixing `_vars_in` to recurse into sequences (the
  `imax`/ordering bug that had left 2 residuals). Fully business-rule valid.
- **PRA001 (banking_reporting, 61,498 facts, 1,448 rules):** offline solver completes in
  ~51 s (11,421 derived facts, ~5,230 inequality adjustments). First full Arelle validation
  (~46 min, ~9 GB RAM): **0 formula-assertion violations** (no `[message:]` lines). Two
  caveats found: (a) one schema `valueError` — the solver had written a number into a DATE
  metric (`di655`); **fixed** by guarding the solver to only write numeric-typed facts
  (those with `@decimals`/`@unitRef`); (b) 2 rules (`b0599`/`b0600`) use a custom `xfm:log`
  function Arelle can't evaluate in this install (environment limitation, not a pass/fail).
  Re-validation of the corrected file confirms the count.

Run modes: `pipeline.py` (small/medium, Arelle-in-the-loop), `solve_all.py` (large, offline
solve + one validation), `sweep.py` (all modules: per-module generate→solve→[validate],
auto-deriving each framework's `val` dir from the sample's schemaRef).

Engine components (all under `src/`):
- `dpm_model.py` — DPM dictionary -> metrics/dims/domains/members (cached JSON).
- `generate.py` — clone + type-correct random value engine.
- `formula_rules.py` — formula-linkbase parser -> Rule(common/var selectors, test). QNames
  in Clark notation; handles explicit/typed/concept/and/or filters.
- `instance.py` — instance -> facts/contexts (live lxml elements, mutable values).
- `resolver.py` — variable->fact binding with implicit filtering (group by uncovered
  aspects) + dimension defaults (`model/dim_defaults.json`, from Arelle).
- `expr.py` — parser/evaluator for the closed test grammar (iaf:*, sum, imax/imin,
  mfn:exp tolerance, XPath sequences `(a,b,c)`, matches, comparisons, if/then/else).
- `solve.py` — FORMAT + EQUALITY (topological derived-value propagation) + INEQUALITY
  (nudge a leaf, re-propagate) solver.
- `solve_loop.py` — generate->Arelle->parse failing rules->solve->repeat to fixpoint.
- `pipeline.py` — one-command entry point.

## Tech choices
- **Python 3.13** (installed) — lxml (emit/parse), openpyxl (DPM workbooks), Arelle (validate).
- Streaming lxml `iterparse` for the large (50–85 MB) instances.
- Config-driven CLI: `--module PRA001 --lei <id> --period 2026-02-28 --seed N --out file.xbrl`.

## Build order (tasks)
1. ✅ Arelle + taxonomy package; baseline-validate an official sample (confirm toolchain).
2. DPM model loader (metrics/dims/domains/datapoints) → cached JSON.
3. Hybrid generator (Layer 1 clone + Layer 3 type-correct random values), all modules.
4. Business-rule layer (Arelle assertion feedback loop): additivity → signs → cross-table.

## Baseline finding (Task 1, verified 2026-06-12)
Arelle toolchain works offline: taxonomy package activates, PRA118 sample validated in ~20s.
**Critical discovery: the official BoE samples are structurally/dimensionally valid but do
NOT satisfy the business rules.** e.g. assertion `boe_b0013_ss` on table CP01.00.03.01:
`r:0010 reported as 6312000 = sum(r:0015;0750) reported as 4414000` — a violated additivity
rule. Also format rules: `b1073` = `^[0-9]{6,8}$`, `b1074` = `^[A-Z0-9]{18}[0-9]{2}$`.

Implications:
- Matching the sample (structural + type-correct random values) is straightforward and is
  exactly what BoE ships.
- Business-rule validity is a *higher* bar than BoE's own reference data → confirmed
  constraint-solving effort. BUT Arelle's assertion messages are the machine-readable
  constraint spec (table/row/col scope + the exact sum/relationship), which directly drives
  the Layer-3 feedback loop. Rule files live at
  `.../fws/banking/<framework>/2026-02-27/val/vr-<id>.xml` inside the package.

## Open risks
- Business-rule validity with random data is a constraint problem; full pass across *all*
  returns is iterative. Layer-1+type-correct values give immediate structural validity;
  business-rule pass is approached module-by-module using the Arelle feedback loop.
- Some rules are format/regex on typed-dimension or string facts — the value engine must be
  pattern-aware (e.g. LEI-like `^[A-Z0-9]{18}[0-9]{2}$`).
