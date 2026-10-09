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
  downloadReportExcel,
  downloadOfficialDocument,
  generatePlaywrightInstructions,
  QueryType,
  testAIAgent,
  getOpenAIStatus,
  AIAgentResult,
} from "../../api/client";
import { graphNodesForStatus } from "../../lib/pipelineGraph";
import { deriveNodeStatus } from "../../lib/pipelineStatus";
import { PipelineNodeData } from "../../lib/defaultPipeline";
import { US_STATES } from "../../data/states";
import { useReactFlow, useNodes, useEdges } from "@xyflow/react";
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
  const edges = useEdges();
  const nodes = useNodes();

  const connectedBeforeNodes = useMemo(() => {
    const incoming = edges.filter((e) => e.target === canvasId);
    return incoming
      .map((e) => {
        const srcNode = nodes.find((n) => n.id === e.source);
        if (!srcNode) return null;
        const sData = srcNode.data as PipelineNodeData | undefined;
        const sNodeId = String(sData?.nodeId || srcNode.id || "").toLowerCase();
        const sLabel = String(sData?.label || sNodeId || "Node");
        return { canvasId: srcNode.id, nodeId: sNodeId, label: sLabel };
      })
      .filter(Boolean) as { canvasId: string; nodeId: string; label: string }[];
  }, [edges, nodes, canvasId]);

  const connectedAfterNodes = useMemo(() => {
    const outgoing = edges.filter((e) => e.source === canvasId);
    return outgoing
      .map((e) => {
        const tgtNode = nodes.find((n) => n.id === e.target);
        if (!tgtNode) return null;
        const tData = tgtNode.data as PipelineNodeData | undefined;
        const tNodeId = String(tData?.nodeId || tgtNode.id || "").toLowerCase();
        const tLabel = String(tData?.label || tNodeId || "Node");
        return { canvasId: tgtNode.id, nodeId: tNodeId, label: tLabel };
      })
      .filter(Boolean) as { canvasId: string; nodeId: string; label: string }[];
  }, [edges, nodes, canvasId]);

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
  const isNameSearcher = nodeId === "name_searcher";
  const isReport = nodeId === "report";
  const isChatbot = nodeId === "chatbot";
  const isAiAgent = nodeId === "ai_agent" || isChatbot;
  const isPortalGate = nodeId === "portal_gate";
  const showUrl = ["netr", "portal_gate", "assessor", "recorder", "name_searcher", "gis", "tax"].includes(nodeId);
  const showNotes = ["netr", "portal_gate", "assessor", "recorder", "name_searcher", "gis", "tax", "platform", "normalizer"].includes(nodeId);
  const showAiGenerate = ["netr", "assessor", "recorder", "name_searcher", "gis", "tax"].includes(nodeId);

  const [apiConfigured, setApiConfigured] = useState<boolean | null>(null);
  const [testingAi, setTestingAi] = useState(false);
  const [aiTestResult, setAiTestResult] = useState<AIAgentResult | null>(null);
  const [aiTestError, setAiTestError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAiAgent) return;
    getOpenAIStatus()
      .then((r) => setApiConfigured(r.configured))
      .catch(() => setApiConfigured(false));
  }, [isAiAgent]);

  async function handleTestAi() {
    setTestingAi(true);
    setAiTestError(null);
    setAiTestResult(null);
    try {
      const primaryPrev = connectedBeforeNodes[0];
      const primaryNext = connectedAfterNodes[0];
      const res = await testAIAgent({
        config: {
          agent_name: data.agentName || (isChatbot ? "Title Chatbot" : "OpenAI Agent"),
          instructions:
            data.instructions ||
            (isChatbot
              ? "You are an expert real estate title chatbot and legal document advisor. Answer user queries, explain title findings, clarify deed terms, and provide concise, accurate advice based on the provided title records."
              : "You are a helpful AI assistant for property title research."),
          user_prompt:
            data.userPrompt ||
            (isChatbot
              ? "Review the public property and title records: {{workflow.previous}}\n\nProvide an interactive summary and answers to common title questions regarding this property."
              : "Analyze this data: {{workflow.previous}}\n\nPlease provide insights and recommendations."),
          model: data.model || "gpt-4o",
          temperature: data.temperature ?? 0.7,
          max_tokens: data.maxTokens ?? 1000,
        },
        context_data: {
          test: true,
          node_id: canvasId,
          previous_node: primaryPrev?.nodeId || "previous",
          previous_label: primaryPrev?.label,
          previous_canvas_id: primaryPrev?.canvasId,
          next_node: primaryNext?.nodeId,
          next_label: primaryNext?.label,
          next_canvas_id: primaryNext?.canvasId,
        },
      });
      setAiTestResult(res);
    } catch (err) {
      setAiTestError(err instanceof Error ? err.message : "Test failed");
    } finally {
      setTestingAi(false);
    }
  }

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
      <div className="space-y-3.5 p-4">
        <div>
          <p className={`text-xs ${isDark ? "text-zinc-400" : "text-slate-600 font-medium"}`}>
            Generates a PDF & Excel Chain Sheet from collected property records.
          </p>
        </div>

        {data.reportStatus === "generating" && (
          <div className="flex items-center gap-2 text-amber-400 text-xs p-3 rounded-lg border border-amber-500/30 bg-amber-500/10">
            <div className="w-3.5 h-3.5 rounded-full border-2 border-amber-400 border-t-transparent animate-spin" />
            Generating report & Chain Sheet...
          </div>
        )}

        {data.reportStatus === "ready" && (data.reportId || data.reportRunId) && (
          <div className="space-y-2">
            <a
              href={`/reports/run/${data.reportRunId || ""}`}
              target="_blank"
              rel="noreferrer"
              className="block w-full text-center px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-xs font-semibold transition-colors shadow-sm"
            >
              View Report
            </a>
            <button
              type="button"
              onClick={async () => {
                if (!data.reportId || !data.reportRunId) return;
                try {
                  await downloadReportPdf(String(data.reportId), String(data.reportRunId));
                } catch (err) {
                  alert(err instanceof Error ? err.message : "Download failed");
                }
              }}
              className={`block w-full text-center px-3 py-2 rounded-lg border text-xs font-semibold transition-colors ${
                isDark
                  ? "bg-zinc-800 hover:bg-zinc-700 border-white/[0.08] text-zinc-200"
                  : "bg-slate-100 hover:bg-slate-200 border-slate-300 text-slate-800"
              }`}
            >
              Download PDF
            </button>
            <button
              type="button"
              onClick={async () => {
                if (!data.reportRunId) return;
                try {
                  await downloadOfficialDocument(String(data.reportRunId));
                } catch (err) {
                  alert(err instanceof Error ? err.message : "Failed");
                }
              }}
              className={`block w-full text-center px-3 py-2 rounded-lg border text-xs font-semibold transition-colors ${
                isDark
                  ? "bg-teal-900/60 hover:bg-teal-900 border-teal-600/50 text-teal-200"
                  : "bg-teal-50 hover:bg-teal-100 border-teal-300 text-teal-800"
              }`}
            >
              Download Official Document
            </button>
          </div>
        )}

        {/* ── NEW SECTION: Excel Chain Sheet (.xlsx) ── */}
        <div className={`p-3.5 rounded-xl border space-y-2.5 transition-all ${
          isDark
            ? "bg-emerald-950/25 border-emerald-800/40"
            : "bg-emerald-50/80 border-emerald-200 shadow-sm"
        }`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-md bg-emerald-600 flex items-center justify-center text-white font-bold text-[10px] shadow-sm tracking-tight">
                XLS
              </div>
              <div>
                <h4 className={`text-xs font-bold ${isDark ? "text-emerald-300" : "text-emerald-950"}`}>
                  Chain Sheet (Excel)
                </h4>
                <p className={`text-[10px] ${isDark ? "text-emerald-400/80" : "text-emerald-700"}`}>
                  Title Examination Spreadsheet
                </p>
              </div>
            </div>
            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
              .XLSX
            </span>
          </div>

          <p className={`text-[11px] leading-relaxed ${isDark ? "text-zinc-300" : "text-slate-700"}`}>
            Generates the official <strong>Chain Sheet</strong> with Account Identifiers, Legal Descriptions, chronological Conveyances (Warranty/Quitclaim Deeds, Mortgages, Liens) with peach highlights, search names, yellow alert notes, and verification checklist.
          </p>

          <button
            type="button"
            disabled={!data.reportRunId}
            onClick={async () => {
              if (!data.reportRunId) {
                alert("Run the pipeline first to generate the report and Excel Chain Sheet.");
                return;
              }
              try {
                await downloadReportExcel(String(data.reportRunId));
              } catch (err) {
                alert(err instanceof Error ? err.message : "Excel export failed");
              }
            }}
            className={`w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-xs font-bold transition-all shadow-md ${
              data.reportRunId
                ? "bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-900/40 cursor-pointer"
                : "bg-zinc-800 text-zinc-500 border border-zinc-700/50 cursor-not-allowed"
            }`}
          >
            <svg className="w-4 h-4 text-emerald-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Download Chain Sheet (.xlsx)
          </button>
        </div>

        {data.reportStatus === "failed" && <p className="text-red-400 text-xs">Report generation failed.</p>}
        {(!data.reportStatus || data.reportStatus === "idle") && (
          <p className="text-zinc-600 text-xs italic">Run the pipeline to generate a report and Excel sheet.</p>
        )}
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

        {/* Search Scope */}
        <div>
          <label className={labelClass}>Search Scope</label>
          <select
            value={(data.searchScope as string) || "full"}
            onChange={(e) => patch({ searchScope: e.target.value as "current" | "full" })}
            className={fieldClass}
          >
            <option value="current">Current Search</option>
            <option value="full">Full Search</option>
          </select>
          <p className="text-[10px] text-zinc-500 mt-1">
            Current Search uses the latest assessor sale deed and searches only the current owner name in Name Searcher.
            Full Search downloads all assessor sales history and searches all recorder party names.
          </p>
        </div>

        {/* Search Limit */}
        <div>
          <label className={labelClass}>Search Limit</label>
          <select
            value={(data.searchLimit as number) ?? 0}
            onChange={(e) => patch({ searchLimit: Number(e.target.value) })}
            className={fieldClass}
          >
            <option value={0}>All</option>
            <option value={1}>1</option>
            <option value={5}>5</option>
            <option value={10}>10</option>
            <option value={25}>25</option>
          </select>
        </div>
      </div>
    );
  }

  if (isNameSearcher) {
    return (
      <div className="p-4 space-y-3.5 overflow-y-auto">
        <div>
          <p className={`text-xs ${isDark ? "text-zinc-400" : "text-slate-600 font-medium"}`}>
            Reads party names from the upstream Recorder node, then runs follow-up recorder
            searches for each extracted grantor/grantee.
          </p>
        </div>

        <div>
          <label className={labelClass}>Party Type</label>
          <select
            value={(data.partyType as string) || "both"}
            onChange={(e) => patch({ partyType: e.target.value as "both" | "grantor" | "grantee" })}
            className={fieldClass}
          >
            <option value="both">Both (Direct + Reverse)</option>
            <option value="grantor">Grantor / Direct</option>
            <option value="grantee">Grantee / Reverse</option>
          </select>
        </div>

        <div>
          <label className={labelClass}>Expand Name Variations</label>
          <label className="flex items-center gap-2 text-xs text-zinc-400">
            <input
              type="checkbox"
              checked={Boolean(data.expandVariations)}
              onChange={(e) => patch({ expandVariations: e.target.checked })}
            />
            Generate nickname, compound-surname, and entity permutations before searching (recommended)
          </label>
        </div>

        <div>
          <label className={labelClass}>Max Names To Search</label>
          <select
            value={(data.maxNames as number) ?? 0}
            onChange={(e) => patch({ maxNames: Number(e.target.value) })}
            className={fieldClass}
          >
            <option value={0}>All extracted names</option>
            <option value={1}>1</option>
            <option value={3}>3</option>
            <option value={5}>5</option>
            <option value={10}>10</option>
            <option value={25}>25</option>
          </select>
        </div>

        <div>
          <label className={labelClass}>Results Per Name</label>
          <select
            value={(data.searchLimit as number) ?? 0}
            onChange={(e) => patch({ searchLimit: Number(e.target.value) })}
            className={fieldClass}
          >
            <option value={0}>All</option>
            <option value={1}>1</option>
            <option value={5}>5</option>
            <option value={10}>10</option>
            <option value={25}>25</option>
          </select>
        </div>
      </div>
    );
  }

  // ── AI Agent node ──────────────────────────────────────────────────────────
  if (isAiAgent) {
    const MODELS = [
      "gpt-4.1",
      "gpt-4.1-mini",
      "gpt-4o",
      "gpt-4o-mini",
      "gpt-4.5-preview",
      "o3-mini",
      "o1",
      "gpt-4-turbo",
      "gpt-4",
      "gpt-3.5-turbo",
    ];
    const AGENT_TYPES = ["orchestrator", "assistant", "title validator", "analyzer"];
    return (
      <div className="p-4 space-y-3.5 overflow-y-auto">
        <div>
          <label className={labelClass}>{isChatbot ? "Chatbot Name" : "Agent Name"}</label>
          <input
            value={data.agentName ?? ""}
            onChange={(e) => patch({ agentName: e.target.value, label: e.target.value || (isChatbot ? "AI Chatbot" : "OpenAI Agent") })}
            placeholder={isChatbot ? "Title Chatbot" : "OpenAI Agent"}
            className={fieldClass}
          />
        </div>

        <div>
          <label className={labelClass}>Instructions / System Prompt</label>
          <textarea
            value={data.instructions ?? ""}
            onChange={(e) => patch({ instructions: e.target.value })}
            placeholder={
              isChatbot
                ? "You are an expert real estate title chatbot and legal document advisor. Answer user queries, explain title findings, clarify deed terms, and provide concise, accurate advice based on the provided title records."
                : "You are a helpful AI assistant for property title research."
            }
            rows={3}
            className={`${fieldClass} resize-y min-h-[60px]`}
          />
          <p className="text-[10px] text-zinc-500 mt-1">
            {isChatbot ? "Define the chatbot's conversational role and knowledge scope" : "Define the agent's role and behavior"}
          </p>
        </div>

        {/* Connected Workflow Topology */}
        <div className={`p-2.5 rounded-lg border text-xs space-y-2 ${isDark ? "bg-zinc-950/60 border-violet-900/40" : "bg-slate-100/90 border-slate-200"
          }`}>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-wider text-violet-400 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-violet-400" />
              Connected Workflow
            </span>
          </div>

          {/* Node Connected Before (Input) */}
          <div className="flex items-start gap-2 text-xs">
            <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-800/40 shrink-0">
              ← Before (Input)
            </span>
            {connectedBeforeNodes.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {connectedBeforeNodes.map((n) => (
                  <span
                    key={n.canvasId}
                    className={`px-2 py-0.5 rounded text-[11px] font-medium border flex items-center gap-1 ${isDark ? "bg-zinc-900 text-zinc-200 border-white/[0.08]" : "bg-white text-slate-800 border-slate-300 shadow-sm"
                      }`}
                  >
                    <span>{n.label}</span>
                    <code className="text-violet-400 font-mono text-[10px]">({n.nodeId})</code>
                  </span>
                ))}
              </div>
            ) : (
              <span className="text-[11px] text-amber-400 italic">No node connected before</span>
            )}
          </div>

          {/* Node Connected After (Output) */}
          <div className="flex items-start gap-2 text-xs">
            <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold bg-blue-950/80 text-blue-300 border border-blue-800/40 shrink-0">
              → After (Output)
            </span>
            {connectedAfterNodes.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {connectedAfterNodes.map((n) => (
                  <span
                    key={n.canvasId}
                    className={`px-2 py-0.5 rounded text-[11px] font-medium border flex items-center gap-1 ${isDark ? "bg-zinc-900 text-zinc-200 border-white/[0.08]" : "bg-white text-slate-800 border-slate-300 shadow-sm"
                      }`}
                  >
                    <span>{n.label}</span>
                    <code className="text-blue-400 font-mono text-[10px]">({n.nodeId})</code>
                  </span>
                ))}
              </div>
            ) : (
              <span className="text-[11px] text-zinc-500 italic">No node connected after</span>
            )}
          </div>
        </div>

        <div>
          <label className={labelClass}>User Input / Prompt</label>
          <textarea
            value={data.userPrompt ?? ""}
            onChange={(e) => patch({ userPrompt: e.target.value })}
            placeholder={
              connectedBeforeNodes.length > 0
                ? `Analyze this data: {{workflow.previous}}`
                : "Analyze this data: {{workflow.previous}}"
            }
            rows={3}
            className={`${fieldClass} resize-y min-h-[60px] font-mono text-[11px]`}
          />
          <div className="flex flex-wrap items-center gap-1 mt-1.5">
            <span className="text-[10px] text-zinc-500 mr-0.5">Insert:</span>

            {connectedBeforeNodes.length > 0 ? (
              <>
                <button
                  type="button"
                  onClick={() => {
                    const cur = data.userPrompt || "";
                    const val = cur.includes("{{workflow.previous}}")
                      ? cur
                      : cur
                        ? `${cur} {{workflow.previous}}`
                        : isChatbot
                          ? "Review the public property and title records: {{workflow.previous}}\n\nProvide an interactive summary and answers to common title questions regarding this property."
                          : "Analyze this data: {{workflow.previous}}\n\nPlease provide insights and recommendations.";
                    patch({ userPrompt: val });
                  }}
                  className={`text-[10px] px-2 py-0.5 rounded transition-colors font-medium flex items-center gap-1 ${
                    isChatbot
                      ? "bg-sky-950/40 hover:bg-sky-900/60 text-sky-300 border border-sky-700/40"
                      : "bg-violet-900/40 hover:bg-violet-800/60 text-violet-300 border border-violet-700/40"
                  }`}
                  title={`Pass preceding node result (${connectedBeforeNodes[0].label})`}
                >
                  <span>+ &#123;&#123;workflow.previous&#125;&#125;</span>
                  <span className={`text-[9px] font-normal ${isChatbot ? "text-sky-400/80" : "text-violet-400/80"}`}>
                    ({connectedBeforeNodes[0].label})
                  </span>
                </button>

                {connectedBeforeNodes.map((n) => (
                  <button
                    key={n.nodeId}
                    type="button"
                    onClick={() => {
                      const cur = data.userPrompt || "";
                      const tok = `{{workflow.${n.nodeId}}}`;
                      patch({ userPrompt: cur ? `${cur} ${tok}` : tok });
                    }}
                    className="text-[10px] px-2 py-0.5 rounded bg-emerald-950/40 hover:bg-emerald-900/60 text-emerald-300 border border-emerald-700/40 transition-colors font-medium"
                    title={`Pass ${n.label} result`}
                  >
                    + &#123;&#123;workflow.{n.nodeId}&#125;&#125;
                  </button>
                ))}
              </>
            ) : (
              <span className="text-[10px] text-amber-400/90 italic">
                Connect an upstream node to enable result variables
              </span>
            )}
          </div>
          <p className="text-[10px] text-zinc-500 mt-1">
            {connectedBeforeNodes.length > 0 ? (
              <>
                Connected to <strong className={isDark ? "text-zinc-200" : "text-slate-800"}>{connectedBeforeNodes.map((n) => n.label).join(", ")}</strong>. Use{" "}
                <code className="text-violet-400">{"{{workflow.previous}}"}</code> or{" "}
                <code className="text-emerald-400">{`{{workflow.${connectedBeforeNodes[0].nodeId}}}`}</code> to pass its result.
              </>
            ) : (
              <>
                Connect an upstream node (e.g. Assessor, Recorder, Tax, Report) to pass its data into this AI agent.
              </>
            )}
          </p>
        </div>

        <div className="rounded-lg border border-violet-900/30 bg-violet-950/20 p-2.5 space-y-1.5">
          <div className="flex items-center justify-between">
            <span className={labelClass}>Authentication</span>
            <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-900/40 text-emerald-400 border border-emerald-800/40">
              From .env
            </span>
          </div>
          <div className="flex items-center justify-between rounded-md bg-zinc-900/60 border border-zinc-800 px-2 py-1.5 text-xs">
            <span className="text-zinc-400 font-mono text-[11px]">OPENAI_API_KEY</span>
            <span className="text-zinc-500 font-mono">••••••••</span>
          </div>
          {apiConfigured === null ? (
            <p className="text-[10px] text-zinc-500">Checking configuration…</p>
          ) : apiConfigured ? (
            <p className="text-[10px] text-emerald-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              Configured in backend .env
            </p>
          ) : (
            <p className="text-[10px] text-red-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
              OPENAI_API_KEY missing in backend .env
            </p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className={labelClass}>Model</label>
            <select
              value={data.model || "gpt-4o"}
              onChange={(e) => patch({ model: e.target.value })}
              className={fieldClass}
            >
              {MODELS.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
              {data.model && !MODELS.includes(data.model) && (
                <option value={data.model}>{data.model}</option>
              )}
            </select>
          </div>
          <div>
            <label className={labelClass}>Agent Type</label>
            <select
              value={data.agentType || "orchestrator"}
              onChange={(e) => patch({ agentType: e.target.value })}
              className={fieldClass}
            >
              {AGENT_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className={labelClass}>Temperature</label>
            <input
              type="number"
              min={0}
              max={2}
              step={0.1}
              value={data.temperature ?? 0.7}
              onChange={(e) => patch({ temperature: parseFloat(e.target.value) || 0.7 })}
              className={fieldClass}
            />
          </div>
          <div>
            <label className={labelClass}>Max Tokens</label>
            <input
              type="number"
              min={100}
              max={16000}
              step={100}
              value={data.maxTokens ?? 1000}
              onChange={(e) => patch({ maxTokens: parseInt(e.target.value, 10) || 1000 })}
              className={fieldClass}
            />
          </div>
        </div>

        <button
          type="button"
          onClick={handleTestAi}
          disabled={testingAi || apiConfigured === false}
          className={`w-full rounded-lg border px-3 py-2 text-xs font-semibold disabled:opacity-50 transition-colors ${
            isChatbot
              ? "border-sky-700/60 bg-sky-900/40 hover:bg-sky-900/60 text-sky-200"
              : "border-violet-700/60 bg-violet-900/40 hover:bg-violet-900/60 text-violet-200"
          }`}
        >
          {testingAi
            ? (isChatbot ? "Testing Chatbot…" : "Testing Agent…")
            : (isChatbot ? "Test Chatbot (Network tab)" : "Test Agent (Network tab)")}
        </button>

        {aiTestError && (
          <p className="text-[10px] text-red-400 border border-red-900/50 rounded p-2">{aiTestError}</p>
        )}
        {aiTestResult && (
          <div className="rounded-lg border border-violet-800/40 bg-zinc-950/80 p-2 space-y-1">
            <p className="text-[10px] text-emerald-400 font-medium">
              {aiTestResult.endpoint} · {aiTestResult.duration_ms}ms · {aiTestResult.model}
            </p>
            <p className="text-[11px] text-zinc-300 whitespace-pre-wrap max-h-32 overflow-y-auto">
              {aiTestResult.content}
            </p>
          </div>
        )}
      </div>
    );
  }

  // ── Other pipeline nodes ───────────────────────────────────────────────────
  return (
    <div className="p-4 space-y-4 overflow-y-auto">
      {isPortalGate && (
        <div>
          <label className={labelClass}>Portal type</label>
          <select
            value={String(data.portalType || "assessor")}
            onChange={(e) => patch({ portalType: e.target.value })}
            className={fieldClass}
          >
            <option value="assessor">Assessor / Property Appraiser</option>
            <option value="recorder">Recorder / Clerk</option>
            <option value="tax">Tax Collector</option>
            <option value="gis">GIS / Map</option>
          </select>
          <p className={`mt-1.5 text-[10px] ${isDark ? "text-zinc-500" : "text-slate-500"}`}>
            Opens the portal and waits for Cloudflare verification in Live Browser. Session cookies are saved per county host.
          </p>
        </div>
      )}

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

      {!showUrl && !showNotes && !isReport && !isAiAgent && (
        <p className="text-zinc-600 text-xs italic">Auto — no manual inputs required.</p>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Node Output View — Displays structured result for any completed or active node
// ─────────────────────────────────────────────────────────────────────────────
function NodeOutputView({
  nodeId,
  canvasId,
  data,
  result,
  runId,
  onSwitchToBrowser,
}: {
  nodeId: string;
  canvasId: string;
  data: PipelineNodeData;
  result?: any;
  runId?: string | null;
  onSwitchToBrowser: () => void;
}) {
  const { isDark } = useTheme();
  const [showRawJson, setShowRawJson] = useState(false);

  const reportId = result?.report_id || data?.reportId;
  const reportRunId = runId || data?.reportRunId;
  const isReport = nodeId === "report";
  const isChatbot = nodeId === "chatbot";
  const isAiAgent = nodeId === "ai_agent" || isChatbot;

  const aiContent = result?.content || data?.aiAgentResponse;

  return (
    <div className="p-4 space-y-3.5 overflow-y-auto h-full">
      {/* Node Output Header */}
      <div className={`p-3 rounded-xl border flex items-center justify-between ${isDark ? "bg-zinc-900/60 border-white/[0.06]" : "bg-slate-50 border-slate-200 shadow-sm"
        }`}>
        <div>
          <h4 className={`text-xs font-bold flex items-center gap-1.5 ${isDark ? "text-zinc-100" : "text-slate-900"}`}>
            <span className="w-2 h-2 rounded-full bg-violet-500" />
            {data.label || nodeId} Output
          </h4>
          <span className="text-[10px] text-zinc-500 font-mono mt-0.5 block">{nodeId}</span>
        </div>
        {result || aiContent || (isReport && reportId) ? (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
            ✓ Available
          </span>
        ) : (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">
            Pending
          </span>
        )}
      </div>

      {/* ── Report Output ── */}
      {isReport && (
        <div className="space-y-3">
          {reportId ? (
            <div className="space-y-2.5">
              <a
                href={`/reports/run/${reportRunId || ""}`}
                target="_blank"
                rel="noreferrer"
                className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-xs font-bold transition-all shadow-md shadow-violet-900/30"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
                View Full Report
              </a>
              <div className="grid grid-cols-3 gap-1.5">
                <button
                  type="button"
                  onClick={async () => {
                    if (!reportId || !reportRunId) return;
                    try { await downloadReportPdf(String(reportId), String(reportRunId)); }
                    catch (err) { alert(err instanceof Error ? err.message : "Download failed"); }
                  }}
                  className={`px-2 py-1.5 rounded-lg border text-[11px] font-semibold transition-colors flex items-center justify-center gap-1 ${isDark ? "bg-zinc-800 hover:bg-zinc-700 border-white/[0.08] text-zinc-200" : "bg-slate-100 hover:bg-slate-200 border-slate-300 text-slate-800"
                    }`}
                >
                  <svg className="w-3 h-3 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                  PDF
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    if (!reportRunId) return;
                    try { await downloadOfficialDocument(String(reportRunId)); }
                    catch (err) { alert(err instanceof Error ? err.message : "Failed"); }
                  }}
                  className={`px-2 py-1.5 rounded-lg border text-[11px] font-semibold transition-colors flex items-center justify-center gap-1 ${isDark ? "bg-teal-950/60 hover:bg-teal-900/60 border-teal-700/40 text-teal-200" : "bg-teal-50 hover:bg-teal-100 border-teal-300 text-teal-800"
                    }`}
                >
                  <svg className="w-3 h-3 text-teal-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                  Deed
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    if (!reportRunId) return;
                    try { await downloadReportExcel(String(reportRunId)); }
                    catch (err) { alert(err instanceof Error ? err.message : "Excel export failed"); }
                  }}
                  className={`px-2 py-1.5 rounded-lg border text-[11px] font-semibold transition-colors flex items-center justify-center gap-1 ${isDark ? "bg-emerald-950/60 hover:bg-emerald-900/60 border-emerald-700/40 text-emerald-200" : "bg-emerald-50 hover:bg-emerald-100 border-emerald-300 text-emerald-800"
                    }`}
                >
                  <svg className="w-3 h-3 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                  Excel
                </button>
              </div>

              {/* Property summary */}
              {result?.property && (
                <div className={`rounded-lg border p-2.5 space-y-1 text-xs ${isDark ? "border-white/[0.06] bg-zinc-900/50" : "border-slate-200 bg-white shadow-sm"}`}>
                  <span className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">Property Details</span>
                  <p className="font-semibold text-zinc-100 dark:text-zinc-100">{result.property.address || result.property.property_address || "—"}</p>
                  <div className="flex items-center justify-between text-[11px] text-zinc-400">
                    <span>APN: {result.property.apn || result.property.parcel_id || "—"}</span>
                    <span>Owner: {result.property.owner_name || "—"}</span>
                  </div>
                </div>
              )}

              {/* Tax summary */}
              {result?.tax_record && (
                <div className={`rounded-lg border p-2.5 space-y-1 text-xs ${isDark ? "border-white/[0.06] bg-zinc-900/50" : "border-slate-200 bg-white shadow-sm"}`}>
                  <span className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">Tax Assessment</span>
                  <div className="flex items-center justify-between text-xs">
                    <span>Status: <strong className="text-emerald-400">{result.tax_record.status || "Paid"}</strong></span>
                    <span>Gross: ${result.tax_record.gross_tax || result.tax_record.net_tax || "—"}</span>
                  </div>
                </div>
              )}

              {/* Chain of title summary */}
              {result?.chain_of_title && (
                <div className={`rounded-lg border p-2.5 space-y-1 text-xs ${isDark ? "border-white/[0.06] bg-zinc-900/50" : "border-slate-200 bg-white shadow-sm"}`}>
                  <span className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">Chain of Title</span>
                  <p className="text-zinc-300 text-[11px]">
                    {Array.isArray(result.chain_of_title) ? `${result.chain_of_title.length} conveyances identified` : "Title history recorded"}
                  </p>
                </div>
              )}
            </div>
          ) : (
            <div className="text-center py-6 px-3 border border-dashed rounded-xl border-zinc-800 text-zinc-500 text-xs space-y-2">
              <p>Report not generated yet.</p>
              <button
                type="button"
                onClick={onSwitchToBrowser}
                className="text-violet-400 hover:text-violet-300 font-semibold underline"
              >
                Watch live browser execution
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── AI Agent / Chatbot Output ── */}
      {isAiAgent && (
        <div className="space-y-3">
          {aiContent ? (
            <div className="space-y-2.5">
              <div className="flex flex-wrap items-center gap-1.5">
                {result?.model && (
                  <span className={`px-2 py-0.5 rounded text-[10px] font-mono ${
                    isChatbot 
                      ? "bg-sky-900/40 text-sky-300 border border-sky-700/40" 
                      : "bg-violet-900/40 text-violet-300 border border-violet-700/40"
                  }`}>
                    {result.model}
                  </span>
                )}
                {result?.duration_ms && (
                  <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-white/[0.06] text-[10px]">
                    {result.duration_ms}ms
                  </span>
                )}
                {result?.completion_tokens && (
                  <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-white/[0.06] text-[10px]">
                    {result.completion_tokens} tokens
                  </span>
                )}
              </div>
              <div className={`rounded-xl border p-3.5 ${
                isChatbot
                  ? (isDark ? "border-sky-900/40 bg-zinc-950/80" : "border-sky-200 bg-sky-50/50")
                  : (isDark ? "border-violet-900/40 bg-zinc-950/80" : "border-violet-200 bg-violet-50/50")
              }`}>
                <span className={`text-[10px] uppercase font-bold tracking-wider block mb-2 ${
                  isChatbot ? "text-sky-500" : "text-violet-500"
                }`}>
                  {isChatbot ? "AI Chatbot Response" : "Autonomous Agent Response"}
                </span>
                <p className={`text-xs leading-relaxed whitespace-pre-wrap ${isDark ? "text-zinc-200" : "text-slate-800"}`}>
                  {aiContent}
                </p>
              </div>
            </div>
          ) : (
            <div className="text-center py-6 px-3 border border-dashed rounded-xl border-zinc-800 text-zinc-500 text-xs space-y-2">
              <p>{isChatbot ? "Chatbot has not executed yet." : "AI Agent has not executed yet."}</p>
              <p className="text-[10px] text-zinc-600">
                {isChatbot
                  ? "Run the pipeline with upstream nodes connected to Chatbot to view conversational answers."
                  : "Run the pipeline with Report connected to AI Agent to view analysis."}
              </p>
            </div>
          )}
        </div>
      )}

      {/* ── Other Node Types (Tax, Assessor, Recorder, GIS, Normalizer, Input, etc.) ── */}
      {!isReport && !isAiAgent && (
        <div className="space-y-3">
          {result ? (
            <div className={`rounded-xl border p-3 space-y-2 text-xs ${isDark ? "border-white/[0.06] bg-zinc-900/50" : "border-slate-200 bg-white shadow-sm"}`}>
              <span className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider block">
                Execution Output Summary
              </span>
              {Object.entries(result).map(([key, val]) => {
                if (typeof val === "object" && val !== null) return null;
                return (
                  <div key={key} className="flex items-center justify-between text-[11px] border-b border-white/[0.04] pb-1">
                    <span className="text-zinc-400 capitalize">{key.replace(/_/g, " ")}:</span>
                    <span className={`font-semibold truncate max-w-[160px] ${isDark ? "text-zinc-200" : "text-slate-800"}`}>{String(val)}</span>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="text-center py-6 px-3 border border-dashed rounded-xl border-zinc-800 text-zinc-500 text-xs space-y-2">
              <p>No execution data yet for this node.</p>
              <button
                type="button"
                onClick={onSwitchToBrowser}
                className="text-violet-400 hover:text-violet-300 font-semibold underline"
              >
                View Live Browser
              </button>
            </div>
          )}
        </div>
      )}

      {/* Raw JSON toggle */}
      {(result || aiContent) && (
        <div className="pt-2 border-t border-white/[0.06]">
          <button
            type="button"
            onClick={() => setShowRawJson(!showRawJson)}
            className="text-[10px] font-semibold text-zinc-500 hover:text-zinc-300 flex items-center gap-1 transition-colors"
          >
            <span>{showRawJson ? "▼ Hide" : "▶ Show"} Raw Output JSON</span>
          </button>
          {showRawJson && (
            <pre className="mt-2 p-2.5 rounded-lg bg-zinc-950 border border-white/[0.06] text-[10px] font-mono text-zinc-300 overflow-x-auto max-h-48 overflow-y-auto">
              {JSON.stringify(result || { content: aiContent }, null, 2)}
            </pre>
          )}
        </div>
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
  const [outputSubTab, setOutputSubTab] = useState<"node" | "browser">("node");
  const [fallbackFrame, setFallbackFrame] = useState<string | null>(null);
  const [localSaving, setLocalSaving] = useState(false);
  const [localSaved, setLocalSaved] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const prevRunTrigger = useRef(0);
  const edges = useEdges();
  const nodes = useNodes();

  const selectedPredecessors = useMemo(() => {
    if (!selectedNodeId) return [];
    const incoming = edges.filter((e) => e.target === selectedNodeId);
    return incoming
      .map((e) => {
        const srcNode = nodes.find((n) => n.id === e.source);
        if (!srcNode) return null;
        const sData = srcNode.data as PipelineNodeData | undefined;
        const sNodeId = String(sData?.nodeId || srcNode.id || "").toLowerCase();
        const sLabel = String(sData?.label || sNodeId || "Node");
        return { canvasId: srcNode.id, nodeId: sNodeId, label: sLabel };
      })
      .filter(Boolean) as { canvasId: string; nodeId: string; label: string }[];
  }, [edges, nodes, selectedNodeId]);

  const selectedSuccessors = useMemo(() => {
    if (!selectedNodeId) return [];
    const outgoing = edges.filter((e) => e.source === selectedNodeId);
    return outgoing
      .map((e) => {
        const tgtNode = nodes.find((n) => n.id === e.target);
        if (!tgtNode) return null;
        const tData = tgtNode.data as PipelineNodeData | undefined;
        const tNodeId = String(tData?.nodeId || tgtNode.id || "").toLowerCase();
        const tLabel = String(tData?.label || tNodeId || "Node");
        return { canvasId: tgtNode.id, nodeId: tNodeId, label: tLabel };
      })
      .filter(Boolean) as { canvasId: string; nodeId: string; label: string }[];
  }, [edges, nodes, selectedNodeId]);

  const nodeResults = useMemo(() => {
    const results: Record<string, any> = {
      ...(((runDetail?.run?.plan_json as Record<string, any> | undefined)?.node_results as Record<string, any>) || {}),
    };
    for (const e of events) {
      if (e.event_type === "node_completed" && e.payload) {
        const node = String(e.payload.node || "").replace(/Node$/, "").toLowerCase();
        const stepId = String(e.payload.step_node_id || "");
        const canvasId = String(e.payload.canvas_id || "");
        const res = e.payload.result || e.payload;
        if (node) results[node] = res;
        if (stepId) results[stepId] = res;
        if (canvasId) results[canvasId] = res;
      }
    }
    return results;
  }, [events, runDetail]);

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
      setOutputSubTab("browser");
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
          <div className="p-4 space-y-3">
            {selectedNodeData?.nodeId === "ai_agent" || selectedNodeData?.nodeId === "chatbot" ? (
              <div className="space-y-3">
                <p className={`text-xs ${isDark ? "text-zinc-400" : "text-slate-600 font-medium"}`}>
                  Test input data feeding into this {selectedNodeData?.nodeId === "chatbot" ? "Chatbot" : "AI Agent"} from the connected workflow.
                </p>

                {/* Connected Source Node Info */}
                <div className={`p-2.5 rounded-lg border text-xs space-y-1.5 ${isDark ? "bg-zinc-900/60 border-white/[0.08]" : "bg-slate-100 border-slate-200"
                  }`}>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Connected Input Node</span>
                    {selectedPredecessors.length > 0 ? (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-950/80 text-emerald-400 border border-emerald-800/40">
                        {selectedPredecessors[0].label} ({selectedPredecessors[0].nodeId})
                      </span>
                    ) : (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-950/80 text-amber-400 border border-amber-800/40">
                        None Connected
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-zinc-400">
                    {selectedPredecessors.length > 0
                      ? `The result below will be injected into {{workflow.previous}} and {{workflow.${selectedPredecessors[0].nodeId}}}.`
                      : "Connect an upstream node to pass data into this agent."}
                  </p>
                </div>

                <div>
                  <label className={isDark ? "block text-[11px] font-semibold text-zinc-400 mb-1.5 uppercase tracking-wider" : "block text-[11px] font-bold text-slate-700 mb-1.5 uppercase tracking-wider"}>
                    {selectedPredecessors.length > 0
                      ? `Payload from ${selectedPredecessors[0].label}`
                      : "Default Test Payload"}
                  </label>
                  <pre className={`w-full rounded-lg border p-2.5 text-[10px] font-mono overflow-x-auto max-h-60 overflow-y-auto ${isDark ? "bg-zinc-950 border-white/[0.08] text-zinc-300" : "bg-slate-50 border-slate-300 text-slate-900"
                    }`}>
                    {JSON.stringify(
                      (selectedPredecessors.length > 0 && (nodeResults[selectedPredecessors[0].canvasId] || nodeResults[selectedPredecessors[0].nodeId])) ||
                      (selectedPredecessors.length > 0 && selectedPredecessors[0].nodeId === "assessor"
                        ? {
                          records_found: 1,
                          parcel: "30-4009-094-0050",
                          owner_name: "John Smith",
                          address: "9441 SW 21 ST",
                          property: { apn: "30-4009-094-0050", address: "9441 SW 21 ST", owner: "John Smith" }
                        }
                        : selectedPredecessors.length > 0 && selectedPredecessors[0].nodeId === "tax"
                          ? {
                            records_found: 1,
                            records: [{ status: "Paid", gross_tax: 4520.18, delinquent: false }],
                            parcel: "30-4009-094-0050"
                          }
                          : selectedPredecessors.length > 0 && selectedPredecessors[0].nodeId === "recorder"
                            ? {
                              documents_found: 3,
                              documents: [{ document_type: "Warranty Deed", recording_date: "2021-04-15", grantor: "Alice Baker", grantee: "John Smith" }],
                              book_number: "1494",
                              page_number: "2483"
                            }
                            : {
                              status: "sample_data",
                              property: { apn: "30-4009-094-0050", address: "9441 SW 21 ST", owner: "John Smith" },
                              tax_record: { status: "Paid", gross_tax: 4520.18 },
                              documents_count: 3
                            }),
                      null,
                      2
                    )}
                  </pre>
                </div>
              </div>
            ) : (
              <div>
                <p className={`text-xs ${isDark ? "text-zinc-500" : "text-slate-600 font-medium"}`}>Provide test data to simulate the node without running the full pipeline.</p>
                <div className="mt-3">
                  <label className={isDark ? "block text-[11px] font-semibold text-zinc-400 mb-1.5 uppercase tracking-wider" : "block text-[11px] font-bold text-slate-700 mb-1.5 uppercase tracking-wider"}>Sample Input (JSON)</label>
                  <textarea rows={8} className={`w-full rounded-lg border px-3 py-2 text-xs resize-y font-mono text-[10px] focus:outline-none transition-colors ${isDark ? "bg-zinc-900/80 border-white/[0.08] text-zinc-200 placeholder:text-zinc-600 focus:border-violet-500/60" : "bg-slate-50 border-slate-300 text-slate-900 placeholder:text-slate-400 focus:border-violet-600 shadow-sm"
                    }`} placeholder='{"owner": "John Smith", "county": "miami-dade"}' />
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Output (Node Output & Live Browser) ── */}
        {tab === "output" && (
          <div className="h-full flex flex-col">
            {/* Output Sub-navigation */}
            <div
              className={`flex items-center gap-1 p-2 border-b shrink-0 ${isDark ? "bg-zinc-900/40 border-white/[0.06]" : "bg-slate-100/70 border-slate-200"
                }`}
            >
              <button
                type="button"
                onClick={() => setOutputSubTab("node")}
                className={`flex-1 py-1.5 px-2 rounded-lg text-[11px] font-semibold transition-all flex items-center justify-center gap-1.5 ${outputSubTab === "node"
                  ? isDark
                    ? "bg-violet-600 text-white shadow-sm font-bold"
                    : "bg-white text-slate-900 shadow-sm border border-slate-300 font-bold"
                  : isDark
                    ? "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60"
                    : "text-slate-600 hover:text-slate-900 hover:bg-slate-200/60"
                  }`}
              >
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                Node Output ({nodeTitle})
              </button>
              <button
                type="button"
                onClick={() => setOutputSubTab("browser")}
                className={`flex-1 py-1.5 px-2 rounded-lg text-[11px] font-semibold transition-all flex items-center justify-center gap-1.5 ${outputSubTab === "browser"
                  ? isDark
                    ? "bg-violet-600 text-white shadow-sm font-bold"
                    : "bg-white text-slate-900 shadow-sm border border-slate-300 font-bold"
                  : isDark
                    ? "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60"
                    : "text-slate-600 hover:text-slate-900 hover:bg-slate-200/60"
                  }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-emerald-400 animate-pulse" : "bg-zinc-500"
                    }`}
                />
                Live Browser
              </button>
            </div>

            {outputSubTab === "node" ? (
              <div className="flex-1 min-h-0 overflow-y-auto">
                <NodeOutputView
                  nodeId={selectedNodeData?.nodeId || ""}
                  canvasId={selectedNodeId || ""}
                  data={selectedNodeData || ({} as PipelineNodeData)}
                  result={
                    nodeResults[selectedNodeId || ""] ||
                    nodeResults[selectedNodeData?.nodeId || ""] ||
                    selectedNodeData?.nodeResult
                  }
                  runId={runId}
                  onSwitchToBrowser={() => setOutputSubTab("browser")}
                />
              </div>
            ) : !runId ? (
              <div className="flex-1 flex flex-col items-center justify-center p-6 text-center">
                <div
                  className={`w-16 h-16 rounded-2xl border flex items-center justify-center mb-4 ${isDark ? "bg-zinc-800/80 border-white/[0.06]" : "bg-slate-100 border-slate-300 shadow-sm"
                    }`}
                >
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
                    Human verification / CAPTCHA click required in browser stream below.
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
