import { useEffect, useRef, useState } from "react";
import {
  buildModel,
  getModelStatus,
  getReconcileReport,
  ModelPage,
  ModelStatus,
  queryModel,
  reconcileModel,
  ReconcileReport,
  Section,
} from "./api";
import ScopePicker, { Scope } from "./ScopePicker";

const SECTIONS: { key: Section; label: string }[] = [
  { key: "metrics", label: "Metrics" },
  { key: "dimensions", label: "Dimensions" },
  { key: "domains", label: "Domains" },
  { key: "members", label: "Members" },
];
const PAGE_SIZE = 50;

export default function Dictionary({ pkgId, pkgName }: { pkgId: string; pkgName?: string }) {
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [section, setSection] = useState<Section>("metrics");
  const [scope, setScope] = useState<Scope>({ framework: "", entryPoint: "" });
  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<ModelPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<ReconcileReport | null>(null);
  const [recError, setRecError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const ready = status?.status === "ready";

  // ---- build-status poll (kicks a build if absent) ----
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    setStatus(null);
    setData(null);
    setReport(null);
    async function tick(kickIfAbsent: boolean) {
      try {
        let st = await getModelStatus(pkgId);
        if (st.status === "absent" && kickIfAbsent) st = await buildModel(pkgId);
        if (cancelled) return;
        setStatus(st);
        if (st.status === "building") timer = window.setTimeout(() => tick(false), 2000);
      } catch {
        if (!cancelled) timer = window.setTimeout(() => tick(false), 3000);
      }
    }
    tick(true);
    getReconcileReport(pkgId).then((r) => !cancelled && r && setReport(r)).catch(() => {});
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [pkgId]);

  // ---- debounce search ----
  useEffect(() => {
    const t = window.setTimeout(() => { setQDebounced(q); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [q]);

  // ---- load section rows once ready ----
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    setLoading(true);
    queryModel(pkgId, section, qDebounced, page, PAGE_SIZE, scope)
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setData(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [pkgId, section, qDebounced, page, ready, report, scope]);

  async function onUpload(file: File) {
    setRecError(null);
    setUploading(true);
    try {
      const r = await reconcileModel(pkgId, file);
      setReport(r);
      // refresh status (reconciled flag) and current page
      setStatus(await getModelStatus(pkgId));
    } catch (e) {
      setRecError((e as Error).message);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  if (!status || status.status === "building")
    return <BuildBanner status={status} pkgName={pkgName} />;
  if (status.status === "error")
    return <div className="error">⚠ Model build failed: {status.error}</div>;

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1;

  return (
    <div className="dict">
      <ReconcileDrop
        uploading={uploading}
        error={recError}
        report={report}
        fileRef={fileRef}
        onUpload={onUpload}
      />
      {report && <DiffPanel report={report} />}

      <div className="dict-head">
        <div className="counts">
          {status.counts && SECTIONS.map((s) => (
            <span key={s.key} className="count-chip">
              {s.label}<em>{status.counts![s.key].toLocaleString()}</em>
            </span>
          ))}
          {status.reconciled && <span className="chip cached">reconciled</span>}
        </div>
      </div>

      <ScopePicker pkgId={pkgId} value={scope} onChange={(s) => { setScope(s); setPage(1); }} />
      {(scope.framework || scope.entryPoint) && (
        <div className="hint" style={{ marginTop: 4 }}>
          Showing only the dictionary concepts used by {scope.entryPoint || scope.framework}.
        </div>
      )}

      <div className="tabs">
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            className={"tab" + (s.key === section ? " active" : "")}
            onClick={() => { setSection(s.key); setPage(1); }}
          >
            {s.label}
          </button>
        ))}
        <input
          className="search"
          placeholder={`Search ${section} by code / label / qname…`}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <Grid section={section} data={data} loading={loading} reconciled={status.reconciled} />

      {data && data.total > 0 && (
        <div className="pager">
          <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>← Prev</button>
          <span className="dim">
            Page {data.page} / {totalPages} · {data.total.toLocaleString()} rows
          </span>
          <button disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next →</button>
        </div>
      )}
    </div>
  );
}

function BuildBanner({ status, pkgName }: { status: ModelStatus | null; pkgName?: string }) {
  const who = pkgName ? `“${pkgName}”` : "this package";
  return (
    <div className="dict">
      <div className="progress-wrap">
        <div className="progress-label">
          {status?.status === "building"
            ? `Building the dictionary model for ${who} from the package itself (Arelle)… one-time & cached. Typically under a minute; longer for very large taxonomies.`
            : "Checking model…"}
        </div>
        <div className="progress-bar"><div className="progress-fill indet" style={{ width: "100%" }} /></div>
      </div>
    </div>
  );
}

function Grid({ section, data, loading, reconciled }: {
  section: Section; data: ModelPage | null; loading: boolean; reconciled: boolean;
}) {
  if (loading && !data) return <div className="hint" style={{ marginTop: 16 }}>Loading…</div>;
  if (!data || data.total === 0)
    return <div className="hint" style={{ marginTop: 16 }}>No rows{loading ? " (loading…)" : ""}.</div>;

  return (
    <table>
      <thead>
        {section === "metrics" && (
          <tr><th>Code</th><th>Label</th><th>Datatype</th><th>Period</th><th>QName</th></tr>
        )}
        {section === "dimensions" && (
          <tr><th>Code</th><th>Label</th><th>Kind</th><th>QName</th></tr>
        )}
        {section === "domains" && (
          <tr><th>Code</th><th>Label</th><th>Type</th><th>Owner</th></tr>
        )}
        {section === "members" && (
          <tr><th>QName</th><th>Code</th><th>Label</th><th>Flags</th></tr>
        )}
      </thead>
      <tbody>
        {data.rows.map((r, i) => {
          if (section === "metrics")
            return (
              <tr key={i}>
                <td><code>{r.code}</code></td>
                <td>{r.label || "—"}</td>
                <td>
                  {r.datatype}
                  {r.needs_refine && <span className="tag warn" title="ambiguous numeric from schema">refine</span>}
                  {reconciled && r.datatype_source === "excel" && <span className="tag ok" title="from DPM Excel">excel</span>}
                </td>
                <td className="dim">{r.period_type || "—"}</td>
                <td><code className="dim">{r.qname}</code></td>
              </tr>
            );
          if (section === "dimensions")
            return (
              <tr key={i}>
                <td><code>{r.code}</code></td>
                <td>{r.label || "—"}</td>
                <td className="dim">{r.typed ? "typed" : "explicit"}</td>
                <td><code className="dim">{r.qname}</code></td>
              </tr>
            );
          if (section === "domains")
            return (
              <tr key={i}>
                <td><code>{r.code}</code></td>
                <td>{r.label || "—"}</td>
                <td className="dim">{String(r.type ?? "—")}</td>
                <td className="dim">{r.owner || "—"}</td>
              </tr>
            );
          return (
            <tr key={i}>
              <td><code>{r.qname}</code></td>
              <td>{r.code}</td>
              <td>{r.label || "—"}</td>
              <td className="dim">
                {r.usable === false ? "not-usable " : ""}{r.default ? "default" : ""}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function ReconcileDrop({ report, uploading, error, fileRef, onUpload }: {
  report: ReconcileReport | null;
  uploading: boolean;
  error: string | null;
  fileRef: React.RefObject<HTMLInputElement>;
  onUpload: (f: File) => void;
}) {
  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    if (uploading) return;
    const f = e.dataTransfer.files?.[0];
    if (f) onUpload(f);
  }
  return (
    <div className="rec-drop-wrap">
      <div
        className={"dropzone" + (uploading ? " disabled" : "")}
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        onClick={() => !uploading && fileRef.current?.click()}
        aria-disabled={uploading}
      >
        <input
          ref={fileRef} type="file" accept=".zip,.xlsx" hidden disabled={uploading}
          onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])}
        />
        <div className="dz-icon">{uploading ? "⏳" : "⬆"}</div>
        <div>
          {uploading ? (
            <>
              <strong>Reconciling…</strong>
              <div className="hint">Reading the DPM workbooks and comparing to the package model.</div>
            </>
          ) : (
            <>
              <strong>Reconcile against the DPM pack (optional)</strong> — drop the DPM{" "}
              <strong>.zip</strong> (dictionary + annotated templates) or click to choose
              <div className="hint">
                The dictionary above is built from the package itself; this cross-checks it.
                A single <code>.xlsx</code> (DPM dictionary or annotated templates) works too.
              </div>
            </>
          )}
        </div>
      </div>
      {error && <div className="error">⚠ {error}</div>}
      {report && (
        <div className="rec-row" style={{ marginTop: 10 }}>
          {report.filename && <span className="chip file">{report.filename}</span>}
          {report.dictionary && <span className="dim">dictionary: <code>{report.dictionary}</code></span>}
          {report.annotatedTemplates && report.annotatedTemplates.length > 0 && (
            <span className="dim">· {report.annotatedTemplates.length} annotated-template workbook(s) stashed for the Tables view</span>
          )}
          {report.kind === "annotated_templates" && <span className="dim">{report.message}</span>}
        </div>
      )}
    </div>
  );
}

function DiffPanel({ report }: { report: ReconcileReport }) {
  const dm = report?.diffs?.metrics.datatype_mismatch ?? [];
  const redecl = report?.diffs?.members.redeclared ?? [];
  const sm = report?.summary;
  if (!sm) return null;

  return (
    <div className="reconcile">
      <h3>Reconciliation result</h3>
      {sm && (
        <div className="diff">
          <div className="diff-cards">
            {(["metrics", "dimensions", "members"] as const).map((sec) => (
              <div key={sec} className="diff-card">
                <div className="diff-title">{sec}</div>
                <div className="diff-line">schema <b>{sm[sec].schema}</b> · excel <b>{sm[sec].excel}</b></div>
                <div className="diff-line dim">
                  only-schema {sm[sec].only_in_schema} · only-excel {sm[sec].only_in_excel}
                  {"datatype_mismatch" in sm[sec] ? ` · dtype Δ ${sm[sec].datatype_mismatch}` : ""}
                  {"redeclared" in sm[sec] ? ` · redeclared ${sm[sec].redeclared}` : ""}
                </div>
              </div>
            ))}
          </div>

          {dm.length > 0 && (
            <>
              <h4>Datatype conflicts ({dm.length}) <span className="dim">— schema kept unless ambiguous</span></h4>
              <table>
                <thead><tr><th>Metric</th><th>Label</th><th>Schema</th><th>Excel</th><th>Resolution</th></tr></thead>
                <tbody>
                  {dm.map((m) => (
                    <tr key={m.code}>
                      <td><code>{m.code}</code></td>
                      <td>{m.label}</td>
                      <td>{m.schema}</td>
                      <td>{m.excel}</td>
                      <td className="dim">{m.needs_refine ? "→ Excel (refined)" : "kept schema"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {redecl.length > 0 && (
            <p className="hint">
              <b>{redecl.length}</b> members are declared under more than one owner namespace
              (e.g. <code>{redecl[0].key}</code> → {redecl[0].prefixes.join(", ")}). These are the
              same logical members; both qnames are kept as valid.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
