import { useEffect, useRef, useState } from "react";
import {
  CachedPackage,
  deletePackage,
  getJob,
  getPackage,
  listPackages,
  PackageSummary,
  uploadPackage,
} from "./api";
import Amend from "./Amend";
import Dictionary from "./Dictionary";
import Guide from "./Guide";
import Rules from "./Rules";
import Tables from "./Tables";
import Validate from "./Validate";

type Phase = "idle" | "uploading" | "extracting" | "done" | "error";
type View = "home" | "ingest" | "dictionary" | "tables" | "amend" | "rules" | "validate";

export default function App() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [pct, setPct] = useState(0);
  const [fileName, setFileName] = useState<string | null>(null);
  const [extract, setExtract] = useState<{ extracted: number; total: number } | null>(null);
  const [summary, setSummary] = useState<PackageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [packages, setPackages] = useState<CachedPackage[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [view, setView] = useState<View>("home");
  const [amendCodes, setAmendCodes] = useState<string[]>([]);
  // per-table origin: "select" = user picked it in Tables to author fresh values; "upload" =
  // it came from an uploaded instance (populate from that file). Drives Amend's behaviour.
  const [amendOrigins, setAmendOrigins] = useState<Record<string, "upload" | "select">>({});
  // solved values from "Generate Full Valid Data" (table -> cellKey -> value), pre-filled in Amend
  const [amendPreset, setAmendPreset] = useState<Record<string, Record<string, string>> | undefined>(undefined);
  const [rulesTable, setRulesTable] = useState<string | undefined>(undefined);
  const inputRef = useRef<HTMLInputElement>(null);

  const busy = phase === "uploading" || phase === "extracting";

  async function refreshPackages() {
    try {
      setPackages(await listPackages());
    } catch {
      /* non-fatal for the list */
    }
  }

  // Amend works on a UNION of tables: those picked in Tables ("Edit") and those found in an
  // uploaded instance. Both entry points merge (deduped) instead of overwriting, so e.g. you
  // can select table A, then upload an instance reporting B/C/D, and edit/export A,B,C,D together.
  // Each table also records its ORIGIN; the latest action wins (re-selecting an uploaded table
  // via Edit flips it to "select" so the user gets a fresh authorable grid).
  const addAmendCodes = (incoming: string[], origin: "upload" | "select") => {
    setAmendOrigins((o) => { const n = { ...o }; incoming.forEach((c) => { n[c] = origin; }); return n; });
    setAmendCodes((prev) => Array.from(new Set([...prev, ...incoming])));
  };

  useEffect(() => {
    refreshPackages();
  }, []);

  async function finish(s: PackageSummary) {
    setSummary(s);
    setSelectedId(s.id);
    setExtract(null);
    setPhase("done");
    await refreshPackages();
  }

  // New zip: poll the backend extraction job until it is ready (or errors).
  async function pollJob(jobId: string) {
    try {
      const st = await getJob(jobId);
      if (st.status === "extracting") {
        setExtract({ extracted: st.extracted, total: st.total });
        window.setTimeout(() => pollJob(jobId), 800);
      } else if (st.status === "ready" && st.summary) {
        await finish(st.summary);
      } else {
        setError(st.error || "Extraction failed.");
        setExtract(null);
        setPhase("error");
      }
    } catch (e) {
      setError((e as Error).message);
      setPhase("error");
    }
  }

  async function handleFile(file: File) {
    setError(null);
    setSummary(null);
    setExtract(null);
    setPct(0);
    setFileName(file.name);
    setPhase("uploading");
    try {
      const res = await uploadPackage(file, (p) => {
        setPct(p);
        if (p >= 100) setPhase("extracting");
      });
      if (res.status === "ready") {
        await finish(res.summary); // cache hit — instant
      } else {
        setPhase("extracting");
        setExtract({ extracted: res.extracted, total: res.total });
        pollJob(res.jobId);
      }
    } catch (e) {
      setError((e as Error).message);
      setPhase("error");
    }
  }

  async function handleSelect(id: string) {
    setSelectedId(id);
    setAmendCodes([]); setAmendOrigins({}); // table codes are package-specific
    if (!id) return;
    setError(null);
    try {
      setSummary(await getPackage(id));
      setPhase("done");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleDelete() {
    if (!selectedId) return;
    const id = selectedId;
    const p = packages.find((x) => x.id === id);
    const label = p?.filename || p?.name || id.slice(0, 12);
    if (!window.confirm(`Delete cached package "${label}"?\nYou can re-upload the zip afterwards.`))
      return;
    setError(null);
    // Optimistic: drop it from the dropdown and clear the metrics/summary immediately,
    // so the UI doesn't wait on the (slow) disk delete.
    const prev = packages;
    setPackages(packages.filter((x) => x.id !== id));
    setSelectedId("");
    setSummary(null);
    setPhase("idle");
    setView("ingest");
    setAmendCodes([]);
    try {
      await deletePackage(id);
      await refreshPackages();
    } catch (e) {
      setPackages(prev); // restore the dropdown if the delete failed
      setError((e as Error).message);
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    if (busy) return;
    const f = e.dataTransfer.files?.[0];
    if (f) handleFile(f);
  }

  return (
    <div className="page">
      <header>
        <div className="title">
          <h1>Datapoint Studio</h1>
          <nav className="nav">
            <button
              className={"nav-tab" + (view === "home" ? " active" : "")}
              onClick={() => setView("home")}
            >
              Home
            </button>
            <button
              className={"nav-tab" + (view === "ingest" ? " active" : "")}
              onClick={() => setView("ingest")}
            >
              Ingest
            </button>
            <button
              className={"nav-tab" + (view === "dictionary" ? " active" : "")}
              disabled={!selectedId}
              title={selectedId ? "" : "Load or select a package first"}
              onClick={() => setView("dictionary")}
            >
              Dictionary
            </button>
            <button
              className={"nav-tab" + (view === "tables" ? " active" : "")}
              disabled={!selectedId}
              title={selectedId ? "" : "Load or select a package first"}
              onClick={() => setView("tables")}
            >
              Tables
            </button>
            <button
              className={"nav-tab" + (view === "amend" ? " active" : "")}
              disabled={amendCodes.length === 0}
              title={amendCodes.length ? "" : "Select tables in the Tables tab and click Edit"}
              onClick={() => setView("amend")}
            >
              Amend{amendCodes.length ? ` (${amendCodes.length})` : ""}
            </button>
            <button
              className={"nav-tab" + (view === "rules" ? " active" : "")}
              disabled={!selectedId}
              title={selectedId ? "" : "Load or select a package first"}
              onClick={() => { setRulesTable(undefined); setView("rules"); }}
            >
              Rules
            </button>
            <button
              className={"nav-tab" + (view === "validate" ? " active" : "")}
              disabled={!selectedId}
              title={selectedId ? "" : "Load or select a package first"}
              onClick={() => setView("validate")}
            >
              Validate
            </button>
          </nav>
        </div>
        <div className="pkg-picker">
          <label>Loaded packages</label>
          <div className="pkg-row">
            <select
              value={selectedId}
              disabled={busy || packages.length === 0}
              onChange={(e) => handleSelect(e.target.value)}
            >
              <option value="">
                {packages.length === 0 ? "— none yet —" : "— select a package —"}
              </option>
              {packages.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.filename || p.name} {p.version ? `(v${p.version})` : ""}
                </option>
              ))}
            </select>
            <button
              className="btn-delete"
              title="Delete the selected cached package"
              disabled={busy || !selectedId}
              onClick={handleDelete}
            >
              🗑 Delete
            </button>
          </div>
        </div>
      </header>

      {view === "home" ? (
        <Guide
          onStart={() => setView("ingest")}
          hasPackage={!!selectedId}
          onOpenDictionary={() => setView("dictionary")}
        />
      ) : view === "dictionary" && selectedId ? (
        <Dictionary
          key={selectedId}
          pkgId={selectedId}
          pkgName={packages.find((p) => p.id === selectedId)?.name || summary?.package.name}
        />
      ) : view === "tables" && selectedId ? (
        <Tables
          key={selectedId}
          pkgId={selectedId}
          pkgName={packages.find((p) => p.id === selectedId)?.name || summary?.package.name}
          onEdit={(codes) => { addAmendCodes(codes, "select"); setView("amend"); }}
          onViewRules={(code) => { setRulesTable(code); setView("rules"); }}
          onInstanceLoaded={(tables) => { addAmendCodes(tables, "upload"); setView("amend"); }}
          onFullValid={(tables, values) => { setAmendPreset(values); addAmendCodes(tables, "select"); setView("amend"); }}
        />
      ) : view === "amend" && selectedId ? (
        <Amend key={selectedId} pkgId={selectedId} codes={amendCodes} origins={amendOrigins} preset={amendPreset} onCodesChange={setAmendCodes} />
      ) : view === "rules" && selectedId ? (
        <Rules key={selectedId + (rulesTable || "")} pkgId={selectedId} initialTable={rulesTable} />
      ) : view === "validate" && selectedId ? (
        <Validate key={selectedId} pkgId={selectedId} />
      ) : (
      <>
      <p className="lead">
        Upload a Bank of England Banking XBRL <strong>taxonomy package zip</strong>. It is
        extracted once (cached by content hash) and summarised below. Previously ingested
        packages are available from the dropdown on the right.
      </p>

      <div
        className={"dropzone" + (busy ? " disabled" : "")}
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        onClick={() => !busy && inputRef.current?.click()}
        aria-disabled={busy}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".zip"
          hidden
          disabled={busy}
          onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
        />
        <div className="dz-icon">{busy ? "⏳" : "⬆"}</div>
        <div>
          {busy ? (
            <>
              <strong>Processing {fileName}</strong>
              <div className="hint">Upload disabled until manifesting finishes…</div>
            </>
          ) : (
            <>
              <strong>Drop the taxonomy zip here</strong> or click to choose
              <div className="hint">e.g. boebanking400.zip (~56 MB)</div>
            </>
          )}
        </div>
      </div>

      {phase === "uploading" && (
        <Progress label={`Uploading ${fileName}… ${pct.toFixed(0)}%`} pct={pct} />
      )}
      {phase === "extracting" &&
        (extract && extract.total > 0 ? (
          <Progress
            label={`Extracting ${fileName} — ${extract.extracted.toLocaleString()} / ${extract.total.toLocaleString()} files (${((extract.extracted / extract.total) * 100).toFixed(0)}%)`}
            pct={(extract.extracted / extract.total) * 100}
          />
        ) : (
          <Progress label={`Counting files in ${fileName}…`} pct={100} indeterminate />
        ))}
      {phase === "error" && <div className="error">⚠ {error}</div>}

      {summary && <Summary s={summary} />}
      </>
      )}
    </div>
  );
}

function Progress({ label, pct, indeterminate }: { label: string; pct: number; indeterminate?: boolean }) {
  return (
    <div className="progress-wrap">
      <div className="progress-label">{label}</div>
      <div className="progress-bar">
        <div className={"progress-fill" + (indeterminate ? " indet" : "")} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function Summary({ s }: { s: PackageSummary }) {
  const p = s.package;
  return (
    <div className="summary">
      <div className="row">
        <h2>{p.name || "Taxonomy package"}</h2>
        {s.cached ? <span className="chip cached">cached</span> : <span className="chip fresh">extracted now</span>}
        {s.filename && <span className="chip file">{s.filename}</span>}
      </div>
      <div className="meta">
        <Kv k="Version" v={p.version} />
        <Kv k="Publisher" v={p.publisher} />
        <Kv k="Published" v={p.publicationDate} />
        <Kv k="Entry points" v={String(p.entryPointCount)} />
        <Kv k="Files" v={s.fileCount != null ? String(s.fileCount) : "—"} />
        <Kv k="Ingest" v={`${s.elapsedMs} ms`} />
      </div>

      {s.model && (
        <div className="cards">
          <Card n={s.model.metrics} label="Metrics" />
          <Card n={s.model.dimensions} label="Dimensions" />
          <Card n={s.model.domains} label="Domains" />
          <Card n={s.model.members} label="Members" />
        </div>
      )}
      {s.model && <div className="hint">Model counts from {s.model.source}.</div>}

      <h3>Frameworks ({Object.keys(p.frameworks).length})</h3>
      <div className="fw">
        {Object.entries(p.frameworks).map(([fw, n]) => (
          <span key={fw} className="fw-chip">
            {fw} <em>{n}</em>
          </span>
        ))}
      </div>

      <h3>Entry points</h3>
      <table>
        <thead>
          <tr><th>Module</th><th>Framework</th><th>Description</th></tr>
        </thead>
        <tbody>
          {p.entryPoints.map((ep) => (
            <tr key={ep.name + ep.href}>
              <td><code>{ep.name}</code></td>
              <td>{ep.framework}<span className="dim"> / {ep.frameworkVersion}</span></td>
              <td>{ep.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="hint">Package id (sha256): <code>{s.id.slice(0, 16)}…</code></div>
    </div>
  );
}

const Kv = ({ k, v }: { k: string; v: string }) => (
  <div className="kv"><span>{k}</span><strong>{v || "—"}</strong></div>
);
const Card = ({ n, label }: { n: number; label: string }) => (
  <div className="card"><div className="num">{n.toLocaleString()}</div><div className="lbl">{label}</div></div>
);
