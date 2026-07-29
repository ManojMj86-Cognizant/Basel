import { useEffect, useRef, useState } from "react";
import {
  Datapoint, EnumValue, GenerateResult, generateFileUrl, generateInstance,
  getGenerateValidStatus, getInstanceGrid, getInstanceInfo, getTableGrid, GridPosition,
  InstanceInfo, saveInstance, startGenerateValid, TableGrid,
} from "./api";

const DEFAULT_COL_W = 130;
const DEFAULT_HEAD_W = 220;

type OpenAxis = TableGrid["openAxes"][number];

const NUMERIC = /^-?\d+(\.\d+)?$/;
const INTEGER = /^-?\d+$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function validateCell(datatype: string | null | undefined, v: string, enumQnames?: Set<string>): string | null {
  if (!v) return null;
  switch (datatype) {
    case "MONETARY": case "DECIMAL": case "PERCENTAGE":
      return NUMERIC.test(v) ? null : "expects a number (e.g. 1234.56)";
    case "INTEGER":
      return INTEGER.test(v) ? null : "expects a whole number";
    case "DATE":
      return ISO_DATE.test(v) ? null : "expects a date (YYYY-MM-DD)";
    case "BOOLEAN":
      return v === "true" || v === "false" ? null : "expects true or false";
    case "ENUMERATION":
      if (enumQnames && enumQnames.size > 0) return enumQnames.has(v) ? null : "not one of the allowed values";
      return null;
    default: return null;
  }
}

// datatype-safe random value for one cell
function randValue(dt: string | null | undefined, ev?: EnumValue[]): string {
  switch (dt) {
    case "MONETARY": return String((1 + Math.floor(Math.random() * 9999)) * 1000);
    case "DECIMAL": return (Math.random() * 9999).toFixed(2);
    case "PERCENTAGE": return Math.random().toFixed(4);
    case "INTEGER": return String(Math.floor(Math.random() * 100000));
    case "BOOLEAN": return Math.random() < 0.5 ? "true" : "false";
    case "DATE": {
      const y = 2018 + Math.floor(Math.random() * 9);
      const m = 1 + Math.floor(Math.random() * 12);
      const d = 1 + Math.floor(Math.random() * 28);
      return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    }
    case "ENUMERATION": return ev && ev.length ? ev[Math.floor(Math.random() * ev.length)].qname : "";
    default: return Math.random().toString(36).slice(2, 10).toUpperCase();
  }
}

const zLayers = (g: TableGrid) => (g.zPositions.length > 1 ? g.zPositions.length : 1);
const zPosOf = (g: TableGrid, z: number) => g.zPositions[g.zPositions.length > 1 ? z : 0];

type GenState = { busy: boolean; phase?: string; result?: GenerateResult; error?: string };

export default function Amend({ pkgId, codes, origins, preset, onCodesChange }:
  { pkgId: string; codes: string[]; origins?: Record<string, "upload" | "select">;
    preset?: Record<string, Record<string, string>>; onCodesChange: (codes: string[]) => void }) {
  const [active, setActive] = useState(codes[0] ?? "");
  // lifted so every selected table's values persist (and are exportable), not just the active tab
  const grids = useRef<Record<string, TableGrid>>({});
  const [values, setValues] = useState<Record<string, Record<string, string>>>({});
  const [gen, setGen] = useState<GenState>({ busy: false });
  const [instance, setInstance] = useState<InstanceInfo | null>(null);
  // instance-expanded grids (open axes filled from the data) keyed by table code
  const [instGrids, setInstGrids] = useState<Record<string, TableGrid>>({});
  // tables whose instance values are still loading (for a per-chip "loading" hint)
  const [loadingCodes, setLoadingCodes] = useState<Set<string>>(new Set());
  // tables the user has LOCKED — Generate Data skips these (their values are preserved)
  const [locked, setLocked] = useState<Set<string>>(new Set());
  const toggleLock = (c: string) =>
    setLocked((s) => { const n = new Set(s); n.has(c) ? n.delete(c) : n.add(c); return n; });
  // a table's origin: explicit "select" (author fresh) / "upload" (populate from the instance);
  // fall back to instance membership when no explicit origin was recorded.
  const originOf = (c: string): "upload" | "select" =>
    origins?.[c] ?? (instance?.tables?.includes(c) ? "upload" : "select");
  const fromUpload = (c: string) => originOf(c) === "upload";

  // remove a table from the working set (view + export only — uploaded data on disk is untouched)
  const removeCode = (c: string) => {
    const next = codes.filter((x) => x !== c);
    onCodesChange(next);
    if (active === c) setActive(next[0] ?? "");
  };
  // user-added open-axis rows/cols, lifted to the parent (keyed by table code) so Generate Data
  // and Create XBRL include them — and across ALL Z layers — not just the base grid.
  const [extraRows, setExtraRows] = useState<Record<string, GridPosition[]>>({});
  const [extraCols, setExtraCols] = useState<Record<string, GridPosition[]>>({});
  // rows hidden by "delete row" (keyed by table → set of *display* row indices)
  const [deletedRows, setDeletedRows] = useState<Record<string, Set<number>>>({});
  // granular locks (keyed by table). A locked row/col/cell is shown yellow and SKIPPED by
  // Generate Data (its value is preserved); Create XBRL still exports it. Rows/cols lock across
  // all Z layers; cells lock per `z:r:c`.
  const [lockedRows, setLockedRows] = useState<Record<string, Set<number>>>({});
  const [lockedCols, setLockedCols] = useState<Record<string, Set<number>>>({});
  const [lockedCells, setLockedCells] = useState<Record<string, Set<string>>>({});
  const toggleRowLock = (code: string, r: number) =>
    setLockedRows((m) => { const n = new Set(m[code] ?? []); n.has(r) ? n.delete(r) : n.add(r); return { ...m, [code]: n }; });
  const toggleColLock = (code: string, c: number) =>
    setLockedCols((m) => { const n = new Set(m[code] ?? []); n.has(c) ? n.delete(c) : n.add(c); return { ...m, [code]: n }; });
  const setCellsLock = (code: string, keys: string[], lock: boolean) =>
    setLockedCells((m) => {
      const n = new Set(m[code] ?? []);
      keys.forEach((k) => (lock ? n.add(k) : n.delete(k)));
      return { ...m, [code]: n };
    });
  const cellLocked = (code: string, z: number, r: number, c: number) =>
    (lockedCells[code]?.has(`${z}:${r}:${c}`) ?? false) ||
    (lockedRows[code]?.has(r) ?? false) || (lockedCols[code]?.has(c) ?? false);
  // per-table cell -> fact index, and the original instance value (to compute edits on save)
  const fiMap = useRef<Record<string, Record<string, number>>>({});
  const orig = useRef<Record<string, Record<string, string>>>({});
  // filename of the instance whose data is currently seeded — to detect a *new* upload and
  // reset stale scratch state (added rows/edits) so the instance grid is the source of truth.
  const loadedFile = useRef<string | null>(null);
  // codes whose cells were seeded from the instance — so if a user later RE-selects one via
  // Edit (origin → "select", i.e. author fresh) we clear its stale instance data exactly once.
  const seeded = useRef<Set<string>>(new Set());

  const openAxesOn = (code: string, axis: "x" | "y"): OpenAxis[] =>
    (grids.current[code]?.openAxes ?? []).filter((o) => o.axis === axis && !!o.dimension);
  const dimLabel = (dims: Record<string, string>, fallback: string) => {
    const parts = Object.entries(dims).map(([d, v]) => `${d.split(":").pop()}=${v ? v.split(":").pop() : "?"}`);
    return parts.length ? parts.join(" · ") : fallback;
  };
  // a new open-axis row/col carries an editable value per open dimension. For an EXPLICIT open
  // dimension we default to a real domain member (cycling) so the row is dimensionally valid;
  // a typed dimension takes a synthesised integer (its typed domain accepts free values).
  const newPos = (axes: OpenAxis[], n: number, fallback: string): GridPosition => {
    const dims: Record<string, string> = {};
    axes.forEach((o) => {
      const d = o.dimension as string;
      dims[d] = (!o.typed && o.members && o.members.length)
        ? o.members[(n - 1) % o.members.length].qname
        : String(n);
    });
    return { label: dimLabel(dims, fallback), concept: null, dims };
  };
  const addRow = (code: string) =>
    setExtraRows((m) => {
      const cur = m[code] ?? [];
      return { ...m, [code]: [...cur, newPos(openAxesOn(code, "y"), cur.length + 1, `new row ${cur.length + 1}`)] };
    });
  const addCol = (code: string) =>
    setExtraCols((m) => {
      const cur = m[code] ?? [];
      return { ...m, [code]: [...cur, newPos(openAxesOn(code, "x"), cur.length + 1, `new col ${cur.length + 1}`)] };
    });
  // edit an added row's open-dimension value
  const setRowDim = (code: string, extraIdx: number, dim: string, value: string) =>
    setExtraRows((m) => {
      const cur = [...(m[code] ?? [])];
      if (!cur[extraIdx]) return m;
      const dims = { ...cur[extraIdx].dims, [dim]: value };
      cur[extraIdx] = { ...cur[extraIdx], dims, label: dimLabel(dims, `new row ${extraIdx + 1}`) };
      return { ...m, [code]: cur };
    });
  const deleteRows = (code: string, indices: number[]) =>
    setDeletedRows((m) => ({ ...m, [code]: new Set([...(m[code] ?? []), ...indices]) }));
  const rowsFor = (g: TableGrid, code: string) => {
    const r = [...g.rows, ...(extraRows[code] ?? [])];
    return r.length ? r : [{ label: "(row)", concept: null, dims: {} } as GridPosition];
  };
  const colsFor = (g: TableGrid, code: string) => {
    const c = [...g.columns, ...(extraCols[code] ?? [])];
    return c.length ? c : [{ label: "Value", concept: null, dims: {} } as GridPosition];
  };
  const isDeleted = (code: string, i: number) => deletedRows[code]?.has(i) ?? false;

  useEffect(() => {
    if (!codes.includes(active)) setActive(codes[0] ?? "");
  }, [codes, active]);

  // seed pre-solved values from "Generate Full Valid Data" (these tables are author/"select" origin)
  useEffect(() => {
    if (!preset) return;
    setValues((m) => {
      const n = { ...m };
      for (const [code, cells] of Object.entries(preset)) n[code] = { ...(n[code] ?? {}), ...cells };
      return n;
    });
  }, [preset]);

  // if an instance is uploaded, pre-fill the grids with its values — using the instance-EXPANDED
  // grid so OPEN-axis tables get their rows/cols from the data (and remember fi + originals).
  useEffect(() => {
    let cancelled = false;
    fiMap.current = {}; orig.current = {};
    getInstanceInfo(pkgId).then((info) => {
      if (cancelled) return;
      if (!info) {
        // instance cleared: drop back to scratch mode with clean grids
        if (loadedFile.current !== null) {
          loadedFile.current = null; seeded.current.clear();
          setExtraRows({}); setExtraCols({}); setDeletedRows({}); setValues({}); setInstGrids({});
        }
        setInstance(null); setLoadingCodes(new Set());
        return;
      }
      setInstance(info);
      // A *newly uploaded* instance is the source of truth: clear any stale scratch state
      // (added rows / prior generate edits) so its expanded grid + values aren't corrupted.
      const isNew = loadedFile.current !== info.filename;
      if (isNew) {
        loadedFile.current = info.filename; seeded.current.clear();
        setExtraRows({}); setExtraCols({}); setDeletedRows({}); setValues({}); setInstGrids({});
      }
      // only tables whose origin is "upload" are populated from the instance; user-selected
      // ("select") tables stay fresh/authorable even while an instance is loaded.
      const uploadCodes = codes.filter(
        (c) => (origins?.[c] ?? (info.tables?.includes(c) ? "upload" : "select")) === "upload");
      // a table previously seeded from the instance but now RE-selected as "select" (author
      // fresh) gets its stale instance grid/values cleared once, so it starts blank.
      const flipped = codes.filter((c) => seeded.current.has(c) && !uploadCodes.includes(c));
      if (flipped.length) {
        flipped.forEach((c) => { seeded.current.delete(c); delete grids.current[c]; delete fiMap.current[c]; delete orig.current[c]; });
        setInstGrids((m) => { const n = { ...m }; flipped.forEach((c) => delete n[c]); return n; });
        setValues((m) => { const n = { ...m }; flipped.forEach((c) => delete n[c]); return n; });
      }
      setLoadingCodes(new Set(uploadCodes));
      // fetch each upload table's instance-expanded grid IN PARALLEL and render as it arrives
      // (was a sequential await-loop — slow to populate when several tables were uploaded).
      const done = (code: string) =>
        setLoadingCodes((s) => { const n = new Set(s); n.delete(code); return n; });
      uploadCodes.forEach((code) => {
        getInstanceGrid(pkgId, code).then((ig) => {
          if (cancelled) return;
          const { values, nMatched, ...grid } = ig;
          void nMatched;
          grids.current[code] = grid as TableGrid;
          const vmap: Record<string, string> = {}, fm: Record<string, number> = {};
          for (const [k, cv] of Object.entries(values)) { vmap[k] = cv.value; fm[k] = cv.fi; }
          fiMap.current[code] = fm; orig.current[code] = { ...vmap }; seeded.current.add(code);
          setInstGrids((m) => ({ ...m, [code]: grid as TableGrid }));
          // new upload -> instance values are authoritative; otherwise keep edits made since load
          setValues((m) => ({ ...m, [code]: isNew ? vmap : { ...vmap, ...(m[code] ?? {}) } }));
          done(code);
        }).catch(() => {
          if (cancelled) return;
          // table not in this instance (or index busy): fall back to the closed grid so the
          // table still renders as a blank editable grid — and never gets stuck "loading".
          getTableGrid(pkgId, code)
            .then((g) => { if (!cancelled) { grids.current[code] = g; setInstGrids((m) => ({ ...m, [code]: g })); } })
            .catch(() => {})
            .finally(() => done(code));
        });
      });
    }).catch(() => { setInstance(null); setLoadingCodes(new Set()); });
    return () => { cancelled = true; };
  }, [pkgId, codes, origins]);

  async function saveEdited() {
    const edits: Record<string, string> = {};
    for (const code of codes) {
      const fm = fiMap.current[code] || {}, og = orig.current[code] || {}, cur = values[code] || {};
      for (const [k, fi] of Object.entries(fm)) {
        const v = cur[k] ?? "";
        if (v !== (og[k] ?? "")) edits[String(fi)] = v;
      }
    }
    if (Object.keys(edits).length === 0) { setGen({ busy: false, phase: "No changes to save." }); return; }
    setGen({ busy: true, phase: "Writing edits back into the uploaded instance…" });
    try {
      await saveInstance(pkgId, edits);
      setGen({ busy: false, phase: `Saved ${Object.keys(edits).length} edited value(s) into ${instance?.filename} — downloaded.` });
    } catch (e) {
      setGen({ busy: false, error: (e as Error).message });
    }
  }

  const tableValues = (code: string) => values[code] ?? {};
  const setCell = (code: string, key: string, v: string) =>
    setValues((m) => ({ ...m, [code]: { ...(m[code] ?? {}), [key]: v } }));
  const setCells = (code: string, updates: Record<string, string>) =>
    setValues((m) => ({ ...m, [code]: { ...(m[code] ?? {}), ...updates } }));

  async function ensureGrid(code: string): Promise<TableGrid> {
    if (grids.current[code]) return grids.current[code];
    const g = await getTableGrid(pkgId, code);
    grids.current[code] = g;
    return g;
  }

  // fill every datapoint cell of every selected table with a datatype-valid random value
  async function generateData() {
    const targets = codes.filter((c) => !locked.has(c));
    if (targets.length === 0) {
      setGen({ busy: false, phase: "All tables are locked — unlock a table (🔓) to generate values." });
      return;
    }
    setGen({ busy: true, phase: `Generating values for ${targets.length} unlocked table(s)…` });
    try {
      const next: Record<string, Record<string, string>> = {};
      for (const code of targets) {
        const g = await ensureGrid(code);
        const cols = colsFor(g, code), rows = rowsFor(g, code);   // base + user-added rows/cols
        const tv: Record<string, string> = { ...(values[code] ?? {}) };  // keep existing edits
        for (let z = 0; z < zLayers(g); z++) {                     // every Z layer
          const zp = zPosOf(g, z);
          for (let i = 0; i < rows.length; i++) {
            if (isDeleted(code, i)) continue;
            for (let j = 0; j < cols.length; j++) {
              if (cellLocked(code, z, i, j)) continue;      // locked cell/row/col -> keep its value
              const concept = rows[i].concept ?? cols[j].concept ?? zp?.concept ?? null;
              if (!concept) continue;
              const dt = rows[i].datatype ?? cols[j].datatype ?? zp?.datatype ?? null;
              const ev = rows[i].enumValues ?? cols[j].enumValues ?? zp?.enumValues;
              tv[`${z}:${i}:${j}`] = randValue(dt, ev);
            }
          }
        }
        next[code] = tv;
      }
      setValues((m) => ({ ...m, ...next }));
      setGen({ busy: false, phase: `Filled random values into ${targets.length} table(s)${locked.size ? ` (${locked.size} locked, skipped)` : ""}. Review/edit, then Create XBRL.` });
    } catch (e) {
      setGen({ busy: false, error: (e as Error).message });
    }
  }

  function buildSelection(): Record<string, Datapoint[]> {
    const sel: Record<string, Datapoint[]> = {};
    for (const code of codes) {
      const g = grids.current[code];
      if (!g) continue;
      const cols = colsFor(g, code), rows = rowsFor(g, code), tv = tableValues(code);
      const dps: Datapoint[] = [];
      for (let z = 0; z < zLayers(g); z++) {
        const zp = zPosOf(g, z);
        for (let i = 0; i < rows.length; i++) {
          if (isDeleted(code, i)) continue;
          for (let j = 0; j < cols.length; j++) {
            const v = tv[`${z}:${i}:${j}`];
            if (!v) continue;
            const concept = rows[i].concept ?? cols[j].concept ?? zp?.concept ?? null;
            if (!concept) continue;
            const dt = rows[i].datatype ?? cols[j].datatype ?? zp?.datatype ?? null;
            const dims = { ...(zp?.dims ?? {}), ...rows[i].dims, ...cols[j].dims };
            dps.push({ concept, dims, datatype: dt, value: v, key: `${z}:${i}:${j}` });
          }
        }
      }
      if (dps.length) sel[code] = dps;
    }
    return sel;
  }

  async function createXbrl() {
    const selection = buildSelection();
    if (Object.keys(selection).length === 0) {
      setGen({ busy: false, error: "No values to export — click Generate Data (or type values) first." });
      return;
    }
    setGen({ busy: true, phase: "Building instance(s)…" });
    try {
      const result = await generateInstance(pkgId, selection);   // build only — no Arelle, instant
      setGen({ busy: false, result });
    } catch (e) {
      setGen({ busy: false, error: (e as Error).message });
    }
  }

  // Build + OFFLINE-solve the rules (no Arelle): writes rule-consistent values back into the grid.
  const gvPoll = useRef<number | null>(null);
  useEffect(() => () => { if (gvPoll.current) window.clearTimeout(gvPoll.current); }, []);
  function pollGenValid() {
    getGenerateValidStatus(pkgId).then((s) => {
      if (s.status === "solving") { gvPoll.current = window.setTimeout(pollGenValid, 2500); return; }
      if (s.status === "ready") {
        const v = s.values ?? {};
        setValues((m) => {
          const n = { ...m };
          for (const [code, cells] of Object.entries(v)) n[code] = { ...(n[code] ?? {}), ...cells };
          return n;
        });
        const nmod = s.modules?.length ?? 0;
        const ncells = Object.values(v).reduce((a, c) => a + Object.keys(c).length, 0);
        setGen({ busy: false, phase: `Offline-solved ${nmod} module(s): ${ncells} rule-consistent values written into the grid. Create XBRL, then Validate (cross-table rules may still need ⚙ Solve).` });
      } else {
        setGen({ busy: false, error: s.error || "Offline solve failed." });
      }
    }).catch((e) => setGen({ busy: false, error: (e as Error).message }));
  }
  async function generateValid() {
    const selection = buildSelection();
    if (Object.keys(selection).length === 0) {
      setGen({ busy: false, error: "Nothing to solve — click Generate Data (or type values) first." });
      return;
    }
    setGen({ busy: true, phase: "Building + solving rules offline (no Arelle)… parsing a large framework's rules can take a few minutes the first time (then cached)." });
    try {
      await startGenerateValid(pkgId, selection);
      pollGenValid();
    } catch (e) {
      setGen({ busy: false, error: (e as Error).message });
    }
  }

  if (codes.length === 0)
    return (
      <div className="dict">
        <div className="hint" style={{ marginTop: 20 }}>
          No tables selected. Go to the <strong>Tables</strong> tab, tick one or more tables,
          and click <strong>Edit</strong>.
        </div>
      </div>
    );

  return (
    <div className="amend">
      <div className="gen-bar">
        <button className="btn primary" disabled={gen.busy} onClick={generateData}>⚄ Generate Data</button>
        <button className="btn primary" disabled={gen.busy} onClick={generateValid} title="Build + solve the rules offline (no Arelle) and write rule-consistent values back into the grid">⚖ Generate valid data</button>
        <button className="btn primary" disabled={gen.busy} onClick={createXbrl}>⤓ Create XBRL</button>
        {instance && (
          <button className="btn primary" disabled={gen.busy} onClick={saveEdited}>💾 Save edited instance</button>
        )}
        <span className="hint">
          {instance
            ? `Pre-filled from ${instance.filename}. Edit cells, then Save edited instance to write your changes back into that file (entity/period/contexts preserved).`
            : `Random datatype-valid values for the ${codes.length} selected table(s); Create XBRL builds one instance per module (instant, no Arelle). Run Arelle from the Validate tab.`}
        </span>
      </div>
      {(gen.busy || gen.phase || gen.error) && (
        <div className={"gen-status" + (gen.error ? " err" : "")}>
          {gen.busy && <span className="spinner" />}{gen.error ? `⚠ ${gen.error}` : gen.phase}
        </div>
      )}
      {gen.result && <GenResultPanel pkgId={pkgId} result={gen.result} />}

      <div className="amend-tabs">
        {codes.map((c) => {
          const locks = locked.has(c);
          return (
          <span key={c} className={"chip-tab" + (c === active ? " active" : "") +
            (fromUpload(c) ? " src-upload" : " src-select") + (locks ? " locked" : "")}>
            <button className="chip-lock" title={locks ? "Locked — Generate Data skips this table" : "Lock to skip on Generate Data"}
              onClick={() => toggleLock(c)}>{locks ? "🔒" : "🔓"}</button>
            <button className="chip-label" onClick={() => setActive(c)}>{c}</button>
            {loadingCodes.has(c) && <span className="chip-loading" title="Loading values…">⏳</span>}
            <button className="chip-close" title="Remove this table" onClick={() => removeCode(c)}>×</button>
          </span>
          );
        })}
      </div>
      <div className="amend-legend hint">
        <span className="legend-swatch src-upload" /> from uploaded XBRL
        <span className="legend-swatch src-select" /> user-selected
        <span>· 🔒 locked tables are skipped by Generate Data</span>
      </div>
      {active && (
        <AmendTable
          key={active}
          pkgId={pkgId}
          code={active}
          presetGrid={fromUpload(active) ? instGrids[active] : undefined}
          instanceMode={fromUpload(active)}
          source={fromUpload(active) ? "upload" : "select"}
          values={tableValues(active)}
          extraRows={extraRows[active] ?? []}
          extraCols={extraCols[active] ?? []}
          deleted={deletedRows[active]}
          lockedRows={lockedRows[active]}
          lockedCols={lockedCols[active]}
          lockedCells={lockedCells[active]}
          onToggleRowLock={(r) => toggleRowLock(active, r)}
          onToggleColLock={(c) => toggleColLock(active, c)}
          onLockCells={(keys, lock) => setCellsLock(active, keys, lock)}
          onAddRow={() => addRow(active)}
          onAddCol={() => addCol(active)}
          onSetRowDim={(extraIdx, dim, v) => setRowDim(active, extraIdx, dim, v)}
          onDeleteRows={(idx) => deleteRows(active, idx)}
          onCell={(k, v) => setCell(active, k, v)}
          onCells={(u) => setCells(active, u)}
          onGrid={(g) => { grids.current[active] = g; }}
        />
      )}
    </div>
  );
}

function GenResultPanel({ pkgId, result }: { pkgId: string; result: GenerateResult }) {
  return (
    <div className="gen-result">
      <div className="row" style={{ gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
        <strong>✓ Built {result.instances.length} instance(s)</strong>
        <span className="dim">entity {result.opts.lei} · {result.opts.date}</span>
        <span className="hint">Download below; run Arelle from the <strong>Validate</strong> tab.</span>
      </div>
      {result.unmapped.length > 0 && (
        <div className="hint">⚠ No module found for: {result.unmapped.join(", ")} (not exported).</div>
      )}
      {result.errors.length > 0 && (
        <div className="error">⚠ {result.errors.map((e) => `${e.module}: ${e.error}`).join("; ")}</div>
      )}
      {result.instances.map((inst) => (
        <div className="inst-card" key={inst.filename}>
          <div className="row" style={{ gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
            <strong>{inst.module}</strong>
            <span className="dim">{inst.framework}</span>
            <span className="count-chip">{inst.facts} facts</span>
            <span className="count-chip">{inst.contexts} contexts</span>
            <a className="btn" href={generateFileUrl(pkgId, inst.filename)} download>⤓ {inst.filename}</a>
          </div>
          <div className="hint">tables: {inst.tables.join(", ")}</div>
        </div>
      ))}
    </div>
  );
}

type Sel = { ar: number; ac: number; fr: number; fc: number };
const norm = (s: Sel) => ({
  r1: Math.min(s.ar, s.fr), r2: Math.max(s.ar, s.fr),
  c1: Math.min(s.ac, s.fc), c2: Math.max(s.ac, s.fc),
});

function AmendTable({ pkgId, code, presetGrid, instanceMode, source, values, extraRows, extraCols, deleted,
                     lockedRows, lockedCols, lockedCells, onToggleRowLock, onToggleColLock, onLockCells,
                     onAddRow, onAddCol, onSetRowDim, onDeleteRows, onCell, onCells, onGrid }: {
  pkgId: string; code: string; presetGrid?: TableGrid; instanceMode?: boolean;
  source?: "upload" | "select"; values: Record<string, string>;
  extraRows: GridPosition[]; extraCols: GridPosition[];
  deleted?: Set<number>;
  lockedRows?: Set<number>; lockedCols?: Set<number>; lockedCells?: Set<string>;
  onToggleRowLock: (r: number) => void; onToggleColLock: (c: number) => void;
  onLockCells: (keys: string[], lock: boolean) => void;
  onAddRow: () => void; onAddCol: () => void;
  onSetRowDim: (extraIdx: number, dim: string, v: string) => void;
  onDeleteRows: (indices: number[]) => void;
  onCell: (key: string, v: string) => void;
  onCells: (updates: Record<string, string>) => void;
  onGrid: (g: TableGrid) => void;
}) {
  const [grid, setGrid] = useState<TableGrid | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zIdx, setZIdx] = useState(0);
  const [full, setFull] = useState(false);
  const [picked, setPicked] = useState<Set<number>>(new Set());   // row selection (for delete)
  const [colW, setColW] = useState<Record<number, number>>({});
  const [headW, setHeadW] = useState(DEFAULT_HEAD_W);
  const [rowH, setRowH] = useState<Record<number, number>>({});
  const [headerH, setHeaderH] = useState<number | null>(null);
  const [sel, setSel] = useState<Sel | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [showTypes, setShowTypes] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(null); setZIdx(0);
    setColW({}); setHeadW(DEFAULT_HEAD_W); setRowH({}); setHeaderH(null); setSel(null);
    if (presetGrid) { setGrid(presetGrid); return; }   // instance-expanded grid from the parent
    setGrid(null);
    if (instanceMode) return;   // an instance is loaded: wait for its expanded grid (parent supplies it)
    getTableGrid(pkgId, code)
      .then((g) => { if (!cancelled) { setGrid(g); onGrid(g); } })
      .catch((e) => { if (!cancelled) setError((e as Error).message); });
    return () => { cancelled = true; };
  }, [pkgId, code, presetGrid, instanceMode]);

  useEffect(() => {
    if (!selecting) return;
    const up = () => setSelecting(false);
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, [selecting]);

  if (error) return <div className="error">⚠ {error === "building" ? "Table index still building…" : error}</div>;
  if (!grid) return <div className="hint" style={{ marginTop: 16 }}>Loading {code}…</div>;

  const openX = grid.openAxes.some((o) => o.axis === "x");
  const openY = grid.openAxes.some((o) => o.axis === "y");
  const openRowAxes = grid.openAxes.filter((o) => o.axis === "y" && o.dimension);
  const baseRowCount = grid.rows.length;            // rows at/after this index are user-added

  let cols: GridPosition[] = [...grid.columns, ...extraCols];
  let rows: GridPosition[] = [...grid.rows, ...extraRows];
  if (cols.length === 0) cols = [{ label: "Value", concept: null, dims: {} }];
  if (rows.length === 0) rows = [{ label: "(row)", concept: null, dims: {} }];

  const togglePick = (i: number) =>
    setPicked((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });
  const delPicked = () => { onDeleteRows([...picked]); setPicked(new Set()); };

  const hasZ = grid.zPositions.length > 1;
  const z = hasZ ? zIdx : 0;
  const colHasType = cols.some((c) => c.datatype);
  const rowHasType = rows.some((r) => r.datatype);

  const zPos = grid.zPositions[z];
  const meta = (p?: GridPosition) =>
    p ? { dt: p.datatype ?? null, ev: p.enumValues, set: p.enumValues ? new Set(p.enumValues.map((e) => e.qname)) : undefined } : null;
  const rowMeta = rows.map(meta);
  const colMeta = cols.map(meta);
  const zMeta = meta(zPos);
  const cellMeta = (i: number, j: number) => {
    const m = (rowMeta[i]?.dt && rowMeta[i]) || (colMeta[j]?.dt && colMeta[j]) || (zMeta?.dt && zMeta) || null;
    return { dt: m?.dt ?? null, ev: m?.ev as EnumValue[] | undefined, set: m?.set as Set<string> | undefined };
  };


  const key = (r: number, c: number) => `${z}:${r}:${c}`;
  const inSel = (r: number, c: number) => {
    if (!sel) return false;
    const n = norm(sel);
    return r >= n.r1 && r <= n.r2 && c >= n.c1 && c <= n.c2;
  };
  const onCellDown = (r: number, c: number, e: React.MouseEvent) => {
    if (e.shiftKey && sel) setSel({ ...sel, fr: r, fc: c });
    else setSel({ ar: r, ac: c, fr: r, fc: c });
    setSelecting(true);
  };
  const onCellEnter = (r: number, c: number) => {
    if (selecting) setSel((s) => (s ? { ...s, fr: r, fc: c } : s));
  };

  // a cell is locked if its own (z,r,c) is locked, or its whole row/column is locked
  const isLocked = (r: number, c: number) =>
    (lockedCells?.has(key(r, c)) ?? false) || (lockedRows?.has(r) ?? false) || (lockedCols?.has(c) ?? false);
  const lockSelection = (lock: boolean) => {
    if (!sel) return;
    const n = norm(sel);
    const keys: string[] = [];
    for (let r = n.r1; r <= n.r2; r++) for (let c = n.c1; c <= n.c2; c++) keys.push(`${z}:${r}:${c}`);
    onLockCells(keys, lock);
  };

  const onPaste = (e: React.ClipboardEvent) => {
    const text = e.clipboardData.getData("text");
    if (!text) return;
    const matrix = text.replace(/\r\n?/g, "\n").replace(/\n$/, "").split("\n").map((ln) => ln.split("\t"));
    const start = sel ? norm(sel) : { r1: 0, c1: 0 };
    e.preventDefault();
    const updates: Record<string, string> = {};
    matrix.forEach((line, dr) =>
      line.forEach((val, dc) => {
        const r = start.r1 + dr, c = start.c1 + dc;
        if (r < rows.length && c < cols.length) updates[`${z}:${r}:${c}`] = val;
      }));
    onCells(updates);
    if (matrix.length)
      setSel({ ar: start.r1, ac: start.c1, fr: Math.min(rows.length - 1, start.r1 + matrix.length - 1),
               fc: Math.min(cols.length - 1, start.c1 + (matrix[0]?.length ?? 1) - 1) });
  };

  const dragResize = (axis: "x" | "y", start: number, cur: number, apply: (n: number) => void) => {
    const min = axis === "x" ? 48 : 22;
    const move = (ev: MouseEvent) => apply(Math.max(min, cur + (axis === "x" ? ev.clientX : ev.clientY) - start));
    const up = () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      document.body.style.userSelect = "";
    };
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  };
  const startColResize = (j: number, e: React.MouseEvent) => { e.preventDefault(); e.stopPropagation(); dragResize("x", e.clientX, colW[j] ?? DEFAULT_COL_W, (w) => setColW((m) => ({ ...m, [j]: w }))); };
  const startHeadResize = (e: React.MouseEvent) => { e.preventDefault(); e.stopPropagation(); dragResize("x", e.clientX, headW, setHeadW); };
  const startRowResize = (i: number, e: React.MouseEvent) => { e.preventDefault(); e.stopPropagation(); dragResize("y", e.clientY, rowH[i] ?? 34, (h) => setRowH((m) => ({ ...m, [i]: h }))); };
  const startHeaderHResize = (e: React.MouseEvent) => { e.preventDefault(); e.stopPropagation(); dragResize("y", e.clientY, headerH ?? 52, setHeaderH); };

  const totalW = headW + cols.reduce((s, _, j) => s + (colW[j] ?? DEFAULT_COL_W), 0);
  const headInner = headerH ? { maxHeight: headerH, overflow: "hidden" as const } : undefined;

  return (
    <div className={"amend-table" + (full ? " full" : "")}>
      <div className="row" style={{ gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>{code}</h2>
        <span className="dim">{grid.framework}</span>
        {source && <span className={"tag " + (source === "upload" ? "src-upload" : "src-select")}>
          {source === "upload" ? "from uploaded XBRL" : "user-selected"}</span>}
        <span className="count-chip">{rows.length}×{cols.length} grid</span>
        {grid.openAxes.length > 0 && <span className="tag warn">open axis</span>}
      </div>

      <div className="grid-toolbar">
        <button className="btn" onClick={() => setFull((f) => !f)}>{full ? "⤢ Exit full screen" : "⛶ Full screen"}</button>
        {openY && <button className="btn" onClick={onAddRow}>+ Add row</button>}
        {openX && <button className="btn" onClick={onAddCol}>+ Add column</button>}
        {picked.size > 0 && <button className="btn danger" onClick={delPicked}>🗑 Delete {picked.size} row{picked.size > 1 ? "s" : ""}</button>}
        {sel && <button className="btn" onClick={() => lockSelection(true)}>🔒 Lock cells</button>}
        {sel && <button className="btn" onClick={() => lockSelection(false)}>🔓 Unlock cells</button>}
        {(colHasType || rowHasType) && (
          <button className={"btn" + (showTypes ? " on" : "")} onClick={() => setShowTypes((s) => !s)}>
            {showTypes ? "Hide datatypes" : "Show datatypes"}
          </button>
        )}
        <span className="hint">Drag a header edge to resize. Select cells (click-drag), then 🔒 Lock; locked (yellow) cells are skipped by Generate. Paste from Excel (Ctrl+V).</span>
      </div>

      {hasZ && (
        <div className="z-select">
          <label>Z&nbsp;axis (sheet)</label>
          <select value={zIdx} onChange={(e) => { setZIdx(Number(e.target.value)); setSel(null); }}>
            {grid.zPositions.map((zp, i) => (
              <option key={i} value={i}>{`${i + 1}/${grid.zPositions.length} — ${zp.label}`}</option>
            ))}
          </select>
        </div>
      )}
      {grid.zPositions.length >= 1 && (
        <div className="z-current"><span className="dim">Sheet:</span> {grid.zPositions[hasZ ? zIdx : 0]?.label}</div>
      )}

      <div className="hint" style={{ margin: "8px 0" }}>
        Cells are restricted by datatype (dropdowns for enumerations/booleans, date pickers, numeric checks);
        off-type values are outlined red.{" "}Showing all {rows.length} rows.
      </div>

      <div className="grid-scroll" onPaste={onPaste}>
        <table className={"amend-grid" + (selecting ? " selecting" : "")} style={{ tableLayout: "fixed", width: totalW }}>
          <colgroup>
            <col style={{ width: headW }} />
            {cols.map((_, j) => <col key={j} style={{ width: colW[j] ?? DEFAULT_COL_W }} />)}
          </colgroup>
          <thead>
            <tr>
              <th className="corner">
                <span className="col-resizer" onMouseDown={startHeadResize} title="Drag to resize row-label width" />
                <span className="row-resizer" onMouseDown={startHeaderHResize} title="Drag to resize header height" />
              </th>
              {cols.map((c, j) => (
                <th key={j} title={c.label} className={lockedCols?.has(j) ? "col-locked" : undefined}>
                  <button className="hdr-lock" title={lockedCols?.has(j) ? "Unlock column" : "Lock column"}
                    onClick={() => onToggleColLock(j)}>{lockedCols?.has(j) ? "🔒" : "🔓"}</button>
                  <div className="th-inner" style={headInner}>
                    {c.label}
                    {showTypes && c.datatype && <span className="dtype">{c.datatype}</span>}
                  </div>
                  <span className="col-resizer" onMouseDown={(e) => startColResize(j, e)} title="Drag to resize column" />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              if (deleted?.has(i)) return null;                  // row deleted by the user
              const added = i >= baseRowCount && openRowAxes.length > 0;
              return (
              <tr key={i} style={rowH[i] ? { height: rowH[i] } : undefined}>
                <th className={"rowhead" + (picked.has(i) ? " picked" : "") + (lockedRows?.has(i) ? " row-locked" : "")} title={r.label}>
                  <div className="rowhead-inner" style={rowH[i] ? { maxHeight: rowH[i] - 4, overflow: "hidden" } : undefined}>
                    <input type="checkbox" className="row-pick" checked={picked.has(i)}
                      onChange={() => togglePick(i)} title="Select row to delete" />
                    <button className="hdr-lock" title={lockedRows?.has(i) ? "Unlock row" : "Lock row"}
                      onClick={() => onToggleRowLock(i)}>{lockedRows?.has(i) ? "🔒" : "🔓"}</button>
                    {added ? (
                      <span className="open-dim-edit">
                        {openRowAxes.map((o) => {
                          const d = o.dimension as string;
                          return (
                          <label key={d}>{d.split(":").pop()}=
                            {!o.typed && o.members && o.members.length ? (
                              <select className="open-dim-input" value={r.dims[d] ?? ""}
                                onChange={(e) => onSetRowDim(i - baseRowCount, d, e.target.value)}>
                                <option value=""></option>
                                {o.members.map((m) => (
                                  <option key={m.qname} value={m.qname}>{m.label || m.qname.split(":").pop()}</option>
                                ))}
                              </select>
                            ) : (
                              <input className="open-dim-input" value={r.dims[d] ?? ""}
                                onChange={(e) => onSetRowDim(i - baseRowCount, d, e.target.value)} />
                            )}
                          </label>
                          );
                        })}
                      </span>
                    ) : (<>{r.label}{showTypes && r.datatype && <span className="dtype">{r.datatype}</span>}</>)}
                  </div>
                  <span className="row-resizer" onMouseDown={(e) => startRowResize(i, e)} title="Drag to resize row height" />
                </th>
                {cols.map((_, j) => {
                  const val = values[key(i, j)] ?? "";
                  const { dt, ev, set } = cellMeta(i, j);
                  const bad = validateCell(dt, val, set);
                  const locked = isLocked(i, j);
                  const cls = "cell-input" + (bad ? " cell-bad" : "");
                  let widget;
                  if (dt === "ENUMERATION" && ev && ev.length) {
                    widget = (
                      <select className={cls} title={bad ?? undefined} value={val} disabled={locked} onChange={(e) => onCell(key(i, j), e.target.value)}>
                        <option value=""></option>
                        {ev.map((o) => <option key={o.qname} value={o.qname}>{o.label}</option>)}
                        {val && !set?.has(val) && <option value={val}>{`⚠ ${val}`}</option>}
                      </select>
                    );
                  } else if (dt === "BOOLEAN") {
                    widget = (
                      <select className={cls} title={bad ?? undefined} value={val} disabled={locked} onChange={(e) => onCell(key(i, j), e.target.value)}>
                        <option value=""></option>
                        <option value="true">true</option>
                        <option value="false">false</option>
                      </select>
                    );
                  } else {
                    widget = (
                      <input className={cls} title={bad ?? undefined}
                        type={dt === "DATE" ? "date" : "text"} readOnly={locked}
                        value={val} onChange={(e) => onCell(key(i, j), e.target.value)} />
                    );
                  }
                  return (
                    <td key={j} className={[inSel(i, j) ? "cell-sel" : "", locked ? "cell-locked" : ""].filter(Boolean).join(" ") || undefined}
                      onMouseDown={(e) => onCellDown(i, j, e)} onMouseEnter={() => onCellEnter(i, j)}>
                      {widget}
                    </td>
                  );
                })}
              </tr>
            );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
