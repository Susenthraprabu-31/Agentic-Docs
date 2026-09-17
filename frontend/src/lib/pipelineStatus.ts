import { RunEvent, SourceProgress } from "../api/client";

export type NodeStatus = "pending" | "running" | "done" | "failed" | "skipped";

export interface PipelineNodeDef {
  id: string;
  label: string;
  description: string;
  sourceKey?: string;
}

/** Pipeline graph definition — mirrors backend app/pipeline/graph.py */
export const PIPELINE_GRAPH: PipelineNodeDef[] = [
  { id: "InputNode", label: "Input", description: "Validate & normalize search" },
  { id: "NETRResolverNode", label: "NETR Resolver", description: "Discover portal URLs", sourceKey: "netronline" },
  { id: "PlatformDetectorNode", label: "Platform Detector", description: "Map URLs → platforms" },
  { id: "AssessorNode", label: "Assessor", description: "Property appraiser search", sourceKey: "assessor" },
  { id: "RecorderNode", label: "Recorder", description: "Official records search", sourceKey: "recorder" },
  { id: "GISNode", label: "GIS", description: "Map screenshot capture", sourceKey: "gis" },
  { id: "TaxNode", label: "Tax", description: "Tax collector record", sourceKey: "tax_record" },
  { id: "AIAgentNode", label: "OpenAI Agent", description: "LLM analysis of collected data" },
  { id: "NormalizerNode", label: "Normalizer", description: "Merge & deduplicate results" },
  { id: "ReportNode", label: "Report", description: "Generate PDF report" },
  { id: "OutputNode", label: "Output", description: "Finalize run" },
];

function eventNodeId(event: RunEvent): string {
  const payload = event.payload || {};
  return String(payload.node || "");
}

function hasNodeEvent(events: RunEvent[], nodeId: string, type: string): boolean {
  return events.some((e) => e.event_type === type && eventNodeId(e) === nodeId);
}

function sourceStatus(sources: SourceProgress[], key: string): string | undefined {
  return sources.find((s) => s.source === key)?.status;
}

export function deriveNodeStatus(
  node: PipelineNodeDef,
  events: RunEvent[],
  sources: SourceProgress[],
  runStatus?: string
): NodeStatus {
  if (hasNodeEvent(events, node.id, "node_failed")) return "failed";
  if (hasNodeEvent(events, node.id, "node_completed")) return "done";
  if (hasNodeEvent(events, node.id, "node_started")) return "running";

  if (node.sourceKey) {
    const st = sourceStatus(sources, node.sourceKey);
    if (st === "failed") return "failed";
    if (st === "done") return "done";
    if (st === "skipped") return "skipped";
    if (st === "in_progress") return "running";
  }

  if (node.id === "TaxNode" && runStatus === "completed") {
    const st = sourceStatus(sources, "tax_record");
    if (!st || st === "pending") return "skipped";
  }

  if (node.id === "OutputNode" && runStatus === "completed") return "done";
  if (node.id === "OutputNode" && runStatus === "failed") return "failed";

  return "pending";
}

export function deriveAllNodeStatuses(
  events: RunEvent[],
  sources: SourceProgress[],
  runStatus?: string
): Record<string, NodeStatus> {
  const result: Record<string, NodeStatus> = {};
  for (const node of PIPELINE_GRAPH) {
    result[node.id] = deriveNodeStatus(node, events, sources, runStatus);
  }
  return result;
}
