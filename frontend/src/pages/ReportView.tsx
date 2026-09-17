import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ChainOfTitle, { mergeChainEntries } from "../components/ChainOfTitle";
import DocumentsList from "../components/DocumentsList";
import PropertyDetails from "../components/PropertyDetails";
import ReportPreview from "../components/ReportPreview";
import TaxRecords from "../components/TaxRecords";
import { getReportByRun, ReportData } from "../api/client";

export default function ReportView() {
  const { runId } = useParams<{ runId: string }>();
  const [report, setReport] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    getReportByRun(runId)
      .then(setReport)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [runId]);

  const documents = (report?.report_json?.documents || []) as Record<string, any>[];
  const property = report?.report_json?.property;
  const taxRecord = report?.report_json?.tax_record;
  const chainEntries = mergeChainEntries(
    documents,
    (property?.chain_of_title as Record<string, string>[]) || []
  );
  const currentOwner = property?.owner_name ? String(property.owner_name) : undefined;
  const state = report?.report_json?.state;
  const county = report?.report_json?.county;
  const queryType = report?.report_json?.query_type;
  const queryValue = report?.report_json?.query_value;

  const firstDoc = documents[0];

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/runs/${runId}`} className="text-sm text-violet-600 dark:text-violet-400 hover:underline">← Back to Run</Link>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-zinc-100 mt-1">Property Report</h1>
      </div>

      {loading && <p className="text-slate-400">Loading report...</p>}
      {error && <p className="text-red-600">{error}</p>}

      {report && (
        <>
          <ReportPreview report={report} />

          {property ? (
            <PropertyDetails property={property as Record<string, unknown>} />
          ) : (
            <div className="bg-white dark:bg-[#161b22] rounded-xl shadow-sm border border-slate-200 dark:border-white/[0.08] p-6">
              <h3 className="text-base font-semibold text-slate-800 dark:text-zinc-100 mb-1">Search & Recording Overview</h3>
              <p className="text-xs text-slate-500 dark:text-zinc-400 mb-4">Official public records search details</p>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
                <div className="p-3 rounded-lg bg-slate-50 dark:bg-zinc-900/60 border border-slate-100 dark:border-white/[0.05]">
                  <div className="text-xs text-slate-500 dark:text-zinc-400 uppercase tracking-wide">Location</div>
                  <div className="font-semibold text-slate-900 dark:text-zinc-200 mt-0.5">
                    {county ? `${county.charAt(0).toUpperCase() + county.slice(1)} County` : "—"}, {state || "FL"}
                  </div>
                </div>
                <div className="p-3 rounded-lg bg-slate-50 dark:bg-zinc-900/60 border border-slate-100 dark:border-white/[0.05]">
                  <div className="text-xs text-slate-500 dark:text-zinc-400 uppercase tracking-wide">Query ({queryType || "book_page"})</div>
                  <div className="font-semibold text-slate-900 dark:text-zinc-200 mt-0.5">{queryValue || "—"}</div>
                </div>
                <div className="p-3 rounded-lg bg-slate-50 dark:bg-zinc-900/60 border border-slate-100 dark:border-white/[0.05]">
                  <div className="text-xs text-slate-500 dark:text-zinc-400 uppercase tracking-wide">Document Type</div>
                  <div className="font-semibold text-slate-900 dark:text-zinc-200 mt-0.5">{firstDoc?.document_type || "Recorded Document"}</div>
                </div>
                <div className="p-3 rounded-lg bg-slate-50 dark:bg-zinc-900/60 border border-slate-100 dark:border-white/[0.05]">
                  <div className="text-xs text-slate-500 dark:text-zinc-400 uppercase tracking-wide">Grantee (Buyer/Owner)</div>
                  <div className="font-semibold text-slate-900 dark:text-zinc-200 mt-0.5">{firstDoc?.grantee || currentOwner || "—"}</div>
                </div>
              </div>
            </div>
          )}

          <TaxRecords taxRecord={taxRecord as Parameters<typeof TaxRecords>[0]["taxRecord"]} />
          <DocumentsList documents={documents} runId={runId} />
          <ChainOfTitle entries={chainEntries} currentOwner={currentOwner || firstDoc?.grantee} />
        </>
      )}
    </div>
  );
}
