"""One-off inspector for Collier County frames and search form."""
import asyncio
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

CDP_URL = "http://127.0.0.1:9222"


async def main() -> None:
    use_cdp = "--cdp" in sys.argv
    async with async_playwright() as p:
        if use_cdp:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()

        await page.goto("https://www.collierappraiser.com/", wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(2_000)

        main_nav = next((f for f in page.frames if f.name == "main"), None)
        if main_nav:
            await main_nav.locator('a[href*="search_rp.html"]').first.click()
        await page.wait_for_timeout(3_000)

        rbottom = page.frame(name="rbottom")
        if not rbottom:
            print("rbottom frame missing")
            return

        print("rbottom url", rbottom.url)
        html = await rbottom.content()
        out = Path("collier_rbottom.html")
        out.write_text(html, encoding="utf-8")
        print("wrote", out, "len", len(html))
        for line in html.splitlines():
            if re.search(r"parcel|address|owner|input|button|tab|search|folio", line, re.I):
                print(line.strip()[:350])

        if not use_cdp:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
