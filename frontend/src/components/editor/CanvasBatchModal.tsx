import React, { useEffect, useState } from "react";
import { US_STATES } from "../../data/states";
import { CountyOption, createCanvasBatch, getCountiesForState, parseBatchCsv } from "../../api/client";
import { PipelineGraph } from "../../lib/pipelineGraph";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  pipelineGraph: PipelineGraph;
  defaultState?: string;
  defaultCounty?: string;
  defaultQueryType?: string;
  onBatchStarted?: (batchId: string) => void;
}

export interface BatchItemRow {
  id: string;
  parcelNumber: string;
  address: string;
  bookPage?: string;
  ownerName?: string;
}

export default function CanvasBatchModal({
  isOpen,
  onClose,
  pipelineGraph,
  defaultState = "FL",
  defaultCounty = "miami-dade",
  defaultQueryType = "parcel",
  onBatchStarted,
}: Props) {
  const [batchName, setBatchName] = useState("");
  const [state, setState] = useState(defaultState || "FL");
  const [county, setCounty] = useState(defaultCounty || "miami-dade");
  const [concurrency, setConcurrency] = useState(1);
  const [counties, setCounties] = useState<CountyOption[]>([]);
  const [countiesLoading, setCountiesLoading] = useState(false);

  // Active Input Tab: "table" (structured rows), "paste" (multi-line paste), "csv" (file upload)
  const [activeTab, setActiveTab] = useState<"table" | "paste" | "csv">("table");

  // Structured table rows with Parcel Number & Address
  const [rows, setRows] = useState<BatchItemRow[]>([
    {
      id: "row-1",
      parcelNumber: "30-4109-001-0100",
      address: "1450 Brickell Ave, Miami FL 33131",
      bookPage: "30189/4575",
    },
    {
      id: "row-2",
      parcelNumber: "01-4138-006-2180",
      address: "200 S Biscayne Blvd, Miami FL 33131",
      bookPage: "29850/1200",
    },
  ]);

  // Quick multi-line paste states
  const [pasteParcels, setPasteParcels] = useState("30-4109-001-0100\n01-4138-006-2180\n01-3136-000-0010");
  const [pasteAddresses, setPasteAddresses] = useState("1450 Brickell Ave, Miami FL\n200 S Biscayne Blvd, Miami FL\n801 Brickell Bay Dr, Miami FL");

  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [parsingCsv, setParsingCsv] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successBatchId, setSuccessBatchId] = useState<string | null>(null);

  // Fetch counties dynamically from API whenever modal is opened or state changes
  useEffect(() => {
    if (!isOpen || !state) return;
    let cancelled = false;
    setCountiesLoading(true);

    getCountiesForState(state)
      .then((list) => {
        if (cancelled) return;
        setCounties(list);
        if (list.length > 0) {
          const currentValid = list.some((c) => c.slug === county);
          if (!currentValid) {
            const preferMiami = state.toUpperCase() === "FL" && list.some((c) => c.slug === "miami-dade");
            setCounty(preferMiami ? "miami-dade" : list[0].slug);
          }
        }
      })
      .catch((err) => {
        if (!cancelled) {
          console.error("Failed to load counties for state:", err);
          setCounties([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setCountiesLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [isOpen, state]);

  if (!isOpen) return null;

  // Add empty row
  const addRow = () => {
    setRows((prev) => [
      ...prev,
      {
        id: `row-${Date.now()}-${Math.random()}`,
        parcelNumber: "",
        address: "",
        bookPage: "",
      },
    ]);
  };

  // Remove row
  const removeRow = (id: string) => {
    setRows((prev) => (prev.length > 1 ? prev.filter((r) => r.id !== id) : prev));
  };

  // Update specific row field
  const updateRow = (id: string, field: keyof BatchItemRow, value: string) => {
    setRows((prev) =>
      prev.map((r) => (r.id === id ? { ...r, [field]: value } : r))
    );
  };

  // Sync quick paste text into rows
  const applyQuickPaste = () => {
    const parcelLines = pasteParcels.split(/\r?\n/).map((s) => s.trim());
    const addressLines = pasteAddresses.split(/\r?\n/).map((s) => s.trim());
    const maxLen = Math.max(parcelLines.filter(Boolean).length, addressLines.filter(Boolean).length);

    if (maxLen === 0) {
      setError("Please paste at least one parcel number or property address.");
      return;
    }

    const newRows: BatchItemRow[] = [];
    for (let i = 0; i < maxLen; i++) {
      const p = parcelLines[i] || "";
      const a = addressLines[i] || "";
      if (p || a) {
        newRows.push({
          id: `row-${Date.now()}-${i}`,
          parcelNumber: p,
          address: a,
          bookPage: "",
        });
      }
    }
    setRows(newRows);
    setActiveTab("table");
    setError(null);
  };

  // CSV upload handler
  const handleCsvUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setCsvFile(file);
    setParsingCsv(true);
    setError(null);
    try {
      const res = await parseBatchCsv(file);
      if (res.orders && res.orders.length > 0) {
        const newRows: BatchItemRow[] = res.orders.map((o, idx) => ({
          id: `csv-${Date.now()}-${idx}`,
          parcelNumber: o.parcel_number || o.parcel || (o.query_type === "parcel" ? o.query_value : "") || "",
          address: o.address || (o.query_type === "address" ? o.query_value : "") || "",
          bookPage: o.book_number && o.page_number ? `${o.book_number}/${o.page_number}` : (o.query_type === "book_page" ? o.query_value : "") || "",
          ownerName: o.owner_name || o.owner || "",
        }));
        if (newRows.length > 0) {
          setRows(newRows);
          setActiveTab("table");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to parse CSV");
    } finally {
      setParsingCsv(false);
    }
  };

  // Compute total valid items
  const validItemsCount = rows.filter(
    (r) => r.parcelNumber.trim() || r.address.trim() || (r.bookPage && r.bookPage.trim())
  ).length;

  const handleRunBatch = async () => {
    const itemsToSubmit = rows
      .filter((r) => r.parcelNumber.trim() || r.address.trim() || (r.bookPage && r.bookPage.trim()))
      .map((r) => {
        const p = r.parcelNumber.trim();
        const a = r.address.trim();
        const bp = r.bookPage ? r.bookPage.trim() : "";
        const qVal = p || a || bp;
        const qType = p ? "parcel" : a ? "address" : "book_page";
        const bpParts = bp.includes("/") ? bp.split("/") : null;

        return {
          parcel_number: p || undefined,
          address: a || undefined,
          query_value: qVal,
          query_type: qType,
          book_number: bpParts ? bpParts[0].trim() : undefined,
          page_number: bpParts ? bpParts[1].trim() : undefined,
          owner_name: r.ownerName ? r.ownerName.trim() : undefined,
        };
      });

    if (itemsToSubmit.length === 0) {
      setError("Please provide at least one parcel number or property address for the batch.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const result = await createCanvasBatch({
        name: batchName.trim() || `Canvas Batch (${itemsToSubmit.length} properties)`,
        state: state.toUpperCase(),
        county: county.toLowerCase(),
        query_type: "parcel",
        items: itemsToSubmit as any,
        custom_graph: pipelineGraph,
        concurrency,
      });
      setSuccessBatchId(result.batch_id);
      if (onBatchStarted) {
        onBatchStarted(result.batch_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit batch execution.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="relative w-full max-w-2xl bg-white dark:bg-[#161b22] border border-slate-200 dark:border-white/[0.1] rounded-2xl shadow-2xl p-6 text-slate-900 dark:text-zinc-100 transition-all">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-200 dark:border-white/[0.08]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-violet-600/20 text-violet-400 flex items-center justify-center font-bold text-sm">
              ✦
            </div>
            <div>
              <h2 className="text-base font-bold leading-tight">Run Batch Pipeline</h2>
              <p className="text-xs text-slate-500 dark:text-zinc-400">
                Execute this pipeline across multiple properties with Parcel Number & Address
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-zinc-200 p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-zinc-800 text-sm transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Success state */}
        {successBatchId ? (
          <div className="py-6 text-center space-y-4">
            <div className="w-12 h-12 rounded-full bg-emerald-500/20 text-emerald-400 mx-auto flex items-center justify-center text-xl font-bold">
              ✓
            </div>
            <div>
              <h3 className="text-lg font-bold text-emerald-600 dark:text-emerald-400">
                Batch Job Queued Successfully!
              </h3>
              <p className="text-xs text-slate-600 dark:text-zinc-400 mt-1 max-w-md mx-auto">
                Dispatched {validItemsCount} properties with parcel numbers and addresses to the pipeline.
              </p>
            </div>
            <div className="flex items-center justify-center gap-3 pt-2">
              <a
                href={`/batches/${successBatchId}`}
                className="px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-500 text-white font-semibold text-xs transition-colors shadow-lg shadow-violet-600/25 flex items-center gap-1.5"
              >
                <span>View Batch Progress</span>
                <span>→</span>
              </a>
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-xl bg-slate-100 dark:bg-zinc-800 hover:bg-slate-200 dark:hover:bg-zinc-700 text-xs font-semibold transition-colors"
              >
                Close & Return to Canvas
              </button>
            </div>
          </div>
        ) : (
          /* Form state */
          <div className="py-4 space-y-4 text-xs">
            {error && (
              <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-500 dark:text-red-400">
                {error}
              </div>
            )}

            {/* Batch Name & Concurrency */}
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="block font-semibold mb-1 text-slate-700 dark:text-zinc-300">
                  Batch Job Name (Optional)
                </label>
                <input
                  type="text"
                  value={batchName}
                  onChange={(e) => setBatchName(e.target.value)}
                  placeholder={`Batch ${new Date().toLocaleDateString()}`}
                  className="w-full rounded-xl bg-slate-50 dark:bg-zinc-900 border border-slate-200 dark:border-white/[0.08] px-3 py-2 text-xs text-slate-900 dark:text-zinc-100 focus:outline-none focus:border-violet-500"
                />
              </div>

              <div>
                <label className="block font-semibold mb-1 text-slate-700 dark:text-zinc-300">
                  Workers
                </label>
                <select
                  value={concurrency}
                  onChange={(e) => setConcurrency(Number(e.target.value))}
                  className="w-full rounded-xl bg-slate-50 dark:bg-zinc-900 border border-slate-200 dark:border-white/[0.08] px-2.5 py-2 text-xs focus:outline-none focus:border-violet-500"
                >
                  <option value={1}>1 (Safe Browser)</option>
                  <option value={2}>2 (Fast)</option>
                  <option value={3}>3 (Max)</option>
                </select>
              </div>
            </div>

            {/* State & County Row (API Powered) */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block font-semibold mb-1 text-slate-700 dark:text-zinc-300">State</label>
                <select
                  value={state}
                  onChange={(e) => setState(e.target.value)}
                  className="w-full rounded-xl bg-slate-50 dark:bg-zinc-900 border border-slate-200 dark:border-white/[0.08] px-2.5 py-2 text-xs focus:outline-none focus:border-violet-500 font-medium"
                >
                  {US_STATES.map((s) => (
                    <option key={s.code} value={s.code}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block font-semibold text-slate-700 dark:text-zinc-300">County</label>
                  {countiesLoading && (
                    <span className="text-[10px] text-violet-500 animate-pulse font-normal">Loading API...</span>
                  )}
                </div>
                <select
                  value={county}
                  disabled={countiesLoading && counties.length === 0}
                  onChange={(e) => setCounty(e.target.value)}
                  className="w-full rounded-xl bg-slate-50 dark:bg-zinc-900 border border-slate-200 dark:border-white/[0.08] px-2.5 py-2 text-xs focus:outline-none focus:border-violet-500 disabled:opacity-60 font-medium"
                >
                  {countiesLoading && counties.length === 0 ? (
                    <option value="">Loading counties from API...</option>
                  ) : counties.length > 0 ? (
                    counties.map((c) => (
                      <option key={c.slug} value={c.slug}>
                        {c.name}
                      </option>
                    ))
                  ) : (
                    <option value="miami-dade">Miami-Dade</option>
                  )}
                </select>
              </div>
            </div>

            {/* Mode Tabs: Table Editor vs Quick Paste vs CSV Upload */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-1.5 p-1 rounded-xl bg-slate-100 dark:bg-zinc-900 border border-slate-200 dark:border-white/[0.06]">
                  <button
                    type="button"
                    onClick={() => setActiveTab("table")}
                    className={`px-3 py-1.5 rounded-lg font-semibold transition-all ${
                      activeTab === "table"
                        ? "bg-white dark:bg-zinc-800 text-violet-700 dark:text-violet-300 shadow-sm"
                        : "text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-200"
                    }`}
                  >
                    Structured Table ({rows.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab("paste")}
                    className={`px-3 py-1.5 rounded-lg font-semibold transition-all ${
                      activeTab === "paste"
                        ? "bg-white dark:bg-zinc-800 text-violet-700 dark:text-violet-300 shadow-sm"
                        : "text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-200"
                    }`}
                  >
                    Quick Multi-Line Paste
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab("csv")}
                    className={`px-3 py-1.5 rounded-lg font-semibold transition-all ${
                      activeTab === "csv"
                        ? "bg-white dark:bg-zinc-800 text-violet-700 dark:text-violet-300 shadow-sm"
                        : "text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-200"
                    }`}
                  >
                    Upload CSV
                  </button>
                </div>

                <span className="text-[11px] px-2.5 py-1 rounded-full bg-violet-100 dark:bg-violet-950/80 text-violet-700 dark:text-violet-300 font-bold border border-violet-200 dark:border-violet-800/40">
                  {validItemsCount} {validItemsCount === 1 ? "Property" : "Properties"} Ready
                </span>
              </div>

              {/* Tab 1: Structured Table Editor with Parcel Number & Address */}
              {activeTab === "table" && (
                <div className="space-y-2">
                  <div className="max-h-[260px] overflow-y-auto rounded-xl border border-slate-200 dark:border-white/[0.08] bg-slate-50 dark:bg-zinc-950/40">
                    <table className="w-full text-left border-collapse text-[11px]">
                      <thead>
                        <tr className="border-b border-slate-200 dark:border-white/[0.08] bg-slate-100/70 dark:bg-zinc-900 text-slate-500 dark:text-zinc-400 font-bold uppercase tracking-wider">
                          <th className="py-2 px-3 w-10 text-center">#</th>
                          <th className="py-2 px-3">Parcel / APN Number</th>
                          <th className="py-2 px-3">Property Address</th>
                          <th className="py-2 px-3 w-28">Book / Page</th>
                          <th className="py-2 px-2 w-8 text-center"></th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-200 dark:divide-white/[0.06]">
                        {rows.map((r, idx) => (
                          <tr key={r.id} className="hover:bg-slate-100/50 dark:hover:bg-zinc-900/50 transition-colors">
                            <td className="py-1.5 px-3 text-center text-slate-400 dark:text-zinc-500 font-mono">
                              {idx + 1}
                            </td>
                            <td className="py-1.5 px-2">
                              <input
                                type="text"
                                value={r.parcelNumber}
                                onChange={(e) => updateRow(r.id, "parcelNumber", e.target.value)}
                                placeholder="e.g. 30-4109-001-0100"
                                className="w-full rounded-lg bg-white dark:bg-zinc-900 border border-slate-200 dark:border-white/[0.08] px-2.5 py-1 text-xs text-slate-900 dark:text-zinc-100 focus:outline-none focus:border-violet-500 font-mono"
                              />
                            </td>
                            <td className="py-1.5 px-2">
                              <input
                                type="text"
                                value={r.address}
                                onChange={(e) => updateRow(r.id, "address", e.target.value)}
                                placeholder="e.g. 1450 Brickell Ave, Miami FL"
                                className="w-full rounded-lg bg-white dark:bg-zinc-900 border border-slate-200 dark:border-white/[0.08] px-2.5 py-1 text-xs text-slate-900 dark:text-zinc-100 focus:outline-none focus:border-violet-500"
                              />
                            </td>
                            <td className="py-1.5 px-2">
                              <input
                                type="text"
                                value={r.bookPage || ""}
                                onChange={(e) => updateRow(r.id, "bookPage", e.target.value)}
                                placeholder="30189/4575"
                                className="w-full rounded-lg bg-white dark:bg-zinc-900 border border-slate-200 dark:border-white/[0.08] px-2 py-1 text-xs text-slate-900 dark:text-zinc-100 focus:outline-none focus:border-violet-500 font-mono"
                              />
                            </td>
                            <td className="py-1.5 px-2 text-center">
                              <button
                                type="button"
                                onClick={() => removeRow(r.id)}
                                className="text-slate-400 hover:text-red-500 p-1 rounded transition-colors"
                                title="Remove row"
                              >
                                ✕
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="flex items-center justify-between pt-1">
                    <button
                      type="button"
                      onClick={addRow}
                      className="px-3 py-1.5 rounded-lg border border-violet-500/40 hover:border-violet-500 text-violet-600 dark:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-950/30 text-xs font-bold transition-all flex items-center gap-1.5"
                    >
                      <span>+ Add Another Property</span>
                    </button>
                    <span className="text-[10px] text-slate-500 dark:text-zinc-400">
                      Provide either Parcel Number, Property Address, or both.
                    </span>
                  </div>
                </div>
              )}

              {/* Tab 2: Quick Multi-Line Paste for Parcels & Addresses */}
              {activeTab === "paste" && (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block font-semibold mb-1 text-slate-700 dark:text-zinc-300">
                        Parcel / APN Numbers (One per line)
                      </label>
                      <textarea
                        rows={6}
                        value={pasteParcels}
                        onChange={(e) => setPasteParcels(e.target.value)}
                        placeholder="30-4109-001-0100&#10;01-4138-006-2180&#10;01-3136-000-0010"
                        className="w-full rounded-xl bg-slate-50 dark:bg-zinc-900 border border-slate-200 dark:border-white/[0.08] p-2.5 text-xs font-mono text-slate-900 dark:text-zinc-100 focus:outline-none focus:border-violet-500 resize-y"
                      />
                    </div>
                    <div>
                      <label className="block font-semibold mb-1 text-slate-700 dark:text-zinc-300">
                        Property Addresses (One per line)
                      </label>
                      <textarea
                        rows={6}
                        value={pasteAddresses}
                        onChange={(e) => setPasteAddresses(e.target.value)}
                        placeholder="1450 Brickell Ave, Miami FL&#10;200 S Biscayne Blvd, Miami FL&#10;801 Brickell Bay Dr, Miami FL"
                        className="w-full rounded-xl bg-slate-50 dark:bg-zinc-900 border border-slate-200 dark:border-white/[0.08] p-2.5 text-xs text-slate-900 dark:text-zinc-100 focus:outline-none focus:border-violet-500 resize-y"
                      />
                    </div>
                  </div>
                  <div className="flex items-center justify-between">
                    <p className="text-[10px] text-slate-500 dark:text-zinc-400">
                      Corresponding lines will be matched together as property pairs.
                    </p>
                    <button
                      type="button"
                      onClick={applyQuickPaste}
                      className="px-3.5 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 text-white font-semibold text-xs transition-colors"
                    >
                      Apply to Property Table →
                    </button>
                  </div>
                </div>
              )}

              {/* Tab 3: CSV Upload */}
              {activeTab === "csv" && (
                <div className="border border-dashed border-slate-300 dark:border-zinc-700 rounded-xl p-6 text-center bg-slate-50/50 dark:bg-zinc-900/40">
                  <input
                    type="file"
                    accept=".csv"
                    onChange={handleCsvUpload}
                    className="hidden"
                    id="batch-csv-upload-input"
                  />
                  <label
                    htmlFor="batch-csv-upload-input"
                    className="cursor-pointer inline-flex flex-col items-center gap-2"
                  >
                    <div className="w-10 h-10 rounded-full bg-violet-600/10 text-violet-500 flex items-center justify-center text-lg">
                      📄
                    </div>
                    <div>
                      <span className="font-semibold text-violet-600 dark:text-violet-400 hover:underline">
                        Choose CSV File
                      </span>{" "}
                      <span className="text-slate-500 dark:text-zinc-400">to upload</span>
                    </div>
                    <p className="text-[10px] text-slate-400">
                      Columns recognized: <code>parcel</code>, <code>address</code>, <code>book</code>, <code>page</code>, <code>owner</code>
                    </p>
                  </label>
                  {parsingCsv && <p className="text-xs text-violet-400 mt-2">Parsing CSV file...</p>}
                  {csvFile && !parsingCsv && (
                    <p className="text-xs text-emerald-400 mt-2">Loaded: {csvFile.name}</p>
                  )}
                </div>
              )}
            </div>

            {/* Actions */}
            <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-slate-200 dark:border-white/[0.08]">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 dark:text-zinc-400 hover:bg-slate-100 dark:hover:bg-zinc-800 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={loading || validItemsCount === 0}
                onClick={handleRunBatch}
                className="px-5 py-2 rounded-xl text-xs font-bold text-white bg-violet-600 hover:bg-violet-500 disabled:opacity-50 transition-all shadow-lg shadow-violet-600/30 flex items-center gap-2"
              >
                {loading ? (
                  <>
                    <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    <span>Queueing Batch...</span>
                  </>
                ) : (
                  <>
                    <span>⚡ Run Batch ({validItemsCount} Properties)</span>
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
