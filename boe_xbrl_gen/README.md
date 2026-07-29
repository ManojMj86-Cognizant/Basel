# BoE Banking XBRL Instance Generator (v4.0.0)

Generate Bank of England Banking XBRL instances shaped like the official samples, with
randomly generated values that aim to be **business-rule valid** (validated with Arelle).
Reusable across all banking returns.

- **`USER_GUIDE.md`** — prerequisites, time/RAM expectations, what is covered. **Start here.**
- **`ARCHITECTURE.md`** — internal design.
- This file — quick command reference.

### Two ways to run
- **Small/medium returns** (LVR, MREL, RFB, PRA112–118): `src\pipeline.py` — iterative
  generate→solve→Arelle loop (whole run < 1 min).
- **Large returns** (PRA001: 61K facts, 1,448 rules): `src\solve_all.py` — solves all
  framework rules offline in ~1 min, validates **once** (~15–30 min). The Arelle-per-iteration
  loop is too slow at this scale.

## Prerequisites (already set up on this machine)
- Python 3.13 with `lxml`, `openpyxl`, `arelle-release` (`pip install --user arelle-release`).
- Extracted taxonomy package at `..\boebanking400\` and the zip `..\boebanking400.zip`.
- Sample instances at `..\boebankingtaxonomysampleinstancesv400\`.

## One-time model build (already generated under `model/`)
```powershell
# DPM model (metrics/dims/domains/members)
python src\dpm_model.py
# Dimension defaults (via Arelle) — uses any sample to load the DTS
python ..\tools\dump_dim_defaults.py `
  "..\boebankingtaxonomysampleinstancesv400\<any sample>.xbrl" model\dim_defaults.json
```

## Generate a valid instance for any module
```powershell
python src\pipeline.py `
  --sample "..\boebankingtaxonomysampleinstancesv400\<MODULE sample>.xbrl" `
  --out    out\MY_INSTANCE.xbrl `
  --seed 1 [--lei <20-char LEI>] [--period YYYY-MM-DD] [--iters 8]
```
The pipeline: clones the sample structure (contexts/dimensions/units/filing indicators) →
injects type-correct random values → runs the Arelle feedback loop to solve business rules
(additivity, sign/inequality bounds, formats) → reports residual violations and writes the
final instance. A `<out>.validate.log` holds the last Arelle run.

## Validate any instance manually
```powershell
python -m arelle.CntlrCmdLine --packages ..\boebanking400.zip `
  --validate -f out\MY_INSTANCE.xbrl --logFile out\v.log --logLevel info
```
Lines starting with `[message:...]` are unsatisfied assertions; none = fully valid.

## Status
- **PRA118: 0 violations. LVR002: 0 violations** (both fully business-rule valid).
- PRA001 (61K facts, 1,448 rules): solver completes in ~51 s (11,421 derived facts,
  5,224 inequality adjustments); final validation count reported per run.
- Remaining gap (task #8): complex `orFilter`/`general` selectors, coupled inequalities
  (both operands derived), `isNull`/existence rules, and the full multi-module sweep.
  The imax/inequality-ordering issue is **resolved**.
