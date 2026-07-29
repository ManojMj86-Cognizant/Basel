import { useEffect, useRef, useState } from "react";
import { getScope, ScopeFramework } from "./api";

export interface Scope { framework: string; entryPoint: string; table?: string }

/** Framework (group 1) ▸ Entry-point (group 2) [▸ Table (group 3)] dropdowns, each with "All".
 *  requireEntryPoint=true (Rules): no "All entry-point" — a module must be chosen.
 *  showTable=true (Rules): adds a Table dropdown scoped to the chosen entry-point. */
export default function ScopePicker({
  pkgId, value, onChange, requireEntryPoint = false, showTable = false,
}: {
  pkgId: string;
  value: Scope;
  onChange: (s: Scope) => void;
  requireEntryPoint?: boolean;
  showTable?: boolean;
}) {
  const [frameworks, setFrameworks] = useState<ScopeFramework[] | null>(null);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const poll = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const fw = await getScope(pkgId);
        if (!cancelled) { setFrameworks(fw); setBuilding(false); }
      } catch (e) {
        if (cancelled) return;
        if ((e as Error).message === "building") {
          setBuilding(true);
          poll.current = window.setTimeout(load, 1500);
        } else setError((e as Error).message);
      }
    }
    load();
    return () => { cancelled = true; if (poll.current) window.clearTimeout(poll.current); };
  }, [pkgId]);

  // entry points for the chosen framework, else all entry points (flattened)
  const eps = frameworks
    ? (value.framework
        ? frameworks.find((f) => f.framework === value.framework)?.entryPoints ?? []
        : frameworks.flatMap((f) => f.entryPoints))
    : [];
  const tables = (showTable && value.entryPoint)
    ? eps.find((ep) => ep.module === value.entryPoint)?.tables ?? []
    : [];

  return (
    <div className="scope-bar">
      <label className="dim">Framework</label>
      <select
        value={value.framework}
        disabled={!frameworks}
        onChange={(e) => onChange({ framework: e.target.value, entryPoint: "", table: "" })}
      >
        <option value="">All frameworks</option>
        {frameworks?.map((f) => (
          <option key={f.framework} value={f.framework}>{f.framework} ({f.nTables} tables)</option>
        ))}
      </select>

      <label className="dim">Entry point</label>
      <select
        value={value.entryPoint}
        disabled={!frameworks}
        onChange={(e) => onChange({ framework: value.framework, entryPoint: e.target.value, table: "" })}
      >
        <option value="">{requireEntryPoint ? "— select an entry point —" : "All entry points"}</option>
        {eps.map((ep) => (
          <option key={ep.module} value={ep.module}>{ep.module} ({ep.nTables} tables)</option>
        ))}
      </select>

      {showTable && (
        <>
          <label className="dim">Table</label>
          <select
            value={value.table ?? ""}
            disabled={!value.entryPoint}
            onChange={(e) => onChange({ framework: value.framework, entryPoint: value.entryPoint, table: e.target.value })}
          >
            <option value="">All tables</option>
            {tables.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </>
      )}

      {building && <span className="dim"><span className="spinner" /> building scope index…</span>}
      {error && <span className="error">⚠ {error}</span>}
    </div>
  );
}
