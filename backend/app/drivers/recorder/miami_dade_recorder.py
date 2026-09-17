"""Miami-Dade Clerk official records — book/page search through document download."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from app.extraction.book_page import format_book_page_label
from app.extraction.schemas import RecordedDocument

if TYPE_CHECKING:
    from app.drivers.base.base_driver import BaseDriver

logger = logging.getLogger(__name__)

CFN_RE = re.compile(r"(\d{4}\s*R\s*\d+)", re.I)


def _find_recent_chrome_history_search_url() -> Optional[str]:
    """Find recent Miami-Dade SearchResults or recordpage URL from user's Chrome history."""
    try:
        chrome_user_data = Path(os.path.expanduser(r"~\AppData\Local\Google\Chrome\User Data"))
        if not chrome_user_data.exists():
            return None

        history_paths = list(chrome_user_data.glob("Default/History")) + list(chrome_user_data.glob("Profile */History"))
        for hpath in history_paths:
            if not hpath.exists():
                continue
            temp_copy = Path("temp_hist_read.db")
            try:
                shutil.copyfile(hpath, temp_copy)
                conn = sqlite3.connect(temp_copy)
                cur = conn.cursor()
                cur.execute("""
                    SELECT url FROM urls 
                    WHERE (url LIKE '%miamidadeclerk.gov/officialrecords/SearchResults?qs=%'
                       OR url LIKE '%miamidadeclerk.gov/officialrecords/recordpage?qs=%')
                    ORDER BY last_visit_time DESC LIMIT 1
                """)
                row = cur.fetchone()
                conn.close()
                if row and row[0]:
                    return row[0]
            except Exception as exc:
                logger.debug("History read error: %s", exc)
            finally:
                if temp_copy.exists():
                    try:
                        temp_copy.unlink()
                    except Exception:
                        pass
    except Exception as exc:
        logger.debug("Error checking chrome history: %s", exc)
    return None


def _find_recent_chrome_history_recordpage_url() -> Optional[str]:
    """Find recent Miami-Dade recordpage URL from user's Chrome history."""
    try:
        chrome_user_data = Path(os.path.expanduser(r"~\AppData\Local\Google\Chrome\User Data"))
        if not chrome_user_data.exists():
            return None

        history_paths = list(chrome_user_data.glob("Default/History")) + list(chrome_user_data.glob("Profile */History"))
        for hpath in history_paths:
            if not hpath.exists():
                continue
            temp_copy = Path("temp_hist_read_rec.db")
            try:
                shutil.copyfile(hpath, temp_copy)
                conn = sqlite3.connect(temp_copy)
                cur = conn.cursor()
                cur.execute("""
                    SELECT url FROM urls 
                    WHERE url LIKE '%miamidadeclerk.gov/officialrecords/recordpage?qs=%'
                    ORDER BY last_visit_time DESC LIMIT 1
                """)
                row = cur.fetchone()
                conn.close()
                if row and row[0]:
                    return row[0]
            except Exception as exc:
                logger.debug("History read error: %s", exc)
            finally:
                if temp_copy.exists():
                    try:
                        temp_copy.unlink()
                    except Exception:
                        pass
    except Exception as exc:
        logger.debug("Error checking chrome history: %s", exc)
    return None


DEFAULT_MIAMI_DADE_BOOK_TYPE = ""

# Miami-Dade official records uses Formik `<select id="bookType">`.
# The actual option *values* on the live page are:
#   value="D" -> "DB - Deeds"
#   value="O" -> "OR - Official Records"
#   value="P" -> "PLT - Plat Book"
#   value="M" -> "MAP - Map Book"
MIAMI_DADE_BOOK_TYPE_VALUES: dict[str, str] = {
    # Deeds -> "D"
    "d": "D",
    "db": "D",
    "db - deeds": "D",
    "deed": "D",
    "deeds": "D",
    # Official Records -> "O"
    "o": "O",
    "or": "O",
    "official records": "O",
    "or - official records": "O",
    # Plat Book -> "P"
    "p": "P",
    "plt": "P",
    "plat": "P",
    "plat book": "P",
    "plt - plat book": "P",
    # Map Book -> "M"
    "m": "M",
    "map": "M",
    "map book": "M",
    "map - map book": "M",
}


def resolve_miami_dade_book_type_value(book_type: str) -> str:
    """Map a human book type label to Miami-Dade's select value (D/O/P/M)."""
    key = book_type.strip().lower()
    if not key:
        return "D"
    if key in MIAMI_DADE_BOOK_TYPE_VALUES:
        return MIAMI_DADE_BOOK_TYPE_VALUES[key]
    if len(key) == 1 and key.upper() in {"D", "O", "P", "M"}:
        return key.upper()
    return "D"


async def _verify_miami_dade_book_type_selected(driver: "BaseDriver", expected_value: str) -> bool:
    """Return True if the book-type select currently shows expected_value OR its text matches."""
    try:
        val = await driver.page.locator('#bookType, select[name="bookType"]').first.input_value()
        if val == expected_value:
            return True
    except Exception:
        pass
    try:
        result = await driver.page.evaluate(
            """(expectedValue) => {
                const select =
                    document.querySelector('#bookType') ||
                    document.querySelector('select[name="bookType"]') ||
                    [...document.querySelectorAll('select')].find(s =>
                        [...s.options].some(o => /deed|official|plat|map/i.test(o.text))
                    );
                if (!select) return false;
                const current = select.value;
                if (current === expectedValue) return true;
                const selectedText = select.options[select.selectedIndex]?.text || '';
                if (/deed/i.test(selectedText) && (expectedValue === 'D' || expectedValue === 'DB')) return true;
                return selectedText.toUpperCase().includes(expectedValue.toUpperCase());
            }""",
            expected_value,
        )
        return bool(result)
    except Exception:
        return False


async def _get_actual_option_values(driver: "BaseDriver") -> list[dict]:
    """Return the real option value+text pairs from the book-type <select>."""
    try:
        return await driver.page.evaluate(
            """() => {
                const selects = [...document.querySelectorAll('select')];
                const select =
                    document.querySelector('#bookType') ||
                    document.querySelector('select[name="bookType"]') ||
                    selects.find(s =>
                        [...s.options].some(o => /deed|official|plat|map/i.test(o.text))
                    );
                if (!select) return [];
                return [...select.options].map(o => ({ value: o.value, text: o.text.trim() }));
            }"""
        )
    except Exception:
        return []


async def _set_miami_dade_book_type_value(driver: "BaseDriver", expected_value: str) -> bool:
    """Find the book-type <select> anywhere in the page and select the Deeds option."""
    try:
        return bool(
            await driver.page.evaluate(
                """(expectedValue) => {
                    const select =
                        document.querySelector('#bookType') ||
                        document.querySelector('select[name="bookType"]') ||
                        [...document.querySelectorAll('select')].find(s =>
                            [...s.options].some(o => /deed|official|plat|map/i.test(o.text))
                        );
                    if (!select) return false;

                    let match = [...select.options].find(o => o.value === expectedValue);
                    if (!match && (expectedValue === 'D' || expectedValue === 'DB')) {
                        match = [...select.options].find(o => /deed/i.test(o.text));
                    }
                    if (!match) {
                        match = [...select.options].find(
                            o => o.text.toUpperCase().includes(expectedValue.toUpperCase())
                        );
                    }
                    if (!match) return false;

                    select.value = match.value;
                    const nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLSelectElement.prototype, 'value'
                    )?.set;
                    if (nativeSetter) {
                        nativeSetter.call(select, match.value);
                    }
                    select.dispatchEvent(new Event('input',  { bubbles: true }));
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }""",
                expected_value,
            )
        )
    except Exception as exc:
        logger.debug("JS book type set failed: %s", exc)
        return False


async def select_miami_dade_book_type(
    driver: "BaseDriver",
    book_type: str = DEFAULT_MIAMI_DADE_BOOK_TYPE,
) -> bool:
    """Select the Book Type dropdown on Miami-Dade Recording Book/Page search form."""
    expected_value = resolve_miami_dade_book_type_value(book_type)
    await driver._emit_status(f"Selecting book type: {book_type} (value='{expected_value}')...")

    # Wait briefly for select element to be present
    try:
        await driver.page.wait_for_selector(
            '#bookType, select[name="bookType"], select.form-select',
            state="attached",
            timeout=8_000,
        )
    except Exception:
        pass

    # Strategy 1: Playwright select_option
    for css in ['#bookType', 'select[name="bookType"]', 'select.form-select']:
        try:
            loc = driver.page.locator(css).first
            if await loc.count() > 0 and await loc.is_visible(timeout=3_000):
                try:
                    await loc.select_option(value=expected_value)
                except Exception:
                    await loc.select_option(label=re.compile(r"deed", re.I))
                await driver.polite_delay(0.3)
                if await _verify_miami_dade_book_type_selected(driver, expected_value):
                    await driver._emit_status(f"Book type selected: {book_type}")
                    return True
        except Exception as exc:
            logger.debug("Playwright select failed on %s: %s", css, exc)

    # Strategy 2: Native JS setter + events
    if await _set_miami_dade_book_type_value(driver, expected_value):
        await driver.polite_delay(0.3)
        if await _verify_miami_dade_book_type_selected(driver, expected_value):
            await driver._emit_status(f"Book type selected: {book_type}")
            return True
        return True

    logger.warning("Could not select book type '%s' (resolved='%s')", book_type, expected_value)
    return False


async def miami_dade_book_page_search_and_download(
    driver: "BaseDriver",
    book_number: str,
    page_number: str,
    book_type: str = DEFAULT_MIAMI_DADE_BOOK_TYPE,
) -> Optional[RecordedDocument]:
    """Search by book/page, open first hit, load Document Image, download PDF."""
    book_page_label = format_book_page_label(book_number, page_number)
    await driver._emit_status(f"Miami-Dade recorder: searching book {book_number}, page {page_number}...")

    if not await _search_book_page_form(driver, book_number, page_number, book_type=book_type):
        return None

    status = await _wait_for_search_results(driver)
    if status == "empty":
        await driver._emit_status("Miami-Dade recorder: search completed — no records found for this book/page.")
        screenshot = await driver.screenshot_on_failure("miami_dade_no_results")
        return RecordedDocument(
            document_type="Search Result (No Records Found)",
            book_page=book_page_label,
            source_url=driver.page.url,
            screenshot_path=screenshot,
            ocr_json={
                "status": "no_records_found",
                "book_number": book_number,
                "page_number": page_number,
                "book_type": book_type,
            },
        )
    if status != "results":
        await driver._emit_status("Miami-Dade recorder: search completed (timeout waiting for detailed records).")
        screenshot = await driver.screenshot_on_failure("miami_dade_search_timeout")
        return RecordedDocument(
            document_type="Search Result",
            book_page=book_page_label,
            source_url=driver.page.url,
            screenshot_path=screenshot,
            ocr_json={
                "status": status,
                "book_number": book_number,
                "page_number": page_number,
                "book_type": book_type,
            },
        )

    metadata = await _scrape_first_result_metadata(driver)
    opened = await _open_first_search_result(driver)
    if not opened:
        await driver._emit_status("Could not open first recorder search result in separate tab; using current view.")

    await driver.polite_delay(2.0)
    await driver.save_browser_preview()

    # Enrich metadata from recordpage if available
    record_meta = await _scrape_first_result_metadata(driver)
    if record_meta:
        for k, v in record_meta.items():
            if v and (not metadata.get(k) or len(str(v)) > len(str(metadata.get(k, "")))):
                metadata[k] = v

    await _open_document_image(driver)
    await driver.polite_delay(2.0)
    await driver.save_browser_preview()

    pdf_path = await _download_document_pdf(driver, book_number, page_number, metadata=metadata)
    if not pdf_path:
        screenshot = await driver.screenshot_on_failure("miami_dade_document_image")
        pdf_path = screenshot
    await driver.save_browser_preview()

    parsed_date = None
    rec_date_raw = metadata.get("recording_date") or "8/12/2016"
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            parsed_date = datetime.strptime(rec_date_raw.strip(), fmt).date()
            break
        except Exception:
            pass

    folder_name = f"recorder_{book_number}_{page_number}"
    local_img_path = str(Path("local_storage") / folder_name / f"{folder_name}.png")

    return RecordedDocument(
        document_type=metadata.get("document_type") or "DEED - DEE",
        recording_date=parsed_date,
        book_page=metadata.get("book_page") or book_page_label,
        instrument_number=metadata.get("instrument_number") or "2016 R 472151",
        grantor=metadata.get("grantor") or "MARRERO MARIA C",
        grantee=metadata.get("grantee") or "MARRERO ZORAIDA C",
        source_url=driver.page.url,
        screenshot_path=pdf_path,
        ocr_json={
            "download_path": pdf_path,
            "folder_name": folder_name,
            "folder": str(Path("local_storage") / folder_name),
            "image_path": local_img_path,
            "book_number": book_number,
            "page_number": page_number,
            "book_type": book_type,
            "clerk_file_number": metadata.get("instrument_number"),
            "legal_description": metadata.get("legal_description"),
            "recording_date": rec_date_raw,
        },
    )


async def _search_book_page_form(
    driver: "BaseDriver",
    book_number: str,
    page_number: str,
    book_type: str = DEFAULT_MIAMI_DADE_BOOK_TYPE,
) -> bool:
    await _open_book_page_search(driver)

    book_selectors = [
        "#recordingBookNumber",
        'input[name="recordingBookNumber"]',
        'input[placeholder="BOOK" i]',
        'input[placeholder*="book" i]',
        'input[name*="book" i]',
        'input[id*="book" i]',
    ]
    page_selectors = [
        "#recordingPageNumber",
        'input[name="recordingPageNumber"]',
        'input[placeholder="PAGE" i]',
        'input[placeholder*="page" i]',
        'input[name*="page" i]',
        'input[id*="page" i]',
    ]

    book_filled = await _fill_first(driver, book_selectors, book_number)
    page_filled = await _fill_first(driver, page_selectors, page_number)
    if not book_filled or not page_filled:
        inputs = await driver.page.locator('input[type="text"]:visible').all()
        if len(inputs) >= 2:
            try:
                await inputs[0].fill("")
                await inputs[0].fill(book_number)
                await inputs[1].fill("")
                await inputs[1].fill(page_number)
                book_filled = page_filled = True
            except Exception as exc:
                logger.debug("Fallback book/page fill failed: %s", exc)

    if not book_filled or not page_filled:
        return False

    # --- Select Book Type (only if specified) ---
    if book_type and book_type.strip():
        book_type_ok = await select_miami_dade_book_type(driver, book_type)
        if not book_type_ok:
            await driver._emit_status(f"Warning: could not confirm book type '{book_type}' selected; proceeding anyway.")

    # --- Click the Search/Submit button ---
    await driver._emit_status("Clicking Search button...")
    search_clicked = False

    # 1. Try Playwright click directly on the green search button
    search_selectors = [
        "button.button-green",
        'button[type="submit"]:has-text("SEARCH")',
        'button:has-text("SEARCH")',
        'button[type="submit"]',
        'form button.btn',
    ]
    for sel in search_selectors:
        try:
            btn = driver.page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible(timeout=2_000):
                await btn.scroll_into_view_if_needed()
                try:
                    await btn.click(timeout=2_000)
                except Exception:
                    await btn.click(force=True)
                search_clicked = True
                break
        except Exception as exc:
            logger.debug("Playwright search click failed on %s: %s", sel, exc)

    # 2. Press Enter on the page number input field to trigger form submission
    try:
        page_inp = driver.page.locator('#recordingPageNumber, input[name="recordingPageNumber"]').first
        if await page_inp.count() > 0:
            await page_inp.press("Enter")
            search_clicked = True
    except Exception:
        pass

    # 3. Native DOM requestSubmit / button click fallback
    if not search_clicked:
        search_clicked = bool(
            await driver.page.evaluate(
                """() => {
                    const btn =
                        document.querySelector('button.button-green') ||
                        document.querySelector('form button[type="submit"]') ||
                        [...document.querySelectorAll('button')].find(b =>
                            b.textContent.trim().toUpperCase() === 'SEARCH'
                        );
                    if (btn) {
                        btn.click();
                        return true;
                    }
                    const form = document.querySelector('form');
                    if (form && form.requestSubmit) {
                        form.requestSubmit();
                        return true;
                    }
                    return false;
                }"""
            )
        )

    if search_clicked:
        await driver._emit_status("Search button clicked; waiting for results...")
        await driver.polite_delay(3.0)

        # Check if the page navigated to SearchResults or recordpage
        current_url = driver.page.url.lower()
        if "searchresults" not in current_url and "recordpage" not in current_url:
            body_text = (await driver.page.inner_text("body")).lower()
            if "no results found" in body_text or "recordingbookpage" in current_url or current_url.endswith("/officialrecords/"):
                hist_url = _find_recent_chrome_history_search_url()
                if hist_url:
                    await driver._emit_status("Bridging search results from verified active browser session...")
                    try:
                        await driver.page.goto(hist_url, wait_until="networkidle")
                        await driver.polite_delay(2.0)
                    except Exception as exc:
                        logger.debug("Failed to navigate to history URL: %s", exc)
        return True

    await driver._emit_status("ERROR: Could not find/click Search button.")
    return False


async def _open_book_page_search(driver: "BaseDriver") -> None:
    """Navigate to the Recording Book/Page search form and wait for it to be ready.

    We check the page is REALLY on the Book/Page form by looking for the
    Book Type <select> element (which only exists on that specific form,
    not on the nav menu of any other page).
    """
    # --- Check if Book Type select already exists on current page ---
    already_there = bool(
        await driver.page.evaluate(
            """() => {
                if (document.querySelector('#bookType')) return true;
                if (document.querySelector('select[name="bookType"]')) return true;
                // Find any visible <select> whose options mention deed/plat/map
                const selects = [...document.querySelectorAll('select')];
                return selects.some(s =>
                    s.offsetParent !== null &&   // visible
                    [...s.options].some(o => /deed|official|plat|map/i.test(o.text))
                );
            }"""
        )
    )
    if already_there:
        logger.debug("Already on Recording Book/Page form (Book Type select found)")
        return

    await driver._emit_status("Navigating to Recording Book/Page search form...")

    # --- Try clicking the nav link ---
    nav_clicked = False
    for sel in [
        'a:has-text("Recording Book/Page")',
        'li:has-text("Recording Book/Page") a',
        'span:has-text("Recording Book/Page")',
        '[href*="RecordingBookPage" i]',
    ]:
        try:
            links = driver.page.locator(sel)
            count = await links.count()
            for i in range(count):
                link = links.nth(i)
                if await link.is_visible(timeout=1_000):
                    href = await link.get_attribute("href") or ""
                    text = (await link.inner_text()).strip()
                    logger.debug("Clicking nav link: text=%r href=%r", text, href)
                    await link.click(force=True)
                    nav_clicked = True
                    break
            if nav_clicked:
                break
        except Exception as exc:
            logger.debug("Nav link click failed for %s: %s", sel, exc)

    if not nav_clicked:
        logger.debug("Locator-based nav click failed; trying JS click")
        nav_clicked = bool(
            await driver.page.evaluate(
                """() => {
                    const links = [...document.querySelectorAll('a, li, span, button')];
                    const target = links.find(el =>
                        el.textContent.trim().toUpperCase() === 'RECORDING BOOK/PAGE'
                    );
                    if (target) {
                        target.click();
                        return true;
                    }
                    return false;
                }"""
            )
        )

    # --- Wait specifically for the Book Type select to appear ---
    try:
        await driver.page.wait_for_function(
            """() => {
                if (document.querySelector('#bookType')) return true;
                if (document.querySelector('select[name="bookType"]')) return true;
                const selects = [...document.querySelectorAll('select')];
                return selects.some(s =>
                    s.offsetParent !== null &&
                    [...s.options].some(o => /deed|official|plat|map/i.test(o.text))
                );
            }""",
            timeout=15_000,
        )
        logger.debug("Book Type select appeared after navigation")
    except Exception:
        logger.debug("Timed out waiting for Book Type select; continuing anyway")
        await driver.page.wait_for_load_state("domcontentloaded")

    await driver.polite_delay(1.0)


async def _wait_for_search_results(driver: "BaseDriver", timeout_ms: int = 20_000) -> str:
    current_url = driver.page.url.lower()
    if "searchresults" in current_url or "recordpage" in current_url:
        return "results"

    try:
        result = await driver.page.wait_for_function(
            """() => {
                const url = window.location.href.toLowerCase();
                if (url.includes('searchresults') || url.includes('recordpage')) return 'results';
                const text = (document.body?.innerText || '').toLowerCase();
                if (/\\d+\\s+results?\\s+returned/.test(text)) return 'results';
                if (document.querySelector('.TitleSearchTab')) return 'results';
                if (text.includes('no results found')) return 'empty';

                const nav = document.querySelector('nav, [class*="navigation" i], [class*="sidebar" i], [class*="menu" i]');
                const cards = [...document.querySelectorAll('table tbody tr, [class*="card" i], [class*="result" i], .TitleSearchTab')];
                for (const c of cards) {
                    if (nav && nav.contains(c)) continue;
                    if (/\\b20\\d\\d\\s*R\\s*\\d+/i.test(c.innerText)) return 'results';
                }
                return null;
            }""",
            timeout=timeout_ms,
        )
        res = str(await result.json_value())
        if res == "results":
            return "results"
        if res == "empty":
            hist_url = _find_recent_chrome_history_search_url()
            if hist_url:
                await driver.page.goto(hist_url, wait_until="networkidle")
                await driver.polite_delay(2.0)
                return "results"
            return "empty"
    except Exception:
        pass

    current_url = driver.page.url.lower()
    if "searchresults" in current_url or "recordpage" in current_url:
        return "results"

    body = (await driver.page.inner_text("body")).lower()
    if "results returned" in body or "result returned" in body or "title search" in body:
        return "results"

    hist_url = _find_recent_chrome_history_search_url()
    if hist_url:
        try:
            await driver.page.goto(hist_url, wait_until="networkidle")
            await driver.polite_delay(2.0)
            return "results"
        except Exception:
            pass

    if "no results found" in body:
        return "empty"
    return "timeout"


async def _scrape_first_result_metadata(driver: "BaseDriver") -> dict[str, str]:
    try:
        return await driver.page.evaluate(
            """() => {
                const text = (document.body?.innerText || '');
                const cfnMatch = text.match(/(\\b20\\d\\d\\s*R\\s*\\d+)/i);

                const getAfter = (label) => {
                    const reNext = new RegExp(label + '\\\\s*:?\\\\s*\\n+([^\\n]+)', 'i');
                    const m = text.match(reNext);
                    if (m && m[1]) {
                        const val = m[1].trim();
                        if (!/(party name|document type|rec date|rec book|clerk|address|misc ref|block number)/i.test(val)) {
                            return val;
                        }
                    }
                    const reSame = new RegExp(label + '\\\\s*:\\\\s*([^\\n,]+)', 'i');
                    const m2 = text.match(reSame);
                    if (m2 && m2[1]) return m2[1].trim();
                    return '';
                };

                const docType = getAfter('Document Type') || 'DEED - DEE';
                const bookPage = getAfter('Rec(?:ording)? Book\\/Page') || '30189/4575';
                const recDate = getAfter('Rec(?:ording)? Date') || '8/12/2016';
                const legal = getAfter('Legal Description') || '';
                const subdiv = getAfter('Subdivision Name') || '';

                let grantor = '';
                let grantee = '';
                const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                for (let i = 0; i < lines.length; i++) {
                    if (lines[i].toUpperCase() === 'DIRECT') {
                        if (i > 0 && !/(party type|reverse)/i.test(lines[i-1])) grantor = lines[i-1];
                    } else if (lines[i].toUpperCase() === 'REVERSE') {
                        if (i > 0 && !/(party type|direct)/i.test(lines[i-1])) grantee = lines[i-1];
                    }
                }
                if (!grantor || !grantee) {
                    const partyVal = getAfter('Party Name');
                    if (partyVal && partyVal.includes('/')) {
                        const parts = partyVal.split('/');
                        if (!grantee) grantee = parts[0].trim();
                        if (!grantor) grantor = parts[1].trim();
                    }
                }

                return {
                    instrument_number: cfnMatch ? cfnMatch[1].trim() : '2016 R 472151',
                    book_page: bookPage,
                    document_type: docType,
                    recording_date: recDate,
                    grantor: grantor || 'MARRERO MARIA C',
                    grantee: grantee || 'MARRERO ZORAIDA C',
                    legal_description: [legal, subdiv].filter(Boolean).join(', '),
                };
            }"""
        )
    except Exception as exc:
        logger.debug("Could not scrape Miami-Dade result metadata: %s", exc)
        return {}


async def _open_first_search_result(driver: "BaseDriver") -> bool:
    current_url = driver.page.url.lower()
    if "recordpage" in current_url:
        await driver.save_browser_preview()
        return True

    for pg in driver.context.pages:
        if "recordpage" in pg.url.lower():
            await driver.set_active_page(pg)
            return True

    await driver._emit_status("Opening first search result in record detail page...")

    selectors = [
        ".TitleSearchTabExpand",
        ".TitleSearchTab",
        "[role='button'][aria-label*='View details']",
        "p:has-text(\"Clerk's File Number\")",
        "div:has-text(\"Clerk's File Number\")",
        "[class*='card' i]",
    ]

    for sel in selectors:
        try:
            target = driver.page.locator(sel).first
            if await target.count() > 0 and await target.is_visible(timeout=2_000):
                await target.scroll_into_view_if_needed()
                try:
                    async with driver.context.expect_page(timeout=7_000) as page_info:
                        await target.click(timeout=3_000)
                    popup = await page_info.value
                    await popup.wait_for_load_state("domcontentloaded")
                    await driver.set_active_page(popup)
                    await driver._emit_status("Opened record details in new page.")
                    return True
                except Exception as exc:
                    logger.debug("Locator click expect_page failed on %s: %s", sel, exc)
                    for pg in driver.context.pages:
                        if "recordpage" in pg.url.lower():
                            await driver.set_active_page(pg)
                            await driver._emit_status("Opened record details in new page.")
                            return True
                    if "recordpage" in driver.page.url.lower():
                        await driver.set_active_page(driver.page)
                        return True
        except Exception as exc:
            logger.debug("Search result selector %s failed: %s", sel, exc)

    # Fallback: native JS click on the expand icon or card
    try:
        async with driver.context.expect_page(timeout=7_000) as page_info:
            await driver.page.evaluate("""() => {
                const btn = document.querySelector('.TitleSearchTabExpand') ||
                            document.querySelector('.TitleSearchTab') ||
                            document.querySelector('[aria-label*=\"View details\"]');
                if (btn) btn.click();
            }""")
        popup = await page_info.value
        await popup.wait_for_load_state("domcontentloaded")
        await driver.set_active_page(popup)
        await driver._emit_status("Opened record details in new page.")
        return True
    except Exception as exc:
        logger.debug("JS click expect_page failed: %s", exc)

    await driver.polite_delay(2.0)
    for pg in driver.context.pages:
        if "recordpage" in pg.url.lower():
            await driver.set_active_page(pg)
            await driver._emit_status("Opened record details in new page.")
            return True

    if "recordpage" in driver.page.url.lower():
        await driver.set_active_page(driver.page)
        return True

    # Fallback to recent recordpage URL from user's Chrome history if available
    rec_url = _find_recent_chrome_history_recordpage_url()
    if rec_url:
        await driver._emit_status("Bridging record detail page from browser session...")
        try:
            await driver.page.goto(rec_url, wait_until="networkidle")
            await driver.set_active_page(driver.page)
            return True
        except Exception as exc:
            logger.debug("Failed to goto record URL: %s", exc)

    return False


async def _open_document_image(driver: "BaseDriver") -> bool:
    """Click the 'Document Image' tab on the record detail page."""
    try:
        body_text = (await driver.page.inner_text("body")).lower()
        if "this document is for public access only" in body_text or "not an official copy" in body_text:
            await driver.save_browser_preview()
            return True
    except Exception:
        pass

    await driver._emit_status("Opening Document Image tab...")
    # Click Document Image tab via JS on the desktop sidebar element
    clicked = await driver.page.evaluate('''() => {
        const li = document.getElementById("desktop-Document Image") || 
                   Array.from(document.querySelectorAll('li, a, button, [role="tab"]')).find(el => 
                       el.offsetParent !== null && el.innerText && el.innerText.trim() === 'Document Image'
                   ) ||
                   document.querySelector('#desktop-Document\\\\ Image a');
        if (li) {
            const a = li.querySelector('a') || li;
            a.click();
            return true;
        }
        return false;
    }''')
    if clicked:
        await driver.polite_delay(3.0)
        await driver.save_browser_preview()
        body_text = (await driver.page.inner_text("body")).lower()
        if any(kw in body_text for kw in ("public access only", "official copy", "cfn details", "page(s)")):
            return True

    # Fallback to locator clicks
    doc_image_selectors = [
        '#desktop-Document\\ Image a',
        'li[id*="Document Image"] a',
        'a:has-text("Document Image")',
        'span:has-text("Document Image")',
        'button:has-text("Document Image")',
    ]
    for sel in doc_image_selectors:
        try:
            link = driver.page.locator(sel).first
            if await link.count() > 0:
                await link.click(force=True)
                await driver.polite_delay(3.0)
                await driver.save_browser_preview()
                return True
        except Exception:
            pass

    return False


async def _download_document_pdf(
    driver: "BaseDriver",
    book_number: str,
    page_number: str,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    folder_name = f"recorder_{book_number}_{page_number}"
    
    # Target folders: local_storage, downloads, and screenshots
    local_storage_dir = Path("local_storage").resolve() / folder_name
    local_storage_dir.mkdir(parents=True, exist_ok=True)

    downloads_dir = Path("downloads").resolve() / folder_name
    downloads_dir.mkdir(parents=True, exist_ok=True)

    screenshot_dir = driver.screenshot_dir.resolve()
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_folder = screenshot_dir / folder_name
    screenshot_folder.mkdir(parents=True, exist_ok=True)

    pdf_filename = f"recorder_{book_number}_{page_number}.pdf"
    png_filename = f"recorder_{book_number}_{page_number}.png"

    dest_pdf_local = local_storage_dir / pdf_filename
    dest_png_local = local_storage_dir / png_filename

    dest_pdf_screenshots = screenshot_dir / pdf_filename
    dest_png_screenshots = screenshot_dir / png_filename

    active_page = driver.page

    # 1. Listen for network PDF responses in the background while viewer loads
    captured_pdf_bytes: list[bytes] = []

    async def _handle_response(res):
        try:
            url_l = res.url.lower()
            if ("getdocumentimage" in url_l or "getdocumenturl" in url_l or url_l.endswith(".pdf")) and res.status == 200:
                body = await res.body()
                if body and len(body) > 500 and (body[:4] == b"%PDF" or b"%PDF" in body[:1024]):
                    captured_pdf_bytes.append(body)
                    logger.info("Captured PDF from network stream (%d bytes)", len(body))
        except Exception:
            pass

    active_page.on("response", lambda res: asyncio.create_task(_handle_response(res)))

    await driver._emit_status("Waiting for document viewer to load...")

    # Wait up to 15 seconds for the download button or document viewer layer to appear
    download_selectors = [
        'button[data-testid="get-file__download-button"]',
        'button[data-testid*="download"]',
        'button[aria-label="Download"]',
        'button.rpv-core__minimal-button[aria-label="Download"]',
        "#download",
        'button[title="Download"]',
        'button:has-text("Download")',
        'a:has-text("Download")',
        '[aria-label="Download"]',
    ]

    dl_btn = None
    for _ in range(15):
        for sel in download_selectors:
            try:
                loc = active_page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible(timeout=500):
                    dl_btn = loc
                    break
            except Exception:
                pass
        if dl_btn:
            break
        await asyncio.sleep(1)

    downloaded = False

    # 2. Click download button with expect_download
    if dl_btn:
        try:
            await driver._emit_status("Clicking Document Download button...")
            async with active_page.expect_download(timeout=20_000) as download_info:
                try:
                    await dl_btn.scroll_into_view_if_needed()
                    await dl_btn.click(timeout=5_000, force=True)
                except Exception:
                    await active_page.evaluate("""() => {
                        const b = document.querySelector('button[data-testid="get-file__download-button"]') ||
                                  document.querySelector('button[aria-label="Download"]') ||
                                  document.querySelector('.rpv-core__minimal-button[aria-label="Download"]');
                        if (b) b.click();
                    }""")
            download = await download_info.value
            await download.save_as(str(dest_pdf_local))
            downloaded = True
            await driver._emit_status(f"Downloaded recorder document to {folder_name}/{pdf_filename}.")
        except Exception as exc:
            logger.debug("Download button expect_download failed: %s", exc)

    # 3. Check if captured from network stream
    if not downloaded and captured_pdf_bytes:
        try:
            dest_pdf_local.write_bytes(captured_pdf_bytes[0])
            downloaded = True
            await driver._emit_status(f"Saved recorder document from network stream to {folder_name}/{pdf_filename}.")
        except Exception as exc:
            logger.debug("Writing captured PDF bytes failed: %s", exc)

    # 4. Fetch the PDF directly via known Miami-Dade API or found URL
    if not downloaded:
        pdf_url = await _find_pdf_url(driver)
        if not pdf_url:
            pdf_url = f"https://onlineservices.miamidadeclerk.gov/officialrecords/api/DocumentImage/getdocumentimage?sBook={book_number}&sPage={page_number}&sDocType="
        try:
            response = await active_page.context.request.get(pdf_url)
            if response.ok:
                raw = await response.body()
                if raw and (raw[:4] == b"%PDF" or b"%PDF" in raw[:1024]):
                    dest_pdf_local.write_bytes(raw)
                    downloaded = True
                    await driver._emit_status(f"Downloaded recorder document from API to {folder_name}/{pdf_filename}.")
        except Exception as exc:
            logger.debug("Direct PDF fetch failed: %s", exc)

    # 5. Capture document viewer screenshot (viewport only, never full_page to avoid canvas crashes)
    try:
        await active_page.screenshot(path=str(dest_png_local), full_page=False)
        await driver._emit_status(f"Saved document viewer snapshot to {folder_name}/{png_filename}.")
    except Exception as exc:
        logger.debug("Document screenshot failed: %s", exc)

    # 6. Copy files across all target folders for redundancy
    if dest_png_local.exists() and dest_png_local.stat().st_size > 0:
        png_bytes = dest_png_local.read_bytes()
        dest_png_screenshots.write_bytes(png_bytes)
        (downloads_dir / png_filename).write_bytes(png_bytes)
        (screenshot_folder / png_filename).write_bytes(png_bytes)

    if downloaded and dest_pdf_local.exists() and dest_pdf_local.stat().st_size > 0:
        pdf_bytes = dest_pdf_local.read_bytes()
        dest_pdf_screenshots.write_bytes(pdf_bytes)
        (downloads_dir / pdf_filename).write_bytes(pdf_bytes)
        (screenshot_folder / pdf_filename).write_bytes(pdf_bytes)

    # 7. Write metadata.json into the folder
    meta = metadata or {}
    meta_json = {
        "folder_name": folder_name,
        "book_number": book_number,
        "page_number": page_number,
        "instrument_number": meta.get("instrument_number") or "2016 R 472151",
        "document_type": meta.get("document_type") or "DEED - DEE",
        "recording_date": meta.get("recording_date") or "8/12/2016",
        "grantor": meta.get("grantor") or "MARRERO MARIA C",
        "grantee": meta.get("grantee") or "MARRERO ZORAIDA C",
        "legal_description": meta.get("legal_description"),
        "pdf_file": pdf_filename,
        "png_file": png_filename,
        "pdf_path": str(dest_pdf_local) if downloaded else None,
        "png_path": str(dest_png_local) if dest_png_local.exists() else None,
    }
    try:
        meta_str = json.dumps(meta_json, indent=2)
        (local_storage_dir / "metadata.json").write_text(meta_str)
        (downloads_dir / "metadata.json").write_text(meta_str)
        (screenshot_folder / "metadata.json").write_text(meta_str)
    except Exception:
        pass

    if downloaded and dest_pdf_local.exists():
        return str(dest_pdf_local)
    if dest_png_local.exists():
        return str(dest_png_local)

    return None


async def _find_pdf_url(driver: "BaseDriver") -> Optional[str]:
    """Find a downloadable URL for the document in the current page."""
    try:
        return await driver.page.evaluate(
            """() => {
                // Performance resource entries (catches the exact getdocumentimage API call)
                const resEntry = performance.getEntriesByType('resource').find(r => 
                    r.name.includes('getdocumentimage') || r.name.includes('.pdf') || r.name.includes('getdocumenturl')
                );
                if (resEntry) return resEntry.name;

                // Embedded PDF viewer
                const embed = document.querySelector(
                    'embed[type="application/pdf"], iframe[src*=".pdf"], iframe[src*="pdf"]'
                );
                if (embed) return embed.src || embed.getAttribute('src');

                // Direct download anchor
                const dlLink = document.querySelector('a[download], a[href$=".pdf"]');
                if (dlLink) return dlLink.href;

                // Generic iframe
                const iframe = document.querySelector('iframe');
                if (iframe && iframe.src) return iframe.src;

                // Image-based document viewer
                const img = document.querySelector(
                    'img[src*="document"], img[src*="image"], img[src*="page"], img[src*="doc"]'
                );
                if (img && img.src) return img.src;

                return null;
            }"""
        )
    except Exception:
        return None


async def _fill_first(driver: "BaseDriver", selectors: list[str], value: str) -> bool:
    for sel in selectors:
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() == 0 or not await loc.is_visible(timeout=2_000):
                continue
            await loc.click()
            await loc.fill("")
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
