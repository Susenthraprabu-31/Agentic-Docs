import { memo, useEffect, useMemo, useState } from "react";
import { Handle, Position, NodeProps, useNodes, useEdges } from "@xyflow/react";
import { getOpenAIStatus, testAIAgent, AIAgentResult } from "../../api/client";
import { PipelineNodeData } from "../../lib/defaultPipeline";
import DeleteNodeButton from "./DeleteNodeButton";
import { stopFlowPointer, usePatchNodeData } from "./usePatchNodeData";

const MODELS = [
  "gpt-4.1",
  "gpt-4.1-mini",
  "gpt-4o",
  "gpt-4o-mini",
  "gpt-4.5-preview",
  "o3-mini",
  "o1",
  "gpt-4-turbo",
  "gpt-4",
  "gpt-3.5-turbo",
];
const AGENT_TYPES = ["orchestrator", "assistant", "analyzer"];

const fieldClass =
  "nodrag nopan w-full rounded-md bg-zinc-950 border border-violet-900/50 px-2 py-1.5 text-zinc-100 focus:border-violet-500 outline-none";

type Props = NodeProps & { data: PipelineNodeData };

function AIAgentNodeComponent({ id, data }: Props) {
  const patch = usePatchNodeData(id);
  const edges = useEdges();
  const nodes = useNodes();

  const connectedBeforeNodes = useMemo(() => {
    const incoming = edges.filter((e) => e.target === id);
    return incoming
      .map((e) => {
        const srcNode = nodes.find((n) => n.id === e.source);
        if (!srcNode) return null;
        const sData = srcNode.data as PipelineNodeData | undefined;
        const sNodeId = String(sData?.nodeId || srcNode.id || "").toLowerCase();
        const sLabel = String(sData?.label || sNodeId || "Node");
        return { canvasId: srcNode.id, nodeId: sNodeId, label: sLabel };
      })
      .filter(Boolean) as { canvasId: string; nodeId: string; label: string }[];
  }, [edges, nodes, id]);

  const connectedAfterNodes = useMemo(() => {
    const outgoing = edges.filter((e) => e.source === id);
    return outgoing
      .map((e) => {
        const tgtNode = nodes.find((n) => n.id === e.target);
        if (!tgtNode) return null;
        const tData = tgtNode.data as PipelineNodeData | undefined;
        const tNodeId = String(tData?.nodeId || tgtNode.id || "").toLowerCase();
        const tLabel = String(tData?.label || tNodeId || "Node");
        return { canvasId: tgtNode.id, nodeId: tNodeId, label: tLabel };
      })
      .filter(Boolean) as { canvasId: string; nodeId: string; label: string }[];
  }, [edges, nodes, id]);

  const [apiConfigured, setApiConfigured] = useState<boolean | null>(null);
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<AIAgentResult | null>(null);

  useEffect(() => {
    getOpenAIStatus()
      .then((r) => setApiConfigured(r.configured))
      .catch(() => setApiConfigured(false));
  }, []);

  async function onTestAgent() {
    setTesting(true);
    setTestError(null);
    setTestResult(null);
    try {
      const primaryPrev = connectedBeforeNodes[0];
      const primaryNext = connectedAfterNodes[0];
      const result = await testAIAgent({
        config: {
          agent_name: data.agentName || "OpenAI Agent",
          instructions: data.instructions || "You are a helpful AI assistant.",
          user_prompt: data.userPrompt || "Say hello and confirm the API is working.",
          model: data.model || "gpt-4o",
          temperature: data.temperature ?? 0.7,
          max_tokens: data.maxTokens ?? 1000,
        },
        context_data: {
          test: true,
          node_id: id,
          previous_node: primaryPrev?.nodeId || "previous",
          previous_label: primaryPrev?.label,
          previous_canvas_id: primaryPrev?.canvasId,
          next_node: primaryNext?.nodeId,
          next_label: primaryNext?.label,
          next_canvas_id: primaryNext?.canvasId,
        },
      });
      setTestResult(result);
    } catch (e) {
      setTestError(e instanceof Error ? e.message : "Test failed");
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="pipeline-node-card w-[320px] rounded-xl border border-violet-800/50 bg-[#1a1524] shadow-xl shadow-black/50 text-zinc-100">
      <Handle type="target" position={Position.Top} className="!bg-violet-400 !w-2 !h-2" />

      <div className="px-3 py-2.5 border-b border-violet-900/40 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-violet-400 text-sm">✦</span>
          <span className="font-semibold text-sm text-violet-100">{data.label || "OpenAI Agent"}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-900/40 text-violet-300 capitalize">
            {data.agentType || "orchestrator"}
          </span>
          <label className="flex items-center gap-1 text-[10px] text-zinc-500 cursor-pointer nodrag">
            <input
              type="checkbox"
              checked={data.enabled !== false}
              onChange={(e) => patch({ enabled: e.target.checked })}
              className="rounded"
            />
            On
          </label>
          <DeleteNodeButton nodeId={id} />
        </div>
      </div>

      <div className="p-3 space-y-3 text-xs max-h-[520px] overflow-y-auto nodrag nopan" onPointerDown={stopFlowPointer}>
        <div>
          <label className="block text-zinc-400 mb-1">Agent Name</label>
          <input
            value={data.agentName ?? ""}
            onChange={(e) => patch({ agentName: e.target.value, label: e.target.value || "OpenAI Agent" })}
            placeholder="OpenAI Agent"
            className={fieldClass}
          />
        </div>

        <div>
          <label className="block text-zinc-400 mb-1">Instructions</label>
          <textarea
            value={data.instructions ?? ""}
            onChange={(e) => patch({ instructions: e.target.value })}
            placeholder="You are a helpful AI assistant."
            rows={3}
            className={`${fieldClass} resize-y min-h-[60px]`}
          />
          <p className="text-[10px] text-zinc-600 mt-1">Define the agent&apos;s role and behavior</p>
        </div>

        {/* Connected Workflow Topology */}
        <div className="p-2.5 rounded-lg border border-violet-900/40 bg-zinc-950/60 text-xs space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-wider text-violet-400 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-violet-400" />
              Connected Workflow
            </span>
            <span className="text-[10px] text-zinc-500 font-mono">Topology</span>
          </div>

          <div className="flex items-start gap-2 text-xs">
            <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-800/40 shrink-0">
              ← Before
            </span>
            {connectedBeforeNodes.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {connectedBeforeNodes.map((n) => (
                  <span
                    key={n.canvasId}
                    className="px-1.5 py-0.5 rounded text-[11px] font-medium bg-zinc-900 text-zinc-200 border border-white/[0.08] flex items-center gap-1"
                  >
                    <span>{n.label}</span>
                    <code className="text-violet-400 font-mono text-[10px]">({n.nodeId})</code>
                  </span>
                ))}
              </div>
            ) : (
              <span className="text-[11px] text-amber-400 italic">No node connected before</span>
            )}
          </div>

          <div className="flex items-start gap-2 text-xs">
            <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold bg-blue-950/80 text-blue-300 border border-blue-800/40 shrink-0">
              → After
            </span>
            {connectedAfterNodes.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {connectedAfterNodes.map((n) => (
                  <span
                    key={n.canvasId}
                    className="px-1.5 py-0.5 rounded text-[11px] font-medium bg-zinc-900 text-zinc-200 border border-white/[0.08] flex items-center gap-1"
                  >
                    <span>{n.label}</span>
                    <code className="text-blue-400 font-mono text-[10px]">({n.nodeId})</code>
                  </span>
                ))}
              </div>
            ) : (
              <span className="text-[11px] text-zinc-500 italic">No node connected after</span>
            )}
          </div>
        </div>

        <div>
          <label className="block text-zinc-400 mb-1">User Input / Prompt</label>
          <textarea
            value={data.userPrompt ?? ""}
            onChange={(e) => patch({ userPrompt: e.target.value })}
            placeholder={
              connectedBeforeNodes.length > 0
                ? `Analyze this data: {{workflow.previous}}`
                : "Analyze this data: {{workflow.previous}}"
            }
            rows={3}
            className={`${fieldClass} resize-y min-h-[60px] font-mono text-[11px]`}
          />
          <div className="flex flex-wrap items-center gap-1 mt-1.5">
            <span className="text-[10px] text-zinc-500 mr-0.5">Insert:</span>

            {connectedBeforeNodes.length > 0 ? (
              <>
                <button
                  type="button"
                  onClick={() => {
                    const cur = data.userPrompt || "";
                    const val = cur.includes("{{workflow.previous}}")
                      ? cur
                      : cur
                      ? `${cur} {{workflow.previous}}`
                      : "Analyze this data: {{workflow.previous}}\n\nPlease provide insights and recommendations.";
                    patch({ userPrompt: val });
                  }}
                  className="text-[10px] px-2 py-0.5 rounded bg-violet-900/50 hover:bg-violet-800 text-violet-300 border border-violet-700/50 transition-colors font-medium flex items-center gap-1"
                  title={`Pass preceding step result (${connectedBeforeNodes[0].label})`}
                >
                  <span>+ &#123;&#123;workflow.previous&#125;&#125;</span>
                  <span className="text-[9px] text-violet-400/80 font-normal">({connectedBeforeNodes[0].label})</span>
                </button>

                {connectedBeforeNodes.map((n) => (
                  <button
                    key={n.nodeId}
                    type="button"
                    onClick={() => {
                      const cur = data.userPrompt || "";
                      const tok = `{{workflow.${n.nodeId}}}`;
                      patch({ userPrompt: cur ? `${cur} ${tok}` : tok });
                    }}
                    className="text-[10px] px-2 py-0.5 rounded bg-emerald-950/40 hover:bg-emerald-900/60 text-emerald-300 border border-emerald-700/40 transition-colors font-medium"
                    title={`Pass ${n.label} result`}
                  >
                    + &#123;&#123;workflow.{n.nodeId}&#125;&#125;
                  </button>
                ))}
              </>
            ) : (
              <span className="text-[10px] text-amber-400/90 italic">
                Connect an upstream node to enable result variables
              </span>
            )}
          </div>
          <p className="text-[10px] text-zinc-500 mt-1">
            {connectedBeforeNodes.length > 0 ? (
              <>
                Connected to <strong className="text-zinc-200">{connectedBeforeNodes.map((n) => n.label).join(", ")}</strong>. Use{" "}
                <code className="text-violet-400">{"{{workflow.previous}}"}</code> or{" "}
                <code className="text-emerald-400">{`{{workflow.${connectedBeforeNodes[0].nodeId}}}`}</code> to pass its result.
              </>
            ) : (
              <>
                Connect an upstream node (e.g. Assessor, Recorder, Tax, Report) to pass its data into this AI agent.
              </>
            )}
          </p>
        </div>

        {Boolean(data.aiAgentResponse) && (
          <div className="rounded-lg border border-emerald-800/40 bg-emerald-950/30 p-2.5 space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                Pipeline Analysis Result
              </span>
              <span className="text-[10px] text-zinc-500">{data.model || "gpt-4o"}</span>
            </div>
            <p className="text-[11px] text-zinc-200 whitespace-pre-wrap max-h-28 overflow-y-auto">
              {String(data.aiAgentResponse)}
            </p>
          </div>
        )}

        <div className="rounded-lg border border-violet-900/40 bg-zinc-950/60 p-2.5 space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-zinc-400">
              Authentication <span className="text-red-400">*</span>
            </label>
            <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-900/30 text-emerald-400 border border-emerald-800/40">
              From .env
            </span>
          </div>
          <div className="flex items-center gap-2 rounded-md bg-zinc-900 border border-zinc-800 px-2 py-1.5">
            <span className="text-zinc-500 font-mono text-[11px]">OPENAI_API_KEY</span>
            <span className="text-zinc-600 font-mono">••••••••</span>
          </div>
          {apiConfigured === null ? (
            <p className="text-[10px] text-zinc-600">Checking backend configuration…</p>
          ) : apiConfigured ? (
            <p className="text-[10px] text-emerald-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              API key configured in backend .env
            </p>
          ) : (
            <p className="text-[10px] text-red-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
              Set OPENAI_API_KEY in backend .env and restart server
            </p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-zinc-400 mb-1">Model</label>
            <select
              value={data.model || "gpt-4o"}
              onChange={(e) => patch({ model: e.target.value })}
              className={fieldClass}
            >
              {MODELS.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-zinc-400 mb-1">Agent Type</label>
            <select
              value={data.agentType || "orchestrator"}
              onChange={(e) => patch({ agentType: e.target.value })}
              className={fieldClass}
            >
              {AGENT_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        </div>

        <button
          type="button"
          onClick={onTestAgent}
          disabled={testing || apiConfigured === false}
          className="w-full rounded-lg border border-violet-700/60 bg-violet-900/30 px-3 py-2 text-xs font-medium text-violet-100 hover:bg-violet-900/50 disabled:opacity-50 nodrag"
        >
          {testing ? "Calling POST /ai-agent/test…" : "Test Agent (Network tab)"}
        </button>

        {testError && (
          <p className="text-[10px] text-red-400 border border-red-900/50 rounded p-2">{testError}</p>
        )}
        {testResult && (
          <div className="rounded-lg border border-violet-800/40 bg-zinc-950/80 p-2 space-y-1">
            <p className="text-[10px] text-emerald-400">
              {testResult.endpoint} · {testResult.duration_ms}ms · {testResult.model}
            </p>
            <p className="text-[11px] text-zinc-300 whitespace-pre-wrap max-h-32 overflow-y-auto">
              {testResult.content}
            </p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-zinc-400 mb-1">Temperature</label>
            <input
              type="number"
              min={0}
              max={2}
              step={0.1}
              value={data.temperature ?? 0.7}
              onChange={(e) => patch({ temperature: parseFloat(e.target.value) || 0.7 })}
              className={fieldClass}
            />
            <p className="text-[10px] text-zinc-600 mt-0.5">0 = focused, 2 = creative</p>
          </div>
          <div>
            <label className="block text-zinc-400 mb-1">Max Tokens</label>
            <input
              type="number"
              min={100}
              max={16000}
              step={100}
              value={data.maxTokens ?? 1000}
              onChange={(e) => patch({ maxTokens: parseInt(e.target.value, 10) || 1000 })}
              className={fieldClass}
            />
            <p className="text-[10px] text-zinc-600 mt-0.5">Max response length</p>
          </div>
        </div>
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-violet-400 !w-2 !h-2" />
    </div>
  );
}

export default memo(AIAgentNodeComponent);
