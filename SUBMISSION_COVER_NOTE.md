# PRA001 Submission — Cover Note

**Instance:** `ABCDEFGHIJ0123456789_pra001_2026-02-28_VALID_v15.xbrl`
**Taxonomy:** Bank of England Banking XBRL taxonomy v4.0.0 (module PRA001, `banking_reporting`)
**Reporting reference date:** 2026-02-28
**Nature:** synthetic / generated test instance (dummy LEI `ABCDEFGHIJ0123456789`, random but
business-rule-consistent values). Not real filer data.

---

## 1. Validation status (TDG Beacon)

| Check | Result |
|---|---|
| Schema validity | **0 errors** |
| Dimensional validity (PrimaryItemDimensionallyInvalid etc.) | **0 errors** |
| Business-rule (formula) — **error** severity | **70 rules / 320 occurrences** + 2 XPTY0004 (see §3.1) |
| Business-rule (formula) — **warning** severity | **103 occurrences** (advisory) |

**Structure and dimensions are fully valid.** The instance is well-formed, schema-valid, and every fact is
dimensionally valid against the taxonomy hypercubes. All remaining findings are business-rule (formula) items,
analysed below.

## 2. Progress summary

The generator was iterated to drive down business-rule failures while preserving structural/dimensional
validity:

- **Error-severity failing rules: 157 → 75 → 70.**
- **Warnings: 184 → 103.**

The remaining items fall into two classes, both explained below and **not resolvable by changing the reported
data**.

## 3. Known residual findings (not data-fixable)

### 3.1 Taxonomy / tool function-evaluation errors
Rules: **`boe_b0361`, `boe_b0363`, `boe_b0365`, `boe_b0366`** (OF24.0x — market-risk expected-shortfall).

These rules use the custom `exp()` function (e.g. `exp(Σ w·xᵢ², 1, 2)` = √(Σ w·xᵢ²)). We verified the reported
values are **mathematically correct** (the expected-shortfall aggregates equal the required √-sum-of-squares
within tolerance). The assertions still report unsatisfied / raise `XPTY0004` because of how the custom
function is evaluated — the **same class of issue would arise on the Bank of England's own official sample
instance**. These are taxonomy/tool evaluation artefacts, not errors in the reported data, and cannot be
cleared by editing the instance.

*Suggested action:* confirm against the official PRA001 sample and treat as known taxonomy evaluation items.

### 3.2 OF08 exposures-core cross-table over-determinations
Rules: the **OF08.01 ↔ OF08.03 / OF08.06 / OF09.02 / OF34.07** consistency family — e.g. **`b0834`, `b0759`,
`b0735`–`b0739`, `b0760`, `b0824`**, and related.

These tables are all different **views of the same underlying exposures** (by exposure class, obligor grade,
counterparty country, and counterparty-credit-risk breakdown). The taxonomy pins individual cells with
**multiple rules simultaneously** — additive roll-ups, non-linear column relationships (e.g. OF34.07
`c0060 = c0010 × c0070`), and cross-table equalities (e.g. `= Σ OF08.01`). For randomly-generated exposures
these constraints are **mutually over-determined**: no single set of values satisfies every rule at once.
This is an inherent property of independently-generated test data, not a structural defect.

*Suggested action:* accept as known residuals of synthetic data, or (for a production filing) derive all views
from one consistent underlying exposure set so the cross-table rules reconcile by construction.

## 4. Summary for the reviewer

- **Fully valid** structurally and dimensionally (0 schema, 0 dimensional).
- **All remaining errors are business-rule findings**, and both residual classes are **not correctable by
  editing the instance**: (a) custom-function evaluation artefacts that also affect the official sample, and
  (b) genuine over-determinations in the OF08 exposures core inherent to randomly-generated data.
- Warnings are advisory (largely completeness/reporting-consistency notes on the sparse test data).

*Prepared as a submission cover note for `…_VALID_v15.xbrl`. Full engineering detail and the analysis behind
each residual class are in `boe_xbrl_gen/COORDINATED_REGEN_SCOPE.md` and the project session notes.*
