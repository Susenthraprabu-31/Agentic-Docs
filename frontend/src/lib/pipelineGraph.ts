import { Edge, Node } from "@xyflow/react";
import { PipelineNodeData } from "./defaultPipeline";

export interface PipelineGraphNode {
  id: string;
  node_id: string;
  type: string;
  enabled: boolean;
  data: Record<string, unknown>;
}

export interface PipelineGraphEdge {
  source: string;
  target: string;
}

export interface PipelineGraph {
  nodes: PipelineGraphNode[];
  edges: PipelineGraphEdge[];
}

export interface GraphValidationResult {
  ok: boolean;
  error?: string;
  order?: string[];
}

const NODE_EXECUTION_PRIORITY: Record<string, number> = {
  input: 0,
  netr: 10,
  platform: 20,
  portal_gate: 25,
  assessor: 30,
  recorder: 40,
  name_searcher: 45,
  gis: 50,
  tax: 60,
  ai_agent: 65,
  chatbot: 66,
  normalizer: 70,
  report: 80,
  output: 90,
};

export const NODE_ID_TO_EVENT: Record<string, string> = {
  input: "InputNode",
  netr: "NETRResolverNode",
  platform: "PlatformDetectorNode",
  portal_gate: "PortalGateNode",
  assessor: "AssessorNode",
  recorder: "RecorderNode",
  name_searcher: "NameSearcherNode",
  gis: "GISNode",
  tax: "TaxNode",
  ai_agent: "AIAgentNode",
  chatbot: "ChatbotNode",
  normalizer: "NormalizerNode",
  report: "ReportNode",
  output: "OutputNode",
};

export function eventNameForNodeId(nodeId: string): string {
  return NODE_ID_TO_EVENT[nodeId] || nodeId;
}

function nodeDataPayload(data: PipelineNodeData): Record<string, unknown> {
  return {
    label: data.label,
    url: data.url?.trim() || undefined,
    portal_type: data.portalType || undefined,
    portalType: data.portalType || undefined,
    playwright_notes: data.playwrightNotes?.trim() || undefined,
    state: data.state,
    county: data.county,
    query_type: data.queryType,
    query_value: data.queryValue,
    address: data.address?.trim() || undefined,
    owner_name: data.ownerName?.trim() || undefined,
    ownerName: data.ownerName?.trim() || undefined,
    parcel_number: data.parcelNumber?.trim() || undefined,
    parcelNumber: data.parcelNumber?.trim() || undefined,
    book_number: data.bookNumber,
    page_number: data.pageNumber,
    bookNumber: data.bookNumber,
    pageNumber: data.pageNumber,
    search_scope: data.searchScope || "full",
    searchScope: data.searchScope || "full",
    search_limit: data.searchLimit ?? 0,
    searchLimit: data.searchLimit ?? 0,
    expand_variations: data.expandVariations ?? false,
    expandVariations: data.expandVariations ?? false,
    party_type: data.partyType || "both",
    partyType: data.partyType || "both",
    max_names: data.maxNames ?? 0,
    maxNames: data.maxNames ?? 0,
    agent_name: data.agentName?.trim() || undefined,
    instructions: data.instructions?.trim() || undefined,
    user_prompt: data.userPrompt?.trim() || undefined,
    model: data.model,
    agent_type: data.agentType,
    temperature: data.temperature,
    max_tokens: data.maxTokens,
  };
}

export function serializePipelineGraph(
  nodes: Node<PipelineNodeData>[],
  edges: Edge[]
): PipelineGraph {
  return {
    nodes: nodes.map((n) => ({
      id: n.id,
      node_id: n.data.nodeId,
      type: n.type || "pipelineNode",
      enabled: n.data.enabled !== false,
      data: nodeDataPayload(n.data),
    })),
    edges: edges.map((e) => ({ source: e.source, target: e.target })),
  };
}

export function validatePipelineGraph(graph: PipelineGraph): GraphValidationResult {
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];

  if (nodes.length === 0) {
    return { ok: false, error: "Add at least one node to the canvas" };
  }

  const inputs = nodes.filter((n) => n.node_id === "input");
  if (inputs.length === 0) {
    return { ok: false, error: "Connect an Input node to start the pipeline" };
  }
  if (inputs.length > 1) {
    return { ok: false, error: "Only one Input node allowed on the canvas" };
  }

  const inputId = inputs[0].id;
  const nodeIds = new Set(nodes.map((n) => n.id));
  const adjacency = new Map<string, string[]>();

  for (const id of nodeIds) {
    adjacency.set(id, []);
  }

  for (const edge of edges) {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
    adjacency.get(edge.source)!.push(edge.target);
  }

  const reachable = new Set<string>();
  const queue = [inputId];
  while (queue.length) {
    const cur = queue.shift()!;
    if (reachable.has(cur)) continue;
    reachable.add(cur);
    for (const next of adjacency.get(cur) || []) {
      if (!reachable.has(next)) queue.push(next);
    }
  }

  const subAdj = new Map<string, string[]>();
  const inDegree = new Map<string, number>();
  for (const id of reachable) {
    subAdj.set(id, []);
    inDegree.set(id, 0);
  }

  for (const edge of edges) {
    if (!reachable.has(edge.source) || !reachable.has(edge.target)) continue;
    subAdj.get(edge.source)!.push(edge.target);
    inDegree.set(edge.target, (inDegree.get(edge.target) || 0) + 1);
  }

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const sortKey = (canvasId: string) => {
    const nodeId = byId.get(canvasId)?.node_id || "";
    return [NODE_EXECUTION_PRIORITY[nodeId] ?? 100, canvasId] as [number, string];
  };

  const order: string[] = [];
  const kahn = [...reachable]
    .filter((id) => (inDegree.get(id) || 0) === 0)
    .sort((a, b) => {
      const [pa, ca] = sortKey(a);
      const [pb, cb] = sortKey(b);
      return pa - pb || ca.localeCompare(cb);
    });
  const visited = new Set<string>();

  while (kahn.length) {
    const cur = kahn.shift()!;
    if (visited.has(cur)) continue;
    visited.add(cur);
    order.push(cur);
    for (const next of subAdj.get(cur) || []) {
      inDegree.set(next, (inDegree.get(next) || 0) - 1);
      if (inDegree.get(next) === 0) kahn.push(next);
    }
    kahn.sort((a, b) => {
      const [pa, ca] = sortKey(a);
      const [pb, cb] = sortKey(b);
      return pa - pb || ca.localeCompare(cb);
    });
  }

  if (order.length !== reachable.size) {
    return { ok: false, error: "Cycle detected in pipeline graph" };
  }

  return { ok: true, order };
}

export function graphNodesForStatus(graph: PipelineGraph | undefined) {
  if (!graph?.nodes?.length) return [];
  const validation = validatePipelineGraph(graph);
  const order = validation.order || [];
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  return order
    .map((id) => byId.get(id))
    .filter(Boolean)
    .map((n) => ({
      id: eventNameForNodeId(n!.node_id),
      canvasId: n!.id,
      label: n!.data?.label as string || n!.node_id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      nodeId: n!.node_id,
    }));
}
