import asyncio
import re
from playwright.async_api import async_playwright


async def main() -> None:
    parcel = "00-00-00-12004-001"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://columbia.floridapa.com/gis/", wait_until="networkidle", timeout=90_000)

        await page.locator("#button1").click(force=True)
        await page.wait_for_timeout(2000)

        search_frame = None
        for f in page.frames:
            if "recordSearch_1_Form" in f.url:
                search_frame = f
                break
        assert search_frame
        await search_frame.locator("#PIN").fill(parcel)
        await search_frame.locator("#submit_RecordSearch").click(force=True)
        await page.wait_for_timeout(4000)

        results_frame = None
        for f in page.frames:
            if "recordSearch_2_Results" in f.url:
                results_frame = f
                break
        assert results_frame

        data = await results_frame.evaluate(
            """() => {
              const row = document.querySelector('tr.hv, tr.pointer, table tr td.pointer')?.closest('tr');
              if (!row) return null;
              const cells = [...row.querySelectorAll('td')].map(td => td.innerText.trim());
              return {cells, html: row.innerHTML.slice(0,500)};
            }"""
        )
        print("ROW", data)

        detail = results_frame.locator('td.pointer, td[onclick*="Detail"]').first
        if await detail.count():
            await detail.click(force=True)
            await page.wait_for_timeout(4000)
            print("frames after detail", [f.url for f in page.frames])
            for f in page.frames:
                if "recordSearch_3" in f.url or "Detail" in f.url or "parcel" in f.url.lower():
                    print("DETAIL FRAME", f.url)
                    txt = await f.inner_text("body")
                    print(txt[:1500])

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
