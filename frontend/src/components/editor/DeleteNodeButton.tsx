import { MouseEvent } from "react";
import { useReactFlow } from "@xyflow/react";

interface Props {
  nodeId: string;
  className?: string;
  title?: string;
}

export default function DeleteNodeButton({
  nodeId,
  className = "",
  title = "Delete node",
}: Props) {
  const { setNodes, setEdges } = useReactFlow();

  function onDelete(event: MouseEvent) {
    event.stopPropagation();
    event.preventDefault();
    setNodes((nodes) => nodes.filter((n) => n.id !== nodeId));
    setEdges((edges) => edges.filter((e) => e.source !== nodeId && e.target !== nodeId));
  }

  return (
    <button
      type="button"
      onClick={onDelete}
      title={title}
      aria-label={title}
      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-zinc-700/80 bg-zinc-900/80 text-zinc-400 hover:border-red-800/80 hover:bg-red-950/60 hover:text-red-300 transition-colors nodrag nopan ${className}`}
    >
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path
          d="M2.5 2.5L9.5 9.5M9.5 2.5L2.5 9.5"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    </button>
  );
}
