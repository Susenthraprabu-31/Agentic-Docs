import { useCallback, useEffect, useState, DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Edge, Node } from "@xyflow/react";
import { PipelineNodeData } from "../../lib/defaultPipeline";
import { SIDEBAR_NODES } from "../../lib/nodeCatalog";
import { AVAILABLE_PIPELINE_NODES, onNodeDragStart } from "./NodePalettePopup";
import {
  WorkflowRecord,
  listWorkflows,
  saveWorkflow,
  deleteWorkflow,
  downloadWorkflowAsJson,
} from "../../api/workflows";
import { useTheme } from "../../context/ThemeContext";

/** Color/icon per node type for the node list */
const NODE_COLORS: Record<string, string> = {
  input: "#6366f1",
  netr: "#3b82f6",
  platform: "#06b6d4",
  assessor: "#14b8a6",
  recorder: "#8b5cf6",
  gis: "#22c55e",
  tax: "#f97316",
  normalizer: "#a855f7",
  report: "#ef4444",
  output: "#10b981",
  ai_agent: "#7c3aed",
  chatbot: "#0ea5e9",
};

interface Props {
  activeId: string | null;
  workflowTitle?: string;
  nodes: Node<PipelineNodeData>[];
  edges: Edge[];
  onSelect: (workflow: WorkflowRecord) => void;
  onNew: () => void;
  onSaveSuccess?: (workflow: WorkflowRecord) => void;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  onDeleteNode: (nodeId: string) => void;
  lastSavedWorkflow?: WorkflowRecord | null;
  onAddNode?: (catalogId: string) => void;
}

export default function WorkflowSidebar({
  activeId,
  workflowTitle = "Untitled Workflow",
  nodes,
  edges,
  onSelect,
  onNew,
  onSaveSuccess,
  selectedNodeId,
  onSelectNode,
  onDeleteNode,
  lastSavedWorkflow,
  onAddNode,
}: Props) {
  const navigate = useNavigate();
  const { isDark } = useTheme();
  const [search, setSearch] = useState("");
  const [workflows, setWorkflows] = useState<WorkflowRecord[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"workflows" | "nodes">("workflows");

  // Sync when workflow is saved from top bar or right panel
  useEffect(() => {
    if (!lastSavedWorkflow) return;
    setWorkflows((prev) => {
      const exists = prev.some((w) => w.id === lastSavedWorkflow.id);
      if (exists) return prev.map((w) => (w.id === lastSavedWorkflow.id ? lastSavedWorkflow : w));
      return [lastSavedWorkflow, ...prev];
    });
  }, [lastSavedWorkflow]);

  // Load workflows from backend on mount
  useEffect(() => {
    listWorkflows()
      .then((data) => {
        setWorkflows(data);
        setLoadError(null);
      })
      .catch((e) => setLoadError(e.message));
  }, []);

  const filtered = workflows.filter((w) =>
    w.name.toLowerCase().includes(search.toLowerCase())
  );

  const filteredAvailableNodes = AVAILABLE_PIPELINE_NODES.filter(
    (n) =>
      n.label.toLowerCase().includes(search.toLowerCase()) ||
      n.description.toLowerCase().includes(search.toLowerCase())
  );

  const handleSave = useCallback(async () => {
    const current = workflows.find((w) => w.id === activeId);
    const name = workflowTitle.trim() || current?.name || "Untitled Workflow";

    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const saved = await saveWorkflow({
        id: activeId || undefined,
        name,
        description: current?.description || "",
        nodes,
        edges,
        metadata: { step_count: nodes.length },
      });
      // Update list
      setWorkflows((prev) => {
        const exists = prev.some((w) => w.id === saved.id);
        if (exists) return prev.map((w) => (w.id === saved.id ? saved : w));
        return [saved, ...prev];
      });
      setSaveSuccess(true);
      onSaveSuccess?.(saved);
      setTimeout(() => setSaveSuccess(false), 2500);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }, [activeId, workflowTitle, workflows, nodes, edges, onSaveSuccess]);

  const handleExportCurrentJson = useCallback(() => {
    downloadWorkflowAsJson({
      id: activeId || undefined,
      name: workflowTitle.trim() || "workflow",
      description: "Exported title search pipeline",
      nodes,
      edges,
      metadata: { step_count: nodes.length, exported_at: new Date().toISOString() },
    });
  }, [activeId, workflowTitle, nodes, edges]);

  const handleDelete = useCallback(
    async (id: string, e: React.MouseEvent) => {
      e.stopPropagation();
      if (!confirm("Delete this workflow?")) return;
      try {
        await deleteWorkflow(id);
        setWorkflows((prev) => prev.filter((w) => w.id !== id));
      } catch (e) {
        alert(e instanceof Error ? e.message : "Delete failed");
      }
    },
    []
  );

  function relativeTime(iso?: string) {
    if (!iso) return "just now";
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  }

  return (
    <aside className={`w-56 shrink-0 flex flex-col ${isDark ? "bg-[#0d1117] border-white/[0.06]" : "bg-white border-slate-200"
      } border-r overflow-hidden transition-colors`}>
      {/* Header */}
      <div className="px-3 pt-3 pb-2 flex items-center justify-between shrink-0">
        <span className={`text-[11px] font-bold uppercase tracking-widest ${isDark ? "text-zinc-400" : "text-slate-800"
          }`}>
          Workflows
        </span>
        <button
          type="button"
          onClick={() => {
            onNew();
            setActiveTab("nodes");
          }}
          className="flex items-center gap-1 px-2 py-1 rounded-md bg-violet-600 hover:bg-violet-500 text-white text-[10px] font-bold transition-colors shadow-sm"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
          </svg>
          New
        </button>
      </div>

      {/* Save & Export Buttons */}
      <div className="px-2 pb-1.5 shrink-0 flex flex-col gap-1">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className={`w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md text-[11px] font-semibold transition-all ${saveSuccess
              ? isDark
                ? "bg-emerald-600/20 text-emerald-400 border border-emerald-600/30"
                : "bg-emerald-50 text-emerald-700 border border-emerald-300"
              : isDark
                ? "bg-violet-900/30 hover:bg-violet-800/40 text-violet-300 border border-violet-700/30"
                : "bg-violet-50 hover:bg-violet-100 text-violet-700 border border-violet-200 shadow-sm"
            } disabled:opacity-50`}
        >
          {saving ? (
            <><div className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" /> Saving...</>
          ) : saveSuccess ? (
            <><svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" /></svg> Saved the Workflow!</>
          ) : (
            <><svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" /></svg> Save Workflow</>
          )}
        </button>

        <button
          type="button"
          onClick={handleExportCurrentJson}
          className={`w-full flex items-center justify-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-medium border transition-colors ${isDark
              ? "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60 border-white/[0.05]"
              : "text-slate-700 hover:text-slate-950 hover:bg-slate-100 border-slate-200 shadow-sm"
            }`}
          title="Download current flow as a .json file"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          Export as JSON
        </button>

        {saveError && (
          <p className="text-[9px] text-red-500 mt-0.5 px-1">{saveError}</p>
        )}
      </div>

      {/* Tabs: Workflows | Nodes */}
      <div className="flex gap-0 px-2 mb-1.5 shrink-0">
        {(["workflows", "nodes"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setActiveTab(t)}
            className={`flex-1 py-1 text-[10px] font-semibold capitalize rounded-md transition-colors ${activeTab === t
                ? isDark
                  ? "bg-zinc-800 text-zinc-100"
                  : "bg-slate-900 text-white shadow-sm"
                : isDark
                  ? "text-zinc-500 hover:text-zinc-300"
                  : "text-slate-600 hover:text-slate-900"
              }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="px-2 pb-2 shrink-0">
        <div className="relative">
          <svg className={`absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 pointer-events-none ${isDark ? "text-zinc-600" : "text-slate-400"
            }`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={activeTab === "workflows" ? "Search workflows..." : "Search available nodes..."}
            className={`w-full pl-6 pr-2 py-1.5 rounded-md border text-[11px] transition-colors focus:outline-none focus:border-violet-500 ${isDark
                ? "bg-zinc-900/80 border-white/[0.06] text-zinc-300 placeholder:text-zinc-600"
                : "bg-slate-50 border-slate-300 text-slate-900 placeholder:text-slate-400 shadow-sm"
              }`}
          />
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-1.5 pb-2">
        {activeTab === "workflows" ? (
          <>
            {loadError && (
              <p className="text-[10px] text-amber-500 px-2 pb-1">{loadError}</p>
            )}
            {filtered.length === 0 && !loadError && (
              <p className={`text-[10px] px-2 py-3 ${isDark ? "text-zinc-600" : "text-slate-500"}`}>
                No workflows saved yet. Click Save Workflow above.
              </p>
            )}
            {filtered.map((w) => (
              <div
                key={w.id}
                onClick={() => onSelect(w)}
                className={`w-full text-left rounded-lg px-2.5 py-2.5 transition-all group mb-0.5 cursor-pointer flex items-start gap-2 border ${activeId === w.id
                    ? isDark
                      ? "bg-zinc-800/80 border-white/[0.08]"
                      : "bg-violet-50 border-violet-300 shadow-sm"
                    : isDark
                      ? "hover:bg-zinc-800/40 border-transparent"
                      : "hover:bg-slate-100 border-transparent"
                  }`}
              >
                <div className={`w-5 h-5 rounded-md shrink-0 mt-0.5 flex items-center justify-center border ${isDark
                    ? "bg-violet-900/30 border-violet-700/40"
                    : "bg-violet-100 border-violet-300"
                  }`}>
                  <div className={`w-2 h-2 rounded-sm ${isDark ? "bg-violet-500" : "bg-violet-600"}`} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className={`text-[11px] font-bold truncate leading-tight ${activeId === w.id
                      ? isDark ? "text-zinc-100" : "text-violet-950"
                      : isDark ? "text-zinc-300" : "text-slate-900"
                    }`}>
                    {w.name}
                  </p>
                  <p className={`text-[10px] mt-0.5 ${isDark ? "text-zinc-600" : "text-slate-500 font-medium"}`}>
                    {(w.nodes as unknown[]).length || 0} steps · {relativeTime(w.updated_at)}
                  </p>
                </div>
                <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      downloadWorkflowAsJson(w);
                    }}
                    className={`p-1 rounded transition-colors ${isDark ? "text-zinc-500 hover:text-violet-300" : "text-slate-400 hover:text-violet-700"
                      }`}
                    title="Download workflow as JSON file"
                  >
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    onClick={(e) => handleDelete(w.id, e)}
                    className={`p-1 rounded transition-colors ${isDark ? "text-zinc-500 hover:text-red-400" : "text-slate-400 hover:text-red-600"
                      }`}
                    title="Delete workflow"
                  >
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              </div>
            ))}
          </>
        ) : (
          /* Available Nodes Catalog */
          <div className="space-y-1">
            <div className={`px-1.5 pb-1 pt-0.5 flex items-center justify-between text-[10px] font-bold tracking-wider uppercase ${isDark ? "text-zinc-500" : "text-slate-600"
              }`}>
              <span>Available Nodes ({filteredAvailableNodes.length})</span>
              <span className={`text-[9px] font-normal lowercase ${isDark ? "text-zinc-600" : "text-slate-500"
                }`}>click or drag</span>
            </div>
            {filteredAvailableNodes.length === 0 ? (
              <p className={`text-[10px] px-2 py-4 text-center ${isDark ? "text-zinc-600" : "text-slate-500"
                }`}>No nodes match &ldquo;{search}&rdquo;</p>
            ) : (
              filteredAvailableNodes.map((item) => {
                const def = SIDEBAR_NODES.find((s) => s.catalogId === item.catalogId);
                return (
                  <div
                    key={item.catalogId}
                    draggable={Boolean(def)}
                    onDragStart={(e) => {
                      if (def) onNodeDragStart(e as unknown as DragEvent, def);
                    }}
                    onClick={() => onAddNode?.(item.catalogId)}
                    className={`w-full flex items-center gap-2.5 rounded-lg px-2 py-2 group transition-all cursor-pointer border text-left select-none ${isDark
                        ? "bg-zinc-900/40 hover:bg-zinc-800/80 active:bg-zinc-700/80 border-white/[0.04] hover:border-white/[0.1]"
                        : "bg-slate-50 hover:bg-slate-100 active:bg-slate-200 border-slate-200 hover:border-slate-300 shadow-sm"
                      }`}
                    title={`Click to append or drag onto canvas: ${item.label}`}
                  >
                    <div
                      className="w-7 h-7 rounded-lg shrink-0 flex items-center justify-center shadow-sm"
                      style={{ backgroundColor: item.iconBg }}
                    >
                      {item.icon}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className={`text-[11px] font-bold truncate leading-tight transition-colors ${isDark ? "text-zinc-200 group-hover:text-white" : "text-slate-900 group-hover:text-black"
                        }`}>
                        {item.label}
                      </p>
                      <p className={`text-[9px] truncate leading-tight mt-0.5 transition-colors ${isDark ? "text-zinc-500 group-hover:text-zinc-400" : "text-slate-600 group-hover:text-slate-800 font-medium"
                        }`}>
                        {item.description}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onAddNode?.(item.catalogId);
                      }}
                      className={`shrink-0 p-1 rounded-md opacity-0 group-hover:opacity-100 transition-all text-[10px] font-bold ${isDark ? "text-zinc-500 hover:text-white hover:bg-violet-600" : "text-slate-400 hover:text-white hover:bg-violet-600"
                        }`}
                      title="Add node to canvas"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
                      </svg>
                    </button>
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>

      {/* Batch Orders footer */}
      {/* <div className={`p-2 border-t shrink-0 ${
        isDark ? "border-white/[0.06]" : "border-slate-200"
      }`}>
        <button
          type="button"
          onClick={() => navigate("/batches")}
          className={`w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs font-semibold transition-colors ${
            isDark
              ? "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40"
              : "text-slate-700 hover:text-slate-950 hover:bg-slate-100"
          }`}
        >
          <svg className={`w-3.5 h-3.5 shrink-0 ${isDark ? "text-zinc-500" : "text-slate-500"}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>
          <span className="truncate">Batch Orders</span>
          <span className="ml-auto px-1.5 py-0.5 rounded-full text-[9px] bg-violet-100 dark:bg-violet-900/60 text-violet-700 dark:text-violet-300 font-bold shrink-0">
            New
          </span>
        </button>
      </div> */}
    </aside>
  );
}
