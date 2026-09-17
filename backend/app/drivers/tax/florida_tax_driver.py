import logging
import re
from typing import Optional
from urllib.parse import urljoin

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

# Selectors for the info (i) button in Account History action column (county-taxes.net).
BILL_INFO_BUTTON_SELECTORS = (
    "td:last-child a[href*='/bills/']",
    "td:last-child a[title*='detail' i]",
    "td:last-child a[aria-label*='info' i]",
    "td:last-child button[aria-label*='info' i]",
    "td:last-child button[title*='detail' i]",
    "td:last-child a",
    "a[href*='/bills/']",
    "button[aria-label*='info' i]",
    "a[title*='detail' i]",
)

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

        # Pick the best direct URL per county (county-taxes.net for Miami-Dade etc.)
        direct_url: Optional[str] = None
        if portal_url:
            direct_url = portal_url
        elif apn:
            direct_url = resolve_florida_tax_url(county, apn)

        try:
            # ── Strategy 1: Known FL tax site — navigate, wait, search if needed ──────
            if direct_url and _is_florida_tax_url(direct_url):
                await self._emit_status(f"Opening tax record at {direct_url}...")
                if await self._open_tax_page(direct_url):
                    tax_page = self.page

                    if _is_county_taxes_com(tax_page.url):
                        # county-taxes.net / county-taxes.com SPA: search by parcel
                        await self._handle_county_taxes_com(tax_page, search_value, apn)
                        tax_page = self.page

                    scraped = await self._scrape_tax_page(tax_page)
                    record = tax_record_from_florida_data(scraped, apn=apn, owner_name=owner_name)
                    if _has_usable_tax_data(record, scraped):
                        await self._emit_status("Saved tax bill details from county tax collector.")
                        return record

                    # Only fallback to generic AI search if NOT county-taxes.net
                    if not _is_county_taxes_com(tax_page.url):
                        await self._emit_status("Tax page opened but no usable data — trying search.")
                        if await self._search_tax_portal(search_type, search_value):
                            tax_page = self.page
                            scraped = await self._scrape_tax_page(tax_page)
                            record = tax_record_from_florida_data(scraped, apn=apn, owner_name=owner_name)
                            if _has_usable_tax_data(record, scraped):
                                await self._emit_status("Saved tax bill details from county tax collector.")
                                return record
                else:
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

            # ── Strategy 3: No direct URL — look for link on PA assessor detail ────────
            await self._emit_status("Looking for tax record link on Property Appraiser detail...")
            if await self._open_tax_record_from_assessor_detail(""):
                tax_page = self.page
                scraped = await self._scrape_tax_page(tax_page)
                record = tax_record_from_florida_data(scraped, apn=apn, owner_name=owner_name)
                if _has_usable_tax_data(record, scraped):
                    await self._emit_status("Saved tax bill details from county tax collector.")
                    return record

            await self._emit_status("Could not reach county tax collector site.")
            return None

        finally:
            if tax_page and tax_page != original_page:
                try:
                    await tax_page.close()
                except Exception:
                    pass
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

    async def _wait_for_county_taxes_account_page(self, page: Page, frame) -> None:
        """Wait until the Real Estate Account / Account History view is rendered."""
        for _ in range(25):
            try:
                text = (await frame.evaluate("() => document.body?.innerText || ''")).lower()
                if (
                    "real estate account" in text
                    or "account history" in text
                    or ("amount due" in text and "owner:" in text)
                ):
                    return
            except Exception:
                pass
            await page.wait_for_timeout(1_000)
        logger.warning("Timed out waiting for county tax account page")

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
        """Return bill rows from the Account History table (newest first)."""
        rows = await frame.locator("table tbody tr").all()
        bill_rows: list = []
        for row in rows:
            try:
                text = (await row.inner_text()).lower()
            except Exception:
                continue
            if "bill" not in text or not re.search(r"20\d{2}", text):
                continue
            bill_rows.append(row)
        return bill_rows

    async def _click_row_info_button(self, row) -> bool:
        """Click the info (i) button in an Account History row."""
        for sel in BILL_INFO_BUTTON_SELECTORS:
            try:
                btn = row.locator(sel).last
                if await btn.count() == 0:
                    continue
                if await btn.is_visible(timeout=800):
                    await btn.click()
                    return True
            except Exception:
                continue
        return False

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

        for _ in range(12):
            await page.wait_for_timeout(1_000)
            frame = await self._get_county_taxes_frame(page)
            try:
                text = (await frame.evaluate("() => document.body?.innerText || ''")).lower()
                if "account history" in text:
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
        await self._scroll_account_history_into_view(current_frame)
        await page.wait_for_timeout(1_500)
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
            for _ in range(15):
                await page.wait_for_timeout(1_000)
                f = await self._get_county_taxes_frame(page)
                try:
                    txt = await f.evaluate("() => document.body?.innerText || ''")
                    if "ad valorem" in txt.lower() or "millage" in txt.lower() or "notice of ad valorem" in txt.lower():
                        detail_frame = f
                        break
                except Exception:
                    continue
            
            if not detail_frame:
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
        await self._scroll_account_history_into_view(active_frame)
        bill_rows = await self._collect_account_history_rows(active_frame)

        for idx in range(min(2, len(bill_rows))):
            active_frame = await self._get_county_taxes_frame(page)
            await self._scroll_account_history_into_view(active_frame)
            bill_rows = await self._collect_account_history_rows(active_frame)
            if idx >= len(bill_rows):
                break

            target_row = bill_rows[idx]
            row_txt = await target_row.inner_text()
            bill_label = row_txt.splitlines()[0].strip() if row_txt else f"Bill #{idx + 1}"

            await self._emit_status(f"Opening details for {bill_label} via info button...")
            if not await self._click_row_info_button(target_row):
                logger.warning("No info button found for bill row: %s", bill_label)
                break

            await page.wait_for_timeout(3_000)
            await self.save_browser_preview()

            bill_data = await scrape_single_bill(bill_label)
            bills_scraped.append(bill_data)
            await self._emit_status(
                f"Captured breakdown for {bill_data.get('bill_summary', {}).get('bill') or bill_label}."
            )

            if idx < 1:
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
        for _ in range(12):
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

            # Check for real detail page
            for sel in REAL_DETAIL_SELECTORS:
                try:
                    if await page.locator(sel).count() > 0:
                        await self._emit_status("Tax bill details loaded.")
                        await self.save_browser_preview()
                        return
                except Exception:
                    pass

            try:
                frame = await self._get_county_taxes_frame(page)
                if frame != page.main_frame:
                    ftxt = await frame.evaluate("() => document.body?.innerText || ''")
                    if "account #" in ftxt.lower() or "amount due" in ftxt.lower() or "account history" in ftxt.lower():
                        await self._emit_status("Tax bill details loaded.")
                        await self.save_browser_preview()
                        return
            except Exception:
                pass

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
                            await page.wait_for_timeout(3_000)
                            await self.save_browser_preview()
                            return
                except Exception:
                    pass

        await self.save_browser_preview()

    async def _open_tax_page(self, url: str) -> bool:
        is_ct = _is_county_taxes_com(url)
        await self._emit_status(f"Opening tax bill detail at {url}...")
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
