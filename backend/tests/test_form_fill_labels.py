"""Tests for accessible-name form helpers."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.drivers.form_fill import (
    click_enabled_button,
    click_property_search_button,
    fill_input_by_accessible_name,
)


@pytest.mark.asyncio
async def test_fill_input_by_accessible_name():
    page = MagicMock()
    locator = MagicMock()
    locator.count = AsyncMock(return_value=1)
    locator.is_visible = AsyncMock(return_value=True)
    locator.is_editable = AsyncMock(return_value=True)
    locator.evaluate = AsyncMock(
        return_value={
            "type": "text",
            "ariaHidden": None,
            "tabIndex": "0",
            "id": "parcel",
            "name": "parcel",
            "className": "",
            "readOnly": False,
            "disabled": False,
        }
    )
    locator.click = AsyncMock()
    locator.fill = AsyncMock()
    locator.press_sequentially = AsyncMock()
    page.get_by_role = MagicMock(return_value=MagicMock(first=locator))

    driver = MagicMock()
    driver.page = page

    filled = await fill_input_by_accessible_name(driver, "Parcel ID:", "22-35-31-AV-*-7")
    assert filled is True
    locator.fill.assert_awaited_with("22-35-31-AV-*-7")


@pytest.mark.asyncio
async def test_click_enabled_button_skips_disabled():
    enabled = MagicMock()
    enabled.is_visible = AsyncMock(return_value=True)
    enabled.is_enabled = AsyncMock(return_value=True)
    enabled.inner_text = AsyncMock(return_value="Search")
    enabled.click = AsyncMock()

    disabled = MagicMock()
    disabled.is_visible = AsyncMock(return_value=True)
    disabled.is_enabled = AsyncMock(return_value=False)

    buttons = MagicMock()
    buttons.count = AsyncMock(return_value=2)
    buttons.nth = MagicMock(side_effect=lambda i: disabled if i == 0 else enabled)

    page = MagicMock()
    page.get_by_role = MagicMock(return_value=buttons)

    driver = MagicMock()
    driver.page = page

    clicked = await click_enabled_button(driver, "Search", exact=True)
    assert clicked is True
    enabled.click.assert_awaited_once()


@pytest.mark.asyncio
async def test_click_property_search_button_uses_exact_search_only():
    research = MagicMock()
    research.is_visible = AsyncMock(return_value=True)
    research.is_enabled = AsyncMock(return_value=True)
    research.inner_text = AsyncMock(return_value="RESEARCH")
    research.click = AsyncMock()

    search = MagicMock()
    search.is_visible = AsyncMock(return_value=True)
    search.is_enabled = AsyncMock(return_value=True)
    search.inner_text = AsyncMock(return_value="Search")
    search.click = AsyncMock()

    buttons = MagicMock()
    buttons.count = AsyncMock(return_value=1)
    buttons.nth = MagicMock(return_value=search)

    page = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    page.get_by_role = MagicMock(return_value=buttons)
    page.locator = MagicMock()

    driver = MagicMock()
    driver.page = page

    clicked = await click_property_search_button(driver)
    assert clicked is True
    search.click.assert_awaited_once()
    research.click.assert_not_called()
