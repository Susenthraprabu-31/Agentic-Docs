import logging
from typing import Optional
from urllib.parse import urljoin

from playwright.async_api import Page

from app.config.florida_portals import resolve_florida_tax_url
from app.drivers.assessor.florida_assessor import _wait_for_florida_pa_frame
from app.drivers.base.base_driver import BaseDriver
from app.extraction.florida_tax_extractors import FLORIDA_TAX_PAGE_JS, tax_record_from_florida_data
from app.extraction.schemas import TaxRecord

logger = logging.getLogger(__name__)

TAX_TABS = ("Taxes", "Assessments", "Legal Description", "Payment History")


def _is_florida_tax_url(url: str) -> bool:
    return "floridatax.us" in url.lower()


class FloridaTaxDriver(BaseDriver):
    async def fetch_tax_record(
        self,
        county: str,
        apn: str,
        owner_name: Optional[str] = None,
    ) -> Optional[TaxRecord]:
        original_page = self.page
        tax_page: Page | None = None
        direct_url = resolve_florida_tax_url(county, apn)

        try:
            await self._emit_status("Opening county tax record from Property Appraiser...")
            await self._open_tax_record_from_assessor_detail(direct_url)
            tax_page = self.page

            if not _is_florida_tax_url(tax_page.url):
                if not await self._open_tax_page(direct_url):
                    await self._emit_status("Could not reach county tax collector site.")
                    return None

            scraped = await self._scrape_all_tax_tabs(tax_page)
            record = tax_record_from_florida_data(scraped, apn=apn, owner_name=owner_name)
            if record.raw_json.get("tabs") or record.tax_account:
                await self._emit_status("Saved tax bill details from county tax collector.")
                return record
            return None
        finally:
            if tax_page and tax_page != original_page:
                try:
                    await tax_page.close()
                except Exception:
                    pass
                self._page = original_page

    async def _open_tax_page(self, url: str) -> bool:
        await self._emit_status(f"Opening tax bill detail at {url}...")
        try:
            await self.safe_goto(url, timeout=60_000)
            await self.polite_delay(2.0)
        except Exception as exc:
            logger.warning("Failed to open tax page %s: %s", url, exc)
            return False
        return _is_florida_tax_url(self.page.url)

    async def _wait_for_tax_page(self, page: Page, timeout_ms: int = 30_000) -> bool:
        try:
            await page.wait_for_url("**floridatax.us/**", timeout=timeout_ms)
        except Exception:
            pass
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        await self.polite_delay(2.0)
        return _is_florida_tax_url(page.url)

    async def _resolve_tax_link_url(self, detail_frame, fallback_url: str) -> Optional[str]:
        selectors = [
            'a[href*="floridatax"]',
            'a:has-text("Retrieve Tax Record")',
        ]
        for sel in selectors:
            try:
                link = detail_frame.locator(sel).first
                if await link.count() == 0:
                    continue
                href = await link.get_attribute("href")
                if not href:
                    continue
                tax_url = href if href.startswith("http") else urljoin(fallback_url, href)
                if _is_florida_tax_url(tax_url):
                    return tax_url
            except Exception as exc:
                logger.debug("Could not resolve tax link href for %s: %s", sel, exc)
        return None

    async def _open_tax_record_from_assessor_detail(self, fallback_url: str) -> bool:
        detail_frame = await _wait_for_florida_pa_frame(self, "recordSearch_3_Details", timeout_ms=3_000)
        if not detail_frame:
            return False

        tax_url = await self._resolve_tax_link_url(detail_frame, fallback_url)
        if tax_url and await self._open_tax_page(tax_url):
            return True

        selectors = [
            'a:has-text("Retrieve Tax Record")',
            'a[href*="floridatax"]',
            'input[value*="Retrieve Tax Record" i]',
        ]
        for sel in selectors:
            popup_page: Page | None = None
            opened = False
            try:
                link = detail_frame.locator(sel).first
                if await link.count() == 0 or not await link.is_visible(timeout=2_000):
                    continue

                try:
                    async with self.context.expect_page(timeout=15_000) as page_info:
                        await link.click(force=True)
                    popup_page = await page_info.value
                    if await self._wait_for_tax_page(popup_page):
                        self._page = popup_page
                        opened = True
                        return True
                except Exception:
                    await link.click(force=True)
                    if await self._wait_for_tax_page(self.page):
                        return True
            except Exception as exc:
                logger.debug("Tax record link click failed for %s: %s", sel, exc)
            finally:
                if popup_page and not opened:
                    try:
                        await popup_page.close()
                    except Exception:
                        pass

        return False

    async def _scrape_all_tax_tabs(self, page: Page) -> dict:
        combined: dict = {"url": page.url, "tabs": {}}

        header = await page.evaluate(FLORIDA_TAX_PAGE_JS)
        combined.update(header or {})
        combined["tabs"]["Summary"] = {
            "fields": header.get("fields") if header else {},
            "tables": header.get("tables") if header else [],
            "yearly_due": header.get("yearly_due") if header else [],
        }

        for tab_name in TAX_TABS:
            await self._emit_status(f"Capturing tax tab: {tab_name}...")
            clicked = await self._click_tax_tab(page, tab_name)
            if not clicked:
                continue
            await page.wait_for_timeout(1_500)
            tab_data = await page.evaluate(FLORIDA_TAX_PAGE_JS)
            combined["tabs"][tab_name] = {
                "fields": (tab_data or {}).get("fields") or {},
                "tables": (tab_data or {}).get("tables") or [],
                "yearly_due": (tab_data or {}).get("yearly_due") or [],
                "body_text": (tab_data or {}).get("body_text") or "",
            }

        return combined

    async def _click_tax_tab(self, page: Page, tab_name: str) -> bool:
        for sel in [
            f'a:has-text("{tab_name}")',
            f'button:has-text("{tab_name}")',
            f'li:has-text("{tab_name}") a',
            f'[role="tab"]:has-text("{tab_name}")',
        ]:
            try:
                tab = page.locator(sel).first
                if await tab.count() > 0 and await tab.is_visible(timeout=2_000):
                    await tab.click(force=True)
                    return True
            except Exception:
                continue
        return False
