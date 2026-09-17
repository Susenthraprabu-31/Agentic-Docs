import { PointerEvent, useCallback } from "react";
import { useReactFlow } from "@xyflow/react";
import { PipelineNodeData } from "../../lib/defaultPipeline";

/** Patch node.data — must use setNodes when nodes are controlled via useNodesState. */
export function usePatchNodeData(nodeId: string) {
  const { setNodes } = useReactFlow();

  return useCallback(
    (fields: Partial<PipelineNodeData>) => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === nodeId ? { ...node, data: { ...node.data, ...fields } } : node
        )
      );
    },
    [nodeId, setNodes]
  );
}

export function stopFlowPointer(e: PointerEvent) {
  e.stopPropagation();
}
