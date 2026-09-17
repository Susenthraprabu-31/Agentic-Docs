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
    
    # Wait for the iframe
    iframe_element = await page.wait_for_selector("iframe[src*='iframe-taxsys'], iframe[name*='iframe-']", timeout=30000)
    frame = await iframe_element.content_frame()
    
    # Wait for rows
    await asyncio.sleep(4)
    
    # Find the first bill row's link/info button
    info_link = frame.locator("a[title*='Parcel details'], a[href*='/bills/']").first
    print('Found info link, clicking...')
    await info_link.click()
    
    # Now wait for the bill page to load
    print('Waiting for bill page to load...')
    for sec in range(15):
        await asyncio.sleep(1)
        # Check current frames
        bill_frame = None
        for f in page.frames:
            if 'bills' in f.url:
                bill_frame = f
                break
        if bill_frame:
            txt = await bill_frame.evaluate("() => document.body?.innerText || ''")
            if 'ad valorem' in txt.lower() or 'millage' in txt.lower() or 'taxing authority' in txt.lower() or 'bill details' in txt.lower():
                print(f'Bill loaded inside bill_frame at sec {sec+1}!')
                print('Bill text snippet:\n', txt[:1200])
                break
            else:
                print(f'Sec {sec+1}: bill_frame url={bill_frame.url} (still loading...)')
        else:
            print(f'Sec {sec+1}: waiting for bill_frame...')

    await page.screenshot(path='screenshots/bill_detail_loaded.png', full_page=True)
    await browser.close()
    await p.stop()

if __name__ == '__main__':
    asyncio.run(main())
