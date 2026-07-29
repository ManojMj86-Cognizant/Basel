// Home / How-to guide — the landing page. Orients the user, then sends them to Ingest.

export default function Guide({ onStart, hasPackage, onOpenDictionary }: {
  onStart: () => void;
  hasPackage: boolean;
  onOpenDictionary: () => void;
}) {
  return (
    <div className="guide">
      <p className="lead">
        <strong>Datapoint Studio</strong> analyses and (soon) amends the datapoints of Bank of
        England XBRL. You start from the <strong>taxonomy package zip</strong> — the app reads
        the metrics, dimensions and members straight out of it, so it works for any BoE
        taxonomy with no extra spreadsheets required.
      </p>

      <div className="steps">
        <Step n={1} title="Ingest — upload the taxonomy package">
          <p>
            Go to the <b>Ingest</b> tab and drop the taxonomy package <code>.zip</code>{" "}
            (e.g. <code>boebanking400.zip</code>, ~56&nbsp;MB). It is extracted once and{" "}
            <b>cached by content hash</b>, so re-uploading the same zip later is instant.
          </p>
          <p className="hint">
            ⏱ First extraction of a 56&nbsp;MB package takes <b>~4–5 minutes</b> (thousands of
            small files) — you'll see a live <code>files extracted</code> progress bar. Cached
            re-use is a few seconds.
          </p>
        </Step>

        <Step n={2} title="How the metrics are translated">
          <p>
            As soon as a package is ingested, the app builds its <b>DPM dictionary</b> directly
            from the taxonomy using <b>Arelle</b> — no DPM spreadsheet needed. It reads:
          </p>
          <ul>
            <li><b>Metrics</b> + their <b>datatype</b> (monetary, percentage, boolean, date, enumeration, …) from the XBRL schema type</li>
            <li><b>Dimensions</b>, <b>domains</b> and <b>members</b> from the dictionary schemas</li>
            <li><b>Labels</b> from the taxonomy's label linkbase</li>
          </ul>
          <p className="hint">
            ⏱ This build is <b>one-time and cached</b>, and scales with taxonomy size —
            typically <b>around a minute</b> for a smaller taxonomy and <b>a minute or two</b>{" "}
            for a large one. While it runs, the Dictionary tab shows a “building…” banner, then
            renders automatically.
          </p>
        </Step>

        <Step n={3} title="Explore — the Dictionary tab">
          <p>
            Open the <b>Dictionary</b> tab to browse the model: section tabs for{" "}
            <b>Metrics / Dimensions / Domains / Members</b>, a search box (by code, label or
            qname) and pagination. Metric rows show the datatype, with small tags:
          </p>
          <ul>
            <li><span className="tag warn">refine</span> an ambiguous numeric the schema can't pin down (PERCENTAGE vs DECIMAL vs INTEGER)</li>
            <li><span className="tag ok">excel</span> a datatype refined from an uploaded DPM workbook (see step 4)</li>
          </ul>
        </Step>

        <Step n={4} title="Reconcile (optional) — cross-check against the DPM workbook">
          <p>
            In the Dictionary tab's <b>Reconcile</b> panel you can upload the BoE{" "}
            <b>DPM dictionary</b> <code>.xlsx</code> to cross-check the package-derived model.
            You'll get a per-section <b>diff</b>: datatype conflicts, items only on one side,
            and a note on members redeclared under more than one namespace. (An <b>Annotated
            Templates</b> workbook is accepted too — stashed for the upcoming per-table view.)
          </p>
        </Step>
      </div>

      <div className="guide-cta">
        <button className="btn primary" onClick={onStart}>① Start — go to Ingest</button>
        {hasPackage && (
          <button className="btn" onClick={onOpenDictionary}>Open the Dictionary →</button>
        )}
        <span className="hint">A package is loaded once and reused; pick it any time from the dropdown, top-right.</span>
      </div>
    </div>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="step">
      <div className="step-n">{n}</div>
      <div className="step-body">
        <h3>{title}</h3>
        {children}
      </div>
    </div>
  );
}
