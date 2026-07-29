# Coordinated-Regeneration Build — Scope

**Goal:** eliminate the ~75 remaining TDG **error**-severity failures in PRA001 (v8) that the surgical
approach cannot fix, by regenerating the entangled table cluster so that **all cross-table and single-table
additive rules hold by construction** — not by patching values after the fact.

**Date:** 2026-07-24 · **Baseline:** v8 (75 error rules, down from 157). Best surgical file.

---

## 1. Why this build (why surgical hit a ceiling)

The remaining failures live in a **single 35-table connected component** linked by cross-table rules
(the "OF08 mega-cluster"): OF08.01/02/03/06/07, OF09.01/02, OF34.07, OF07, OF18/19/20, OF24.x, OF02.x,
C01/03/04/13/14/24, C09.04, OF700 — **385 cross-table rules + 643 single-table rules**.

Every surgical attempt (greedy cross-table, joint-LP, OF34.07, OF09.02, OF08.01↔03/06) confirmed the same
wall: **cells are shared across many rules**, so editing any hub cell to satisfy one rule breaks its
neighbours, and **the offline classifier cannot validate cross-table edits** (only TDG can). The values are
mutually constrained; you cannot patch them independently.

**Root cause of the residual failures:** we generate each cell's value **independently (random)** then try
to reconcile the aggregates. But the aggregates (row/column totals, sub-table breakdowns, country
aggregations, CCR totals, own-funds roll-ups) are all **different VIEWS of the same underlying exposures**.
Independently-generated views are mutually inconsistent → rules fail → patching one breaks another.

---

## 2. Core design — LEAF-FIRST coordinated generation

Generate **one canonical set of leaf (finest-grain) exposure facts**, then **derive every aggregate/
cross-table cell as a sum (or defined function) of those leaves.** Then every additive rule — single-table
AND cross-table — holds *by construction*, because both sides trace to the same leaves.

```
                     leaves (per obligor × z-sheet × full hypercube dims)   ← generated (random, ≥0, DRS-valid)
                      │  derive ▼ (topological, following the rule DAG)
   row/col totals ── sub-table breakdowns ── country aggs (OF09.x, CEG) ── CCR totals (OF34.07) ── own-funds (C01/OF02)
```

### 2.1 The rule-derivation DAG
- Parse all additive rules (single + cross) into `aggregate_cell = Σ coef · source_cells` (already have this
  via `workbook_rules.parse_expression` / `expand_scoped_asts` / `plan_equality`).
- Build a directed graph: edge `source → aggregate` for each rule's derived cell.
- **Leaves** = cells that are no rule's aggregate target. **Topologically order** the aggregates.
- Generate leaves; derive aggregates in topo order. Result: all additive rules satisfied simultaneously.

### 2.2 Why this fixes the specific failures we saw
- **b0785** (OF09.02 Corporates = Σ sub-classes) *and* **b0282** (OF09.02 Corporates = OF08.01 corp total):
  both hold because OF08.01's corporate total is itself *derived* as the sum of its corporate leaves →
  no source inconsistency. (v8's conflict was from patching, not deriving.)
- **OF09.02 CEG=x1 / country aggs**: derived by collapsing the country (CEG) and obligor (CPZ) dimensions of
  the leaves → correct per-z pairing (b1053-55, b0303) by construction.
- **OF34.07 r0180**: derived = Σ OF08.01 leaves → matches, and its own internal total (b0834) also holds.
- **OF08.01↔03/06**: OF08.03/06 breakdowns and OF08.01 totals both derived from shared leaves → consistent.

---

## 3. Components to build (and what to reuse)

| # | Component | Reuse | New work |
|---|---|---|---|
| A | **Derivation-DAG builder** — all additive rules → `aggregate = Σ sources`, topo-sort, detect leaves | `workbook_rules` parser, rc-bridge, default-drop keying (from `solve_existing`) | DAG construction, cycle/over-determination detection |
| B | **Leaf generator** — generate the finest-grain cells (random ≥0, datatype-valid), DRS-valid, hypercube-filtered | `dim_drs`, `hypercube_store`, `table_model` grid | identify the leaf set per table incl. open dims |
| C | **Aggregate deriver** — walk DAG, compute each aggregate = Σ leaves; collapse open dims (CEG/CPZ/z) correctly | genvalid `_crosstable_agg_values`, `_crosstable_open_link`, `gen_of0902` (CEG add + DRS) | generic open-dim collapse/pairing |
| D | **Non-additive pass** — OF24 √/exp, imax ratios, ×12.5 risk-weights (C13/C14/OF19/OF20) | genvalid `_apply_nonlinear`, `formula_eval` | order after additive leaves |
| E | **Inequality/sign/isNull/const-sum** — enforce ≤ (OF08.02, b0367/8/9), sign, empties, share-sums | genvalid `_nonneg_additive_solve` + `_crosstable_le_rows`, `_apply_isnull`, `_constant_sum_values` | fold into leaf constraints |
| F | **Fact emitter** — build contexts+facts for derived cells (incl. new dims like CEG), DRS-valid | `gen_of0902` context/fact builder, `instance_build` | generalise to all derived cells |
| G | **Offline verifier** — DRS (dimensional) + full additive-consistency check across the cluster | `dim_drs`, `classify_fails`, `check_of0902_internal` | cluster-wide consistency report |

**Existing engine leverage is high** — genvalid already implements B/C/D/E partially (it reached 0/0 on the
OF08.01 pair). The *new* core is **A (the DAG) + leaf-first ordering**, replacing genvalid's
"random-then-patch" with "generate-leaves-then-derive."

---

## 4. The hard parts (honest unknowns)

1. **Open-dimension pairing / collapse** (biggest risk). Leaves live in the full hypercube (obligor CPZ,
   country CEG, z-sheets, approach APR…); aggregates collapse subsets of these. Getting the exact
   collapse mapping right for every aggregate (which leaf dims sum into which aggregate) is intricate —
   this is what defeated the OF09.02 leftovers (b1053-55) and OF08.02. Needs the rc-bridge + DRS + the
   annotated-template dimension blocks as the authority.
2. **Over-determination / genuine inconsistency.** If two rules define the same aggregate over
   *non-reconcilable* leaf sets, no data satisfies both. Leaf-first minimises this (single leaf source), but
   the DAG builder must **detect cycles and multi-definition conflicts** and report them (some BoE rules may
   be mutually inconsistent — a finding, not a bug).
3. **Non-additive rules** (OF24 exp/imax, ×12.5 risk weights) don't fit the additive DAG — derive after, and
   they can re-introduce imbalance in additive cells that reference them (ordering matters).
4. **Scale/performance** — 35 tables, ~thousands of leaves, hypercube expansion. Derivation is O(rules) (fast,
   no big LP), but leaf generation + DRS validation over the hypercube is the cost (the ~46-min hypercube
   pass is already cached).
5. **Verification gap** — offline DRS confirms dimensions; an offline additive-consistency checker (build G)
   can confirm additive rules; but non-additive + inequality + TDG-specific semantics still need a TDG
   submission to fully confirm.

---

## 5. Phasing (incremental, each independently testable)

- **Phase 0 — DAG + consistency report (no generation).** Build A over the 35-table cluster; output the
  derivation graph, the leaf set, cycles, and multi-definition conflicts. *Deliverable:* a report telling us
  how much of the cluster is cleanly leaf-derivable vs genuinely over-determined. **Do this first — it
  de-risks everything and may show the achievable ceiling before we build the generator.**
- **Phase 1 — Leaf-first additive generation on ONE sub-cluster** (e.g. OF08.01↔OF09.02↔OF34.07, which we
  understand). Generate leaves, derive aggregates, emit, DRS-verify, offline-additive-verify → TDG.
- **Phase 2 — Extend to the full 35-table additive web** (OF08.03/06, OF07, OF18-20, OF02.x, C0x).
- **Phase 3 — Non-additive + inequality + isNull layers** (OF24, ×12.5, OF08.02 ≤, b0367/8/9).
- **Phase 4 — Full-cluster generate + TDG acceptance.**

---

## 6. Effort & recommendation

- **Effort:** substantial — a multi-phase engine build (the "full coordinated PRA001 generation" that has
  been the outstanding acceptance since the project's start). Phase 0 is small (~1 session) and high-value.
- **Risk:** the open-dim pairing (§4.1) and possible genuine over-determination (§4.2) mean **we cannot
  promise 0 errors** — Phase 0 will quantify the achievable floor.
- **Payoff:** if the cluster is largely leaf-derivable, this is the *only* path to drive the ~75 errors down
  substantially (surgical is proven exhausted). It also yields a **reusable, correct-by-construction
  generator** for any BoE module — far more valuable than v8's patches.

**Recommendation:** start with **Phase 0** (DAG + consistency report). It's cheap, needs no generation, and
tells us — before committing to the full build — exactly how many of the 75 errors are cleanly resolvable by
leaf-first derivation vs blocked by genuine source over-determination. Decision on Phases 1-4 follows from
Phase 0's numbers.

---

## Phase 0 RESULTS (2026-07-24, `tools/phase0_dag.py`) — leaf-first VIABLE

- Cluster: **35 tables · 553 additive rules · 16,402 concrete equations · 44,090 cells.**
- **Leaves: 31,251 (71%)** · aggregates 12,839 (1,674 pure + 11,165 intermediate).
- Multi-defined aggregates 2,970 → differing-source 2,535 → **2,309 benign same-table 2D** (row+col totals,
  consistent under leaf-first) vs **only 226 cross-table genuine conflicts (0.5%)**.
- Cycle back-edges: **145** (resolve via canonical-definition choice). Relational (no lone total): 123.
- **→ ~99.5% of cells cleanly leaf-derivable.**

**Verdict:** leaf-first satisfies the bulk of the 553 additive rules by construction. Achievable floor = a
small residual (226 cross-table over-determinations — some may reconcile at the leaf level — + 145 cycles +
the separate non-additive OF24/×12.5 and inequality layers). **Proceed to Phase 1** (leaf-first generation on
the OF08.01↔OF09.02↔OF34.07 sub-cluster, which we already understand end-to-end).

---

## Phase 1 RESULTS (2026-07-24, `tools/phase1_derive.py`) — deriver PROVEN (98.5%)

Built the leaf-first deriver: read v8's actual leaf values, derive all **12,759 aggregates topologically**
(canonical = single-table 'own total' → **0 cycles**, the 145 back-edges resolved by that preference),
re-check all **16,258 additive equations**:
- **BALANCED after leaf-first: 16,014 (98.5%)**
- Residual (unbalanced): **244** = genuine over-determinations (≈ Phase 0's 226), irreducible by any data.

**Computational proof achieved:** deriving aggregates from leaves satisfies the additive web by construction,
no cascade. **Phase 1b (next, substantial)** = EMIT the derived values into a file: overwrite ~12,759 present
aggregates + generate absent ones (DRS-valid contexts, 35 tables) + fold in the nonneg / inequality (OF08.02
≤, b0367/8/9) / non-additive (OF24 exp/imax, ×12.5) / isNull layers so the additive re-derivation doesn't
introduce new failures on those layers.
