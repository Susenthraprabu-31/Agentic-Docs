"""Tests for safe form fill helpers."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.drivers.form_fill import fill_first_visible_input, is_fillable_input


@pytest.mark.asyncio
async def test_is_fillable_input_rejects_debug_field():
    locator = MagicMock()
    locator.count = AsyncMock(return_value=1)
    locator.is_visible = AsyncMock(return_value=True)
    locator.is_editable = AsyncMock(return_value=True)
    locator.evaluate = AsyncMock(
        return_value={
            "type": "text",
            "ariaHidden": "true",
            "tabIndex": "-1",
            "id": "txtDebug",
            "name": "txtDebug",
            "className": "cssDebug cssNoPrint",
            "readOnly": False,
            "disabled": False,
        }
    )

    assert await is_fillable_input(locator) is False


@pytest.mark.asyncio
async def test_fill_first_visible_input_skips_hidden_and_fills_next():
    hidden = MagicMock()
    hidden.count = AsyncMock(return_value=1)
    hidden.is_visible = AsyncMock(return_value=True)
    hidden.is_editable = AsyncMock(return_value=False)

    visible = MagicMock()
    visible.count = AsyncMock(return_value=1)
    visible.is_visible = AsyncMock(return_value=True)
    visible.is_editable = AsyncMock(return_value=True)
    visible.evaluate = AsyncMock(
        return_value={
            "type": "text",
            "ariaHidden": None,
            "tabIndex": "0",
            "id": "parcelSearch",
            "name": "parcel",
            "className": "",
            "readOnly": False,
            "disabled": False,
        }
    )
    visible.click = AsyncMock()
    visible.fill = AsyncMock()
    visible.press_sequentially = AsyncMock()

    page = MagicMock()
    locator = MagicMock()
    locator.count = AsyncMock(return_value=2)
    locator.nth = MagicMock(side_effect=lambda i: hidden if i == 0 else visible)
    page.locator = MagicMock(return_value=locator)

    driver = MagicMock()
    driver.page = page

    filled = await fill_first_visible_input(driver, ['input[type="text"]'], "01874 201-251")
    assert filled is True
    visible.click.assert_awaited_once()
    visible.fill.assert_awaited()
