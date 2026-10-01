import { memo, useCallback } from "react";
import { Handle, Position, NodeProps, useReactFlow } from "@xyflow/react";
import { PipelineNodeData } from "../../lib/defaultPipeline";
import { useTheme } from "../../context/ThemeContext";

type Props = NodeProps & { data: PipelineNodeData };

/** Icon + color config per node type */
const NODE_STYLE: Record<
  string,
  { bg: string; border: string; iconBg: string; icon: React.ReactNode }
> = {
  input: {
    bg: "#1a1f2e", border: "#6366f155", iconBg: "#6366f1",
    icon: <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>,
  },
  netr: {
    bg: "#1a1f2e", border: "#3b82f655", iconBg: "#3b82f6",
    icon: <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9" /></svg>,
  },
  platform: {
    bg: "#1a1f2e", border: "#06b6d455", iconBg: "#06b6d4",
    icon: <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18" /></svg>,
  },
  assessor: {
    bg: "#1a1f2e", border: "#14b8a655", iconBg: "#14b8a6",
    icon: <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>,
  },
  recorder: {
    bg: "#1a1f2e", border: "#8b5cf655", iconBg: "#8b5cf6",
    icon: <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>,
  },
  name_searcher: {
    bg: "#1a1f2e", border: "#d946ef55", iconBg: "#d946ef",
    icon: <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" /></svg>,
  },
  gis: {
    bg: "#1a1f2e", border: "#22c55e55", iconBg: "#22c55e",
    icon: <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" /></svg>,
  },
  tax: {
    bg: "#1a1f2e", border: "#f9731655", iconBg: "#f97316",
    icon: <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z" /></svg>,
  },
  normalizer: {
    bg: "#1a1f2e", border: "#a855f755", iconBg: "#a855f7",
    icon: <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" /></svg>,
  },
  report: {
    bg: "#1a1f2e", border: "#ef444455", iconBg: "#ef4444",
    icon: <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>,
  },
  output: {
    bg: "#1a1f2e", border: "#10b98155", iconBg: "#10b981",
    icon: <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>,
  },
  ai_agent: {
    bg: "#1e1a2e", border: "#7c3aed55", iconBg: "#7c3aed",
    icon: <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>,
  },
  chatbot: {
    bg: "#0c2340", border: "#0ea5e955", iconBg: "#0ea5e9",
    icon: (
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
      </svg>
    ),
  },
};

const DEFAULT_STYLE = {
  bg: "#1a1f2e", border: "#374151", iconBg: "#374151",
  icon: <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" /></svg>,
};

const NODE_SUBTITLES: Record<string, string> = {
  input: "Provide search parameters",
  netr: "Discover portal URLs",
  platform: "Map URLs to platform drivers",
  assessor: "Fetch property details",
  recorder: "Search official records",
  name_searcher: "Search extracted party names",
  gis: "Map screenshot capture",
  tax: "Tax collector lookup",
  normalizer: "Merge & deduplicate records",
  report: "Generate final output",
  output: "Finalize run results",
  ai_agent: "AI Automated",
  chatbot: "Conversational title Q&A",
};

// Non-deletable core nodes
const PROTECTED_NODES = new Set(["input"]);

function PipelineNodeComponent({ id, data, selected }: Props) {
  const { isDark } = useTheme();
  const { setNodes, setEdges } = useReactFlow();
  const style = NODE_STYLE[data.nodeId] || DEFAULT_STYLE;
  const subtitle = NODE_SUBTITLES[data.nodeId] || data.nodeId;
  const isReport = data.nodeId === "report";
  const canDelete = !PROTECTED_NODES.has(data.nodeId);

  const handleDelete = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      setNodes((nds) => nds.filter((n) => n.id !== id));
      setEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id));
    },
    [id, setNodes, setEdges]
  );

  const executionStatus =
    (data.executionStatus as "pending" | "running" | "done" | "failed" | "skipped") ||
    (isReport && data.reportStatus === "ready"
      ? "done"
      : isReport && data.reportStatus === "generating"
        ? "running"
        : "pending");

  let statusEmoji = "⏳";
  let statusBadgeClass = isDark
    ? "bg-zinc-800/80 border-white/[0.08] text-zinc-400"
    : "bg-slate-100 border-slate-300 text-slate-500 shadow-sm";
  let statusLabel = "Pending";

  if (executionStatus === "done") {
    statusEmoji = "✅";
    statusBadgeClass = isDark
      ? "bg-emerald-950/60 border-emerald-500/50 text-emerald-400 shadow-sm shadow-emerald-950/40"
      : "bg-emerald-50 border-emerald-400 text-emerald-600 shadow-sm";
    statusLabel = "Completed";
  } else if (executionStatus === "running") {
    statusEmoji = "⚡";
    statusBadgeClass = isDark
      ? "bg-amber-950/80 border-amber-400/60 text-amber-300 ring-2 ring-amber-400/30 animate-pulse"
      : "bg-amber-50 border-amber-400 text-amber-600 ring-2 ring-amber-400/40 shadow-sm animate-pulse";
    statusLabel = "Currently Working...";
  } else if (executionStatus === "failed") {
    statusEmoji = "❌";
    statusBadgeClass = isDark
      ? "bg-red-950/60 border-red-500/50 text-red-400"
      : "bg-red-50 border-red-400 text-red-600 shadow-sm";
    statusLabel = "Failed";
  } else if (executionStatus === "skipped") {
    statusEmoji = "⏭️";
    statusBadgeClass = isDark
      ? "bg-zinc-800/60 border-zinc-600/40 text-zinc-400"
      : "bg-slate-100 border-slate-300 text-slate-500";
    statusLabel = "Skipped";
  }

  const nodeBg = isDark
    ? selected ? "#1e2235" : style.bg
    : selected ? "#f5f3ff" : "#ffffff";

  let nodeBorder = isDark
    ? selected ? "#6366f1aa" : style.border
    : selected ? "#8b5cf6" : "#cbd5e1";

  if (executionStatus === "running") {
    nodeBorder = "#8b5cf6";
  } else if (executionStatus === "done") {
    nodeBorder = isDark ? "#10b981aa" : "#10b981";
  } else if (executionStatus === "failed") {
    nodeBorder = "#ef4444";
  }

  return (
    <div
      className={`pipeline-node-card relative rounded-xl transition-all duration-200 group ${executionStatus === "running"
        ? "ring-2 ring-violet-500 shadow-xl shadow-violet-500/25 animate-pulse"
        : executionStatus === "done"
          ? isDark
            ? "shadow-md shadow-emerald-950/30"
            : "shadow-md shadow-emerald-500/10"
          : selected
            ? isDark
              ? "shadow-lg shadow-violet-900/40 ring-1 ring-violet-500/50"
              : "shadow-lg shadow-violet-500/25 ring-2 ring-violet-500/70"
            : isDark
              ? "shadow-md shadow-black/30 hover:shadow-lg hover:shadow-black/50"
              : "shadow-md shadow-slate-300/60 hover:shadow-lg border border-slate-300"
        }`}
      style={{
        width: 240,
        background: nodeBg,
        borderColor: nodeBorder,
        borderWidth: executionStatus === "running" ? 2 : 1,
        borderStyle: "solid",
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-2.5 !h-2.5 !border-2"
        style={{
          background: style.iconBg,
          borderColor: isDark ? "#0d1117" : "#ffffff",
        }}
      />

      <div className="px-3.5 py-3 flex items-center gap-3">
        {/* Icon */}
        <div
          className="w-9 h-9 rounded-lg shrink-0 flex items-center justify-center shadow-md"
          style={{ background: style.iconBg }}
        >
          {style.icon}
        </div>

        {/* Labels */}
        <div className="flex-1 min-w-0">
          <p className={`text-[13px] font-bold leading-tight truncate ${isDark ? "text-zinc-100" : "text-slate-950"}`}>
            {(data.agentName as string) || (data.label as string)}
          </p>
          <p className={`text-[11px] font-medium leading-snug truncate mt-0.5 ${isDark ? "text-zinc-400" : "text-slate-600"}`}>
            {subtitle}
          </p>
        </div>

        {/* Right end: Delete button (on hover) + Status Emoji Badge */}
        <div className="flex items-center gap-1.5 shrink-0">
          {canDelete && (
            <button
              type="button"
              onClick={handleDelete}
              className={`opacity-0 group-hover:opacity-100 nodrag nopan w-5 h-5 rounded-md flex items-center justify-center transition-all ${isDark
                ? "text-zinc-500 hover:text-red-400 hover:bg-red-900/30"
                : "text-slate-400 hover:text-red-600 hover:bg-red-50"
                }`}
              title="Delete node"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}

          {/* Status Emoji Badge */}
          <div
            className={`w-6 h-6 rounded-full flex items-center justify-center text-[12px] font-semibold border transition-all select-none ${statusBadgeClass}`}
            title={`Status: ${statusLabel}`}
          >
            {statusEmoji}
          </div>
        </div>
      </div>

      {/* Report quick-actions */}
      {isReport && data.reportStatus === "ready" && data.reportId && (
        <div className="px-3.5 pb-3">
          <a
            href={`/reports/run/${data.reportRunId || ""}`}
            target="_blank"
            rel="noreferrer"
            className="block w-full text-center px-2 py-1.5 rounded-lg text-[10px] font-semibold text-white transition-colors"
            style={{ background: style.iconBg }}
            onClick={(e) => e.stopPropagation()}
          >
            View Report
          </a>
        </div>
      )}

      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-2.5 !h-2.5 !border-2"
        style={{
          background: style.iconBg,
          borderColor: isDark ? "#0d1117" : "#ffffff",
        }}
      />
    </div>
  );
}

export default memo(PipelineNodeComponent);
