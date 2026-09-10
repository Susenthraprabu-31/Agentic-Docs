"""Quick integration test for Columbia County floridapa search."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.drivers.assessor.florida_assessor import _search_florida_pa
from app.drivers.assessor.gila_assessor_driver import GilaAssessorDriver
from app.extraction.schemas import QueryType


class _StubDriver(GilaAssessorDriver):
    def __init__(self, page) -> None:
        self._page = page
        self._status = []

    async def _emit_status(self, msg: str) -> None:
        self._status.append(msg)
        print("STATUS:", msg)


async def main() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        driver = _StubDriver(page)
        records = await _search_florida_pa(
            driver,
            "https://columbia.floridapa.com/gis/",
            QueryType.PARCEL,
            "00-00-00-12004-001",
            county="columbia",
        )
        print("RECORDS", records)
        print("COUNT", len(records))
        await browser.close()
        if not records:
            raise SystemExit("no records returned")
        assert records, "expected at least one record"
        assert records[0].apn
        assert records[0].owner_name
        assert records[0].assessed_value
        assert records[0].raw_json.get("sales_history")
        assert records[0].raw_json.get("chain_of_title")


if __name__ == "__main__":
    asyncio.run(main())
