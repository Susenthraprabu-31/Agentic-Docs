import { memo, useEffect, useState } from "react";
import { Handle, Position, NodeProps } from "@xyflow/react";
import { getOpenAIStatus, testAIAgent, AIAgentResult } from "../../api/client";
import { PipelineNodeData } from "../../lib/defaultPipeline";
import DeleteNodeButton from "./DeleteNodeButton";
import { stopFlowPointer, usePatchNodeData } from "./usePatchNodeData";

const MODELS = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"];
const AGENT_TYPES = ["orchestrator", "assistant", "analyzer"];

const fieldClass =
  "nodrag nopan w-full rounded-md bg-zinc-950 border border-violet-900/50 px-2 py-1.5 text-zinc-100 focus:border-violet-500 outline-none";

type Props = NodeProps & { data: PipelineNodeData };

function AIAgentNodeComponent({ id, data }: Props) {
  const patch = usePatchNodeData(id);
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
      const result = await testAIAgent({
        config: {
          agent_name: data.agentName || "OpenAI Agent",
          instructions: data.instructions || "You are a helpful AI assistant.",
          user_prompt: data.userPrompt || "Say hello and confirm the API is working.",
          model: data.model || "gpt-4o",
          temperature: data.temperature ?? 0.7,
          max_tokens: data.maxTokens ?? 1000,
        },
        context_data: { test: true, node_id: id },
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

        <div>
          <label className="block text-zinc-400 mb-1">User Input / Prompt</label>
          <textarea
            value={data.userPrompt ?? ""}
            onChange={(e) => patch({ userPrompt: e.target.value })}
            placeholder="Analyze this data: {{dataFlow.previous()}}"
            rows={3}
            className={`${fieldClass} resize-y min-h-[60px] font-mono text-[11px]`}
          />
          <p className="text-[10px] text-zinc-600 mt-1">
            Use <code className="text-violet-400">{"{{dataFlow.previous()}}"}</code> for prior step data
          </p>
        </div>

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
