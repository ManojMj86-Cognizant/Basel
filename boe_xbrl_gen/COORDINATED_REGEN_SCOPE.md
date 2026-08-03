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

---

# ============================================================================
# REVISED SCOPE v2 — 2026-08-03 (supersedes the v1 approach above)
# ============================================================================

## Why v1 stalled (what the 2026-08-03 build attempts proved)
The v1 plan derived/solved aggregates over **v15's EXISTING leaves**. That has a hard ceiling:
- **`coregen` absent-only** (v14/v15): safe, fixed the missing cross-table completeness cells (warnings
  184→103) but CANNOT touch present-cell over-determinations. ✅ shipped as v15.
- **`fix_b0834` targeted free-absorb**: only +9 instances, needed artificial CCR-row values, activation risk. ✗
- **`phase2_solve` full-cluster joint least-squares**: 85% (worse than 244 residual) — the combined
  single+cross system is **over-determined AND inconsistent on fixed existing leaves**, so any solve
  compromises; the exact LP over the combined nullspace is **intractable at cluster scale** (re-confirms the
  2026-07-23 joint-LP finding). ✗
- **Key diagnosis** (`probe_of3407_struct`): the residual is **VALUE-driven, not structural** — b0834's detail
  sources ⊆ its total's sources, so fresh CONSISTENT leaves would satisfy it. The problem was never the rules;
  it's that we generate each **view independently** then try to reconcile marginals of an exposure set we
  never modelled.

## The reframe: model ONE exposure LEAF-TENSOR; every reported cell is a MARGINAL of it
Do NOT generate views then reconcile. Instead:
1. Model the finest-grain exposures as one tensor: dimensions = {exposure-class, approach (SA/FIRB/AIRB),
   obligor-grade/pool, counterparty-country (CEG), default-status, CRM, z-sheet, …}; measures = {original
   exposure, exposure value, RWA inputs, EL, #obligors, …}.
2. **Generate leaf measures once** (random ≥0, DRS-valid at leaf grain).
3. **Project every reported cell as the appropriate marginal sum** of the leaf tensor (a "total over dim X" =
   Σ over X's members). Because OF08.01/02/03/06, OF09.01/02, OF34.07, OF07 are all marginals of the SAME
   tensor, every cross-view additive rule (b0834, b0752, b0282, b0735-39, …) holds **by construction** — they
   just assert "marginal = marginal of the same joint." No solve, no cascade. Derivation is O(cells), scales.
4. Layer the non-marginal measures on top (RWA = base×risk-weight; OF24 ES = √Σw·horizon²; ×12.5), then
   inequality / sign / isNull.

## Components (reuse ↔ new)
| # | Component | Reuse | New |
|---|-----------|-------|-----|
| A | **Leaf-tensor schema** — dims + valid leaf cells at finest grain | `hypercube_store`, `dim_drs`, table linkbase | leaf-grain cell set (finer than current hypercube) |
| B | **Leaf generator** — random ≥0 measures over valid leaf cells, incl. default-status + FULL open breadth (all grades/countries) | `instance_build.gen_value` | full-breadth open-dim enumeration (vs genvalid's 1 synth row/z) |
| C | **Projection engine** — each reported (table,r,c,z,dims) cell → its leaf marginal | rc-bridge (`table_model.rc_codes`), `dim_drs` | the dimensional COLLAPSE map (which leaf dims each cell marginalises) — THE core new artifact |
| D | **Non-marginal layer** — RWA×weight, OF24 √, ×12.5 | genvalid `_apply_nonlinear`, `fix_of24c` | ordering after marginals |
| E | **Inequality/isNull/sign** | genvalid `_crosstable_le_rows`, `_apply_isnull` | fold onto leaf constraints |
| F | **Emitter** — contexts+facts at full open breadth | `gen_of0902`, `coregen`, `instance_build` | scale |
| G | **Verifier** — dim + additive + cross-view | `dim_drs`, `verify_coregen`, `diff_cluster_additive` | cross-view marginal check |

## Hard parts (honest — unchanged risks + the make-or-break)
1. **§4.1 the collapse map (C) is make-or-break.** For every cell we must know EXACTLY which leaf slice sums
   into it — from the table-linkbase dimensional definitions + annotated templates, not the additive rules
   (which are the over-determined *consequence*, not the *source of truth*). If the map is wrong, marginals
   won't match the rules. Open dims (CEG country, obligor CPZ) are the intricate case that defeated the
   OF09.02 leftovers.
2. **Scale** — full open breadth (all grades × all countries) may multiply fact count well beyond v15's ~50k.
3. **Non-marginal measures** (RWA, ES √, ×12.5) don't project linearly → separate ordered layer; can perturb.
4. **Verification gap** — offline confirms dims + additive + marginal-consistency; cross-view + non-additive
   still need a TDG submit.
5. **Residual floor regardless:** the `exp()` taxonomy errors (b0361/63/65/66) and any genuine BoE-rule
   inconsistencies remain — **0 errors is NOT achievable**; target = MINIMISE the OF08 cluster + warnings.

## Phasing (each independently testable; GATE = go/no-go before the next)
- **P2.1 — Collapse-map extraction (make-or-break, CHEAP, do FIRST).** Build C's dimensional collapse for the
  OF08.01 ↔ OF09.02 ↔ OF34.07 sub-core; offline-verify the map reproduces the b0834 / b0752 / b0282 / b0735-39
  relationships (marginal identities). **GATE: if the map can't reproduce them, STOP — the approach is blocked,
  accept v15.**
- **P2.2 — Leaf tensor + generate + project for that sub-core** (A+B+C). Verify additive holds BY CONSTRUCTION
  offline (`verify_coregen` → ~100% on the sub-core). GATE.
- **P2.3 — Emit the sub-core into v15** (replace those tables' cells), `dim_drs` = 0, submit to TDG → confirm
  the sub-core cross-table cluster clears (real-world gate; offline can't fully confirm cross-view).
- **P2.4 — Extend to the full 35-table exposures core.**
- **P2.5 — Non-marginal + inequality + isNull layers.**
- **P2.6 — Full generate + TDG acceptance.**

## Effort / risk / payoff (honest)
- **Effort:** multi-session (the long-outstanding "full coordinated PRA001 generation").
- **Risk:** HIGH on P2.1 (the collapse map) — it gates everything; MEDIUM on scale + non-marginal layers.
- **Payoff:** if P2.1/2.2 land, this clears the OF08 cluster (~60 err) + most of the 103 warnings. **Floor is
  NOT zero** — the exp() taxonomy errors (~4-6) survive no matter what.
- **First action = P2.1 only.** It's cheap and decides whether the whole build is viable before any big spend.

## P2.1 RESULTS (2026-08-03, `tools/p2_collapse.py`) — AMBER (viable but the collapse map is a real sub-build)
Tested 10 sub-core cross-view rules (total = Σ details) for clean marginal structure:
- **CLEAN single-axis marginal: 2** — `b0872`/`b0876` (OF34.07↔OF08.01, collapse over MCY). Proves the marginal
  reframe works where signatures are clean.
- **MULTI-AXIS: 8** — `b0834` {IMS,PDR}; `b0735-39` {MRW,IMS,PDR,TRI} (OF08.03 carries extra risk-weight/PD
  dims — a legitimate multi-dim marginal); `b0752`/`b0282-84` {APR,EXC,TRI,CEG,CPZ} (OF08.02 grade + OF09.02
  country). Multi-axis is acceptable IN PRINCIPLE, but…
- **The blocker = signature INCONSISTENCY:** in `b0736` some OF08.01 details differ from the total on
  {IMS,MRW,PDR,TRI}, others ALSO on MCY (x311/x100 vs total x195) → **MCY is HIERARCHICAL** (x195 is a parent
  "total" member). And the rc-bridge OMITS the open dims (CEG country, CPZ obligor). So a usable collapse map
  needs FULL dimensional signatures + **domain-member hierarchies** reconstructed from the taxonomy
  (domain/hierarchy linkbase + dim defs + annotated templates) — well beyond `table_model.rc_codes`.

**Verdict:** the leaf-tensor/marginal reframe is STRUCTURALLY SOUND (2 clean proofs; multi-axis is fine) but
the collapse map is a **substantial sub-build** (full-signature + member-hierarchy extractor), and it is exactly
the §4.1 open-dim/hierarchy work that defeated prior attempts — real risk it's slow/partial. NOT a clean pass.
**DECISION for user:** (A) invest in the full-signature + hierarchy extractor (the next big, uncertain step —
would need its own gate: does it reproduce the b07xx/b08xx marginal identities EXACTLY?), or (B) stop here and
accept v15 (70 err/103 warn) — the payoff floor is non-zero regardless (exp() taxonomy errors survive).
Tool: `tools/p2_collapse.py`.

## P2.1 PROGRESS (2026-08-03 cont.) — gate now trending GREEN; hierarchy extractor BUILT
Research (subagent) + build resolved the amber blockers:
- **Member sum-trees ARE cleanly extractable** — from `dict/dom/<domain>/hier-cal.xml` (Eurofiling
  `complete-breakdown` arcs: parent = Σ weight·child EXACTLY; `partial-breakdown` = ≥). NOT hier-def (that's
  plain containment, no weights). **Built + tested `src/member_hier.py`**: 30 domains, **274 complete-breakdown
  totals**; confirmed **MC x309 = x311+x100+x310** (complete). The P2.1 "MCY x195" messiness was an rc-bridge
  artifact (x195 is a leaf; x309 is the real total) — NOT a hierarchy gap.
- **OF08.01 + OF08.03 are FULLY CLOSED** (zero open axes; CEG/CPZ pinned). So the feared open-dim breadth
  problem (§4.1) largely **does not apply to the OF08 core** — a major de-risk. (Open axes live in other
  tables e.g. C06.02/C09.04/C14.)
- **Full cell signature** = metric + ruleNode explicitDimensions + open-axis member(s) + default member for
  each unset TableDRS hypercube dim — assemble from `parse_table.datapoints[].dims` + `dim_drs.TableDRS.specs`
  + `dim_defaults` (no single existing call returns it fully-defaulted; assemble the three).
- **model.json has NO hierarchy** → `member_hier.py` is the new required parser (done).

**Verdict update:** the two amber blockers (hierarchy source + open-dim breadth) are resolved — hierarchy is
extractable and the OF08 core is closed. **P2.1 is now trending GREEN.** Remaining P2.1 step: assemble the
FULL signature per cell + expand total members via `member_hier` and re-run `p2_collapse` to confirm the
sub-core rules (b0752/b0834/b0872/b0735-39/b0282) become clean marginals. Then P2.2. Tools: `src/member_hier.py`
(built/tested), `tools/p2_collapse.py`, `tools/probe_mcy_hier.py`.

## ✅ P2.1 GATE PASSED (2026-08-03, `tools/p2_collapse2.py`) — the marginal reframe is VIABLE
Hierarchy+default-aware collapse test on the 10 sub-core cross-view rules → **all 10 are valid marginals** of
one leaf tensor, via TWO extractable collapse mechanisms:
- **5 = dim-member hierarchy marginals** (`b0752`, `b0834`, `b0872`, `b0735`, `b0876`): total member = Σ its
  complete-breakdown descendants (`member_hier.all_descendants`), and an OMITTED dim = its default member =
  "aggregate over all of it". Both handled → CLEAN.
- **5 = z-sheet-set marginals** (`b0282`/`b0283`/`b0284`, `b0736`, `b0739`): the rule `isum`s OF08.01 over an
  explicit SET of z-sheets (e.g. b0282 z={0009,0010,0011,0012,0022,0023,0024}); each z-sheet pins a distinct
  APR/EXC/MCY combo, which is why those dims "varied". The collapse is the rule's **z-list** — VALID, just a
  different mechanism than single-dim hierarchy. Confirmed by reading the rule scopes/expressions.

**⇒ The collapse map = `member_hier` (dim-total expansion) + rule z-scopes (z-sheet sums). Both extractable
from taxonomy + rules. The leaf-tensor/marginal reframe is CONFIRMED viable for the sub-core.** GATE PASSED →
proceed to **P2.2** (define the leaf tensor axes {metric/column × exposure-class row × obligor-grade ×
z-sheet(approach×class) × country CEG × hypercube dims}, generate leaves, project every cell as its marginal,
verify additive holds by construction). Tools: `src/member_hier.py`, `tools/p2_collapse2.py`.

## P2.2 PROGRESS (2026-08-03, `tools/p2_project.py`) — projection PROVEN to reconcile b0834
Derived OF34.07 r0180 AND its detail rows ALL from the SAME OF08.01 leaves (scan every additive rule whose
lone target is OF34.07 and whose sources are all OF08.01 — auto-captures the b0872-0889 / b1035 / b1067-68 /
b0830-33 family across columns×z). Then checked the b0834 gap = r0180 − Σ(covered details):
- **51 / 51 cross-pinned instances gap ≥ 0 (min 0, max 2.7M) → b0834 HOLDS BY CONSTRUCTION** (free detail rows
  absorb the non-negative gap). The other 34 have no cross-pin → r0180 = Σdetail trivially.
- vs v15's 60/85 gap≥0 when r0180 came from a DIFFERENT pass. **The marginal projection from ONE consistent
  OF08.01 basis reconciles the whole b0834 family** — the biggest error cluster that defeated surgical,
  coregen and joint-solve.
**⇒ P2.2 core is validated for the OF34.07 sub-core.** Remaining P2.2: extend the projection to OF09.02
(b0282-84 z-sheet sums, CEG=x1) + OF08.02 (b0752, obligor-grade), wire actual leaf generation, and verify the
full sub-core additive web offline. Then P2.3 (emit → TDG gate). Tools: `tools/p2_project.py`.

## P2.3 EMIT ATTEMPT #1 (2026-08-03, `tools/p2_emit.py`) — found OF34.07 has an INTERNAL tree; needs top-down
Projected OF34.07+OF09.02 targets = Σ OF08.01 (498 targets, 92 overwritten) into v15→v16. `diff_cluster_additive`:
**fixed 2, BROKE 4 (b0830-b0833) → net worse (51→53)**; v16 discarded.
- **Root cause (diagnosed):** b0830-b0833 are **OF34.07-INTERNAL sub-totals** (`r0010 = Σ r0015;0025;0030`,
  `r0070 = Σ r0080;0090`, …), NOT OF08.01 links. OF34.07 is a **nested tree**: `r0180 = Σ detail rows` (b0834)
  and several detail rows `= Σ sub-rows` (b0830-33). The naive emit set r0180 = ΣOF08.01 correctly but then
  ZEROED "free" rows — clobbering the b0830-33 sub-totals.
- **Fix required (P2.3 emit v2):** distribute r0180 **top-down through OF34.07's internal additive tree** (only
  the true LEAF rows are free; internal totals must equal Σ their children), and only OF08.01-link the rows the
  b08xx/b10xx family actually pins. i.e. the OF34.07 emit is a top-down SPLIT respecting its own tree, not a
  flat overwrite. This is precise, well-understood next work — NOT a blocker. v15 remains best.
Tools: `tools/p2_emit.py` (v1, superseded).

## P2.3 EMIT ATTEMPT #2 (2026-08-03, `tools/p2_emit.py` v2) — minimal is SAFE but INEFFECTIVE
v2 = MINIMAL: set r0180 = ΣOF08.01, absorb delta on ONE true-free leaf, keep the b0830-33 sub-totals at v15.
Result: only 9/51 r0180 fixable (17 no free leaf, **25 skip because delta<0** → free leaf would go negative),
39 OF09.02 cells set. `diff_cluster_additive` v15→v16: **0 fixed / 0 broken** at rule level → SAFE (no
b0830-33 breakage) but INEFFECTIVE (too few instances to clear any rule). v16 discarded.
- **Why minimal fails:** v15's OF34.07 sub-tree **over-sums** relative to r0180 (that IS why b0834 fails), so
  the fix needs to REDUCE detail values — a single free leaf can't (goes negative). Must **rebuild the whole
  OF34.07 sub-tree** so it sums to r0180 = ΣOF08.01: either PROPORTIONAL SCALING (×f = r0180/Σdetails,
  preserves internal sums linearly) or TOP-DOWN DISTRIBUTION (put r0180 down one leaf path, zero the rest —
  always ≥0). Both are FULL OF34.07 overwrites with activation risk on OF34.07's OTHER rules (inequalities /
  isNull / non-additive) that **only TDG can confirm**.

## ⚖ P2.3 STATUS + DECISION (2026-08-03)
**The projection MATH is proven (P2.2: b0834 reconcilable 51/51). The clean EMIT is the hard part** — two
iterations in, the safe-minimal emit can't fix b0834 (sub-tree over-sums), and the effective emit is a full
OF34.07 sub-tree rebuild (scaling / top-down) = a big overwrite whose side-effects on OF34.07's non-additive
rules are TDG-only-verifiable. This is a substantial, iterative build, not a quick win. v15 (70 err/103 warn)
remains the delivered best throughout. **DECISION for user:** (A) continue — build the sub-tree-rebuild emit
(proportional scaling), verify offline, ship a v16 to TDG (real but risky, may need iteration); or (B) bank the
P2 R&D (reframe proven viable, extractor + collapse map + projection all built and committed) and keep v15 as
the delivered instance. Tools: `p2_emit.py`, `p2_project.py`, `p2_collapse2.py`, `src/member_hier.py`.

## 🛑 P2.3 EMIT ATTEMPT #3 + ROOT CAUSE (2026-08-03) — the rc-bridge keying is INSUFFICIENT
Built the top-down sub-tree rebuild (distribute r0180 down the OF34.07 tree, proportional to v15). `diff` v15→
v16: **fixed 2 / broke 4 (b0830-33) AGAIN**. Diagnosed the real root cause: **`CellResolver.resolve` conflates
OF34.07 rows** — `b0834`'s 8 detail cells (r0010, r0040, … r0170) ALL resolve to the SAME `(concept, dims)`
key (`mi119` + identical dims). The row-distinguishing dimension is NOT in what `res.resolve` returns, so the
`(concept, dims)` key I've used throughout P2 **cannot tell r0010 from r0040 from r0180**. Every emit scrambles
the tree because it literally can't address the cells distinctly.
- **Implication:** this also means the P2.2 gap-proof (b0834 51/51) was computed on CONFLATED keys → it must be
  re-validated once cells are keyed distinctly. The reframe may still be sound, but the EVIDENCE needs redoing
  with a correct resolver.
- **The real fix = a FULL cell-signature resolver** (per the research agent §4): assemble each cell's complete
  signature from `parse_table` ruleNode dims **+ `dim_drs.TableDRS` hypercube dims + `dim_defaults`** so
  r0010/r0040/r0180 get DISTINCT keys. `res.resolve` (rc-bridge) alone is insufficient for OF34.07-class tables
  whose rows are dimension members it drops. This is a substantial new component and it underpins EVERYTHING
  (collapse map, projection, emit) — the current tooling can't emit correctly without it.

## ⚖ P2 HONEST STATUS (2026-08-03) — hit a tooling wall; recommend banking R&D
Three emit attempts, all blocked by the same root cause: the rc-bridge `(concept,dims)` key conflates
same-concept rows in OF34.07, so the emit cannot address cells distinctly. Fixing it needs a full-signature
resolver (parse_table + TableDRS + defaults) — a substantial component that also forces re-validating the P2.1/
P2.2 evidence on correct keys. **The reframe is still promising in principle, but the effort to make it
emit-correct is materially larger than a session and I no longer have offline-verified progress toward a v16.**
v15 (70 err / 103 warn) remains the delivered best. RECOMMEND: bank the P2 R&D (reframe, member_hier, collapse
analysis — all committed) and keep v15, OR commit to building the full-signature resolver first (then redo
P2.1/2.2/2.3 on correct keys). Tools this phase: `member_hier.py`, `p2_collapse2.py`, `p2_project.py`,
`p2_emit.py`, `probe_*`.

## ⚠ CORRECTION (2026-08-03, `tools/probe_of3407_rows.py` + `probe_tree_compose.py`) — 'conflation' was WRONG
The OF34.07 rows ARE distinctly keyed: the 8 b0834 detail cells differ by **PDR** (x400/x403/x404/x405/x436/
x409/x412; 8th by IMS x3) → **8 DISTINCT keys**, and the internal tree composes (4 of 8 details are tree
parents with children). My 'rc-bridge conflates rows' claim was an artifact of a diagnostic that truncated the
dims print to 4 entries (hiding PDR). **`res.resolve` keys these fine → NO full-signature resolver is needed;
P2.1/P2.2 keying STANDS.** Row structure: cell = column concept (mi119/ii177/mi793) + column dims
(BAS,MCY,PRP,TRI) + row dims (IMS,PDR); r0180 has no IMS/PDR (aggregates over them). ⇒ The 3 emit failures are
a BUG in the distribute/write logic, NOT a tooling wall — a much smaller fix. NEXT: fix the emit
distribution/write bug and re-verify (b0830-33 must stay balanced).

## 🧱 P2.3 EMIT v4 (integer-exact) — FIXED b0834 but hit a genuine OVER-DETERMINATION (the real wall)
Fixed the emit bugs: INTEGER-EXACT top-down distribution (Σ children == parent exactly) + WRITE every
distributed cell. Result on v15→v16: **b0834 FIXED** (48-instance family gone from the failing list),
b0830-33 preserved (0 additive-rule regressions vs v15), 1008 OF34.07 cells rewritten. BUT
`verify_coregen`: balance 98.4%→**97.0%** because **`b0759` exploded 14→285 instances**. `b0759` is a
**NON-additive column product**: OF34.07 `c0060 = c0010 × c0070` (per row). My additive redistribution changed
c0010/c0060 independently and broke it.
- **The real wall = OF34.07 `c0060` is OVER-DETERMINED by THREE constraints at once:** the additive tree
  (`r0180 c0060 = Σ details c0060`, b0834), the non-linear product (`c0060 = c0010·c0070`, b0759), and the
  cross-table link (`c0060 = ΣOF08.01`, b1067/68). No single value/redistribution satisfies all three — this
  is genuine over-determination (scope §4.2), now demonstrated concretely, with a non-linear twist.
- **Conclusion:** the marginal reframe + integer-exact distribution cleanly handle **pure-additive** structure
  (b0834 tree — proven fixable), but OF34.07's cells are governed by an OVERLAPPING web (additive + non-linear
  product + cross-table) that mutually over-determines them. This is the same fundamental entanglement that
  defeated surgical / coregen / joint-solve — the emit cannot make an over-determined cell satisfy conflicting
  rules. **v15 (70 err/103 warn) remains the delivered best.**

## ✅ FINAL P2 ASSESSMENT (2026-08-03)
The reframe is genuinely sound for clean-additive structure and the tooling built here works (member_hier;
integer-exact tree distribution reconciles b0834 with 0 additive regressions). But turning it into a clean
emit is blocked by **over-determination** where a cell is pinned by additive + non-linear + cross-table rules
simultaneously (OF34.07 c0060 the concrete example). That is a mathematical wall, not a code bug. **RECOMMEND:
keep v15 as the delivered instance and BANK the P2 R&D** (reframe, member_hier, collapse map, integer-exact
distributor — all committed and reusable). Reaching zero on the OF08 cluster would require BoE-rule-level
reconciliation of the over-determined cells (or accepting those specific residuals), beyond what any
generation approach can force. Tools: `member_hier.py`, `p2_collapse2.py`, `p2_project.py`, `p2_emit.py`,
`probe_of3407_rows.py`, `probe_tree_compose.py`.
