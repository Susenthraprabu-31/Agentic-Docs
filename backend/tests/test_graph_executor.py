import pytest

from app.pipeline.graph_executor import (
    GraphValidationError,
    requires_browser,
    requires_report,
    resolve_pipeline_graph,
)


def _graph(nodes, edges):
    return {"nodes": nodes, "edges": edges}


def test_input_only_graph():
    parsed = resolve_pipeline_graph(_graph(
        [{"id": "input", "node_id": "input", "enabled": True, "data": {}}],
        [],
    ))
    assert parsed.step_node_ids == ["input"]
    assert parsed.order == ["input"]
    assert not requires_browser(parsed.step_node_ids)
    assert not requires_report(parsed.step_node_ids)


def test_linear_chain():
    parsed = resolve_pipeline_graph(_graph(
        [
            {"id": "input", "node_id": "input", "enabled": True, "data": {}},
            {"id": "netr", "node_id": "netr", "enabled": True, "data": {}},
            {"id": "assessor", "node_id": "assessor", "enabled": True, "data": {}},
        ],
        [
            {"source": "input", "target": "netr"},
            {"source": "netr", "target": "assessor"},
        ],
    ))
    assert parsed.step_node_ids == ["input", "netr", "assessor"]
    assert requires_browser(parsed.step_node_ids)


def test_unreachable_nodes_ignored():
    parsed = resolve_pipeline_graph(_graph(
        [
            {"id": "input", "node_id": "input", "enabled": True, "data": {}},
            {"id": "netr", "node_id": "netr", "enabled": True, "data": {}},
            {"id": "tax", "node_id": "tax", "enabled": True, "data": {}},
        ],
        [{"source": "input", "target": "netr"}],
    ))
    assert parsed.step_node_ids == ["input", "netr"]
    assert "tax" not in parsed.step_node_ids


def test_cycle_detection():
    with pytest.raises(GraphValidationError, match="Cycle"):
        resolve_pipeline_graph(_graph(
            [
                {"id": "input", "node_id": "input", "enabled": True, "data": {}},
                {"id": "a", "node_id": "netr", "enabled": True, "data": {}},
                {"id": "b", "node_id": "assessor", "enabled": True, "data": {}},
            ],
            [
                {"source": "input", "target": "a"},
                {"source": "a", "target": "b"},
                {"source": "b", "target": "a"},
            ],
        ))


def test_requires_report():
    assert requires_report(["input", "report", "output"])
