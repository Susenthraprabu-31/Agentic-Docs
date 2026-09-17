"""Tests for AI Playwright instruction writer (mocked)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.drivers.instruction_writer_ai import (
    InstructionWriterAI,
    _actions_to_instructions,
    _guess_nav_search_text,
    _plan_to_instruction_steps,
    _probe_page,
    _resolve_portal_url,
    _snapshot_has_search_inputs,
    generate_playwright_instructions,
)
from app.extraction.schemas import CountySources, QueryType


def test_snapshot_has_search_inputs():
    assert _snapshot_has_search_inputs({"elements": [{"kind": "input", "text": ""}]}) is True
    assert _snapshot_has_search_inputs({"elements": [{"kind": "button", "text": "Search"}]}) is False


def test_guess_nav_search_text():
    snapshot = {
        "elements": [
            {"tag": "a", "kind": "button", "text": "HOME"},
            {"tag": "a", "kind": "button", "text": "SEARCH RECORDS AND TAX DETAILS"},
        ]
    }
    assert _guess_nav_search_text(snapshot) == "SEARCH RECORDS AND TAX DETAILS"


def test_actions_to_instructions_dedupes_steps():
    text = _actions_to_instructions(
        [
            "Click SEARCH RECORDS AND TAX DETAILS",
            "fill parcel field",
            "click Search",
            "wait for results",
        ]
    )
    assert "Click SEARCH RECORDS" in text
    assert "fill parcel field" in text


def test_plan_to_instruction_steps():
    steps = _plan_to_instruction_steps(
        {
            "tab_selector": 'a:has-text("SEARCH RECORDS AND TAX DETAILS")',
            "input_selector": "#parcel",
            "submit_selector": 'button:has-text("Search")',
        },
        QueryType.PARCEL,
        {
            "elements": [
                {"selector": 'a:has-text("SEARCH RECORDS AND TAX DETAILS")', "text": "SEARCH RECORDS AND TAX DETAILS"}
            ]
        },
    )
    assert steps[0] == "Click SEARCH RECORDS AND TAX DETAILS"
    assert "fill parcel field" in steps


def test_resolve_portal_url():
    sources = CountySources(
        assessor_url="https://assessor.example.com",
        recorder_url="https://recorder.example.com",
        gis_url="https://gis.example.com",
        treasurer_url="https://tax.example.com",
    )
    assert _resolve_portal_url(sources, "assessor") == "https://assessor.example.com"
    assert _resolve_portal_url(sources, "recorder") == "https://recorder.example.com"


@pytest.mark.asyncio
async def test_instruction_writer_uses_successful_probe_actions():
    writer = InstructionWriterAI()
    writer.settings = MagicMock(openai_api_key="sk-test")
    actions = [
        "Click SEARCH RECORDS AND TAX DETAILS",
        "fill parcel field",
        "click Search",
        "wait for results",
    ]
    result = await writer.write_instructions(
        [{"url": "https://example.com/search", "elements": [{"kind": "input"}]}],
        node_id="assessor",
        query_type=QueryType.PARCEL,
        actions_taken=actions,
        search_succeeded=True,
    )
    assert "Click SEARCH RECORDS AND TAX DETAILS" in result["instructions"]
    assert result["confidence"] == "high"


@pytest.mark.asyncio
async def test_instruction_writer_raises_without_api_key():
    writer = InstructionWriterAI()
    writer.settings = MagicMock(openai_api_key="")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        await writer.write_instructions(
            [{"url": "https://example.com", "elements": []}],
            node_id="assessor",
            query_type=QueryType.PARCEL,
        )


@pytest.mark.asyncio
async def test_instruction_writer_returns_instructions():
    writer = InstructionWriterAI()
    writer.settings = MagicMock(openai_api_key="sk-test", openai_browser_model="gpt-4o-mini")
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"layout_type":"top_nav_landing","instructions":"Click Search Records and Tax Details, fill parcel field, click Search, wait for results","confidence":"high","reasoning":"Nav link opens search","nav_click_text":"Search Records and Tax Details"}'
            )
        )
    ]

    with patch.object(writer, "_get_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = mock_response
        result = await writer.write_instructions(
            [{"url": "https://example.com", "elements": []}],
            node_id="assessor",
            query_type=QueryType.PARCEL,
        )

    assert "Click Search Records" in result["instructions"]
    assert result["layout_type"] == "top_nav_landing"
    assert result["confidence"] == "high"


@pytest.mark.asyncio
async def test_probe_page_follows_nav_when_no_inputs():
    driver = MagicMock()
    driver.safe_goto = AsyncMock()
    driver.dismiss_netronline_modals = AsyncMock()
    driver.dismiss_schneider_terms = AsyncMock()
    driver.is_cloudflare_blocked = AsyncMock(return_value=False)
    driver.polite_delay = AsyncMock()

    landing_snapshot = {
        "url": "https://county.example.com",
        "elements": [{"tag": "a", "kind": "button", "text": "SEARCH RECORDS AND TAX DETAILS"}],
    }
    search_snapshot = {
        "url": "https://county.example.com/search",
        "elements": [{"kind": "input", "text": "", "placeholder": "Parcel"}],
    }

    page_ai = MagicMock()
    page_ai.extract_snapshot = AsyncMock(side_effect=[landing_snapshot, search_snapshot])

    with patch("app.drivers.instruction_writer_ai.PageSearchAI", return_value=page_ai), patch(
        "app.drivers.instruction_writer_ai._click_by_visible_text", new=AsyncMock(return_value=True)
    ):
        snapshots, cloudflare, terms, actions = await _probe_page(driver, "https://county.example.com")

    assert len(snapshots) == 2
    assert _snapshot_has_search_inputs(snapshots[-1])
    assert cloudflare is False
    assert any("Click SEARCH RECORDS" in step for step in actions)


@pytest.mark.asyncio
async def test_generate_playwright_instructions_without_api_key():
    with patch("app.drivers.instruction_writer_ai.InstructionWriterAI") as mock_writer_cls:
        mock_writer = MagicMock()
        mock_writer.is_configured = False
        mock_writer_cls.return_value = mock_writer

        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            await generate_playwright_instructions(
                node_id="assessor",
                state="HI",
                county="kauai",
                query_type=QueryType.PARCEL,
                query_value="00-00-00-12004-001",
            )
