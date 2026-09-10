import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright

from app.drivers.assessor.florida_assessor import _search_florida_pa
from app.drivers.assessor.gila_assessor_driver import GilaAssessorDriver
from app.extraction.schemas import QueryType


class Driver(GilaAssessorDriver):
    def __init__(self, page):
        self._page = page

    async def _emit_status(self, msg: str) -> None:
        print("STATUS:", msg)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        driver = Driver(page)

        # Run only through search submit (copy steps)
        from app.config.florida_portals import normalize_florida_pa_parcel
        from app.drivers.assessor.florida_assessor import (
            _click_florida_pa_run_search,
            _dismiss_florida_pa_disclaimer,
            _dismiss_florida_pa_disclaimer_in_frame,
            _fill_florida_pa_input,
            _wait_for_florida_pa_frame,
        )

        parcel = normalize_florida_pa_parcel("00-00-00-12004-001")
        await page.goto("https://columbia.floridapa.com/gis/", wait_until="networkidle", timeout=60_000)
        await _dismiss_florida_pa_disclaimer(driver)
        sf = await _wait_for_florida_pa_frame(driver, "recordSearch_1_Form", 25000)
        await _dismiss_florida_pa_disclaimer_in_frame(sf)
        await _fill_florida_pa_input(sf, "#PIN", parcel)
        await _click_florida_pa_run_search(sf)
        await page.wait_for_timeout(2000)

        rf = await _wait_for_florida_pa_frame(driver, "recordSearch_2_Results", 20000)
        assert rf
        print("RESULTS OK", rf.url)
        await rf.locator('td.pointer[onclick*="Detail"]').first.click(force=True)
        await page.wait_for_timeout(6000)

        for f in page.frames:
            print("FRAME", f.url)
        for f in page.frames:
            if "recordSearch" in f.url and "Results" not in f.url and "Form" not in f.url:
                data = await f.evaluate(
                    """() => {
                      const fields = {};
                      document.querySelectorAll('tr').forEach(tr => {
                        const cells = [...tr.querySelectorAll('th,td')];
                        if (cells.length >= 2) {
                          const k = cells[0].innerText.trim().toLowerCase();
                          const v = cells.slice(1).map(c => c.innerText.trim()).join(' | ');
                          if (k && v) fields[k] = v;
                        }
                      });
                      const tables = [...document.querySelectorAll('table')].map((t, idx) => ({
                        idx,
                        rows: [...t.querySelectorAll('tr')].map(r => [...r.querySelectorAll('th,td')].map(c => c.innerText.trim()))
                      }));
                      return {fields, tables};
                    }"""
                )
                print("DETAIL DATA", json.dumps(data, indent=2)[:20000])

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
