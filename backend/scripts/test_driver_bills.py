import asyncio
from app.drivers.tax.florida_tax_driver import FloridaTaxDriver

async def test():
    driver = FloridaTaxDriver()
    await driver.start()
    try:
        page = driver.page
        url = 'https://county-taxes.net/fl-miamidade/property-tax'
        print('Navigating...')
        await page.goto(url, timeout=60000)
        
        inp = await page.wait_for_selector("input[placeholder*='Name, Address']", timeout=30000)
        
        # Dismiss notification
        try:
            cb = page.locator("button[aria-label*='close' i], button:has-text('✕')").first
            if await cb.is_visible():
                await cb.click()
        except Exception:
            pass

        folio = '30-4009-096-0060'
        print('Searching folio:', folio)
        await inp.fill(folio)
        await inp.press('Enter')
        
        print('Waiting for Account Summary...')
        await page.wait_for_selector("text=Real Estate Account", timeout=30000)
        print('Account Summary loaded!')
        await asyncio.sleep(4)
        
        # Scroll down so Account History table is in view
        await page.evaluate("window.scrollBy(0, 500)")
        await asyncio.sleep(1)
        
        # Let's inspect the Account History section
        data = await page.evaluate('''() => {
            const table = document.querySelector('table');
            if (!table) return { error: 'No table found' };
            const headers = Array.from(table.querySelectorAll('th')).map(th => th.innerText.trim());
            const rows = Array.from(table.querySelectorAll('tbody tr')).map((tr, idx) => {
                const cells = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim().replace(/\\s+/g, ' '));
                const buttons = Array.from(tr.querySelectorAll('button, a, svg, [role="button"], i')).map(el => ({
                    tag: el.tagName,
                    aria: el.getAttribute('aria-label') || '',
                    title: el.getAttribute('title') || '',
                    class: el.className || '',
                    text: el.innerText ? el.innerText.trim() : '',
                    html: el.outerHTML.slice(0, 300)
                }));
                return { idx, cells, buttons };
            });
            return { headers, rows };
        }''')
        
        import json
        print('TABLE DATA:')
        print(json.dumps(data, indent=2))
        
        await page.screenshot(path='screenshots/driver_account_history.png')
    finally:
        await driver.close()

if __name__ == '__main__':
    asyncio.run(test())
