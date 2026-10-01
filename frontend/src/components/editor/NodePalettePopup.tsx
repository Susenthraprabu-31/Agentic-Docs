import { DragEvent, useEffect, useRef, useState } from "react";
import { SIDEBAR_NODES, SidebarNodeDef } from "../../lib/nodeCatalog";
import { useTheme } from "../../context/ThemeContext";

const DRAG_TYPE = "application/reactflow";

export function onNodeDragStart(event: DragEvent, def: SidebarNodeDef) {
  event.dataTransfer.setData(DRAG_TYPE, def.catalogId);
  event.dataTransfer.effectAllowed = "move";
}

export interface AvailableNodeItem {
  catalogId: string;
  label: string;
  description: string;
  iconBg: string;
  icon: React.ReactNode;
}

/** Complete catalog of all 11 available title search pipeline nodes */
export const AVAILABLE_PIPELINE_NODES: AvailableNodeItem[] = [
  {
    catalogId: "input",
    label: "Input",
    description: "Search query, address, state & county parameters",
    iconBg: "#6366f1",
    icon: (
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
    ),
  },
  {
    catalogId: "netr",
    label: "NETR Resolver",
    description: "Discover public records portals from NETR Online",
    iconBg: "#3b82f6",
    icon: (
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9" />
      </svg>
    ),
  },
  {
    catalogId: "platform",
    label: "Platform Detector",
    description: "Map portal URLs to platform drivers",
    iconBg: "#06b6d4",
    icon: (
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    ),
  },
  {
    catalogId: "assessor",
    label: "Assessor",
    description: "Property appraiser & deed history search",
    iconBg: "#14b8a6",
    icon: (
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
      </svg>
    ),
  },
  {
    catalogId: "recorder",
    label: "Recorder",
    description: "Official clerk deeds & mortgages search",
    iconBg: "#8b5cf6",
    icon: (
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
  {
    catalogId: "name_searcher",
    label: "Name Searcher",
    description: "Follow-up recorder searches using extracted party names",
    iconBg: "#d946ef",
    icon: (
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
  },
  {
    catalogId: "gis",
    label: "GIS Map",
    description: "Capture parcel boundary map screenshot",
    iconBg: "#22c55e",
    icon: (
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
      </svg>
    ),
  },
  {
    catalogId: "tax",
    label: "Tax Record",
    description: "Property tax collector & assessment lookup",
    iconBg: "#f97316",
    icon: (
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    catalogId: "ai_agent",
    label: "AI Agent",
    description: "OpenAI autonomous research & extraction agent",
    iconBg: "#7c3aed",
    icon: (
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
    ),
  },
  {
    catalogId: "chatbot",
    label: "AI Chatbot",
    description: "Interactive title assistant & conversational Q&A",
    iconBg: "#0ea5e9",
    icon: (
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
      </svg>
    ),
  },
  {
    catalogId: "normalizer",
    label: "Normalizer",
    description: "Merge & deduplicate records by APN",
    iconBg: "#a855f7",
    icon: (
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
      </svg>
    ),
  },
  {
    catalogId: "report",
    label: "Report Generator",
    description: "Generate final title search PDF report",
    iconBg: "#ef4444",
    icon: (
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
      </svg>
    ),
  },
  {
    catalogId: "output",
    label: "Output",
    description: "Finalize and summarize pipeline results",
    iconBg: "#10b981",
    icon: (
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
      </svg>
    ),
  },
];

interface Props {
  onClose: () => void;
  onAdd: (catalogId: string) => void;
}

export default function NodePalettePopup({ onClose, onAdd }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [search, setSearch] = useState("");

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  // Close on Escape key
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const { isDark } = useTheme();

  const filtered = AVAILABLE_PIPELINE_NODES.filter(
    (entry) =>
      entry.label.toLowerCase().includes(search.toLowerCase()) ||
      entry.description.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div
      ref={ref}
      className={`relative w-80 max-w-[92vw] rounded-xl border backdrop-blur-xl shadow-2xl overflow-hidden flex flex-col text-left select-none animate-in fade-in zoom-in-95 duration-150 ${
        isDark
          ? "border-white/[0.12] bg-[#141922]/98 shadow-black/80"
          : "border-slate-300 bg-white/98 shadow-slate-900/20"
      }`}
    >
      {/* Search Header */}
      <div className={`px-3 pt-3 pb-2 border-b ${
        isDark ? "border-white/[0.06] bg-zinc-900/50" : "border-slate-200 bg-slate-50"
      }`}>
        <div className="flex items-center justify-between mb-2">
          <span className={`text-[10px] font-bold uppercase tracking-wider ${
            isDark ? "text-zinc-400" : "text-slate-800"
          }`}>
            Available Nodes ({filtered.length})
          </span>
          <button
            type="button"
            onClick={onClose}
            className={`p-1 rounded-md transition-colors ${
              isDark
                ? "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/60"
                : "text-slate-400 hover:text-slate-700 hover:bg-slate-200/60"
            }`}
            title="Close"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="relative">
          <svg
            className={`absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 pointer-events-none ${
              isDark ? "text-zinc-500" : "text-slate-400"
            }`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            autoFocus
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search nodes..."
            className={`w-full pl-7 pr-3 py-1.5 rounded-lg border text-xs focus:outline-none transition-colors ${
              isDark
                ? "bg-zinc-900 border-white/[0.08] text-zinc-200 placeholder:text-zinc-600 focus:border-violet-500/60"
                : "bg-white border-slate-300 text-slate-900 placeholder:text-slate-400 focus:border-violet-600"
            }`}
          />
        </div>
      </div>

      {/* Node list */}
      <div className="overflow-y-auto max-h-[320px] p-1.5 space-y-1">
        {filtered.length === 0 ? (
          <p className={`text-center py-6 text-xs ${isDark ? "text-zinc-500" : "text-slate-500"}`}>
            No nodes match &ldquo;{search}&rdquo;
          </p>
        ) : (
          filtered.map((entry) => {
            const def = SIDEBAR_NODES.find((n) => n.catalogId === entry.catalogId);
            return (
              <button
                key={entry.catalogId}
                type="button"
                draggable={Boolean(def)}
                onDragStart={(e) => {
                  if (def) {
                    onNodeDragStart(e as unknown as DragEvent, def);
                    onClose();
                  }
                }}
                onClick={() => {
                  onAdd(entry.catalogId);
                  onClose();
                }}
                className={`w-full flex items-center gap-3 px-2.5 py-2 rounded-lg border border-transparent transition-all group text-left cursor-pointer ${
                  isDark
                    ? "hover:bg-zinc-800/80 active:bg-zinc-700/80 hover:border-white/[0.06]"
                    : "hover:bg-slate-100 active:bg-slate-200 hover:border-slate-200 shadow-sm"
                }`}
              >
                <div
                  className="w-8 h-8 rounded-lg shrink-0 flex items-center justify-center shadow-md"
                  style={{ backgroundColor: entry.iconBg }}
                >
                  {entry.icon}
                </div>
                <div className="min-w-0 flex-1">
                  <p className={`text-xs font-bold transition-colors leading-tight ${
                    isDark ? "text-zinc-200 group-hover:text-white" : "text-slate-900 group-hover:text-black"
                  }`}>
                    {entry.label}
                  </p>
                  <p className={`text-[10px] transition-colors line-clamp-1 mt-0.5 ${
                    isDark ? "text-zinc-500 group-hover:text-zinc-400" : "text-slate-600 group-hover:text-slate-800 font-medium"
                  }`}>
                    {entry.description}
                  </p>
                </div>
                <div className={`shrink-0 opacity-0 group-hover:opacity-100 text-[10px] font-bold px-1.5 py-0.5 rounded border transition-opacity ${
                  isDark
                    ? "text-violet-400 bg-violet-950/60 border-violet-700/40"
                    : "text-violet-700 bg-violet-100 border-violet-300"
                }`}>
                  + Add
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
