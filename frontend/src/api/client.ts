const API_BASE = import.meta.env.VITE_API_URL || "";

export type QueryType = "owner" | "parcel" | "address";

export interface SearchRequest {
  state: string;
  county: string;
  query_type: QueryType;
  query_value: string;
}

export interface RunEvent {
  id?: string;
  run_id: string;
  event_type: string;
  source?: string;
  payload?: {
    message?: string;
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
    property?: Record<string, unknown>;
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

export function getWebSocketUrl(runId: string): string {
  const base = import.meta.env.VITE_WS_URL || "ws://localhost:8000";
  return `${base}/runs/${runId}/stream`;
}
