from app.pipeline.workflow_templates import WORKFLOW_TEMPLATES, resolve_workflow_graph

def test_workflow_templates_exist():
    assert "recorder_deed" in WORKFLOW_TEMPLATES
    assert "assessor_tax" in WORKFLOW_TEMPLATES
    assert "full_title" in WORKFLOW_TEMPLATES

def test_resolve_recorder_deed_workflow():
    order_data = {
        "book": "30189",
        "page": "4575",
        "order_number": "ORD-TEST-001"
    }
    graph = resolve_workflow_graph("recorder_deed", order_data)
    assert "nodes" in graph
    assert "edges" in graph
    
    recorder_node = next((n for n in graph["nodes"] if n["data"].get("componentId") == "recorder_search"), None)
    assert recorder_node is not None
    assert recorder_node["data"]["params"]["book"] == "30189"
    assert recorder_node["data"]["params"]["page"] == "4575"
