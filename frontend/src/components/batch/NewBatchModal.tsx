import React, { useEffect, useMemo, useState } from "react";
import {
  CountyOption,
  createBatch,
  getBatchTemplates,
  getCountiesForState,
  parseBatchCsv,
  WorkflowTemplate,
} from "../../api/client";
import { US_STATES } from "../../data/states";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (batchId: string) => void;
}

interface OrderRow {
  state: string;
  county: string;
  query_type: string;
  query_value: string;
  book_number?: string;
  page_number?: string;
  workflow_template?: string;
}

export default function NewBatchModal({ isOpen, onClose, onCreated }: Props) {
  const [activeTab, setActiveTab] = useState<"csv" | "manual">("csv");
  const [batchName, setBatchName] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState("recorder_deed");
  const [concurrency, setConcurrency] = useState(2);
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);

  // CSV Tab State
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [detectedOrders, setDetectedOrders] = useState<OrderRow[]>([]);
  const [parsingCsv, setParsingCsv] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);

  // Manual Tab State
  const [manualRows, setManualRows] = useState<OrderRow[]>([
    { state: "FL", county: "miami-dade", query_type: "book_page", query_value: "30189/4575", book_number: "30189", page_number: "4575" },
    { state: "FL", county: "miami-dade", query_type: "book_page", query_value: "29850/1200", book_number: "29850", page_number: "1200" },
  ]);

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [countiesByState, setCountiesByState] = useState<Record<string, CountyOption[]>>({});
  const [countiesLoading, setCountiesLoading] = useState<Record<string, boolean>>({});
  const [countiesError, setCountiesError] = useState<Record<string, string>>({});

  const manualStatesKey = useMemo(
    () => [...new Set(manualRows.map((r) => r.state))].sort().join("|"),
    [manualRows]
  );

  useEffect(() => {
    getBatchTemplates()
      .then(setTemplates)
      .catch(() => {});
  }, []);

  useEffect(() => {
    const uniqueStates = manualStatesKey ? manualStatesKey.split("|") : [];
    let cancelled = false;

    uniqueStates.forEach((stateCode) => {
      setCountiesLoading((prev) => ({ ...prev, [stateCode]: true }));
      setCountiesError((prev) => ({ ...prev, [stateCode]: "" }));

      getCountiesForState(stateCode)
        .then((list) => {
          if (cancelled) return;
          setCountiesByState((prev) => ({ ...prev, [stateCode]: list }));
          setManualRows((prev) =>
            prev.map((row) => {
              if (row.state !== stateCode) return row;
              if (list.some((c) => c.slug === row.county)) return row;
              return { ...row, county: list[0]?.slug ?? "" };
            })
          );
        })
        .catch((e) => {
          if (cancelled) return;
          setCountiesByState((prev) => ({ ...prev, [stateCode]: [] }));
          setCountiesError((prev) => ({
            ...prev,
            [stateCode]: e instanceof Error ? e.message : "Failed to load counties",
          }));
        })
        .finally(() => {
          if (!cancelled) {
            setCountiesLoading((prev) => ({ ...prev, [stateCode]: false }));
          }
        });
    });

    return () => {
      cancelled = true;
    };
  }, [manualStatesKey]);

  if (!isOpen) return null;

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setCsvFile(file);
    setParsingCsv(true);
    setParseError(null);
    try {
      const res = await parseBatchCsv(file);
      setDetectedOrders(res.orders);
    } catch (err) {
      setParseError(err instanceof Error ? err.message : "Failed to parse CSV");
      setDetectedOrders([]);
    } finally {
      setParsingCsv(false);
    }
  };

  const handleDownloadSampleCsv = () => {
    const csvContent =
      "State,County,Query_Type,Book,Page,Query_Value,Workflow\n" +
      "FL,miami-dade,book_page,30189,4575,,recorder_deed\n" +
      "FL,miami-dade,book_page,29850,1200,,recorder_deed\n" +
      "FL,miami-dade,parcel,,,01-3113-037-0010,full_title\n";
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", "sample_orders_template.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const addManualRow = () => {
    const state = "FL";
    const county = countiesByState[state]?.[0]?.slug ?? "";
    setManualRows((prev) => [
      ...prev,
      { state, county, query_type: "book_page", query_value: "", book_number: "", page_number: "" },
    ]);
  };

  const removeManualRow = (index: number) => {
    setManualRows((prev) => prev.filter((_, i) => i !== index));
  };

  const updateManualRow = (index: number, field: keyof OrderRow, val: string) => {
    setManualRows((prev) => {
      const copy = [...prev];
      copy[index] = { ...copy[index], [field]: val };
      if (field === "book_number" || field === "page_number") {
        const b = field === "book_number" ? val : copy[index].book_number || "";
        const p = field === "page_number" ? val : copy[index].page_number || "";
        if (b && p) copy[index].query_value = `${b.trim()}/${p.trim()}`;
      }
      return copy;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitError(null);
    const ordersToSubmit = activeTab === "csv" ? detectedOrders : manualRows;

    if (!ordersToSubmit.length) {
      setSubmitError(
        activeTab === "csv"
          ? "Please upload a valid CSV file with order rows."
          : "Please add at least one order in the table."
      );
      return;
    }

    if (activeTab === "manual" && ordersToSubmit.some((row) => !row.county.trim())) {
      setSubmitError("Please select a county for each order row.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await createBatch({
        name: batchName.trim() || undefined,
        workflow_template: selectedTemplate,
        concurrency,
        orders: ordersToSubmit,
      });
      onCreated(res.batch_id);
      onClose();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to create batch job");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="bg-[#0f141c] border border-teal-900/60 rounded-2xl w-full max-w-3xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-teal-950 bg-[#0c1017]">
          <div>
            <h2 className="text-lg font-bold text-zinc-100 flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-teal-400 animate-pulse" />
              New Multi-Order Batch
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">
              Process multiple title orders simultaneously across automated workflows
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-zinc-400 hover:text-zinc-100 p-1.5 rounded-lg hover:bg-zinc-800/60 transition-colors"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 space-y-5">
          {submitError && (
            <div className="p-3 rounded-lg bg-red-950/60 border border-red-800 text-red-300 text-xs">
              {submitError}
            </div>
          )}

          {/* Batch Name & Concurrency */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="md:col-span-2">
              <label className="block text-xs font-medium text-zinc-300 mb-1.5">Batch Name</label>
              <input
                type="text"
                placeholder="e.g. Miami-Dade Weekly Deed Ingestion"
                value={batchName}
                onChange={(e) => setBatchName(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-zinc-950 border border-teal-900/40 text-zinc-100 text-sm focus:border-teal-500 outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-zinc-300 mb-1.5">
                Worker Concurrency: <span className="text-teal-400 font-bold">{concurrency}</span>
              </label>
              <input
                type="range"
                min={1}
                max={4}
                value={concurrency}
                onChange={(e) => setConcurrency(Number(e.target.value))}
                className="w-full mt-2 accent-teal-500 cursor-pointer"
              />
              <span className="text-[11px] text-zinc-500 block text-right mt-0.5">1 to 4 parallel workers</span>
            </div>
          </div>

          {/* Workflow Template Selection */}
          <div>
            <label className="block text-xs font-medium text-zinc-300 mb-2">Default Workflow Pipeline</label>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {templates.map((tpl) => (
                <label
                  key={tpl.id}
                  className={`flex flex-col p-3 rounded-xl border cursor-pointer transition-all ${
                    selectedTemplate === tpl.id
                      ? "bg-teal-950/40 border-teal-500 text-zinc-100 shadow-sm"
                      : "bg-zinc-950/60 border-zinc-800/80 text-zinc-400 hover:border-zinc-700"
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-semibold text-xs text-zinc-200">{tpl.name}</span>
                    <input
                      type="radio"
                      name="workflow_template"
                      value={tpl.id}
                      checked={selectedTemplate === tpl.id}
                      onChange={() => setSelectedTemplate(tpl.id)}
                      className="accent-teal-500"
                    />
                  </div>
                  <p className="text-[11px] text-zinc-400 line-clamp-2 leading-relaxed">{tpl.description}</p>
                  <div className="mt-2 text-[10px] text-teal-400 font-mono">
                    {tpl.steps.join(" → ")}
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Input Method Tabs */}
          <div>
            <div className="flex items-center justify-between border-b border-zinc-800 pb-2 mb-3">
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setActiveTab("csv")}
                  className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
                    activeTab === "csv"
                      ? "bg-teal-600 text-white"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40"
                  }`}
                >
                  📁 CSV / Spreadsheet Upload
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("manual")}
                  className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
                    activeTab === "manual"
                      ? "bg-teal-600 text-white"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40"
                  }`}
                >
                  ✍ Manual Order Grid
                </button>
              </div>

              {activeTab === "csv" && (
                <button
                  type="button"
                  onClick={handleDownloadSampleCsv}
                  className="text-xs text-teal-400 hover:underline flex items-center gap-1"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Download Sample CSV
                </button>
              )}
            </div>

            {/* TAB 1: CSV Upload */}
            {activeTab === "csv" && (
              <div className="space-y-4">
                <div className="border-2 border-dashed border-teal-900/50 rounded-xl p-6 text-center hover:border-teal-500/60 transition-colors bg-zinc-950/30">
                  <input
                    type="file"
                    accept=".csv"
                    onChange={handleFileChange}
                    id="csv-upload"
                    className="hidden"
                  />
                  <label htmlFor="csv-upload" className="cursor-pointer flex flex-col items-center">
                    <svg className="w-8 h-8 text-teal-400 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                    <span className="text-xs font-semibold text-zinc-200">
                      {csvFile ? csvFile.name : "Click or drag CSV file to upload"}
                    </span>
                    <span className="text-[11px] text-zinc-500 mt-1">
                      Supports Book, Page, Parcel, Address, County, State columns
                    </span>
                  </label>
                </div>

                {parsingCsv && <p className="text-xs text-teal-400 animate-pulse">Parsing CSV rows...</p>}
                {parseError && <p className="text-xs text-red-400">{parseError}</p>}

                {detectedOrders.length > 0 && (
                  <div>
                    <div className="flex items-center justify-between text-xs text-zinc-400 mb-1.5">
                      <span>Detected <strong className="text-teal-300">{detectedOrders.length}</strong> orders</span>
                      <span>Previewing first 5 rows:</span>
                    </div>
                    <div className="border border-zinc-800 rounded-lg overflow-hidden max-h-48 overflow-y-auto">
                      <table className="w-full text-left text-[11px] text-zinc-300">
                        <thead className="bg-zinc-900 text-zinc-400 font-semibold border-b border-zinc-800">
                          <tr>
                            <th className="p-2">#</th>
                            <th className="p-2">State</th>
                            <th className="p-2">County</th>
                            <th className="p-2">Type</th>
                            <th className="p-2">Value / Book-Page</th>
                            <th className="p-2">Workflow</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800/60">
                          {detectedOrders.slice(0, 5).map((ord, idx) => (
                            <tr key={idx} className="hover:bg-zinc-900/40">
                              <td className="p-2 text-zinc-500">{idx + 1}</td>
                              <td className="p-2">{ord.state}</td>
                              <td className="p-2">{ord.county}</td>
                              <td className="p-2 font-mono text-zinc-400">{ord.query_type}</td>
                              <td className="p-2 font-mono text-teal-200">{ord.query_value || `${ord.book_number}/${ord.page_number}`}</td>
                              <td className="p-2 text-zinc-400">{ord.workflow_template || selectedTemplate}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* TAB 2: Manual Row Grid */}
            {activeTab === "manual" && (
              <div className="space-y-3">
                <div className="max-h-56 overflow-y-auto space-y-2 border border-zinc-800/80 rounded-xl p-3 bg-zinc-950/40">
                  {manualRows.map((row, idx) => (
                    <div key={idx} className="flex items-center gap-2 bg-zinc-900/60 p-2 rounded-lg border border-zinc-800">
                      <span className="text-xs text-zinc-500 font-mono w-5 text-center">{idx + 1}</span>
                      <select
                        value={row.state}
                        onChange={(e) => updateManualRow(idx, "state", e.target.value)}
                        className="px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-xs text-zinc-200"
                      >
                        {US_STATES.map((s) => (
                          <option key={s.code} value={s.code}>{s.code}</option>
                        ))}
                      </select>
                      <select
                        value={row.county}
                        onChange={(e) => updateManualRow(idx, "county", e.target.value)}
                        disabled={countiesLoading[row.state]}
                        title={countiesError[row.state] || undefined}
                        className="px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-xs text-zinc-200 w-36 disabled:opacity-60"
                      >
                        {countiesLoading[row.state] ? (
                          <option value="">Loading counties...</option>
                        ) : (countiesByState[row.state] ?? []).length === 0 ? (
                          <option value="">
                            {countiesError[row.state] ? "Failed to load" : "No counties"}
                          </option>
                        ) : (
                          (countiesByState[row.state] ?? []).map((c) => (
                            <option key={c.slug} value={c.slug}>{c.name}</option>
                          ))
                        )}
                      </select>
                      <select
                        value={row.query_type}
                        onChange={(e) => updateManualRow(idx, "query_type", e.target.value)}
                        className="px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-xs text-zinc-200"
                      >
                        <option value="book_page">Book / Page</option>
                        <option value="parcel">APN / Parcel</option>
                        <option value="address">Address</option>
                        <option value="owner">Owner</option>
                      </select>

                      {row.query_type === "book_page" ? (
                        <div className="flex gap-1 flex-1">
                          <input
                            type="text"
                            placeholder="Book"
                            value={row.book_number || ""}
                            onChange={(e) => updateManualRow(idx, "book_number", e.target.value)}
                            className="px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-xs text-zinc-200 w-1/2"
                          />
                          <input
                            type="text"
                            placeholder="Page"
                            value={row.page_number || ""}
                            onChange={(e) => updateManualRow(idx, "page_number", e.target.value)}
                            className="px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-xs text-zinc-200 w-1/2"
                          />
                        </div>
                      ) : (
                        <input
                          type="text"
                          placeholder="Search Value"
                          value={row.query_value}
                          onChange={(e) => updateManualRow(idx, "query_value", e.target.value)}
                          className="px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-xs text-zinc-200 flex-1"
                        />
                      )}

                      <button
                        type="button"
                        onClick={() => removeManualRow(idx)}
                        className="text-zinc-500 hover:text-red-400 p-1 text-xs"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>

                <button
                  type="button"
                  onClick={addManualRow}
                  className="text-xs text-teal-400 hover:text-teal-300 font-semibold flex items-center gap-1"
                >
                  + Add Another Order Row
                </button>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between pt-4 border-t border-teal-950">
            <span className="text-xs text-zinc-400">
              Total Orders: <strong className="text-teal-300 font-bold">{activeTab === "csv" ? detectedOrders.length : manualRows.length}</strong>
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-xs font-semibold text-zinc-300"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="px-5 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-xs font-bold text-white shadow-lg transition-all disabled:opacity-50 flex items-center gap-2"
              >
                {submitting ? (
                  <>
                    <span className="w-3 h-3 border border-white border-t-transparent rounded-full animate-spin" />
                    Queueing Batch...
                  </>
                ) : (
                  "Launch Batch Processing"
                )}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
