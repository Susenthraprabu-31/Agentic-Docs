import { Edge, Node } from "@xyflow/react";

import { QueryType } from "../api/client";



export interface PipelineNodeData {

  label: string;

  nodeId: string;

  url?: string;

  portalType?: "assessor" | "recorder" | "tax" | "gis";

  playwrightNotes?: string;

  enabled?: boolean;

  state?: string;

  county?: string;

  queryType?: QueryType;

  queryValue?: string;

  address?: string;

  ownerName?: string;

  parcelNumber?: string;

  bookNumber?: string;

  pageNumber?: string;

  searchScope?: "current" | "full";

  searchLimit?: number;

  expandVariations?: boolean;

  partyType?: "both" | "grantor" | "grantee";

  maxNames?: number;

  // AI Agent fields

  agentName?: string;

  instructions?: string;

  userPrompt?: string;

  model?: string;

  agentType?: string;

  temperature?: number;

  maxTokens?: number;

  reportId?: string;

  reportRunId?: string;

  reportStatus?: "idle" | "generating" | "ready" | "failed";

  executionStatus?: "pending" | "running" | "done" | "failed" | "skipped";

  aiAgentResponse?: string;

  nodeResult?: unknown;

  [key: string]: unknown;
}



/** Vertical linear layout — one node per row, top to bottom */

const X = 280;

const ROW = 200;



export const DEFAULT_NODES: Node<PipelineNodeData>[] = [

  {

    id: "input",

    type: "pipelineNode",

    position: { x: X, y: 0 * ROW },

    data: {

      label: "Input",

      nodeId: "input",

      enabled: true,

      state: "AZ",

      county: "gila",

      queryType: "owner",

      queryValue: "",

      searchScope: "full",

      searchLimit: 0,

    },

  },

  {

    id: "netr",

    type: "pipelineNode",

    position: { x: X, y: 1 * ROW },

    data: {

      label: "NETR Resolver",

      nodeId: "netr",

      enabled: true,

      url: "",

      playwrightNotes: "Auto-scrape publicrecords.netronline.com for portal links. Leave URL empty to use NETR.",

    },

  },

  {

    id: "platform",

    type: "pipelineNode",

    position: { x: X, y: 2 * ROW },

    data: {

      label: "Platform Detector",

      nodeId: "platform",

      enabled: true,

      playwrightNotes: "Maps portal URLs to platform drivers (Schneider, FloridaPA, etc.)",

    },

  },

  {

    id: "assessor",

    type: "pipelineNode",

    position: { x: X, y: 3 * ROW },

    data: {

      label: "Assessor",

      nodeId: "assessor",

      enabled: true,

      url: "",

      playwrightNotes: "Uses Input query type: Address opens ADDRESS tab, Owner opens OWNER NAME tab, Parcel opens FOLIO tab.",

    },

  },

  {

    id: "recorder",

    type: "pipelineNode",

    position: { x: X, y: 4 * ROW },

    data: {

      label: "Recorder",

      nodeId: "recorder",

      enabled: true,

      url: "",

      playwrightNotes: "e.g. Search by grantor name, expand first result row",

    },

  },

  {

    id: "gis",

    type: "pipelineNode",

    position: { x: X, y: 5 * ROW },

    data: {

      label: "GIS",

      nodeId: "gis",

      enabled: true,

      url: "",

      playwrightNotes: "e.g. Navigate to map, zoom to parcel, screenshot canvas",

    },

  },

  {

    id: "tax",

    type: "pipelineNode",

    position: { x: X, y: 6 * ROW },

    data: {

      label: "Tax",

      nodeId: "tax",

      enabled: true,

      url: "",

      playwrightNotes: "e.g. Open PropertyDetail page, wait for tax bill table",

    },

  },

  {

    id: "normalizer",

    type: "pipelineNode",

    position: { x: X, y: 7 * ROW },

    data: {

      label: "Normalizer",

      nodeId: "normalizer",

      enabled: true,

      playwrightNotes: "Merge & deduplicate records by APN",

    },

  },

  {

    id: "report",

    type: "pipelineNode",

    position: { x: X, y: 8 * ROW },

    data: {

      label: "Report",

      nodeId: "report",

      enabled: true,

    },

  },

  {

    id: "output",

    type: "pipelineNode",

    position: { x: X, y: 9 * ROW },

    data: {

      label: "Output",

      nodeId: "output",

      enabled: true,

    },

  },

];



/** Single chain — sequential execution, no parallel branches */

export const DEFAULT_EDGES: Edge[] = [

  { id: "e-input-netr", source: "input", target: "netr", animated: true },

  { id: "e-netr-platform", source: "netr", target: "platform", animated: true },

  { id: "e-platform-assessor", source: "platform", target: "assessor", animated: true },

  { id: "e-assessor-recorder", source: "assessor", target: "recorder", animated: true },

  { id: "e-recorder-gis", source: "recorder", target: "gis", animated: true },

  { id: "e-gis-tax", source: "gis", target: "tax", animated: true },

  { id: "e-tax-normalizer", source: "tax", target: "normalizer", animated: true },

  { id: "e-normalizer-report", source: "normalizer", target: "report", animated: true },

  { id: "e-report-output", source: "report", target: "output", animated: true },

];



const AUTO_NODES = new Set(["input", "platform", "normalizer", "report", "output"]);



export function collectNodeOverrides(nodes: Node<PipelineNodeData>[]) {

  return nodes

    .filter((n) => !AUTO_NODES.has(n.data.nodeId))

    .map((n) => {

      const base = {

        node_id: n.data.nodeId,

        enabled: n.data.enabled !== false,

      };



      if (n.data.nodeId === "ai_agent") {

        return {

          ...base,

          agent_name: n.data.agentName?.trim() || undefined,

          instructions: n.data.instructions?.trim() || undefined,

          user_prompt: n.data.userPrompt?.trim() || undefined,

          model: n.data.model || "gpt-4o",

          agent_type: n.data.agentType || "orchestrator",

          temperature: n.data.temperature ?? 0.7,

          max_tokens: n.data.maxTokens ?? 1000,

        };

      }



      return {

        ...base,

        url: n.data.url?.trim() || undefined,

        playwright_notes: n.data.playwrightNotes?.trim() || undefined,

      };

    });

}



export function getInputFromNodes(nodes: Node<PipelineNodeData>[]) {
  const input = nodes.find((n) => n.data.nodeId === "input");
  return {
    state: input?.data.state || "AZ",
    county: input?.data.county || "gila",
    queryType: (input?.data.queryType || "owner") as QueryType,
    queryValue: input?.data.queryValue || "",
    ownerName: (input?.data.ownerName as string) || "",
    address: (input?.data.address as string) || "",
    parcelNumber: (input?.data.parcelNumber as string) || "",
    bookNumber: input?.data.bookNumber || "",
    pageNumber: input?.data.pageNumber || "",
    searchScope: (input?.data.searchScope as "current" | "full") || "full",
    searchLimit: (input?.data.searchLimit as number) ?? 0,
  };
}



export function hasAIAgentNode(nodes: Node<PipelineNodeData>[]) {

  return nodes.some((n) => n.data.nodeId === "ai_agent" && n.data.enabled !== false);

}


