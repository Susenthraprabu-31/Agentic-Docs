import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ChainOfTitle from "../components/ChainOfTitle";
import DocumentsList from "../components/DocumentsList";
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

  const documents = (report?.report_json?.documents || []) as Record<string, string>[];
  const property = report?.report_json?.property as Record<string, unknown> | undefined;
  const taxRecord = report?.report_json?.tax_record as Record<string, unknown> | undefined;

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/runs/${runId}`} className="text-sm text-blue-600 hover:underline">← Back to Run</Link>
        <h1 className="text-2xl font-bold text-slate-900 mt-1">Property Report</h1>
      </div>

      {loading && <p className="text-slate-400">Loading report...</p>}
      {error && <p className="text-red-600">{error}</p>}

      {report && (
        <>
          <ReportPreview report={report} />
          {property && (
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
              <h3 className="font-semibold mb-3">Property Summary</h3>
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div><dt className="text-slate-500">Owner</dt><dd className="font-medium">{String(property.owner_name || "—")}</dd></div>
                <div><dt className="text-slate-500">APN</dt><dd className="font-medium">{String(property.apn || "—")}</dd></div>
                <div className="col-span-2"><dt className="text-slate-500">Legal Description</dt><dd className="font-medium">{String(property.legal_desc || "—")}</dd></div>
              </dl>
            </div>
          )}
          <TaxRecords taxRecord={taxRecord as Parameters<typeof TaxRecords>[0]["taxRecord"]} />
          <DocumentsList documents={documents} />
          <ChainOfTitle documents={documents} />
        </>
      )}
    </div>
  );
}
