import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ChainOfTitle, { mergeChainEntries } from "../components/ChainOfTitle";
import PropertyDetails from "../components/PropertyDetails";
import DocumentsList from "../components/DocumentsList";
import GisMapPreview from "../components/GisMapPreview";
import TaxRecords from "../components/TaxRecords";
import ReportPreview from "../components/ReportPreview";
import PipelineNodes from "../components/PipelineNodes";
import RunProgress from "../components/RunProgress";
import SourcesPanel from "../components/SourcesPanel";
import { getReportByRun, ReportData } from "../api/client";
import { useRunStream } from "../hooks/useRunStream";

export default function RunDetail() {
  const { runId } = useParams<{ runId: string }>();
  const { runDetail, events, connected } = useRunStream(runId);
  const [report, setReport] = useState<ReportData | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  useEffect(() => {
    if (!runId || runDetail?.run.status !== "completed") return;
    setReportLoading(true);
    getReportByRun(runId)
      .then(setReport)
      .catch(() => setReport(null))
      .finally(() => setReportLoading(false));
  }, [runId, runDetail?.run.status]);

  const documents =
    (runDetail?.documents?.length ? runDetail.documents : report?.report_json?.documents) || [];
  const records = runDetail?.records || [];
  const property = records.find((r) => r.source === "assessor") || records[0];
  const taxRecord = records.find((r) => r.source === "tax_record");
  const rawJson = (property?.raw_json as Record<string, unknown>) || {};
  const ownerRows = Array.isArray(rawJson.owner_rows) ? rawJson.owner_rows : [];
  const currentOwner =
    ownerRows.length
      ? ownerRows
          .map((row) => String((row as Record<string, string>)["Owner Name"] || ""))
          .filter(Boolean)
          .join("; ")
      : String(property?.owner_name || "");
  const chainEntries = mergeChainEntries(
    documents as Record<string, unknown>[],
    (rawJson.chain_of_title as Record<string, string>[]) || []
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/" className="text-sm font-semibold text-violet-600 dark:text-violet-400 hover:underline">← New Search</Link>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-zinc-100 mt-1">Research Run</h1>
          {runDetail && (
            <p className="text-sm text-slate-500 dark:text-zinc-400">
              {runDetail.run.query_type}: {runDetail.run.query_value}
            </p>
          )}
        </div>
        {runDetail?.run.status === "completed" && (
          <Link
            to={`/reports/run/${runId}`}
            className="text-sm bg-violet-600 hover:bg-violet-700 text-white font-semibold px-4 py-2 rounded-lg shadow-sm transition-colors"
          >
            View Full Report
          </Link>
        )}
      </div>

      <PipelineNodes
        events={events}
        sources={runDetail?.sources || []}
        runStatus={runDetail?.run.status}
        live={connected}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <RunProgress
          events={events}
          recordsCount={runDetail?.records_count || 0}
          documentsCount={runDetail?.documents_count || 0}
          status={runDetail?.run.status}
          connected={connected}
        />
        <SourcesPanel sources={runDetail?.sources || []} />
      </div>

      {runDetail?.run.status === "completed" && (
        <div className="bg-blue-50/80 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800/40 rounded-xl px-4 py-3 text-sm text-blue-800 dark:text-blue-200">
          <strong>What the numbers mean:</strong> NETR "records" = county portal links found.
          Parcels = assessor property data. Chain of Title / Recorded Documents include Sales Information
          transfers from the assessor report (date, instrument #, grantor/grantee when listed).
        </div>
      )}

      {property && <PropertyDetails property={property} />}
      {taxRecord && <TaxRecords taxRecord={taxRecord as Parameters<typeof TaxRecords>[0]["taxRecord"]} />}

      {runDetail?.run.status === "completed" && (
        <>
          <GisMapPreview
            gisScreenshotUrl={report?.report_json?.gis_screenshot_url}
            gisScreenshotDataUri={report?.report_json?.gis_screenshot_data_uri}
            documents={documents as Record<string, unknown>[]}
            queryValue={runDetail.run.query_value}
          />
          <DocumentsList documents={documents as Record<string, string>[]} />
          <ChainOfTitle entries={chainEntries} currentOwner={currentOwner || undefined} />
          <ReportPreview report={report} loading={reportLoading} />
        </>
      )}
    </div>
  );
}
