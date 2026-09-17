import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { BatchJob, listBatches } from "../api/client";
import NewBatchModal from "../components/batch/NewBatchModal";

export default function BatchDashboard() {
  const navigate = useNavigate();
  const [batches, setBatches] = useState<BatchJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);

  const fetchBatches = () => {
    listBatches()
      .then(setBatches)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchBatches();
    const interval = setInterval(fetchBatches, 4000);
    return () => clearInterval(interval);
  }, []);

  const totalOrders = batches.reduce((acc, b) => acc + (b.total_orders || 0), 0);
  const completedOrders = batches.reduce((acc, b) => acc + (b.completed_orders || 0), 0);
  const runningBatches = batches.filter((b) => b.status === "running").length;

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100 flex items-center gap-2.5">
            <svg className="w-6 h-6 text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
            Batch Orders Processing
          </h1>
          <p className="text-xs text-zinc-400 mt-1">
            Execute high-volume title searches in parallel across county portals
          </p>
        </div>

        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="px-4 py-2.5 rounded-xl bg-teal-600 hover:bg-teal-500 text-white text-xs font-bold shadow-lg shadow-teal-950/50 flex items-center gap-2 transition-all"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New Batch Order
        </button>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl bg-[#0f141c] border border-teal-900/40">
          <div className="text-[11px] text-zinc-500 uppercase tracking-wider font-semibold">Total Batches</div>
          <div className="text-2xl font-black text-zinc-100 mt-1">{batches.length}</div>
        </div>
        <div className="p-4 rounded-xl bg-[#0f141c] border border-teal-900/40">
          <div className="text-[11px] text-zinc-500 uppercase tracking-wider font-semibold">Orders Processed</div>
          <div className="text-2xl font-black text-teal-300 mt-1">{completedOrders} <span className="text-xs text-zinc-500 font-normal">/ {totalOrders}</span></div>
        </div>
        <div className="p-4 rounded-xl bg-[#0f141c] border border-teal-900/40">
          <div className="text-[11px] text-zinc-500 uppercase tracking-wider font-semibold">Active Batches</div>
          <div className="text-2xl font-black text-amber-400 mt-1">{runningBatches}</div>
        </div>
        <div className="p-4 rounded-xl bg-[#0f141c] border border-teal-900/40">
          <div className="text-[11px] text-zinc-500 uppercase tracking-wider font-semibold">Completion Rate</div>
          <div className="text-2xl font-black text-teal-400 mt-1">
            {totalOrders > 0 ? `${Math.round((completedOrders / totalOrders) * 100)}%` : "100%"}
          </div>
        </div>
      </div>

      {/* Batches Table */}
      <div className="bg-[#0f141c] border border-teal-900/40 rounded-2xl overflow-hidden shadow-xl">
        <div className="px-6 py-4 border-b border-teal-950 flex items-center justify-between">
          <h2 className="text-sm font-bold text-zinc-200">Recent Batch Jobs</h2>
          <span className="text-xs text-zinc-500">Auto-refreshes every 4s</span>
        </div>

        {loading && !batches.length ? (
          <div className="p-8 text-center text-xs text-zinc-500">Loading batches...</div>
        ) : !batches.length ? (
          <div className="p-12 text-center space-y-3">
            <p className="text-sm text-zinc-400">No batch orders created yet.</p>
            <button
              type="button"
              onClick={() => setModalOpen(true)}
              className="text-xs text-teal-400 hover:underline font-semibold"
            >
              + Launch your first batch order
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-zinc-300">
              <thead className="bg-[#0c1017] text-zinc-400 font-semibold border-b border-teal-950">
                <tr>
                  <th className="py-3 px-5">Batch Name</th>
                  <th className="py-3 px-5">Workflow</th>
                  <th className="py-3 px-5">Progress</th>
                  <th className="py-3 px-5">Status</th>
                  <th className="py-3 px-5">Workers</th>
                  <th className="py-3 px-5">Created</th>
                  <th className="py-3 px-5 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/40">
                {batches.map((b) => {
                  const pct = b.total_orders > 0 ? Math.round((b.completed_orders / b.total_orders) * 100) : 0;
                  return (
                    <tr key={b.id} className="hover:bg-zinc-900/40 transition-colors">
                      <td className="py-3 px-5 font-semibold text-zinc-100">
                        <Link to={`/batches/${b.id}`} className="hover:text-teal-300 transition-colors">
                          {b.name}
                        </Link>
                        <span className="block text-[10px] text-zinc-500 font-mono mt-0.5">{b.id}</span>
                      </td>
                      <td className="py-3 px-5 font-mono text-zinc-400">
                        <span className="px-2 py-0.5 rounded bg-zinc-900 border border-zinc-800 text-[11px]">
                          {b.workflow_template}
                        </span>
                      </td>
                      <td className="py-3 px-5 min-w-[140px]">
                        <div className="flex items-center justify-between text-[11px] mb-1 text-zinc-400">
                          <span>{b.completed_orders} / {b.total_orders}</span>
                          <span className="font-bold text-teal-300">{pct}%</span>
                        </div>
                        <div className="w-full bg-zinc-800 h-1.5 rounded-full overflow-hidden">
                          <div
                            className={`h-full transition-all duration-500 ${
                              b.status === "failed" ? "bg-red-500" : "bg-teal-500"
                            }`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </td>
                      <td className="py-3 px-5">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                            b.status === "completed"
                              ? "bg-teal-950 text-teal-400 border border-teal-800"
                              : b.status === "running"
                              ? "bg-amber-950/80 text-amber-400 border border-amber-800 animate-pulse"
                              : b.status === "partially_failed"
                              ? "bg-orange-950 text-orange-400 border border-orange-800"
                              : b.status === "failed"
                              ? "bg-red-950 text-red-400 border border-red-800"
                              : "bg-zinc-900 text-zinc-400 border border-zinc-800"
                          }`}
                        >
                          {b.status}
                        </span>
                      </td>
                      <td className="py-3 px-5 text-zinc-400">{b.concurrency} parallel</td>
                      <td className="py-3 px-5 text-zinc-500 text-[11px]">
                        {new Date(b.created_at).toLocaleString()}
                      </td>
                      <td className="py-3 px-5 text-right">
                        <Link
                          to={`/batches/${b.id}`}
                          className="px-3 py-1 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-semibold inline-block transition-colors"
                        >
                          Open Batch →
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* New Batch Modal */}
      <NewBatchModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={(id) => navigate(`/batches/${id}`)}
      />
    </div>
  );
}
