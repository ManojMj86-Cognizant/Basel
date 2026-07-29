# BoE Banking XBRL Instance Generator — User Guide (v4.0.0)

This guide explains what the tool does, what you need to run it, how long things take,
and exactly what is covered in **data creation** and **business-rule validation**.

For the internal design see `ARCHITECTURE.md`; for a quick command reference see `README.md`.

---

## 1. What this tool does

It produces a **Bank of England Banking XBRL instance** (v4.0.0 taxonomy) that:
1. **Looks like an official BoE sample** for a chosen return (same structure: namespaces,
   `schemaRef`, units, contexts/dimensions, filing indicators), and
2. **Has randomly generated data values** that are **type-correct** and, as far as the
   engine can solve, **business-rule valid** (verified with Arelle, the reference XBRL
   processor).

It is a **reusable engine**, not a one-off script: point it at any module's sample and it
generates a fresh instance for that return.

> **Important context:** the official BoE sample instances themselves are *structurally*
> valid but **do not satisfy the business rules** (they ship with placeholder values). Our
> target — random values that *also* pass the business rules — is therefore a **higher bar
> than BoE's own reference data**.

---

## 2. Prerequisites

### Software
| Requirement | Notes |
|-------------|-------|
| **Windows** + **PowerShell** | Tested on Windows 11. A Bash shell also works. |
| **Python 3.13** (or 3.10+) | `python --version` |
| **Python packages** | `lxml`, `openpyxl`, `arelle-release` — install: `pip install --user lxml openpyxl arelle-release` |
| **RAM** | **≥ 16 GB recommended.** Arelle validation of a large return (PRA001) uses **~9 GB**. |
| **Disk** | ~2 GB for the extracted taxonomy + outputs. |

### Data files (from the BoE v4.0.0 release, already on this machine)
| File / folder | Purpose |
|---------------|---------|
| `boebanking400.zip` + extracted `boebanking400\` | **Taxonomy package** — Arelle resolves the instance against it offline. |
| `boebankingtaxonomydpmv400\` | **DPM dictionary** (metric datatypes, dimensions, domains, members) + annotated templates. |
| `boebankingtaxonomysampleinstancesv400\` | **Official sample `.xbrl`** per module — the structural template we clone. |
| `boebankingtaxonomyvalidationsv400\` | Human-readable rule catalogs (reference). The machine rules live inside the taxonomy package. |

### One-time generated artifacts (under `boe_xbrl_gen\model\`)
These are built once and reused:
| Artifact | How to (re)build | Time |
|----------|------------------|------|
| `dpm_model.json` | `python src\dpm_model.py` | seconds |
| `dim_defaults.json` (dimension defaults, via Arelle) | `python ..\tools\dump_dim_defaults.py "<any sample>.xbrl" model\dim_defaults.json` | ~30 s |
| `out\rules_<framework>.pkl` (parsed rule cache) | built automatically on first `solve_all` run | ~3 min first time, then instant |

---

## 3. How to run

### Small / medium returns (e.g. LVR, MREL, RFB, PRA112–118)
Use the iterative pipeline (generate → solve → Arelle, looping to a fixpoint):
```powershell
python src\pipeline.py `
  --sample "..\boebankingtaxonomysampleinstancesv400\<MODULE sample>.xbrl" `
  --out    out\MY_INSTANCE.xbrl `
  --seed 1 [--lei <20-char LEI>] [--period YYYY-MM-DD] [--iters 8]
```

### Large returns (e.g. PRA001 — 61K facts, 1,448 rules)
Use the **offline whole-framework solver** — it solves all rules in one pass and validates
**once** at the end (Arelle is too slow to run every iteration on a 50 MB instance):
```powershell
# 1) generate the random base instance
python src\generate.py --sample "..\...\PRA001 sample.xbrl" --out out\SOLVED_PRA001.gen.xbrl --seed 5
# 2) solve all framework rules + validate once
python src\solve_all.py `
  --in  out\SOLVED_PRA001.gen.xbrl `
  --out out\SOLVED_PRA001.xbrl `
  --val-dir "..\boebanking400\Banking_4.0.0\www.bankofengland.co.uk\data\xbrl\fws\banking\banking_reporting\2026-02-27\val" `
  --pkg "..\boebanking400.zip" --defaults model\dim_defaults.json --rounds 10 --validate
```
(Omit `--validate` to solve quickly and inspect stats first; validate separately when ready.)

### Validate any instance manually
```powershell
python -m arelle.CntlrCmdLine --packages ..\boebanking400.zip `
  --validate -f out\MY_INSTANCE.xbrl --logFile out\v.log --logLevel info
```
Lines beginning `[message:...]` are **unsatisfied assertions**; **none = fully valid**.

---

## 4. Time & resource expectations (the "hurdles")

Measured on PRA001 (the largest return: 61,498 facts, 42,998 contexts, 1,448 rules):

| Step | Time | Notes |
|------|------|-------|
| Generate (clone 50 MB + randomize) | **~10 s** | one-off per instance |
| Parse all framework rules | **~3 min first run, then instant** | cached to `rules_<framework>.pkl` |
| Load instance into the solver | **~9 s** | |
| **Solve all 1,448 rules** | **~51 s** | 11,421 derived facts, 5,224 inequality adjustments |
| **Arelle validation (one pass)** | **~15–30 min, ~9 GB RAM** | the dominant cost |

**Key hurdle = Arelle validation of large instances.** This is inherent: Arelle loads the
full DTS, dimensionally validates 43K contexts / 61K facts, then evaluates 1,448 formula
assertions with implicit filtering. It is *not* something our code controls. Mitigations
we built in:
- **Offline solve** (`solve_all.py`) — solve everything in ~1 min, validate only **once**,
  instead of the per-iteration validation used for small modules.
- **Rule parse cache** — the 3-min parse happens once, then loads instantly.
- **Concept index + O(1) arc lookups** — so the solver scales to 61K facts and 40 MB rule
  files (a few rule files are ~40 MB; without indexing they were effectively unparseable).
- Small modules validate in **~20 s**, so the iterative pipeline is fine for them.

For small modules the whole pipeline (generate→solve→validate→repeat) is **under a minute**.

---

## 5. What we cover

### A. Data creation (structure + values)
- **Structure (cloned verbatim from the sample):** root namespaces, `schemaRef`, units
  (`uGBP`, `uPURE`), every `xbrli:context` including all explicit/typed dimensions in
  `xbrli:scenario`, and the `find:filingIndicator` set. This guarantees a structurally and
  dimensionally valid shape by construction.
- **Random, type-correct values** assigned per the DPM metric datatype:
  | Datatype | Value generated |
  |----------|-----------------|
  | MONETARY / DECIMAL | random number rounded to the fact's `@decimals` (e.g. thousands) |
  | PERCENTAGE | fraction in [0,1] |
  | INTEGER | random non-negative integer |
  | BOOLEAN | `true` / `false` |
  | DATE | ISO date near the reporting period |
  | ENUMERATION | a valid member drawn from the values the sample uses for that metric |
  | STRING | random token (format-constrained ones handled by the rule layer) |
- Optional overrides: entity **LEI** (`--lei`) and reporting **period** (`--period`).

### B. Business-rule solving (toward Arelle-clean)
We parse the **formula linkbase** (what Arelle actually evaluates) and solve these classes:
| Rule class | Example | How we satisfy it |
|------------|---------|-------------------|
| **Additivity / equality** | `total = sum(components)` ; `a = b` | mark the total as *derived*; compute it from its components, **bottom-up** via a fact dependency graph (so chained totals stay consistent) |
| **Scaled equality** | `a = 0.25 * b` , `a = b / 0.08` | evaluate the expression |
| **Tolerance equality** | `a = exp(x, lo, hi)` | evaluate within interval tolerance |
| **min/max & abs** | `a = imax(0, b−c, c−b)` | evaluate `imax`/`imin`/`abs` over XPath sequences |
| **Inequality / sign** | `a ≥ 0`, `a ≤ b`, `a ≥ sum(...)` | nudge a *leaf* operand to satisfy the bound, then re-propagate equalities |
| **Conditional** | `if {flag}=true() then <relation>` | evaluate the precondition; enforce the consequent only when it currently holds |
| **Format** | `matches(v, "^[0-9]{6,8}$")` , LEI patterns | generate a string matching the regex |

The engine resolves each rule's variables to actual facts using **implicit filtering** (the
relationship holds per group of the dimensions the rule doesn't pin) and **dimension
defaults** (members omitted from contexts are treated as their default).

### C. Validation
- Every output is validated with **Arelle** against the v4.0.0 taxonomy package — the
  authoritative pass/fail. `[message:...]` lines are the unsatisfied assertions.
- Proven results: **PRA118 = 0 violations**, **LVR002 = 0 violations**. PRA001 solve
  completes in ~51 s (11,421 derived facts); validation count reported separately.

---

## 6. Known limitations / not yet fully covered

- **Complex `orFilter` / `general` / `aspectCover` selectors** are approximated (flagged
  `complex`); a few rules using them may not be solved precisely.
- **Coupled inequalities** where *both* operands are derived totals (can't be fixed by
  nudging a single leaf) may remain.
- **Existence / `isNull`** rules (require a fact to be present/absent) are not yet enforced.
- **Cross-framework rules** beyond the chosen framework's `val` directory are not loaded
  in offline mode (the iterative pipeline picks them up via Arelle's failing-rule report).
- These are tracked as the remaining tail toward "zero across all returns" (task #8).

---

## 7. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Validation "times out after 600 seconds" | Large instance > the wrapper timeout. Run Arelle directly (Section 3) or use the bumped 3600 s timeout. |
| `UnicodeEncodeError` in console | Set `$env:PYTHONIOENCODING="utf-8"` before running. |
| HTTP 403 fetching BoE pages | The BoE site blocks non-browser user agents; use a browser User-Agent (only relevant for downloading the packages). |
| Arelle uses ~9 GB RAM | Expected for PRA001-scale validation; ensure ≥16 GB RAM. |
| Rule parse is slow the first time | ~3 min one-off; it caches to `rules_<framework>.pkl` and is instant afterward. |
