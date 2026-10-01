from unittest.mock import AsyncMock, patch

import pytest

from app.drivers.recorder.miami_dade_recorder import _search_property_address_form


@pytest.mark.asyncio
async def test_search_property_address_form_uses_normal_page_button():
    mock_driver = AsyncMock()
    mock_driver.page.url = "https://onlineservices.miamidadeclerk.gov/officialrecords/SearchResults?qs=search-token"
    mock_driver._emit_status = AsyncMock()

    with patch(
        "app.drivers.recorder.miami_dade_recorder._open_property_condo_search",
        new_callable=AsyncMock,
    ), patch(
        "app.drivers.recorder.miami_dade_recorder._fill_miami_dade_property_address",
        new_callable=AsyncMock,
        return_value=True,
    ), patch(
        "app.drivers.recorder.miami_dade_recorder._ensure_miami_dade_property_address_on_form",
        new_callable=AsyncMock,
        return_value=True,
    ), patch(
        "app.drivers.recorder.miami_dade_recorder._click_miami_dade_search_button",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_click:
        qs = await _search_property_address_form(mock_driver, "9956 SW 157 ST")

    assert qs == "search-token"
    mock_click.assert_awaited_once_with(mock_driver)
