import pytest

from app.drivers.netronline.netronline_driver import NetronlineDriver


@pytest.mark.asyncio
@pytest.mark.integration
async def test_resolve_gila_county_urls():
    async with NetronlineDriver() as driver:
        sources = await driver.resolve_county_sources("AZ", "gila")

    assert sources.assessor_url, "Assessor URL should be resolved"
    assert sources.recorder_url, "Recorder URL should be resolved"
    assert sources.assessor_url.startswith("http"), "Assessor URL must be HTTPS"
    assert sources.recorder_url.startswith("http"), "Recorder URL must be HTTPS"
    assert "netronline.com" not in (sources.assessor_url or ""), "Assessor should be external portal"
    assert "netronline.com" not in (sources.recorder_url or ""), "Recorder should be external portal"
