import asyncio
import logging
import re
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

from playwright.async_api import Page

from app.config.florida_portals import is_florida_tax_site, resolve_florida_tax_url
from app.drivers.assessor.florida_assessor import _wait_for_florida_pa_frame
from app.drivers.base.base_driver import BaseDriver
from app.drivers.page_search_ai import execute_ai_page_search
from app.drivers.playwright_instructions import apply_playwright_instructions
from app.extraction.florida_tax_extractors import FLORIDA_TAX_PAGE_JS, tax_record_from_florida_data
from app.extraction.schemas import QueryType, TaxRecord

logger = logging.getLogger(__name__)

TAX_TABS = ("Taxes", "Assessments", "Legal Description", "Payment History")

# How many most-recent annual bills to open via the info (i) icon and download.
ANNUAL_BILLS_TO_CAPTURE = 2

# Detect when county-taxes iframe has real account data (not just section headers / spinners).
COUNTY_TAXES_CONTENT_READY_JS = """
() => {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const bodyText = norm(document.body?.innerText || '');
    const lower = bodyText.toLowerCase();

    if (!bodyText || lower === 'loading') {
        return { ready: false, reason: 'loading' };
    }
    if (lower.includes('validating your session')) {
        return { ready: false, reason: 'session' };
    }
    if (lower.includes('loading') && bodyText.length < 500) {
        return { ready: false, reason: 'loading_short' };
    }

    const busy = document.querySelector('[aria-busy="true"]');
    if (busy && busy.offsetParent !== null) {
        return { ready: false, reason: 'aria_busy' };
    }

    const hasAccount = /real estate account #?[\\d-]+/i.test(bodyText) || /account #[\\d-]+/i.test(bodyText);
    if (!hasAccount && !lower.includes('bill details')) {
        return { ready: false, reason: 'no_account' };
    }

    const ownerMatch = bodyText.match(/Owner:\\s*([^\\n]+?)\\s*Situs:/i);
    const owner = ownerMatch ? norm(ownerMatch[1]) : '';
    if (lower.includes('owner:') && owner.length < 3) {
        return { ready: false, reason: 'owner_loading' };
    }

    if (lower.includes('amount due')) {
        const amountReady = /\\$[\\d,]+\\.\\d{2}/.test(bodyText)
            || /paid in full/i.test(bodyText)
            || /nothing due/i.test(bodyText)
            || /no amount due/i.test(bodyText);
        if (!amountReady) {
            return { ready: false, reason: 'amount_due_loading' };
        }
    }

    let annualBillRows = 0;
    document.querySelectorAll('table tbody tr').forEach((tr) => {
        const txt = norm(tr.innerText).toLowerCase();
        if (txt.includes('annual bill') && /20\\d{2}/.test(txt)) {
            annualBillRows += 1;
        }
    });

    if (lower.includes('account history') && annualBillRows === 0) {
        return { ready: false, reason: 'account_history_loading', annualBillRows };
    }

    return { ready: true, annualBillRows, owner };
}
"""

COUNTY_TAXES_BILL_DETAILS_READY_JS = """
() => {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const bodyText = norm(document.body?.innerText || '');
    const lower = bodyText.toLowerCase();

    if (!bodyText || lower === 'loading') {
        return { ready: false, reason: 'loading' };
    }
    if (lower.includes('validating your session')) {
        return { ready: false, reason: 'session' };
    }
    if (lower.includes('loading') && bodyText.length < 600) {
        return { ready: false, reason: 'loading_short' };
    }

    const onBillPage = lower.includes('bill details')
        || lower.includes('ad valorem')
        || lower.includes('combined taxes')
        || lower.includes('notice of ad valorem');
    if (!onBillPage) {
        return { ready: false, reason: 'not_bill_details' };
    }

    const hasPdfLink = [...document.querySelectorAll('a')].some((a) => {
        const t = norm(a.innerText).toLowerCase();
        return t.includes('view bill') || (t.includes('print') && t.includes('pdf'));
    });
    const hasTaxTable = [...document.querySelectorAll('table tbody tr')].some((tr) => {
        return /millage|levy|assessment|authority/i.test(tr.innerText);
    });
    const hasSummary = /\\$[\\d,]+\\.\\d{2}/.test(bodyText) || /millage/i.test(bodyText);

    if (!hasPdfLink && !hasTaxTable && !hasSummary) {
        return { ready: false, reason: 'bill_details_loading' };
    }

    return { ready: true };
}
"""

# JavaScript to scrape a county-taxes.com (GovTech/EasySmartPay) property detail page.
COUNTY_TAXES_COM_JS = """
() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const fields = {};
  const assign = (k, v) => { if (v) fields[k.toLowerCase()] = v; };

  // Key-value pairs from definition lists and label/value blocks
  document.querySelectorAll('dl dt, .label, .key, th').forEach((el) => {
    const key = norm(el.innerText).replace(/:$/, '');
    const val = norm((el.nextElementSibling || el.parentElement?.querySelector('dd, .value, td'))?.innerText || '');
    if (key && val) assign(key, val);
  });

  // Tables
  const tables = [...document.querySelectorAll('table')].map((t, idx) => {
    const rows = [...t.querySelectorAll('tr')].map(r =>
      [...r.querySelectorAll('th,td')].map(c => norm(c.innerText)).filter(Boolean)
    ).filter(r => r.length > 0);
    const headers = rows[0]?.every(c => c.length < 50) ? rows[0] : [];
    return { idx, headers, rows };
  });

  return {
    title: document.title,
    url: location.href,
    fields,
    tables,
    body_text: norm(document.body?.innerText || '').slice(0, 12000),
  };
}
"""


def _is_florida_tax_url(url: str) -> bool:
    """Return True for any recognised FL county tax collector site."""
    return is_florida_tax_site(url)


def _is_county_taxes_com(url: str) -> bool:
    return "county-taxes.com" in url.lower() or "county-taxes.net" in url.lower()


def _has_usable_tax_data(record: TaxRecord, scraped: dict) -> bool:
    if record.tax_account or record.amount_due is not None or record.bill_number:
        return True
    fields = scraped.get("fields") or {}
    for key in ("tax account", "account", "folio", "total due", "amount due", "assessed value", "taxes"):
        if any(key in k for k in fields):
            return True
    for tbl in scraped.get("tables") or []:
        if len(tbl.get("rows", [])) > 0 and tbl.get("headers"):
            return True
    return False


class FloridaTaxDriver(BaseDriver):
    async def _scrape_open_tax_page(
        self,
        tax_page: Page,
        *,
        apn: str,
        owner_name: Optional[str],
        search_type: QueryType,
        search_value: str,
    ) -> Optional[TaxRecord]:
        if _is_county_taxes_com(tax_page.url):
            await self._handle_county_taxes_com(tax_page, search_value, apn)
            tax_page = self.page

        scraped = await self._scrape_tax_page(tax_page)
        record = tax_record_from_florida_data(scraped, apn=apn, owner_name=owner_name)
        if _has_usable_tax_data(record, scraped):
            await self._emit_status("Saved tax bill details from county tax collector.")
            return record

        if not _is_county_taxes_com(tax_page.url):
            await self._emit_status("Tax page opened but no usable data — trying search.")
            if await self._search_tax_portal(search_type, search_value):
                tax_page = self.page
                scraped = await self._scrape_tax_page(tax_page)
                record = tax_record_from_florida_data(scraped, apn=apn, owner_name=owner_name)
                if _has_usable_tax_data(record, scraped):
                    await self._emit_status("Saved tax bill details from county tax collector.")
                    return record
        return None

    async def _open_and_scrape_florida_tax_portal(
        self,
        direct_url: str,
        *,
        apn: str,
        owner_name: Optional[str],
        search_type: QueryType,
        search_value: str,
        attempts: int = 2,
    ) -> Optional[TaxRecord]:
        for attempt in range(1, attempts + 1):
            if not await self.ensure_page_alive():
                await self._emit_status("Browser is not available for tax lookup.")
                return None

            await self._emit_status(f"Opening tax record at {direct_url}...")
            if not await self._open_tax_page(direct_url):
                if attempt < attempts:
                    await self._emit_status("Retrying tax portal with a fresh browser tab...")
                    continue
                return None

            try:
                record = await self._scrape_open_tax_page(
                    self.page,
                    apn=apn,
                    owner_name=owner_name,
                    search_type=search_type,
                    search_value=search_value,
                )
                if record:
                    return record
            except Exception as exc:
                logger.warning("Tax portal scrape failed on attempt %d: %s", attempt, exc)
                if attempt < attempts and "closed" in str(exc).lower():
                    await self._emit_status("Browser tab closed during tax lookup — retrying...")
                    continue
                return None
        return None

    async def fetch_tax_record(
        self,
        county: str,
        apn: str,
        owner_name: Optional[str] = None,
        portal_url: Optional[str] = None,
        query_type: Optional[QueryType] = None,
        query_value: Optional[str] = None,
    ) -> Optional[TaxRecord]:
        original_page = self.page
        tax_page: Page | None = None
        search_type = query_type or QueryType.PARCEL
        search_value = query_value or apn

        if not await self.ensure_browser_ready():
            await self._emit_status("Browser is not available for tax lookup.")
            return None

        # Pick the best direct URL per county (county-taxes.net for Miami-Dade etc.)
        direct_url: Optional[str] = None
        if portal_url:
            direct_url = portal_url
        elif apn:
            direct_url = resolve_florida_tax_url(county, apn)

        try:
            # ── Strategy 1: Known FL tax site — navigate, wait, search if needed ──────
            if direct_url and _is_florida_tax_url(direct_url):
                record = await self._open_and_scrape_florida_tax_portal(
                    direct_url,
                    apn=apn,
                    owner_name=owner_name,
                    search_type=search_type,
                    search_value=search_value,
                )
                if record:
                    return record

                if _is_county_taxes_com(direct_url):
                    await self._emit_status("Could not load county tax portal.")
                    return None

                await self._emit_status("Could not open tax portal — trying fallbacks.")

            # ── Strategy 2: Non-FL-tax portal URL (custom county site) ────────────────
            if direct_url and not _is_florida_tax_url(direct_url):
                await self._emit_status(f"Opening county tax portal at {direct_url}...")
                if not await self._open_tax_page(direct_url):
                    await self._emit_status("Could not open county tax collector portal.")
                    return None
                tax_page = self.page
                if await self._search_tax_portal(search_type, search_value):
                    tax_page = self.page
                scraped = await self._scrape_tax_page(tax_page)
                record = tax_record_from_florida_data(scraped, apn=apn, owner_name=owner_name)
                if _has_usable_tax_data(record, scraped):
                    await self._emit_status("Saved tax bill details from county tax collector.")
                    return record
                await self._emit_status("Could not extract tax data from the county portal.")
                return None

            # ── Strategy 3: floridapa.com assessor detail tax link (not Miami-Dade SPA) ─
            if not await self.ensure_page_alive():
                await self._emit_status("Browser is not available for tax lookup.")
                return None

            await self._emit_status("Looking for tax record link on Property Appraiser detail...")
            try:
                if await self._open_tax_record_from_assessor_detail(""):
                    tax_page = self.page
                    scraped = await self._scrape_tax_page(tax_page)
                    record = tax_record_from_florida_data(scraped, apn=apn, owner_name=owner_name)
                    if _has_usable_tax_data(record, scraped):
                        await self._emit_status("Saved tax bill details from county tax collector.")
                        return record
            except Exception as exc:
                logger.warning("Assessor tax link fallback failed: %s", exc)

            await self._emit_status("Could not reach county tax collector site.")
            return None

        finally:
            if tax_page and tax_page != original_page:
                try:
                    await tax_page.close()
                except Exception:
                    pass
                if await self.ensure_page_alive():
                    if self.page != original_page and self._page_is_alive(original_page):
                        self._page = original_page

    async def _search_tax_portal(self, query_type: QueryType, query_value: str) -> bool:
        notes = (self.playwright_notes or "").strip()
        if notes:
            if await apply_playwright_instructions(self, notes, query_type, query_value):
                return True
        if await execute_ai_page_search(
            self, query_type, query_value, user_instructions=notes or None
        ):
            return True
        if notes:
            return await apply_playwright_instructions(self, notes, query_type, query_value)
        return False

    async def _get_county_taxes_frame(self, page: Page):
        for sel in ["iframe[src*='iframe-taxsys']", "iframe[name*='iframe-']", "iframe"]:
            try:
                el = await page.query_selector(sel)
                if el:
                    cf = await el.content_frame()
                    if cf:
                        return cf
            except Exception:
                pass
        for f in page.frames:
            if f != page.main_frame and ("taxsys" in f.url or "govhub" in f.url or "bills" in f.url):
                return f
        return page.main_frame

    async def _evaluate_county_taxes_ready(self, frame, bill_details: bool = False) -> dict:
        script = COUNTY_TAXES_BILL_DETAILS_READY_JS if bill_details else COUNTY_TAXES_CONTENT_READY_JS
        try:
            return await frame.evaluate(script)
        except Exception:
            return {"ready": False, "reason": "evaluate_error"}

    async def _wait_for_county_taxes_content_ready(
        self,
        page: Page,
        frame=None,
        timeout_seconds: int = 60,
        bill_details: bool = False,
    ) -> bool:
        """Wait until iframe content is fully loaded (not just section headers/spinners)."""
        label = "bill details" if bill_details else "tax account"
        await self._emit_status(f"Waiting for {label} data to finish loading...")
        last_reason = ""
        for attempt in range(timeout_seconds):
            active = frame or await self._get_county_taxes_frame(page)
            state = await self._evaluate_county_taxes_ready(active, bill_details=bill_details)
            if state.get("ready"):
                await self._emit_status(f"{label.title()} data fully loaded.")
                return True
            last_reason = state.get("reason") or "loading"
            if attempt % 5 == 0:
                await self._emit_status(f"Still loading {label} ({last_reason})...")
            await page.wait_for_timeout(1_000)
            frame = None
        logger.warning("Timed out waiting for county tax %s content (%s)", label, last_reason)
        return False

    async def _wait_for_county_taxes_account_page(self, page: Page, frame) -> None:
        """Wait until the Real Estate Account view has real data, not just headers."""
        for _ in range(30):
            try:
                text = (await frame.evaluate("() => document.body?.innerText || ''")).lower()
                if (
                    "real estate account" in text
                    or "account history" in text
                    or ("amount due" in text and "owner:" in text)
                ):
                    break
            except Exception:
                pass
            await page.wait_for_timeout(1_000)
        else:
            logger.warning("Timed out waiting for county tax account shell")

        await self._wait_for_county_taxes_content_ready(page, frame, timeout_seconds=60)

    async def _wait_for_account_history_rows(
        self,
        page: Page,
        frame,
        min_rows: int = 1,
        timeout_seconds: int = 45,
    ) -> list:
        """Poll until Account History annual bill rows are present."""
        for attempt in range(timeout_seconds):
            rows = await self._collect_account_history_rows(frame)
            if len(rows) >= min_rows:
                return rows
            if attempt % 5 == 0:
                await self._emit_status("Waiting for Account History bills to load...")
            await page.wait_for_timeout(1_000)
            frame = await self._get_county_taxes_frame(page)
        return []

    async def _scroll_account_history_into_view(self, frame) -> None:
        try:
            await frame.evaluate(
                """() => {
                    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    const marker = [...document.querySelectorAll('h1,h2,h3,h4,th,div,span')].find(
                        (el) => norm(el.innerText).includes('account history')
                    );
                    if (marker) {
                        marker.scrollIntoView({ behavior: 'instant', block: 'center' });
                    } else {
                        window.scrollBy(0, 700);
                    }
                }"""
            )
        except Exception as exc:
            logger.debug("Could not scroll to account history: %s", exc)

    async def _collect_account_history_rows(self, frame) -> list:
        """Return annual bill rows from Account History (newest first)."""
        rows = await frame.locator("table tbody tr").all()
        bill_rows: list = []
        for row in rows:
            try:
                text = (await row.inner_text()).lower()
            except Exception:
                continue
            if "annual bill" not in text or not re.search(r"20\d{2}", text):
                continue
            bill_rows.append(row)
        return bill_rows

    def _is_page_alive(self, page: Page | None) -> bool:
        try:
            return page is not None and not page.is_closed()
        except Exception:
            return False

    async def _close_extra_pages(self, page: Page) -> None:
        """Close popup tabs opened during PDF download without touching the main page."""
        if not self.context:
            return
        for extra in list(self.context.pages):
            if extra == page:
                continue
            try:
                if not extra.is_closed():
                    await extra.close()
            except Exception:
                pass

    async def _restore_account_summary_after_pdf_download(self, page: Page) -> None:
        """Return to Account History after a Print PDF action navigates away or opens a tab."""
        if not self._is_page_alive(page):
            return

        await self._close_extra_pages(page)

        try:
            frame = await self._get_county_taxes_frame(page)
            text = (await frame.evaluate("() => document.body?.innerText || ''")).lower()
            frame_url = (getattr(frame, "url", "") or "").lower()
            if "account history" in text and "annual bill" in text:
                return
            if "bill details" in text or "ad valorem" in text:
                await self._navigate_back_to_account_summary(page)
                return
            if ".pdf" in frame_url or len(text) < 120:
                try:
                    await page.go_back(wait_until="domcontentloaded", timeout=15_000)
                    await page.wait_for_timeout(1_500)
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("Could not inspect page after PDF download: %s", exc)

        await self._navigate_back_to_account_summary(page)

    async def _refresh_account_history_row(self, page: Page, row_index: int):
        """Re-fetch an Account History row after navigation or DOM refresh."""
        if not self._is_page_alive(page):
            return None
        frame = await self._get_county_taxes_frame(page)
        await self._scroll_account_history_into_view(frame)
        bill_rows = await self._collect_account_history_rows(frame)
        if row_index < len(bill_rows):
            return bill_rows[row_index]
        return None

    def _bill_record_from_pdf(self, bill_label: str, pdf_path: str) -> dict:
        return {
            "bill_title": bill_label,
            "bill_summary": {"bill": bill_label},
            "pdf_path": pdf_path,
            "pdf_downloaded": True,
        }

    async def _click_row_info_button(self, row) -> bool:
        """Click the info (i) icon beside the bill name (not Print PDF in Action column)."""
        try:
            await row.scroll_into_view_if_needed()
        except Exception as exc:
            if "closed" in str(exc).lower():
                return False

        try:
            bill_cell = row.locator("th").first
            if await bill_cell.count() == 0:
                bill_cell = row.locator("td").first
        except Exception as exc:
            if "closed" in str(exc).lower():
                return False
            raise

        for sel in (
            "a[href*='/bills/']",
            "a[title*='bill' i]",
            "a[title*='detail' i]",
            "a[aria-label*='info' i]",
            "button[aria-label*='info' i]",
            "a:has(svg)",
        ):
            btn = bill_cell.locator(sel).first
            try:
                if await btn.count() == 0:
                    continue
                if await btn.is_visible(timeout=800):
                    await btn.click()
                    return True
            except Exception as exc:
                if "closed" in str(exc).lower():
                    return False
                continue

        try:
            bill_links = await row.locator("a[href*='/bills/']").all()
        except Exception as exc:
            if "closed" in str(exc).lower():
                return False
            return False

        for link in bill_links:
            try:
                label = (
                    (await link.inner_text())
                    + " "
                    + (await link.get_attribute("title") or "")
                ).lower()
                if any(w in label for w in ("print", "receipt")) and "view bill" not in label:
                    continue
                if await link.is_visible(timeout=500):
                    await link.click()
                    return True
            except Exception as exc:
                if "closed" in str(exc).lower():
                    return False
                continue
        return False

    async def _wait_for_bill_details_page(self, page: Page) -> None:
        """Wait until the Bill Details screen has loaded its tables/PDF links."""
        for _ in range(20):
            frame = await self._get_county_taxes_frame(page)
            try:
                text = (await frame.evaluate("() => document.body?.innerText || ''")).lower()
                if (
                    "bill details" in text
                    or "ad valorem" in text
                    or "view bill" in text
                    or "combined taxes" in text
                ):
                    break
            except Exception:
                pass
            await page.wait_for_timeout(1_000)
        await self._wait_for_county_taxes_content_ready(
            page,
            bill_details=True,
            timeout_seconds=45,
        )

    def _tax_bill_dest_pdfs(self, bill_label: str, account_number: str = "") -> list[Path]:
        safe_label = re.sub(r"[^\w\-]+", "_", bill_label).strip("_") or "tax_bill"
        acct_part = re.sub(r"[^\w\-]+", "_", account_number or "account").strip("_")
        dest_pdfs: list[Path] = []
        for folder_key in dict.fromkeys([self.preview_run_id, acct_part]):
            if not folder_key:
                continue
            dest_dir = Path(self.screenshot_dir) / "tax_bills" / folder_key
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_pdfs.append(dest_dir / f"{safe_label}.pdf")
        return dest_pdfs

    def _write_tax_pdf(self, dest_paths: list[Path], body: bytes) -> Optional[str]:
        if not body or len(body) < 500 or body[:4] != b"%PDF":
            return None
        primary: Optional[str] = None
        for dest_pdf in dest_paths:
            dest_pdf.write_bytes(body)
            if primary is None:
                primary = str(dest_pdf.resolve())
        return primary

    def _pdf_already_saved(self, dest_paths: list[Path]) -> Optional[str]:
        for dest_pdf in dest_paths:
            if dest_pdf.exists() and dest_pdf.stat().st_size > 500:
                with dest_pdf.open("rb") as handle:
                    if handle.read(4) == b"%PDF":
                        return str(dest_pdf.resolve())
        return None

    async def _discover_tax_pdf_urls(self, page: Page, frame) -> list[str]:
        try:
            hrefs = await frame.evaluate(
                """() => {
                    const out = [];
                    document.querySelectorAll('a[href], button[data-href]').forEach((el) => {
                        const href = el.getAttribute('href') || el.getAttribute('data-href') || '';
                        const text = (el.innerText || el.getAttribute('title') || '').toLowerCase();
                        if (!href) return;
                        if (/pdf|print|download|bill/i.test(href) || /view bill|print/i.test(text)) {
                            out.push(href);
                        }
                    });
                    return [...new Set(out)];
                }"""
            )
        except Exception:
            hrefs = []
        urls: list[str] = []
        base = getattr(frame, "url", None) or page.url
        for href in hrefs or []:
            if not href or href in ("#", "javascript:void(0)"):
                continue
            urls.append(href if href.startswith("http") else urljoin(base, href))
        frame_url = getattr(frame, "url", "") or ""
        bill_match = re.search(r"/bills/([0-9a-f-]{36})", frame_url, re.I)
        if bill_match:
            bill_id = bill_match.group(1)
            parsed = urlparse(frame_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            urls.extend([
                f"{origin}/api/bills/{bill_id}/pdf",
                f"{origin}/bills/{bill_id}/pdf",
                f"{origin}/api/bills/{bill_id}/print",
                f"{origin}/bills/{bill_id}/print.pdf",
            ])
        return list(dict.fromkeys(urls))

    async def _wait_for_tax_pdf_capture(
        self,
        page: Page,
        frame,
        dest_paths: list[Path],
        captured: list[bytes],
        timeout_seconds: int = 45,
    ) -> Optional[str]:
        for _ in range(timeout_seconds):
            if captured:
                saved = self._write_tax_pdf(dest_paths, captured[-1])
                if saved:
                    return saved
            existing = self._pdf_already_saved(dest_paths)
            if existing:
                return existing
            try:
                text = (await frame.evaluate("() => document.body?.innerText || ''")).lower()
                if "downloading" not in text:
                    existing = self._pdf_already_saved(dest_paths)
                    if existing:
                        return existing
            except Exception:
                pass
            await page.wait_for_timeout(1_000)
        if captured:
            return self._write_tax_pdf(dest_paths, captured[-1])
        return self._pdf_already_saved(dest_paths)

    async def _attach_pdf_response_listener(self, page: Page, captured: list[bytes]) -> Callable:
        async def _handle_response(response) -> None:
            try:
                url = response.url.lower()
                content_type = (response.headers.get("content-type") or "").lower()
                if not (
                    "pdf" in content_type
                    or url.endswith(".pdf")
                    or "/pdf" in url
                    or "print" in url
                    or "bill" in url
                ):
                    return
                body = await response.body()
                if body and len(body) > 500 and body[:4] == b"%PDF":
                    captured.append(body)
            except Exception:
                pass

        def _listener(response) -> None:
            asyncio.create_task(_handle_response(response))

        page.on("response", _listener)
        return _listener

    async def _click_and_capture_tax_pdf(
        self,
        page: Page,
        frame,
        link,
        dest_paths: list[Path],
        label: str,
    ) -> Optional[str]:
        captured: list[bytes] = []
        listener = await self._attach_pdf_response_listener(page, captured)
        try:
            await self._emit_status(f"Downloading official tax PDF for {label}...")
            try:
                async with page.expect_download(timeout=25_000) as dl_info:
                    await link.click()
                download = await dl_info.value
                await download.save_as(str(dest_paths[0]))
                saved = self._pdf_already_saved(dest_paths)
                if saved:
                    for dest_pdf in dest_paths[1:]:
                        dest_pdf.write_bytes(Path(saved).read_bytes())
                    return saved
            except Exception as exc:
                logger.debug("expect_download failed for %s: %s", label, exc)

            try:
                await link.click()
            except Exception:
                pass

            saved = await self._wait_for_tax_pdf_capture(page, frame, dest_paths, captured, timeout_seconds=45)
            if saved:
                return saved

            try:
                async with self.context.expect_page(timeout=12_000) as page_info:
                    await link.click()
                popup = await page_info.value
                await popup.wait_for_load_state("domcontentloaded", timeout=12_000)
                popup_url = popup.url
                if ".pdf" in popup_url.lower() or "/pdf" in popup_url.lower():
                    resp = await self.context.request.get(popup_url)
                    if resp.ok:
                        saved = self._write_tax_pdf(dest_paths, await resp.body())
                        await popup.close()
                        if saved:
                            return saved
                await popup.close()
            except Exception as exc:
                logger.debug("PDF popup download failed for %s: %s", label, exc)

            href = await link.get_attribute("href")
            if href and href not in ("#", "javascript:void(0)"):
                base = getattr(frame, "url", None) or page.url
                full_url = href if href.startswith("http") else urljoin(base, href)
                resp = await self.context.request.get(full_url)
                if resp.ok:
                    saved = self._write_tax_pdf(dest_paths, await resp.body())
                    if saved:
                        return saved
        finally:
            try:
                page.remove_listener("response", listener)
            except Exception:
                pass
        return None

    async def _download_row_print_pdf(
        self,
        page: Page,
        row,
        bill_label: str,
        account_number: str = "",
    ) -> Optional[str]:
        """Download the official bill PDF from Account History Print PDF / print icon."""
        frame = await self._get_county_taxes_frame(page)
        dest_paths = self._tax_bill_dest_pdfs(bill_label, account_number)
        action_cell = row.locator("td").last
        search_roots = [action_cell, row]
        selectors = (
            "a:has-text('Print PDF')",
            "a:has-text('Print (PDF)')",
            "button:has-text('Print PDF')",
            "a[href*='print']",
            "a[href*='.pdf']",
            "a[title*='print' i]",
            "button[title*='print' i]",
            "a[aria-label*='print' i]",
        )
        for root in search_roots:
            for sel in selectors:
                link = root.locator(sel).first
                try:
                    if await link.count() == 0:
                        continue
                    if not await link.is_visible(timeout=1_500):
                        continue
                except Exception:
                    continue

                href = await link.get_attribute("href")
                if href and href not in ("#", "javascript:void(0)"):
                    base = getattr(frame, "url", None) or page.url
                    full_url = href if href.startswith("http") else urljoin(base, href)
                    try:
                        resp = await self.context.request.get(full_url)
                        if resp.ok:
                            saved = self._write_tax_pdf(dest_paths, await resp.body())
                            if saved:
                                return saved
                    except Exception as exc:
                        logger.debug("Direct row PDF fetch failed for %s: %s", bill_label, exc)

                saved = await self._click_and_capture_tax_pdf(page, frame, link, dest_paths, bill_label)
                if saved:
                    await self._restore_account_summary_after_pdf_download(page)
                    return saved
        return None

    async def _download_bill_pdf(
        self,
        page: Page,
        bill_label: str,
        account_number: str = "",
    ) -> Optional[str]:
        """Download the official bill PDF from Bill Details (print icon / View Bill PDF)."""
        frame = await self._get_county_taxes_frame(page)
        await self._wait_for_bill_details_page(page)
        dest_paths = self._tax_bill_dest_pdfs(bill_label, account_number)

        selectors = (
            "a:has-text('View Bill (PDF)')",
            "a:has-text('View Bill')",
            "a:has-text('Print (PDF)')",
            "a:has-text('Print PDF')",
            "a[title*='Print' i]",
            "button[title*='Print' i]",
            "a[aria-label*='Print' i]",
            "button[aria-label*='Print' i]",
            "a[href*='.pdf']",
            "a[href*='/pdf']",
            "a[href*='print']",
        )
        for sel in selectors:
            link = frame.locator(sel).first
            if await link.count() == 0:
                continue
            try:
                if not await link.is_visible(timeout=2_000):
                    continue
            except Exception:
                continue
            saved = await self._click_and_capture_tax_pdf(page, frame, link, dest_paths, bill_label)
            if saved:
                return saved

        for pdf_url in await self._discover_tax_pdf_urls(page, frame):
            try:
                resp = await self.context.request.get(pdf_url)
                if resp.ok:
                    saved = self._write_tax_pdf(dest_paths, await resp.body())
                    if saved:
                        return saved
            except Exception as exc:
                logger.debug("Direct tax PDF fetch failed for %s: %s", pdf_url, exc)

        return None

    async def _navigate_back_to_account_summary(self, page: Page) -> None:
        """Return from a bill detail page to the Account Summary view."""
        frame = await self._get_county_taxes_frame(page)
        for link_text in ("Account Summary", "Real Estate Account"):
            link = frame.locator("a").filter(has_text=link_text).first
            if await link.count() > 0:
                try:
                    await link.click()
                    break
                except Exception:
                    pass

        for _ in range(20):
            await page.wait_for_timeout(1_000)
            frame = await self._get_county_taxes_frame(page)
            try:
                text = (await frame.evaluate("() => document.body?.innerText || ''")).lower()
                if "account history" in text:
                    if await self._wait_for_county_taxes_content_ready(page, frame, timeout_seconds=30):
                        await self._scroll_account_history_into_view(frame)
                        return
            except Exception:
                pass

    async def _scrape_county_taxes_net(self, page: Page) -> dict:
        """Scrape account summary and the last two bill summaries (with full detailed breakdown)
        from county-taxes.net / county-taxes.com (Miami-Dade, etc.).
        """
        await self._emit_status("Extracting property tax account details...")
        current_frame = await self._get_county_taxes_frame(page)
        await self._wait_for_county_taxes_account_page(page, current_frame)
        current_frame = await self._get_county_taxes_frame(page)
        await self._scroll_account_history_into_view(current_frame)
        await self._wait_for_account_history_rows(page, current_frame, min_rows=1, timeout_seconds=45)
        await page.wait_for_timeout(1_000)
        await self.save_browser_preview()

        # 1. Account Summary details
        summary_data = await current_frame.evaluate("""() => {
            const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
            const bodyText = norm(document.body?.innerText || '');
            const res = {
                account_number: '',
                owner: '',
                situs: '',
                exemptions_summary: '',
                amount_due_message: '',
                last_payment: '',
                amount_due: 0.0,
                account_history: []
            };
            
            // Account number
            const acctM = bodyText.match(/Real Estate Account #([\\d-]+)/i) || bodyText.match(/Account #([\\d-]+)/i);
            if (acctM) res.account_number = acctM[1];

            // Owner
            const ownerM = bodyText.match(/Owner:\\s*([^:]+?)\\s*Situs:/i) || bodyText.match(/Owner:\\s*([^\\n]+?)(?:\\s*Situs:|\\s*Parcel details|\\s*Enroll)/i);
            if (ownerM) res.owner = norm(ownerM[1]);

            // Situs
            const situsM = bodyText.match(/Situs:\\s*([^:]+?)\\s*(?:Parcel details|Property Appraiser|Enroll)/i);
            if (situsM) res.situs = norm(situsM[1]);

            // Exemptions summary
            if (bodyText.includes('Homestead Exemption')) res.exemptions_summary = 'Homestead Exemption';

            // Amount Due
            const dueM = bodyText.match(/Amount Due\\s+([^\\n]+?(?:paid in full|nothing due|due at this time)[^\\n]*?\\.)/i);
            if (dueM) res.amount_due_message = norm(dueM[1]);
            
            // Amount due value if any
            const dueValM = bodyText.match(/Amount Due[\\s\\S]*?\\$([\\d,]+\\.\\d{2})/i);
            if (dueValM && !bodyText.toLowerCase().includes('paid in full')) {
                res.amount_due = parseFloat(dueValM[1].replace(/,/g, '')) || 0.0;
            }

            // Last Payment
            const payM = bodyText.match(/payment was made on\\s+([\\d/]+\\s+for\\s+\\$[\\d,.]+)/i);
            if (payM) res.last_payment = norm(payM[1]);

            // Account History table
            document.querySelectorAll('table').forEach(tbl => {
                const headers = [...tbl.querySelectorAll('th')].map(th => norm(th.innerText));
                if (headers.some(h => h.includes('BILL') || h.includes('AMOUNT DUE'))) {
                    const trs = [...tbl.querySelectorAll('tbody tr')];
                    trs.forEach(tr => {
                        const billCell = tr.querySelector('th') || tr.querySelector('td');
                        const billName = norm(billCell?.innerText || '');
                        const tds = [...tr.querySelectorAll('td')].map(td => norm(td.innerText));
                        if (billName && billName.toLowerCase().includes('bill') && tds.length >= 2) {
                            res.account_history.push({
                                bill: billName,
                                amount_due: tds[0] || '$0.00',
                                status: tds[1] || '',
                                date: tds[2] || '',
                                action: tds[3] || tds.slice(3).join(' ')
                            });
                        }
                    });
                }
            });
            return res;
        }""")

        await self.save_browser_preview()

        # 2. Extract Last Two Bill Summaries via the info (i) button
        async def scrape_single_bill(bill_name: str) -> dict:
            detail_frame = None
            for _ in range(30):
                await page.wait_for_timeout(1_000)
                f = await self._get_county_taxes_frame(page)
                state = await self._evaluate_county_taxes_ready(f, bill_details=True)
                if state.get("ready"):
                    detail_frame = f
                    break

            if not detail_frame:
                await self._wait_for_bill_details_page(page)
                detail_frame = await self._get_county_taxes_frame(page)

            return await detail_frame.evaluate("""() => {
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const res = {
                    bill_title: '',
                    bill_summary: {},
                    ad_valorem_taxes: { headers: [], rows: [] },
                    non_ad_valorem_assessments: { headers: [], rows: [] },
                    combined_taxes: '',
                    parcel_details: {},
                    exemptions: {},
                    legal_description: '',
                    location: {}
                };
                
                const h = document.querySelector('h1, h2, h3');
                if (h) res.bill_title = norm(h.innerText);

                const bodyText = norm(document.body?.innerText || '');
                const combMatch = bodyText.match(/Combined taxes and assessments:?\\s*(\\$?[\\d,]+\\.\\d{2})/i);
                if (combMatch) res.combined_taxes = combMatch[1];

                // Parse tables
                document.querySelectorAll('table').forEach(tbl => {
                    const headers = [...tbl.querySelectorAll('th')].map(th => norm(th.innerText)).filter(Boolean);
                    const rows = [...tbl.querySelectorAll('tbody tr')].map(tr => 
                        [...tr.querySelectorAll('td, th')].map(td => norm(td.innerText))
                    ).filter(r => r.length > 0);
                    
                    const headerStr = headers.join(' ').toLowerCase();
                    if (headerStr.includes('bill') && headerStr.includes('escrow')) {
                        if (rows.length > 0) {
                            res.bill_summary = {
                                bill: rows[0][0] || '',
                                escrow_code: rows[0][1] || '',
                                millage_code: rows[0][2] || '',
                                amount_due: rows[0][3] || '',
                                status: rows[0][4] || ''
                            };
                        }
                    } else if (headerStr.includes('taxing authority') || headerStr.includes('millage')) {
                        res.ad_valorem_taxes = {
                            headers: ['TAXING AUTHORITY', 'MILLAGE', 'ASSESSED', 'EXEMPTION', 'TAXABLE', 'TAX'],
                            rows: rows
                        };
                    } else if (headerStr.includes('levying authority') || headerStr.includes('rate')) {
                        res.non_ad_valorem_assessments = {
                            headers: ['LEVYING AUTHORITY', 'RATE', 'AMOUNT'],
                            rows: rows
                        };
                    }
                });

                // Extract Legal description
                const legMatch = bodyText.match(/LEGAL DESCRIPTION\\s+([^\\n]+?(?:View More)?(?:\\s+Range:|\\s+LOCATION|$))/i);
                if (legMatch) {
                    res.legal_description = norm(legMatch[1].replace('View More', ''));
                }
                
                // Location fields
                const rangeM = bodyText.match(/Range:\\s*([^\\s]+)/i);
                if (rangeM) res.location.range = rangeM[1];
                const twpM = bodyText.match(/Township:\\s*([^\\s]+)/i);
                if (twpM) res.location.township = twpM[1];
                const secM = bodyText.match(/Section:\\s*([^\\s]+)/i);
                if (secM) res.location.section = secM[1];
                const blkM = bodyText.match(/Block:\\s*([^\\s]+)/i);
                if (blkM) res.location.block = blkM[1];
                const useM = bodyText.match(/Use code:\\s*([^\\s]+)/i);
                if (useM) res.location.use_code = useM[1];

                // Exemptions
                const exBlock = bodyText.match(/EXEMPTIONS\\s+([\\s\\S]+?)(?:Miami-Dade|Help|Terms|$)/i);
                if (exBlock) {
                    const lines = exBlock[1].split(/[\\n\\r]+/);
                    for (let i = 0; i < lines.length; i++) {
                        const l = norm(lines[i]);
                        const m = l.match(/^(ADDL HOMESTEAD|COUNTY SR|MUNIC SR|HOMESTEAD|WIDOW|VETERAN|DISABILITY)\\s*(\\$?[\\d,]+)/i);
                        if (m) {
                            res.exemptions[m[1]] = m[2];
                        }
                    }
                }

                return res;
            }""")

        bills_scraped = []
        active_frame = await self._get_county_taxes_frame(page)
        acct_num = summary_data.get("account_number") or ""

        async def capture_current_bill_page(bill_label: str, row_pdf_path: str | None = None) -> dict:
            await self._wait_for_bill_details_page(page)
            await page.wait_for_timeout(1_500)
            await self.save_browser_preview()
            bill_data = await scrape_single_bill(bill_label)
            pdf_path = row_pdf_path if row_pdf_path and row_pdf_path.lower().endswith(".pdf") else None
            if not pdf_path:
                pdf_path = await self._download_bill_pdf(page, bill_label, acct_num)
            if pdf_path and pdf_path.lower().endswith(".pdf"):
                bill_data["pdf_path"] = pdf_path
                bill_data["pdf_downloaded"] = True
                await self._emit_status(f"Saved official tax bill PDF: {Path(pdf_path).name}")
            else:
                bill_data["pdf_downloaded"] = False
                await self._emit_status(f"Could not save official PDF for {bill_label}.")
            return bill_data

        try:
            frame_text = (await active_frame.evaluate("() => document.body?.innerText || ''")).lower()
        except Exception:
            frame_text = ""

        # Already on Bill Details (e.g. after Cloudflare or direct navigation) — capture now.
        if "ad valorem" in frame_text or "bill details" in frame_text:
            title = await active_frame.evaluate(
                "() => (document.querySelector('h1,h2,h3')?.innerText || '').trim()"
            )
            bill_label = title or "Annual Bill"
            await self._emit_status(f"Capturing bill details for {bill_label}...")
            bills_scraped.append(await capture_current_bill_page(bill_label))

        active_frame = await self._get_county_taxes_frame(page)
        await self._scroll_account_history_into_view(active_frame)
        bill_rows = await self._wait_for_account_history_rows(
            page, active_frame, min_rows=1, timeout_seconds=45
        )
        capture_count = min(ANNUAL_BILLS_TO_CAPTURE, len(bill_rows))

        if not bills_scraped:
            for idx in range(capture_count):
                if not self._is_page_alive(page):
                    logger.warning("Browser page closed before bill %d could be processed", idx + 1)
                    break

                active_frame = await self._get_county_taxes_frame(page)
                await self._scroll_account_history_into_view(active_frame)
                bill_rows = await self._collect_account_history_rows(active_frame)
                if idx >= len(bill_rows):
                    break

                target_row = bill_rows[idx]
                try:
                    row_txt = await target_row.inner_text()
                except Exception as exc:
                    logger.warning("Could not read bill row %d: %s", idx + 1, exc)
                    break
                bill_label = row_txt.splitlines()[0].strip() if row_txt else f"Bill #{idx + 1}"

                row_pdf_path = await self._download_row_print_pdf(page, target_row, bill_label, acct_num)
                if row_pdf_path:
                    await self._emit_status(
                        f"Downloaded official tax PDF from Account History: {Path(row_pdf_path).name}"
                    )

                if not self._is_page_alive(page):
                    if row_pdf_path:
                        bills_scraped.append(self._bill_record_from_pdf(bill_label, row_pdf_path))
                    break

                target_row = await self._refresh_account_history_row(page, idx)
                if target_row is None:
                    if row_pdf_path:
                        bills_scraped.append(self._bill_record_from_pdf(bill_label, row_pdf_path))
                    break

                await self._emit_status(f"Opening Bill Details for {bill_label} via info (i) button...")
                try:
                    opened = await self._click_row_info_button(target_row)
                except Exception as exc:
                    logger.warning("Info button click failed for %s: %s", bill_label, exc)
                    opened = False

                if not opened:
                    logger.warning("No info button found for bill row: %s", bill_label)
                    if row_pdf_path:
                        bills_scraped.append(self._bill_record_from_pdf(bill_label, row_pdf_path))
                    break

                try:
                    bill_data = await capture_current_bill_page(bill_label, row_pdf_path=row_pdf_path)
                    bills_scraped.append(bill_data)
                    await self._emit_status(
                        f"Captured breakdown for {bill_data.get('bill_summary', {}).get('bill') or bill_label}."
                    )
                except Exception as exc:
                    logger.warning("Bill detail capture failed for %s: %s", bill_label, exc)
                    if row_pdf_path:
                        bills_scraped.append(self._bill_record_from_pdf(bill_label, row_pdf_path))
                    if "closed" in str(exc).lower():
                        break

                if idx < capture_count - 1:
                    if not self._is_page_alive(page):
                        break
                    await self._navigate_back_to_account_summary(page)
                    await self.save_browser_preview()

        # Build combined tables for tabs
        combined_tabs = {}
        summary_tab_tables = []
        if summary_data.get("account_history"):
            summary_tab_tables.append({
                "headers": ["BILL", "AMOUNT DUE", "STATUS", "DATE", "ACTION"],
                "rows": [
                    [r.get("bill", ""), r.get("amount_due", ""), r.get("status", ""), r.get("date", ""), r.get("action", "")]
                    for r in summary_data["account_history"]
                ]
            })
        combined_tabs["Summary"] = {
            "tables": summary_tab_tables,
            "body_text": summary_data.get("amount_due_message", "")
        }

        for b in bills_scraped:
            b_name = b.get("bill_summary", {}).get("bill") or b.get("bill_title") or "Bill"
            b_tables = []
            if b.get("ad_valorem_taxes", {}).get("rows"):
                b_tables.append({
                    "headers": b["ad_valorem_taxes"]["headers"],
                    "rows": b["ad_valorem_taxes"]["rows"]
                })
            if b.get("non_ad_valorem_assessments", {}).get("rows"):
                b_tables.append({
                    "headers": b["non_ad_valorem_assessments"]["headers"],
                    "rows": b["non_ad_valorem_assessments"]["rows"]
                })
            body_parts = [
                f"Millage: {b.get('bill_summary', {}).get('millage_code')}",
                f"Combined Taxes: {b.get('combined_taxes')}",
            ]
            if b.get("legal_description"):
                body_parts.append(f"Legal: {b['legal_description']}")
            combined_tabs[b_name] = {
                "tables": b_tables,
                "body_text": " | ".join(p for p in body_parts if p and not p.endswith(": None")),
            }

        return {
            "url": page.url,
            "account_number": summary_data.get("account_number"),
            "owner": summary_data.get("owner"),
            "situs": summary_data.get("situs"),
            "exemptions_summary": summary_data.get("exemptions_summary"),
            "amount_due": summary_data.get("amount_due"),
            "amount_due_message": summary_data.get("amount_due_message"),
            "last_payment": summary_data.get("last_payment"),
            "account_history": summary_data.get("account_history"),
            "last_two_bills": bills_scraped,
            "downloaded_bills": [
                {
                    "bill": b.get("bill_summary", {}).get("bill") or b.get("bill_title") or "",
                    "pdf_path": b.get("pdf_path"),
                    "pdf_downloaded": bool(b.get("pdf_downloaded") and b.get("pdf_path")),
                }
                for b in bills_scraped
                if b.get("pdf_path") and b.get("pdf_downloaded")
            ],
            "fields": {
                "property tax account": summary_data.get("account_number"),
                "owner name": summary_data.get("owner"),
                "property address": summary_data.get("situs"),
                "amount due": str(summary_data.get("amount_due", "0.00")),
                "status": summary_data.get("amount_due_message"),
                "last payment": summary_data.get("last_payment"),
            },
            "tables": summary_tab_tables,
            "tabs": combined_tabs,
            "body_text": summary_data.get("amount_due_message", ""),
        }

    async def _scrape_tax_page(self, page: Page) -> dict:
        """Scrape a tax collector page using the right JS extractor for the site."""
        url = page.url
        if _is_county_taxes_com(url):
            return await self._scrape_county_taxes_net(page)
        # Default: floridatax.us tabs scraper
        return await self._scrape_all_tax_tabs(page)

    async def _scrape_generic_tax_page(self, page: Page) -> dict:
        if _is_county_taxes_com(page.url):
            return await self._scrape_county_taxes_net(page)
        data = await page.evaluate(FLORIDA_TAX_PAGE_JS)
        if data and (data.get("fields") or data.get("tables")):
            return {"url": page.url, "tabs": {"Summary": data}, **data}
        body_text = await page.evaluate("() => (document.body?.innerText || '').trim()")
        if len(body_text) > 200:
            return {"url": page.url, "tabs": {"Summary": {"body_text": body_text[:8000]}}, "body_text": body_text[:8000]}
        return {}

    async def _dismiss_notifications_modal(self, page: Page) -> None:
        """Close public notifications flyout / modal if open."""
        try:
            close_selectors = [
                "button[aria-label*='close' i]",
                "button:has-text('✕')",
                "button:has-text('Close')",
                ".notification-close",
                "[class*='notification'] button",
                "[class*='flyout'] button",
            ]
            for sel in close_selectors:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible(timeout=300):
                    await btn.click()
                    await page.wait_for_timeout(400)
                    break
        except Exception:
            pass

    async def _handle_county_taxes_com(
        self,
        page: Page,
        search_value: str,
        apn: str,
    ) -> None:
        """After navigating to county-taxes.net / county-taxes.com, wait for the SPA to render,
        dismiss any public notifications modal, enter parcel/folio into the search input,
        submit, and wait for results or property detail.
        """
        await self._emit_status("Waiting for county tax portal to load...")

        # True property detail indicators (do NOT use generic 'Property' or 'Tax' headers)
        REAL_DETAIL_SELECTORS = [
            ".account-summary",
            ".bill-summary",
            ".taxes-due",
            "table.bills-table",
            "[data-testid*='account-detail']",
            "button:has-text('Pay Bill')",
            "button:has-text('Add to Cart')",
            "dt:has-text('Total Amount Due')",
            "th:has-text('Total Amount Due')",
            "td:has-text('Total Amount Due')",
            "h2:has-text('Account Summary')",
            "h2:has-text('Bills')",
        ]

        SEARCH_SELECTORS = [
            "input[placeholder*='Name, Address' i]",
            "input[placeholder*='Folio' i]",
            "input[placeholder*='Account' i]",
            "input[placeholder*='Parcel' i]",
            "input[placeholder*='search' i]",
            "input[type='search']",
            "input[type='text']",
        ]

        # 1. Poll for the SPA to render (search input or true property detail)
        inp = None
        for _ in range(15):
            await page.wait_for_timeout(1_500)
            await self._dismiss_notifications_modal(page)
            await self.save_browser_preview()

            # Check if already on a real detail page
            for sel in REAL_DETAIL_SELECTORS:
                try:
                    if await page.locator(sel).count() > 0:
                        await self._emit_status("Property detail loaded on county tax portal.")
                        return
                except Exception:
                    pass

            # Check for search input
            for sel in SEARCH_SELECTORS:
                try:
                    candidate = page.locator(sel).first
                    if await candidate.count() > 0 and await candidate.is_visible(timeout=300):
                        inp = candidate
                        break
                except Exception:
                    pass
            if inp is not None:
                break

        if inp is None:
            await self._emit_status("Search input not found on county tax portal.")
            return

        # Ensure notifications modal is closed so preview is pristine (matching user expectation)
        await self._dismiss_notifications_modal(page)
        await self.save_browser_preview()

        # 2. Enter folio / parcel number into the search box
        folio = apn or search_value
        await self._emit_status(f"Entering parcel {folio} into tax search...")
        try:
            await inp.click()
            await inp.fill(folio)
            await page.wait_for_timeout(500)
            await self.save_browser_preview()
        except Exception as e:
            logger.warning("Could not fill search input: %s", e)
            return

        # 3. Submit search: click search button or press Enter
        submitted = False
        for btn_sel in [
            "button[type='submit']",
            "[aria-label*='Search' i]",
            "button:has-text('Search')",
            "form button",
        ]:
            try:
                btn = page.locator(btn_sel).first
                if await btn.count() > 0 and await btn.is_visible(timeout=300):
                    await btn.click()
                    submitted = True
                    break
            except Exception:
                pass
        if not submitted:
            await inp.press("Enter")

        await self._emit_status("Waiting for tax search results...")

        # 4. Wait for results list, "No bills", or property detail
        for _ in range(30):
            await page.wait_for_timeout(1_500)
            await self._dismiss_notifications_modal(page)
            await self.save_browser_preview()

            body_text = await page.evaluate("() => document.body?.innerText || ''")

            # Check for "No bills or accounts matched"
            if "No bills or accounts matched" in body_text:
                digits = re.sub(r"\D", "", folio)
                if digits and digits != folio:
                    await self._emit_status(f"Trying folio without dashes: {digits}...")
                    try:
                        await inp.click()
                        await inp.fill(digits)
                        await inp.press("Enter")
                        folio = digits
                        continue
                    except Exception:
                        pass
                await self._emit_status(f"No tax bills or accounts matched parcel {folio}.")
                await self.save_browser_preview()
                return

            # Check for real detail page (headers alone are not enough — wait for data).
            detail_detected = False
            for sel in REAL_DETAIL_SELECTORS:
                try:
                    if await page.locator(sel).count() > 0:
                        detail_detected = True
                        break
                except Exception:
                    pass

            try:
                frame = await self._get_county_taxes_frame(page)
                if frame != page.main_frame:
                    ftxt = await frame.evaluate("() => document.body?.innerText || ''")
                    if "account #" in ftxt.lower() or "amount due" in ftxt.lower() or "account history" in ftxt.lower():
                        detail_detected = True
            except Exception:
                pass

            if detail_detected:
                frame = await self._get_county_taxes_frame(page)
                if await self._wait_for_county_taxes_content_ready(page, frame, timeout_seconds=45):
                    await self._emit_status("Tax bill details loaded.")
                    await self.save_browser_preview()
                    return

            # Check for result links/rows to click
            for res_sel in [
                "a[href*='parcels']",
                "a[href*='accounts']",
                "a[href*='property-tax/']",
                ".result-item a",
                "[class*='result'] a",
                "table tbody tr a",
            ]:
                try:
                    link = page.locator(res_sel).first
                    if await link.count() > 0 and await link.is_visible(timeout=300):
                        href = await link.get_attribute("href") or ""
                        if "upload" not in href and "help" not in href:
                            await self._emit_status("Opening property tax account...")
                            await link.click()
                            frame = await self._get_county_taxes_frame(page)
                            if await self._wait_for_county_taxes_content_ready(page, frame, timeout_seconds=45):
                                await self._emit_status("Tax bill details loaded.")
                                await self.save_browser_preview()
                                return
                except Exception:
                    pass

        await self.save_browser_preview()

    async def _open_tax_page(self, url: str) -> bool:
        is_ct = _is_county_taxes_com(url)
        await self._emit_status(f"Opening tax bill detail at {url}...")
        if not await self.ensure_page_alive():
            logger.warning("Cannot open tax page — browser page is not available")
            return False
        try:
            # county-taxes.net / county-taxes.com is a React SPA — use a longer initial wait.
            timeout = 90_000 if is_ct else 60_000
            await self.safe_goto(url, timeout=timeout)
            await self.polite_delay(3.0 if is_ct else 2.0)
        except Exception as exc:
            logger.warning("Failed to open tax page %s: %s", url, exc)
            return False
        return True

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
        if not await self.ensure_page_alive():
            return False

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
