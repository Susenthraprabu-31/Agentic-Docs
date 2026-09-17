import { useEffect, useMemo, useState } from "react";
import { getRunPreviewUrl, sendPreviewClick } from "../../api/client";
import { RunDetail, RunEvent } from "../../api/client";
import { PipelineGraph } from "../../api/client";
import { graphNodesForStatus } from "../../lib/pipelineGraph";
import { deriveNodeStatus } from "../../lib/pipelineStatus";

interface Props {
  runId?: string | null;
  pipelineGraph?: PipelineGraph | null;
  runDetail?: RunDetail | null;
  events?: RunEvent[];
  connected?: boolean;
  liveFrame?: string | null;
}

type PanelTab = "live" | "log" | "nodes";

export default function BrowserPanel({
  runId,
  pipelineGraph,
  runDetail = null,
  events = [],
  connected = false,
  liveFrame = null,
}: Props) {
  const [tab, setTab] = useState<PanelTab>("live");
  const [fallbackFrame, setFallbackFrame] = useState<string | null>(null);

  const status = runDetail?.run.status;
  const isRunning = status === "running" || status === "pending";

  // Fallback poll only when screencast hasn't delivered a frame yet
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
          if (!cancelled && !liveFrame) {
            setFallbackFrame(reader.result as string);
          }
        };
        reader.readAsDataURL(blob);
      } catch {
        /* ignore */
      }
    };
    poll();
    const id = setInterval(poll, 1500);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [runId, liveFrame, isRunning]);

  const displayFrame = liveFrame
    ? `data:image/jpeg;base64,${liveFrame}`
    : fallbackFrame;

  const activeGraph =
    pipelineGraph ||
    (runDetail?.run.plan_json?.pipeline_graph as PipelineGraph | undefined);
  const graphNodes = graphNodesForStatus(activeGraph);
  const trail = events.filter((e) => e.event_type !== "ping" && e.event_type !== "browser_frame").slice(-20);

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
    try {
      await sendPreviewClick(runId, x, y);
    } catch {
      /* ignore transient click errors while page loads */
    }
  }

  const tabClass = (t: PanelTab) =>
    `px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
      tab === t
        ? "bg-teal-600/30 text-teal-200 border border-teal-500/50"
        : "text-zinc-500 hover:text-zinc-300"
    }`;

  return (
    <div className="flex flex-col h-full bg-[#0c1017] border-l border-teal-900/40">
      <div className="flex items-center justify-between px-3 py-2 border-b border-teal-900/40">
        <div className="flex items-center gap-2">
          <button type="button" className={tabClass("live")} onClick={() => setTab("live")}>
            Live
          </button>
          <button type="button" className={tabClass("log")} onClick={() => setTab("log")}>
            Log
          </button>
          <button type="button" className={tabClass("nodes")} onClick={() => setTab("nodes")}>
            Nodes
          </button>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className={`inline-flex items-center gap-1 ${connected ? "text-teal-400" : "text-zinc-500"}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-teal-400 animate-pulse" : "bg-zinc-600"}`} />
            {connected ? "Streaming" : "Connecting"}
          </span>
          {liveFrame && isRunning && (
            <span className="text-teal-600/80 text-[10px] uppercase tracking-wide">Live</span>
          )}
          {status && (
            <span className="px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-300 capitalize">{status}</span>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-hidden">
        {tab === "live" && (
          <div className="h-full flex flex-col">
            {!runId ? (
              <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
                <div className="w-14 h-14 rounded-xl bg-zinc-800/80 border border-teal-800/50 flex items-center justify-center mb-3">
                  <svg className="w-7 h-7 text-teal-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9" />
                  </svg>
                </div>
                <p className="text-zinc-400 text-sm">Live browser stream</p>
                <p className="text-zinc-600 text-xs mt-2 max-w-xs">
                  Click Run — Playwright automation streams here in real time.
                </p>
              </div>
            ) : (
              <>
                {needsPreviewClick && (
                  <div className="px-3 py-2 bg-amber-950/80 border-b border-amber-700/40 text-amber-200 text-xs">
                    Cloudflare detected — click <strong>Verify you are human</strong> directly in the preview below.
                  </div>
                )}
                <div className="flex-1 min-h-0 bg-black flex items-center justify-center overflow-hidden relative">
                  {displayFrame ? (
                    <>
                      <img
                        src={displayFrame}
                        alt="Live browser automation"
                        className={`w-full h-full object-contain ${needsPreviewClick ? "cursor-pointer" : ""}`}
                        onClick={handlePreviewClick}
                      />
                      {isRunning && liveFrame && (
                        <div className="absolute top-2 left-2 flex items-center gap-1.5 px-2 py-1 rounded bg-red-600/90 text-white text-[10px] font-bold uppercase tracking-wider">
                          <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                          Live
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="text-center p-6">
                      <div className="w-8 h-8 border-2 border-teal-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                      <p className="text-zinc-500 text-sm">Connecting to browser stream...</p>
                    </div>
                  )}
                </div>
                <div className="px-3 py-2 border-t border-teal-900/30 text-xs text-zinc-500 truncate">
                  {trail.length > 0
                    ? trail[trail.length - 1].payload?.message || trail[trail.length - 1].event_type
                    : "Starting automation..."}
                </div>
              </>
            )}
          </div>
        )}

        {tab === "log" && (
          <div className="h-full overflow-y-auto p-3 space-y-1.5">
            {trail.length === 0 && <p className="text-zinc-600 text-xs italic">No events yet</p>}
            {trail.map((e, i) => (
              <div key={e.id || i} className="text-xs border-l-2 border-teal-700 pl-2 py-0.5">
                <span className="text-teal-600/80 font-mono">
                  {(e.payload?.node as string) || e.source || e.event_type}
                </span>
                <span className="text-zinc-400 ml-2">{e.payload?.message || e.event_type}</span>
              </div>
            ))}
          </div>
        )}

        {tab === "nodes" && (
          <div className="h-full overflow-y-auto p-3 space-y-2">
            {graphNodes.length === 0 && (
              <p className="text-zinc-600 text-xs italic">Run the pipeline to see node progress</p>
            )}
            {graphNodes.map((node) => {
              const st = deriveNodeStatus(
                { id: node.id, label: node.label, description: "" },
                events,
                runDetail?.sources || [],
                status
              );
              const colors: Record<string, string> = {
                pending: "border-zinc-700 text-zinc-500",
                running: "border-teal-500 text-teal-300 animate-pulse",
                done: "border-emerald-600 text-emerald-300",
                failed: "border-red-600 text-red-300",
                skipped: "border-amber-600 text-amber-300",
              };
              return (
                <div
                  key={node.canvasId}
                  className={`rounded-lg border px-3 py-2 text-xs ${colors[st] || colors.pending}`}
                >
                  <div className="flex justify-between">
                    <span className="font-medium">{node.label}</span>
                    <span className="uppercase text-[10px] tracking-wide">{st}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
