const API_BASE = import.meta.env.VITE_API_URL || "";

export type QueryType = "owner" | "parcel" | "address" | "book_page";

export interface NodeOverride {
  node_id: string;
  url?: string;
  playwright_notes?: string;
  enabled?: boolean;
  agent_name?: string;
  instructions?: string;
  user_prompt?: string;
  model?: string;
  agent_type?: string;
  temperature?: number;
  max_tokens?: number;
}

export interface OpenAIConfigStatus {
  configured: boolean;
}

export interface PipelineGraphNode {
  id: string;
  node_id: string;
  type: string;
  enabled: boolean;
  data: Record<string, unknown>;
}

export interface PipelineGraphEdge {
  source: string;
  target: string;
}

export interface PipelineGraph {
  nodes: PipelineGraphNode[];
  edges: PipelineGraphEdge[];
}

export interface SearchRequest {
  state: string;
  county: string;
  query_type: QueryType;
  query_value: string;
  book_number?: string;
  page_number?: string;
  pipeline_graph?: PipelineGraph;
  node_overrides?: NodeOverride[];
}

export interface RunEvent {
  id?: string;
  run_id: string;
  event_type: string;
  source?: string;
  payload?: {
    message?: string;
    node?: string;
    records_found?: number;
    duration_ms?: number;
    reason?: string;
    [key: string]: unknown;
  };
  created_at?: string;
}

export interface SourceProgress {
  source: string;
  status: string;
  records_found: number;
  message?: string | null;
}

export interface RunDetail {
  run: {
    id: string;
    state: string;
    county: string;
    query_type: QueryType;
    query_value: string;
    status: string;
    plan_json?: {
      steps?: string[];
      state?: string;
      county?: string;
      query_type?: string;
      query_value?: string;
      pipeline_graph?: PipelineGraph;
    };
    error_message?: string;
  };
  events: RunEvent[];
  records_count: number;
  documents_count: number;
  records: Record<string, unknown>[];
  documents: Record<string, unknown>[];
  sources: SourceProgress[];
}

export interface ReportData {
  id: string;
  run_id: string;
  report_json: {
    state?: string;
    county?: string;
    query_type?: string;
    query_value?: string;
    property?: Record<string, unknown>;
    tax_record?: Record<string, unknown>;
    documents?: Record<string, unknown>[];
    sources_trail?: Record<string, unknown>[];
    generated_at?: string;
  };
  pdf_path?: string;
  storage_path?: string;
  storage_url?: string;
}

export interface DownloadReportResult {
  storageUrl?: string | null;
  storagePath?: string | null;
}

export interface CountyOption {
  slug: string;
  name: string;
}

export interface AIAgentConfigPayload {
  agent_name?: string;
  instructions?: string;
  user_prompt?: string;
  model?: string;
  temperature?: number;
  max_tokens?: number;
}

export interface AIAgentResult {
  content: string;
  model: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  duration_ms?: number;
  endpoint?: string;
}

export interface GenerateInstructionsPayload {
  node_id: string;
  state: string;
  county: string;
  query_type: QueryType;
  url?: string;
  query_value?: string;
  playwright_notes?: string;
}

export interface GenerateInstructionsResult {
  instructions: string;
  layout_type: string;
  confidence: string;
  reasoning: string;
  resolved_url: string;
}

export async function generatePlaywrightInstructions(
  payload: GenerateInstructionsPayload
): Promise<GenerateInstructionsResult> {
  const res = await fetch(`${API_BASE}/pipeline/generate-instructions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Failed to generate Playwright instructions");
  }
  return res.json();
}

export async function getOpenAIStatus(): Promise<OpenAIConfigStatus> {
  const res = await fetch(`${API_BASE}/config/openai`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function testAIAgent(body: {
  config: AIAgentConfigPayload;
  context_data?: Record<string, unknown>;
}): Promise<AIAgentResult> {
  const res = await fetch(`${API_BASE}/ai-agent/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "AI agent test failed");
  }
  return res.json();
}

export async function executeRunAIAgent(
  runId: string,
  body: {
    canvas_id: string;
    config: AIAgentConfigPayload;
    context_data?: Record<string, unknown>;
  }
): Promise<AIAgentResult> {
  const res = await fetch(`${API_BASE}/runs/${runId}/ai-agent/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "AI agent execute failed");
  }
  return res.json();
}

export async function getCountiesForState(stateCode: string): Promise<CountyOption[]> {
  const res = await fetch(`${API_BASE}/locations/states/${stateCode}/counties`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createSearch(req: SearchRequest): Promise<{ run_id: string }> {
  const res = await fetch(`${API_BASE}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getRun(runId: string): Promise<RunDetail> {
  const res = await fetch(`${API_BASE}/runs/${runId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getReportByRun(runId: string): Promise<ReportData> {
  const res = await fetch(`${API_BASE}/reports/by-run/${runId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function getReportDownloadUrl(reportId: string): string {
  return `${API_BASE}/reports/${reportId}/download`;
}

export async function downloadReportPdf(reportId: string, runId: string): Promise<DownloadReportResult> {
  const res = await fetch(getReportDownloadUrl(reportId));
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Failed to download report PDF");
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `property_report_${runId}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);

  return {
    storageUrl: res.headers.get("X-PDF-Storage-Url"),
    storagePath: res.headers.get("X-PDF-Storage-Path"),
  };
}

export function getDocumentDownloadUrl(runId: string): string {
  return `${API_BASE}/reports/run/${runId}/document/download`;
}

export async function downloadOfficialDocument(runId: string, filename?: string): Promise<void> {
  const res = await fetch(getDocumentDownloadUrl(runId));
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Failed to download official document");
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename || `official_document_${runId}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function getWebSocketUrl(runId: string): string {
  const base = import.meta.env.VITE_WS_URL || "ws://localhost:8000";
  return `${base}/runs/${runId}/stream`;
}

export function getRunPreviewUrl(runId: string, cacheBust?: number): string {
  const t = cacheBust ?? Date.now();
  return `${API_BASE}/runs/${runId}/preview.png?t=${t}`;
}

export async function sendPreviewClick(runId: string, x: number, y: number): Promise<void> {
  const res = await fetch(`${API_BASE}/runs/${runId}/preview-click`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ x, y }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Preview click failed");
  }
}

// ---------------------------------------------------------------------------
// Multi-Order Batch Processing API
// ---------------------------------------------------------------------------

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  icon: string;
  steps: string[];
}

export interface BatchOrderItem {
  id: string;
  batch_id: string;
  order_index: number;
  run_id?: string | null;
  state: string;
  county: string;
  query_type: string;
  query_value: string;
  book_number?: string | null;
  page_number?: string | null;
  workflow_template?: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  error_message?: string | null;
  report_id?: string | null;
  created_at: string;
  completed_at?: string | null;
}

export interface BatchJob {
  id: string;
  name: string;
  status: "pending" | "running" | "completed" | "partially_failed" | "failed" | "cancelled";
  total_orders: number;
  completed_orders: number;
  failed_orders: number;
  running_orders: number;
  concurrency: number;
  workflow_template: string;
  created_at: string;
  completed_at?: string | null;
}

export interface BatchDetailResponse {
  batch: BatchJob;
  orders: BatchOrderItem[];
}

export interface CreateBatchPayload {
  name?: string;
  workflow_template?: string;
  concurrency?: number;
  orders: {
    state: string;
    county: string;
    query_type: string;
    query_value?: string;
    book_number?: string;
    page_number?: string;
    workflow_template?: string;
  }[];
  custom_graph?: PipelineGraph;
}

export async function getBatchTemplates(): Promise<WorkflowTemplate[]> {
  const res = await fetch(`${API_BASE}/batches/templates`);
  if (!res.ok) throw new Error("Failed to load workflow templates");
  return res.json();
}

export async function createBatch(payload: CreateBatchPayload): Promise<{ batch_id: string; name: string }> {
  const res = await fetch(`${API_BASE}/batches`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || "Failed to create batch job");
  }
  return res.json();
}

export async function parseBatchCsv(file: File): Promise<{ total_detected: number; orders: any[] }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/batches/parse-csv`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || "Failed to parse CSV file");
  }
  return res.json();
}

export async function listBatches(): Promise<BatchJob[]> {
  const res = await fetch(`${API_BASE}/batches`);
  if (!res.ok) throw new Error("Failed to load batches");
  return res.json();
}

export async function getBatch(batchId: string): Promise<BatchDetailResponse> {
  const res = await fetch(`${API_BASE}/batches/${batchId}`);
  if (!res.ok) throw new Error("Failed to load batch details");
  return res.json();
}

export async function cancelBatch(batchId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/batches/${batchId}/cancel`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to cancel batch");
}

export async function retryBatch(batchId: string): Promise<{ retried_orders: number }> {
  const res = await fetch(`${API_BASE}/batches/${batchId}/retry`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to retry batch");
  return res.json();
}

export function getBatchExportUrl(batchId: string): string {
  return `${API_BASE}/batches/${batchId}/export`;
}
