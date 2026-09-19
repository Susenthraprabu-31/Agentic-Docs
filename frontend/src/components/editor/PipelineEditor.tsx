import { useCallback, useEffect, useMemo, useRef, useState, DragEvent } from "react";

import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  ReactFlowProvider,
  useReactFlow,
  addEdge,
  Connection,
  Edge,
  Node,
} from "@xyflow/react";

import "@xyflow/react/dist/style.css";

import PipelineNode from "./PipelineNode";
import AIAgentNode from "./AIAgentNode";
import DeletableEdge from "./DeletableEdge";
import RightConfigPanel from "./BrowserPanel";
import WorkflowSidebar from "./WorkflowSidebar";
import NodePalettePopup from "./NodePalettePopup";

import {
  DEFAULT_EDGES,
  DEFAULT_NODES,
  getInputFromNodes,
} from "../../lib/defaultPipeline";
import { getSidebarNode, createNodeFromCatalog } from "../../lib/nodeCatalog";
import { serializePipelineGraph, validatePipelineGraph, PipelineGraph, NODE_ID_TO_EVENT } from "../../lib/pipelineGraph";
import { PIPELINE_GRAPH } from "../../lib/pipelineStatus";
import { createSearch, getReportByRun } from "../../api/client";
import { useRunStream } from "../../hooks/useRunStream";
import { PipelineNodeData } from "../../lib/defaultPipeline";
import { WorkflowRecord, saveWorkflow, downloadWorkflowAsJson } from "../../api/workflows";

import { useTheme } from "../../context/ThemeContext";
import ThemeToggle from "../common/ThemeToggle";

const nodeTypes = {
  pipelineNode: PipelineNode,
  aiAgentNode: PipelineNode,
};

const edgeTypes = {
  deletable: DeletableEdge,
};

const DRAG_TYPE = "application/reactflow";

interface PaletteAnchor { x: number; y: number; }

function EditorCanvas() {
  const { theme, isDark } = useTheme();
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const { screenToFlowPosition } = useReactFlow();

  const [nodes, setNodes, onNodesChange] = useNodesState(DEFAULT_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState(DEFAULT_EDGES);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [lastRunGraph, setLastRunGraph] = useState<PipelineGraph | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [showRightPanel, setShowRightPanel] = useState(true);
  const [paletteAnchor, setPaletteAnchor] = useState<PaletteAnchor | null>(null);
  const [activeWorkflowId, setActiveWorkflowId] = useState<string | null>(null);
  const [workflowTitle, setWorkflowTitle] = useState("Title Research");
  const [editingTitle, setEditingTitle] = useState(false);
  const [activeTab, setActiveTab] = useState<"canvas" | "variables" | "settings">("canvas");
  /** Increments each time Run is clicked — signals RightConfigPanel to switch to Output tab */
  const [runTrigger, setRunTrigger] = useState(0);

  const { runDetail, events, connected, liveFrame } = useRunStream(activeRunId || undefined);
  const reportFetchRef = useRef<string | null>(null);

  // Selected node data
  const selectedNode = nodes.find((n) => n.id === selectedNodeId);
  const selectedNodeData = selectedNode?.data as PipelineNodeData | undefined;

  // Report tracking
  useEffect(() => {
    if (!activeRunId) return;

    const reportEvent = [...events].reverse().find(
      (e) => e.event_type === "node_completed" && e.payload?.node === "ReportNode" && e.payload?.report_id
    );

    if (reportEvent?.payload?.report_id) {
      const reportId = String(reportEvent.payload.report_id);
      setNodes((nds) =>
        nds.map((n) =>
          n.data.nodeId === "report"
            ? { ...n, data: { ...n.data, reportId, reportRunId: activeRunId, reportStatus: "ready" } }
            : n
        )
      );
      reportFetchRef.current = activeRunId;
      return;
    }

    if (runDetail?.run.status === "failed") {
      setNodes((nds) =>
        nds.map((n) =>
          n.data.nodeId === "report" && n.data.reportStatus === "generating"
            ? { ...n, data: { ...n.data, reportStatus: "failed" } }
            : n
        )
      );
      return;
    }

    if (runDetail?.run.status !== "completed") return;
    if (reportFetchRef.current === activeRunId) return;

    const graphHasReport = lastRunGraph?.nodes?.some((n) => n.node_id === "report");
    if (!graphHasReport) return;

    reportFetchRef.current = activeRunId;
    getReportByRun(activeRunId)
      .then((report) => {
        setNodes((nds) =>
          nds.map((n) =>
            n.data.nodeId === "report"
              ? { ...n, data: { ...n.data, reportId: report.id, reportRunId: activeRunId, reportStatus: "ready" } }
              : n
          )
        );
      })
      .catch(() => {
        setNodes((nds) =>
          nds.map((n) =>
            n.data.nodeId === "report"
              ? { ...n, data: { ...n.data, reportStatus: "failed" } }
              : n
          )
        );
      });
  }, [activeRunId, events, runDetail?.run.status, lastRunGraph, setNodes]);

  // Node results & AI agent response tracking
  useEffect(() => {
    if (!activeRunId) return;

    const aiEvent = [...events].reverse().find(
      (e) => e.event_type === "node_completed" && (e.payload?.node === "AIAgentNode" || e.payload?.node === "ChatbotNode")
    );
    const planAiResponse = (runDetail?.run?.plan_json as Record<string, any> | undefined)?.ai_agent_response;
    const planChatbotResponse = (runDetail?.run?.plan_json as Record<string, any> | undefined)?.chatbot_response;
    const payloadAny = aiEvent?.payload as Record<string, any> | undefined;
    const aiContent = String(payloadAny?.result?.content || payloadAny?.message || planAiResponse || "");
    const chatbotContent = String(
      payloadAny?.node === "ChatbotNode"
        ? payloadAny?.result?.content || payloadAny?.message || planChatbotResponse
        : planChatbotResponse || aiContent || ""
    );

    const planResults = ((runDetail?.run?.plan_json as Record<string, any> | undefined)?.node_results || {}) as Record<string, unknown>;

    setNodes((nds) =>
      nds.map((n) => {
        let changed = false;
        const updatedData = { ...n.data };

        if (n.data.nodeId === "ai_agent" && aiContent && n.data.aiAgentResponse !== aiContent) {
          updatedData.aiAgentResponse = aiContent;
          changed = true;
        } else if (n.data.nodeId === "chatbot" && (chatbotContent || aiContent) && n.data.aiAgentResponse !== (chatbotContent || aiContent)) {
          updatedData.aiAgentResponse = chatbotContent || aiContent;
          changed = true;
        }

        const nodeRes = planResults[n.id] || planResults[n.data.nodeId];
        if (nodeRes && !n.data.nodeResult) {
          updatedData.nodeResult = nodeRes;
          changed = true;
        }

        return changed ? { ...n, data: updatedData } : n;
      })
    );
  }, [activeRunId, events, runDetail?.run?.plan_json, setNodes]);

  // Derive execution status for all canvas nodes based on run stream events
  const nodeStatusMap = useMemo<Record<string, "pending" | "running" | "done" | "failed" | "skipped">>(() => {
    const map: Record<string, "pending" | "running" | "done" | "failed" | "skipped"> = {};
    const runStatus = runDetail?.run.status;
    const sources = runDetail?.sources || [];

    for (const node of nodes) {
      const canvasId = node.id;
      const nodeId = node.data.nodeId;
      const backendName = NODE_ID_TO_EVENT[nodeId] || nodeId;
      const sourceKey = PIPELINE_GRAPH.find((g) => g.id === backendName)?.sourceKey;

      if (!activeRunId) {
        map[canvasId] = "pending";
        continue;
      }

      // 1. Check if node failed
      const isFailed = events.some(
        (e) =>
          (e.event_type === "node_failed" && (e.payload?.node === backendName || e.payload?.step_node_id === nodeId)) ||
          (e.event_type === "source_failed" && sourceKey && e.source === sourceKey)
      );
      if (isFailed) {
        map[canvasId] = "failed";
        continue;
      }

      // 2. Check if node completed
      const isCompleted = events.some(
        (e) =>
          (e.event_type === "node_completed" && (e.payload?.node === backendName || e.payload?.step_node_id === nodeId)) ||
          (e.event_type === "source_completed" && sourceKey && e.source === sourceKey)
      );
      if (isCompleted) {
        map[canvasId] = "done";
        continue;
      }

      // If run itself is completed, any node that wasn't failed or skipped is done
      if (runStatus === "completed") {
        map[canvasId] = "done";
        continue;
      }

      // 3. Check if currently running / working
      const isStarted = events.some(
        (e) =>
          (e.event_type === "node_started" && (e.payload?.node === backendName || e.payload?.step_node_id === nodeId)) ||
          (e.event_type === "pipeline_step" && (e.payload?.node === backendName || e.payload?.step_node_id === nodeId)) ||
          (e.event_type === "source_started" && sourceKey && e.source === sourceKey)
      );
      if (isStarted) {
        map[canvasId] = "running";
        continue;
      }

      map[canvasId] = "pending";
    }
    return map;
  }, [nodes, events, runDetail?.run.status, runDetail?.sources, activeRunId]);

  // Inject executionStatus into nodes for rendering
  const styledNodes = useMemo(() => {
    return nodes.map((node) => {
      const status = nodeStatusMap[node.id] || "pending";
      return {
        ...node,
        data: {
          ...node.data,
          executionStatus: status,
        },
      };
    });
  }, [nodes, nodeStatusMap]);

  // Apply edge status, dynamic colors, and marching flow animation
  const styledEdges = useMemo(() => {
    return edges.map((edge) => {
      const sourceStatus = nodeStatusMap[edge.source] || "pending";
      const targetStatus = nodeStatusMap[edge.target] || "pending";

      let edgeClass = "edge-pending";
      let isAnimated = false;
      let strokeColor = isDark ? "#334155" : "#cbd5e1";
      let strokeWidth = 1.5;

      if (sourceStatus === "done" && targetStatus === "done") {
        edgeClass = "edge-completed";
        isAnimated = false;
        strokeColor = "#10b981";
        strokeWidth = 2.5;
      } else if (targetStatus === "running" || (sourceStatus === "running" && targetStatus === "pending")) {
        edgeClass = "edge-running";
        isAnimated = true;
        strokeColor = "#8b5cf6";
        strokeWidth = 3;
      } else if (targetStatus === "failed") {
        edgeClass = "edge-failed";
        isAnimated = false;
        strokeColor = "#ef4444";
        strokeWidth = 2;
      }

      return {
        ...edge,
        type: edge.type || "deletable",
        className: edgeClass,
        animated: isAnimated,
        style: {
          ...edge.style,
          stroke: strokeColor,
          strokeWidth,
        },
      };
    });
  }, [edges, nodeStatusMap, isDark]);

  const onConnect = useCallback(
    (connection: Connection) =>
      setEdges((eds) =>
        addEdge({ ...connection, type: "deletable", animated: true }, eds)
      ),
    [setEdges]
  );

  const onNodesDelete = useCallback(
    (deleted: Node[]) => {
      const ids = new Set(deleted.map((n) => n.id));
      setEdges((eds) => eds.filter((e) => !ids.has(e.source) && !ids.has(e.target)));
    },
    [setEdges]
  );

  const onEdgesDelete = useCallback(
    (deleted: Edge[]) => {
      const ids = new Set(deleted.map((e) => e.id));
      setEdges((eds) => eds.filter((e) => !ids.has(e.id)));
    },
    [setEdges]
  );

  const onDragOver = useCallback((event: DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault();
      const catalogId = event.dataTransfer.getData(DRAG_TYPE);
      if (!catalogId || !reactFlowWrapper.current) return;
      const def = getSidebarNode(catalogId);
      if (!def) return;
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      const newNode = createNodeFromCatalog(def, position);
      setNodes((nds) => nds.concat(newNode));
    },
    [screenToFlowPosition, setNodes]
  );

  const onAddFromPalette = useCallback(
    (catalogId: string) => {
      const def = getSidebarNode(catalogId);
      if (!def) return;
      const lastNode = nodes[nodes.length - 1];
      const position = lastNode
        ? { x: lastNode.position.x, y: lastNode.position.y + 180 }
        : { x: 280, y: 100 };
      const newNode = createNodeFromCatalog(def, position);
      setNodes((nds) => nds.concat(newNode));
      if (lastNode) {
        setEdges((eds) =>
          eds.concat({
            id: `e-${lastNode.id}-${newNode.id}`,
            source: lastNode.id,
            target: newNode.id,
            type: "deletable",
            animated: true,
          })
        );
      }
      setSelectedNodeId(newNode.id);
      setShowRightPanel(true);
      setPaletteAnchor(null);
    },
    [nodes, setNodes, setEdges]
  );

  /** Delete a node by ID from the sidebar or canvas */
  const onDeleteNode = useCallback(
    (nodeId: string) => {
      setNodes((nds) => nds.filter((n) => n.id !== nodeId));
      setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      if (selectedNodeId === nodeId) setSelectedNodeId(null);
    },
    [setNodes, setEdges, selectedNodeId]
  );

  /** Load a saved workflow into the canvas */
  const onLoadWorkflow = useCallback(
    (workflow: WorkflowRecord) => {
      setActiveWorkflowId(workflow.id);
      setWorkflowTitle(workflow.name);
      if (workflow.nodes?.length) {
        setNodes(
          workflow.nodes.map((n) => ({
            ...n,
            type: "pipelineNode",
          })) as Node<PipelineNodeData>[]
        );
      }
      if (workflow.edges?.length) {
        setEdges(workflow.edges);
      }
    },
    [setNodes, setEdges]
  );

  /** New empty workflow */
  const onNewWorkflow = useCallback(() => {
    setActiveWorkflowId(null);
    setWorkflowTitle("Untitled Workflow");
    setNodes([]);
    setEdges([]);
    setSelectedNodeId(null);
  }, [setNodes, setEdges]);

  const [savingWorkflow, setSavingWorkflow] = useState(false);
  const [saveSuccessWorkflow, setSaveSuccessWorkflow] = useState(false);
  const [lastSavedWorkflow, setLastSavedWorkflow] = useState<WorkflowRecord | null>(null);

  const handleSaveCurrentWorkflow = useCallback(async () => {
    setSavingWorkflow(true);
    setError(null);
    try {
      const saved = await saveWorkflow({
        id: activeWorkflowId || undefined,
        name: workflowTitle.trim() || "Untitled Workflow",
        nodes,
        edges,
        metadata: { step_count: nodes.length },
      });
      setActiveWorkflowId(saved.id);
      setWorkflowTitle(saved.name);
      setLastSavedWorkflow(saved);
      setSaveSuccessWorkflow(true);
      setTimeout(() => setSaveSuccessWorkflow(false), 2500);
      return saved;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save workflow");
      throw e;
    } finally {
      setSavingWorkflow(false);
    }
  }, [activeWorkflowId, workflowTitle, nodes, edges]);

  const handleExportJson = useCallback(() => {
    downloadWorkflowAsJson({
      id: activeWorkflowId || undefined,
      name: workflowTitle.trim() || "workflow",
      description: "Title Search Pipeline",
      nodes,
      edges,
      metadata: { step_count: nodes.length, exported_at: new Date().toISOString() },
    });
  }, [activeWorkflowId, workflowTitle, nodes, edges]);

  const onRun = useCallback(async () => {
    const { state, county, queryType, queryValue, ownerName, address, parcelNumber, bookNumber, pageNumber } = getInputFromNodes(nodes);

    const hasAddr = Boolean(address.trim());
    const hasOwner = Boolean(ownerName.trim());
    const hasParcel = Boolean(parcelNumber.trim());
    const hasBkPg = Boolean(bookNumber.trim() || pageNumber.trim());

    let effectiveQueryType = queryType;
    let effectiveQueryValue = queryValue.trim();

    // Infer effective query type based on actual user inputs
    if (hasAddr && !hasOwner && !hasParcel && !hasBkPg) {
      effectiveQueryType = "address";
      effectiveQueryValue = address.trim();
    } else if (hasParcel && !hasOwner && !hasAddr && !hasBkPg) {
      effectiveQueryType = "parcel";
      effectiveQueryValue = parcelNumber.trim();
    } else if (hasBkPg && !hasOwner && !hasAddr && !hasParcel) {
      effectiveQueryType = "book_page";
      effectiveQueryValue = `${bookNumber.trim()}/${pageNumber.trim()}`.replace(/^\/|\/$/g, "");
    } else if (hasOwner && !hasAddr && !hasParcel && !hasBkPg) {
      effectiveQueryType = "owner";
      effectiveQueryValue = ownerName.trim();
    } else {
      // Multiple inputs or explicit selection
      if (effectiveQueryType === "address" && hasAddr) effectiveQueryValue = address.trim();
      else if (effectiveQueryType === "owner" && hasOwner) effectiveQueryValue = ownerName.trim();
      else if (effectiveQueryType === "parcel" && hasParcel) effectiveQueryValue = parcelNumber.trim();
      else if (effectiveQueryType === "book_page" && hasBkPg) {
        effectiveQueryValue = `${bookNumber.trim()}/${pageNumber.trim()}`.replace(/^\/|\/$/g, "");
      } else if (!effectiveQueryValue) {
        if (hasAddr) {
          effectiveQueryType = "address";
          effectiveQueryValue = address.trim();
        } else if (hasParcel) {
          effectiveQueryType = "parcel";
          effectiveQueryValue = parcelNumber.trim();
        } else if (hasOwner) {
          effectiveQueryType = "owner";
          effectiveQueryValue = ownerName.trim();
        }
      }
    }

    const updatedNodes = nodes.map((n) => {
      if (n.data.nodeId === "input") {
        return {
          ...n,
          data: {
            ...n.data,
            queryType: effectiveQueryType,
            queryValue: effectiveQueryValue,
            address: address.trim() || undefined,
            ownerName: ownerName.trim() || undefined,
            parcelNumber: parcelNumber.trim() || undefined,
          },
        };
      }
      return n;
    });

    const pipelineGraph = serializePipelineGraph(updatedNodes, edges);
    const validation = validatePipelineGraph(pipelineGraph);
    if (!validation.ok) {
      setError(validation.error || "Invalid pipeline graph");
      return;
    }

    setLoading(true);
    setError(null);
    reportFetchRef.current = null;

    // Signal the right panel to switch to Output tab and show it
    setShowRightPanel(true);
    setRunTrigger((t) => t + 1);

    if (nodes.some((n) => n.data.nodeId === "report")) {
      setNodes((nds) =>
        nds.map((n) =>
          n.data.nodeId === "report"
            ? { ...n, data: { ...n.data, reportId: undefined, reportRunId: undefined, reportStatus: "generating" } }
            : n
        )
      );
    }

    try {
      const result = await createSearch({
        state: (state || "AZ").toUpperCase(),
        county: (county || "gila").toLowerCase(),
        query_type: effectiveQueryType,
        query_value: effectiveQueryValue,
        address: address.trim() || undefined,
        owner_name: ownerName.trim() || undefined,
        parcel_number: parcelNumber.trim() || undefined,
        book_number: bookNumber.trim() || undefined,
        page_number: pageNumber.trim() || undefined,
        pipeline_graph: pipelineGraph,
      });

      setLastRunGraph(pipelineGraph);
      setActiveRunId(result.run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Run failed");
      // Revert run trigger on error
    } finally {
      setLoading(false);
    }
  }, [nodes, edges]);

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
    setShowRightPanel(true);
  }, []);

  const onPaneClick = useCallback(() => {
    setPaletteAnchor(null);
  }, []);

  return (
    <div className={`flex h-screen w-screen ${isDark ? "bg-[#0d1117]" : "bg-white"} overflow-hidden transition-colors`}>
      {/* ── Left: Workflows + Nodes sidebar ── */}
      <WorkflowSidebar
        activeId={activeWorkflowId}
        workflowTitle={workflowTitle}
        nodes={nodes}
        edges={edges}
        onSelect={onLoadWorkflow}
        onNew={onNewWorkflow}
        onSaveSuccess={(w) => {
          setActiveWorkflowId(w.id);
          setWorkflowTitle(w.name);
        }}
        selectedNodeId={selectedNodeId}
        onSelectNode={(id) => {
          setSelectedNodeId(id);
          setShowRightPanel(true);
        }}
        onDeleteNode={onDeleteNode}
        lastSavedWorkflow={lastSavedWorkflow}
        onAddNode={onAddFromPalette}
      />

      {/* ── Center: Canvas ── */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Top Toolbar */}
        <header className={`h-12 shrink-0 flex items-center px-4 gap-3 border-b ${
          isDark ? "border-white/[0.06] bg-[#0d1117]" : "border-slate-200 bg-white"
        } transition-colors`}>
          {/* Workflow title */}
          <div className="flex items-center gap-2 mr-2">
            {editingTitle ? (
              <input
                autoFocus
                value={workflowTitle}
                onChange={(e) => setWorkflowTitle(e.target.value)}
                onBlur={() => setEditingTitle(false)}
                onKeyDown={(e) => e.key === "Enter" && setEditingTitle(false)}
                className={`bg-transparent border-b border-violet-500 text-sm font-bold ${
                  isDark ? "text-zinc-100" : "text-slate-900"
                } focus:outline-none px-0 py-0.5 w-48`}
              />
            ) : (
              <button
                type="button"
                onClick={() => setEditingTitle(true)}
                className="flex items-center gap-1.5 group"
              >
                <span className={`text-sm font-bold ${isDark ? "text-zinc-100" : "text-slate-900"}`}>
                  {workflowTitle}
                </span>
                <svg className={`w-3.5 h-3.5 transition-colors ${
                  isDark ? "text-zinc-600 group-hover:text-zinc-400" : "text-slate-400 group-hover:text-slate-600"
                }`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                </svg>
              </button>
            )}
          </div>

          {/* Center: Canvas / View tabs */}
          <div className="flex-1 flex items-center justify-center">
            <div className={`flex items-center gap-0.5 rounded-lg p-0.5 border ${
              isDark ? "bg-zinc-900/60 border-white/[0.06]" : "bg-slate-100 border-slate-200"
            }`}>
              {(["canvas", ] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setActiveTab(t)}
                  className={`px-3.5 py-1.5 rounded-md text-xs font-semibold capitalize transition-colors ${
                    activeTab === t
                      ? "bg-violet-600 text-white shadow-sm"
                      : isDark
                      ? "text-zinc-400 hover:text-zinc-200"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          {/* Right: Status, Theme Toggle, and Action buttons */}
          <div className="flex items-center gap-3.5 shrink-0">
            {activeRunId && (
              <span className={`text-[10px] font-mono truncate max-w-[120px] hidden lg:inline ${
                isDark ? "text-zinc-600" : "text-slate-500"
              }`}>
                run {activeRunId.slice(0, 8)}…
              </span>
            )}

            <span className={`text-xs hidden md:flex items-center gap-1.5 ${
              isDark ? "text-zinc-400" : "text-slate-600 font-medium"
            }`}>
              <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
              All changes saved
            </span>

            {/* Vertical Divider */}
            <div className={`h-4 w-px ${isDark ? "bg-white/[0.1]" : "bg-slate-200"}`} />

            {/* Day / Dark Theme Toggle */}
            <div className="flex items-center">
              <ThemeToggle />
            </div>

            {/* Vertical Divider */}
            <div className={`h-4 w-px ${isDark ? "bg-white/[0.1]" : "bg-slate-200"}`} />

            {/* Action buttons */}
            <div className="flex items-center gap-2.5">
              <button
                type="button"
                onClick={handleSaveCurrentWorkflow}
                disabled={savingWorkflow}
                className={`px-3.5 py-1.5 rounded-lg border text-xs font-semibold transition-all flex items-center gap-1.5 ${
                  saveSuccessWorkflow
                    ? isDark
                      ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                      : "bg-emerald-50 text-emerald-700 border-emerald-300"
                    : isDark
                    ? "border-white/[0.1] text-zinc-300 hover:text-white hover:border-white/[0.2]"
                    : "border-slate-300 text-slate-800 hover:text-slate-950 hover:border-slate-400 bg-white shadow-sm"
                } disabled:opacity-50`}
              >
                {savingWorkflow ? (
                  <><div className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" /> Saving...</>
                ) : saveSuccessWorkflow ? (
                  <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg> Saved</>
                ) : (
                  <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" /></svg> Save</>
                )}
              </button>

              <button
                type="button"
                onClick={onRun}
                disabled={loading}
                className="px-4 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white text-xs font-bold transition-colors shadow-lg shadow-violet-900/30 flex items-center gap-1.5"
              >
                {loading ? (
                  <><div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" /> Running...</>
                ) : (
                  <><svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg> Run Pipeline</>
                )}
              </button>
            </div>
          </div>
        </header>

        {/* Error bar */}
        {error && (
          <div className="mx-4 mt-2 px-3 py-2 rounded-lg bg-red-950/60 border border-red-800/50 text-red-200 text-xs shrink-0 flex items-center gap-2">
            <svg className="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {error}
            <button type="button" onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-200">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        )}

        {/* Canvas */}
        <div ref={reactFlowWrapper} className="flex-1 min-h-0 relative">
          <ReactFlow
            nodes={styledNodes}
            edges={styledEdges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onDragOver={onDragOver}
            onDrop={onDrop}
            onNodesDelete={onNodesDelete}
            onEdgesDelete={onEdgesDelete}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            deleteKeyCode={["Backspace", "Delete"]}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            defaultEdgeOptions={{ type: "deletable", animated: true, deletable: true }}
            fitView
            fitViewOptions={{ padding: 0.3 }}
            minZoom={0.15}
            maxZoom={1.5}
            className={isDark ? "bg-[#0d1117]" : "bg-slate-100"}
          >
            <Background color={isDark ? "#1a2030" : "#cbd5e1"} gap={28} size={1} />
            <Controls
              className={
                isDark
                  ? "!bg-zinc-900/90 !border-white/[0.08] !shadow-xl [&>button]:!bg-zinc-800 [&>button]:!border-white/[0.08] [&>button]:!text-zinc-300"
                  : "!bg-white/95 !border-slate-300 !shadow-lg [&>button]:!bg-white [&>button]:!border-slate-200 [&>button]:!text-slate-700 hover:[&>button]:!bg-slate-100"
              }
              showInteractive={false}
            />
          </ReactFlow>

          {/* Empty Canvas Placeholder */}
          {nodes.length === 0 && (
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none z-10 p-6">
              <div className="text-center p-8 max-w-sm rounded-2xl bg-white/90 dark:bg-zinc-900/90 backdrop-blur-md border border-slate-200 dark:border-white/[0.08] shadow-2xl pointer-events-auto">
                <div className="w-14 h-14 rounded-2xl bg-violet-600/10 border border-violet-500/20 text-violet-500 flex items-center justify-center mx-auto mb-3.5 shadow-sm">
                  <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M12 4v16m8-8H4" />
                  </svg>
                </div>
                <h3 className="text-sm font-bold text-slate-900 dark:text-zinc-100">Blank Workflow Canvas</h3>
                <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1 mb-5 leading-relaxed">
                  Start building your custom workflow by dragging nodes from the sidebar or click below.
                </p>
                <button
                  type="button"
                  onClick={() => setPaletteAnchor({ x: 0, y: 0 })}
                  className="px-4 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-xs font-bold shadow-lg shadow-violet-900/30 transition-all flex items-center justify-center gap-2 w-full"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                  Add First Node
                </button>
              </div>
            </div>
          )}

          {/* Edge toggle handle when panel is closed */}
          {!showRightPanel && (
            <button
              type="button"
              onClick={() => setShowRightPanel(true)}
              className="absolute right-0 top-1/2 -translate-y-1/2 z-20 flex items-center gap-1 px-1.5 py-3 rounded-l-lg bg-white/90 dark:bg-zinc-800/90 hover:bg-slate-100 dark:hover:bg-zinc-700 border-l border-t border-b border-slate-300 dark:border-white/[0.1] text-slate-500 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100 shadow-xl transition-all group"
              title="Open Node Configuration Panel"
            >
              <svg className="w-3.5 h-3.5 group-hover:-translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M15 19l-7-7 7-7" />
              </svg>
            </button>
          )}

          {/* Add next step */}
          <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-30" style={{ pointerEvents: "auto" }}>
            <div className="relative flex flex-col items-center">
              {paletteAnchor && (
                <div
                  className="absolute bottom-full mb-3 left-1/2 -translate-x-1/2 z-50"
                  onClick={(e) => e.stopPropagation()}
                >
                  <NodePalettePopup
                    onClose={() => setPaletteAnchor(null)}
                    onAdd={onAddFromPalette}
                  />
                </div>
              )}

              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setPaletteAnchor(paletteAnchor ? null : { x: 0, y: 0 });
                }}
                className={`flex items-center gap-2 px-4 py-2 rounded-full border border-dashed text-xs font-medium transition-all backdrop-blur shadow-xl ${
                  paletteAnchor
                    ? "border-violet-500 text-white bg-violet-600 shadow-violet-950/50 ring-2 ring-violet-500/20"
                    : isDark
                    ? "border-white/20 text-zinc-400 hover:text-zinc-200 hover:border-white/40 bg-[#0d1117]/90 hover:bg-zinc-800/80"
                    : "border-slate-300 text-slate-600 hover:text-slate-900 hover:border-slate-400 bg-white/95 hover:bg-slate-50 shadow-slate-300/40"
                }`}
              >
                <svg
                  className={`w-3.5 h-3.5 transition-transform duration-200 ${paletteAnchor ? "rotate-45 text-white" : ""}`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                {paletteAnchor ? "Close menu" : "Add next step"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ── Right: Config Panel ── */}
      {showRightPanel && (
        <RightConfigPanel
          runId={activeRunId}
          pipelineGraph={lastRunGraph}
          runDetail={runDetail}
          events={events}
          connected={connected}
          liveFrame={liveFrame}
          selectedNodeId={selectedNodeId}
          selectedNodeData={selectedNodeData}
          onClose={() => {
            setShowRightPanel(false);
            setSelectedNodeId(null);
          }}
          runTrigger={runTrigger}
          onSave={handleSaveCurrentWorkflow}
          isSaving={savingWorkflow}
          isSaved={saveSuccessWorkflow}
        />
      )}
    </div>
  );
}

export default function PipelineEditor() {
  return (
    <ReactFlowProvider>
      <EditorCanvas />
    </ReactFlowProvider>
  );
}
