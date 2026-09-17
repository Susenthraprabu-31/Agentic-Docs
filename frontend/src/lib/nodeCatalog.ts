import { PipelineNodeData } from "./defaultPipeline";



export interface SidebarNodeDef {

  catalogId: string;

  type: "pipelineNode" | "aiAgentNode";

  label: string;

  description: string;

  category: "ai" | "pipeline";

  defaultData: Partial<PipelineNodeData>;

}



export const SIDEBAR_NODES: SidebarNodeDef[] = [

  // ── Pipeline nodes ──────────────────────────────────────────────────────

  {

    catalogId: "input",

    type: "pipelineNode",

    label: "Input",

    description: "State, county, and search query",

    category: "pipeline",

    defaultData: {

      label: "Input",

      nodeId: "input",

      enabled: true,

      state: "AZ",

      county: "gila",

      queryType: "owner",

      queryValue: "",

    },

  },

  {

    catalogId: "netr",

    type: "pipelineNode",

    label: "NETR Resolver",

    description: "Discover portal URLs from NETR Online",

    category: "pipeline",

    defaultData: {

      label: "NETR Resolver",

      nodeId: "netr",

      enabled: true,

      url: "",

      playwrightNotes:

        "Auto-scrape publicrecords.netronline.com for portal links. Leave URL empty to use NETR.",

    },

  },

  {

    catalogId: "platform",

    type: "pipelineNode",

    label: "Platform Detector",

    description: "Map URLs to platform drivers",

    category: "pipeline",

    defaultData: {

      label: "Platform Detector",

      nodeId: "platform",

      enabled: true,

      playwrightNotes: "Maps portal URLs to platform drivers (Schneider, FloridaPA, etc.)",

    },

  },

  {

    catalogId: "assessor",

    type: "pipelineNode",

    label: "Assessor",

    description: "Property appraiser search",

    category: "pipeline",

    defaultData: {

      label: "Assessor",

      nodeId: "assessor",

      enabled: true,

      url: "",

      playwrightNotes:
        "Click address search tab, fill address field, click search, wait for results table",

    },

  },

  {

    catalogId: "recorder",

    type: "pipelineNode",

    label: "Recorder",

    description: "Official records search",

    category: "pipeline",

    defaultData: {

      label: "Recorder",

      nodeId: "recorder",

      enabled: true,

      url: "",

      playwrightNotes:
        "Search by grantor name, click Search, expand first result row",

    },

  },

  {

    catalogId: "gis",

    type: "pipelineNode",

    label: "GIS",

    description: "Map screenshot capture",

    category: "pipeline",

    defaultData: {

      label: "GIS",

      nodeId: "gis",

      enabled: true,

      url: "",

      playwrightNotes: "e.g. Navigate to map, zoom to parcel, screenshot canvas",

    },

  },

  {

    catalogId: "tax",

    type: "pipelineNode",

    label: "Tax",

    description: "Tax collector record lookup",

    category: "pipeline",

    defaultData: {

      label: "Tax",

      nodeId: "tax",

      enabled: true,

      url: "",

      playwrightNotes: "e.g. Open PropertyDetail page, wait for tax bill table",

    },

  },

  {

    catalogId: "normalizer",

    type: "pipelineNode",

    label: "Normalizer",

    description: "Merge & deduplicate by APN",

    category: "pipeline",

    defaultData: {

      label: "Normalizer",

      nodeId: "normalizer",

      enabled: true,

      playwrightNotes: "Merge & deduplicate records by APN",

    },

  },

  {

    catalogId: "report",

    type: "pipelineNode",

    label: "Report",

    description: "Generate PDF report",

    category: "pipeline",

    defaultData: {

      label: "Report",

      nodeId: "report",

      enabled: true,

    },

  },

  {

    catalogId: "output",

    type: "pipelineNode",

    label: "Output",

    description: "Finalize run results",

    category: "pipeline",

    defaultData: {

      label: "Output",

      nodeId: "output",

      enabled: true,

    },

  },

  // ── AI nodes ────────────────────────────────────────────────────────────

  {

    catalogId: "ai_agent",

    type: "aiAgentNode",

    label: "OpenAI Agent",

    description: "LLM orchestrator — API key from backend .env",

    category: "ai",

    defaultData: {

      label: "OpenAI Agent",

      nodeId: "ai_agent",

      enabled: true,

      agentName: "OpenAI Agent",

      instructions: "You are a helpful AI assistant for property title research.",

      userPrompt:

        "Analyze this data: {{dataFlow.previous()}}\n\nPlease provide insights and recommendations.",

      model: "gpt-4o",

      agentType: "orchestrator",

      temperature: 0.7,

      maxTokens: 1000,

    },

  },

];



export function getSidebarNode(catalogId: string): SidebarNodeDef | undefined {

  return SIDEBAR_NODES.find((n) => n.catalogId === catalogId);

}



export function createNodeFromCatalog(

  def: SidebarNodeDef,

  position: { x: number; y: number },

  id?: string

) {

  const nodeId = id || `${def.defaultData.nodeId}-${Date.now()}`;

  return {

    id: nodeId,

    type: def.type,

    position,

    data: { ...def.defaultData, label: def.label } as PipelineNodeData,

  };

}


