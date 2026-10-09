import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  DocumentDetail,
  RecordingDetails,
  analyzeDocumentOcr,
  getDocumentById,
  getDocumentFileUrl,
  getReportByRun,
} from "../api/client";

type ViewMode = "split" | "document" | "details";

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  return new Date(parsed).toLocaleDateString("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  });
}

function DetailRow({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return (
    <div className="grid grid-cols-[120px_1fr] gap-3 py-2 border-b border-slate-100 dark:border-white/[0.06] text-sm">
      <div className="text-slate-500 dark:text-zinc-400">{label}</div>
      <div className="text-slate-900 dark:text-zinc-100 font-medium break-words">{value}</div>
    </div>
  );
}

function PartyPills({ title, names }: { title: string; names: string[] }) {
  if (!names.length) return null;
  return (
    <div className="mt-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-zinc-400 mb-2">
        {title}
      </div>
      <div className="flex flex-wrap gap-2">
        {names.map((name) => (
          <span
            key={name}
            className="inline-flex px-2.5 py-1 rounded-md bg-slate-100 dark:bg-zinc-800 text-slate-800 dark:text-zinc-200 text-xs font-medium border border-slate-200 dark:border-white/[0.08]"
          >
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}

function SectionTitle({ title }: { title: string }) {
  return (
    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-zinc-400 mb-2 mt-6 first:mt-0">
      {title}
    </div>
  );
}

function formatOcrError(message: string): string {
  if (/rate limit|rate_limited|\b429\b/i.test(message)) {
    return "OCR rate limit reached. Recorder metadata is shown instead. Wait a moment, then click Re-analyze.";
  }
  return message;
}

function recorderViewerUsesGptOcr(ocr: Record<string, unknown> | undefined): boolean {
  return Boolean(ocr?.gpt_analyzed);
}

function isRecentRateLimit(ocr: Record<string, unknown> | undefined): boolean {
  const stamp = ocr?.rate_limited_at;
  if (typeof stamp !== "string" || !stamp) return false;
  const when = Date.parse(stamp);
  if (Number.isNaN(when)) return false;
  return Date.now() - when < 120_000;
}

const RECORDING_SCALAR_FIELDS = [
  "document_type",
  "recorded_date",
  "executed_date",
  "book",
  "page",
  "book_page",
  "instrument_number",
  "clerk_file_number",
  "grantor",
  "grantee",
  "consideration",
  "sale_price",
  "conveyance",
  "warranty",
  "documentary_stamps",
  "recording_fee",
  "deed_doc_fee",
  "parcel_id",
  "folio_number",
  "order_number",
  "prepared_by",
  "pages",
  "marital_status",
  "first_party",
  "second_party",
  "attorney",
  "legal_description",
  "property_address",
] as const;

const RECORDING_LIST_FIELDS = [
  "grantors",
  "grantees",
  "beneficiaries",
  "borrowers",
] as const;

function readStringField(source: Record<string, unknown>, key: string): string | undefined {
  const value = source[key];
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function readStringList(source: Record<string, unknown>, key: string): string[] {
  const value = source[key];
  if (!Array.isArray(value)) return [];
  return [...new Set(value.map((item) => String(item).trim()).filter(Boolean))];
}

function mergeRecordingDetails(doc: DocumentDetail | null): RecordingDetails {
  const ocr = (doc?.ocr_json || {}) as Record<string, unknown>;
  const nested = (ocr.recording_details || {}) as RecordingDetails;
  const fromDoc = (doc?.recording_details || {}) as RecordingDetails;
  const merged: RecordingDetails = { ...nested, ...fromDoc };

  for (const key of RECORDING_SCALAR_FIELDS) {
    const value = readStringField(ocr, key) || readStringField(nested as Record<string, unknown>, key);
    if (value) {
      merged[key] = value;
    }
  }

  for (const key of RECORDING_LIST_FIELDS) {
    const values = [
      ...readStringList(ocr, key),
      ...readStringList(nested as Record<string, unknown>, key),
      ...readStringList(fromDoc as Record<string, unknown>, key),
    ];
    if (values.length) {
      merged[key] = [...new Set(values)];
    }
  }

  const ocrAnalyzed = Boolean(ocr.gpt_analyzed || ocr.mistral_analyzed);

  merged.document_type = doc?.document_type || merged.document_type;
  merged.recorded_date =
    doc?.recording_date ||
    merged.recorded_date ||
    readStringField(ocr, "recording_date");
  merged.book_page = doc?.book_page || merged.book_page || readStringField(ocr, "book_page");
  merged.instrument_number =
    doc?.instrument_number ||
    merged.instrument_number ||
    merged.clerk_file_number ||
    readStringField(ocr, "clerk_file_number") ||
    readStringField(ocr, "instrument_number");

  if (!ocrAnalyzed) {
    merged.grantor = doc?.grantor || merged.grantor;
    merged.grantee = doc?.grantee || merged.grantee;
  } else if (!merged.grantor && merged.grantors?.length) {
    merged.grantor = merged.grantors[0];
  } else if (!merged.grantee && merged.grantees?.length) {
    merged.grantee = merged.grantees[0];
  }

  if (!merged.consideration && merged.sale_price) {
    merged.consideration = merged.sale_price;
  }

  return merged;
}

export default function DocumentViewer() {
  const { runId, docId } = useParams<{ runId: string; docId: string }>();
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [county, setCounty] = useState<string>("");
  const [state, setState] = useState<string>("FL");
  const [loading, setLoading] = useState(true);
  const [ocrLoading, setOcrLoading] = useState(false);
  const [ocrError, setOcrError] = useState<string | null>(null);
  const [ocrWarning, setOcrWarning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("split");
  const [zoom, setZoom] = useState(100);
  const [showPreviewImage, setShowPreviewImage] = useState(false);

  useEffect(() => {
    if (!docId || !runId) return;
    let cancelled = false;

    async function loadDocument() {
      setLoading(true);
      setError(null);
      setOcrError(null);
      setOcrWarning(null);

      try {
        const [document, report] = await Promise.all([getDocumentById(docId), getReportByRun(runId)]);
        if (cancelled) return;

        setDoc(document);
        setCounty(String(report.report_json?.county || ""));
        setState(String(report.report_json?.state || "FL"));

        const ocrJson = (document.ocr_json || {}) as Record<string, unknown>;

        if (document.ocr_warning) {
          setOcrWarning(document.ocr_warning);
        } else if (document.ocr_status === "fallback" && !recorderViewerUsesGptOcr(ocrJson)) {
          setOcrWarning(
            "Showing recorder metadata while GPT OCR is unavailable. Click Re-analyze to retry full OCR.",
          );
        }

        const needsGptOcr = !recorderViewerUsesGptOcr(ocrJson) && !isRecentRateLimit(ocrJson);

        if (needsGptOcr) {
          setOcrLoading(true);
          try {
            const analyzed = await analyzeDocumentOcr(docId, false, "gpt");
            if (!cancelled) {
              setDoc(analyzed);
              setOcrWarning(analyzed.ocr_warning || null);
              if (analyzed.ocr_status === "fallback" && !recorderViewerUsesGptOcr(analyzed.ocr_json)) {
                setOcrWarning(
                  analyzed.ocr_warning ||
                    "GPT OCR could not analyze this document. Showing recorder metadata instead.",
                );
              }
            }
          } catch (ocrErr) {
            if (!cancelled) {
              const message = ocrErr instanceof Error ? ocrErr.message : "OCR analysis failed";
              setOcrError(formatOcrError(message));
            }
          } finally {
            if (!cancelled) {
              setOcrLoading(false);
            }
          }
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load document");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadDocument();
    return () => {
      cancelled = true;
    };
  }, [docId, runId]);

  const details = useMemo(() => mergeRecordingDetails(doc), [doc]);

  const partyNames = useMemo(() => {
    const ocr = doc?.ocr_json || {};
    const names = [
      ...(Array.isArray(ocr.party_names) ? ocr.party_names : []),
      ...(Array.isArray(ocr.name_search_names) ? ocr.name_search_names : []),
    ];
    return [...new Set(names.map((name) => String(name).trim()).filter(Boolean))];
  }, [doc]);

  const ocrAnalyzed = useMemo(
    () => Boolean(doc?.ocr_json?.gpt_analyzed || doc?.ocr_json?.mistral_analyzed),
    [doc],
  );

  const grantors = useMemo(() => {
    const names = [
      ...(details.grantors || []),
      ...(details.grantor ? [details.grantor] : []),
      ...(!ocrAnalyzed && doc?.grantor ? [doc.grantor] : []),
    ];
    return [...new Set(names.map((name) => name.trim()).filter(Boolean))];
  }, [details, doc, ocrAnalyzed]);

  const grantees = useMemo(() => {
    const names = [
      ...(details.grantees || []),
      ...(details.grantee ? [details.grantee] : []),
      ...(!ocrAnalyzed && doc?.grantee ? [doc.grantee] : []),
    ];
    return [...new Set(names.map((name) => name.trim()).filter(Boolean))];
  }, [details, doc, ocrAnalyzed]);

  const beneficiaries = useMemo(
    () => [...new Set((details.beneficiaries || []).map((name) => name.trim()).filter(Boolean))],
    [details],
  );

  const borrowers = useMemo(
    () => [...new Set((details.borrowers || []).map((name) => name.trim()).filter(Boolean))],
    [details],
  );

  const pdfUrl = docId ? getDocumentFileUrl(docId, true) : null;
  const previewSrc = doc?.preview_url || null;
  const isPdf = Boolean(pdfUrl && !showPreviewImage);

  async function retryOcr() {
    if (!docId) return;
    setOcrLoading(true);
    setOcrError(null);
    setOcrWarning(null);
    try {
      const analyzed = await analyzeDocumentOcr(docId, true, "gpt");
      setDoc(analyzed);
      if (analyzed.ocr_warning || (analyzed.ocr_status === "fallback" && !recorderViewerUsesGptOcr(analyzed.ocr_json))) {
        setOcrWarning(
          analyzed.ocr_warning ||
            "GPT OCR could not analyze this document. Showing recorder metadata instead.",
        );
      }
    } catch (ocrErr) {
      const message = ocrErr instanceof Error ? ocrErr.message : "OCR analysis failed";
      setOcrError(formatOcrError(message));
    } finally {
      setOcrLoading(false);
    }
  }

  if (loading) {
    return <div className="p-8 text-slate-500">Loading document...</div>;
  }

  if (error || !doc) {
    return (
      <div className="p-8">
        <Link to={`/reports/run/${runId}`} className="text-sm text-violet-600 dark:text-violet-400 hover:underline">
          ← Back to Report
        </Link>
        <p className="mt-4 text-red-600">{error || "Document not found"}</p>
      </div>
    );
  }

  const countyLabel = county ? `${county.replace(/-/g, " ")} County, ${state}` : state;

  return (
    <div className="min-h-[calc(100vh-64px)] flex flex-col bg-slate-100 dark:bg-[#0d1117]">
      <div className="border-b border-slate-200 dark:border-white/[0.08] bg-white dark:bg-[#161b22] px-4 py-3">
        <div className="max-w-[1600px] mx-auto flex flex-wrap items-center justify-between gap-3">
          <div>
            <Link
              to={`/reports/run/${runId}`}
              className="text-xs text-violet-600 dark:text-violet-400 hover:underline"
            >
              ← Back
            </Link>
            <h1 className="text-lg font-bold text-slate-900 dark:text-zinc-100 mt-1">
              {details.document_type || doc.document_type || "Recorded Document"}
            </h1>
            <p className="text-xs text-slate-500 dark:text-zinc-400 mt-0.5">
              Chain Of Title • {details.book_page || doc.book_page || "—"} • Inst#{" "}
              {details.instrument_number || doc.instrument_number || "—"} • {countyLabel}
            </p>
          </div>

          <div className="flex items-center gap-2">
            {(["split", "document", "details"] as ViewMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setViewMode(mode)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold capitalize transition-colors ${
                  viewMode === mode
                    ? "bg-slate-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                    : "bg-slate-100 text-slate-600 dark:bg-zinc-800 dark:text-zinc-300"
                }`}
              >
                {mode}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 max-w-[1600px] mx-auto w-full p-4 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px] gap-4 min-h-0">
        {(viewMode === "split" || viewMode === "document") && (
          <div className="flex flex-col min-h-[70vh] rounded-xl border border-slate-200 dark:border-white/[0.08] bg-white dark:bg-[#161b22] overflow-hidden">
            <div className="flex items-center justify-between gap-3 px-4 py-2 border-b border-slate-200 dark:border-white/[0.08] bg-slate-50 dark:bg-zinc-900/60">
              <div className="flex items-center gap-2 text-xs text-slate-600 dark:text-zinc-300">
                <span className="font-semibold">1 page</span>
                <button
                  type="button"
                  onClick={() => setZoom((z) => Math.max(50, z - 10))}
                  className="px-2 py-1 rounded border border-slate-200 dark:border-white/[0.08]"
                >
                  −
                </button>
                <span className="min-w-[48px] text-center">{zoom}%</span>
                <button
                  type="button"
                  onClick={() => setZoom((z) => Math.min(200, z + 10))}
                  className="px-2 py-1 rounded border border-slate-200 dark:border-white/[0.08]"
                >
                  +
                </button>
              </div>
              <div className="flex items-center gap-2">
                {doc.preview_url && (
                  <button
                    type="button"
                    onClick={() => setShowPreviewImage((v) => !v)}
                    className={`px-2.5 py-1 rounded text-xs font-semibold border ${
                      showPreviewImage
                        ? "bg-teal-600 text-white border-teal-600"
                        : "border-slate-200 dark:border-white/[0.08] text-slate-600 dark:text-zinc-300"
                    }`}
                  >
                    Snapshot
                  </button>
                )}
                {docId && (
                  <a
                    href={getDocumentFileUrl(docId, false)}
                    className="px-2.5 py-1 rounded text-xs font-semibold text-teal-700 dark:text-teal-300 hover:underline"
                  >
                    Download
                  </a>
                )}
              </div>
            </div>

            <div className="flex-1 overflow-auto bg-slate-200/60 dark:bg-zinc-950 p-4">
              {showPreviewImage && previewSrc ? (
                <img
                  src={previewSrc}
                  alt={doc.document_type || "Document preview"}
                  className="mx-auto max-w-full h-auto shadow-lg bg-white"
                  style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }}
                />
              ) : isPdf && pdfUrl ? (
                <object
                  data={pdfUrl}
                  type="application/pdf"
                  className="w-full bg-white shadow-lg"
                  style={{
                    height: `${Math.max(720, 900 * (zoom / 100))}px`,
                  }}
                >
                  <iframe
                    title={doc.document_type || "Document"}
                    src={pdfUrl}
                    className="w-full h-full bg-white"
                  />
                </object>
              ) : previewSrc ? (
                <img
                  src={previewSrc}
                  alt={doc.document_type || "Document preview"}
                  className="mx-auto max-w-full h-auto shadow-lg bg-white"
                  style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }}
                />
              ) : (
                <div className="h-full min-h-[480px] flex items-center justify-center text-slate-500 dark:text-zinc-400 text-sm">
                  Document preview is not available for this file.
                </div>
              )}
            </div>
          </div>
        )}

        {(viewMode === "split" || viewMode === "details") && (
          <div className="rounded-xl border border-slate-200 dark:border-white/[0.08] bg-white dark:bg-[#161b22] overflow-y-auto max-h-[85vh]">
            <div className="p-4 border-b border-slate-200 dark:border-white/[0.08] flex items-center justify-between gap-3">
              <h2 className="text-sm font-bold text-slate-900 dark:text-zinc-100">Recording Details</h2>
              {ocrLoading ? (
                <span className="text-xs text-teal-600 dark:text-teal-400">Analyzing...</span>
              ) : (
                <button
                  type="button"
                  onClick={retryOcr}
                  className="text-xs font-semibold text-violet-600 dark:text-violet-400 hover:underline"
                >
                  Re-analyze
                </button>
              )}
            </div>
            <div className="p-4">
              {ocrLoading && (
                <div className="mb-4 rounded-lg border border-teal-200 dark:border-teal-900/40 bg-teal-50 dark:bg-teal-950/20 px-3 py-2 text-xs text-teal-700 dark:text-teal-300">
                  Running GPT OCR on this recorder document...
                </div>
              )}
              {ocrWarning && (
                <div className="mb-4 rounded-lg border border-amber-200 dark:border-amber-900/40 bg-amber-50 dark:bg-amber-950/20 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
                  {ocrWarning}
                </div>
              )}
              {ocrError && (
                <div className="mb-4 rounded-lg border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-950/20 px-3 py-2 text-xs text-red-700 dark:text-red-300">
                  {ocrError}
                </div>
              )}

              <SectionTitle title="Recording Details" />
              <DetailRow label="Recorded" value={formatDate(details.recorded_date)} />
              <DetailRow label="Executed" value={formatDate(details.executed_date) || details.executed_date} />
              <DetailRow label="Book / Page" value={details.book_page} />
              <DetailRow label="Instrument #" value={details.instrument_number || details.clerk_file_number} />
              <DetailRow label="Pages" value={details.pages} />
              <DetailRow label="Document Type" value={details.document_type || doc.document_type} />
              <DetailRow label="County" value={countyLabel} />

              <SectionTitle title="Parties" />
              <PartyPills title="Grantors" names={grantors} />
              <PartyPills title="Grantees" names={grantees} />
              <PartyPills title="Beneficiaries" names={beneficiaries} />
              <PartyPills title="Borrowers" names={borrowers} />
              <DetailRow label="First Party" value={details.first_party} />
              <DetailRow label="Second Party" value={details.second_party} />
              <DetailRow label="Attorney" value={details.attorney} />
              {partyNames.length > 0 && <PartyPills title="Parties" names={partyNames} />}

              <SectionTitle title="Transaction" />
              <DetailRow label="Conveyance" value={details.conveyance} />
              <DetailRow label="Warranty" value={details.warranty} />
              <DetailRow label="Consideration" value={details.consideration} />
              <DetailRow label="Sale Price" value={details.sale_price} />
              <DetailRow label="Documentary Stamps" value={details.documentary_stamps} />
              <DetailRow label="Recording Fee" value={details.recording_fee || details.deed_doc_fee} />
              <DetailRow label="Order #" value={details.order_number} />
              <DetailRow label="Prepared By" value={details.prepared_by} />

              <SectionTitle title="Legal & Property" />
              <DetailRow label="Marital Status" value={details.marital_status} />
              <DetailRow label="Legal Description" value={details.legal_description} />
              <DetailRow label="Property Address" value={details.property_address} />
              <DetailRow label="Parcel / Folio" value={details.parcel_id || details.folio_number} />

              {doc.file_name && (
                <div className="mt-6 pt-4 border-t border-slate-100 dark:border-white/[0.06] text-xs text-slate-500 dark:text-zinc-400">
                  File: <span className="font-mono text-slate-700 dark:text-zinc-300">{doc.file_name}</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
