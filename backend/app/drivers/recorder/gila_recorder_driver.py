import logging
import re

from app.config.florida_portals import (
    is_florida_recorder,
    is_miami_dade_recorder,
    is_myflorida_county_recorder,
    normalize_florida_parcel,
)
from app.drivers.base.base_driver import BaseDriver
from app.drivers.page_search_ai import execute_ai_recorder_search
from app.drivers.playwright_instructions import (
    apply_playwright_instructions,
    apply_playwright_post_search,
)
from app.drivers.recorder.acclaimweb_recorder import (
    format_acclaimweb_party_name,
    is_acclaimweb_recorder,
    prepare_acclaimweb_name_search,
    resolve_party_type_from_notes,
    search_acclaimweb_party_name,
)
from app.drivers.recorder.miami_dade_recorder import (
    DEFAULT_MIAMI_DADE_BOOK_TYPE,
    miami_dade_book_page_search_and_download,
    select_miami_dade_book_type,
)
from app.extraction.book_page import format_book_page_label, parse_book_page
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


def _format_recorder_search_value(query_type: QueryType, query_value: str, page_url: str = "") -> str:
    value = query_value.strip()
    if not value:
        return value

    if query_type == QueryType.PARCEL:
        if is_miami_dade_recorder(page_url):
            return normalize_florida_parcel(value, county="miami-dade")
        return value

    if query_type == QueryType.BOOK_PAGE:
        parsed = parse_book_page(value)
        if parsed:
            return format_book_page_label(parsed[0], parsed[1])
        return value

    if query_type == QueryType.OWNER and "," not in value:
        parts = value.split()
        if len(parts) >= 2 and not re.search(r"\d{3,}", value):
            return f"{parts[-1]}, {' '.join(parts[:-1])}"
    return value


class GilaRecorderDriver(BaseDriver):
    async def search(
        self,
        recorder_url: str,
        query_type: QueryType,
        query_value: str,
        book_number: str | None = None,
        page_number: str | None = None,
        available_values: dict[str, str] | None = None,
    ) -> list[RecordedDocument]:
        await self._emit_status("Opening county recorder portal...")
        recorder_wait_selector = None
        if is_miami_dade_recorder(recorder_url):
            recorder_wait_selector = (
                "#bookType, #recordingBookNumber, input[type='text'], form, button"
            )
        try:
            await self.safe_goto(
                recorder_url,
                wait_selector=recorder_wait_selector,
                timeout=60_000,
            )
        except Exception as exc:
            if _is_retriable_navigation_error(exc):
                await self._emit_status("Recorder portal slow to load, retrying...")
                await self.polite_delay(2.0)
                await self.safe_goto(
                    recorder_url,
                    wait_selector=recorder_wait_selector,
                    timeout=60_000,
                )
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
            elif is_miami_dade_recorder(recorder_url) or is_miami_dade_recorder(self.page.url):
                prefer_book_page = bool(book_number and page_number)
                await self._open_miami_dade_recorder_search(prefer_book_page=prefer_book_page)
            elif not is_acclaimweb_recorder(recorder_url) and not is_acclaimweb_recorder(self.page.url):
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

        try:
            await self.page.wait_for_selector(
                'input[type="text"], input:not([type="hidden"]), button:has-text("Search")',
                state="visible",
                timeout=15_000,
            )
        except Exception:
            pass

        book_page = parse_book_page(query_value, book_number, page_number)
        notes = (self.playwright_notes or "").strip()
        search_value = _format_recorder_search_value(query_type, query_value, self.page.url)
        searched = False
        acclaimweb = is_acclaimweb_recorder(recorder_url) or is_acclaimweb_recorder(self.page.url)
        values = {
            k: str(v).strip()
            for k, v in (available_values or {}).items()
            if v and str(v).strip()
        }
        if book_page:
            values.setdefault("book", book_page[0])
            values.setdefault("page", book_page[1])
        if query_type == QueryType.OWNER:
            values.setdefault("owner", search_value)
        elif query_type == QueryType.PARCEL:
            values.setdefault("parcel", search_value)
        elif query_type == QueryType.ADDRESS:
            values.setdefault("address", search_value)
        values.setdefault("query_value", search_value)

        if query_type == QueryType.BOOK_PAGE:
            if not book_page:
                await self._emit_status("Recorder search skipped — book and page numbers are required.")
                return []
            book_number, page_number = book_page
            search_value = format_book_page_label(book_number, page_number)
        elif not query_value.strip() and not (values.get("book") and values.get("page")):
            await self._emit_status("Recorder search skipped — no name, parcel, or book/page in Input node.")
            return []

        ai_ok, search_kind = await execute_ai_recorder_search(
            self,
            query_type,
            search_value,
            available_values=values,
            user_instructions=notes or None,
        )
        if search_kind == "book_page" and values.get("book") and values.get("page"):
            book_number, page_number = values["book"], values["page"]
            query_type = QueryType.BOOK_PAGE
            search_value = format_book_page_label(book_number, page_number)
            if is_miami_dade_recorder(recorder_url) or is_miami_dade_recorder(self.page.url):
                await self._emit_status(
                    f"GPT-4o detected Book/Page search — using book {book_number}, page {page_number}."
                )
                doc = await miami_dade_book_page_search_and_download(self, book_number, page_number)
                await self.save_browser_preview()
                if doc:
                    return [doc]
            searched = ai_ok
        elif ai_ok:
            searched = True

        if not searched and query_type == QueryType.BOOK_PAGE and book_page:
            bnum, pnum = book_page
            if is_miami_dade_recorder(recorder_url) or is_miami_dade_recorder(self.page.url):
                doc = await miami_dade_book_page_search_and_download(self, bnum, pnum)
                await self.save_browser_preview()
                if doc:
                    return [doc]
                return []

        if notes and query_type != QueryType.BOOK_PAGE:
            await self._emit_status(f"Recorder instructions: {notes[:100]}...")

        if acclaimweb and query_type == QueryType.OWNER:
            search_value = format_acclaimweb_party_name(query_value)
            await prepare_acclaimweb_name_search(self, self.page.url)

        if notes and query_type != QueryType.BOOK_PAGE:
            if await apply_playwright_instructions(
                self, notes, query_type, search_value, portal_type="recorder"
            ):
                searched = await self._recorder_search_applied(search_value, acclaimweb)
            if not searched and acclaimweb and query_type == QueryType.OWNER:
                searched = await search_acclaimweb_party_name(
                    self, query_type, search_value, notes=notes
                )

        if not searched and not notes and acclaimweb and query_type == QueryType.OWNER:
            searched = await search_acclaimweb_party_name(
                self, query_type, format_acclaimweb_party_name(query_value), notes=""
            )

        if not searched:
            await self._emit_status(f"Running recorder search ({query_type.value})...")
            await self._try_search(
                query_type,
                search_value,
                notes=notes,
                book_number=book_number,
                page_number=page_number,
            )
            searched = await self._recorder_search_applied(search_value, acclaimweb)

        if notes:
            await apply_playwright_post_search(self, notes)

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
                    grantor=search_value if query_type == QueryType.OWNER else None,
                    document_type="Search Result",
                    book_page=search_value if query_type == QueryType.BOOK_PAGE else None,
                    source_url=self.page.url,
                    screenshot_path=screenshot_path,
                )
            ]

        return documents

    async def _recorder_search_applied(self, search_value: str, acclaimweb: bool) -> bool:
        if not acclaimweb:
            return True
        try:
            loc = self.page.locator("#SearchOnName").first
            if await loc.count() == 0:
                return True
            entered = (await loc.input_value()).strip()
            if entered:
                return True
        except Exception:
            pass
        if not search_value.strip():
            return False
        await self._emit_status("Retrying AcclaimWeb party name fill...")
        return await search_acclaimweb_party_name(
            self, QueryType.OWNER, search_value, notes=(self.playwright_notes or "")
        )

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

    async def _open_miami_dade_recorder_search(self, prefer_book_page: bool = False) -> None:
        """Wait for Miami-Dade Clerk official records search UI."""
        await self._click_disclaimer()
        if prefer_book_page and await self._open_miami_dade_book_page_search():
            return
        for sel in [
            'input[name*="folio" i]',
            'input[placeholder*="folio" i]',
            'input[name*="name" i]',
            'input[placeholder*="name" i]',
            'input[type="text"]',
            'button:has-text("Search")',
        ]:
            try:
                if await self.page.locator(sel).first.is_visible(timeout=5_000):
                    return
            except Exception:
                continue

    async def _open_miami_dade_book_page_search(self) -> bool:
        """Open Miami-Dade Clerk Recording Book/Page search form."""
        if await self.page.locator('#bookType, #recordingBookNumber').first.is_visible(timeout=1_000):
            return True

        nav_selectors = [
            'a:has-text("Recording Book/Page")',
            'span:has-text("Recording Book/Page")',
            'li:has-text("Recording Book/Page") a',
            '[href*="book" i]:has-text("Book/Page")',
        ]
        for sel in nav_selectors:
            try:
                link = self.page.locator(sel).first
                if await link.count() > 0 and await link.is_visible(timeout=3_000):
                    await link.click(force=True)
                    try:
                        await self.page.wait_for_selector(
                            "#bookType, #recordingBookNumber, input[type='text']",
                            state="attached",
                            timeout=10_000,
                        )
                    except Exception:
                        await self.polite_delay(1.0)
                    break
            except Exception:
                continue

        for sel in [
            '#recordingBookNumber',
            'input[placeholder="BOOK" i]',
            'input[placeholder*="book" i]',
            'input[name*="book" i]',
        ]:
            try:
                if await self.page.locator(sel).first.is_visible(timeout=5_000):
                    await self._emit_status("Opened Miami-Dade Recording Book/Page search.")
                    return True
            except Exception:
                continue
        return False

    async def _search_book_page(self, book_number: str, page_number: str) -> bool:
        if is_miami_dade_recorder(self.page.url):
            await self._open_miami_dade_book_page_search()
            # _open_miami_dade_book_page_search already navigated to the form;
            # do NOT re-click the nav link below or we'll navigate away.

        book_selectors = [
            'input[placeholder="BOOK" i]',
            'input[placeholder*="book" i]',
            'input[name*="book" i]',
            'input[id*="book" i]',
        ]
        page_selectors = [
            'input[placeholder="PAGE" i]',
            'input[placeholder*="page" i]',
            'input[name*="page" i]',
            'input[id*="page" i]',
        ]

        book_filled = await self._fill_first_visible(book_selectors, book_number)
        page_filled = await self._fill_first_visible(page_selectors, page_number)
        if not book_filled or not page_filled:
            inputs = await self.page.locator('input[type="text"]:visible').all()
            if len(inputs) >= 2:
                try:
                    await inputs[0].fill(book_number)
                    await inputs[1].fill(page_number)
                    book_filled = page_filled = True
                except Exception:
                    pass

        if not book_filled or not page_filled:
            await self._emit_status("Could not find book/page fields on recorder search form.")
            return False

        if is_miami_dade_recorder(self.page.url):
            if DEFAULT_MIAMI_DADE_BOOK_TYPE:
                await select_miami_dade_book_type(self, DEFAULT_MIAMI_DADE_BOOK_TYPE)

        await self._emit_status(f"Searching recorder for book {book_number}, page {page_number}...")
        await self._click_search_button()
        return True

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

    async def _book_page_fields_visible(self) -> bool:
        book_selectors = [
            '#recordingBookNumber',
            'input[placeholder="BOOK" i]',
            'input[placeholder*="book" i]',
            'input[name*="book" i]',
            'input[id*="book" i]',
        ]
        page_selectors = [
            '#recordingPageNumber',
            'input[placeholder="PAGE" i]',
            'input[placeholder*="page" i]',
            'input[name*="page" i]',
            'input[id*="page" i]',
        ]
        book_ok = False
        page_ok = False
        for sel in book_selectors:
            try:
                if await self.page.locator(sel).first.is_visible(timeout=400):
                    book_ok = True
                    break
            except Exception:
                continue
        for sel in page_selectors:
            try:
                if await self.page.locator(sel).first.is_visible(timeout=400):
                    page_ok = True
                    break
            except Exception:
                continue
        return book_ok and page_ok

    async def _try_search(
        self,
        query_type: QueryType,
        query_value: str,
        notes: str = "",
        book_number: str | None = None,
        page_number: str | None = None,
    ) -> None:
        parsed = parse_book_page(query_value, book_number, page_number)
        if parsed and await self._book_page_fields_visible():
            if await self._search_book_page(parsed[0], parsed[1]):
                return
        if query_type == QueryType.BOOK_PAGE:
            parsed = parse_book_page(query_value, book_number, page_number)
            if parsed and await self._search_book_page(parsed[0], parsed[1]):
                return

        if is_acclaimweb_recorder(self.page.url) and query_type == QueryType.OWNER:
            party_name = format_acclaimweb_party_name(query_value)
            if await search_acclaimweb_party_name(
                self, query_type, party_name, notes=notes
            ):
                return

        if query_type == QueryType.PARCEL:
            parcel_selectors = [
                'input[name*="folio" i]',
                'input[placeholder*="folio" i]',
                'input[name*="tmk" i]',
                'input[name*="parcel" i]',
                'input[name*="apn" i]',
                'input[name*="instrument" i]',
                'input[placeholder*="tmk" i]',
                'input[placeholder*="parcel" i]',
                'input[id*="tmk" i]',
                'input[id*="parcel" i]',
            ]
            filled = await self._fill_first_visible(parcel_selectors, query_value)
            if not filled:
                await self._fill_first_visible(['input[type="text"]'], query_value)
        elif query_type == QueryType.OWNER:
            party = resolve_party_type_from_notes(notes)
            if party == "grantee":
                await self._click_first_visible(["#Reverse", 'input[type="radio"][value="Reverse"]'])
            elif party == "grantor":
                await self._click_first_visible(["#Direct", 'input[type="radio"][value="Direct"]'])
            elif party == "all":
                await self._click_first_visible(["#Both", 'input[type="radio"][value="Both"]'])
            name_selectors = [
                "#SearchOnName",
                'input[name="SearchOnName"]',
                'input[name*="SearchOnName" i]',
                'input[name*="name" i]:not([name="Username"]):not([name="PartyType"])',
                'input[name*="grantor" i]',
                'input[name*="party" i]',
                'input[placeholder*="name" i]',
            ]
            filled = await self._fill_first_visible(name_selectors, query_value)
            if not filled:
                await self._fill_first_visible(['input[type="text"]'], query_value)
        else:
            address_selectors = [
                'input[name*="address" i]',
                'input[placeholder*="address" i]',
                'input[name*="legal" i]',
            ]
            filled = await self._fill_first_visible(address_selectors, query_value)
            if not filled:
                await self._fill_first_visible(['input[type="text"]'], query_value)

        await self._click_search_button()

    async def _click_search_button(self) -> None:
        """Click the Search submit button, preferring elements inside a <form> to avoid
        accidentally clicking nav links that also say 'Search'.
        """
        # First try: find the submit button scoped inside a <form>
        clicked = bool(
            await self.page.evaluate(
                """() => {
                    const form = document.querySelector('form');
                    const scope = form || document;
                    const btn =
                        scope.querySelector('button[type="submit"]') ||
                        scope.querySelector('input[type="submit"]') ||
                        [...scope.querySelectorAll('button')]
                            .find(el => /^search$/i.test((el.textContent || '').trim())) ||
                        [...scope.querySelectorAll('button')]
                            .find(el => /search/i.test(el.textContent || ''));
                    if (btn) { btn.click(); return true; }
                    return false;
                }"""
            )
        )
        if clicked:
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:
                pass
            return

        # Playwright fallback (avoids <a> tags to prevent nav link clicks)
        for btn_sel in [
            'button:has-text("SEARCH")',
            "#btnSearch",
            'input[type="submit"][value="Search"]',
            'button:has-text("Search")',
            'button[type="submit"]',
            'input[type="submit"]',
            'input[value="Search"]',
        ]:
            try:
                btn = self.page.locator(btn_sel).first
                if await btn.count() > 0 and await btn.is_visible(timeout=3_000):
                    await btn.click(force=True)
                    await self.page.wait_for_load_state("domcontentloaded")
                    return
            except Exception:
                continue

    async def _click_first_visible(self, selectors: list[str]) -> bool:
        for sel in selectors:
            try:
                loc = self.page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible(timeout=2_000):
                    await loc.click(force=True)
                    await self.polite_delay(0.3)
                    return True
            except Exception:
                continue
        return False

    async def _fill_first_visible(self, selectors: list[str], value: str) -> bool:
        for sel in selectors:
            try:
                loc = self.page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible(timeout=3_000):
                    await loc.click()
                    await loc.fill("")
                    try:
                        await loc.press_sequentially(value, delay=20)
                    except Exception:
                        await loc.fill(value)
                    await loc.evaluate(
                        """(el, val) => {
                            el.value = val;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                        }""",
                        value,
                    )
                    return True
            except Exception:
                continue
        return False
