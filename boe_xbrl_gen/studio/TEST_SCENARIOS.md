# Datapoint Studio — Test Scenarios (manual QA checklist)

End-to-end test scenarios for **everything built so far** (Phases 0 → 2 + Rules/Validate/Scope/
Upload-binding). Most items have been verified at **API + build level**; the **visual click-through
is the outstanding QA**. Work top-to-bottom. Concrete expected values are for **BoE Banking
4.0.0** (`boebanking400.zip`, sha `50c2f2…`).

Legend: **[A]** verified via API/engine, **[B]** build/tsc verified, **[V]** needs visual check.

---

## 0. Prerequisites / start the app
```powershell
# Backend — port 8201, NO --reload
cd C:\Users\177069\ClaudeLearning\boe_xbrl_gen\studio\backend
$env:PYTHONIOENCODING="utf-8"; python -m uvicorn app.main:app --port 8201 --log-level warning
# Frontend
cd C:\Users\177069\ClaudeLearning\boe_xbrl_gen\studio\frontend; npm run dev
```
- **P1** Open http://localhost:5173 → the app loads (Home/Guide), nav shows Home · Ingest ·
  Dictionary · Tables · Amend · Rules · Validate. Dictionary/Tables/Amend/Rules/Validate are
  **disabled until a package is selected**. [V]
- **P2** `GET http://localhost:8201/api/health` → `{status:"ok"}`. [A]
- Test inputs on disk: `boebanking400.zip` (banking), `boe-insurance-taxonomy-v201.zip` (insurance),
  sample instances in `boebankingtaxonomysampleinstancesv400/` (e.g. PRAMEM, RFB002, PRA001).

---

## 1. Phase 0 — Ingest
- **I1** First upload of `boebanking400.zip` (56 MB) → live **N / total files** progress bar →
  summary card. (~4–5 min one-time; cached after.) [A]
- **I2** Re-select banking from the **Loaded packages** dropdown → instant (cache hit), chip reads
  **cached**. [A]
- **I3** Summary shows: version **4.0.0**, **25 entry points**, **10 frameworks**; model count cards
  appear once the dictionary is built (metrics 1098 · dims 376 · domains 68 · members 5442). [A]
- **I4** Upload the **insurance** package → **6 frameworks / 12 entry points**, no "(unknown)"
  frameworks (taxonomy-agnostic). [A]
- **I5** **Delete** a cached package → disappears from the dropdown immediately; re-upload works. [A]
- **I6** Re-uploading the **same** zip is a cache hit (no re-extract). [A]

## 1a. Phase 1a — Dictionary
- **D1** Select banking → Dictionary tab → "building… ~60–110 s" bar (first time) → renders. [A]
- **D2** Count chips: metrics **1098**, dims **376**, domains **68**, members **5442**. [A]
- **D3** Section tabs Metrics/Dimensions/Domains/Members switch; server-paginated (50/page),
  Prev/Next work. [V]
- **D4** Search box (debounced) filters by code/label/qname (e.g. metrics search "own funds"). [V]
- **D5** Metric rows show **datatype** with `refine`/`excel` tags; member rows show qname +
  usable/default flags. [V]
- **D6 Reconcile:** upload the DPM dictionary `.xlsx` (or the DPM-pack `.zip`) via the top dropzone →
  diff panel: **1 datatype conflict** (`ti761` BOOLEAN vs STRING), dims 376 vs 374, members
  5406=5406, **36 redeclared**; `reconciled` chip turns on. [A]
- **D7** Insurance package reconcile (DPM dict) parses without 500 (tolerant column handling). [A]

## 1b. Phase 1b — Tables
- **T1** Tables tab → "indexing…" (~30 s first time) → left tree grouped by **framework**;
  totals **286 tables / 182,009 datapoints / 10 frameworks**. [A]
- **T2** Expand a framework → tables with datapoint counts; `open` tag on open-axis tables;
  filter box narrows by code. [V]
- **T3** Click **C01.00.01.01** → right grid: **106 datapoints**, Metric code+label · Datatype ·
  one column per dimension (member codes, label tooltip); paginated. [A]
- **T4** Model-enriched labels present (e.g. `mi81` MONETARY "Amount including transitional
  provisions"). [A]

---

## 2. Framework ▸ Entry-point scoping (Dictionary / Tables / Rules)
- **S1** Each tab shows a **Framework** dropdown (All + the 10 frameworks) and an **Entry point**
  dropdown that repopulates from the chosen framework. [V]
- **S2 Tables** scope: All=**286**; framework `leverage`=**13**; entry point `lvr002`=**6**. [A]
- **S3 Dictionary** scope (concepts USED by the scope): All metrics=**1098**; entry point
  `pra_mem`=**12 metrics**; `lvr002` members=**22** (vs 5442 full). [A]
- **S4** Dictionary "All / All" = the full dictionary (no filter). [A]
- **S5 Rules** scope: framework filters the entry-point list; an entry point is **required** (no
  "All entry-point" for Rules). [V]

## 3. Rules tab (business validation rules)
- **R1** Rules tab → pick entry point `pra_mem` → builds in ~1 s → **2 rules** (`boe_b1_m`,
  `boe_b2_m`) with human message + Tables + collapsible formal `test`. [A]
- **R2** Pick `pra001` → ~2 min first build (cached after) → **1448 rules** (889 ERROR / 559
  WARNING). [A]
- **R3** Search `q=b0076` → 1 rule; it shows the cross-table tables it touches (e.g. OF25.x). [A]
- **R4** Table filter (the 3rd dropdown) restricts to rules touching a chosen table. [A]
- **R5 "View related rules"** from Tables: select **C01.00.01.01** → click ⚖ **View related rules**
  → jumps to Rules pre-set to `banking_reporting / pra001 / C01.00.01.01` → **38 rules**, of which
  **12 cross-table** (e.g. `b0787` → OF02·C03·C01, with C01 highlighted). [A]

---

## 4. Phase 2 — Amend grid (datatype restrictions, resize, paste)
Select tables in Tables (tick checkboxes) → **Edit N tables →** → Amend tab (chip-tab per table).
- **A1** Datatype widgets per cell: **ENUMERATION**→dropdown, **BOOLEAN**→true/false dropdown,
  **DATE**→date picker, MONETARY/DECIMAL/PERCENTAGE/INTEGER→numeric-guarded text, STRING→free. [V]
  - Open **C06.02.01.01** → an enum cell ("Type of entity") is a dropdown with **14 options**
    (Credit institution, Investment firm, …). [A]
- **A2** Off-type value → cell gets a **red outline** + tooltip; a valid value clears it. Type
  letters in a MONETARY cell to see it flag. [V]
- **A3** "Show datatypes" toggle shows datatype under row/column headers (C01 rows MONETARY; C14
  columns STRING). [A]/[V]
- **A4** **No pagination** — all rows render in one scrollable grid (sticky headers). [V]
- **A5** **Resize**: drag a column header's right edge, the row-label width (corner right edge), the
  **header-row height** (corner bottom edge), and a row's bottom edge — all resize live. [V]
- **A6** **Full screen** (⛶) toggles an overlay; wrapping headers readable. [V]
- **A7** **Z-axis** table (e.g. OF07.00.01.01, 16 sheets) → Z selector switches sheets; "Sheet:" label
  echoes the long name. [A]/[V]
- **A8 Multi-cell paste from Excel**: click-drag to select a rectangle (highlights), copy a block in
  Excel, **Ctrl+V** → fills from the selection's top-left; bad pasted values flag red. [V]

## 5. Generate Data + Create XBRL (build only)
- **G1** **⚄ Generate Data** → fills every datapoint cell of all selected tables with datatype-valid
  random values (instant, no Arelle): enum→a random allowed member, boolean true/false, dates,
  numbers, strings. [A]/[V]
- **G2** **⤓ Create XBRL** → **instant** (no Arelle); result panel: per-module instance with facts/
  contexts counts + **download link**. pra_mem → 43 facts; C14 (pra001) builds in ~8 s **(no 500)**. [A]
- **G3** Downloaded file: BOM + `<?xml?>`, `schemaRef` to the module, contexts (entity scheme
  iso/17442, placeholder LEI `ABCDEFGHIJ0123456789`, date 2026-02-28), uPURE/uGBP units, filing
  indicators, facts. [A]
- **G4** Multi-framework selection → one instance **per module**; `unmapped`/`errors` reported, never
  a crash. [A]

## 6. Open-axis rows + Z + select/delete (generate-from-scratch)
Use an open-axis table (e.g. **SR802.01.02.01** = open typed dim INC; or C14.01.01.01).
- **O1 + Add row** → a new row appears with an **editable open-dim value** (e.g. `INC=1`) in its
  header. Add a few → `INC=1, 2, 3`. [A]/[V]
- **O2 Generate Data** → fills the added rows **across all Z sheets** (flip the Z selector to
  confirm), not just sheet 1 (this was the "only Row 1" bug — now fixed). [A]/[V]
- **O3** Tick row checkboxes → **🗑 Delete N rows** → rows disappear and are excluded from Generate /
  Create XBRL. [V]
- **O4 Create XBRL** on the open table → instance emits proper `<xbrldi:typedMember
  dimension="eba_dim:INC"><eba_typ:CC>1</eba_typ:CC></xbrldi:typedMember>`. [A]
- **O5 Validate** that file (see §8) → **0 dim-invalid, 0 value errors** for the typed open rows. [A]

---

## 7. Upload instance → populate / edit / save (Section C)
Tables tab → **⬆ Upload data (.xbrl)** with a sample for the selected package.
- **U1** Upload **PRAMEM** sample → opens its reported tables (FS700/FS701) in Amend, **pre-filled**
  with the real values (FS701.00.01.01 → 19 matched cells; values like 9072000). [A]
- **U2** Upload **RFB002** sample (open-axis) → open tables expand from the data: **SR802.01.02.01**
  → 2 rows (INC=1,2); **SR802.02.02.01** → 4 rows (INC×GCC); **SR99.01.01.01** → 16 rows. [A]
- **U3** Edit a populated cell → **💾 Save edited instance** → downloads the file with only your
  changed values, **original entity/period/contexts/units preserved** (verified: mi170 9072000→
  999999, 72 contexts + scheme intact; open-table fact 2558→7777777, 84 typedMembers preserved). [A]
- **U4** A mismatched instance (different taxonomy) → matches nothing (counts reveal it); no crash. [A]
- **U5** Uploading a new instance replaces the previous one; clearing it returns to blank grids. [A]

## 8. Validate tab (async Arelle)
- **VL1** Validate tab → **File** dropdown lists all built (generated) + uploaded instances;
  `hasSourceZip` true for banking. [A]
- **VL2** Pick a built **pra_mem** instance → **⚖ Validate** → "building…" spinner → **ready**:
  ✓ structurally valid, **2 business-rule assertions not satisfied** (b1_m, b2_m). [A]
- **VL3** Pick a built **lvr002** instance → validate → **48 dim-invalid facts pruned**, ✓ valid
  after prune, ~15–22 assertions; **⤓ cleaned file** download offered. [A]
- **VL4** Switch tabs while validating, come back → progress/result still shown (job is server-side,
  persistent). [V]
- **VL5** A big module (pra001) → validate shows "building…" for several minutes, **never a 500**;
  status surfaces errors as a message. [A]
- **VL6** Assertions list + datatype/value-error details are expandable. [V]

---

## 9. Cross-cutting / regression
- **X1** Switching packages (banking ↔ insurance) re-keys all tabs; no stale data. [V]
- **X2** `tsc --noEmit` + `vite build` clean. [B]
- **X3** Backend restart with no `--reload`; port 8201 frees cleanly (kill stale listener if
  needed). [A]
- **X4** Insurance package: Ingest + Dictionary + Tables work (taxonomy-agnostic); Generate/Validate
  exercised on banking only. [A]
- **X5** Encoding: `PYTHONIOENCODING=utf-8` set; labels with `·`/accents render correctly. [A]

## 9b. 2026-06-22 features (Phase A real members · Phase B solver · union/origin · locking)
- **PA1** Open **C06.02.01.01** → **+ Add row** → the open **IGS** dimension shows a **member
  dropdown** (real members, e.g. "x15 …"), not an integer box; **LGS** (typed) stays a free input.
  Added rows default to real members. [A]/[V]
- **PA2** Build that table with IGS=`eba_BT:x15` → Create XBRL → Validate → **0 dim-invalid** for
  those rows (the old synthesised int was dim-invalid). [A]  *(Other BT members may be table-invalid
  until per-table hypercube extraction lands.)*
- **PB1 Solver:** Validate a built instance with unsatisfied assertions (e.g. a generated **pra_mem**
  → b1_m/b2_m) → **⚙ Solve business rules** → progress → **before 2 → after 0**, N iterations, and a
  **download** of `…​.solved.xbrl`. [A]
- **PB2** The solved file appears in the Validate **File** dropdown as source `solved`; re-validate →
  ✓ assertions satisfied. [A]
- **UO1 Union + origin:** select table **A** (Edit) → upload an instance reporting **B/C/D** → Amend
  shows **A,B,C,D**; A is **amber** (user-selected, blank/authorable), B/C/D **green** (populated). [V]
- **UO2** Re-select an uploaded (green) table via **Edit** → it flips to **amber** and goes blank
  (author fresh); ✕ on a chip removes that table. [V]
- **LK1 Locking:** row/column header **🔓/🔒** toggles; select a rectangle → toolbar **🔒 Lock cells**.
  Locked = **yellow** + read-only; **Generate Data skips** them (status: "N locked, skipped"); Create
  XBRL still exports them. [V]
- **SP1 Dropdown speed:** on launch the **Loaded packages** dropdown appears effectively instantly
  (was ~3 s); `GET /api/packages` ~25 ms server-side after the first call. [A]

## 10. Known limitations (expected behaviour, NOT bugs)
- Validate **reports** unsatisfied business rules; the **⚙ Solve** button (Phase B) drives them to
  satisfaction (additivity/equality/inequality/sign/format/existence). Cross-table aggregation tails
  may need another pass; solve is banking-only (rule-URL→file mapping); each iteration is a full Arelle run.
- First builds are slow & one-time-cached: model ~60–110 s; tables index ~30 s; pra001 rules ~2 min;
  Arelle validate of pra001 ~minutes.
- **Explicit** open dimensions: added rows now offer **real domain members** (dropdown). The global
  domain can be broader than a given table's hypercube allows, so a chosen member may still be
  dim-invalid for that table (pruned at Validate) until per-table hypercube extraction lands. Typed
  open dims take a free value.
- Editing an **empty** cell of an uploaded instance (no existing fact) isn't written back — needs a
  new context; use Create XBRL for a fresh instance.
- Generate/Create XBRL exercised on **banking 4.0.0**; the builder is package-generic but untested on
  other packages.
- Create XBRL reporting context is a **placeholder** (LEI/scheme/date); a per-instance form is a
  follow-up.

---

## Quick API smoke (no UI) — for fast regression
```bash
P=50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181
curl -s localhost:8201/api/health
curl -s "localhost:8201/api/package/$P/model/status"            # ready, counts
curl -s "localhost:8201/api/package/$P/tables?framework=leverage"   # nTables 13
curl -s "localhost:8201/api/package/$P/model?section=metrics&entryPoint=pra_mem&pageSize=1"  # total 12
curl -s "localhost:8201/api/package/$P/scope" | head -c 300       # 10 frameworks
curl -s "localhost:8201/api/package/$P/scope/resolve?table=C01.00.01.01"  # pra001
curl -s "localhost:8201/api/package/$P/rules?module=pra_mem"      # 2 rules
# upload + validate: see §7/§8 (multipart POST /instance, POST /validate)
```
