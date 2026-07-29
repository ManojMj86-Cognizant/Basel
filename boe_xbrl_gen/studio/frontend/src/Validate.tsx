import { useEffect, useRef, useState } from "react";
import {
  getSolveStatus, getValidateFiles, getValidateStatus, SolveStatus, startSolve, startValidate,
  solveFileUrl, ValidateFile, ValidateStatus, validateCleanedUrl,
} from "./api";

export default function Validate({ pkgId }: { pkgId: string }) {
  const [files, setFiles] = useState<ValidateFile[]>([]);
  const [hasZip, setHasZip] = useState(true);
  const [sel, setSel] = useState<string>("");          // "source|filename"
  const [st, setSt] = useState<ValidateStatus | null>(null);
  const [solve, setSolve] = useState<SolveStatus | null>(null);
  const poll = useRef<number | null>(null);
  const spoll = useRef<number | null>(null);

  useEffect(() => {
    getValidateFiles(pkgId).then((d) => {
      setFiles(d.files); setHasZip(d.hasSourceZip);
      if (d.files[0]) setSel(`${d.files[0].source}|${d.files[0].filename}`);
    }).catch(() => setFiles([]));
    getValidateStatus(pkgId).then(setSt).catch(() => {});
    return () => { if (poll.current) window.clearTimeout(poll.current); if (spoll.current) window.clearTimeout(spoll.current); };
  }, [pkgId]);

  function pollStatus() {
    getValidateStatus(pkgId).then((s) => {
      setSt(s);
      if (s.status === "building") poll.current = window.setTimeout(pollStatus, 2000);
    }).catch(() => {});
  }

  async function run() {
    const [source, filename] = sel.split("|");
    if (!filename) return;
    setSt({ status: "building", filename });
    setSolve(null);
    try {
      await startValidate(pkgId, source, filename);
      pollStatus();
    } catch (e) {
      setSt({ status: "error", error: (e as Error).message });
    }
  }

  function pollSolve() {
    getSolveStatus(pkgId).then((s) => {
      setSolve(s);
      if (s.status === "solving") spoll.current = window.setTimeout(pollSolve, 2500);
      else if (s.status === "ready") { getValidateFiles(pkgId).then((d) => setFiles(d.files)).catch(() => {}); }
    }).catch(() => {});
  }

  async function runSolve() {
    const [source, filename] = sel.split("|");
    if (!filename) return;
    setSolve({ status: "solving", filename });
    try {
      await startSolve(pkgId, source, filename);
      pollSolve();
    } catch (e) {
      setSolve({ status: "error", error: (e as Error).message });
    }
  }

  const r = st?.report;
  return (
    <div className="dict">
      <div className="row" style={{ gap: 12, alignItems: "baseline", flexWrap: "wrap", marginTop: 10 }}>
        <h2 style={{ margin: 0 }}>Validate</h2>
        <span className="hint">Run Arelle on a built or uploaded instance — structure, dimensions, and the package's business rules.</span>
      </div>

      {!hasZip && <div className="error" style={{ marginTop: 10 }}>⚠ The package source zip isn't cached — re-upload the package to enable Arelle validation.</div>}

      <div className="scope-bar">
        <label className="dim">File</label>
        <select value={sel} onChange={(e) => setSel(e.target.value)} disabled={files.length === 0} style={{ minWidth: 360 }}>
          {files.length === 0 && <option value="">— no built/uploaded instances yet —</option>}
          {files.map((f) => (
            <option key={f.source + f.filename} value={`${f.source}|${f.filename}`}>
              {f.filename} ({f.source})
            </option>
          ))}
        </select>
        <button className="btn primary" disabled={!sel || st?.status === "building"} onClick={run}>⚖ Validate</button>
      </div>
      <div className="hint">Build instances in the Amend tab (Create XBRL) or upload one in the Tables tab; they appear here.</div>

      {st?.status === "building" && (
        <div className="gen-status"><span className="spinner" />Validating {st.filename} with Arelle… big modules (e.g. PRA001) can take several minutes; this keeps running if you switch tabs.</div>
      )}
      {st?.status === "error" && <div className="error" style={{ marginTop: 10 }}>⚠ {st.error}</div>}

      {st?.status === "ready" && r && (
        <div className="gen-result">
          <div className="row" style={{ gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
            <strong>{st.filename}</strong>
            <span className={"tag " + (r.ok ? "ok" : "warn")}>{r.ok ? "✓ structurally valid" : "⚠ issues"}</span>
            {(st.removed ?? 0) > 0 && <span className="tag warn">{st.removed} dim-invalid facts pruned</span>}
            {st.cleaned ? <a className="btn" href={validateCleanedUrl(pkgId, st.cleaned)} download>⤓ cleaned file</a> : null}
            {st.elapsedMs != null && <span className="dim">{(st.elapsedMs / 1000).toFixed(0)}s</span>}
          </div>
          <div className="report" style={{ marginTop: 6 }}>
            {r.dimInvalid.length > 0 && <span className="dim">{r.dimInvalid.length} dim-invalid · </span>}
            {r.valueErrors.length > 0 && <span className="dim">{r.valueErrors.length} value errors · </span>}
            {r.otherErrors.length > 0 && <span className="dim">{r.otherErrors.length} other errors · </span>}
            <span className="dim">{r.assertionsUnsatisfied.length} business-rule assertion(s) not satisfied</span>
          </div>
          {r.assertionsUnsatisfied.length > 0 && (
            <details open>
              <summary>business-rule assertions (e.g. additivity that random/edited data may break)</summary>
              <ul className="assert-list">
                {r.assertionsUnsatisfied.slice(0, 100).map((a) => (
                  <li key={a.id}><code>{a.id}</code> ×{a.count} — {a.message}</li>
                ))}
              </ul>
            </details>
          )}
          {r.assertionsUnsatisfied.length > 0 && (
            <div className="row" style={{ gap: 10, alignItems: "baseline", marginTop: 8, flexWrap: "wrap" }}>
              <button className="btn primary" disabled={solve?.status === "solving"} onClick={runSolve}>⚙ Solve business rules</button>
              <span className="hint">Adjusts derived/total values (additivity, sign, cross-table sums) to satisfy the rules, then re-validates. Iterative Arelle — can take minutes.</span>
            </div>
          )}
          {r.valueErrors.length > 0 && (
            <details>
              <summary>{r.valueErrors.length} datatype/value error(s)</summary>
              <ul className="assert-list">{r.valueErrors.slice(0, 50).map((e, i) => <li key={i}>{e}</li>)}</ul>
            </details>
          )}
        </div>
      )}

      {solve?.status === "solving" && (
        <div className="gen-status"><span className="spinner" />Solving business rules (iterative validate→solve→re-validate)… this can take several minutes; it keeps running if you switch tabs.</div>
      )}
      {solve?.status === "error" && <div className="error" style={{ marginTop: 10 }}>⚠ {solve.error}</div>}
      {solve?.status === "ready" && (
        <div className="gen-result" style={{ marginTop: 12 }}>
          <div className="row" style={{ gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
            <strong>⚙ Solve result</strong>
            <span className={"tag " + ((solve.after?.assertions ?? 1) === 0 ? "ok" : "warn")}>
              {(solve.before?.assertions ?? "?")} → {solve.after?.assertions ?? "?"} unsatisfied assertion(s)
            </span>
            <span className="dim">{solve.iterations} iteration(s)</span>
            {solve.elapsedMs != null && <span className="dim">{(solve.elapsedMs / 1000).toFixed(0)}s</span>}
            {solve.solved && <a className="btn" href={solveFileUrl(pkgId, solve.solved)} download>⤓ {solve.solved}</a>}
          </div>
          {(solve.after?.assertions ?? 0) === 0
            ? <div className="hint">✓ All business-rule assertions satisfied. The solved file is also in the File list above — re-validate to confirm.</div>
            : (
              <details open>
                <summary>{solve.after?.assertions} assertion(s) still unsatisfied (cross-table tails may need another pass)</summary>
                <ul className="assert-list">
                  {(solve.after?.list ?? []).slice(0, 100).map((a) => (
                    <li key={a.id}><code>{a.id}</code> ×{a.count} — {a.message}</li>
                  ))}
                </ul>
              </details>
            )}
        </div>
      )}
    </div>
  );
}
