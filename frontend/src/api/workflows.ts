// Workflow save/load — calls the backend /workflows endpoints
// which persist to Supabase AND local JSON files on disk

import { Edge, Node } from "@xyflow/react";
import { PipelineNodeData } from "../lib/defaultPipeline";

const API_BASE = import.meta.env.VITE_API_URL || "";

export interface WorkflowRecord {
  id: string;
  name: string;
  description: string;
  nodes: Node<PipelineNodeData>[];
  edges: Edge[];
  metadata: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export async function listWorkflows(): Promise<WorkflowRecord[]> {
  const res = await fetch(`${API_BASE}/workflows`);
  if (!res.ok) throw new Error("Failed to load workflows");
  return res.json();
}

export async function saveWorkflow(payload: {
  id?: string;
  name: string;
  description?: string;
  nodes: Node<PipelineNodeData>[];
  edges: Edge[];
  metadata?: Record<string, unknown>;
}): Promise<WorkflowRecord> {
  const res = await fetch(`${API_BASE}/workflows`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: payload.id,
      name: payload.name,
      description: payload.description || "",
      nodes: payload.nodes,
      edges: payload.edges,
      metadata: payload.metadata || {},
    }),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || "Failed to save workflow");
  }
  return res.json();
}

export async function getWorkflow(workflowId: string): Promise<WorkflowRecord> {
  const res = await fetch(`${API_BASE}/workflows/${workflowId}`);
  if (!res.ok) throw new Error("Workflow not found");
  return res.json();
}

export async function deleteWorkflow(workflowId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/workflows/${workflowId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete workflow");
}

export function exportWorkflowUrl(workflowId: string): string {
  return `${API_BASE}/workflows/${workflowId}/export`;
}

/** Client-side helper to immediately trigger download of workflow as a .json file */
export function downloadWorkflowAsJson(data: {
  id?: string;
  name: string;
  description?: string;
  nodes: Node<PipelineNodeData>[];
  edges: Edge[];
  metadata?: Record<string, unknown>;
}) {
  const jsonStr = JSON.stringify(data, null, 2);
  const blob = new Blob([jsonStr], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const safeName = (data.name || "workflow").toLowerCase().replace(/[^a-z0-9_-]/g, "_");
  a.href = url;
  a.download = `${safeName}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
