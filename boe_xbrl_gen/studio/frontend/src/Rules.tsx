import { useEffect, useRef, useState } from "react";
import { buildRules, getRules, getRulesStatus, resolveTableScope, RuleRow } from "./api";
import ScopePicker, { Scope } from "./ScopePicker";

const PAGE = 50;

export default function Rules({ pkgId, initialTable }: { pkgId: string; initialTable?: string }) {
  const [scope, setScope] = useState<Scope>({ framework: "", entryPoint: "", table: "" });
  const module = scope.entryPoint;
  const tableFilter = scope.table ?? "";
  const [status, setStatus] = useState<string>("");      // building | ready | error | absent
  const [statusErr, setStatusErr] = useState<string | null>(null);
  const [rows, setRows] = useState<RuleRow[]>([]);
  const [total, setTotal] = useState(0);
  const [nRulesModule, setNRulesModule] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const poll = useRef<number | null>(null);

  useEffect(() => () => { if (poll.current) window.clearTimeout(poll.current); }, []);

  // arriving from Tables' "View related rules": resolve the table -> framework/entry-point/table
  useEffect(() => {
    if (!initialTable) return;
    let cancelled = false;
    const tryResolve = () => resolveTableScope(pkgId, initialTable)
      .then((r) => { if (!cancelled && r.found) setScope({ framework: r.framework, entryPoint: r.entryPoint, table: r.table }); })
      .catch((e) => { if (!cancelled && (e as Error).message === "building") poll.current = window.setTimeout(tryResolve, 1500); });
    tryResolve();
    return () => { cancelled = true; };
  }, [pkgId, initialTable]);

  // when a module is picked, ensure its rules are built, then load (honoring the current table filter)
  useEffect(() => {
    if (!module) { setStatus(""); setRows([]); return; }
    setRows([]); setTotal(0); setPage(1); setQ(""); setStatusErr(null);
    let cancelled = false;
    async function ensure() {
      const st = await getRulesStatus(pkgId, module);
      if (cancelled) return;
      if (st.status === "ready") { setStatus("ready"); load(1, "", tableFilter); return; }
      if (st.status === "error") { setStatus("error"); setStatusErr(st.error || "build failed"); return; }
      if (st.status === "absent") await buildRules(pkgId, module);
      setStatus("building");
      poll.current = window.setTimeout(ensure, 1500);
    }
    ensure();
    return () => { cancelled = true; if (poll.current) window.clearTimeout(poll.current); };
  }, [pkgId, module]); // eslint-disable-line react-hooks/exhaustive-deps

  async function load(p: number, qv: string, tv: string) {
    try {
      const res = await getRules(pkgId, module, qv, tv, p, PAGE);
      setRows(res.rules); setTotal(res.total); setNRulesModule(res.nRulesModule);
      setPage(res.page); setStatus("ready");
    } catch (e) {
      if ((e as Error).message === "building") setStatus("building");
      else setStatusErr((e as Error).message);
    }
  }

  // debounced re-load on search text or table-filter change
  useEffect(() => {
    if (status !== "ready") return;
    const h = window.setTimeout(() => load(1, q, tableFilter), 300);
    return () => window.clearTimeout(h);
  }, [q, tableFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalPages = Math.max(1, Math.ceil(total / PAGE));

  return (
    <div className="dict">
      <div className="row" style={{ gap: 12, alignItems: "baseline", flexWrap: "wrap", marginTop: 10 }}>
        <h2 style={{ margin: 0 }}>Validation Rules</h2>
        <span className="hint">Business (formula) assertions shipped in the package — the rules Arelle evaluates.</span>
      </div>

      <ScopePicker pkgId={pkgId} value={scope} onChange={setScope} requireEntryPoint showTable />
      {tableFilter && (
        <div className="hint" style={{ marginTop: 4 }}>
          Showing rules that touch <code>{tableFilter}</code> — cross-table rules also list the other tables they impact.
        </div>
      )}
      {module && status === "ready" && (
        <div className="row" style={{ gap: 12, alignItems: "center", flexWrap: "wrap", margin: "10px 0" }}>
          <input className="search" placeholder="search id / message / test…" value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="count-chip">{total} / {nRulesModule} rules</span>
        </div>
      )}

      {!module && <div className="hint" style={{ marginTop: 8 }}>Pick an entry point to see the business rules it enforces (e.g. <code>pra001</code>) — or use <strong>View related rules</strong> on a table in the Tables tab.</div>}
      {module && status === "building" && (
        <div className="gen-status"><span className="spinner" />Collecting rules for {module}… (big modules like PRA001 take a little while; cached after the first time)</div>
      )}
      {statusErr && <div className="error">⚠ {statusErr}</div>}

      {status === "ready" && (
        <>
          <table className="rules-table">
            <thead>
              <tr><th>Rule</th><th>Sev.</th><th>Tables</th><th>Assertion</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td><code>{r.id}</code></td>
                  <td><span className={"sev " + (r.severity || "").toLowerCase()}>{r.severity}</span></td>
                  <td className="rule-tables">
                    {r.tables.map((t) => (
                      <span key={t} className={"rt" + (t === tableFilter ? " hit" : "")}>{t}</span>
                    ))}
                  </td>
                  <td>
                    <div className="rule-msg">{r.message || <span className="dim">(no message label)</span>}</div>
                    <details>
                      <summary>formal test</summary>
                      <code className="rule-test">{r.test}</code>
                      <div className="dim" style={{ marginTop: 2 }}>source: {r.source}</div>
                    </details>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={4} className="hint">No rules match.</td></tr>}
            </tbody>
          </table>
          {totalPages > 1 && (
            <div className="pager">
              <button disabled={page <= 1} onClick={() => load(page - 1, q, tableFilter)}>← Prev</button>
              <span className="dim">page {page}/{totalPages}</span>
              <button disabled={page >= totalPages} onClick={() => load(page + 1, q, tableFilter)}>Next →</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
