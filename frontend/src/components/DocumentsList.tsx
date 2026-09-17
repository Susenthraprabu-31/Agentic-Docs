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
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <h3 className="text-base font-semibold text-slate-800 mb-2">Recorded Transactions</h3>
        <p className="text-sm text-slate-400">No transaction history found yet.</p>
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
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
        <div>
          <h3 className="text-base font-semibold text-slate-800 mb-0.5">Recorded Transactions</h3>
          <p className="text-xs text-slate-500">
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

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-500">
              <th className="pb-2 pr-4">Type</th>
              <th className="pb-2 pr-4">Date</th>
              <th className="pb-2 pr-4">Book / Page</th>
              <th className="pb-2 pr-4">Instrument #</th>
              <th className="pb-2 pr-4">Grantor</th>
              <th className="pb-2 pr-4">Grantee</th>
              <th className="pb-2 pr-4">Source</th>
              <th className="pb-2">Action</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((doc, i) => {
              const ocr = doc.ocr_json || {};
              const bp = doc.book_page || (ocr.book_number && ocr.page_number ? `${ocr.book_number}/${ocr.page_number}` : "—");
              return (
                <tr key={i} className="border-b border-slate-100 hover:bg-slate-50/50">
                  <td className="py-2.5 pr-4 font-medium text-slate-900">{doc.document_type || "—"}</td>
                  <td className="py-2.5 pr-4 text-slate-600">{doc.recording_date || "—"}</td>
                  <td className="py-2.5 pr-4 text-slate-600">{bp}</td>
                  <td className="py-2.5 pr-4 font-mono text-xs text-slate-700">{doc.instrument_number || "—"}</td>
                  <td className="py-2.5 pr-4 text-slate-800">{doc.grantor || "—"}</td>
                  <td className="py-2.5 pr-4 text-slate-800">{doc.grantee || "—"}</td>
                  <td className="py-2.5 pr-4 text-xs text-slate-500">{sourceLabel(doc)}</td>
                  <td className="py-2.5">
                    {runId ? (
                      <button
                        type="button"
                        onClick={() => handleDownload(doc.file_name)}
                        className="text-teal-600 hover:text-teal-700 hover:underline text-xs font-medium"
                      >
                        Download
                      </button>
                    ) : doc.source_url ? (
                      <a
                        href={doc.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:underline text-xs"
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
          <div key={idx} className="mt-6 p-5 rounded-xl bg-slate-50 border border-slate-200">
            <div className="flex flex-wrap items-center justify-between gap-4 pb-3 border-b border-slate-200/80">
              <div>
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-blue-100 text-blue-700">
                    Official Copy
                  </span>
                  <span className="text-xs text-slate-500 font-mono">
                    CFN: {doc.instrument_number || "—"}
                  </span>
                </div>
                <h4 className="text-sm font-bold text-slate-900 mt-1">
                  {doc.document_type || "Recorded Document"}
                </h4>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600 mt-1">
                  {folderName && (
                    <span>
                      Folder: <code className="bg-slate-200 text-slate-800 px-1.5 py-0.5 rounded text-[11px] font-mono">{folderName}</code>
                    </span>
                  )}
                  {fileName && (
                    <span>
                      File: <strong className="text-slate-800">{fileName}</strong>
                    </span>
                  )}
                  {doc.book_page && (
                    <span>
                      Book/Page: <strong>{doc.book_page}</strong>
                    </span>
                  )}
                  {doc.recording_date && (
                    <span>
                      Recorded: <strong>{doc.recording_date}</strong>
                    </span>
                  )}
                </div>
              </div>

              {runId && (
                <button
                  type="button"
                  onClick={() => handleDownload(fileName)}
                  disabled={downloading}
                  className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-xs font-medium shadow-sm transition-all"
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
                <div className="flex items-center justify-between text-xs text-slate-500 mb-2">
                  <span>Document View Snapshot</span>
                  {runId && (
                    <a
                      href={getDocumentDownloadUrl(runId)}
                      target="_blank"
                      rel="noreferrer"
                      className="text-teal-600 hover:underline"
                    >
                      Open Raw PDF ↗
                    </a>
                  )}
                </div>
                <div className="border border-slate-300 rounded-lg overflow-hidden bg-white shadow-inner max-h-[520px] overflow-y-auto">
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
