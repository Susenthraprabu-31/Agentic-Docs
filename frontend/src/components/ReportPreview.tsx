import { useState } from "react";
import { downloadReportPdf, downloadReportExcel, ReportData } from "../api/client";

interface Props {
  report: ReportData | null;
  loading?: boolean;
}

export default function ReportPreview({ report, loading }: Props) {
  const [downloading, setDownloading] = useState(false);
  const [downloadingExcel, setDownloadingExcel] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [storageUrl, setStorageUrl] = useState<string | null>(null);

  if (loading) {
    return (
      <div className="bg-white dark:bg-[#161b22] rounded-xl shadow-sm border border-slate-200 dark:border-white/[0.08] p-6">
        <p className="text-sm text-slate-500 dark:text-zinc-400">Generating report...</p>
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

  async function handleDownloadExcel() {
    if (!report) return;
    setDownloadingExcel(true);
    setDownloadError(null);
    try {
      await downloadReportExcel(report.run_id || report.id);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "Excel download failed");
    } finally {
      setDownloadingExcel(false);
    }
  }

  return (
    <div className="bg-white dark:bg-[#161b22] rounded-xl shadow-sm border border-slate-200 dark:border-white/[0.08] p-6 space-y-4 transition-colors">
      <div className="flex items-center justify-between gap-4">
        <h3 className="text-base font-bold text-slate-900 dark:text-zinc-100">Property Report</h3>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleDownloadExcel}
            disabled={downloadingExcel}
            className="inline-flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-xs font-semibold px-3 py-2 rounded-lg transition-colors shadow-sm"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            {downloadingExcel ? "Generating Excel..." : "Chain Sheet (.xlsx)"}
          </button>
          <button
            type="button"
            onClick={handleDownload}
            disabled={downloading}
            className="inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs font-semibold px-3 py-2 rounded-lg transition-colors shadow-sm"
          >
            {downloading ? "Preparing PDF..." : "Download PDF"}
          </button>
        </div>
      </div>

      {downloadError && (
        <p className="text-sm text-red-600 dark:text-red-400">{downloadError}</p>
      )}

      {(storageUrl || report.storage_url) && (
        <p className="text-sm text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/50 rounded-lg px-3 py-2">
          PDF saved to Supabase storage.{" "}
          <a
            href={storageUrl || report.storage_url}
            target="_blank"
            rel="noreferrer"
            className="underline font-semibold"
          >
            Open stored copy
          </a>
        </p>
      )}

      {property && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm p-4 rounded-xl bg-slate-50/80 dark:bg-zinc-900/60 border border-slate-200/80 dark:border-white/[0.06]">
          <div>
            <span className="text-slate-500 dark:text-zinc-400 font-medium">Owner:</span>{" "}
            <span className="font-semibold text-slate-900 dark:text-zinc-100">{String(property.owner_name || "—")}</span>
          </div>
          <div>
            <span className="text-slate-500 dark:text-zinc-400 font-medium">APN:</span>{" "}
            <span className="font-semibold text-slate-900 dark:text-zinc-100 font-mono">{String(property.apn || "—")}</span>
          </div>
          <div className="sm:col-span-2">
            <span className="text-slate-500 dark:text-zinc-400 font-medium">Address:</span>{" "}
            <span className="font-semibold text-slate-900 dark:text-zinc-100">{String(property.property_address || "—")}</span>
          </div>
          <div>
            <span className="text-slate-500 dark:text-zinc-400 font-medium">Assessed Value:</span>{" "}
            <span className="font-semibold text-slate-900 dark:text-zinc-100">{property.assessed_value ? `$${property.assessed_value}` : "—"}</span>
          </div>
        </div>
      )}

      <p className="text-xs text-slate-500 dark:text-zinc-400">
        Generated: {report.report_json?.generated_at || "—"}
      </p>
    </div>
  );
}
