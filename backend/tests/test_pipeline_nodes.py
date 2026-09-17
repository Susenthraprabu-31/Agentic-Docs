"""Unit tests for pipeline nodes (no Playwright / network)."""
from __future__ import annotations

import pytest

from app.pipeline.base_node import PipelineContext
from app.pipeline.nodes.input_node import InputNode
from app.pipeline.nodes.normalizer_node import (
    NormalizerNode,
    deduplicate_documents,
    deduplicate_records,
)
from app.pipeline.nodes.output_node import OutputNode
from app.pipeline.nodes.platform_detector_node import (
    PlatformDetectorNode,
    _build_tax_url,
    detect_platform,
    resolve_search_url,
)
from app.config.platform_rules import get_assessor_platform_rules


def _ctx(**kwargs) -> PipelineContext:
    defaults = {
        "run_id": "test-run-1",
        "state": "FL",
        "county": "columbia",
        "query_type": "parcel",
        "query_value": "00-00-00-12003-001",
    }
    defaults.update(kwargs)
    return PipelineContext(**defaults)


# ── InputNode ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_input_node_normalizes_fields(monkeypatch):
    updates: list[dict] = []

    class FakeRepo:
        def update_run(self, run_id, **kwargs):
            updates.append({"run_id": run_id, **kwargs})

    node = InputNode(runs_repo=FakeRepo())
    ctx = _ctx(state=" fl ", county=" Columbia ", query_type="PARCEL", query_value=" 123 ")
    result = await node.run(ctx)

    assert result.state == "FL"
    assert result.county == "columbia"
    assert result.query_type == "parcel"
    assert result.query_value == "123"
    assert any(u.get("status") == "running" for u in updates)


@pytest.mark.asyncio
async def test_input_node_rejects_empty_query():
    node = InputNode(runs_repo=type("R", (), {"update_run": lambda *a, **k: None})())
    ctx = _ctx(query_value="   ")
    with pytest.raises(ValueError, match="query_value"):
        await node.run(ctx)


# ── PlatformDetectorNode ─────────────────────────────────────────────────────


def test_detect_platform_florida_pa():
    rules = get_assessor_platform_rules()
    assert detect_platform("https://columbia.floridapa.com/gis/", rules) == "florida_pa"


def test_detect_platform_schneider():
    rules = get_assessor_platform_rules()
    url = "https://qpublic.schneidercorp.com/Application.aspx?App=BayCountyFL"
    assert detect_platform(url, rules) == "schneider"


def test_resolve_search_url_floridapa():
    resolved = resolve_search_url("https://columbia.floridapa.com/", {})
    assert resolved == "https://columbia.floridapa.com/gis/"


def test_build_tax_url_no_state_check():
    url = _build_tax_url("columbia", "florida_pa")
    assert url == "https://columbia.floridatax.us"


def test_build_tax_url_skips_non_florida_pa():
    assert _build_tax_url("gila", "schneider") is None


@pytest.mark.asyncio
async def test_platform_detector_node_sets_platforms():
    node = PlatformDetectorNode()
    ctx = _ctx(
        assessor_url="https://columbia.floridapa.com/",
        recorder_url="https://www.myfloridacounty.com/orisearch/12",
    )
    result = await node.run(ctx)
    assert result.assessor_platform == "florida_pa"
    assert result.recorder_platform == "myflorida"
    assert result.tax_url == "https://columbia.floridatax.us"
    assert "gis/" in (result.assessor_url or "")


# ── NormalizerNode ───────────────────────────────────────────────────────────


def test_deduplicate_records_prefers_assessor():
    records = [
        {"source": "tax_record", "apn": "123", "owner_name": "Tax Owner"},
        {"source": "assessor", "apn": "123", "owner_name": "Assessor Owner"},
    ]
    result = deduplicate_records(records)
    assert len(result) == 1
    assert result[0]["owner_name"] == "Assessor Owner"


def test_deduplicate_documents_by_instrument():
    docs = [
        {"instrument_number": "ABC123", "grantor": "A"},
        {"instrument_number": "ABC123", "grantor": "B"},
        {"book_page": "1/2", "grantor": "C"},
    ]
    result = deduplicate_documents(docs)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_normalizer_node_deduplicates():
    node = NormalizerNode()
    ctx = _ctx()
    ctx.records = [
        {"source": "assessor", "apn": "X1"},
        {"source": "tax_record", "apn": "X1"},
        {"source": "assessor", "apn": "X2"},
    ]
    ctx.documents = [
        {"instrument_number": "I1"},
        {"instrument_number": "I1"},
    ]
    result = await node.run(ctx)
    assert len(result.records) == 2
    assert len(result.documents) == 1


# ── OutputNode ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_output_node_sets_summary(monkeypatch):
    updates: list[dict] = []

    class FakeRepo:
        def update_run(self, run_id, **kwargs):
            updates.append(kwargs)

    node = OutputNode(runs_repo=FakeRepo())
    ctx = _ctx()
    ctx.records = [{"apn": "1"}]
    ctx.documents = [{"instrument_number": "D1"}]
    ctx.assessor_platform = "florida_pa"
    result = await node.run(ctx)

    assert result.summary is not None
    assert result.summary["total_records"] == 1
    assert result.summary["total_documents"] == 1
    assert result.summary["assessor_platform"] == "florida_pa"
    assert any(u.get("status") == "completed" for u in updates)
