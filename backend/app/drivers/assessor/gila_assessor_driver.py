import logging
import re

from app.config.assessor_portals import (
    HONOLULU_LANDING_URL,
    HONOLULU_PROPERTY_SEARCH_URL,
    HONOLULU_SEARCH_URL,
    is_honolulu_schneider,
    resolve_assessor_search_url,
)
from app.drivers.assessor.florida_assessor import search_florida_assessor
from app.drivers.base.base_driver import BaseDriver
from app.extraction.html_extractors import extract_parcel_from_html
from app.extraction.schneider_extractors import (
    SCHNEIDER_SCRAPE_JS,
    extract_schneider_qpublic_from_html,
    parcel_record_from_schneider_data,
)
from app.extraction.schemas import ParcelRecord, QueryType

logger = logging.getLogger(__name__)

HONOLULU_PARCEL_INPUT = "#ctlBodyPane_ctl02_ctl01_txtParcelID"
HONOLULU_PARCEL_SEARCH_BTN = "#ctlBodyPane_ctl02_ctl01_btnSearch"
HONOLULU_ADDRESS_INPUT = "#ctlBodyPane_ctl01_ctl01_txtAddress"
HONOLULU_ADDRESS_SEARCH_BTN = "#ctlBodyPane_ctl01_ctl01_btnSearch"
HONOLULU_OWNER_INPUT = "#ctlBodyPane_ctl03_ctl01_txtOwnerName"
HONOLULU_OWNER_SEARCH_BTN = "#ctlBodyPane_ctl03_ctl01_btnSearch"


def _normalize_honolulu_parcel(parcel: str) -> str:
    """Strip non-digits; Honolulu TMK search accepts digits with or without dashes."""
    digits = re.sub(r"\D", "", parcel)
    return digits or parcel.strip()


class GilaAssessorDriver(BaseDriver):
    """Property assessor driver — works with Gila County and qPublic/Schneider Corp portals."""

    async def search(
        self,
        assessor_url: str,
        query_type: QueryType,
        query_value: str,
        state: str | None = None,
        county: str | None = None,
    ) -> list[ParcelRecord]:
        search_url = resolve_assessor_search_url(assessor_url)

        if state and state.upper() == "FL":
            return await search_florida_assessor(self, assessor_url, query_type, query_value)

        if is_honolulu_schneider(search_url) or is_honolulu_schneider(assessor_url):
            return await self._search_honolulu_schneider(search_url, query_type, query_value)

        await self.safe_goto(search_url, wait_selector="table, form, input")
        await self.dismiss_netronline_modals()

        if "schneidercorp.com" in search_url or "qpublic.net" in search_url:
            return await self._search_qpublic(search_url, query_type, query_value)

        await self._try_search_form(query_type, query_value)
        await self.polite_delay(2.0)

        html = await self.page.content()
        parcel = extract_parcel_from_html(html)

        if not parcel.apn and not parcel.owner_name:
            results = await self._parse_result_links()
            if results:
                return results

        if parcel.apn or parcel.owner_name or parcel.property_address:
            return [parcel]
        return []

    async def _search_honolulu_schneider(
        self,
        search_url: str,
        query_type: QueryType,
        query_value: str,
    ) -> list[ParcelRecord]:
        """Honolulu qPublic Schneider — open search page, enter parcel, click Search."""
        await self._emit_status("Opening Honolulu parcel search page...")
        target = HONOLULU_SEARCH_URL
        if "schneidercorp.com" in search_url.lower():
            target = search_url

        await self.page.goto(target, wait_until="domcontentloaded", timeout=20_000)
        await self.dismiss_schneider_terms()

        if await self.is_cloudflare_blocked():
            cleared = await self.wait_for_cloudflare_clear(
                max_wait=120,
                success_selector=HONOLULU_PARCEL_INPUT,
            )
            try:
                form_visible = await self.page.locator(HONOLULU_PARCEL_INPUT).is_visible()
            except Exception:
                form_visible = False
            if not cleared and not form_visible:
                return []

        await self.dismiss_netronline_modals()

        if not await self._wait_for_honolulu_search_form():
            return []

        if query_type == QueryType.PARCEL:
            parcel_value = _normalize_honolulu_parcel(query_value)
            await self._submit_honolulu_parcel_search(parcel_value)
        elif query_type == QueryType.ADDRESS:
            await self._submit_honolulu_address_search(query_value)
        else:
            await self._submit_honolulu_owner_search(query_value)

        await self.polite_delay(2.0)

        # Search often lands directly on detail/report — extract immediately if so
        if await self._is_honolulu_detail_page():
            await self._open_honolulu_report_tab()
            parcel = await self._extract_schneider_detail_record()
            if parcel.apn or parcel.owner_name or parcel.property_address:
                return [parcel]

        if await self.is_cloudflare_blocked():
            cleared = await self.wait_for_cloudflare_clear(
                success_selector=".widgetLabel, #ctlBodyPane",
            )
            if not cleared and not await self._is_honolulu_detail_page():
                return []

        await self._open_honolulu_parcel_detail()
        await self._open_honolulu_report_tab()
        parcel = await self._extract_schneider_detail_record()
        if parcel.apn or parcel.owner_name or parcel.property_address:
            return [parcel]

        return await self._parse_result_links()

    async def _open_honolulu_report_tab(self) -> None:
        """Open the Report tab — contains full parcel, owner, and assessment data."""
        for sel in [
            'a[id*="Report" i]',
            '#TopBar a:has-text("Report")',
            'a:has-text("Report")',
        ]:
            try:
                tab = self.page.locator(sel).first
                if await tab.count() == 0 or not await tab.is_visible():
                    continue
                text = (await tab.inner_text()).strip().lower()
                if text != "report" and "report" not in (await tab.get_attribute("href") or "").lower():
                    continue
                await tab.click()
                await self.polite_delay(2.5)
                try:
                    await self.page.wait_for_selector(".widgetLabel, table", timeout=12_000)
                except Exception:
                    pass
                await self._emit_status("Report tab loaded — extracting full property data.")
                return
            except Exception:
                continue

    async def _expand_honolulu_owners(self) -> None:
        try:
            btn = self.page.locator(
                'button:has-text("Show All Owners"), a:has-text("Show All Owners")'
            ).first
            if await btn.count() and await btn.is_visible():
                await btn.click()
                await self.polite_delay(1.5)
        except Exception:
            pass

    async def _scroll_to_parcel_information(self) -> None:
        try:
            heading = self.page.locator("text=Parcel Information").first
            if await heading.count():
                await heading.scroll_into_view_if_needed()
                await self.polite_delay(1.0)
        except Exception:
            pass

    async def _scroll_to_sales_information(self) -> None:
        """Scroll to Sales Information on the Report tab — recorder-type transaction history."""
        try:
            heading = self.page.locator('text=Sales Information').first
            if await heading.count():
                await heading.scroll_into_view_if_needed()
                await self.polite_delay(1.5)
                await self._emit_status("Reading Sales Information transaction history from report...")
        except Exception:
            pass

    def _merge_scrape_data(self, base: dict, extra: dict) -> dict:
        from app.extraction.schneider_extractors import PARCEL_INFO_KEYS

        merged = {**base}
        for key, value in extra.items():
            key_lower = str(key).lower()
            if key in ("assessment_rows", "owner_rows", "chain_of_title") and isinstance(value, list):
                existing = merged.get(key) or []
                merged[key] = existing + value
            elif key_lower in PARCEL_INFO_KEYS and merged.get(key):
                continue
            elif value and key not in merged:
                merged[key] = value
        if extra.get("Owner Names") and (
            not merged.get("Owner Names") or merged.get("Owner Names") == "Owner Type"
        ):
            merged["Owner Names"] = extra["Owner Names"]
        return merged

    def _merge_parcel_records(self, primary: ParcelRecord, secondary: ParcelRecord) -> ParcelRecord:
        merged_raw = {**primary.raw_json, **secondary.raw_json}
        for key, value in primary.raw_json.items():
            if value:
                merged_raw[key] = value
        return primary.model_copy(
            update={
                "apn": primary.apn or secondary.apn,
                "owner_name": primary.owner_name or secondary.owner_name,
                "property_address": primary.property_address or secondary.property_address,
                "legal_desc": primary.legal_desc or secondary.legal_desc,
                "assessed_value": primary.assessed_value or secondary.assessed_value,
                "raw_json": merged_raw,
            }
        )

    async def _extract_schneider_detail_record(self) -> ParcelRecord:
        """Scrape all label/value fields from a Schneider qPublic detail page."""
        await self._emit_status("Extracting property data from detail page...")
        await self._open_honolulu_report_tab()

        try:
            await self.page.wait_for_selector(
                ".widgetLabel, table, #ctlBodyPane, [id*='lblLocation'], [id*='lblLegal']",
                timeout=15_000,
            )
        except Exception:
            pass

        await self._expand_honolulu_owners()
        await self._scroll_to_parcel_information()
        await self.polite_delay(1.0)
        await self._scroll_to_sales_information()
        try:
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self.polite_delay(1.5)
            await self._scroll_to_sales_information()
        except Exception:
            pass

        report_url = self.page.url
        report_html = await self.page.content()

        data: dict = {}
        try:
            data = await self.page.evaluate(SCHNEIDER_SCRAPE_JS)
        except Exception as exc:
            logger.warning("Live Schneider scrape failed: %s", exc)

        report_parcel = extract_schneider_qpublic_from_html(report_html, report_url)
        if data:
            parcel = parcel_record_from_schneider_data(data, source_url=report_url)
        else:
            parcel = report_parcel

        parcel = self._merge_parcel_records(parcel, report_parcel)

        if not (parcel.apn or parcel.owner_name or parcel.property_address):
            fallback = extract_parcel_from_html(report_html)
            if fallback.apn or fallback.owner_name:
                parcel = self._merge_parcel_records(parcel, fallback)

        chain_count = len(parcel.raw_json.get("chain_of_title") or [])
        field_count = len(
            [k for k in parcel.raw_json if k not in ("assessment_rows", "owner_rows", "chain_of_title")]
        )
        await self._emit_status(
            f"Extracted {field_count} property field(s)"
            + (f" and {chain_count} chain-of-title entry(ies)." if chain_count else ".")
        )
        return parcel

    async def _open_honolulu_property_search(self) -> None:
        """Go to Property Search — same destination as clicking the nav link, but faster."""
        await self._emit_status("Opening Property Search page...")

        # Fast path: search.html is the href behind the "Property Search" nav button
        try:
            await self.page.goto(
                HONOLULU_PROPERTY_SEARCH_URL,
                wait_until="domcontentloaded",
                timeout=20_000,
            )
        except Exception:
            logger.debug("search.html navigation failed, trying Schneider search URL")
            await self.safe_goto(HONOLULU_SEARCH_URL, wait_selector="body")
            return

        if "schneidercorp.com" not in self.page.url:
            try:
                await self.page.wait_for_url("**/*schneidercorp.com/**", timeout=12_000)
            except Exception:
                logger.debug("Redirect to Schneider slow — opening search URL directly")
                await self.safe_goto(HONOLULU_SEARCH_URL, wait_selector="body")

        if "schneidercorp.com" in self.page.url:
            await self.wait_for_cloudflare_clear(max_wait=60)

    async def _wait_for_honolulu_search_form(self) -> bool:
        await self.dismiss_schneider_terms()
        try:
            await self.page.wait_for_selector(HONOLULU_PARCEL_INPUT, state="visible", timeout=12_000)
            return True
        except Exception:
            if await self.wait_for_cloudflare_clear(
                max_wait=60,
                success_selector=HONOLULU_PARCEL_INPUT,
            ):
                try:
                    await self.page.wait_for_selector(HONOLULU_PARCEL_INPUT, state="visible", timeout=12_000)
                    return True
                except Exception:
                    pass
        try:
            return await self.page.locator(HONOLULU_PARCEL_INPUT).is_visible()
        except Exception:
            return False

    async def _ensure_honolulu_parcel_section_open(self) -> None:
        """Expand 'Search by Parcel Number (TMK)' if the section is collapsed."""
        toggle = self.page.locator("#ctlBodyPane_ctl02_btnHeaderToggle")
        if await toggle.count() == 0:
            return
        parcel_input = self.page.locator(HONOLULU_PARCEL_INPUT)
        if not await parcel_input.is_visible():
            await toggle.click()
            await self.polite_delay(0.5)

    async def _submit_honolulu_parcel_search(self, parcel_value: str) -> None:
        """Fill parcel TMK field and click Search — navigates to results or detail page."""
        await self._emit_status(f"Entering parcel {parcel_value} and clicking Search...")

        for _ in range(3):
            await self.dismiss_schneider_terms()

        await self._ensure_honolulu_parcel_section_open()

        parcel_input = self.page.locator(HONOLULU_PARCEL_INPUT)
        await parcel_input.wait_for(state="visible", timeout=10_000)
        await parcel_input.scroll_into_view_if_needed()
        await parcel_input.click()
        await parcel_input.fill("")
        await parcel_input.press_sequentially(parcel_value, delay=30)

        entered = await parcel_input.input_value()
        if entered != parcel_value:
            await parcel_input.evaluate(
                """(el, val) => {
                    el.value = val;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                parcel_value,
            )

        await self.dismiss_schneider_terms()
        await self._click_honolulu_parcel_search()

        try:
            await self.page.wait_for_selector(
                'a[href*="KeyValue"], .widgetLabel, table.results',
                timeout=15_000,
            )
        except Exception:
            pass
        await self.polite_delay(1.0)

    async def _click_honolulu_parcel_search(self) -> None:
        """Click the parcel Search button — ASP.NET WebForms postback."""
        await self.dismiss_schneider_terms()
        search_btn = self.page.locator(HONOLULU_PARCEL_SEARCH_BTN)
        await search_btn.scroll_into_view_if_needed()

        clicked = await self.page.evaluate(
            """() => {
                const btn = document.querySelector('#ctlBodyPane_ctl02_ctl01_btnSearch');
                if (btn) { btn.click(); return true; }
                if (typeof __doPostBack === 'function') {
                    __doPostBack('ctlBodyPane$ctl02$ctl01$btnSearch', '');
                    return true;
                }
                return false;
            }"""
        )
        if not clicked:
            await search_btn.click(force=True)

        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        await self.polite_delay(1.5)

    async def _submit_honolulu_address_search(self, address: str) -> None:
        await self._emit_status(f"Searching address {address}...")
        address_input = self.page.locator(HONOLULU_ADDRESS_INPUT)
        await address_input.scroll_into_view_if_needed()
        await address_input.click()
        await address_input.fill(address)
        await self.dismiss_schneider_terms()
        await self._click_honolulu_search(self.page.locator(HONOLULU_ADDRESS_SEARCH_BTN))

    async def _submit_honolulu_owner_search(self, owner: str) -> None:
        await self._emit_status(f"Searching owner {owner}...")
        filled = await self._fill_first_visible(
            [
                HONOLULU_OWNER_INPUT,
                "#ctlBodyPane_ctl03_ctl01_txtName",
                'input[id*="ctl03"][id*="Owner" i]',
                'input[id*="ctl03"][id*="Name" i]',
            ],
            owner,
        )
        if not filled:
            await self._emit_status("Could not find Honolulu owner search field.")
            return
        await self.dismiss_schneider_terms()
        await self._click_honolulu_search(self.page.locator(HONOLULU_OWNER_SEARCH_BTN))

    async def _click_honolulu_search(self, btn) -> None:
        await self.dismiss_schneider_terms()
        try:
            await btn.click(force=True, timeout=5_000)
        except Exception:
            await btn.evaluate("el => el.click()")
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        await self.polite_delay(1.0)

    async def _is_honolulu_detail_page(self) -> bool:
        url = self.page.url.lower()
        if "keyvalue=" in url:
            return True
        if await self.page.locator(".widgetLabel").count() > 2:
            return True
        return False

    async def _open_honolulu_parcel_detail(self) -> bool:
        """Open parcel detail from search results (or stay if already on detail page)."""
        if await self._is_honolulu_detail_page():
            await self._emit_status("Parcel detail page loaded.")
            return True

        await self._emit_status("Opening parcel detail from search results...")
        parcel_link_selectors = [
            'table a[href*="KeyValue"]',
            'a[href*="PageTypeID=4"]',
            'a[href*="KeyValue"]',
            '#ctlBodyPane table td a',
            'table.results a',
        ]
        for sel in parcel_link_selectors:
            links = self.page.locator(sel)
            count = await links.count()
            for i in range(min(count, 8)):
                link = links.nth(i)
                text = (await link.inner_text()).strip()
                href = (await link.get_attribute("href") or "").lower()
                if not href or text.lower() in ("search", "print", "email", "map"):
                    continue
                if "keyvalue" not in href and not re.search(r"\d{4,}", text):
                    continue
                try:
                    async with self.page.expect_navigation(timeout=25_000):
                        await link.click()
                except Exception:
                    await link.click()
                await self.polite_delay(2.0)
                await self.wait_for_cloudflare_clear()
                return True

        return await self._is_honolulu_detail_page()

    async def _search_qpublic(
        self,
        search_url: str,
        query_type: QueryType,
        query_value: str,
    ) -> list[ParcelRecord]:
        """Generic Schneider Corp qPublic — used by many US counties."""
        if "pagetype=search" not in search_url.lower():
            await self._open_qpublic_search()

        if query_type == QueryType.OWNER:
            filled = await self._fill_first_visible(
                [
                    'input[id*="Owner" i]',
                    'input[name*="Owner" i]',
                    'input[placeholder*="owner" i]',
                    'input[aria-label*="owner" i]',
                ],
                query_value,
            )
        elif query_type == QueryType.ADDRESS:
            filled = await self._fill_first_visible(
                [
                    'input[id*="Address" i]',
                    'input[name*="Address" i]',
                    'input[placeholder*="address" i]',
                    'input[aria-label*="address" i]',
                    'input[placeholder*="street" i]',
                ],
                query_value,
            )
        else:
            filled = await self._fill_first_visible(
                [
                    'input[placeholder*="parcel number" i]',
                    'input[id*="Parcel" i]',
                    'input[name*="Parcel" i]',
                    'input[id*="Pin" i]',
                    'input[placeholder*="parcel" i]',
                    'input[aria-label*="parcel" i]',
                ],
                query_value,
            )

        if not filled:
            await self._fill_first_visible(['input[type="text"]'], query_value)

        await self.dismiss_schneider_terms()
        await self._click_search_button()
        await self.polite_delay(2.5)
        try:
            await self.page.wait_for_selector("table a, table tr", timeout=15_000)
        except Exception:
            pass

        clicked = await self._click_first_parcel_result()
        if clicked:
            await self.polite_delay(2.0)
            try:
                await self.page.wait_for_selector("table, span, .widgetLabel", timeout=15_000)
            except Exception:
                pass

        if await self._is_honolulu_detail_page() or "keyvalue=" in self.page.url.lower():
            parcel = await self._extract_schneider_detail_record()
        else:
            html = await self.page.content()
            parcel = extract_schneider_qpublic_from_html(html, self.page.url)

        if parcel.apn or parcel.owner_name or parcel.property_address:
            return [parcel]

        return await self._parse_result_links()

    async def _open_qpublic_search(self) -> None:
        for sel in [
            'a:has-text("Property Search")',
            'a:has-text("Parcel Search")',
            '#ctl00_TopNavBar_Search',
            'a:has-text("Search")',
        ]:
            try:
                link = self.page.locator(sel).first
                if await link.count() > 0 and await link.is_visible(timeout=2000):
                    await link.click()
                    await self.page.wait_for_load_state("domcontentloaded")
                    await self.polite_delay(1.5)
                    await self.dismiss_schneider_terms()
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

    async def _click_search_button(self) -> None:
        for sel in [
            'a[id*="btnSearch"][searchintent="ParcelID"]',
            'a[id*="btnSearch"]',
            'button:has-text("Search")',
            'input[type="submit"][value*="Search" i]',
            '#btSearch',
        ]:
            try:
                btn = self.page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible(timeout=1500):
                    await self.dismiss_schneider_terms()
                    await btn.click()
                    await self.page.wait_for_load_state("domcontentloaded")
                    return
            except Exception:
                continue

    async def _click_first_parcel_result(self) -> bool:
        parcel_link_selectors = [
            'a[href*="KeyValue"]',
            'a[href*="PageTypeID"]',
            'table a[href*="Parcel"]',
            'table td a',
        ]
        for sel in parcel_link_selectors:
            try:
                links = self.page.locator(sel)
                count = await links.count()
                for i in range(min(count, 10)):
                    link = links.nth(i)
                    text = (await link.inner_text()).strip()
                    if not text or text.lower() in ("search", "fix", "map"):
                        continue
                    if re.search(r"\d", text) and len(text) >= 4:
                        await link.click()
                        return True
            except Exception:
                continue
        return False

    async def _try_search_form(self, query_type: QueryType, query_value: str) -> None:
        owner_selectors = [
            'input[name*="owner" i]',
            'input[name*="name" i]',
        ]
        address_selectors = [
            'input[name*="address" i]',
            'input[name*="street" i]',
            'input[placeholder*="address" i]',
        ]
        parcel_selectors = [
            'input[name*="parcel" i]',
            'input[name*="account" i]',
            'input[type="search"]',
            'input[type="text"]',
        ]

        filled = False
        if query_type == QueryType.OWNER:
            selectors = owner_selectors
        elif query_type == QueryType.ADDRESS:
            selectors = address_selectors
        else:
            selectors = parcel_selectors

        for sel in selectors:
            loc = self.page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.fill(query_value)
                filled = True
                break

        if not filled:
            generic = self.page.locator('input[type="text"]').first
            if await generic.count() > 0:
                await generic.fill(query_value)
                filled = True

        if filled:
            for btn_sel in ['button[type="submit"]', 'input[type="submit"]', 'button:has-text("Search")']:
                btn = self.page.locator(btn_sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await self.page.wait_for_load_state("domcontentloaded")
                    return

    async def _parse_result_links(self) -> list[ParcelRecord]:
        records: list[ParcelRecord] = []
        links = await self.page.locator("table a, .results a, tr a").all()
        for link in links[:5]:
            try:
                text = await link.inner_text()
                href = await link.get_attribute("href")
                if href and len(text.strip()) > 2:
                    if re.match(r"^[\d\-]+$", text.strip()):
                        await link.click()
                        await self.polite_delay(2.0)
                        html = await self.page.content()
                        parcel = extract_parcel_from_html(html)
                        if parcel.apn or parcel.owner_name:
                            return [parcel]
                    records.append(
                        ParcelRecord(
                            apn=text.strip() if re.match(r"^[\d\-]+$", text.strip()) else None,
                            owner_name=text.strip() if not re.match(r"^[\d\-]+$", text.strip()) else None,
                            source="assessor",
                            raw_json={"link": href, "preview": text.strip()},
                        )
                    )
            except Exception as exc:
                logger.debug("Link parse skip: %s", exc)
        return records
