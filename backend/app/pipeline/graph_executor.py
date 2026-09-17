"""Resolve canvas pipeline graph into execution order."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BROWSER_NODE_IDS = frozenset({"netr", "assessor", "recorder", "gis", "tax"})

# Tie-break parallel-ready nodes in a stable, user-friendly order.
NODE_EXECUTION_PRIORITY: dict[str, int] = {
    "input": 0,
    "netr": 10,
    "platform": 20,
    "assessor": 30,
    "recorder": 40,
    "gis": 50,
    "tax": 60,
    "ai_agent": 65,
    "normalizer": 70,
    "report": 80,
    "output": 90,
}


def _node_sort_key(canvas_id: str, node_map: dict[str, dict[str, Any]]) -> tuple[int, str]:
    node_id = str(node_map.get(canvas_id, {}).get("node_id") or "")
    return (NODE_EXECUTION_PRIORITY.get(node_id, 100), canvas_id)


@dataclass
class ParsedPipelineGraph:
    node_map: dict[str, dict[str, Any]]
    order: list[str]
    input_canvas_id: str
    step_node_ids: list[str]


class GraphValidationError(ValueError):
    pass


def resolve_pipeline_graph(graph: dict[str, Any] | None) -> ParsedPipelineGraph:
    if not graph:
        raise GraphValidationError("pipeline_graph is required")

    nodes: list[dict[str, Any]] = graph.get("nodes") or []
    edges: list[dict[str, Any]] = graph.get("edges") or []

    if not nodes:
        raise GraphValidationError("Add at least one node to the canvas")

    inputs = [n for n in nodes if n.get("node_id") == "input"]
    if not inputs:
        raise GraphValidationError("Connect an Input node to start the pipeline")
    if len(inputs) > 1:
        raise GraphValidationError("Only one Input node allowed on the canvas")

    input_id = inputs[0]["id"]
    node_map = {n["id"]: n for n in nodes if n.get("id")}
    node_ids = set(node_map.keys())

    adjacency: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for edge in edges:
        src, tgt = edge.get("source"), edge.get("target")
        if src in node_ids and tgt in node_ids:
            adjacency[src].append(tgt)

    reachable: set[str] = set()
    queue = [input_id]
    while queue:
        cur = queue.pop(0)
        if cur in reachable:
            continue
        reachable.add(cur)
        for nxt in adjacency.get(cur, []):
            if nxt not in reachable:
                queue.append(nxt)

    sub_adj: dict[str, list[str]] = {nid: [] for nid in reachable}
    in_degree: dict[str, int] = {nid: 0 for nid in reachable}
    for edge in edges:
        src, tgt = edge.get("source"), edge.get("target")
        if src in reachable and tgt in reachable:
            sub_adj[src].append(tgt)
            in_degree[tgt] += 1

    order: list[str] = []
    kahn = sorted(
        (nid for nid in reachable if in_degree[nid] == 0),
        key=lambda cid: _node_sort_key(cid, node_map),
    )
    visited: set[str] = set()

    while kahn:
        cur = kahn.pop(0)
        if cur in visited:
            continue
        visited.add(cur)
        order.append(cur)
        for nxt in sub_adj.get(cur, []):
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                kahn.append(nxt)
        kahn.sort(key=lambda cid: _node_sort_key(cid, node_map))

    if len(order) != len(reachable):
        raise GraphValidationError("Cycle detected in pipeline graph")

    step_node_ids = [node_map[cid]["node_id"] for cid in order]
    return ParsedPipelineGraph(
        node_map=node_map,
        order=order,
        input_canvas_id=input_id,
        step_node_ids=step_node_ids,
    )


def requires_browser(step_node_ids: list[str]) -> bool:
    return bool(BROWSER_NODE_IDS.intersection(step_node_ids))


def requires_report(step_node_ids: list[str]) -> bool:
    return "report" in step_node_ids
