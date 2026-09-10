from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.main import app
from app.extraction.schemas import QueryType, SearchRequest

client = TestClient(app)

def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_create_search(monkeypatch):
    monkeypatch.setattr("app.api.routes.search.enqueue_run", AsyncMock(return_value=None))
    res = client.post(
        "/search",
        json={"state": "AZ", "county": "gila", "query_type": "owner", "query_value": "Test Owner"},
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
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "run_id" in data


def test_search_request_accepts_address():
    req = SearchRequest(
        state="FL",
        county="columbia",
        query_type=QueryType.ADDRESS,
        query_value="542 N MARION AVE",
    )
    assert req.query_type == QueryType.ADDRESS
