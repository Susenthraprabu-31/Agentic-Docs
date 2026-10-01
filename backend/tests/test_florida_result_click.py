from app.drivers.assessor.florida_assessor import (
    _is_florida_results_page,
    _normalize_parcel_token,
    _parcel_tokens_match,
)


def test_normalize_parcel_token():
    assert _normalize_parcel_token("28-2S-22-0216-0000-1210") == "282S22021600001210"
    assert _normalize_parcel_token("282S22021600001210") == "282S22021600001210"


def test_parcel_tokens_match_baker_formats():
    query = "28-2S-22-0216-0000-1210"
    link = "282S22021600001210"
    assert _parcel_tokens_match(query, link) is True


import pytest


@pytest.mark.asyncio
async def test_is_florida_results_page_detects_baker_searchresults():
    from unittest.mock import AsyncMock, MagicMock

    driver = MagicMock()
    driver.page = MagicMock()
    driver.page.url = "https://www.bakerpa.com/searchresults.php?parcel=28-2S-22-0216-0000-1210"
    driver.page.title = AsyncMock(return_value="Search Results")
    driver.page.inner_text = AsyncMock(
        return_value="Search Results Click Parcel # to view more details Parcel Number Owner's Name"
    )
    driver.page.locator = MagicMock(return_value=MagicMock(count=AsyncMock(return_value=0)))

    assert await _is_florida_results_page(driver) is True
