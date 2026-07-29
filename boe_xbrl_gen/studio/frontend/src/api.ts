// Thin API client for the Datapoint Studio backend (Phase 0).

export interface EntryPoint {
  name: string;
  description: string;
  framework: string;
  frameworkVersion: string;
  href: string;
}

export interface PackageManifest {
  name: string;
  version: string;
  publisher: string;
  publicationDate: string;
  identifier: string;
  entryPoints: EntryPoint[];
  frameworks: Record<string, number>;
  entryPointCount: number;
}

export interface ModelCounts {
  metrics: number;
  dimensions: number;
  domains: number;
  memberSets: number;
  members: number;
  source: string;
}

export interface PackageSummary {
  id: string;
  filename: string | null;
  sizeBytes: number | null;
  cached: boolean;
  freshlyExtracted?: boolean;
  fileCount: number | null;
  extractedPath: string;
  elapsedMs: number;
  package: PackageManifest;
  model: ModelCounts | null;
}

// POST /api/package returns one of these: a cache hit (ready) or a started job.
export interface IngestReady {
  status: "ready";
  summary: PackageSummary;
}
export interface IngestStarted {
  status: "extracting";
  jobId: string;
  id: string;
  filename: string;
  extracted: number;
  total: number;
}
export type IngestResponse = IngestReady | IngestStarted;

export interface JobStatus {
  status: "extracting" | "ready" | "error";
  extracted: number;
  total: number;
  summary?: PackageSummary;
  error?: string;
}

export async function getJob(jobId: string): Promise<JobStatus> {
  const r = await fetch(`/api/package/job/${jobId}`);
  if (!r.ok) throw new Error(`Failed to read extraction progress (${r.status})`);
  return r.json();
}

export interface CachedPackage {
  id: string;
  filename: string | null;
  name: string;
  version: string;
}

export async function listPackages(): Promise<CachedPackage[]> {
  const r = await fetch("/api/packages");
  if (!r.ok) throw new Error(`Failed to list packages (${r.status})`);
  return (await r.json()).packages as CachedPackage[];
}

export async function getPackage(id: string): Promise<PackageSummary> {
  const r = await fetch(`/api/package/${id}`);
  if (!r.ok) throw new Error(`Failed to load package (${r.status})`);
  return r.json();
}

export async function deletePackage(id: string): Promise<void> {
  const r = await fetch(`/api/package/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`Failed to delete package (${r.status})`);
}

// ----------------------------------------------------- Phase 1a: dictionary model
export interface ModelStatus {
  status: "absent" | "building" | "ready" | "error";
  reconciled: boolean;
  counts?: { metrics: number; dimensions: number; domains: number; members: number };
  elapsedMs?: number;
  error?: string;
}

export type Section = "metrics" | "dimensions" | "domains" | "members";

export interface ModelRow {
  code: string;
  label?: string;
  qname?: string;
  owner?: string;
  prefix?: string;
  datatype?: string;
  needs_refine?: boolean;
  datatype_source?: string;
  period_type?: string | null;
  typed?: boolean;
  [k: string]: unknown;
}

export interface ModelPage {
  section: Section;
  total: number;
  page: number;
  pageSize: number;
  reconciled: boolean;
  rows: ModelRow[];
}

export interface ReconcileReport {
  kind: "dpm_dictionary" | "annotated_templates" | "zip";
  filename?: string;
  message?: string;
  dictionary?: string;
  annotatedTemplates?: string[];
  summary?: Record<string, Record<string, number>>;
  diffs?: {
    metrics: { only_in_schema: string[]; only_in_excel: string[];
      datatype_mismatch: { code: string; schema: string; excel: string; label?: string; needs_refine?: boolean }[];
      label_diff: { code: string; schema?: string; excel?: string }[] };
    dimensions: { only_in_schema: string[]; only_in_excel: string[];
      datatype_mismatch: unknown[]; label_diff: { code: string; schema?: string; excel?: string }[] };
    members: { only_in_schema: string[]; only_in_excel: string[];
      label_diff: { key: string; schema?: string; excel?: string }[];
      redeclared: { key: string; prefixes: string[] }[] };
  };
}

export async function getModelStatus(id: string): Promise<ModelStatus> {
  const r = await fetch(`/api/package/${id}/model/status`);
  if (!r.ok) throw new Error(`Failed to read model status (${r.status})`);
  return r.json();
}

export async function buildModel(id: string, force = false): Promise<ModelStatus> {
  const r = await fetch(`/api/package/${id}/model/build${force ? "?force=true" : ""}`, { method: "POST" });
  if (!r.ok) throw new Error(`Failed to start model build (${r.status})`);
  return r.json();
}

export async function queryModel(
  id: string, section: Section, q: string, page: number, pageSize = 50,
  scope?: { framework?: string; entryPoint?: string }
): Promise<ModelPage> {
  const p = new URLSearchParams({ section, q, page: String(page), pageSize: String(pageSize) });
  if (scope?.framework) p.set("framework", scope.framework);
  if (scope?.entryPoint) p.set("entryPoint", scope.entryPoint);
  const r = await fetch(`/api/package/${id}/model?${p}`);
  if (r.status === 425) throw new Error("building");
  if (!r.ok) throw new Error(`Failed to query model (${r.status})`);
  return r.json();
}

export async function reconcileModel(id: string, file: File): Promise<ReconcileReport> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(`/api/package/${id}/model/reconcile`, { method: "POST", body: form });
  if (!r.ok) {
    let detail = `Reconcile failed (${r.status})`;
    try { detail = (await r.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return r.json();
}

export async function getReconcileReport(id: string): Promise<ReconcileReport | null> {
  const r = await fetch(`/api/package/${id}/model/reconcile`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`Failed to load reconcile report (${r.status})`);
  return r.json();
}

// ----------------------------------------------------- Phase 1b: tables / datapoints
export interface TableInfo { code: string; nDatapoints: number; nOpenAxes: number; }
export interface FrameworkGroup {
  framework: string; tables: TableInfo[]; nTables: number; nDatapoints: number;
}
export interface TablesIndex { frameworks: FrameworkGroup[]; nTables: number; nDatapoints: number; }
export interface TablesStatus {
  status: "absent" | "building" | "ready" | "error";
  count?: number; elapsedMs?: number; error?: string;
}
export interface DatapointDim {
  dimension: string; dimLabel?: string; member: string; memberLabel?: string;
}
export interface DatapointRow {
  metric: string; metricLabel?: string; datatype?: string; dimensions: DatapointDim[];
}
export interface TableDatapoints {
  code: string; framework: string;
  axes: Record<string, number>;
  openAxes: { node: string; dimension?: string; axis?: string; typed?: boolean; members?: EnumValue[] }[];
  modelReady: boolean; total: number; page: number; pageSize: number; rows: DatapointRow[];
}

export async function getTablesStatus(id: string): Promise<TablesStatus> {
  const r = await fetch(`/api/package/${id}/tables/status`);
  if (!r.ok) throw new Error(`Failed to read tables status (${r.status})`);
  return r.json();
}

export async function buildTables(id: string): Promise<TablesStatus> {
  const r = await fetch(`/api/package/${id}/tables/build`, { method: "POST" });
  if (!r.ok) throw new Error(`Failed to start table index (${r.status})`);
  return r.json();
}

export async function getTables(
  id: string, scope?: { framework?: string; entryPoint?: string }
): Promise<TablesIndex> {
  const p = new URLSearchParams();
  if (scope?.framework) p.set("framework", scope.framework);
  if (scope?.entryPoint) p.set("entryPoint", scope.entryPoint);
  const r = await fetch(`/api/package/${id}/tables?${p}`);
  if (r.status === 425) throw new Error("building");
  if (!r.ok) throw new Error(`Failed to load tables (${r.status})`);
  return r.json();
}

// ----------------------------------------------------- framework ▸ entry-point scope
export interface ScopeEntryPoint { module: string; nTables: number; tables: string[] }
export interface ScopeFramework { framework: string; entryPoints: ScopeEntryPoint[]; nTables: number }
export async function getScope(id: string): Promise<ScopeFramework[]> {
  const r = await fetch(`/api/package/${id}/scope`);
  if (r.status === 425) throw new Error("building");
  if (!r.ok) throw new Error(`Failed to load scope (${r.status})`);
  return (await r.json()).frameworks;
}
// ----------------------------------------------------- uploaded instance (Section C)
export interface InstanceInfo {
  filename: string; module: string; framework: string;
  tables: string[]; nFacts: number; nTyped: number; nIndexed: number;
}
export interface CellValue { value: string; fi: number }
export interface InstanceValues { code: string; values: Record<string, CellValue>; nMatched: number }

export async function uploadInstance(id: string, file: File): Promise<InstanceInfo> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(`/api/package/${id}/instance`, { method: "POST", body: form });
  if (!r.ok) {
    const m = await r.json().catch(() => null);
    throw new Error(m?.detail || `Upload failed (${r.status})`);
  }
  return r.json();
}
export async function getInstanceInfo(id: string): Promise<InstanceInfo | null> {
  const r = await fetch(`/api/package/${id}/instance`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`Failed to read instance (${r.status})`);
  return r.json();
}
export async function clearInstance(id: string): Promise<void> {
  await fetch(`/api/package/${id}/instance`, { method: "DELETE" });
}
export async function getInstanceValues(id: string, code: string): Promise<InstanceValues> {
  const r = await fetch(`/api/package/${id}/instance/values/${encodeURIComponent(code)}`);
  if (r.status === 425) throw new Error("building");
  if (!r.ok) throw new Error(`Failed to load instance values (${r.status})`);
  return r.json();
}
// instance-expanded grid (OPEN axes expanded from the instance's facts) + matched values
export type InstanceGrid = TableGrid & { values: Record<string, CellValue>; nMatched: number };
export async function getInstanceGrid(id: string, code: string): Promise<InstanceGrid> {
  const r = await fetch(`/api/package/${id}/instance/grid/${encodeURIComponent(code)}`);
  if (r.status === 425) throw new Error("building");
  if (!r.ok) throw new Error(`Failed to load instance grid (${r.status})`);
  return r.json();
}
export async function saveInstance(id: string, edits: Record<string, string>): Promise<void> {
  const r = await fetch(`/api/package/${id}/instance/save`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ edits }),
  });
  if (!r.ok) throw new Error(`Save failed (${r.status})`);
  const blob = await r.blob();
  const cd = r.headers.get("Content-Disposition") || "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] || "edited.xbrl";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  URL.revokeObjectURL(url);
}

export interface ResolvedScope { framework: string; entryPoint: string; table: string; found: boolean }
export async function resolveTableScope(id: string, table: string): Promise<ResolvedScope> {
  const r = await fetch(`/api/package/${id}/scope/resolve?table=${encodeURIComponent(table)}`);
  if (r.status === 425) throw new Error("building");
  if (!r.ok) throw new Error(`Failed to resolve table (${r.status})`);
  return r.json();
}

export async function getTableDatapoints(
  id: string, code: string, page: number, pageSize = 50
): Promise<TableDatapoints> {
  const p = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
  const r = await fetch(`/api/package/${id}/tables/${encodeURIComponent(code)}/datapoints?${p}`);
  if (r.status === 425) throw new Error("building");
  if (!r.ok) throw new Error(`Failed to load datapoints (${r.status})`);
  return r.json();
}

// ----------------------------------------------------- Phase 2: amend (grid layout)
export interface EnumValue { qname: string; label: string }
export interface GridPosition {
  label: string;
  concept: string | null;
  datatype?: string | null;
  enumValues?: EnumValue[];
  dims: Record<string, string>;
}
export interface TableGrid {
  code: string;
  framework: string;
  axes: Record<string, number>;
  openAxes: { node: string; dimension?: string; axis?: string; typed?: boolean; members?: EnumValue[] }[];
  columns: GridPosition[];
  rows: GridPosition[];
  zPositions: GridPosition[];
  modelReady: boolean;
}

export async function getTableGrid(id: string, code: string): Promise<TableGrid> {
  const r = await fetch(`/api/package/${id}/tables/${encodeURIComponent(code)}/grid`);
  if (r.status === 425) throw new Error("building");
  if (!r.ok) throw new Error(`Failed to load table grid (${r.status})`);
  return r.json();
}

// ----------------------------------------------------- Phase 2: generate / create XBRL
export interface Datapoint {
  concept: string | null;
  dims: Record<string, string>;
  datatype?: string | null;
  value: string;
  key?: string;          // grid cell key "z:r:c" — lets offline-solve reflect solved values back
}
export interface AssertionRow { id: string; count: number; message: string }
export interface ValidationReport {
  dimInvalid: { fact: string; context: string }[];
  valueErrors: string[];
  assertionsUnsatisfied: AssertionRow[];
  otherErrors: string[];
  ok: boolean;
}
// generate = BUILD ONLY (instant, no Arelle); validation is a separate async step.
export interface InstanceResult {
  filename: string; module: string; framework: string; schemaRef: string;
  tables: string[]; facts: number; contexts: number;
}
export interface GenerateResult {
  instances: InstanceResult[];
  unmapped: string[];
  errors: { module: string; error: string }[];
  opts: { lei: string; date: string };
}
export async function generateInstance(
  id: string, selection: Record<string, Datapoint[]>
): Promise<GenerateResult> {
  const r = await fetch(`/api/package/${id}/generate`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ selection }),
  });
  if (!r.ok) {
    const msg = await r.json().catch(() => null);
    throw new Error(msg?.detail || `Build failed (${r.status})`);
  }
  return r.json();
}
export function generateFileUrl(id: string, filename: string): string {
  return `/api/package/${id}/generate/file/${encodeURIComponent(filename)}`;
}

// ----------------------------------------------- generate rule-consistent data (offline, async)
export interface GenValidModule { module: string; framework?: string; tables: string[]; stats: Record<string, unknown>; ruleCount: number }
export interface GenValidStatus {
  status: "absent" | "solving" | "ready" | "error";
  values?: Record<string, Record<string, string>>;   // table -> cellKey -> solved value
  tables?: string[];
  modules?: GenValidModule[];
  unmapped?: string[]; errors?: { module: string; error: string }[];
  elapsedMs?: number; error?: string; phase?: string; entryPoint?: string;
}
export async function startGenerateValidModule(id: string, entryPoint: string): Promise<GenValidStatus> {
  const r = await fetch(`/api/package/${id}/generate-valid-module`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entryPoint }),
  });
  if (!r.ok) {
    const msg = await r.json().catch(() => null);
    throw new Error(msg?.detail || `Generate-valid-module failed to start (${r.status})`);
  }
  return r.json();
}
export async function startGenerateValid(id: string, selection: Record<string, Datapoint[]>): Promise<GenValidStatus> {
  const r = await fetch(`/api/package/${id}/generate-valid`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ selection }),
  });
  if (!r.ok) {
    const msg = await r.json().catch(() => null);
    throw new Error(msg?.detail || `Generate-valid failed to start (${r.status})`);
  }
  return r.json();
}
export async function getGenerateValidStatus(id: string): Promise<GenValidStatus> {
  const r = await fetch(`/api/package/${id}/generate-valid/status`);
  if (!r.ok) throw new Error(`Failed to read generate-valid status (${r.status})`);
  return r.json();
}

// ----------------------------------------------------- validation (separate async step)
export interface ValidateFile { filename: string; source: "generated" | "uploaded" | "solved" }
export interface ValidateStatus {
  status: "absent" | "building" | "ready" | "error";
  filename?: string; source?: string; report?: ValidationReport;
  removed?: number; cleaned?: string; elapsedMs?: number; error?: string;
}
export async function getValidateFiles(id: string): Promise<{ files: ValidateFile[]; hasSourceZip: boolean }> {
  const r = await fetch(`/api/package/${id}/validate/files`);
  if (!r.ok) throw new Error(`Failed to list files (${r.status})`);
  return r.json();
}
export async function startValidate(id: string, source: string, filename: string): Promise<ValidateStatus> {
  const r = await fetch(`/api/package/${id}/validate`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, filename }),
  });
  if (!r.ok) {
    const msg = await r.json().catch(() => null);
    throw new Error(msg?.detail || `Validate failed to start (${r.status})`);
  }
  return r.json();
}
export async function getValidateStatus(id: string): Promise<ValidateStatus> {
  const r = await fetch(`/api/package/${id}/validate/status`);
  if (!r.ok) throw new Error(`Failed to read validate status (${r.status})`);
  return r.json();
}
export function validateCleanedUrl(id: string, filename: string): string {
  return `/api/package/${id}/validate/file/${encodeURIComponent(filename)}`;
}

// ----------------------------------------------------- solve business rules (Phase B, async)
export interface SolveStatus {
  status: "absent" | "solving" | "ready" | "error";
  filename?: string; source?: string; solved?: string; iterations?: number;
  before?: { violations: number | null; assertions: number | null };
  after?: { violations: number | null; assertions: number; list: AssertionRow[] };
  elapsedMs?: number; error?: string;
}
export async function startSolve(id: string, source: string, filename: string, iters = 4): Promise<SolveStatus> {
  const r = await fetch(`/api/package/${id}/solve`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, filename, iters }),
  });
  if (!r.ok) {
    const msg = await r.json().catch(() => null);
    throw new Error(msg?.detail || `Solve failed to start (${r.status})`);
  }
  return r.json();
}
export async function getSolveStatus(id: string): Promise<SolveStatus> {
  const r = await fetch(`/api/package/${id}/solve/status`);
  if (!r.ok) throw new Error(`Failed to read solve status (${r.status})`);
  return r.json();
}
export function solveFileUrl(id: string, filename: string): string {
  return `/api/package/${id}/solve/file/${encodeURIComponent(filename)}`;
}

// ----------------------------------------------------- Phase B: business validation rules
export interface RuleModule { module: string; framework: string; nTables: number }
export interface RuleRow {
  id: string; severity: string; test: string; message: string | null;
  source: string; tables: string[];
}
export interface RulesPage {
  module: string; total: number; nRulesModule: number;
  page: number; pageSize: number; rules: RuleRow[];
}
export interface RulesStatus { status: string; nRules?: number; elapsedMs?: number; error?: string }

export async function getRuleModules(id: string): Promise<RuleModule[]> {
  const r = await fetch(`/api/package/${id}/rules/modules`);
  if (!r.ok) throw new Error(`Failed to load modules (${r.status})`);
  return (await r.json()).modules;
}
export async function buildRules(id: string, module: string, force = false): Promise<RulesStatus> {
  const r = await fetch(`/api/package/${id}/rules/build?module=${encodeURIComponent(module)}&force=${force}`, { method: "POST" });
  if (!r.ok) throw new Error(`Failed to start rules build (${r.status})`);
  return r.json();
}
export async function getRulesStatus(id: string, module: string): Promise<RulesStatus> {
  const r = await fetch(`/api/package/${id}/rules/status?module=${encodeURIComponent(module)}`);
  if (!r.ok) throw new Error(`Failed to read rules status (${r.status})`);
  return r.json();
}
export async function getRules(
  id: string, module: string, q: string, table: string, page: number, pageSize = 50
): Promise<RulesPage> {
  const p = new URLSearchParams({ module, q, table, page: String(page), pageSize: String(pageSize) });
  const r = await fetch(`/api/package/${id}/rules?${p}`);
  if (r.status === 425) throw new Error("building");
  if (!r.ok) throw new Error(`Failed to load rules (${r.status})`);
  return r.json();
}

export async function uploadPackage(
  file: File,
  onProgress?: (pct: number) => void
): Promise<IngestResponse> {
  // XHR (not fetch) so we can report upload progress for the 56 MB zip.
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/package");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress((e.loaded / e.total) * 100);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
      else {
        try {
          reject(new Error(JSON.parse(xhr.responseText).detail || xhr.statusText));
        } catch {
          reject(new Error(`Upload failed (${xhr.status})`));
        }
      }
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(form);
  });
}
