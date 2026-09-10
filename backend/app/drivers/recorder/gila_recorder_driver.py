import logging

from app.config.florida_portals import is_florida_recorder, is_myflorida_county_recorder
from app.drivers.base.base_driver import BaseDriver
from app.extraction.html_extractors import extract_documents_from_html
from app.extraction.schemas import QueryType, RecordedDocument

logger = logging.getLogger(__name__)


def _is_retriable_navigation_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "timeout",
            "timed_out",
            "connection",
            "err_connection",
            "net::",
        )
    )


class GilaRecorderDriver(BaseDriver):
    async def search(
        self,
        recorder_url: str,
        query_type: QueryType,
        query_value: str,
    ) -> list[RecordedDocument]:
        await self._emit_status("Opening county recorder portal...")
        try:
            await self.safe_goto(recorder_url, timeout=90_000)
        except Exception as exc:
            if _is_retriable_navigation_error(exc):
                await self._emit_status("Recorder portal slow to load, retrying...")
                await self.polite_delay(3.0)
                await self.safe_goto(recorder_url, timeout=90_000)
            else:
                raise

        if await self.is_cloudflare_blocked():
            cleared = await self.wait_for_cloudflare_clear(max_wait=90)
            if not cleared:
                await self._emit_status("Recorder skipped — Cloudflare verification not completed.")
                return []

        await self.dismiss_netronline_modals()
        await self._click_disclaimer()

        if is_florida_recorder(recorder_url) or is_florida_recorder(self.page.url):
            await self._emit_status("Opening Florida clerk official records search...")
            if is_myflorida_county_recorder(recorder_url) or is_myflorida_county_recorder(self.page.url):
                await self._open_myfloridacounty_search()
            else:
                await self._open_florida_recorder_search()
            await self.polite_delay(1.5)

        if "hawaii.gov/boc" in recorder_url or "boc" in recorder_url.lower():
            if await self.is_cloudflare_blocked():
                cleared = await self.wait_for_cloudflare_clear(max_wait=90)
                if not cleared:
                    return []
            await self._open_hawaii_boc_search()
            if await self.is_cloudflare_blocked():
                cleared = await self.wait_for_cloudflare_clear(max_wait=90)
                if not cleared:
                    return []

        await self._try_search(query_type, query_value)
        await self.polite_delay(2.0)

        if await self.is_cloudflare_blocked():
            return []

        html = await self.page.content()
        documents = extract_documents_from_html(html)

        if not documents:
            if "hawaii.gov" in self.page.url and "boc" in self.page.url.lower():
                await self._emit_status(
                    "Hawaii Bureau of Conveyances requires login for full document access."
                )
            screenshot_path = await self.screenshot_on_failure("recorder_results")
            documents = [
                RecordedDocument(
                    grantor=query_value if query_type == QueryType.OWNER else None,
                    document_type="Search Result",
                    source_url=self.page.url,
                    screenshot_path=screenshot_path,
                )
            ]

        return documents

    async def _open_florida_recorder_search(self) -> None:
        """Navigate into Florida county clerk / comptroller official records search."""
        for sel in [
            'a:has-text("Official Records")',
            'a:has-text("Document Search")',
            'a:has-text("Search Records")',
            'a:has-text("Property Search")',
            'a:has-text("Name Search")',
            'a[href*="search"]',
            'a[href*="officialrecords"]',
            'button:has-text("Search")',
        ]:
            try:
                link = self.page.locator(sel).first
                if await link.count() > 0 and await link.is_visible(timeout=2_000):
                    await link.click()
                    await self.page.wait_for_load_state("domcontentloaded")
                    await self.polite_delay(1.5)
                    return
            except Exception:
                continue

    async def _open_myfloridacounty_search(self) -> None:
        """Accept disclaimer and wait for MyFloridaCounty ORI search form."""
        await self._click_disclaimer()
        for sel in [
            'input[name*="parcel" i]',
            'input[name*="name" i]',
            'input[type="text"]',
            'button:has-text("Search")',
        ]:
            try:
                if await self.page.locator(sel).first.is_visible(timeout=3_000):
                    return
            except Exception:
                continue

    async def _open_hawaii_boc_search(self) -> None:
        """Follow NETR link into Hawaii Bureau of Conveyances document search portal."""
        await self._emit_status("Opening Hawaii document search...")
        for sel in [
            'a:has-text("document ordering")',
            'a:has-text("Document Search")',
            'a:has-text("search the system")',
            'a[href*="search"]',
            'a[href*="order"]',
        ]:
            try:
                link = self.page.locator(sel).first
                if await link.count() > 0 and await link.is_visible(timeout=2000):
                    await link.click()
                    await self.page.wait_for_load_state("domcontentloaded")
                    await self.polite_delay(1.5)
                    return
            except Exception:
                continue

    async def _click_disclaimer(self) -> None:
        disclaimer_selectors = [
            'button:has-text("Accept")',
            'button:has-text("I Agree")',
            'button:has-text("Agree")',
            'input[value="Accept"]',
            'a:has-text("Accept")',
            'button:has-text("Continue")',
            '#disclaimerAccept',
            '.accept-button',
        ]
        for sel in disclaimer_selectors:
            try:
                btn = self.page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                    await btn.click()
                    await self.page.wait_for_load_state("domcontentloaded")
                    await self.polite_delay()
                    return
            except Exception:
                continue

    async def _try_search(self, query_type: QueryType, query_value: str) -> None:
        if query_type == QueryType.PARCEL:
            parcel_selectors = [
                'input[name*="tmk" i]',
                'input[name*="parcel" i]',
                'input[name*="apn" i]',
                'input[placeholder*="tmk" i]',
                'input[placeholder*="parcel" i]',
                'input[id*="tmk" i]',
                'input[id*="parcel" i]',
            ]
            filled = await self._fill_first_visible(parcel_selectors, query_value)
            if not filled:
                await self._fill_first_visible(['input[type="text"]'], query_value)
        else:
            name_selectors = [
                'input[name*="name" i]',
                'input[name*="grantor" i]',
                'input[name*="party" i]',
                'input[placeholder*="name" i]',
            ]
            filled = await self._fill_first_visible(name_selectors, query_value)
            if not filled:
                await self._fill_first_visible(['input[type="text"]'], query_value)

        for btn_sel in [
            'button:has-text("Search")',
            'button[type="submit"]',
            'input[type="submit"]',
            'a:has-text("Search")',
        ]:
            try:
                btn = self.page.locator(btn_sel).first
                if await btn.count() > 0 and await btn.is_visible(timeout=1500):
                    await btn.click()
                    await self.page.wait_for_load_state("domcontentloaded")
                    return
            except Exception:
                continue

    async def _fill_first_visible(self, selectors: list[str], value: str) -> bool:
        for sel in selectors:
            try:
                loc = self.page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible(timeout=1500):
                    await loc.click()
                    await loc.fill(value)
                    return True
            except Exception:
                continue
        return False
