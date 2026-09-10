import { RunEvent } from "../api/client";

interface Props {
  events: RunEvent[];
  recordsCount: number;
  documentsCount: number;
  status?: string;
  connected?: boolean;
}

export default function RunProgress({ events, recordsCount, documentsCount, status, connected }: Props) {
  const trail = events.filter((e) => e.event_type !== "ping");

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-semibold text-slate-800">Live Progress</h3>
        <div className="flex items-center gap-3 text-xs">
          <span className={`inline-flex items-center gap-1 ${connected ? "text-green-600" : "text-slate-400"}`}>
            <span className={`w-2 h-2 rounded-full ${connected ? "bg-green-500" : "bg-slate-300"}`} />
            {connected ? "Live" : "Polling"}
          </span>
          {status && (
            <span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 capitalize">{status}</span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="rounded-lg bg-blue-50 px-4 py-3 text-center">
          <p className="text-2xl font-bold text-blue-700">{recordsCount}</p>
          <p className="text-xs text-blue-600">Parcels Found</p>
        </div>
        <div className="rounded-lg bg-purple-50 px-4 py-3 text-center">
          <p className="text-2xl font-bold text-purple-700">{documentsCount}</p>
          <p className="text-xs text-purple-600">Documents Found</p>
        </div>
      </div>

      <div className="space-y-2 max-h-64 overflow-y-auto">
        {trail.length === 0 && (
          <p className="text-sm text-slate-400 italic">Waiting for research to begin...</p>
        )}
        {trail.map((e, i) => (
          <div key={e.id || i} className="flex gap-3 text-sm border-l-2 border-blue-200 pl-3 py-1">
            <span className="text-xs text-slate-400 shrink-0 w-20 capitalize">{e.source || "—"}</span>
            <span className="text-slate-700">{e.payload?.message || e.event_type}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
