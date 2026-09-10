import { useState } from "react";
import { downloadReportPdf, ReportData } from "../api/client";

interface Props {
  report: ReportData | null;
  loading?: boolean;
}

export default function ReportPreview({ report, loading }: Props) {
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [storageUrl, setStorageUrl] = useState<string | null>(null);

  if (loading) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <p className="text-sm text-slate-400">Generating report...</p>
      </div>
    );
  }

  if (!report) return null;

  const property = report.report_json?.property as Record<string, unknown> | undefined;

  async function handleDownload() {
    if (!report) return;
    setDownloading(true);
    setDownloadError(null);
    setStorageUrl(null);
    try {
      const result = await downloadReportPdf(report.id, report.run_id);
      setStorageUrl(result.storageUrl || report.storage_url || null);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "Download failed");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 space-y-4">
      <div className="flex items-center justify-between gap-4">
        <h3 className="text-base font-semibold text-slate-800">Property Report</h3>
        <button
          type="button"
          onClick={handleDownload}
          disabled={downloading}
          className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          {downloading ? "Preparing PDF..." : "Download PDF"}
        </button>
      </div>

      {downloadError && (
        <p className="text-sm text-red-600">{downloadError}</p>
      )}

      {(storageUrl || report.storage_url) && (
        <p className="text-sm text-green-700 bg-green-50 border border-green-100 rounded-lg px-3 py-2">
          PDF saved to Supabase storage.{" "}
          <a
            href={storageUrl || report.storage_url}
            target="_blank"
            rel="noreferrer"
            className="underline font-medium"
          >
            Open stored copy
          </a>
        </p>
      )}

      {property && (
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div><span className="text-slate-500">Owner:</span> <span className="font-medium">{String(property.owner_name || "—")}</span></div>
          <div><span className="text-slate-500">APN:</span> <span className="font-medium">{String(property.apn || "—")}</span></div>
          <div className="col-span-2"><span className="text-slate-500">Address:</span> <span className="font-medium">{String(property.property_address || "—")}</span></div>
          <div><span className="text-slate-500">Assessed Value:</span> <span className="font-medium">{property.assessed_value ? `$${property.assessed_value}` : "—"}</span></div>
        </div>
      )}

      <p className="text-xs text-slate-400">
        Generated: {report.report_json?.generated_at || "—"}
      </p>
    </div>
  );
}
