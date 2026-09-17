"""Pre-configured standard pipeline workflow templates and custom canvas resolvers."""
from __future__ import annotations

from typing import Any

# Standard workflow templates
WORKFLOW_TEMPLATES: dict[str, dict[str, Any]] = {
    "recorder_deed": {
        "id": "recorder_deed",
        "name": "Recorder Deed Retrieval",
        "description": "Searches county recorder records for official deeds, downloads PDF and generates document report.",
        "icon": "document-text",
        "nodes": [
            {"id": "input", "node_id": "input", "data": {"label": "Input"}, "enabled": True},
            {"id": "netr", "node_id": "netr", "data": {"label": "NETR Resolver"}, "enabled": True},
            {"id": "recorder", "node_id": "recorder", "data": {"label": "Recorder"}, "enabled": True},
            {"id": "report", "node_id": "report", "data": {"label": "Report"}, "enabled": True},
        ],
        "edges": [
            {"source": "input", "target": "netr"},
            {"source": "netr", "target": "recorder"},
            {"source": "recorder", "target": "report"},
        ],
    },
    "assessor_tax": {
        "id": "assessor_tax",
        "name": "Property & Tax Assessment",
        "description": "Retrieves property appraiser valuation, ownership, legal description and tax bill records.",
        "icon": "calculator",
        "nodes": [
            {"id": "input", "node_id": "input", "data": {"label": "Input"}, "enabled": True},
            {"id": "netr", "node_id": "netr", "data": {"label": "NETR Resolver"}, "enabled": True},
            {"id": "assessor", "node_id": "assessor", "data": {"label": "Assessor"}, "enabled": True},
            {"id": "tax", "node_id": "tax", "data": {"label": "Tax"}, "enabled": True},
            {"id": "report", "node_id": "report", "data": {"label": "Report"}, "enabled": True},
        ],
        "edges": [
            {"source": "input", "target": "netr"},
            {"source": "netr", "target": "assessor"},
            {"source": "assessor", "target": "tax"},
            {"source": "tax", "target": "report"},
        ],
    },
    "full_title": {
        "id": "full_title",
        "name": "Full Comprehensive Title",
        "description": "Complete search across NETR, Assessor, Recorder, Tax Collector, and GIS mapping.",
        "icon": "shield-check",
        "nodes": [
            {"id": "input", "node_id": "input", "data": {"label": "Input"}, "enabled": True},
            {"id": "netr", "node_id": "netr", "data": {"label": "NETR Resolver"}, "enabled": True},
            {"id": "assessor", "node_id": "assessor", "data": {"label": "Assessor"}, "enabled": True},
            {"id": "recorder", "node_id": "recorder", "data": {"label": "Recorder"}, "enabled": True},
            {"id": "tax", "node_id": "tax", "data": {"label": "Tax"}, "enabled": True},
            {"id": "gis", "node_id": "gis", "data": {"label": "GIS"}, "enabled": True},
            {"id": "report", "node_id": "report", "data": {"label": "Report"}, "enabled": True},
        ],
        "edges": [
            {"source": "input", "target": "netr"},
            {"source": "netr", "target": "assessor"},
            {"source": "assessor", "target": "recorder"},
            {"source": "recorder", "target": "tax"},
            {"source": "tax", "target": "gis"},
            {"source": "gis", "target": "report"},
        ],
    },
}


def list_workflow_templates() -> list[dict[str, Any]]:
    """Return available template definitions."""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "description": t["description"],
            "icon": t.get("icon", "template"),
            "steps": [n["node_id"] for n in t["nodes"]],
        }
        for t in WORKFLOW_TEMPLATES.values()
    ]


def get_workflow_graph(template_id: str, custom_graph: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Resolve a pipeline graph by template_id or fallback to custom_graph or recorder_deed.
    """
    if template_id == "custom" and custom_graph and custom_graph.get("nodes"):
        return custom_graph

    tpl = WORKFLOW_TEMPLATES.get(template_id)
    if tpl:
        return {
            "nodes": [dict(n) for n in tpl["nodes"]],
            "edges": [dict(e) for e in tpl["edges"]],
        }

    if custom_graph and custom_graph.get("nodes"):
        return custom_graph

    # Default to recorder deed workflow
    default_tpl = WORKFLOW_TEMPLATES["recorder_deed"]
    return {
        "nodes": [dict(n) for n in default_tpl["nodes"]],
        "edges": [dict(e) for e in default_tpl["edges"]],
    }
