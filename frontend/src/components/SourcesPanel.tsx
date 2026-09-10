import { SourceProgress } from "../api/client";

const SOURCE_LABELS: Record<string, string> = {
  netronline: "NETR Online Directory",
  assessor: "County Assessor",
  tax_record: "Tax Records",
  recorder: "County Recorder",
  gis: "GIS / Mapping",
};

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-slate-100 text-slate-500 border-slate-200",
  in_progress: "bg-blue-50 text-blue-700 border-blue-200 animate-pulse",
  done: "bg-green-50 text-green-700 border-green-200",
  skipped: "bg-amber-50 text-amber-700 border-amber-200",
  failed: "bg-red-50 text-red-700 border-red-200",
};

interface Props {
  sources: SourceProgress[];
}

export default function SourcesPanel({ sources }: Props) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <h3 className="text-base font-semibold text-slate-800 mb-4">Sources</h3>
      <div className="space-y-3">
        {sources.map((src) => (
          <div
            key={src.source}
            className={`flex items-center justify-between rounded-lg border px-4 py-3 ${STATUS_STYLES[src.status] || STATUS_STYLES.pending}`}
          >
            <div>
              <p className="font-medium text-sm">{SOURCE_LABELS[src.source] || src.source}</p>
              {src.message && <p className="text-xs mt-0.5 opacity-80">{src.message}</p>}
            </div>
            <div className="text-right">
              <span className="text-xs uppercase tracking-wide font-semibold">{src.status.replace("_", " ")}</span>
              {src.records_found > 0 && (
                <p className="text-xs mt-0.5">
                  {src.source === "netronline"
                    ? `${src.records_found} link${src.records_found !== 1 ? "s" : ""} resolved`
                    : `${src.records_found} record${src.records_found !== 1 ? "s" : ""}`}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
