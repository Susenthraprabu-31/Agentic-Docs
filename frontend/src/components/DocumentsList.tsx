import React from "react";
import { downloadOfficialDocument, getDocumentDownloadUrl } from "../api/client";

interface Document {
  id?: string;
  document_type?: string;
  recording_date?: string;
  book_page?: string;
  instrument_number?: string;
  grantor?: string;
  grantee?: string;
  source_url?: string;
  screenshot_path?: string;
  file_name?: string;
  folder_name?: string;
  image_data_uri?: string;
  ocr_json?: {
    sale_price?: string;
    source?: string;
    section?: string;
    download_path?: string;
    folder_name?: string;
    folder?: string;
    image_path?: string;
    book_number?: string;
    page_number?: string;
  };
}

interface Props {
  documents: Document[];
  runId?: string;
}

function sourceLabel(doc: Document): string {
  const source = doc.ocr_json?.source;
  if (source === "assessor_sales") return "Assessor Sales";
  if (source === "assessor") return "Assessor";
  if (source) return String(source);
  return "Recorder";
}

export default function DocumentsList({ documents, runId }: Props) {
  const [downloading, setDownloading] = React.useState(false);

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
      <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
        <div>
          <h3 className="text-base font-bold text-slate-900 dark:text-zinc-100 mb-0.5">Recorded Transactions</h3>
          <p className="text-xs text-slate-500 dark:text-zinc-400">
            Deed and official records from county recorder and sales history.
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
              <th className="py-2.5 px-3">Source</th>
              <th className="py-2.5 px-3">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-white/[0.05] bg-white dark:bg-[#161b22]">
            {documents.map((doc, i) => {
              const ocr = doc.ocr_json || {};
              const bp = doc.book_page || (ocr.book_number && ocr.page_number ? `${ocr.book_number}/${ocr.page_number}` : "—");
              return (
                <tr key={i} className="hover:bg-slate-50/70 dark:hover:bg-zinc-800/30 transition-colors">
                  <td className="py-2.5 px-3 font-semibold text-slate-900 dark:text-zinc-100">{doc.document_type || "—"}</td>
                  <td className="py-2.5 px-3 text-slate-700 dark:text-zinc-300">{doc.recording_date || "—"}</td>
                  <td className="py-2.5 px-3 font-mono text-slate-700 dark:text-zinc-300">{bp}</td>
                  <td className="py-2.5 px-3 font-mono text-xs text-slate-800 dark:text-zinc-200">{doc.instrument_number || "—"}</td>
                  <td className="py-2.5 px-3 text-slate-800 dark:text-zinc-200">{doc.grantor || "—"}</td>
                  <td className="py-2.5 px-3 text-slate-800 dark:text-zinc-200">{doc.grantee || "—"}</td>
                  <td className="py-2.5 px-3 text-xs text-slate-500 dark:text-zinc-400">{sourceLabel(doc)}</td>
                  <td className="py-2.5 px-3">
                    {runId ? (
                      <button
                        type="button"
                        onClick={() => handleDownload(doc.file_name)}
                        className="text-teal-600 dark:text-teal-400 hover:underline text-xs font-semibold"
                      >
                        Download
                      </button>
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

      {/* Official Document Copies Attachment Cards */}
      {documents.map((doc, idx) => {
        const ocr = doc.ocr_json || {};
        const folderName =
          doc.folder_name ||
          ocr.folder_name ||
          (ocr.book_number && ocr.page_number ? `recorder_${ocr.book_number}_${ocr.page_number}` : null);
        const fileName =
          doc.file_name ||
          (ocr.download_path ? ocr.download_path.split(/[\\/]/).pop() : null) ||
          (folderName ? `${folderName}.pdf` : "recorder_document.pdf");
        const imageSrc =
          doc.image_data_uri ||
          (folderName ? `http://localhost:8000/local_storage/${folderName}/${folderName}.png` : null);

        return (
          <div key={idx} className="mt-6 p-5 rounded-xl bg-slate-50/80 dark:bg-zinc-900/60 border border-slate-200 dark:border-white/[0.08]">
            <div className="flex flex-wrap items-center justify-between gap-4 pb-3 border-b border-slate-200 dark:border-white/[0.08]">
              <div>
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-blue-100 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800/40">
                    Official Copy
                  </span>
                  <span className="text-xs text-slate-500 dark:text-zinc-400 font-mono">
                    CFN: {doc.instrument_number || "—"}
                  </span>
                </div>
                <h4 className="text-sm font-bold text-slate-900 dark:text-zinc-100 mt-1">
                  {doc.document_type || "Recorded Document"}
                </h4>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-zinc-400 mt-1">
                  {folderName && (
                    <span>
                      Folder: <code className="bg-slate-200 dark:bg-zinc-800 text-slate-800 dark:text-zinc-200 px-1.5 py-0.5 rounded text-[11px] font-mono">{folderName}</code>
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
                <button
                  type="button"
                  onClick={() => handleDownload(fileName)}
                  disabled={downloading}
                  className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-xs font-semibold shadow-sm transition-all"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Download PDF
                </button>
              )}
            </div>

            {/* Document Image View */}
            {imageSrc && (
              <div className="mt-4">
                <div className="flex items-center justify-between text-xs text-slate-500 dark:text-zinc-400 mb-2">
                  <span className="font-semibold">Document View Snapshot</span>
                  {runId && (
                    <a
                      href={getDocumentDownloadUrl(runId)}
                      target="_blank"
                      rel="noreferrer"
                      className="text-teal-600 dark:text-teal-400 font-semibold hover:underline"
                    >
                      Open Raw PDF ↗
                    </a>
                  )}
                </div>
                <div className="border border-slate-300 dark:border-white/[0.1] rounded-lg overflow-hidden bg-white dark:bg-zinc-950 shadow-inner max-h-[520px] overflow-y-auto">
                  <img
                    src={imageSrc}
                    alt="Official Recorded Document Image"
                    className="w-full h-auto object-top display-block"
                    onError={(e) => {
                      (e.target as HTMLElement).style.display = "none";
                    }}
                  />
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
