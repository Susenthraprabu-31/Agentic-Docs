import { RunEvent, SourceProgress } from "../api/client";
import {
  deriveAllNodeStatuses,
  NodeStatus,
  PIPELINE_GRAPH,
  PipelineNodeDef,
} from "../lib/pipelineStatus";

interface Props {
  events: RunEvent[];
  sources?: SourceProgress[];
  runStatus?: string;
  live?: boolean;
}

const STATUS_STYLES: Record<NodeStatus, { box: string; dot: string; label: string }> = {
  pending: {
    box: "bg-slate-50 border-slate-200 text-slate-500",
    dot: "bg-slate-300",
    label: "Pending",
  },
  running: {
    box: "bg-blue-50 border-blue-400 text-blue-800 ring-2 ring-blue-200 animate-pulse",
    dot: "bg-blue-500",
    label: "Running",
  },
  done: {
    box: "bg-emerald-50 border-emerald-400 text-emerald-800",
    dot: "bg-emerald-500",
    label: "Done",
  },
  failed: {
    box: "bg-red-50 border-red-400 text-red-800",
    dot: "bg-red-500",
    label: "Failed",
  },
  skipped: {
    box: "bg-amber-50 border-amber-300 text-amber-700",
    dot: "bg-amber-400",
    label: "Skipped",
  },
};

function Connector({ vertical = true }: { vertical?: boolean }) {
  if (vertical) {
    return (
      <div className="flex justify-center py-1">
        <div className="w-0.5 h-5 bg-slate-300" />
      </div>
    );
  }
  return <div className="hidden sm:block w-6 h-0.5 bg-slate-300 shrink-0 self-center" />;
}

function NodeBox({
  node,
  status,
  source,
}: {
  node: PipelineNodeDef;
  status: NodeStatus;
  source?: SourceProgress;
}) {
  const styles = STATUS_STYLES[status];
  return (
    <div
      className={`relative rounded-xl border-2 px-4 py-3 min-w-[140px] max-w-[200px] transition-all duration-300 ${styles.box}`}
    >
      <div className="flex items-start gap-2">
        <span className={`mt-1.5 w-2.5 h-2.5 rounded-full shrink-0 ${styles.dot}`} />
        <div className="min-w-0">
          <p className="font-semibold text-sm leading-tight">{node.label}</p>
          <p className="text-xs opacity-75 mt-0.5 leading-snug">{node.description}</p>
          <p className="text-[10px] uppercase tracking-wider font-bold mt-1.5 opacity-60">
            {styles.label}
          </p>
          {source && source.records_found > 0 && (
            <p className="text-xs mt-1 font-medium">
              {source.source === "netronline"
                ? `${source.records_found} link${source.records_found !== 1 ? "s" : ""}`
                : `${source.records_found} record${source.records_found !== 1 ? "s" : ""}`}
            </p>
          )}
          {source?.message && status === "failed" && (
            <p className="text-xs mt-1 truncate" title={source.message}>
              {source.message}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function ParallelRow({
  nodes,
  statuses,
  sources,
}: {
  nodes: PipelineNodeDef[];
  statuses: Record<string, NodeStatus>;
  sources: SourceProgress[];
}) {
  return (
    <div className="flex flex-col sm:flex-row items-center justify-center gap-3 sm:gap-4">
      {nodes.map((node, i) => (
        <div key={node.id} className="flex items-center gap-3 sm:gap-4">
          {i > 0 && <Connector vertical={false} />}
          <NodeBox
            node={node}
            status={statuses[node.id]}
            source={sources.find((s) => s.source === node.sourceKey)}
          />
        </div>
      ))}
    </div>
  );
}

export default function PipelineNodes({ events, sources = [], runStatus, live }: Props) {
  const statuses = deriveAllNodeStatuses(events, sources, runStatus);
  const doneCount = Object.values(statuses).filter((s) => s === "done").length;
  const total = PIPELINE_GRAPH.length;

  const input = PIPELINE_GRAPH[0];
  const netr = PIPELINE_GRAPH[1];
  const platform = PIPELINE_GRAPH[2];
  const stage1 = [PIPELINE_GRAPH[3], PIPELINE_GRAPH[4]];
  const stage2 = [PIPELINE_GRAPH[5], PIPELINE_GRAPH[6]];
  const normalizer = PIPELINE_GRAPH[7];
  const report = PIPELINE_GRAPH[8];
  const output = PIPELINE_GRAPH[9];

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-base font-semibold text-slate-800">Pipeline Nodes</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            DAG-style research workflow — each step runs independently
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          {live !== undefined && (
            <span className={`inline-flex items-center gap-1 ${live ? "text-green-600" : "text-slate-400"}`}>
              <span className={`w-2 h-2 rounded-full ${live ? "bg-green-500" : "bg-slate-300"}`} />
              {live ? "Live" : "Polling"}
            </span>
          )}
          <span className="px-2.5 py-1 rounded-full bg-slate-100 text-slate-600 font-medium">
            {doneCount}/{total} nodes
          </span>
          {runStatus && (
            <span className="px-2.5 py-1 rounded-full bg-slate-800 text-white capitalize font-medium">
              {runStatus}
            </span>
          )}
        </div>
      </div>

      <div className="flex flex-col items-center overflow-x-auto pb-2">
        <NodeBox node={input} status={statuses[input.id]} />
        <Connector />
        <NodeBox
          node={netr}
          status={statuses[netr.id]}
          source={sources.find((s) => s.source === netr.sourceKey)}
        />
        <Connector />
        <NodeBox node={platform} status={statuses[platform.id]} />
        <Connector />

        <div className="w-full max-w-md">
          <p className="text-[10px] uppercase tracking-widest text-slate-400 text-center mb-2 font-semibold">
            Stage 1 — parallel
          </p>
          <ParallelRow nodes={stage1} statuses={statuses} sources={sources} />
        </div>

        <Connector />
        <div className="w-full max-w-md">
          <p className="text-[10px] uppercase tracking-widest text-slate-400 text-center mb-2 font-semibold">
            Stage 2 — parallel
          </p>
          <ParallelRow nodes={stage2} statuses={statuses} sources={sources} />
        </div>

        <Connector />
        <NodeBox node={normalizer} status={statuses[normalizer.id]} />
        <Connector />
        <NodeBox node={report} status={statuses[report.id]} />
        <Connector />
        <NodeBox node={output} status={statuses[output.id]} />
      </div>
    </div>
  );
}

/** Static read-only preview for the home page (all nodes pending) */
export function PipelinePreview() {
  return (
    <div className="mt-10">
      <p className="text-xs uppercase tracking-widest text-slate-400 text-center mb-4 font-semibold">
        How it works — node pipeline
      </p>
      <div className="opacity-70 pointer-events-none scale-[0.85] origin-top">
        <PipelineNodes events={[]} sources={[]} />
      </div>
    </div>
  );
}
