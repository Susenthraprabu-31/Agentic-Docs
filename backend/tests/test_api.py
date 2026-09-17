from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.main import app
from app.extraction.schemas import QueryType, SearchRequest

client = TestClient(app)

def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def _input_only_graph():
    return {
        "nodes": [{"id": "input", "node_id": "input", "type": "pipelineNode", "enabled": True, "data": {}}],
        "edges": [],
    }


def test_create_search(monkeypatch):
    monkeypatch.setattr("app.api.routes.search.enqueue_run", AsyncMock(return_value=None))
    res = client.post(
        "/search",
        json={
            "state": "AZ",
            "county": "gila",
            "query_type": "owner",
            "query_value": "Test Owner",
            "pipeline_graph": _input_only_graph(),
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "run_id" in data


def test_create_address_search(monkeypatch):
    monkeypatch.setattr("app.api.routes.search.enqueue_run", AsyncMock(return_value=None))
    res = client.post(
        "/search",
        json={
            "state": "FL",
            "county": "columbia",
            "query_type": "address",
            "query_value": "542 N MARION AVE",
            "pipeline_graph": _input_only_graph(),
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "run_id" in data


def test_create_book_page_search(monkeypatch):
    monkeypatch.setattr("app.api.routes.search.enqueue_run", AsyncMock(return_value=None))
    res = client.post(
        "/search",
        json={
            "state": "FL",
            "county": "miami-dade",
            "query_type": "book_page",
            "query_value": "",
            "book_number": "1494",
            "page_number": "2483",
            "pipeline_graph": _input_only_graph(),
        },
    )
    assert res.status_code == 200
    assert "run_id" in res.json()


def test_create_book_page_search_requires_values(monkeypatch):
    monkeypatch.setattr("app.api.routes.search.enqueue_run", AsyncMock(return_value=None))
    res = client.post(
        "/search",
        json={
            "state": "FL",
            "county": "miami-dade",
            "query_type": "book_page",
            "query_value": "",
            "pipeline_graph": _input_only_graph(),
        },
    )
    assert res.status_code == 400


def test_create_search_requires_pipeline_graph(monkeypatch):
    monkeypatch.setattr("app.api.routes.search.enqueue_run", AsyncMock(return_value=None))
    res = client.post(
        "/search",
        json={"state": "AZ", "county": "gila", "query_type": "owner", "query_value": "Test Owner"},
    )
    assert res.status_code == 400


def test_search_request_accepts_address():
    from app.extraction.schemas import PipelineGraph, PipelineGraphNode

    req = SearchRequest(
        state="FL",
        county="columbia",
        query_type=QueryType.ADDRESS,
        query_value="542 N MARION AVE",
        pipeline_graph=PipelineGraph(
            nodes=[PipelineGraphNode(id="input", node_id="input", type="pipelineNode", enabled=True, data={})],
            edges=[],
        ),
    )
    assert req.query_type == QueryType.ADDRESS
