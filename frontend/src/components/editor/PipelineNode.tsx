import { memo, useEffect, useState } from "react";
import { Handle, Position, NodeProps, useReactFlow } from "@xyflow/react";
import {
  CountyOption,
  downloadOfficialDocument,
  downloadReportPdf,
  generatePlaywrightInstructions,
  getCountiesForState,
  QueryType,
} from "../../api/client";
import { PipelineNodeData } from "../../lib/defaultPipeline";
import { US_STATES } from "../../data/states";
import DeleteNodeButton from "./DeleteNodeButton";
import { stopFlowPointer, usePatchNodeData } from "./usePatchNodeData";

type Props = NodeProps & { data: PipelineNodeData };

const URL_NODES = new Set(["netr", "assessor", "recorder", "gis", "tax"]);
const NOTES_NODES = new Set(["netr", "assessor", "recorder", "gis", "tax", "platform", "normalizer"]);
const AI_INSTRUCTION_NODES = new Set(["netr", "assessor", "recorder", "gis", "tax"]);

const fieldClass =
  "nodrag nopan w-full rounded-md bg-zinc-950 border border-teal-900/50 px-2 py-1.5 text-zinc-100 focus:border-teal-600 outline-none";

function PipelineNodeComponent({ id, data }: Props) {
  const patch = usePatchNodeData(id);
  const { getNodes } = useReactFlow();
  const [counties, setCounties] = useState<CountyOption[]>([]);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [layoutType, setLayoutType] = useState<string | null>(null);

  const isInput = data.nodeId === "input";
  const isReport = data.nodeId === "report";
  const showUrl = URL_NODES.has(data.nodeId);
  const showNotes = NOTES_NODES.has(data.nodeId);
  const showAiGenerate = AI_INSTRUCTION_NODES.has(data.nodeId);
  const canDisable = !["input", "platform", "normalizer", "report", "output"].includes(data.nodeId);

  const inputNode = getNodes().find((n) => n.data.nodeId === "input");
  const inputState = (inputNode?.data.state as string) || "AZ";
  const inputCounty = (inputNode?.data.county as string) || "";
  const inputQueryType = (inputNode?.data.queryType as QueryType) || "owner";
  const inputQueryValue = (inputNode?.data.queryValue as string) || "";
  const inputBookNumber = (inputNode?.data.bookNumber as string) || "";
  const inputPageNumber = (inputNode?.data.pageNumber as string) || "";
  const canGenerateAi = Boolean(
    inputCounty.trim() &&
      (inputQueryType === "book_page"
        ? inputBookNumber.trim() && inputPageNumber.trim()
        : inputQueryValue.trim())
  );

  async function handleGenerateInstructions() {
    if (!canGenerateAi) return;
    setGenerating(true);
    setGenerateError(null);
    setLayoutType(null);
    try {
      const result = await generatePlaywrightInstructions({
        node_id: data.nodeId,
        state: inputState.toUpperCase(),
        county: inputCounty.toLowerCase(),
        query_type: inputQueryType,
        url: data.url?.trim() || undefined,
        query_value:
          inputQueryType === "book_page"
            ? `${inputBookNumber.trim()}/${inputPageNumber.trim()}`
            : inputQueryValue.trim(),
        playwright_notes: data.playwrightNotes?.trim() || undefined,
      });
      patch({
        playwrightNotes: result.instructions,
        ...(showUrl && !data.url?.trim() && result.resolved_url ? { url: result.resolved_url } : {}),
      });
      setLayoutType(result.layout_type);
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  }

  useEffect(() => {
    if (!isInput || !data.state) return;
    let cancelled = false;
    getCountiesForState(data.state)
      .then((list) => {
        if (cancelled) return;
        setCounties(list);
        const current = data.county || "";
        if (!list.some((c) => c.slug === current)) {
          patch({ county: list[0]?.slug ?? "" });
        }
      })
      .catch(() => {
        if (!cancelled) setCounties([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isInput, data.state, patch]);

  return (
    <div className="pipeline-node-card w-[280px] rounded-xl border border-teal-800/60 bg-[#141c24] shadow-xl shadow-black/40 text-zinc-100">
      <Handle type="target" position={Position.Top} className="!bg-teal-400 !w-2 !h-2" />

      <div className="px-3 py-2 border-b border-teal-900/40 flex items-center justify-between gap-2">
        <span className="font-semibold text-sm text-teal-100 truncate">{data.label}</span>
        <div className="flex items-center gap-2 shrink-0">
          {canDisable && (
            <label className="flex items-center gap-1.5 text-[10px] text-zinc-500 cursor-pointer nodrag nopan">
              <input
                type="checkbox"
                checked={data.enabled !== false}
                onChange={(e) => patch({ enabled: e.target.checked })}
                onPointerDown={stopFlowPointer}
                className="rounded"
              />
              Enabled
            </label>
          )}
          <DeleteNodeButton nodeId={id} />
        </div>
      </div>

      <div className="p-3 space-y-3 text-xs nodrag nopan" onPointerDown={stopFlowPointer}>
        {isInput && (
          <>
            <div>
              <label className="block text-zinc-500 mb-1">State</label>
              <select
                value={data.state || "AZ"}
                onChange={(e) => patch({ state: e.target.value })}
                className={fieldClass}
              >
                {US_STATES.map((s) => (
                  <option key={s.code} value={s.code}>{s.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-zinc-500 mb-1">County</label>
              <select
                value={data.county || ""}
                onChange={(e) => patch({ county: e.target.value })}
                className={fieldClass}
              >
                {counties.map((c) => (
                  <option key={c.slug} value={c.slug}>{c.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-zinc-500 mb-1">Search by</label>
              <div className="flex gap-2 flex-wrap">
                {(["owner", "parcel", "address", "book_page"] as QueryType[]).map((t) => (
                  <label key={t} className="flex items-center gap-1 cursor-pointer capitalize">
                    <input
                      type="radio"
                      checked={data.queryType === t}
                      onChange={() => patch({ queryType: t })}
                    />
                    {t === "book_page" ? "Book/Page" : t}
                  </label>
                ))}
              </div>
            </div>
            {data.queryType === "book_page" ? (
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-zinc-500 mb-1">Book number</label>
                  <input
                    value={data.bookNumber || ""}
                    onChange={(e) => patch({ bookNumber: e.target.value })}
                    placeholder="e.g. 1494"
                    className={fieldClass}
                  />
                </div>
                <div>
                  <label className="block text-zinc-500 mb-1">Page number</label>
                  <input
                    value={data.pageNumber || ""}
                    onChange={(e) => patch({ pageNumber: e.target.value })}
                    placeholder="e.g. 2483"
                    className={fieldClass}
                  />
                </div>
              </div>
            ) : (
              <div>
                <label className="block text-zinc-500 mb-1">Search value</label>
                <input
                  value={data.queryValue || ""}
                  onChange={(e) => patch({ queryValue: e.target.value })}
                  placeholder="Owner name, parcel, or address"
                  className={fieldClass}
                />
              </div>
            )}
          </>
        )}

        {showUrl && (
          <div>
            <label className="block text-zinc-500 mb-1">URL</label>
            <input
              value={data.url ?? ""}
              onChange={(e) => patch({ url: e.target.value })}
              placeholder="https://... (leave empty for auto)"
              className={fieldClass}
            />
          </div>
        )}

        {showNotes && (
          <div>
            {showAiGenerate && (
              <div className="mb-2 space-y-1.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <button
                    type="button"
                    disabled={generating || !canGenerateAi}
                    title={
                      canGenerateAi
                        ? "Resolve county URL, run search, then write Playwright instructions"
                        : "Set state, county, and search value in the Input node first"
                    }
                    onClick={handleGenerateInstructions}
                    className="px-2.5 py-1 rounded-md bg-violet-700 hover:bg-violet-600 disabled:opacity-50 disabled:cursor-not-allowed text-white text-[10px] font-semibold uppercase tracking-wide"
                  >
                    {generating ? "Searching…" : "Generate with AI"}
                  </button>
                  {layoutType && (
                    <span className="text-[10px] text-zinc-500 capitalize">
                      layout: {layoutType.replace(/_/g, " ")}
                    </span>
                  )}
                </div>
                {generateError && (
                  <p className="text-[10px] text-red-400 leading-snug">{generateError}</p>
                )}
                <p className="text-[10px] text-zinc-600 leading-snug">
                  Resolves URL from Input county, runs search, then writes Playwright steps.
                </p>
              </div>
            )}
            <label className="block text-zinc-500 mb-1">Playwright instructions</label>
            <textarea
              value={data.playwrightNotes ?? ""}
              onChange={(e) => patch({ playwrightNotes: e.target.value })}
              placeholder='Click "Generate with AI" to analyze the county site, or write steps manually'
              rows={3}
              className={`${fieldClass} resize-y min-h-[60px] placeholder:text-zinc-600`}
            />
          </div>
        )}

        {isReport && (
          <div className="space-y-2">
            <p className="text-zinc-500">Generates a PDF from collected property records.</p>
            {data.reportStatus === "generating" && (
              <p className="text-teal-400 flex items-center gap-2">
                <span className="inline-block w-3 h-3 border border-teal-400 border-t-transparent rounded-full animate-spin" />
                Generating report...
              </p>
            )}
            {data.reportStatus === "ready" && data.reportId && (
              <div className="flex flex-col gap-2">
                <a
                  href={`/reports/run/${data.reportRunId || ""}`}
                  target="_blank"
                  rel="noreferrer"
                  className="w-full text-center px-3 py-1.5 rounded-md bg-teal-700 hover:bg-teal-600 text-white text-xs font-medium"
                >
                  View Report
                </a>
                <button
                  type="button"
                  onClick={async () => {
                    if (!data.reportId || !data.reportRunId) return;
                    try {
                      await downloadReportPdf(String(data.reportId), String(data.reportRunId));
                    } catch (err) {
                      alert(err instanceof Error ? err.message : "Download failed");
                    }
                  }}
                  className="w-full px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 border border-teal-800 text-teal-200 text-xs font-medium"
                >
                  Download Report
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    if (!data.reportRunId) return;
                    try {
                      await downloadOfficialDocument(String(data.reportRunId));
                    } catch (err) {
                      alert(err instanceof Error ? err.message : "Document download failed");
                    }
                  }}
                  className="w-full px-3 py-1.5 rounded-md bg-teal-900/60 hover:bg-teal-900 border border-teal-600 text-teal-200 text-xs font-medium flex items-center justify-center gap-1.5"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Download Official Document
                </button>
              </div>
            )}
            {data.reportStatus === "failed" && (
              <p className="text-red-400">Report generation failed. Check the run log.</p>
            )}
            {(!data.reportStatus || data.reportStatus === "idle") && (
              <p className="text-zinc-600 italic">Run the pipeline to generate a report</p>
            )}
          </div>
        )}

        {!isInput && !showUrl && !showNotes && !isReport && (
          <p className="text-zinc-600 italic">Auto — no manual inputs</p>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-teal-400 !w-2 !h-2" />
    </div>
  );
}

export default memo(PipelineNodeComponent);
