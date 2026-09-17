import asyncio
from playwright.async_api import async_playwright
from app.drivers.base.base_driver import USER_AGENT

async def inspect():
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
    
    # Close modal if open
    try:
        cb = page.locator("button[aria-label*='close' i], button:has-text('✕')").first
        if await cb.is_visible():
            await cb.click()
    except Exception:
        pass

    folio = '30-4009-096-0060'
    await inp.fill(folio)
    await inp.press('Enter')
    
    await asyncio.sleep(5)
    
    # Scroll down to Account History
    await page.evaluate("window.scrollBy(0, 800)")
    await asyncio.sleep(2)
    
    await page.screenshot(path='screenshots/account_history_scrolled.png', full_page=True)
    
    # Dump all text and buttons under Account History
    content = await page.content()
    body = await page.evaluate("() => document.body.innerText")
    print('=== BODY BELOW ===')
    start = False
    for line in body.split('\n'):
        if 'Account History' in line:
            start = True
        if start and line.strip():
            print(line.strip())

    # Find all buttons, links, icons under Account History
    items = await page.locator("button, a, [role='button'], i, svg").all()
    print(f'Total interactive elements: {len(items)}')
    for it in items:
        try:
            aria = await it.get_attribute("aria-label") or ""
            text = (await it.inner_text()).strip()
            title = await it.get_attribute("title") or ""
            cls = await it.get_attribute("class") or ""
            href = await it.get_attribute("href") or ""
            tag = await it.evaluate("el => el.tagName")
            if any(w in (aria + text + title + cls + href).lower() for w in ['bill', 'detail', 'info', 'summary', 'history', 'expand', 'view', '2024', '2023', '2022', '2025']):
                print(f'Match: <{tag}> text={text!r} aria={aria!r} title={title!r} class={cls!r} href={href!r}')
        except Exception:
            pass

    await browser.close()
    await p.stop()

if __name__ == '__main__':
    asyncio.run(inspect())
