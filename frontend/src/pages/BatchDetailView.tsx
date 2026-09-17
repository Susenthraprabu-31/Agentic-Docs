import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  cancelBatch,
  downloadOfficialDocument,
  getBatch,
  getBatchExportUrl,
  retryBatch,
  BatchJob,
  BatchOrderItem,
} from "../api/client";

export default function BatchDetailView() {
  const { batchId } = useParams<{ batchId: string }>();
  const [batch, setBatch] = useState<BatchJob | null>(null);
  const [orders, setOrders] = useState<BatchOrderItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);

  const fetchBatch = () => {
    if (!batchId) return;
    getBatch(batchId)
      .then((res) => {
        setBatch(res.batch);
        setOrders(res.orders);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchBatch();
    const interval = setInterval(fetchBatch, 3000);
    return () => clearInterval(interval);
  }, [batchId]);

  if (loading && !batch) {
    return <div className="p-12 text-center text-xs text-zinc-500">Loading batch details...</div>;
  }

  if (!batch) {
    return (
      <div className="p-12 text-center space-y-3">
        <p className="text-sm text-red-400">Batch job not found.</p>
        <Link to="/batches" className="text-xs text-teal-400 hover:underline">← Back to Batches</Link>
      </div>
    );
  }

  const completedCount = orders.filter((o) => o.status === "completed").length;
  const failedCount = orders.filter((o) => o.status === "failed").length;
  const runningCount = orders.filter((o) => o.status === "running").length;
  const pct = batch.total_orders > 0 ? Math.round((completedCount / batch.total_orders) * 100) : 0;

  const handleCancel = async () => {
    if (!batchId || !confirm("Are you sure you want to cancel remaining orders in this batch?")) return;
    try {
      setActionLoading(true);
      await cancelBatch(batchId);
      fetchBatch();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Cancel failed");
    } finally {
      setActionLoading(false);
    }
  };

  const handleRetry = async () => {
    if (!batchId) return;
    try {
      setActionLoading(true);
      const res = await retryBatch(batchId);
      alert(`Re-queued ${res.retried_orders} failed/cancelled order(s).`);
      fetchBatch();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Retry failed");
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Breadcrumb & Controls */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <Link to="/batches" className="text-xs text-teal-400 hover:underline flex items-center gap-1 mb-1">
            ← Back to Batches
          </Link>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-zinc-100">{batch.name}</h1>
            <span
              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase tracking-wider ${
                batch.status === "completed"
                  ? "bg-teal-950 text-teal-400 border border-teal-800"
                  : batch.status === "running"
                  ? "bg-amber-950/80 text-amber-400 border border-amber-800 animate-pulse"
                  : batch.status === "partially_failed"
                  ? "bg-orange-950 text-orange-400 border border-orange-800"
                  : batch.status === "failed"
                  ? "bg-red-950 text-red-400 border border-red-800"
                  : "bg-zinc-900 text-zinc-400 border border-zinc-800"
              }`}
            >
              {batch.status}
            </span>
          </div>
          <p className="text-xs text-zinc-500 mt-0.5 font-mono">
            ID: {batch.id} &nbsp;·&nbsp; Created {new Date(batch.created_at).toLocaleString()}
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          {batch.status === "running" && (
            <button
              type="button"
              onClick={handleCancel}
              disabled={actionLoading}
              className="px-3.5 py-2 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-red-400 text-xs font-semibold border border-red-900/40 transition-colors"
            >
              Cancel Batch
            </button>
          )}

          {(failedCount > 0 || batch.status === "partially_failed" || batch.status === "failed") && (
            <button
              type="button"
              onClick={handleRetry}
              disabled={actionLoading}
              className="px-3.5 py-2 rounded-xl bg-amber-900/40 hover:bg-amber-800/60 text-amber-200 text-xs font-semibold border border-amber-700/50 transition-colors"
            >
              Retry Failed ({failedCount})
            </button>
          )}

          <a
            href={getBatchExportUrl(batch.id)}
            download
            className="px-4 py-2 rounded-xl bg-teal-600 hover:bg-teal-500 text-white text-xs font-bold shadow-lg shadow-teal-950/50 flex items-center gap-2 transition-all"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            Export All (ZIP)
          </a>
        </div>
      </div>

      {/* Progress & Stats Card */}
      <div className="p-6 rounded-2xl bg-[#0f141c] border border-teal-900/40 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-xs text-zinc-400">Batch Progress</span>
            <div className="text-lg font-bold text-zinc-100 mt-0.5">
              {completedCount} of {batch.total_orders} orders completed
            </div>
          </div>
          <span className="text-2xl font-black text-teal-300">{pct}%</span>
        </div>

        <div className="w-full bg-zinc-900 h-2.5 rounded-full overflow-hidden border border-zinc-800">
          <div
            className={`h-full transition-all duration-500 ${
              batch.status === "failed" ? "bg-red-500" : "bg-teal-500"
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
          <div className="p-3 rounded-lg bg-zinc-950/60 border border-zinc-800/80">
            <div className="text-[10px] text-zinc-500 uppercase font-semibold">Total Orders</div>
            <div className="text-base font-bold text-zinc-100 mt-0.5">{batch.total_orders}</div>
          </div>
          <div className="p-3 rounded-lg bg-zinc-950/60 border border-zinc-800/80">
            <div className="text-[10px] text-zinc-500 uppercase font-semibold">Running Now</div>
            <div className="text-base font-bold text-amber-400 mt-0.5">{runningCount}</div>
          </div>
          <div className="p-3 rounded-lg bg-zinc-950/60 border border-zinc-800/80">
            <div className="text-[10px] text-zinc-500 uppercase font-semibold">Completed</div>
            <div className="text-base font-bold text-teal-300 mt-0.5">{completedCount}</div>
          </div>
          <div className="p-3 rounded-lg bg-zinc-950/60 border border-zinc-800/80">
            <div className="text-[10px] text-zinc-500 uppercase font-semibold">Failed / Cancelled</div>
            <div className="text-base font-bold text-red-400 mt-0.5">{failedCount}</div>
          </div>
        </div>
      </div>

      {/* Orders Table */}
      <div className="bg-[#0f141c] border border-teal-900/40 rounded-2xl overflow-hidden shadow-xl">
        <div className="px-6 py-4 border-b border-teal-950 flex items-center justify-between">
          <h2 className="text-sm font-bold text-zinc-200">Orders in this Batch ({orders.length})</h2>
          <span className="text-xs text-zinc-500">Auto-refreshing</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-zinc-300">
            <thead className="bg-[#0c1017] text-zinc-400 font-semibold border-b border-teal-950">
              <tr>
                <th className="py-3 px-5">#</th>
                <th className="py-3 px-5">Location</th>
                <th className="py-3 px-5">Query</th>
                <th className="py-3 px-5">Workflow</th>
                <th className="py-3 px-5">Status</th>
                <th className="py-3 px-5">Error / Details</th>
                <th className="py-3 px-5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/40">
              {orders.map((ord, idx) => {
                const isRunning = ord.status === "running";
                const isDone = ord.status === "completed";
                const isFailed = ord.status === "failed";
                const isCancelled = ord.status === "cancelled";

                return (
                  <tr key={ord.id} className="hover:bg-zinc-900/40 transition-colors">
                    <td className="py-3 px-5 text-zinc-500 font-mono">{idx + 1}</td>
                    <td className="py-3 px-5 font-semibold text-zinc-200">
                      {ord.county}, {ord.state}
                    </td>
                    <td className="py-3 px-5 font-mono text-teal-200">
                      <span className="text-zinc-500 uppercase text-[10px] block">{ord.query_type}</span>
                      {ord.query_value}
                    </td>
                    <td className="py-3 px-5 font-mono text-zinc-400">
                      <span className="px-2 py-0.5 rounded bg-zinc-900 border border-zinc-800 text-[11px]">
                        {ord.workflow_template}
                      </span>
                    </td>
                    <td className="py-3 px-5">
                      <span
                        className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                          isDone
                            ? "bg-teal-950 text-teal-400 border border-teal-800"
                            : isRunning
                            ? "bg-amber-950/80 text-amber-400 border border-amber-800 animate-pulse"
                            : isFailed
                            ? "bg-red-950 text-red-400 border border-red-800"
                            : isCancelled
                            ? "bg-zinc-900 text-zinc-500 border border-zinc-800"
                            : "bg-zinc-900 text-zinc-400 border border-zinc-800"
                        }`}
                      >
                        {isRunning && (
                          <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping" />
                        )}
                        {ord.status}
                      </span>
                    </td>
                    <td className="py-3 px-5 text-[11px] text-zinc-400 max-w-xs truncate">
                      {ord.error_message ? (
                        <span className="text-red-400" title={ord.error_message}>
                          {ord.error_message}
                        </span>
                      ) : isDone ? (
                        <span className="text-teal-400">Report & document ready</span>
                      ) : isRunning ? (
                        <span className="text-amber-300">Searching records...</span>
                      ) : (
                        <span className="text-zinc-500">Queued</span>
                      )}
                    </td>
                    <td className="py-3 px-5 text-right space-x-2 whitespace-nowrap">
                      {ord.run_id && (
                        <>
                          <Link
                            to={`/reports/run/${ord.run_id}`}
                            target="_blank"
                            className="px-2.5 py-1 rounded bg-teal-900/40 hover:bg-teal-900 border border-teal-700/50 text-teal-200 text-xs font-semibold inline-block transition-colors"
                          >
                            View Report
                          </Link>

                          <button
                            type="button"
                            onClick={() => ord.run_id && downloadOfficialDocument(ord.run_id)}
                            className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-semibold inline-block transition-colors"
                            title="Download official recorded PDF"
                          >
                            Deed PDF ↓
                          </button>

                          <Link
                            to={`/runs/${ord.run_id}`}
                            target="_blank"
                            className="px-2 py-1 rounded text-zinc-500 hover:text-zinc-300 text-xs inline-block"
                            title="View live run stream and logs"
                          >
                            Log ↗
                          </Link>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
