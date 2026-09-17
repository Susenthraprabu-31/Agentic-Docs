import asyncio
from playwright.async_api import async_playwright
from app.drivers.base.base_driver import USER_AGENT

async def main():
    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=True,
        channel='chrome',
        args=['--disable-blink-features=AutomationControlled', '--disable-dev-shm-usage']
    )
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={'width': 1366, 'height': 900},
        locale='en-US'
    )
    page = await context.new_page()
    url = 'https://county-taxes.net/fl-miamidade/property-tax'
    await page.goto(url, timeout=60000)
    
    inp = await page.wait_for_selector("input[placeholder*='Name, Address']", timeout=30000)
    try:
        cb = page.locator("button[aria-label*='close' i], button:has-text('✕')").first
        if await cb.is_visible():
            await cb.click()
    except Exception:
        pass

    folio = '30-4009-096-0060'
    await inp.fill(folio)
    await inp.press('Enter')
    await asyncio.sleep(8)
    
    print('Frames count:', len(page.frames))
    for i, f in enumerate(page.frames):
        print(f'Frame {i}: name={f.name}, url={f.url}')
        try:
            txt = await f.evaluate("() => document.body?.innerText || ''")
            if 'Account History' in txt:
                print(f'*** Found Account History in Frame {i}!')
                print('Frame text snippet:', txt[:1000])
        except Exception as e:
            print(f'Frame {i} err: {e}')

    await browser.close()
    await p.stop()

if __name__ == '__main__':
    asyncio.run(main())
