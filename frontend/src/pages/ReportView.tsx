import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ChainOfTitle, { mergeChainEntries } from "../components/ChainOfTitle";
import GisMapPreview from "../components/GisMapPreview";
import PropertyDetails from "../components/PropertyDetails";
import ReportPreview from "../components/ReportPreview";
import ReportSearchExplorer from "../components/ReportSearchExplorer";
import { getReportByRun, ReportData } from "../api/client";

type ReportTab = "overview" | "search" | "deliverables";

export default function ReportView() {
  const { runId } = useParams<{ runId: string }>();
  const [report, setReport] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ReportTab>("search");

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
  const nameSearchGroups = (report?.report_json?.name_search_groups || []) as {
    name: string;
    documents: Record<string, unknown>[];
    document_count?: number;
  }[];
  const recorderPrimaryDocuments = (report?.report_json?.recorder_primary_documents || []) as Record<
    string,
    unknown
  >[];
  const chainEntries = mergeChainEntries(
    documents,
    (property?.chain_of_title as Record<string, string>[]) || [],
    { recorderPrimaryDocuments, nameSearchGroups },
  );
  const currentOwner = property?.owner_name ? String(property.owner_name) : undefined;
  const state = report?.report_json?.state;
  const county = report?.report_json?.county;
  const queryType = report?.report_json?.query_type;
  const queryValue = report?.report_json?.query_value;

  const firstDoc = documents[0];

  const tabs: { id: ReportTab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "search", label: "Search" },
    { id: "deliverables", label: "Deliverables" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/runs/${runId}`} className="text-sm text-violet-600 dark:text-violet-400 hover:underline">
          ← Back to Run
        </Link>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-zinc-100 mt-1">Property Report</h1>
      </div>

      {loading && <p className="text-slate-400">Loading report...</p>}
      {error && <p className="text-red-600">{error}</p>}

      {report && (
        <>
          <div className="border-b border-slate-200 dark:border-white/[0.08]">
            <nav className="flex flex-wrap gap-6">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  className={`pb-3 text-sm font-semibold border-b-2 transition-colors ${
                    activeTab === tab.id
                      ? "border-sky-500 text-sky-700 dark:text-sky-300"
                      : "border-transparent text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-zinc-200"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </nav>
          </div>

          {activeTab === "overview" && (
            <div className="space-y-6">
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

              {report.report_json?.ai_agent_response && (
                <div className="bg-white dark:bg-[#161b22] rounded-xl shadow-sm border border-purple-200/80 dark:border-purple-800/40 p-6 transition-colors">
                  <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-purple-100 dark:border-purple-900/30">
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 rounded-lg bg-purple-600/10 dark:bg-purple-500/20 text-purple-600 dark:text-purple-400 flex items-center justify-center">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                        </svg>
                      </div>
                      <div>
                        <h3 className="text-base font-bold text-slate-900 dark:text-zinc-100">AI Title Analysis & Verification</h3>
                        <p className="text-xs text-slate-500 dark:text-zinc-400">Autonomous LLM examination of public property records</p>
                      </div>
                    </div>
                  </div>
                  <div className="mt-4 p-4 rounded-xl bg-purple-50/40 dark:bg-[#0d1117] border border-purple-100 dark:border-purple-900/30 text-sm leading-relaxed text-slate-800 dark:text-zinc-200 whitespace-pre-wrap font-sans">
                    {report.report_json.ai_agent_response}
                  </div>
                </div>
              )}

              <GisMapPreview
                gisScreenshotUrl={report.report_json?.gis_screenshot_url}
                gisScreenshotDataUri={report.report_json?.gis_screenshot_data_uri}
                documents={documents}
                queryValue={queryValue}
              />

              <ChainOfTitle entries={chainEntries} currentOwner={currentOwner || firstDoc?.grantee} />
            </div>
          )}

          {activeTab === "search" && (
            <ReportSearchExplorer
              documents={documents as Parameters<typeof ReportSearchExplorer>[0]["documents"]}
              runId={runId}
              queryValue={queryValue}
              queryType={queryType}
              county={county}
              state={state}
              nameSearchGroups={nameSearchGroups as Parameters<typeof ReportSearchExplorer>[0]["nameSearchGroups"]}
              recorderPrimaryDocuments={
                recorderPrimaryDocuments as Parameters<typeof ReportSearchExplorer>[0]["recorderPrimaryDocuments"]
              }
              taxRecord={taxRecord as Parameters<typeof ReportSearchExplorer>[0]["taxRecord"]}
            />
          )}

          {activeTab === "deliverables" && <ReportPreview report={report} />}
        </>
      )}
    </div>
  );
}
