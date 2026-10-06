import React from "react";
import { Link } from "react-router-dom";
import { downloadOfficialDocument, getDocumentFileUrl } from "../api/client";

interface Document {
  id?: string;
  document_type?: string;
  recording_date?: string;
  book_page?: string;
  instrument_number?: string;
  grantor?: string;
  grantee?: string;
  property_address?: string;
  source_url?: string;
  screenshot_path?: string;
  file_name?: string;
  folder_name?: string;
  image_data_uri?: string;
  notes?: string;
  ocr_json?: {
    sale_price?: string;
    source?: string;
    section?: string;
    download_path?: string;
    folder_name?: string;
    file_name?: string;
    folder?: string;
    image_path?: string;
    book_number?: string;
    page_number?: string;
    model?: string;
    ai_response?: string;
    agent_name?: string;
    tokens?: number;
    prompt_tokens?: number;
    completion_tokens?: number;
    duration_ms?: number;
    searched_name?: string;
    property_address?: string;
    address?: string;
    party_name?: string;
    card_index?: string;
  };
}

export interface NameSearchGroup {
  name: string;
  documents: Document[];
  document_count?: number;
}

interface Props {
  documents: Document[];
  runId?: string;
  nameSearchGroups?: NameSearchGroup[];
}

type DocumentCategory = "assessor" | "recorder" | "ai" | "other";

function getDocumentCategory(doc: Document): DocumentCategory {
  const source = doc.ocr_json?.source;
  if (source === "ai_agent" || doc.document_type === "AI Title Analysis") return "ai";
  if (source === "assessor" || source === "assessor_sales") return "assessor";
  const folderName = doc.folder_name || doc.ocr_json?.folder_name || "";
  if (
    source === "name_searcher" ||
    folderName.startsWith("name_search_") ||
    folderName.startsWith("name_search/")
  ) {
    return "recorder";
  }
  if (
    source === "recorder" ||
    !source ||
    doc.folder_name?.startsWith("recorder_") ||
    doc.ocr_json?.folder_name?.startsWith("recorder_")
  ) {
    return "recorder";
  }
  return "other";
}

function sourceLabel(doc: Document): string {
  const source = doc.ocr_json?.source;
  if (source === "ai_agent") return "OpenAI Agent";
  if (source === "assessor_sales") return "Assessor Sales";
  if (source === "assessor") return "Assessor";
  if (source === "name_searcher") {
    const searchedName = doc.ocr_json?.searched_name;
    if (searchedName && isBookPageLabel(String(searchedName))) return "Recorder";
    return "Name Search";
  }
  if (source) return String(source);
  return "Recorder";
}

function getSearchedName(doc: Document): string | null {
  const name = doc.ocr_json?.searched_name;
  return name ? String(name).trim() : null;
}

function isBookPageLabel(value: string): boolean {
  return /^\s*\d+\s*[/-]\s*\d+\s*$/i.test(value.trim());
}

function isPrimaryRecorderDocument(doc: Document): boolean {
  const source = doc.ocr_json?.source;
  if (source === "assessor" || source === "assessor_sales" || source === "ai_agent") return false;
  if (getDocumentCategory(doc) !== "recorder") return false;
  const searchedName = getSearchedName(doc);
  if (!searchedName) return true;
  return isBookPageLabel(searchedName);
}

function getPrimaryRecorderDocuments(
  documents: Document[],
  options?: {
    providedPrimary?: Document[];
    nameSearchGroups?: NameSearchGroup[];
  },
): Document[] {
  const seen = new Set<string>();
  const primary: Document[] = [];

  const add = (doc: Document) => {
    const ocr = doc.ocr_json || {};
    const key =
      doc.id ||
      [
        doc.book_page || "",
        doc.instrument_number || "",
        doc.document_type || "",
        doc.grantor || "",
        doc.grantee || "",
        ocr.party_name || "",
        ocr.property_address || "",
        ocr.searched_name || "",
        ocr.card_index || "",
      ].join("|");
    if (seen.has(key)) return;
    seen.add(key);
    primary.push(doc);
  };

  for (const doc of options?.providedPrimary || []) {
    if (isPrimaryRecorderDocument(doc)) add(doc);
  }
  for (const doc of documents) {
    if (isPrimaryRecorderDocument(doc)) add(doc);
  }
  for (const group of options?.nameSearchGroups || []) {
    if (isBookPageLabel(group.name)) {
      for (const doc of group.documents || []) {
        if (isPrimaryRecorderDocument(doc)) add(doc);
      }
    }
  }

  return primary;
}

function buildNameSearchGroups(
  documents: Document[],
  providedGroups?: NameSearchGroup[],
): NameSearchGroup[] {
  const isNameSearchDocument = (doc: Document) => {
    const searchedName = getSearchedName(doc);
    return Boolean(searchedName && !isBookPageLabel(searchedName));
  };

  if (providedGroups?.length) {
    return providedGroups
      .filter((group) => group.name && !isBookPageLabel(group.name))
      .map((group) => ({
        name: group.name,
        documents: (group.documents || []).filter(isNameSearchDocument),
        document_count: group.document_count ?? (group.documents || []).length,
      }))
      .filter((group) => group.documents.length > 0);
  }

  const order: string[] = [];
  const grouped = new Map<string, Document[]>();
  for (const doc of documents) {
    const searchedName = getSearchedName(doc);
    if (!searchedName || isBookPageLabel(searchedName)) continue;
    if (!grouped.has(searchedName)) {
      grouped.set(searchedName, []);
      order.push(searchedName);
    }
    grouped.get(searchedName)!.push(doc);
  }

  return order.map((name) => ({
    name,
    documents: grouped.get(name) || [],
    document_count: (grouped.get(name) || []).length,
  }));
}

function resolvePreviewUrl(doc: Document): string | null {
  const ocr = doc.ocr_json || {};
  if (doc.image_data_uri) return doc.image_data_uri;

  const filePath = String(ocr.download_path || doc.screenshot_path || "");
  if (filePath) {
    const normalized = filePath.replace(/\\/g, "/");
    if (normalized.toLowerCase().endsWith(".pdf")) {
      const pngPath = normalized.replace(/\.pdf$/i, ".png");
      const storageIdx = pngPath.indexOf("local_storage/");
      if (storageIdx >= 0) return `/${pngPath.slice(storageIdx)}`;
    }
  }

  if (ocr.image_path) {
    const normalized = String(ocr.image_path).replace(/\\/g, "/");
    const storageIdx = normalized.indexOf("local_storage/");
    if (storageIdx >= 0) return `/${normalized.slice(storageIdx)}`;
  }

  if (doc.id) return getDocumentFileUrl(doc.id, true);
  return null;
}

function hasDownloadablePdf(doc: Document): boolean {
  const ocr = doc.ocr_json || {};
  if (ocr.source === "assessor_sales") return false;
  const path = doc.screenshot_path || ocr.download_path || "";
  if (path.toLowerCase().endsWith(".pdf")) return true;
  if (ocr.source === "assessor" && (ocr.file_name || doc.file_name)) return true;
  const folderName = doc.folder_name || ocr.folder_name || "";
  if (folderName.startsWith("recorder_")) return true;
  if (folderName.startsWith("name_search_") || folderName.startsWith("name_search/")) return true;
  return Boolean(doc.file_name && doc.file_name.endsWith(".pdf"));
}

function resolveFolderAndFile(doc: Document): { folderName: string | null; fileName: string } {
  const ocr = doc.ocr_json || {};
  const searchedName = ocr.searched_name ? String(ocr.searched_name).trim() : "";
  const nameSlug = searchedName
    ? searchedName.replace(/[^\w]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48)
    : "";
  const folderName =
    doc.folder_name ||
    ocr.folder_name ||
    (ocr.source === "assessor"
      ? null
      : ocr.book_number && ocr.page_number
        ? searchedName
          ? `name_search/${nameSlug}/${ocr.book_number}_${ocr.page_number}`
          : `recorder_${ocr.book_number}_${ocr.page_number}`
        : null);
  const fileName =
    doc.file_name ||
    ocr.file_name ||
    (ocr.download_path ? ocr.download_path.split(/[\\/]/).pop() : null) ||
    (folderName && ocr.source !== "assessor" ? `${folderName}.pdf` : null) ||
    "recorder_document.pdf";
  return { folderName, fileName };
}

function getDocumentAddress(doc: Document): string {
  const ocr = doc.ocr_json || {};
  return (
    doc.property_address ||
    ocr.property_address ||
    ocr.address ||
    ""
  ).trim();
}

function DocumentTable({
  documents,
  runId,
  onDownload,
  downloading,
}: {
  documents: Document[];
  runId?: string;
  onDownload: (filename?: string) => void;
  downloading: boolean;
}) {
  if (!documents.length) {
    return (
      <p className="text-sm text-slate-500 dark:text-zinc-400 italic py-2">No entries in this section.</p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-white/[0.08]">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-100 dark:bg-zinc-900 border-b border-slate-200 dark:border-white/[0.08] text-left text-slate-800 dark:text-zinc-200 font-semibold">
            <th className="py-2.5 px-3">Type</th>
            <th className="py-2.5 px-3">Date</th>
            <th className="py-2.5 px-3">Book / Page</th>
            <th className="py-2.5 px-3">Instrument #</th>
            <th className="py-2.5 px-3">Grantor</th>
            <th className="py-2.5 px-3">Grantee</th>
            <th className="py-2.5 px-3">Address</th>
            <th className="py-2.5 px-3">Source</th>
            <th className="py-2.5 px-3">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-white/[0.05] bg-white dark:bg-[#161b22]">
          {documents.map((doc, i) => {
            const ocr = doc.ocr_json || {};
            const bp =
              doc.book_page ||
              (ocr.book_number && ocr.page_number ? `${ocr.book_number}/${ocr.page_number}` : "—");
            const address = getDocumentAddress(doc);
            const { fileName } = resolveFolderAndFile(doc);
            return (
              <tr key={doc.id || i} className="hover:bg-slate-50/70 dark:hover:bg-zinc-800/30 transition-colors">
                <td className="py-2.5 px-3 font-semibold text-slate-900 dark:text-zinc-100">
                  {doc.document_type || "—"}
                </td>
                <td className="py-2.5 px-3 text-slate-700 dark:text-zinc-300">{doc.recording_date || "—"}</td>
                <td className="py-2.5 px-3 font-mono text-slate-700 dark:text-zinc-300">{bp}</td>
                <td className="py-2.5 px-3 font-mono text-xs text-slate-800 dark:text-zinc-200">
                  {doc.instrument_number || "—"}
                </td>
                <td className="py-2.5 px-3 text-slate-800 dark:text-zinc-200">{doc.grantor || "—"}</td>
                <td className="py-2.5 px-3 text-slate-800 dark:text-zinc-200">{doc.grantee || "—"}</td>
                <td
                  className={`py-2.5 px-3 text-xs ${
                    address
                      ? "font-semibold text-emerald-700 dark:text-emerald-300"
                      : "text-slate-400 dark:text-zinc-500"
                  }`}
                >
                  {address || "—"}
                </td>
                <td className="py-2.5 px-3 text-xs text-slate-500 dark:text-zinc-400">{sourceLabel(doc)}</td>
                <td className="py-2.5 px-3">
                  {hasDownloadablePdf(doc) && runId ? (
                    <div className="flex items-center gap-3">
                      {doc.id && (
                        <Link
                          to={`/reports/run/${runId}/documents/${doc.id}`}
                          className="text-violet-600 dark:text-violet-400 hover:underline text-xs font-semibold"
                        >
                          View
                        </Link>
                      )}
                      <button
                        type="button"
                        onClick={() => onDownload(fileName)}
                        disabled={downloading}
                        className="text-teal-600 dark:text-teal-400 hover:underline text-xs font-semibold disabled:opacity-50"
                      >
                        Download
                      </button>
                    </div>
                  ) : doc.source_url ? (
                    <a
                      href={doc.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 dark:text-blue-400 hover:underline text-xs font-semibold"
                    >
                      Open
                    </a>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function OfficialDocumentCard({
  doc,
  idx,
  runId,
  downloading,
  onDownload,
  accent,
}: {
  doc: Document;
  idx: number;
  runId?: string;
  downloading: boolean;
  onDownload: (filename?: string) => void;
  accent: "assessor" | "recorder";
}) {
  const ocr = doc.ocr_json || {};
  const { folderName, fileName } = resolveFolderAndFile(doc);
  const previewUrl = resolvePreviewUrl(doc);
  const pdfUrl = doc.id ? getDocumentFileUrl(doc.id, true) : null;

  const badgeClass =
    accent === "assessor"
      ? "bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/40"
      : "bg-blue-100 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800/40";

  const cardClass =
    accent === "assessor"
      ? "bg-emerald-50/50 dark:bg-emerald-950/15 border-emerald-200 dark:border-emerald-900/40"
      : "bg-slate-50/80 dark:bg-zinc-900/60 border-slate-200 dark:border-white/[0.08]";

  return (
    <div key={doc.id || idx} className={`mt-4 p-5 rounded-xl border ${cardClass}`}>
      <div className="flex flex-wrap items-center justify-between gap-4 pb-3 border-b border-slate-200/80 dark:border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold border ${badgeClass}`}>
              {accent === "assessor" ? "Assessor Report" : "Official Copy"}
            </span>
            <span className="text-xs text-slate-500 dark:text-zinc-400 font-mono">
              {accent === "assessor" ? `Folio: ${doc.instrument_number || "—"}` : `CFN: ${doc.instrument_number || "—"}`}
            </span>
          </div>
          <h4 className="text-sm font-bold text-slate-900 dark:text-zinc-100 mt-1">
            {doc.document_type || (accent === "assessor" ? "Assessor Document" : "Recorded Document")}
          </h4>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-zinc-400 mt-1">
            {folderName && (
              <span>
                Folder:{" "}
                <code className="bg-slate-200 dark:bg-zinc-800 text-slate-800 dark:text-zinc-200 px-1.5 py-0.5 rounded text-[11px] font-mono">
                  {folderName}
                </code>
              </span>
            )}
            {fileName && (
              <span>
                File: <strong className="text-slate-900 dark:text-zinc-100 font-semibold">{fileName}</strong>
              </span>
            )}
            {doc.book_page && (
              <span>
                Book/Page: <strong className="text-slate-900 dark:text-zinc-100 font-semibold">{doc.book_page}</strong>
              </span>
            )}
            {doc.recording_date && (
              <span>
                Recorded: <strong className="text-slate-900 dark:text-zinc-100 font-semibold">{doc.recording_date}</strong>
              </span>
            )}
          </div>
        </div>

        {runId && (
          <div className="flex items-center gap-2">
            {doc.id && (
              <Link
                to={`/reports/run/${runId}/documents/${doc.id}`}
                className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-700 text-white text-xs font-semibold shadow-sm transition-all"
              >
                View Document
              </Link>
            )}
            <button
              type="button"
              onClick={() => onDownload(fileName)}
              disabled={downloading}
              className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-xs font-semibold shadow-sm transition-all disabled:opacity-50"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download PDF
            </button>
          </div>
        )}
      </div>

      {(previewUrl || pdfUrl) && (
        <div className="mt-4">
          <div className="flex items-center justify-between text-xs text-slate-500 dark:text-zinc-400 mb-2">
            <span className="font-semibold">Document Preview</span>
            {doc.id && runId && (
              <Link
                to={`/reports/run/${runId}/documents/${doc.id}`}
                className="text-teal-600 dark:text-teal-400 font-semibold hover:underline"
              >
                Open Full Viewer ↗
              </Link>
            )}
          </div>
          <div className="border border-slate-300 dark:border-white/[0.1] rounded-lg overflow-hidden bg-white dark:bg-zinc-950 shadow-inner max-h-[520px] overflow-y-auto">
            {pdfUrl && accent === "assessor" ? (
              <iframe
                title={doc.document_type || "Assessor document"}
                src={pdfUrl}
                className="w-full h-[480px] bg-white"
              />
            ) : previewUrl ? (
              <img
                src={previewUrl}
                alt={doc.document_type || "Document preview"}
                className="w-full h-auto object-top display-block"
                onError={(e) => {
                  const target = e.target as HTMLImageElement;
                  if (pdfUrl && target.parentElement) {
                    target.style.display = "none";
                    const iframe = document.createElement("iframe");
                    iframe.src = pdfUrl;
                    iframe.title = doc.document_type || "Document";
                    iframe.className = "w-full h-[480px] bg-white";
                    target.parentElement.appendChild(iframe);
                  } else {
                    target.style.display = "none";
                  }
                }}
              />
            ) : pdfUrl ? (
              <iframe
                title={doc.document_type || "Document"}
                src={pdfUrl}
                className="w-full h-[480px] bg-white"
              />
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

function AiDocumentCard({ doc, idx }: { doc: Document; idx: number }) {
  const ocr = doc.ocr_json || {};
  const content = doc.notes || ocr.ai_response || "";
  return (
    <div key={doc.id || idx} className="mt-4 p-5 rounded-xl bg-purple-50/50 dark:bg-purple-950/20 border border-purple-200 dark:border-purple-800/40">
      <div className="flex flex-wrap items-center justify-between gap-4 pb-3 border-b border-purple-200/80 dark:border-purple-800/40">
        <div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-purple-100 dark:bg-purple-900/60 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-700/50">
              AI Document Analysis
            </span>
            <span className="text-xs text-purple-700/70 dark:text-purple-400 font-mono">
              CFN: {doc.instrument_number || "—"}
            </span>
          </div>
          <h4 className="text-sm font-bold text-slate-900 dark:text-zinc-100 mt-1">
            {doc.document_type || "AI Title Analysis"}
          </h4>
        </div>
      </div>
      <div className="mt-4 p-4 rounded-lg bg-white dark:bg-[#0d1117] border border-purple-100 dark:border-purple-900/40 text-xs sm:text-sm text-slate-800 dark:text-zinc-200 whitespace-pre-wrap font-sans leading-relaxed shadow-sm">
        {content}
      </div>
    </div>
  );
}

function DocumentSection({
  title,
  description,
  documents,
  cardDocuments,
  runId,
  downloading,
  onDownload,
  accent,
}: {
  title: string;
  description: string;
  documents: Document[];
  cardDocuments: Document[];
  runId?: string;
  downloading: boolean;
  onDownload: (filename?: string) => void;
  accent: "assessor" | "recorder";
}) {
  if (!documents.length && !cardDocuments.length) return null;

  const borderAccent =
    accent === "assessor"
      ? "border-emerald-200 dark:border-emerald-900/50"
      : "border-blue-200 dark:border-blue-900/50";

  return (
    <section className={`mt-8 pt-6 border-t-2 ${borderAccent}`}>
      <div className="mb-4">
        <h4 className="text-sm font-bold text-slate-900 dark:text-zinc-100">{title}</h4>
        <p className="text-xs text-slate-500 dark:text-zinc-400 mt-0.5">{description}</p>
      </div>

      <DocumentTable documents={documents} runId={runId} onDownload={onDownload} downloading={downloading} />

      {cardDocuments.map((doc, idx) => (
        <OfficialDocumentCard
          key={doc.id || `card-${idx}`}
          doc={doc}
          idx={idx}
          runId={runId}
          downloading={downloading}
          onDownload={onDownload}
          accent={accent}
        />
      ))}
    </section>
  );
}

export default function DocumentsList({ documents, runId, nameSearchGroups }: Props) {
  const [downloading, setDownloading] = React.useState(false);

  const assessorDocs = documents.filter((d) => getDocumentCategory(d) === "assessor");
  const recorderDocs = documents.filter((d) => getDocumentCategory(d) === "recorder");
  const aiDocs = documents.filter((d) => getDocumentCategory(d) === "ai");
  const otherDocs = documents.filter((d) => getDocumentCategory(d) === "other");

  const groupedNameSearches = buildNameSearchGroups(recorderDocs, nameSearchGroups);
  const primaryRecorderDocs = recorderDocs.filter((d) => !getSearchedName(d));

  const assessorCards = assessorDocs.filter((d) => d.ocr_json?.source === "assessor" && hasDownloadablePdf(d));
  const recorderCards = primaryRecorderDocs.filter((d) => hasDownloadablePdf(d));

  if (!documents.length) {
    return (
      <div className="bg-white dark:bg-[#161b22] rounded-xl shadow-sm border border-slate-200 dark:border-white/[0.08] p-6 transition-colors">
        <h3 className="text-base font-bold text-slate-900 dark:text-zinc-100 mb-2">Recorded Transactions</h3>
        <p className="text-sm text-slate-500 dark:text-zinc-400">No transaction history found yet.</p>
      </div>
    );
  }

  const handleDownload = async (filename?: string) => {
    if (!runId) return;
    try {
      setDownloading(true);
      await downloadOfficialDocument(runId, filename);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Download failed");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="bg-white dark:bg-[#161b22] rounded-xl shadow-sm border border-slate-200 dark:border-white/[0.08] p-6 transition-colors">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-2">
        <div>
          <h3 className="text-base font-bold text-slate-900 dark:text-zinc-100 mb-0.5">Recorded Transactions</h3>
          <p className="text-xs text-slate-500 dark:text-zinc-400">
            Assessor property reports and recorder official documents, organized by source.
          </p>
        </div>
        {runId && (
          <button
            type="button"
            onClick={() => handleDownload()}
            disabled={downloading}
            className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-xs font-semibold shadow-sm transition-all disabled:opacity-50"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            {downloading ? "Downloading..." : "Download Official Document (PDF)"}
          </button>
        )}
      </div>

      <DocumentSection
        title="Assessor Documents"
        description="Property appraiser sales history and downloaded assessor summary/detailed reports."
        documents={assessorDocs}
        cardDocuments={assessorCards}
        runId={runId}
        downloading={downloading}
        onDownload={handleDownload}
        accent="assessor"
      />

      <DocumentSection
        title="Recorder Documents"
        description="Official recorded deeds and instruments from the original recorder search."
        documents={[...primaryRecorderDocs, ...otherDocs]}
        cardDocuments={recorderCards}
        runId={runId}
        downloading={downloading}
        onDownload={handleDownload}
        accent="recorder"
      />

      {groupedNameSearches.map((group) => (
        <DocumentSection
          key={group.name}
          title={`Name Search: ${group.name}`}
          description={`${group.document_count ?? group.documents.length} record(s) found for this party name search.`}
          documents={group.documents}
          cardDocuments={group.documents.filter((d) => hasDownloadablePdf(d))}
          runId={runId}
          downloading={downloading}
          onDownload={handleDownload}
          accent="recorder"
        />
      ))}

      {aiDocs.length > 0 && (
        <section className="mt-8 pt-6 border-t-2 border-purple-200 dark:border-purple-900/50">
          <div className="mb-4">
            <h4 className="text-sm font-bold text-slate-900 dark:text-zinc-100">AI Analysis</h4>
            <p className="text-xs text-slate-500 dark:text-zinc-400 mt-0.5">Generated title examination notes.</p>
          </div>
          {aiDocs.map((doc, idx) => (
            <AiDocumentCard key={doc.id || idx} doc={doc} idx={idx} />
          ))}
        </section>
      )}
    </div>
  );
}

export type { Document };
export {
  getDocumentCategory,
  getDocumentAddress,
  getSearchedName,
  isBookPageLabel,
  isPrimaryRecorderDocument,
  getPrimaryRecorderDocuments,
  buildNameSearchGroups,
  DocumentTable,
  hasDownloadablePdf,
  resolveFolderAndFile,
};
