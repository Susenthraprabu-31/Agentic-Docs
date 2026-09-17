"""Tests for AI page search planning (mocked)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.drivers.page_search_ai import PageSearchAI, execute_ai_page_search
from app.extraction.schemas import QueryType


@pytest.mark.asyncio
async def test_execute_ai_page_search_skips_without_api_key():
    driver = MagicMock()
    driver._emit_status = AsyncMock()
    driver.page = MagicMock()

    with patch("app.drivers.page_search_ai.get_settings") as mock_settings:
        mock_settings.return_value.openai_api_key = ""
        result = await execute_ai_page_search(driver, QueryType.ADDRESS, "123 Main St")
        assert result is False
        driver._emit_status.assert_called()


@pytest.mark.asyncio
async def test_page_search_ai_execute_plan_fills_and_clicks():
    driver = MagicMock()
    driver.polite_delay = AsyncMock()

    ai = PageSearchAI()
    plan = {
        "tab_selector": '[role="tab"]:has-text("ADDRESS")',
        "input_selector": 'input[placeholder="Enter Address"]',
        "submit_selector": 'button:has-text("Search")',
        "use_enter_key": False,
    }

    with patch("app.drivers.page_search_ai._click_selector", new=AsyncMock(return_value=True)), patch(
        "app.drivers.page_search_ai._fill_selector", new=AsyncMock(return_value=True)
    ):
        success = await ai.execute_plan(driver, plan, "532 N MARION AVE")
    assert success is True
