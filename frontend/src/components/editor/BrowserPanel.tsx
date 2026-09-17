import { useEffect, useMemo, useRef, useState } from "react";
import {
  getRunPreviewUrl,
  sendPreviewClick,
  RunDetail,
  RunEvent,
  PipelineGraph,
  CountyOption,
  getCountiesForState,
  downloadReportPdf,
  downloadOfficialDocument,
  generatePlaywrightInstructions,
  QueryType,
} from "../../api/client";
import { graphNodesForStatus } from "../../lib/pipelineGraph";
import { deriveNodeStatus } from "../../lib/pipelineStatus";
import { PipelineNodeData } from "../../lib/defaultPipeline";
import { US_STATES } from "../../data/states";
import { useReactFlow } from "@xyflow/react";
import { useTheme } from "../../context/ThemeContext";

interface Props {
  runId?: string | null;
  pipelineGraph?: PipelineGraph | null;
  runDetail?: RunDetail | null;
  events?: RunEvent[];
  connected?: boolean;
  liveFrame?: string | null;
  selectedNodeId?: string | null;
  selectedNodeData?: PipelineNodeData | null;
  onClose?: () => void;
  /** Increments each time Run Pipeline is clicked — triggers Output tab switch */
  runTrigger?: number;
  onSave?: () => Promise<unknown> | void;
  isSaving?: boolean;
  isSaved?: boolean;
}

type PanelTab = "configuration" | "testData" | "output" | "logs";

const fieldClass =
  "w-full rounded-lg bg-slate-50 dark:bg-zinc-900/80 border border-slate-200 dark:border-white/[0.08] px-3 py-2 text-xs text-slate-900 dark:text-zinc-200 focus:border-violet-500/60 focus:outline-none transition-colors placeholder:text-slate-400 dark:placeholder:text-zinc-600";

const labelClass = "block text-[11px] font-semibold text-slate-500 dark:text-zinc-400 mb-1.5 uppercase tracking-wider";

// ─────────────────────────────────────────────────────────────────────────────
// Configuration Tab — fully self-contained, patches ReactFlow node on every change
// ─────────────────────────────────────────────────────────────────────────────
function ConfigurationTab({
  canvasId,
  nodeId,
  data,
}: {
  canvasId: string;
  nodeId: string;
  data: PipelineNodeData;
}) {
  const { isDark } = useTheme();
  const { setNodes } = useReactFlow();

  const fieldClass = isDark
    ? "w-full rounded-lg bg-zinc-900/80 border border-white/[0.08] px-3 py-2 text-xs text-zinc-200 focus:border-violet-500/60 focus:outline-none transition-colors placeholder:text-zinc-600"
    : "w-full rounded-lg bg-slate-50 border border-slate-300 px-3 py-2 text-xs text-slate-900 focus:border-violet-600 focus:outline-none transition-colors placeholder:text-slate-400 font-medium shadow-sm";

  const labelClass = isDark
    ? "block text-[11px] font-semibold text-zinc-400 mb-1.5 uppercase tracking-wider"
    : "block text-[11px] font-bold text-slate-700 mb-1.5 uppercase tracking-wider";

  // Patch helper — writes directly to ReactFlow state
  const patch = (fields: Partial<PipelineNodeData>) => {
    setNodes((nds) =>
      nds.map((n) =>
        n.id === canvasId ? { ...n, data: { ...n.data, ...fields } } : n
      )
    );
  };

  const [counties, setCounties] = useState<CountyOption[]>([]);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [layoutType, setLayoutType] = useState<string | null>(null);

  const isInput = nodeId === "input";
  const isReport = nodeId === "report";
  const showUrl = ["netr", "assessor", "recorder", "gis", "tax"].includes(nodeId);
  const showNotes = ["netr", "assessor", "recorder", "gis", "tax", "platform", "normalizer"].includes(nodeId);
  const showAiGenerate = ["netr", "assessor", "recorder", "gis", "tax"].includes(nodeId);

  const rawQType = (data.queryType as QueryType) || "owner";
  const hasAddr = Boolean((data.address as string)?.trim());
  const hasOwn = Boolean((data.ownerName as string)?.trim());
  const hasParc = Boolean((data.parcelNumber as string)?.trim());
  const hasBkPg = Boolean((data.bookNumber as string)?.trim() || (data.pageNumber as string)?.trim());

  let qType: QueryType = rawQType;
  if (rawQType === "owner" && !hasOwn && hasAddr) {
    qType = "address";
  } else if (rawQType === "owner" && !hasOwn && hasParc) {
    qType = "parcel";
  } else if (rawQType === "owner" && !hasOwn && hasBkPg) {
    qType = "book_page";
  }

  // Load counties when state changes
  useEffect(() => {
    if (!isInput || !data.state) return;
    let cancelled = false;
    getCountiesForState(data.state)
      .then((list) => {
        if (cancelled) return;
        setCounties(list);
        if (!list.some((c) => c.slug === (data.county || ""))) {
          patch({ county: list[0]?.slug ?? "" });
        }
      })
      .catch(() => { if (!cancelled) setCounties([]); });
    return () => { cancelled = true; };
  }, [isInput, data.state]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleGenerateInstructions() {
    setGenerating(true);
    setGenerateError(null);
    setLayoutType(null);
    try {
      const result = await generatePlaywrightInstructions({
        node_id: nodeId,
        state: (data.state || "FL").toUpperCase(),
        county: (data.county || "").toLowerCase(),
        query_type: qType,
        url: data.url?.trim() || undefined,
        query_value: data.queryValue?.trim() || "",
        playwright_notes: data.playwrightNotes?.trim() || undefined,
      });
      patch({
        playwrightNotes: result.instructions,
        ...(showUrl && !data.url?.trim() && result.resolved_url ? { url: result.resolved_url } : {}),
      });
      setLayoutType(result.layout_type);
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  }

  // ── Report node ────────────────────────────────────────────────────────────
  if (isReport) {
    return (
      <div className="space-y-3 p-4">
        <p className="text-xs text-zinc-400">Generates a PDF from collected property records.</p>
        {data.reportStatus === "generating" && (
          <div className="flex items-center gap-2 text-amber-400 text-xs">
            <div className="w-3.5 h-3.5 rounded-full border-2 border-amber-400 border-t-transparent animate-spin" />
            Generating report...
          </div>
        )}
        {data.reportStatus === "ready" && data.reportId && (
          <div className="space-y-2">
            <a href={`/reports/run/${data.reportRunId || ""}`} target="_blank" rel="noreferrer"
              className="block w-full text-center px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-xs font-semibold transition-colors">
              View Report
            </a>
            <button type="button"
              onClick={async () => {
                if (!data.reportId || !data.reportRunId) return;
                try { await downloadReportPdf(String(data.reportId), String(data.reportRunId)); }
                catch (err) { alert(err instanceof Error ? err.message : "Download failed"); }
              }}
              className="block w-full text-center px-3 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 border border-white/[0.08] text-zinc-200 text-xs font-semibold transition-colors">
              Download PDF
            </button>
            <button type="button"
              onClick={async () => {
                if (!data.reportRunId) return;
                try { await downloadOfficialDocument(String(data.reportRunId)); }
                catch (err) { alert(err instanceof Error ? err.message : "Failed"); }
              }}
              className="block w-full text-center px-3 py-2 rounded-lg bg-teal-900/60 hover:bg-teal-900 border border-teal-600/50 text-teal-200 text-xs font-semibold transition-colors">
              Download Official Document
            </button>
          </div>
        )}
        {data.reportStatus === "failed" && <p className="text-red-400 text-xs">Report generation failed.</p>}
        {(!data.reportStatus || data.reportStatus === "idle") && <p className="text-zinc-600 text-xs italic">Run the pipeline to generate a report.</p>}
      </div>
    );
  }

  // ── Input node ─────────────────────────────────────────────────────────────
  if (isInput) {
    return (
      <div className="p-4 space-y-4 overflow-y-auto">

        {/* Query Type */}
        <div>
          <label className={labelClass}>Query Type</label>
          <select
            value={qType}
            onChange={(e) => {
              const newType = e.target.value as QueryType;
              let newQueryVal = "";
              if (newType === "owner") newQueryVal = (data.ownerName as string) || "";
              else if (newType === "address") newQueryVal = (data.address as string) || "";
              else if (newType === "parcel") newQueryVal = (data.parcelNumber as string) || "";
              else if (newType === "book_page") {
                const b = (data.bookNumber as string) || "";
                const p = (data.pageNumber as string) || "";
                newQueryVal = b && p ? `${b}/${p}` : (b || p || "");
              }
              patch({ queryType: newType, queryValue: newQueryVal });
            }}
            className={fieldClass}
          >
            <option value="owner">Owner Name</option>
            <option value="address">Address</option>
            <option value="parcel">Parcel Number</option>
            <option value="book_page">Book / Page</option>
          </select>
        </div>

        {/* State */}
        <div>
          <label className={labelClass}>State</label>
          <select value={data.state || "AZ"} onChange={(e) => patch({ state: e.target.value })} className={fieldClass}>
            {US_STATES.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
          </select>
        </div>

        {/* County */}
        <div>
          <label className={labelClass}>County</label>
          <select value={data.county || ""} onChange={(e) => patch({ county: e.target.value })} className={fieldClass}>
            {counties.length === 0 && <option value="">Loading...</option>}
            {counties.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
          </select>
        </div>

        {/* Owner Name — optional */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className={labelClass}>Owner / Party Name</label>
            <span className="text-[10px] text-zinc-500 font-normal">Optional</span>
          </div>
          <input
            value={(data.ownerName as string) || ""}
            onChange={(e) => {
              const val = e.target.value;
              patch({
                ownerName: val,
                queryType: "owner",
                queryValue: val,
              });
            }}
            placeholder="e.g. John Smith"
            className={fieldClass}
          />
        </div>

        {/* Address — optional */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className={labelClass}>Property Address</label>
            <span className="text-[10px] text-zinc-500 font-normal">Optional</span>
          </div>
          <input
            value={(data.address as string) || ""}
            onChange={(e) => {
              const val = e.target.value;
              patch({
                address: val,
                queryType: "address",
                queryValue: val,
              });
            }}
            placeholder="e.g. 123 Main St, Miami FL 33101"
            className={fieldClass}
          />
        </div>

        {/* Parcel Number — optional */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className={labelClass}>Parcel / APN Number</label>
            <span className="text-[10px] text-zinc-500 font-normal">Optional</span>
          </div>
          <input
            value={(data.parcelNumber as string) || ""}
            onChange={(e) => {
              const val = e.target.value;
              patch({
                parcelNumber: val,
                queryType: "parcel",
                queryValue: val,
              });
            }}
            placeholder="e.g. 30189.4575"
            className={fieldClass}
          />
        </div>

        {/* Book / Page — optional */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className={labelClass}>Book &amp; Page</label>
            <span className="text-[10px] text-zinc-500 font-normal">Optional</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-zinc-500 block mb-1 font-medium">Book #</label>
              <input
                value={(data.bookNumber as string) || ""}
                onChange={(e) => {
                  const b = e.target.value;
                  const p = (data.pageNumber as string) || "";
                  patch({
                    bookNumber: b,
                    queryType: "book_page",
                    queryValue: b && p ? `${b}/${p}` : b || p,
                  });
                }}
                placeholder="e.g. 1494"
                className={fieldClass}
              />
            </div>
            <div>
              <label className="text-[10px] text-zinc-500 block mb-1 font-medium">Page #</label>
              <input
                value={(data.pageNumber as string) || ""}
                onChange={(e) => {
                  const p = e.target.value;
                  const b = (data.bookNumber as string) || "";
                  patch({
                    pageNumber: p,
                    queryType: "book_page",
                    queryValue: b && p ? `${b}/${p}` : b || p,
                  });
                }}
                placeholder="e.g. 2483"
                className={fieldClass}
              />
            </div>
          </div>
        </div>

        {/* Search Limit */}
        <div>
          <label className={labelClass}>Search Limit</label>
          <select
            value={(data.searchLimit as number) || 1}
            onChange={(e) => patch({ searchLimit: Number(e.target.value) })}
            className={fieldClass}
          >
            <option value={1}>1</option>
            <option value={5}>5</option>
            <option value={10}>10</option>
            <option value={25}>25</option>
          </select>
        </div>
      </div>
    );
  }

  // ── Other pipeline nodes ───────────────────────────────────────────────────
  return (
    <div className="p-4 space-y-4 overflow-y-auto">
      {showUrl && (
        <div>
          <label className={labelClass}>URL</label>
          <input
            value={data.url ?? ""}
            onChange={(e) => patch({ url: e.target.value })}
            placeholder="https://... (leave empty for auto-detection)"
            className={fieldClass}
          />
        </div>
      )}

      {showNotes && (
        <div>
          {showAiGenerate && (
            <div className="mb-3 space-y-2">
              <button
                type="button"
                disabled={generating}
                onClick={handleGenerateInstructions}
                className="w-full px-3 py-2 rounded-lg bg-violet-700 hover:bg-violet-600 disabled:opacity-50 text-white text-xs font-semibold transition-colors flex items-center justify-center gap-2"
              >
                {generating ? (
                  <><div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" /> Generating…</>
                ) : (
                  <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg> Generate with AI</>
                )}
              </button>
              {layoutType && <p className="text-[10px] text-zinc-500">Layout: {layoutType.replace(/_/g, " ")}</p>}
              {generateError && <p className="text-[10px] text-red-400">{generateError}</p>}
            </div>
          )}
          <label className={labelClass}>Playwright Instructions</label>
          <textarea
            value={data.playwrightNotes ?? ""}
            onChange={(e) => patch({ playwrightNotes: e.target.value })}
            placeholder='Click "Generate with AI" or write steps manually'
            rows={6}
            className={`${fieldClass} resize-y min-h-[80px]`}
          />
        </div>
      )}

      {!showUrl && !showNotes && !isReport && (
        <p className="text-zinc-600 text-xs italic">Auto — no manual inputs required.</p>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Right Config Panel
// ─────────────────────────────────────────────────────────────────────────────
export default function RightConfigPanel({
  runId,
  pipelineGraph,
  runDetail = null,
  events = [],
  connected = false,
  liveFrame = null,
  selectedNodeId,
  selectedNodeData,
  onClose,
  runTrigger = 0,
  onSave,
  isSaving = false,
  isSaved = false,
}: Props) {
  const [tab, setTab] = useState<PanelTab>("configuration");
  const [fallbackFrame, setFallbackFrame] = useState<string | null>(null);
  const [localSaving, setLocalSaving] = useState(false);
  const [localSaved, setLocalSaved] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const prevRunTrigger = useRef(0);

  const isSavingToDb = isSaving || localSaving;
  const isSavedToDb = isSaved || localSaved;

  const handleSaveConfiguration = async () => {
    if (!onSave) return;
    setLocalSaving(true);
    setSaveErr(null);
    try {
      await onSave();
      setLocalSaved(true);
      setTimeout(() => setLocalSaved(false), 2500);
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : "Failed to save configuration");
    } finally {
      setLocalSaving(false);
    }
  };

  const status = runDetail?.run.status;
  const isRunning = status === "running" || status === "pending";

  // Auto-switch to Output tab when Run Pipeline is clicked
  useEffect(() => {
    if (runTrigger > 0 && runTrigger !== prevRunTrigger.current) {
      prevRunTrigger.current = runTrigger;
      setTab("output");
    }
  }, [runTrigger]);

  // Switch to config when a node is selected
  useEffect(() => {
    if (selectedNodeId) setTab("configuration");
  }, [selectedNodeId]);

  // Fallback poll for browser frame
  useEffect(() => {
    if (!runId || liveFrame) return;
    let cancelled = false;
    const poll = async () => {
      if (cancelled || liveFrame) return;
      try {
        const res = await fetch(getRunPreviewUrl(runId, Date.now()));
        if (!res.ok) return;
        const blob = await res.blob();
        const reader = new FileReader();
        reader.onload = () => {
          if (!cancelled && !liveFrame) setFallbackFrame(reader.result as string);
        };
        reader.readAsDataURL(blob);
      } catch { /* ignore */ }
    };
    poll();
    const id = setInterval(poll, 1500);
    return () => { cancelled = true; clearInterval(id); };
  }, [runId, liveFrame, isRunning]);

  const displayFrame = liveFrame
    ? `data:image/jpeg;base64,${liveFrame}`
    : fallbackFrame;

  const activeGraph = pipelineGraph || (runDetail?.run.plan_json?.pipeline_graph as PipelineGraph | undefined);
  const graphNodes = graphNodesForStatus(activeGraph);
  const trail = events.filter((e) => e.event_type !== "ping" && e.event_type !== "browser_frame").slice(-30);

  const needsPreviewClick = useMemo(() => {
    if (!isRunning) return false;
    return events.some((e) => {
      if (e.event_type === "human_action_required") return true;
      const msg = String(e.payload?.message || "").toLowerCase();
      return msg.includes("cloudflare") || msg.includes("verify you are human");
    });
  }, [events, isRunning]);

  async function handlePreviewClick(event: React.MouseEvent<HTMLImageElement>) {
    if (!runId || !needsPreviewClick) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;
    try { await sendPreviewClick(runId, x, y); } catch { /* ignore */ }
  }

  const tabs: { id: PanelTab; label: string }[] = [
    { id: "configuration", label: "Configuration" },
    { id: "testData", label: "Test Data" },
    { id: "output", label: "Output" },
    { id: "logs", label: "Logs" },
  ];

  const { isDark } = useTheme();
  const nodeTitle = selectedNodeData?.label ? String(selectedNodeData.label) : "Node";
  const nodeSubtitle = selectedNodeData?.nodeId === "input" ? "Provide search parameters" : (selectedNodeData?.nodeId || "");

  return (
    <div className={`flex flex-col h-full border-l transition-colors ${isDark ? "bg-[#0d1117] border-white/[0.06]" : "bg-white border-slate-200"
      }`} style={{ width: 320 }}>
      {/* Panel Header */}
      <div className="px-4 pt-4 pb-0 flex items-start justify-between shrink-0">
        <div>
          <div className="flex items-center gap-2">
            <h3 className={`text-sm font-bold ${isDark ? "text-zinc-100" : "text-slate-900"}`}>{nodeTitle}</h3>
            {status === "completed" && (
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${isDark ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" : "bg-emerald-50 text-emerald-700 border-emerald-300"
                }`}>
                Completed
              </span>
            )}
            {isRunning && (
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border animate-pulse ${isDark ? "bg-amber-500/20 text-amber-400 border-amber-500/30" : "bg-amber-50 text-amber-700 border-amber-300"
                }`}>
                Running
              </span>
            )}
          </div>
          {nodeSubtitle && (
            <p className={`text-[11px] mt-0.5 ${isDark ? "text-zinc-500" : "text-slate-600 font-medium"}`}>{nodeSubtitle}</p>
          )}
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            title="Close panel"
            aria-label="Close panel"
            className={`p-1.5 rounded-lg transition-colors ${isDark ? "text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/80" : "text-slate-400 hover:text-slate-900 hover:bg-slate-100"
              }`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className={`flex gap-0 px-3 mt-3 border-b shrink-0 ${isDark ? "border-white/[0.06]" : "border-slate-200"
        }`}>
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`px-3 py-2 text-[11px] font-semibold transition-colors border-b-2 -mb-px relative ${tab === t.id
              ? isDark
                ? "border-violet-500 text-violet-300"
                : "border-violet-600 text-violet-700 font-bold"
              : isDark
                ? "border-transparent text-zinc-500 hover:text-zinc-300"
                : "border-transparent text-slate-600 hover:text-slate-900"
              }`}
          >
            {t.label}
            {/* Badge on Output tab when running */}
            {t.id === "output" && isRunning && tab !== "output" && (
              <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-y-auto">

        {/* ── Configuration ── */}
        {tab === "configuration" && selectedNodeId && selectedNodeData && (
          <ConfigurationTab
            canvasId={selectedNodeId}
            nodeId={selectedNodeData.nodeId}
            data={selectedNodeData}
          />
        )}

        {tab === "configuration" && !selectedNodeId && (
          <div className="flex flex-col items-center justify-center h-full text-center p-8">
            <div className={`w-14 h-14 rounded-2xl border flex items-center justify-center mb-4 ${isDark ? "bg-zinc-800/80 border-white/[0.06]" : "bg-slate-100 border-slate-300 shadow-sm"
              }`}>
              <svg className={`w-7 h-7 ${isDark ? "text-zinc-600" : "text-slate-400"}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
              </svg>
            </div>
            <p className={`text-sm font-bold ${isDark ? "text-zinc-300" : "text-slate-900"}`}>Select a node</p>
            <p className={`text-xs mt-1 max-w-[180px] ${isDark ? "text-zinc-600" : "text-slate-500 font-medium"}`}>Click any node on the canvas to configure it</p>
          </div>
        )}

        {/* ── Test Data ── */}
        {tab === "testData" && (
          <div className="p-4">
            <p className={`text-xs ${isDark ? "text-zinc-500" : "text-slate-600 font-medium"}`}>Provide test data to simulate the node without running the full pipeline.</p>
            <div className="mt-3">
              <label className={isDark ? "block text-[11px] font-semibold text-zinc-400 mb-1.5 uppercase tracking-wider" : "block text-[11px] font-bold text-slate-700 mb-1.5 uppercase tracking-wider"}>Sample Input (JSON)</label>
              <textarea rows={8} className={`w-full rounded-lg border px-3 py-2 text-xs resize-y font-mono text-[10px] focus:outline-none transition-colors ${isDark ? "bg-zinc-900/80 border-white/[0.08] text-zinc-200 placeholder:text-zinc-600 focus:border-violet-500/60" : "bg-slate-50 border-slate-300 text-slate-900 placeholder:text-slate-400 focus:border-violet-600 shadow-sm"
                }`} placeholder='{"owner": "John Smith", "county": "miami-dade"}' />
            </div>
          </div>
        )}

        {/* ── Output (Live Browser) ── */}
        {tab === "output" && (
          <div className="h-full flex flex-col">
            {!runId ? (
              <div className="flex-1 flex flex-col items-center justify-center p-6 text-center">
                <div className={`w-16 h-16 rounded-2xl border flex items-center justify-center mb-4 ${isDark ? "bg-zinc-800/80 border-white/[0.06]" : "bg-slate-100 border-slate-300 shadow-sm"
                  }`}>
                  <svg className={`w-8 h-8 ${isDark ? "text-zinc-600" : "text-slate-400"}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9" />
                  </svg>
                </div>
                <p className={`text-sm font-bold ${isDark ? "text-zinc-300" : "text-slate-900"}`}>Live Browser Stream</p>
                <p className={`text-xs mt-2 max-w-[200px] ${isDark ? "text-zinc-600" : "text-slate-600 font-medium"}`}>
                  Click <span className="text-violet-600 font-bold">Run Pipeline</span> to start the automation. Live browser preview streams here.
                </p>
              </div>
            ) : (
              <>
                {needsPreviewClick && (
                  <div className="px-3 py-2 bg-amber-950/80 border-b border-amber-700/40 text-amber-200 text-xs shrink-0">

                  </div>
                )}
                <div className="flex-1 min-h-0 bg-black flex items-center justify-center overflow-hidden relative">
                  {displayFrame ? (
                    <>
                      <img
                        src={displayFrame}
                        alt="Live browser"
                        className={`w-full h-full object-contain ${needsPreviewClick ? "cursor-pointer" : ""}`}
                        onClick={handlePreviewClick}
                      />
                      {isRunning && liveFrame && (
                        <div className="absolute top-2 left-2 flex items-center gap-1.5 px-2 py-1 rounded-md bg-red-600/90 text-white text-[10px] font-bold uppercase tracking-wider">
                          <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                          Live
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="text-center p-6">
                      <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                      <p className="text-zinc-500 text-xs">Connecting to browser stream...</p>
                    </div>
                  )}
                </div>

                {/* Status bar */}
                <div className="px-3 py-2 border-t border-white/[0.05] text-xs text-zinc-500 shrink-0 flex items-center justify-between gap-2">
                  <span className="truncate flex-1">
                    {trail.length > 0
                      ? trail[trail.length - 1].payload?.message || trail[trail.length - 1].event_type
                      : "Starting automation..."}
                  </span>
                  <span className={`flex items-center gap-1 shrink-0 ${connected ? "text-emerald-400" : "text-zinc-600"}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-emerald-400 animate-pulse" : "bg-zinc-600"}`} />
                    {connected ? "Live" : "—"}
                  </span>
                </div>

                {/* Preview Output mini strip */}
                {/* <div className="border-t border-white/[0.06] px-3 py-2 shrink-0">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider flex items-center gap-1.5">
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                      Preview Output
                    </span>
                    <button type="button" className="text-[10px] text-violet-400 hover:text-violet-300 transition-colors">
                      View Full Screen
                    </button>
                  </div>
                  <div className="rounded-lg bg-zinc-900/60 border border-white/[0.05] overflow-hidden" style={{ height: 80 }}>
                    {displayFrame ? (
                      <img src={displayFrame} alt="Preview" className="w-full h-full object-cover" />
                    ) : (
                      <div className="flex items-center justify-center h-full text-zinc-700 text-[10px]">No preview yet</div>
                    )}
                  </div>
                </div> */}
              </>
            )}
          </div>
        )}

        {/* ── Logs ── */}
        {tab === "logs" && (
          <div className="p-3 space-y-2 h-full overflow-y-auto">
            {/* Node status grid */}
            {graphNodes.length > 0 && (
              <div className="space-y-1.5 mb-3">
                {graphNodes.map((node) => {
                  const st = deriveNodeStatus(
                    { id: node.id, label: node.label, description: "" },
                    events,
                    runDetail?.sources || [],
                    status
                  );
                  const colors: Record<string, string> = {
                    pending: "border-zinc-700/50 text-zinc-500",
                    running: "border-amber-500/50 text-amber-300 animate-pulse",
                    done: "border-emerald-600/50 text-emerald-300",
                    failed: "border-red-600/50 text-red-300",
                    skipped: "border-zinc-600/50 text-zinc-400",
                  };
                  return (
                    <div key={node.canvasId} className={`rounded-lg border px-3 py-2 text-xs ${colors[st] || colors.pending}`}>
                      <div className="flex justify-between">
                        <span className="font-medium">{node.label}</span>
                        <span className="uppercase text-[10px] tracking-wide">{st}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            {/* Event trail */}
            {trail.length === 0 && <p className="text-zinc-600 text-xs italic">No events yet. Run the pipeline to see logs here.</p>}
            {trail.map((e, i) => (
              <div key={e.id || i} className="text-xs border-l-2 border-violet-800/40 pl-2 py-0.5">
                <span className="text-violet-500/80 font-mono">{(e.payload?.node as string) || e.source || e.event_type}</span>
                <span className="text-zinc-400 ml-2">{e.payload?.message || e.event_type}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Save Button — in Configuration tab */}
      {tab === "configuration" && selectedNodeId && (
        <div className={`px-4 py-3 border-t shrink-0 ${isDark ? "border-white/[0.06]" : "border-slate-200"}`}>
          <button
            type="button"
            disabled={isSavingToDb}
            className={`w-full py-2.5 rounded-xl text-white text-sm font-bold transition-all shadow-lg flex items-center justify-center gap-2 ${isSavedToDb
              ? "bg-emerald-600 hover:bg-emerald-500 shadow-emerald-900/30"
              : "bg-violet-600 hover:bg-violet-500 shadow-violet-900/30"
              } disabled:opacity-50`}
            onClick={handleSaveConfiguration}
          >
            {isSavingToDb ? (
              <>
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Saving to Database...
              </>
            ) : isSavedToDb ? (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                </svg>
                Saved to Database!
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
                </svg>
                Save
              </>
            )}
          </button>
          {saveErr && (
            <p className="text-[10px] text-red-400 mt-1 text-center">{saveErr}</p>
          )}
        </div>
      )}
    </div>
  );
}
