import { useCallback, useEffect, useRef, useState, DragEvent } from "react";

import {

  ReactFlow,

  Background,

  Controls,

  MiniMap,

  useNodesState,

  useEdgesState,

  ReactFlowProvider,

  useReactFlow,

  addEdge,

  Connection,

  Node,

} from "@xyflow/react";

import "@xyflow/react/dist/style.css";



import PipelineNode from "./PipelineNode";

import AIAgentNode from "./AIAgentNode";

import NodeSidebar from "./NodeSidebar";

import BrowserPanel from "./BrowserPanel";

import {
  DEFAULT_EDGES,
  DEFAULT_NODES,
  getInputFromNodes,
} from "../../lib/defaultPipeline";
import { getSidebarNode, createNodeFromCatalog } from "../../lib/nodeCatalog";
import { serializePipelineGraph, validatePipelineGraph, PipelineGraph } from "../../lib/pipelineGraph";
import { createSearch, getReportByRun } from "../../api/client";
import { useRunStream } from "../../hooks/useRunStream";



const nodeTypes = {

  pipelineNode: PipelineNode,

  aiAgentNode: AIAgentNode,

};



const DRAG_TYPE = "application/reactflow";



function EditorCanvas() {

  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  const { screenToFlowPosition } = useReactFlow();

  const [nodes, setNodes, onNodesChange] = useNodesState(DEFAULT_NODES);

  const [edges, setEdges, onEdgesChange] = useEdgesState(DEFAULT_EDGES);

  const [loading, setLoading] = useState(false);

  const [error, setError] = useState<string | null>(null);

  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [lastRunGraph, setLastRunGraph] = useState<PipelineGraph | null>(null);
  const { runDetail, events, connected, liveFrame } = useRunStream(activeRunId || undefined);
  const reportFetchRef = useRef<string | null>(null);

  useEffect(() => {
    if (!activeRunId) return;

    const reportEvent = [...events]
      .reverse()
      .find(
        (e) =>
          e.event_type === "node_completed" &&
          e.payload?.node === "ReportNode" &&
          e.payload?.report_id
      );

    if (reportEvent?.payload?.report_id) {
      const reportId = String(reportEvent.payload.report_id);
      setNodes((nds) =>
        nds.map((n) =>
          n.data.nodeId === "report"
            ? {
                ...n,
                data: {
                  ...n.data,
                  reportId,
                  reportRunId: activeRunId,
                  reportStatus: "ready",
                },
              }
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
              ? {
                  ...n,
                  data: {
                    ...n.data,
                    reportId: report.id,
                    reportRunId: activeRunId,
                    reportStatus: "ready",
                  },
                }
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



  const onConnect = useCallback(

    (connection: Connection) => setEdges((eds) => addEdge({ ...connection, animated: true }, eds)),

    [setEdges]

  );

  const onNodesDelete = useCallback(
    (deleted: Node[]) => {
      const ids = new Set(deleted.map((n) => n.id));
      setEdges((eds) => eds.filter((e) => !ids.has(e.source) && !ids.has(e.target)));
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



      const position = screenToFlowPosition({

        x: event.clientX,

        y: event.clientY,

      });



      const newNode = createNodeFromCatalog(def, position);

      setNodes((nds) => nds.concat(newNode));

    },

    [screenToFlowPosition, setNodes]

  );



  const onRun = useCallback(async () => {

    const { state, county, queryType, queryValue, bookNumber, pageNumber } = getInputFromNodes(nodes);

    if (queryType === "book_page") {
      if (!bookNumber.trim() || !pageNumber.trim()) {
        setError("Enter book and page numbers in the Input node");
        return;
      }
    } else if (!queryValue.trim()) {
      setError("Enter a search value in the Input node");
      return;
    }

    if (!county) {

      setError("Select a county in the Input node");

      return;

    }



    const pipelineGraph = serializePipelineGraph(nodes, edges);
    const validation = validatePipelineGraph(pipelineGraph);
    if (!validation.ok) {
      setError(validation.error || "Invalid pipeline graph");
      return;
    }

    setLoading(true);
    setError(null);
    reportFetchRef.current = null;

    if (nodes.some((n) => n.data.nodeId === "report")) {
      setNodes((nds) =>
        nds.map((n) =>
          n.data.nodeId === "report"
            ? {
                ...n,
                data: {
                  ...n.data,
                  reportId: undefined,
                  reportRunId: undefined,
                  reportStatus: "generating",
                },
              }
            : n
        )
      );
    }

    try {
      const result = await createSearch({
        state: state.toUpperCase(),
        county: county.toLowerCase(),
        query_type: queryType,
        query_value:
          queryType === "book_page"
            ? `${bookNumber.trim()}/${pageNumber.trim()}`
            : queryValue.trim(),
        book_number: queryType === "book_page" ? bookNumber.trim() : undefined,
        page_number: queryType === "book_page" ? pageNumber.trim() : undefined,
        pipeline_graph: pipelineGraph,
      });

      setLastRunGraph(pipelineGraph);
      setActiveRunId(result.run_id);

    } catch (e) {

      setError(e instanceof Error ? e.message : "Run failed");

    } finally {

      setLoading(false);

    }

  }, [nodes, edges]);



  return (

    <div className="flex flex-col h-[calc(100vh-52px)] bg-[#0a0e14]">

      <div className="flex items-center justify-between px-4 py-2 border-b border-teal-900/40 bg-[#0c1017] shrink-0">

        <div className="flex items-center gap-3">

          <span className="text-sm font-medium text-teal-300">Editor</span>

          <span className="text-zinc-600">|</span>

          <span className="text-sm text-zinc-500">Browser Preview</span>

          {activeRunId && (

            <span className="text-[10px] font-mono text-zinc-600 truncate max-w-[180px]">

              run {activeRunId.slice(0, 8)}…

            </span>

          )}

        </div>

        <button

          type="button"

          onClick={onRun}

          disabled={loading}

          className="px-5 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-white text-sm font-semibold shadow-lg shadow-teal-900/30"

        >

          {loading ? "Running..." : "Run"}

        </button>

      </div>



      {error && (

        <div className="mx-4 mt-2 px-3 py-2 rounded-lg bg-red-950/60 border border-red-800 text-red-200 text-sm shrink-0">

          {error}

        </div>

      )}



      <div className="flex flex-1 min-h-0">

        <NodeSidebar />



        <div ref={reactFlowWrapper} className="flex-1 min-w-0 border-r border-teal-900/30">

          <ReactFlow

            nodes={nodes}

            edges={edges}

            onNodesChange={onNodesChange}

            onEdgesChange={onEdgesChange}

            onConnect={onConnect}

            onDragOver={onDragOver}

            onDrop={onDrop}

            onNodesDelete={onNodesDelete}

            deleteKeyCode={["Backspace", "Delete"]}

            nodeTypes={nodeTypes}

            fitView

            fitViewOptions={{ padding: 0.2 }}

            minZoom={0.2}

            maxZoom={1.5}

            className="bg-[#0a0e14]"

          >

            <Background color="#1e3a4a" gap={24} />

            <Controls className="!bg-zinc-900 !border-teal-900/50 !shadow-lg [&>button]:!bg-zinc-800 [&>button]:!border-teal-900/40 [&>button]:!text-teal-200" />

            <MiniMap

              nodeColor={(n) => (n.type === "aiAgentNode" ? "#8b5cf6" : "#14b8a6")}

              maskColor="rgb(10 14 20 / 0.85)"

              className="!bg-zinc-900 !border-teal-900/40"

            />

          </ReactFlow>

        </div>



        <div className="w-[42%] max-w-xl min-w-[300px] shrink-0">

          <BrowserPanel
            runId={activeRunId}
            pipelineGraph={lastRunGraph}
            runDetail={runDetail}
            events={events}
            connected={connected}
            liveFrame={liveFrame}
          />

        </div>

      </div>

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


