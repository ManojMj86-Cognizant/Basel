import { useEffect, useRef, useState } from "react";
import {
  buildTables,
  DatapointRow,
  FrameworkGroup,
  getGenerateValidStatus,
  getTableDatapoints,
  getTables,
  getTablesStatus,
  startGenerateValidModule,
  TableDatapoints,
  TablesIndex,
  TablesStatus,
  uploadInstance,
} from "./api";
import ScopePicker, { Scope } from "./ScopePicker";

const PAGE_SIZE = 50;

export default function Tables({ pkgId, pkgName, onEdit, onViewRules, onInstanceLoaded, onFullValid }: {
  pkgId: string; pkgName?: string; onEdit: (codes: string[]) => void;
  onViewRules: (code: string) => void;
  onInstanceLoaded: (tables: string[]) => void;
  onFullValid: (tables: string[], values: Record<string, Record<string, string>>) => void;
}) {
  const instRef = useRef<HTMLInputElement>(null);
  const [uploadingInst, setUploadingInst] = useState(false);
  const [instErr, setInstErr] = useState<string | null>(null);
  const [gv, setGv] = useState<{ busy: boolean; phase?: string; error?: string }>({ busy: false });
  const gvPoll = useRef<number | null>(null);
  useEffect(() => () => { if (gvPoll.current) window.clearTimeout(gvPoll.current); }, []);

  function pollFullValid() {
    getGenerateValidStatus(pkgId).then((s) => {
      if (s.status === "solving") {
        setGv({ busy: true, phase: s.phase || "solving rules offline…" });
        gvPoll.current = window.setTimeout(pollFullValid, 3000);
      } else if (s.status === "ready") {
        setGv({ busy: false, phase: `Generated ${(s.tables ?? []).length} table(s) — opening in Amend.` });
        onFullValid(s.tables ?? [], s.values ?? {});
      } else {
        setGv({ busy: false, error: s.error || "Generate failed." });
      }
    }).catch((e) => setGv({ busy: false, error: (e as Error).message }));
  }
  async function genFullValid() {
    if (!scope.entryPoint) return;
    setGv({ busy: true, phase: `Building + solving all tables of ${scope.entryPoint}…` });
    try {
      await startGenerateValidModule(pkgId, scope.entryPoint);
      pollFullValid();
    } catch (e) {
      setGv({ busy: false, error: (e as Error).message });
    }
  }

  async function handleInstance(file: File) {
    setInstErr(null); setUploadingInst(true);
    try {
      const meta = await uploadInstance(pkgId, file);
      if (meta.tables.length === 0) setInstErr("No reported tables found in that instance for this package.");
      else onInstanceLoaded(meta.tables);
    } catch (e) {
      setInstErr((e as Error).message);
    } finally {
      setUploadingInst(false);
      if (instRef.current) instRef.current.value = "";
    }
  }
  const [status, setStatus] = useState<TablesStatus | null>(null);
  const [scope, setScope] = useState<Scope>({ framework: "", entryPoint: "" });
  const [index, setIndex] = useState<TablesIndex | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [dp, setDp] = useState<TableDatapoints | null>(null);
  const [page, setPage] = useState(1);
  const [loadingDp, setLoadingDp] = useState(false);
  const filterRef = useRef<HTMLInputElement>(null);
  const [filter, setFilter] = useState("");

  const ready = status?.status === "ready";

  // poll index status (kick build if absent), then load the index
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    setStatus(null); setIndex(null); setSelected(null); setDp(null);
    async function tick(kick: boolean) {
      try {
        let st = await getTablesStatus(pkgId);
        if (st.status === "absent" && kick) st = await buildTables(pkgId);
        if (cancelled) return;
        setStatus(st);
        if (st.status === "building") timer = window.setTimeout(() => tick(false), 1500);
      } catch {
        if (!cancelled) timer = window.setTimeout(() => tick(false), 2000);
      }
    }
    tick(true);
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [pkgId]);

  // (re)load the index whenever the scope changes (once the index is ready)
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    getTables(pkgId, scope)
      .then((idx) => {
        if (cancelled) return;
        setIndex(idx);
        setOpen({ [idx.frameworks[0]?.framework]: true });
        setSelected(null); setDp(null);
      })
      .catch(() => { if (!cancelled) setIndex(null); });
    return () => { cancelled = true; };
  }, [pkgId, ready, scope]);

  // load datapoints for the selected table / page
  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setLoadingDp(true);
    getTableDatapoints(pkgId, selected, page, PAGE_SIZE)
      .then((d) => { if (!cancelled) setDp(d); })
      .catch(() => { if (!cancelled) setDp(null); })
      .finally(() => { if (!cancelled) setLoadingDp(false); });
    return () => { cancelled = true; };
  }, [pkgId, selected, page]);

  function pick(code: string) { setSelected(code); setPage(1); }
  function toggleCheck(code: string) {
    setChecked((s) => { const n = new Set(s); n.has(code) ? n.delete(code) : n.add(code); return n; });
  }

  if (!ready)
    return (
      <div className="dict">
        <div className="progress-wrap">
          <div className="progress-label">
            {status?.status === "error"
              ? `⚠ Table index failed: ${status.error}`
              : `Indexing the tables in ${pkgName ? `“${pkgName}”` : "this package"} from the table linkbase… one-time & cached.`}
          </div>
          {status?.status !== "error" && (
            <div className="progress-bar"><div className="progress-fill indet" style={{ width: "100%" }} /></div>
          )}
        </div>
      </div>
    );

  return (
    <>
    <div className="inst-upload">
      <input ref={instRef} type="file" accept=".xbrl,.xml" hidden disabled={uploadingInst}
        onChange={(e) => e.target.files?.[0] && handleInstance(e.target.files[0])} />
      <button className="btn" disabled={uploadingInst} onClick={() => instRef.current?.click()}>
        {uploadingInst ? "⏳ Loading instance…" : "⬆ Upload data (.xbrl) → populate tables"}
      </button>
      <span className="hint">Loads an XBRL instance for this package; its reported tables open in Amend pre-filled with the data.</span>
      {instErr && <span className="error">⚠ {instErr}</span>}
    </div>
    <ScopePicker pkgId={pkgId} value={scope} onChange={setScope} />
    <div className="inst-upload">
      <button className="btn primary" disabled={!scope.entryPoint || gv.busy} onClick={genFullValid}
        title={scope.entryPoint ? `Build every table of ${scope.entryPoint} and offline-solve its rules` : "Pick a Framework ▸ Entry point first"}>
        {gv.busy ? "⏳ Generating…" : "⚖ Generate Full Valid Data"}
      </button>
      <span className="hint">
        {scope.entryPoint
          ? `Fills all tables of ${scope.entryPoint} with rule-consistent values (offline solve of the enforced rules), then opens them in Amend.`
          : "Select a Framework ▸ Entry point above to enable. First run parses the framework's rules (cached); large modules take a few minutes."}
      </span>
      {gv.error && <span className="error">⚠ {gv.error}</span>}
      {!gv.error && gv.phase && gv.busy && <span className="hint">{gv.phase}</span>}
    </div>
    <div className="tables-view">
      <aside className="tbl-tree">
        <input
          ref={filterRef}
          className="search"
          placeholder="Filter tables by code…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <div className="tree-summary dim">
          {index?.nTables.toLocaleString()} tables · {index?.nDatapoints.toLocaleString()} datapoints
        </div>
        {checked.size > 0 && (
          <div className="edit-bar">
            <button className="btn primary" onClick={() => onEdit([...checked])}>
              ✎ Edit {checked.size} table{checked.size > 1 ? "s" : ""} →
            </button>
            <button className="btn" onClick={() => setChecked(new Set())}>Clear</button>
          </div>
        )}
        {index?.frameworks.map((fw) => (
          <FrameworkNode
            key={fw.framework}
            fw={fw}
            open={!!open[fw.framework] || !!filter}
            filter={filter}
            selected={selected}
            checked={checked}
            onToggle={() => setOpen((o) => ({ ...o, [fw.framework]: !o[fw.framework] }))}
            onPick={pick}
            onToggleCheck={toggleCheck}
          />
        ))}
      </aside>

      <section className="tbl-detail">
        {!selected ? (
          <div className="hint" style={{ marginTop: 20 }}>
            Select a table on the left to see its datapoints (metric × dimension members),
            read straight from the taxonomy's table linkbase.
          </div>
        ) : (
          <>
            <div className="detail-bar">
              <button className="btn" onClick={() => onViewRules(selected!)} title="See the business rules that touch this table">
                ⚖ View related rules
              </button>
            </div>
            <TableDetail dp={dp} loading={loadingDp} page={page} setPage={setPage} />
          </>
        )}
      </section>
    </div>
    </>
  );
}

function FrameworkNode({ fw, open, filter, selected, checked, onToggle, onPick, onToggleCheck }: {
  fw: FrameworkGroup; open: boolean; filter: string; selected: string | null;
  checked: Set<string>; onToggle: () => void; onPick: (code: string) => void;
  onToggleCheck: (code: string) => void;
}) {
  const f = filter.trim().toUpperCase();
  const tables = f ? fw.tables.filter((t) => t.code.toUpperCase().includes(f)) : fw.tables;
  if (f && tables.length === 0) return null;
  return (
    <div className="fw-node">
      <button className="fw-head" onClick={onToggle}>
        <span className="caret">{open ? "▾" : "▸"}</span>
        <span className="fw-name">{fw.framework}</span>
        <span className="fw-meta dim">{fw.nTables}</span>
      </button>
      {open && (
        <ul className="tbl-list">
          {tables.map((t) => (
            <li key={t.code} className={"tbl-row" + (checked.has(t.code) ? " checked" : "")}>
              <input
                type="checkbox"
                className="tbl-check"
                checked={checked.has(t.code)}
                onChange={() => onToggleCheck(t.code)}
                title="Select for amend"
              />
              <button
                className={"tbl-item" + (t.code === selected ? " active" : "")}
                onClick={() => onPick(t.code)}
                title={`${t.nDatapoints} datapoints${t.nOpenAxes ? ` · ${t.nOpenAxes} open axis` : ""}`}
              >
                <code>{t.code}</code>
                <span className="tbl-count dim">{t.nDatapoints.toLocaleString()}</span>
                {t.nOpenAxes > 0 && <span className="tag warn">open</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TableDetail({ dp, loading, page, setPage }: {
  dp: TableDatapoints | null; loading: boolean; page: number; setPage: (p: number) => void;
}) {
  if (!dp && loading) return <div className="hint" style={{ marginTop: 20 }}>Loading…</div>;
  if (!dp) return <div className="hint" style={{ marginTop: 20 }}>No datapoints.</div>;
  const totalPages = Math.max(1, Math.ceil(dp.total / dp.pageSize));
  // dimension columns present on this page (union, stable order)
  const dimCols: string[] = [];
  for (const r of dp.rows) for (const d of r.dimensions) if (!dimCols.includes(d.dimension)) dimCols.push(d.dimension);

  return (
    <>
      <div className="row" style={{ gap: 10, alignItems: "baseline" }}>
        <h2 style={{ margin: 0 }}>{dp.code}</h2>
        <span className="dim">{dp.framework}</span>
        <span className="count-chip">datapoints <em>{dp.total.toLocaleString()}</em></span>
      </div>
      <div className="hint" style={{ marginTop: 4 }}>
        axes: {Object.entries(dp.axes).map(([a, n]) => `${a}=${n}`).join(" · ") || "—"}
        {dp.openAxes.length > 0 && (
          <> · <span className="tag warn">open</span> {dp.openAxes.length} open dimension axis
            {dp.openAxes.length > 1 ? "es" : ""} (members not enumerated here)</>
        )}
        {!dp.modelReady && <> · labels pending (dictionary still building)</>}
      </div>

      {dp.total === 0 ? (
        <div className="hint" style={{ marginTop: 16 }}>
          No closed (rule-node) datapoints — this table's axes are open over dimensions.
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Metric</th><th>Datatype</th>
              {dimCols.map((d) => <th key={d}>{d.split(":").pop()}</th>)}
            </tr>
          </thead>
          <tbody>
            {dp.rows.map((r, i) => <DatapointTr key={i} r={r} dimCols={dimCols} />)}
          </tbody>
        </table>
      )}

      {dp.total > 0 && (
        <div className="pager">
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}>← Prev</button>
          <span className="dim">Page {dp.page} / {totalPages} · {dp.total.toLocaleString()} datapoints</span>
          <button disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next →</button>
        </div>
      )}
    </>
  );
}

function DatapointTr({ r, dimCols }: { r: DatapointRow; dimCols: string[] }) {
  const byDim: Record<string, { member: string; memberLabel?: string }> = {};
  for (const d of r.dimensions) byDim[d.dimension] = { member: d.member, memberLabel: d.memberLabel };
  return (
    <tr>
      <td>
        <code>{r.metric.split(":").pop()}</code>
        {r.metricLabel && <span className="dim"> {r.metricLabel}</span>}
      </td>
      <td>{r.datatype || "—"}</td>
      {dimCols.map((d) => (
        <td key={d}>
          {byDim[d]
            ? <span title={byDim[d].memberLabel || ""}><code>{byDim[d].member.split(":").pop()}</code></span>
            : <span className="dim">—</span>}
        </td>
      ))}
    </tr>
  );
}
