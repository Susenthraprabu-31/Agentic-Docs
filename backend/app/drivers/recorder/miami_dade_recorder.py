"""Miami-Dade Clerk official records — book/page search through document download."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import parse_qs, quote, urlparse

from app.config.florida_portals import (
    MIAMI_DADE_NAME_DOCUMENT_SEARCH_URL,
    MIAMI_DADE_RECORDER_SEARCH_URL,
    format_miami_dade_address_for_search,
    format_miami_dade_recorder_address_for_search,
)
from app.extraction.book_page import format_book_page_label, parse_book_page
from app.drivers.recorder.acclaimweb_recorder import resolve_party_type_from_notes
from app.extraction.miami_dade_name_searches import (
    parse_miami_dade_party_name_fields,
    sanitize_miami_dade_party_name_for_search,
)
from app.extraction.miami_dade_party_scrape import (
    apply_party_names_to_recorded_document,
    collect_miami_dade_party_names_for_document,
)
from app.extraction.schemas import RecordedDocument

if TYPE_CHECKING:
    from app.drivers.base.base_driver import BaseDriver

logger = logging.getLogger(__name__)

CFN_RE = re.compile(r"(\d{4}\s*R\s*\d+)", re.I)

MIAMI_DADE_PROPERTY_SEARCH_TYPE = "Property/Condo"
MIAMI_DADE_NAME_DOCUMENT_SEARCH_TYPE = "Name/Document"
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

# Miami-Dade book/page searches must leave Book Type on "Select Type" (empty value).
# Selecting OR/Deeds filters often returns "No results found" for assessor book/pages.
MIAMI_DADE_BOOK_PAGE_SEARCH_TYPES: tuple[str, ...] = ("",)

MIAMI_DADE_SEARCH_RESULTS_TIMEOUT_MS = 60_000
# Cap name-search PDF downloads when no explicit search_limit is set (site may return 500+).
MIAMI_DADE_NAME_SEARCH_DEFAULT_MAX_DOWNLOADS = 50

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
        return ""
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
                    label_match = (
                        re.compile(r"select type", re.I)
                        if not expected_value
                        else re.compile(
                            r"deed|official|plat|map",
                            re.I,
                        )
                    )
                    await loc.select_option(label=label_match)
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


async def clear_miami_dade_book_type(driver: "BaseDriver") -> bool:
    """Reset Book Type to the default 'Select Type' placeholder (searches all book types)."""
    await driver._emit_status("Leaving book type as Select Type (search all book types)...")
    try:
        await driver.page.wait_for_selector(
            '#bookType, select[name="bookType"], select.form-select',
            state="attached",
            timeout=8_000,
        )
    except Exception:
        pass

    for css in ['#bookType', 'select[name="bookType"]', 'select.form-select']:
        try:
            loc = driver.page.locator(css).first
            if await loc.count() > 0 and await loc.is_visible(timeout=3_000):
                try:
                    await loc.select_option(value="")
                except Exception:
                    await loc.select_option(label=re.compile(r"select type", re.I))
                await driver.polite_delay(0.3)
                val = await loc.input_value()
                if not val:
                    return True
        except Exception as exc:
            logger.debug("Playwright clear book type failed on %s: %s", css, exc)

    try:
        cleared = bool(
            await driver.page.evaluate(
                """() => {
                    const select =
                        document.querySelector('#bookType') ||
                        document.querySelector('select[name="bookType"]') ||
                        [...document.querySelectorAll('select')].find(s =>
                            [...s.options].some(o => /deed|official|plat|map|select type/i.test(o.text))
                        );
                    if (!select) return false;
                    const emptyOption =
                        [...select.options].find(o => !o.value) ||
                        [...select.options].find(o => /select type/i.test(o.text));
                    if (!emptyOption) return false;
                    select.value = emptyOption.value;
                    const nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLSelectElement.prototype, 'value'
                    )?.set;
                    if (nativeSetter) {
                        nativeSetter.call(select, emptyOption.value);
                    }
                    select.dispatchEvent(new Event('input', { bubbles: true }));
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    return select.value === emptyOption.value;
                }"""
            )
        )
        if cleared:
            return True
    except Exception as exc:
        logger.debug("JS clear book type failed: %s", exc)
    return False


async def configure_miami_dade_book_type(driver: "BaseDriver", book_type: str = "") -> bool:
    """Set or clear the Book Type dropdown before a book/page search."""
    if not book_type or not book_type.strip():
        return await clear_miami_dade_book_type(driver)
    return await select_miami_dade_book_type(driver, book_type)


async def miami_dade_book_page_search_and_download(
    driver: "BaseDriver",
    book_number: str,
    page_number: str,
    book_type: str = DEFAULT_MIAMI_DADE_BOOK_TYPE,
    search_limit: Optional[int] = None,
) -> list[RecordedDocument]:
    """Search by book/page and download PDFs for all matching recorder results."""
    _monitor_miami_dade_verification(driver)
    await _reset_miami_dade_recorder_session(driver)
    book_page_label = format_book_page_label(book_number, page_number)

    effective_type = book_type if book_type and book_type.strip() else DEFAULT_MIAMI_DADE_BOOK_TYPE
    type_label = resolve_miami_dade_book_type_value(effective_type) or "Select Type"
    await driver._emit_status(
        f"Miami-Dade recorder: searching book {book_number}, page {page_number} "
        f"(book type {type_label})..."
    )

    if not await _search_book_page_form(
        driver,
        book_number,
        page_number,
        book_type=effective_type,
    ):
        return []

    documents = await _download_all_search_results(
        driver,
        search_limit=search_limit,
        fallback_book=book_number,
        fallback_page=page_number,
        book_type=effective_type,
        search_label=book_page_label,
        prefer_fallback_book_page=True,
    )
    pdf_docs = [
        doc
        for doc in documents
        if doc.screenshot_path and str(doc.screenshot_path).lower().endswith(".pdf")
    ]
    if pdf_docs:
        return pdf_docs

    await driver._emit_status(
        f"Miami-Dade recorder: no downloadable document found for book {book_number}, page {page_number}."
    )
    return []


def _is_miami_dade_assessor_recorder_url(url: str) -> bool:
    url_l = (url or "").lower()
    if "officialrecords" not in url_l and "miamidadeclerk.gov" not in url_l:
        return False
    return any(
        token in url_l
        for token in ("recordpage", "searchresults", "searchresults?", "qs=")
    )


async def miami_dade_open_assessor_recorder_link_and_download(
    driver: "BaseDriver",
    recorder_url: str,
    book_number: str,
    page_number: str,
    search_limit: Optional[int] = None,
    *,
    download_all_cards: bool = False,
) -> list[RecordedDocument]:
    """Open the clerk URL from an assessor OR Book-Page hyperlink and download matching PDFs."""
    book_page_label = format_book_page_label(book_number, page_number)
    if not _is_miami_dade_assessor_recorder_url(recorder_url):
        return []

    _monitor_miami_dade_verification(driver)
    await _reset_miami_dade_recorder_session(driver)
    await driver._emit_status(
        f"Miami-Dade recorder: opening assessor OR Book-Page link for {book_page_label}..."
    )

    try:
        await driver.page.goto(recorder_url, wait_until="domcontentloaded", timeout=60_000)
    except Exception as exc:
        logger.warning("Failed to open assessor recorder link %s: %s", recorder_url, exc)
        return []

    await driver.polite_delay(3.0)
    current_url = (driver.page.url or "").lower()

    if download_all_cards and "recordpage" in current_url:
        qs_token = _extract_qs_param(recorder_url) or _extract_qs_param(driver.page.url)
        if qs_token:
            search_results_url = (
                "https://onlineservices.miamidadeclerk.gov/officialrecords/"
                f"SearchResults?qs={quote(str(qs_token), safe='')}"
            )
            try:
                await driver.page.goto(search_results_url, wait_until="domcontentloaded", timeout=60_000)
                await driver.polite_delay(2.0)
                current_url = (driver.page.url or "").lower()
            except Exception as exc:
                logger.debug("Could not open SearchResults from assessor qs token: %s", exc)

    status = await _wait_for_search_results(
        driver,
        timeout_ms=MIAMI_DADE_SEARCH_RESULTS_TIMEOUT_MS,
    )
    await driver.save_browser_preview()

    if "searchresults" in current_url or status == "results":
        documents = await _download_all_search_results(
            driver,
            search_limit=search_limit,
            fallback_book=book_number,
            fallback_page=page_number,
            search_label=book_page_label,
            prefer_fallback_book_page=True,
        )
    elif "recordpage" in current_url and not download_all_cards:
        metadata = await _scrape_first_result_metadata(driver) or {}
        metadata["source_url"] = driver.page.url
        party_names = await _collect_document_party_names(driver, metadata)
        await _open_document_image(driver)
        await driver.polite_delay(2.0)
        await driver.save_browser_preview()
        pdf_path = await _download_document_pdf(
            driver,
            book_number,
            page_number,
            metadata=metadata,
            result_index=0,
        )
        if not pdf_path:
            return []
        documents = [
            apply_party_names_to_recorded_document(
                _build_recorded_document(
                    metadata,
                    book_number,
                    page_number,
                    pdf_path,
                ),
                party_names,
            )
        ]
    else:
        await driver._emit_status(
            f"Miami-Dade recorder: assessor link for {book_page_label} did not open recorder results."
        )
        return []

    pdf_docs = [
        doc
        for doc in documents
        if doc.screenshot_path and str(doc.screenshot_path).lower().endswith(".pdf")
    ]
    if pdf_docs:
        await driver._emit_status(
            f"Miami-Dade recorder: downloaded {len(pdf_docs)} document(s) for "
            f"{book_page_label} via assessor link."
        )
        return pdf_docs
    return []


async def miami_dade_prepare_recorder_queue_step(driver: "BaseDriver") -> bool:
    """Reset tabs and reopen Name/Document search between queued Miami-Dade searches."""
    await driver._emit_status(
        "Miami-Dade recorder: finished current name search — preparing next Name/Document search..."
    )
    await _close_stale_recordpage_tabs(driver)
    if not await driver.ensure_page_alive():
        return False

    current_url = (driver.page.url or "").lower()
    if "officialrecords" not in current_url:
        if not await _reset_miami_dade_recorder_session(driver):
            return False

    try:
        await driver.page.goto(
            MIAMI_DADE_NAME_DOCUMENT_SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await driver.polite_delay(1.5)
    except Exception as exc:
        logger.debug("Name/Document queue navigation failed: %s", exc)

    return await _open_name_document_search(driver)


async def miami_dade_property_address_search_and_download(
    driver: "BaseDriver",
    address: str,
    suite: str = "",
    search_limit: Optional[int] = None,
) -> list[RecordedDocument]:
    """Search Miami-Dade Property/Condo records by street address and download all PDFs."""
    _monitor_miami_dade_verification(driver)
    normalized = format_miami_dade_recorder_address_for_search(address)
    await driver._emit_status(
        f"Miami-Dade recorder: searching Property/Condo address {repr(normalized)}..."
    )

    qs_token = await _search_property_address_form(driver, normalized, suite=suite)
    if not qs_token:
        return []

    # Property/Condo address searches should fetch every matching record by default.
    effective_limit = None
    if search_limit and search_limit > 0:
        await driver._emit_status(
            f"Miami-Dade Property/Condo search: ignoring search limit {search_limit}; "
            "downloading all matching records."
        )

    return await _download_all_search_results(
        driver,
        search_limit=effective_limit,
        search_label=normalized,
        property_address=normalized,
    )


def format_miami_dade_party_name_for_search(name: str) -> str:
    """Format a party name for Miami-Dade Name/Document search."""
    return sanitize_miami_dade_party_name_for_search(name)


async def miami_dade_party_name_search_and_download(
    driver: "BaseDriver",
    party_name: str,
    *,
    party_type: str | None = None,
    search_limit: Optional[int] = None,
) -> list[RecordedDocument]:
    """Search Miami-Dade Name/Document records by party name and download matching PDFs."""
    _monitor_miami_dade_verification(driver)
    current_url = (driver.page.url or "").lower() if driver.page else ""
    if "/name/document" not in current_url and "searchresults" not in current_url:
        if "officialrecords" not in current_url:
            await _reset_miami_dade_recorder_session(driver)
        await _open_name_document_search(driver)
    normalized = format_miami_dade_party_name_for_search(party_name)
    if not normalized:
        return []

    party_label = normalized
    await driver._emit_status(
        f"Miami-Dade recorder: searching Name/Document for party {party_label!r}..."
    )

    search_status = await _search_party_name_form(driver, normalized, party_type=party_type)
    if search_status == "empty":
        return []
    if search_status != "results":
        await driver._emit_status(
            "Miami-Dade recorder: search results page did not load — skipping downloads."
        )
        return []

    effective_limit = search_limit
    if not effective_limit or effective_limit <= 0:
        effective_limit = MIAMI_DADE_NAME_SEARCH_DEFAULT_MAX_DOWNLOADS

    documents = await _download_all_search_results(
        driver,
        search_limit=effective_limit,
        search_label=party_label,
        reset_session_after=False,
        searched_name=party_label,
    )
    pdf_docs = [
        doc
        for doc in documents
        if doc.screenshot_path and str(doc.screenshot_path).lower().endswith(".pdf")
    ]
    if pdf_docs:
        return pdf_docs

    await driver._emit_status(
        f"Miami-Dade recorder: no downloadable document found for party {party_label!r}."
    )
    return documents


async def _search_party_name_form(
    driver: "BaseDriver",
    party_name: str,
    *,
    party_type: str | None = None,
) -> str:
    """Fill Miami-Dade Name/Document search form, submit, and wait for results."""
    if not await _open_name_document_search(driver):
        await driver._emit_status("Miami-Dade recorder: could not open Name/Document search form.")
        return "submit_failed"

    parsed = parse_miami_dade_party_name_fields(party_name)
    if not await _fill_miami_dade_party_name(driver, party_name):
        await driver._emit_status("Miami-Dade recorder: could not fill party name field.")
        await driver.screenshot_on_failure("miami_dade_party_name_fill_failed")
        return "submit_failed"

    await _select_miami_dade_party_type(driver, party_type)
    await driver.polite_delay(0.35)

    if not await _verify_name_document_form_values(driver, parsed):
        await driver._emit_status("Miami-Dade recorder: re-applying party name before search...")
        if not await _fill_miami_dade_party_name(driver, party_name):
            return "submit_failed"

    status = await _submit_miami_dade_name_document_form(driver, parsed=parsed)
    if status == "results":
        if await _ensure_on_miami_dade_search_results_page(driver):
            return "results"
        return "submit_failed"
    if status == "empty":
        return "empty"
    if status == "submit_failed":
        await driver._emit_status("ERROR: Could not submit Miami-Dade party name search.")
        await driver.screenshot_on_failure("miami_dade_party_name_search_failed")
    elif status == "not_submitted":
        await driver._emit_status(
            "ERROR: Miami-Dade search form did not submit — the portal may require "
            "Register/Login to pass Turnstile verification."
        )
        await driver.screenshot_on_failure("miami_dade_party_name_search_not_submitted")
    return "submit_failed"


async def _verify_name_document_form_values(
    driver: "BaseDriver",
    parsed: dict[str, str],
) -> bool:
    """Verify visible form fields contain the expected party name values."""
    try:
        return bool(
            await driver.page.evaluate(
                """(payload) => {
                    const norm = (value) => (value || '').trim().toUpperCase();
                    if (payload.kind === 'company') {
                        const expected = norm(payload.company_name);
                        const selectors = ['#companyName', 'input[name="companyName"]'];
                        return selectors.some((sel) => {
                            const el = document.querySelector(sel);
                            return el && norm(el.value) === expected;
                        });
                    }
                    const last = norm(payload.last_name);
                    const first = norm(payload.first_name || '');
                    const middle = norm(payload.middle_name || '');
                    const lastEl = document.querySelector('#lastName, input[name="lastName"]');
                    const firstEl = document.querySelector('#firstName, input[name="firstName"]');
                    const middleEl = document.querySelector('#middleName, input[name="middleName"]');
                    if (!lastEl || norm(lastEl.value) !== last) return false;
                    if (first && (!firstEl || norm(firstEl.value) !== first)) return false;
                    if (middle && (!middleEl || norm(middleEl.value) !== middle)) return false;
                    return true;
                }""",
                parsed,
            )
        )
    except Exception:
        return False


async def _is_name_document_search_form_visible(driver: "BaseDriver") -> bool:
    """Return True when the Name/Document search form is still on screen."""
    try:
        return bool(
            await driver.page.evaluate(
                """() => {
                    const url = window.location.href.toLowerCase();
                    if (url.includes('searchresults') || url.includes('recordpage')) {
                        return false;
                    }
                    const searchBtn = document.querySelector('button.button-green');
                    const nameField = document.querySelector(
                        '#lastName, input[name="lastName"], #companyName, input[name="companyName"]'
                    );
                    return !!(searchBtn && nameField && nameField.offsetParent !== null);
                }"""
            )
        )
    except Exception:
        return False


async def _get_miami_dade_name_search_mode(driver: "BaseDriver") -> str | None:
    """Return 'person' or 'company' based on which Name/Document fields are visible."""
    try:
        return await driver.page.evaluate(
            """() => {
                const company = document.querySelector('#companyName, input[name="companyName"]');
                const last = document.querySelector('#lastName, input[name="lastName"]');
                const companyVisible = !!(company && company.offsetParent !== null);
                const lastVisible = !!(last && last.offsetParent !== null);
                if (companyVisible && !lastVisible) return 'company';
                if (lastVisible && !companyVisible) return 'person';
                const labels = [...document.querySelectorAll('.fw-bold')];
                const nameLabel = labels.find((el) =>
                    /company name|party name/i.test(el.textContent || '')
                );
                if (nameLabel) {
                    return /company name/i.test(nameLabel.textContent || '')
                        ? 'company'
                        : 'person';
                }
                return null;
            }"""
        )
    except Exception:
        return None


async def _select_miami_dade_name_search_mode(driver: "BaseDriver", kind: str) -> bool:
    """Select Person or Company on the Miami-Dade Name/Document form.

    The Person/Company toggle is local React state, not a Formik field. Setting the
    radio's checked property does not run the component onChange handler, so submit
    can still read Person mode and send an empty party name.
    """
    desired = "company" if kind == "company" else "person"
    if (await _get_miami_dade_name_search_mode(driver)) == desired:
        return True

    label_sel = (
        'label[for="companySearchRadio"]'
        if desired == "company"
        else 'label[for="personSearchRadio"]'
    )
    radio_sel = "#companySearchRadio" if desired == "company" else "#personSearchRadio"
    wait_field = (
        "#companyName, input[name='companyName']"
        if desired == "company"
        else "#lastName, input[name='lastName']"
    )

    clicked = False
    for sel in (label_sel, radio_sel):
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible(timeout=2_000):
                await loc.scroll_into_view_if_needed()
                try:
                    await loc.click(timeout=3_000)
                except Exception:
                    await loc.click(force=True)
                clicked = True
                break
        except Exception:
            continue

    if not clicked:
        return False

    try:
        await driver.page.wait_for_selector(wait_field, state="visible", timeout=5_000)
    except Exception:
        pass
    await driver.polite_delay(0.5)
    return (await _get_miami_dade_name_search_mode(driver)) == desired


def _build_miami_dade_party_name_query(parsed: dict[str, str]) -> str:
    """Build the partyName query string Miami-Dade sends to standardsearch."""
    if parsed.get("kind") == "company":
        return str(parsed.get("company_name") or "").strip()
    parts = [
        str(parsed.get("last_name") or "").strip(),
        str(parsed.get("first_name") or "").strip(),
        str(parsed.get("middle_name") or "").strip(),
    ]
    return " ".join(part for part in parts if part).strip()


async def _miami_dade_results_page_has_content(driver: "BaseDriver") -> bool:
    """Return True when the SearchResults page shows a result count or cards."""
    try:
        return bool(
            await driver.page.evaluate(
                """() => {
                    const text = (document.body?.innerText || '').toLowerCase();
                    if (/\\d+\\s+results?\\s+returned/.test(text)) return true;
                    if (document.querySelectorAll('.TitleSearchTab').length > 0) return true;
                    return false;
                }"""
            )
        )
    except Exception:
        return False


async def _count_miami_dade_visible_result_cards(driver: "BaseDriver") -> int:
    """Count rendered SearchResults cards after client-side filtering."""
    try:
        return int(await driver.page.locator(".TitleSearchTab").count())
    except Exception:
        return 0


def _parse_miami_dade_results_returned_count(body_text: str) -> int:
    match = re.search(r"(\d+)\s+results?\s+returned", body_text or "", re.I)
    return int(match.group(1)) if match else 0


async def _get_miami_dade_results_returned_count(
    driver: "BaseDriver",
    *,
    prefer_visible_cards: bool = False,
) -> int:
    """Read the SearchResults count from visible cards or the page header."""
    reported = 0
    try:
        body_text = await driver.page.inner_text("body")
        reported = _parse_miami_dade_results_returned_count(body_text)
    except Exception:
        reported = 0

    card_count = await _count_miami_dade_visible_result_cards(driver)
    if prefer_visible_cards and card_count > 0:
        return max(card_count, reported)
    if reported > 0:
        return max(reported, card_count)
    return card_count


async def _resolve_miami_dade_name_search_download_count(
    driver: "BaseDriver",
    *,
    search_limit: int | None = None,
) -> int:
    """Return how many SearchResults cards should be downloaded after filters apply."""
    await _scroll_miami_dade_results_to_load_cards(driver)
    await _wait_for_miami_dade_result_cards(driver)
    await _scroll_miami_dade_results_to_load_cards(driver)

    reported = await _get_miami_dade_results_returned_count(driver)
    card_count = await _count_miami_dade_visible_result_cards(driver)
    available = max(reported, card_count)
    if available <= 0:
        return 0

    max_downloads = min(available, 500)
    if search_limit and search_limit > 0:
        max_downloads = min(max_downloads, search_limit)
    return max_downloads


def _find_miami_dade_results_filter_controls(driver: "BaseDriver"):
    """Locate the SearchResults filter dropdown, text box, and search icon."""
    toolbar = driver.page.locator(".filter-search-container").first
    toggle = toolbar.locator("#filter-dropdown").first
    input_box = toolbar.locator("input[type='text']").first
    search_button = toolbar.locator(".cursorPointer").first
    return toggle, input_box, search_button


async def _reset_miami_dade_results_sort(driver: "BaseDriver") -> None:
    """Reset the sort dropdown so it does not interfere with address filtering."""
    sort_select = driver.page.locator('select[aria-label="Select sorting type"]').first
    try:
        if not await sort_select.is_visible(timeout=1000):
            return
        current = (await sort_select.input_value() or "").strip()
        if current and current.lower() != "select sorting type":
            await sort_select.select_option(label=re.compile(r"^Select sorting type$", re.I))
            await driver.polite_delay(0.4)
    except Exception as exc:
        logger.debug("Could not reset Miami-Dade results sort dropdown: %s", exc)


async def _select_miami_dade_results_filter_type(driver: "BaseDriver", filter_type: str) -> bool:
    """Open the SearchResults filter dropdown and choose a filter type."""
    toggle, _, _ = _find_miami_dade_results_filter_controls(driver)
    try:
        if not await toggle.is_visible(timeout=3000):
            await driver._emit_status("Miami-Dade Name Search: filter dropdown not found.")
            return False
        await toggle.click(timeout=3000)
        await driver.polite_delay(0.25)
        menu_item = driver.page.locator(".dropdown-menu.show .dropdown-item").filter(
            has_text=re.compile(rf"^{re.escape(filter_type)}$", re.I)
        )
        if await menu_item.count() == 0:
            menu_item = driver.page.locator(".dropdown-item").filter(
                has_text=re.compile(rf"^{re.escape(filter_type)}$", re.I)
            )
        await menu_item.first.click(timeout=3000)
        await driver.polite_delay(0.35)
        try:
            await toggle.filter(has_text=re.compile(rf"^{re.escape(filter_type)}$", re.I)).wait_for(
                state="visible",
                timeout=3000,
            )
        except Exception:
            pass
        return True
    except Exception as exc:
        logger.debug("Miami-Dade filter type select failed (%s): %s", filter_type, exc)
        return False


async def _wait_for_miami_dade_results_filter_input_enabled(driver: "BaseDriver") -> bool:
    """Wait until the SearchResults filter text box is enabled after choosing a filter type."""
    _, filter_input, _ = _find_miami_dade_results_filter_controls(driver)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            if await filter_input.is_visible() and not await filter_input.is_disabled():
                return True
        except Exception:
            pass
        await asyncio.sleep(0.15)
    return False


async def _fill_miami_dade_results_filter_input(driver: "BaseDriver", value: str) -> bool:
    """Fill the SearchResults filter text box next to the filter dropdown."""
    _, filter_input, _ = _find_miami_dade_results_filter_controls(driver)
    street = value.strip()
    if not street:
        return False
    try:
        if not await _wait_for_miami_dade_results_filter_input_enabled(driver):
            return False

        await filter_input.click(timeout=2000)
        await filter_input.press("Control+A")
        await filter_input.press("Backspace")
        await filter_input.press_sequentially(street, delay=25)
        await driver.polite_delay(0.2)
        current = (await filter_input.input_value() or "").strip()
        if current.lower() != street.lower():
            await filter_input.evaluate(_SET_REACT_INPUT_VALUE_JS, street)
            await driver.polite_delay(0.15)
            current = (await filter_input.input_value() or "").strip()
        if current.lower() != street.lower():
            return False
        return True
    except Exception as exc:
        logger.debug("Miami-Dade filter input fill failed: %s", exc)
        return False


async def _click_miami_dade_results_filter_search(driver: "BaseDriver") -> bool:
    """Submit the SearchResults filter using Enter or the magnifying-glass icon."""
    _, filter_input, search_button = _find_miami_dade_results_filter_controls(driver)
    if filter_input:
        try:
            if await filter_input.is_visible(timeout=1000):
                await filter_input.press("Enter")
                await driver.polite_delay(0.35)
                return True
        except Exception:
            pass
    try:
        if await search_button.is_visible(timeout=1000):
            await search_button.click(timeout=3000)
            return True
    except Exception:
        pass
    return False


async def _wait_for_miami_dade_applied_filter(driver: "BaseDriver", filter_type: str) -> None:
    """Wait until the SearchResults page shows the requested applied filter chip."""
    deadline = time.monotonic() + 5.0
    target = filter_type.strip().lower()
    while time.monotonic() < deadline:
        try:
            chips = driver.page.locator(".border-primary-subtle")
            count = await chips.count()
            for i in range(count):
                text = (await chips.nth(i).inner_text() or "").lower()
                if text.startswith(f"{target}:"):
                    await driver.polite_delay(0.25)
                    return
        except Exception:
            pass
        await asyncio.sleep(0.2)


async def _apply_miami_dade_results_address_filter(driver: "BaseDriver", address: str) -> bool:
    """Apply the SearchResults Address filter chip and submit it."""
    street = format_miami_dade_address_for_search(address).strip()
    if not street:
        return False

    await _reset_miami_dade_results_sort(driver)
    if not await _select_miami_dade_results_filter_type(driver, "Address"):
        await driver._emit_status("Miami-Dade Name Search: could not choose Address filter type.")
        return False

    await driver._emit_status(
        f"Miami-Dade Name Search: entering address filter value {street!r}..."
    )
    if not await _fill_miami_dade_results_filter_input(driver, street):
        await driver._emit_status(
            f"Miami-Dade Name Search: could not type address {street!r} into filter box."
        )
        return False

    if not await _click_miami_dade_results_filter_search(driver):
        await driver._emit_status("Miami-Dade Name Search: could not submit address filter.")
        return False

    await _wait_for_miami_dade_applied_filter(driver, "Address")
    await driver.polite_delay(0.75)
    await _wait_for_miami_dade_result_cards(driver)
    await _scroll_miami_dade_results_to_load_cards(driver)
    return True


async def _clear_miami_dade_results_filter(driver: "BaseDriver") -> bool:
    """Remove applied SearchResults filter chips and restore the full result set."""
    removed_any = False
    remove_buttons = driver.page.locator(".border-primary-subtle div[style*='cursor: pointer']")
    try:
        while await remove_buttons.count() > 0:
            await remove_buttons.first.click(timeout=2000)
            removed_any = True
            await driver.polite_delay(0.35)
    except Exception as exc:
        logger.debug("Could not remove Miami-Dade applied filter chips: %s", exc)

    await _select_miami_dade_results_filter_type(driver, "Select a filter type")
    await _reset_miami_dade_results_sort(driver)
    await driver.polite_delay(0.5)
    await _scroll_miami_dade_results_to_load_cards(driver)
    return removed_any


async def _maybe_filter_miami_dade_name_results_by_address(
    driver: "BaseDriver",
    address: str,
    *,
    fallback_to_unfiltered: bool = True,
) -> bool:
    """Filter name-search results by property address.

    When ``fallback_to_unfiltered`` is False and the filter matches nothing, restore the
    unfiltered result page but return False so the caller can skip to the next name.
    """
    street = format_miami_dade_address_for_search(address).strip()
    if not street:
        return False

    initial_count = await _get_miami_dade_results_returned_count(driver)
    if initial_count <= 0:
        return False

    search_results_url = driver.page.url
    await driver._emit_status(
        f"Miami-Dade Name Search: filtering {initial_count} name result(s) by address {street!r}..."
    )
    if not await _apply_miami_dade_results_address_filter(driver, street):
        return False

    await _wait_for_miami_dade_result_cards(driver)
    filtered_count = await _get_miami_dade_results_returned_count(
        driver,
        prefer_visible_cards=True,
    )
    if filtered_count > 0:
        await _scroll_miami_dade_results_to_load_cards(driver)
        refreshed_count = await _get_miami_dade_results_returned_count(driver)
        await driver._emit_status(
            f"Miami-Dade Name Search: address filter matched {refreshed_count or filtered_count} record(s)."
        )
        return True

    if fallback_to_unfiltered:
        await driver._emit_status(
            f"Miami-Dade Name Search: no records matched address {street!r}; "
            "removing filter and downloading full name search results."
        )
    else:
        await driver._emit_status(
            f"Miami-Dade Name Search: no records matched address {street!r}; "
            "skipping this name variation and moving to the next name."
        )
    await _clear_miami_dade_results_filter(driver)
    await _wait_for_miami_dade_result_cards(driver)
    restored_count = await _get_miami_dade_results_returned_count(driver)
    if restored_count <= 0 and search_results_url:
        try:
            await driver.page.goto(search_results_url, wait_until="domcontentloaded", timeout=60_000)
            await driver.polite_delay(1.5)
            await _scroll_miami_dade_results_to_load_cards(driver)
            await _wait_for_miami_dade_result_cards(driver)
        except Exception as exc:
            logger.debug("Could not restore unfiltered name search results: %s", exc)
    return False


async def _scroll_miami_dade_results_to_load_cards(driver: "BaseDriver") -> int:
    """Scroll the results list so lazy-loaded TitleSearchTab cards appear."""
    try:
        count = await driver.page.evaluate(
            """async () => {
                const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                let previous = 0;
                for (let i = 0; i < 20; i++) {
                    window.scrollTo(0, document.body.scrollHeight);
                    await sleep(300);
                    const count = document.querySelectorAll('.TitleSearchTab').length;
                    if (count > 0 && count === previous && i > 2) break;
                    previous = count;
                }
                window.scrollTo(0, 0);
                await sleep(250);
                return document.querySelectorAll('.TitleSearchTab').length;
            }"""
        )
        return int(count or 0)
    except Exception:
        return 0


async def _wait_for_miami_dade_result_cards(driver: "BaseDriver") -> int:
    """Wait until SearchResults cards are rendered and return the visible card count."""
    try:
        count = await driver.page.wait_for_function(
            """() => {
                const text = (document.body?.innerText || '').toLowerCase();
                const cards = document.querySelectorAll('.TitleSearchTab').length;
                if (cards > 0) return cards;
                const match = text.match(/(\\d+)\\s+results?\\s+returned/);
                if (match) return parseInt(match[1], 10);
                return null;
            }""",
            timeout=MIAMI_DADE_SEARCH_RESULTS_TIMEOUT_MS,
        )
        return int(await count.json_value() or 0)
    except Exception:
        if await _miami_dade_results_page_has_content(driver):
            return await _scroll_miami_dade_results_to_load_cards(driver) or 1
        return 0


async def _ensure_on_miami_dade_search_results_page(driver: "BaseDriver") -> bool:
    """Verify the browser is on SearchResults with cards ready to open."""
    current_url = (driver.page.url or "").lower()
    if "searchresults" not in current_url:
        status = await _wait_for_search_results(
            driver,
            timeout_ms=MIAMI_DADE_SEARCH_RESULTS_TIMEOUT_MS,
        )
        if status != "results":
            return False

    for attempt in range(4):
        card_count = await _wait_for_miami_dade_result_cards(driver)
        if card_count > 0:
            await driver._emit_status(
                f"Miami-Dade recorder: search results ready ({card_count} result card(s) visible)."
            )
            return True

        if await _miami_dade_results_page_has_content(driver):
            await driver._emit_status(
                "Miami-Dade recorder: results page loaded — scrolling to reveal result cards..."
            )
            card_count = await _scroll_miami_dade_results_to_load_cards(driver)
            if card_count > 0:
                await driver._emit_status(
                    f"Miami-Dade recorder: search results ready ({card_count} result card(s) visible)."
                )
                return True
            if attempt >= 2:
                await driver._emit_status(
                    "Miami-Dade recorder: results page loaded (cards still rendering)."
                )
                return True

        await driver.polite_delay(2.0)

    return False


async def _navigate_miami_dade_search_results(driver: "BaseDriver", qs: str) -> bool:
    """Open the Miami-Dade SearchResults page for a returned qs token."""
    if not qs:
        return False
    results_url = (
        "https://onlineservices.miamidadeclerk.gov/officialrecords/"
        f"SearchResults?qs={quote(str(qs), safe='')}"
    )
    try:
        await driver.page.goto(results_url, wait_until="domcontentloaded", timeout=60_000)
        await driver.polite_delay(2.0)
        return "searchresults" in driver.page.url.lower()
    except Exception as exc:
        logger.debug("Failed to open Miami-Dade search results page: %s", exc)
        return False


async def _wait_for_miami_dade_turnstile_token(
    driver: "BaseDriver",
    *,
    timeout_ms: int = 15_000,
) -> str:
    """Wait for Cloudflare Turnstile to produce a submit token (required for API search)."""
    try:
        token = await driver.page.evaluate(
            """async (timeoutMs) => {
                const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                if (!window.turnstile) return '';

                const readExisting = () => {
                    const widgets = document.querySelectorAll(
                        '.cf-turnstile, [data-sitekey], [data-cf-turnstile-widget-id]'
                    );
                    for (const widget of widgets) {
                        const widgetId =
                            widget.getAttribute('data-cf-turnstile-widget-id') ||
                            widget.id ||
                            widget.getAttribute('id');
                        if (!widgetId || !window.turnstile.getResponse) continue;
                        const existing = window.turnstile.getResponse(widgetId);
                        if (existing) return existing;
                    }
                    return '';
                };

                let token = readExisting();
                if (token) return token;

                const started = Date.now();
                while (Date.now() - started < timeoutMs) {
                    await wait(500);
                    token = readExisting();
                    if (token) return token;
                }
                return '';
            }""",
            timeout_ms,
        )
        return str(token or "")
    except Exception as exc:
        logger.debug("Turnstile token wait failed: %s", exc)
        return ""


async def _post_miami_dade_standard_search(
    driver: "BaseDriver",
    parsed: dict[str, str],
    *,
    turnstile_token: str = "",
) -> dict[str, Any]:
    """Call Miami-Dade standardsearch API directly and return the JSON body."""
    party_name = _build_miami_dade_party_name_query(parsed)
    if not party_name:
        return {"ok": False, "reason": "empty_party_name"}

    try:
        return await driver.page.evaluate(
            """async ({ partyName, token }) => {
                const params = new URLSearchParams({
                    partyName,
                    dateRangeFrom: '',
                    dateRangeTo: '',
                    documentType: '',
                    searchT: '',
                    firstQuery: 'y',
                    searchtype: 'Name/Document',
                });
                const response = await fetch(
                    `/officialrecords/api/home/standardsearch?${params.toString()}`,
                    {
                        method: 'POST',
                        headers: {
                            Accept: 'application/json',
                            'x-recaptcha-token': token || '',
                            'content-type': 'application/json; charset=utf-8',
                        },
                    }
                );
                let body = null;
                try {
                    body = await response.json();
                } catch (err) {
                    body = null;
                }
                return {
                    ok: response.ok,
                    status: response.status,
                    body,
                    isValidSearch: !!(body && body.isValidSearch),
                    qs: body && body.qs ? String(body.qs) : '',
                };
            }""",
            {"partyName": party_name, "token": turnstile_token},
        )
    except Exception as exc:
        logger.debug("Miami-Dade standardsearch API call failed: %s", exc)
        return {"ok": False, "reason": str(exc)}


async def _extract_miami_dade_search_qs_from_page(driver: "BaseDriver") -> str:
    """Read the qs token from the current SearchResults URL, if present."""
    try:
        parsed = urlparse(driver.page.url or "")
        if "searchresults" not in parsed.path.lower():
            return ""
        qs_values = parse_qs(parsed.query).get("qs") or []
        return str(qs_values[0]).strip() if qs_values else ""
    except Exception:
        return ""


async def _click_and_wait_standard_search(
    driver: "BaseDriver",
    *,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Click Search and capture the standardsearch API response."""
    result: dict[str, Any] = {"clicked": False}
    try:
        async with driver.page.expect_response(
            lambda resp: "standardsearch" in resp.url.lower()
            and resp.request.method == "POST",
            timeout=timeout_ms,
        ) as response_info:
            result["clicked"] = await _click_miami_dade_search_button(
                driver,
                wait_for_results=False,
            )
        if not result["clicked"]:
            result["reason"] = "click_failed"
            return result

        response = await response_info.value
        result["http_ok"] = response.ok
        result["status"] = response.status
        try:
            body = await response.json()
            result["body"] = body
            result["isValidSearch"] = bool(body.get("isValidSearch"))
            result["qs"] = body.get("qs")
        except Exception as exc:
            result["parse_error"] = str(exc)
    except Exception as exc:
        result["reason"] = str(exc)
        if result.get("clicked"):
            await driver.polite_delay(2.5)
            page_qs = await _extract_miami_dade_search_qs_from_page(driver)
            if page_qs:
                result["isValidSearch"] = True
                result["qs"] = page_qs
                result["navigated"] = True
            elif "searchresults" in (driver.page.url or "").lower():
                result["navigated"] = True
                result["isValidSearch"] = True
    return result


async def _name_document_validation_errors(driver: "BaseDriver") -> list[str]:
    """Return visible Formik validation messages on the Name/Document form."""
    try:
        raw = await driver.page.evaluate(
            """() => [...document.querySelectorAll('.text-danger, .errorText')]
                .filter((el) => el.offsetParent !== null)
                .map((el) => (el.textContent || '').trim())
                .filter(Boolean)"""
        )
        return [str(item) for item in (raw or []) if str(item).strip()]
    except Exception:
        return []


async def _submit_miami_dade_name_document_form(
    driver: "BaseDriver",
    *,
    parsed: dict[str, str] | None = None,
) -> str:
    """Submit the Name/Document search form and wait for results."""
    await driver._emit_status("Submitting Name/Document search...")
    parsed = parsed or {}

    expected_kind = parsed.get("kind")
    if expected_kind in ("person", "company"):
        mode = await _get_miami_dade_name_search_mode(driver)
        if mode != expected_kind:
            await driver._emit_status(
                f"Miami-Dade recorder: switching search mode to {expected_kind} before submit..."
            )
            if not await _select_miami_dade_name_search_mode(driver, expected_kind):
                return "submit_failed"
            if not await _verify_name_document_form_values(driver, parsed):
                return "submit_failed"

    try:
        await driver.page.wait_for_function(
            "() => typeof window.turnstile !== 'undefined'",
            timeout=8_000,
        )
    except Exception:
        pass

    await driver._emit_status("Waiting for Miami-Dade Turnstile verification token...")
    turnstile_token = await _wait_for_miami_dade_turnstile_token(driver)
    if not turnstile_token:
        await driver._emit_status(
            "Miami-Dade recorder: Turnstile token not ready — if searches fail, "
            "Register/Login on the clerk site in Live Browser and re-run."
        )
    else:
        await driver._emit_status("Miami-Dade recorder: Turnstile token acquired.")

    validation_errors = await _name_document_validation_errors(driver)
    if validation_errors:
        await driver._emit_status(
            "Miami-Dade recorder: form validation blocked search — "
            f"{validation_errors[0][:120]}"
        )

    party_query = _build_miami_dade_party_name_query(parsed)
    if party_query:
        await driver._emit_status(f"Miami-Dade recorder: searching party name {party_query!r}...")

    api_result = await _click_and_wait_standard_search(driver)
    if api_result.get("navigated") and await _ensure_on_miami_dade_search_results_page(driver):
        await driver._emit_status("Miami-Dade recorder: search results loaded.")
        return "results"
    if api_result.get("isValidSearch") and api_result.get("qs"):
        current_qs = await _extract_miami_dade_search_qs_from_page(driver)
        if current_qs:
            if await _ensure_on_miami_dade_search_results_page(driver):
                await driver._emit_status("Miami-Dade recorder: search results loaded.")
                return "results"
        if await _navigate_miami_dade_search_results(driver, str(api_result["qs"])):
            if await _ensure_on_miami_dade_search_results_page(driver):
                await driver._emit_status("Miami-Dade recorder: search results loaded.")
                return "results"

    if api_result.get("http_ok") and api_result.get("body") is not None:
        if not api_result.get("isValidSearch"):
            await driver._emit_status("Miami-Dade recorder: search completed — no records found.")
            return "empty"

    if not turnstile_token:
        turnstile_token = await _wait_for_miami_dade_turnstile_token(driver, timeout_ms=10_000)

    await driver._emit_status("Retrying Miami-Dade search via official records API...")
    direct_result = await _post_miami_dade_standard_search(
        driver,
        parsed,
        turnstile_token=turnstile_token,
    )
    if direct_result.get("isValidSearch") and direct_result.get("qs"):
        current_qs = await _extract_miami_dade_search_qs_from_page(driver)
        if current_qs:
            if await _ensure_on_miami_dade_search_results_page(driver):
                await driver._emit_status("Miami-Dade recorder: search results loaded.")
                return "results"
        if await _navigate_miami_dade_search_results(driver, str(direct_result["qs"])):
            if await _ensure_on_miami_dade_search_results_page(driver):
                await driver._emit_status("Miami-Dade recorder: search results loaded.")
                return "results"
    if direct_result.get("ok") and direct_result.get("body") is not None:
        if not direct_result.get("isValidSearch"):
            await driver._emit_status("Miami-Dade recorder: search completed — no records found.")
            return "empty"

    if await _is_name_document_search_form_visible(driver):
        await driver._emit_status(
            "Miami-Dade recorder: search blocked by Turnstile — the site shows "
            "'No results found' even when records exist. Register/Login in Live Browser."
        )
        return "verification_failed"

    status = await _wait_for_search_results(
        driver,
        timeout_ms=MIAMI_DADE_SEARCH_RESULTS_TIMEOUT_MS,
    )
    if status == "results":
        await driver._emit_status("Miami-Dade recorder: search results loaded.")
    elif status == "empty":
        await driver._emit_status("Miami-Dade recorder: search completed — no records found.")
    elif status == "timeout":
        await driver._emit_status(
            "Miami-Dade recorder: search submitted but results did not appear in time."
        )
    return status


async def _name_document_form_visible(driver: "BaseDriver") -> bool:
    """Return True when the Miami-Dade Name/Document search form is visible."""
    selectors = [
        "#lastName",
        'input[name="lastName"]',
        "#firstName",
        'input[name="firstName"]',
        "#companyName",
        'input[name="companyName"]',
        "#partyName",
        'input[name="partyName"]',
        "#personSearchRadio",
        "#companySearchRadio",
    ]
    for sel in selectors:
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible(timeout=500):
                return True
        except Exception:
            continue
    return False


async def _open_name_document_search(driver: "BaseDriver") -> bool:
    """Navigate to the Miami-Dade Name/Document search form."""
    if await _name_document_form_visible(driver):
        return True

    await driver._emit_status("Navigating to Name/Document search form...")
    nav_clicked = False
    for sel in [
        'a:has-text("Name/Document")',
        'li:has-text("Name/Document") a',
        'span:has-text("Name/Document")',
        '[href*="NameDocument" i]',
        '[href*="Name/Document" i]',
    ]:
        try:
            links = driver.page.locator(sel)
            count = await links.count()
            for i in range(count):
                link = links.nth(i)
                if await link.is_visible(timeout=1_000):
                    await link.click(force=True)
                    nav_clicked = True
                    break
            if nav_clicked:
                break
        except Exception as exc:
            logger.debug("Name/Document nav click failed for %s: %s", sel, exc)

    if not nav_clicked:
        nav_clicked = bool(
            await driver.page.evaluate(
                """() => {
                    const links = [...document.querySelectorAll('a, li, span, button')];
                    const target = links.find(el =>
                        el.textContent.trim().toUpperCase() === 'NAME/DOCUMENT'
                    );
                    if (target) {
                        target.click();
                        return true;
                    }
                    return false;
                }"""
            )
        )

    if not nav_clicked:
        try:
            await driver.page.goto(
                MIAMI_DADE_NAME_DOCUMENT_SEARCH_URL,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            nav_clicked = True
        except Exception as exc:
            logger.debug("Direct Name/Document navigation failed: %s", exc)

    try:
        await driver.page.wait_for_selector(
            "#lastName, input[name='lastName'], #companyName, input[name='companyName'], "
            "#partyName, input[name='partyName']",
            state="visible",
            timeout=15_000,
        )
    except Exception:
        await driver.page.wait_for_load_state("domcontentloaded")
    await driver.polite_delay(1.0)

    visible = await _name_document_form_visible(driver)
    if visible:
        await driver._emit_status("Opened Miami-Dade Name/Document search form.")
    return visible


async def _click_first_visible(driver: "BaseDriver", selectors: list[str]) -> bool:
    for sel in selectors:
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible(timeout=1_000):
                await loc.click(force=True)
                return True
        except Exception:
            continue
    return False


async def _clear_first_visible(driver: "BaseDriver", selectors: list[str]) -> bool:
    for sel in selectors:
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() == 0 or not await loc.is_visible(timeout=1_000):
                continue
            await loc.click()
            await loc.fill("")
            await loc.evaluate(_SET_REACT_INPUT_VALUE_JS, "")
            await loc.blur()
            return True
        except Exception:
            continue
    return False


async def _fill_miami_dade_party_name(driver: "BaseDriver", party_name: str) -> bool:
    """Fill the Miami-Dade Name/Document form for a person or company."""
    parsed = parse_miami_dade_party_name_fields(party_name)
    if parsed.get("kind") == "unknown":
        return False

    await driver._emit_status(f"Entering party name on Name/Document form: {party_name}")

    if parsed["kind"] == "company":
        if not await _select_miami_dade_name_search_mode(driver, "company"):
            await driver._emit_status("Miami-Dade recorder: could not select Company search mode.")
            return False
        for sel in ("#companyName", 'input[name="companyName"]'):
            if await _fill_first(driver, [sel], parsed["company_name"]):
                await driver.polite_delay(0.2)
                if await _verify_name_document_form_values(driver, parsed):
                    return True
        return False

    if not await _select_miami_dade_name_search_mode(driver, "person"):
        await driver._emit_status("Miami-Dade recorder: could not select Person search mode.")
        return False

    filled_last = await _fill_first(
        driver,
        ["#lastName", 'input[name="lastName"]'],
        parsed["last_name"],
    )
    if parsed.get("first_name"):
        await _fill_first(
            driver,
            ["#firstName", 'input[name="firstName"]'],
            parsed["first_name"],
        )
    else:
        await _clear_first_visible(
            driver,
            ["#firstName", 'input[name="firstName"]'],
        )
    if parsed.get("middle_name"):
        await _fill_first(
            driver,
            ["#middleName", 'input[name="middleName"]'],
            parsed["middle_name"],
        )
    else:
        await _clear_first_visible(
            driver,
            ["#middleName", 'input[name="middleName"]'],
        )

    if filled_last:
        await driver.polite_delay(0.2)
        return await _verify_name_document_form_values(driver, parsed)
    return False


async def _select_miami_dade_party_type(driver: "BaseDriver", party_type: str | None) -> None:
    """Select Direct/Reverse/Both on the Miami-Dade Name/Document form."""
    resolved = resolve_party_type_from_notes(party_type or "")
    value = "Both"
    if resolved == "grantor":
        value = "Direct"
    elif resolved == "grantee":
        value = "Reverse"

    for sel in ("#partyType1", 'select[name="partyType1"]'):
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() == 0 or not await loc.is_visible(timeout=1_000):
                continue
            await loc.select_option(value)
            return
        except Exception as exc:
            logger.debug("Miami-Dade party type select failed for %s: %s", sel, exc)


async def _search_book_page_form(
    driver: "BaseDriver",
    book_number: str,
    page_number: str,
    book_type: str = DEFAULT_MIAMI_DADE_BOOK_TYPE,
) -> bool:
    if not await driver.ensure_page_alive():
        return False
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

    book_type_ok = await configure_miami_dade_book_type(driver, book_type or DEFAULT_MIAMI_DADE_BOOK_TYPE)
    # The Miami-Dade form can rehydrate its dropdown after navigation and retain
    # DB-Deeds from a previous session. For an unspecified type, never submit a
    # filtered search: clear it immediately before clicking Search and verify it.
    if not (book_type or "").strip():
        book_type_ok = await clear_miami_dade_book_type(driver)
    if not book_type_ok:
        await driver._emit_status(
            "Miami-Dade recorder: could not reset Book Type to Select Type; search was not submitted."
        )
        return False

    # This is a React-controlled form.  A visible input value alone is not a
    # guarantee that the form model has accepted it.  Let the input blur and
    # give the page a moment to commit its change handlers before submitting.
    await driver.polite_delay(0.35)

    # --- Click the Search/Submit button ---
    await driver._emit_status("Clicking Search button...")
    if not await _click_miami_dade_search_button(driver):
        # Press Enter on the page number input field to trigger form submission
        try:
            page_inp = driver.page.locator('#recordingPageNumber, input[name="recordingPageNumber"]').first
            if await page_inp.count() > 0:
                await page_inp.press("Enter")
                await driver._emit_status(
                    "Search submitted; waiting for results (this may take up to 60 seconds)..."
                )
                await _wait_for_search_results(
                    driver,
                    timeout_ms=MIAMI_DADE_SEARCH_RESULTS_TIMEOUT_MS,
                )
                return True
        except Exception:
            pass
        await driver._emit_status("ERROR: Could not find/click Search button.")
        return False
    return True


_SET_REACT_INPUT_VALUE_JS = """
(el, val) => {
    const previousValue = el.value;
    const tracker = el._valueTracker;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
    if (setter) {
        setter.call(el, val);
    } else {
        el.value = val;
    }
    // React compares its tracker with the native value during the input
    // event.  Keep the tracker at the *previous* value so the event is
    // recognised as a change.  Setting it to val first suppresses the change
    // in controlled forms and caused Miami-Dade searches to submit blanks.
    if (tracker) {
        tracker.setValue(previousValue);
    }
    el.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
    el.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true, composed: true }));
    return el.value;
}
"""


async def _fill_miami_dade_property_address(
    driver: "BaseDriver",
    address: str,
    suite: str = "",
) -> bool:
    """Fill Property/Condo address with one leading space, like manual entry."""
    street = format_miami_dade_address_for_search(address)
    formatted = format_miami_dade_recorder_address_for_search(address)
    if not formatted:
        return False

    address_selectors = [
        "#addressNoUnit",
        'input[name="addressNoUnit"]',
        'input[placeholder*="address" i]',
        'input[id*="address" i]',
    ]
    suite_selectors = [
        "#addressUnit",
        'input[name="addressUnit"]',
        'input[placeholder*="suite" i]',
    ]

    filled = False
    for sel in address_selectors:
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() == 0 or not await loc.is_visible(timeout=2_000):
                continue
            await loc.click()
            await loc.fill("")
            try:
                await loc.press_sequentially(formatted, delay=20)
            except Exception:
                await driver.page.keyboard.press("Space")
                await driver.page.keyboard.type(street, delay=20)

            current = await loc.evaluate("(el) => el.value")
            if current != formatted or not current.startswith(" "):
                await loc.evaluate(_SET_REACT_INPUT_VALUE_JS, formatted)

            filled = True
            break
        except Exception as exc:
            logger.debug("Miami-Dade property address fill failed for %s: %s", sel, exc)

    if not filled:
        inputs = await driver.page.locator('input[type="text"]:visible').all()
        if inputs:
            try:
                loc = inputs[0]
                await loc.click()
                await loc.fill("")
                await driver.page.keyboard.press("Space")
                await driver.page.keyboard.type(street, delay=20)
                await loc.evaluate(_SET_REACT_INPUT_VALUE_JS, formatted)
                filled = True
            except Exception as exc:
                logger.debug("Fallback Miami-Dade property address fill failed: %s", exc)

    if suite:
        await _fill_first(driver, suite_selectors, suite)

    return filled


async def _ensure_miami_dade_property_address_on_form(
    driver: "BaseDriver",
    address: str,
) -> bool:
    formatted = format_miami_dade_recorder_address_for_search(address)
    if not formatted:
        return False
    for sel in ("#addressNoUnit", 'input[name="addressNoUnit"]'):
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() == 0:
                continue
            current = await loc.evaluate("(el) => el.value")
            if current == formatted and current.startswith(" "):
                return True
            await loc.evaluate(_SET_REACT_INPUT_VALUE_JS, formatted)
            current = await loc.evaluate("(el) => el.value")
            return current == formatted and current.startswith(" ")
        except Exception as exc:
            logger.debug("Could not re-apply Miami-Dade property address value: %s", exc)
    return False


def _extract_qs_param(url: str) -> Optional[str]:
    """Extract the `qs` token from a Miami-Dade SearchResults URL."""
    if not url:
        return None
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("qs") or []
    token = values[0].strip() if values else ""
    return token or None


def _monitor_miami_dade_verification(driver: "BaseDriver") -> None:
    """Record official-site verification failures; do not attempt to defeat them."""
    if getattr(driver, "_miami_dade_verification_monitor", False):
        return
    setattr(driver, "_miami_dade_verification_monitor", True)
    setattr(driver, "_miami_dade_verification_error", None)

    def _on_console(message) -> None:
        try:
            text = str(message.text)
        except Exception:
            return
        normalized = text.lower()
        if "cloudflare turnstile" in normalized and "error" in normalized:
            setattr(driver, "_miami_dade_verification_error", text)

    try:
        driver.page.on("console", _on_console)
    except Exception as exc:
        logger.debug("Could not monitor Miami-Dade verification messages: %s", exc)


async def _search_property_address_form(
    driver: "BaseDriver",
    address: str,
    suite: str = "",
) -> Optional[str]:
    """Fill Miami-Dade Property/Condo search form, submit, and return the results `qs` token."""
    address = format_miami_dade_recorder_address_for_search(address)
    await _open_property_condo_search(driver)

    if not await _fill_miami_dade_property_address(driver, address, suite=suite):
        return None

    await _ensure_miami_dade_property_address_on_form(driver, address)
    await driver._emit_status(
        f"Submitting Property/Condo search for {repr(address)} (leading space required)..."
    )

    if not await _click_miami_dade_search_button(driver):
        return None
    return _extract_qs_param(driver.page.url)


async def _open_property_condo_search(driver: "BaseDriver") -> None:
    """Navigate to the Property/Condo search form."""
    try:
        if await driver.page.locator("#addressNoUnit, input[name='addressNoUnit']").first.is_visible(timeout=1_000):
            return
    except Exception:
        pass

    await driver._emit_status("Navigating to Property/Condo search form...")
    nav_clicked = False
    for sel in [
        'a:has-text("Property/Condo")',
        'li:has-text("Property/Condo") a',
        'span:has-text("Property/Condo")',
        '[href*="Property" i]:has-text("Condo")',
    ]:
        try:
            links = driver.page.locator(sel)
            count = await links.count()
            for i in range(count):
                link = links.nth(i)
                if await link.is_visible(timeout=1_000):
                    await link.click(force=True)
                    nav_clicked = True
                    break
            if nav_clicked:
                break
        except Exception as exc:
            logger.debug("Property/Condo nav click failed for %s: %s", sel, exc)

    if not nav_clicked:
        nav_clicked = bool(
            await driver.page.evaluate(
                """() => {
                    const links = [...document.querySelectorAll('a, li, span, button')];
                    const target = links.find(el =>
                        el.textContent.trim().toUpperCase() === 'PROPERTY/CONDO'
                    );
                    if (target) {
                        target.click();
                        return true;
                    }
                    return false;
                }"""
            )
        )

    try:
        await driver.page.wait_for_selector(
            "#addressNoUnit, input[name='addressNoUnit']",
            state="attached",
            timeout=15_000,
        )
    except Exception:
        await driver.page.wait_for_load_state("domcontentloaded")
    await driver.polite_delay(1.0)


async def _dismiss_miami_dade_info_modal(driver: "BaseDriver") -> bool:
    """Close informational popups such as 'No results found' after a search."""
    dismissed = False
    for sel in (
        '.modal.show button.btn-close',
        '.modal.show button.close',
        '.modal-dialog button.btn-close',
        '[role="dialog"] button.btn-close',
        '[role="dialog"] button[aria-label="Close"]',
        'button.btn-close',
    ):
        try:
            btn = driver.page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible(timeout=500):
                await btn.click(timeout=2_000)
                dismissed = True
                await driver.polite_delay(0.5)
                break
        except Exception:
            pass

    if not dismissed:
        try:
            await driver.page.keyboard.press("Escape")
            await driver.polite_delay(0.3)
            dismissed = True
        except Exception:
            pass
    return dismissed


async def _click_miami_dade_search_button(
    driver: "BaseDriver",
    *,
    wait_for_results: bool = True,
) -> bool:
    """Click the green SEARCH button on any Miami-Dade recorder search form."""
    search_clicked = False
    search_selectors = [
        'button.button-green:has-text("SEARCH")',
        'button[type="submit"]:has-text("SEARCH")',
        'button:has-text("SEARCH"):not(:has-text("REFRESH"))',
        "button.button-green",
        'button[type="submit"]',
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

    if not search_clicked:
        search_clicked = bool(
            await driver.page.evaluate(
                """() => {
                    const buttons = [...document.querySelectorAll('button')];
                    const searchBtn = buttons.find((btn) => {
                        const text = (btn.textContent || '').trim().toUpperCase();
                        return text === 'SEARCH' || (text.includes('SEARCH') && !text.includes('REFRESH'));
                    });
                    if (searchBtn) {
                        searchBtn.click();
                        return true;
                    }
                    const greenBtn = document.querySelector('button.button-green');
                    if (greenBtn && !/refresh/i.test(greenBtn.textContent || '')) {
                        greenBtn.click();
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

    if not search_clicked:
        return False

    if not wait_for_results:
        return True

    await driver._emit_status(
        "Search button clicked; waiting for results (this may take up to 60 seconds)..."
    )
    status = await _wait_for_search_results(
        driver,
        timeout_ms=MIAMI_DADE_SEARCH_RESULTS_TIMEOUT_MS,
    )
    if status == "results":
        await driver._emit_status("Miami-Dade recorder: search results loaded.")
    elif status == "empty":
        await driver._emit_status("Miami-Dade recorder: search completed — no records found.")
    elif status == "verification_failed":
        await driver._emit_status(
            "Miami-Dade recorder: Cloudflare Turnstile verification failed; "
            "the portal's no-results message is not a data result."
        )
    elif status == "not_submitted":
        await driver._emit_status(
            "Miami-Dade recorder: search form did not submit — login may be required."
        )
    elif status == "timeout":
        await driver._emit_status(
            "Miami-Dade recorder: search is still loading; continuing to wait for results..."
        )
    return True


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


async def _wait_for_search_results(
    driver: "BaseDriver",
    timeout_ms: int = MIAMI_DADE_SEARCH_RESULTS_TIMEOUT_MS,
) -> str:
    if getattr(driver, "_miami_dade_verification_error", None):
        return "verification_failed"
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

                const nav = document.querySelector('nav, [class*="navigation" i], [class*="sidebar" i], [class*="menu" i]');
                const cards = [...document.querySelectorAll('table tbody tr, [class*="card" i], [class*="result" i], .TitleSearchTab')];
                for (const c of cards) {
                    if (nav && nav.contains(c)) continue;
                    if (/\\b20\\d\\d\\s*R\\s*\\d+/i.test(c.innerText)) return 'results';
                }

                const loading = document.querySelector(
                    '.spinner, .loading, [class*="spinner" i], [class*="loading" i], [aria-busy="true"]'
                );
                if (loading && loading.offsetParent !== null) return null;

                const onNameDocForm = !!(
                    document.querySelector('button.button-green') &&
                    (document.querySelector('#lastName, input[name="lastName"]') ||
                     document.querySelector('#companyName, input[name="companyName"]'))
                );
                if (text.includes('no results found')) {
                    if (onNameDocForm && !url.includes('searchresults')) return 'not_submitted';
                    return 'empty';
                }
                return null;
            }""",
            timeout=timeout_ms,
        )
        res = str(await result.json_value())
        if res == "results":
            return "results"
        if res == "not_submitted":
            return "not_submitted"
        if res == "empty":
            if getattr(driver, "_miami_dade_verification_error", None):
                return "verification_failed"
            if await _is_name_document_search_form_visible(driver):
                return "not_submitted"
            await _dismiss_miami_dade_info_modal(driver)
            await driver.polite_delay(0.5)
            current_url = driver.page.url.lower()
            if "searchresults" in current_url or "recordpage" in current_url:
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

    if "no results found" in body:
        if getattr(driver, "_miami_dade_verification_error", None):
            return "verification_failed"
        if await _is_name_document_search_form_visible(driver):
            return "not_submitted"
        await _dismiss_miami_dade_info_modal(driver)
        return "empty"
    if await _is_name_document_search_form_visible(driver):
        return "not_submitted"
    return "timeout"


def _resolve_book_page_numbers(
    metadata: dict[str, str],
    fallback_book: str = "",
    fallback_page: str = "",
    *,
    prefer_fallback: bool = False,
) -> tuple[str, str]:
    if prefer_fallback and fallback_book and fallback_page:
        return fallback_book, fallback_page
    book_page = metadata.get("book_page") or ""
    parsed = parse_book_page(book_page)
    if parsed:
        return parsed
    if fallback_book and fallback_page:
        return fallback_book, fallback_page
    return "", ""


def _parse_recording_date(raw: str) -> Optional[datetime.date]:
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except Exception:
            pass
    return None


def _build_recorded_document(
    metadata: dict[str, str],
    book_number: str,
    page_number: str,
    pdf_path: Optional[str],
    *,
    book_type: str = DEFAULT_MIAMI_DADE_BOOK_TYPE,
    property_address: str = "",
    result_index: int = 0,
    searched_name: str = "",
) -> RecordedDocument:
    book_page_label = metadata.get("book_page") or format_book_page_label(book_number, page_number)
    folder_name, pdf_filename = _recorder_pdf_storage_key(
        book_number,
        page_number,
        metadata,
        result_index=result_index,
        searched_name=searched_name,
    )
    png_filename = pdf_filename.replace(".pdf", ".png")
    rec_date_raw = metadata.get("recording_date") or ""
    local_img_path = str(Path("local_storage") / folder_name / png_filename)

    ocr_json: dict[str, Any] = {
        "download_path": pdf_path,
        "folder_name": folder_name,
        "folder": str(Path("local_storage") / folder_name),
        "pdf_file": pdf_filename,
        "png_file": png_filename,
        "image_path": local_img_path,
        "book_number": book_number,
        "page_number": page_number,
        "book_type": book_type,
        "clerk_file_number": metadata.get("instrument_number"),
        "legal_description": metadata.get("legal_description"),
        "recording_date": rec_date_raw,
        "storage_category": "name_searcher" if searched_name.strip() else "recorder",
    }
    if property_address:
        ocr_json["property_address"] = property_address
    elif metadata.get("property_address"):
        ocr_json["property_address"] = metadata.get("property_address")
    if metadata.get("party_name"):
        ocr_json["party_name"] = metadata.get("party_name")
    if metadata.get("card_index"):
        ocr_json["card_index"] = metadata.get("card_index")
    if searched_name.strip():
        ocr_json["searched_name"] = searched_name.strip()
        ocr_json["source"] = "name_searcher"

    return RecordedDocument(
        document_type=metadata.get("document_type") or "Official Record",
        recording_date=_parse_recording_date(rec_date_raw),
        book_page=book_page_label,
        instrument_number=metadata.get("instrument_number"),
        grantor=metadata.get("grantor"),
        grantee=metadata.get("grantee"),
        source_url=metadata.get("source_url"),
        screenshot_path=pdf_path,
        ocr_json=ocr_json,
    )


async def _collect_document_party_names(
    driver: "BaseDriver",
    metadata: dict[str, str],
) -> list[str]:
    """Collect all party names for a recorder document from metadata and CFN Details."""
    return await collect_miami_dade_party_names_for_document(driver, metadata)


async def _download_all_search_results(
    driver: "BaseDriver",
    *,
    search_limit: Optional[int] = None,
    fallback_book: str = "",
    fallback_page: str = "",
    book_type: str = DEFAULT_MIAMI_DADE_BOOK_TYPE,
    search_label: str = "",
    property_address: str = "",
    prefer_fallback_book_page: bool = False,
    reset_session_after: bool = True,
    searched_name: str = "",
) -> list[RecordedDocument]:
    """Download PDFs for every result card on the Miami-Dade search results page."""
    status = await _wait_for_search_results(driver)
    label = search_label or property_address or format_book_page_label(fallback_book, fallback_page)

    if status == "empty":
        await driver._emit_status("Miami-Dade recorder: search completed — no records found.")
        if prefer_fallback_book_page:
            return []
        screenshot = await driver.screenshot_on_failure("miami_dade_no_results")
        return [
            RecordedDocument(
                document_type="Search Result (No Records Found)",
                book_page=label or None,
                source_url=driver.page.url,
                screenshot_path=screenshot,
                ocr_json={"status": "no_records_found", "property_address": property_address or None},
            )
        ]
    if status == "verification_failed":
        await driver._emit_status(
            "Miami-Dade recorder: stopped because the official site rejected its "
            "Turnstile verification. No record-search conclusion was made."
        )
        await driver.screenshot_on_failure("miami_dade_turnstile_verification_failed")
        return []
    if status == "not_submitted":
        await driver._emit_status(
            "Miami-Dade recorder: search did not submit — register/login on the clerk "
            "site in Live Browser to pass Turnstile verification, then re-run."
        )
        await driver.screenshot_on_failure("miami_dade_party_name_search_not_submitted")
        return [
            RecordedDocument(
                document_type="Search Result",
                book_page=label or None,
                source_url=driver.page.url,
                ocr_json={"status": "not_submitted", "property_address": property_address or None},
            )
        ]
    if status != "results":
        await driver._emit_status("Miami-Dade recorder: search completed (timeout waiting for detailed records).")
        if prefer_fallback_book_page:
            return []
        screenshot = await driver.screenshot_on_failure("miami_dade_search_timeout")
        return [
            RecordedDocument(
                document_type="Search Result",
                book_page=label or None,
                source_url=driver.page.url,
                screenshot_path=screenshot,
                ocr_json={"status": status, "property_address": property_address or None},
            )
        ]

    search_results_url = driver.page.url
    await _wait_for_miami_dade_result_cards(driver)
    all_metadata = await _scrape_all_search_results_metadata(driver)
    if not all_metadata:
        await driver._emit_status("Miami-Dade recorder: scrolling results list to load cards...")
        await driver.polite_delay(1.5)
        all_metadata = await _scrape_all_search_results_metadata(scroll_first=True)
    if not all_metadata:
        first_meta = await _scrape_first_result_metadata(driver)
        if first_meta:
            all_metadata = [first_meta]

    if not all_metadata:
        if prefer_fallback_book_page:
            return []
        screenshot = await driver.screenshot_on_failure("miami_dade_no_result_cards")
        return [
            RecordedDocument(
                document_type="Search Result",
                book_page=label or None,
                source_url=driver.page.url,
                screenshot_path=screenshot,
                ocr_json={"status": "no_result_cards", "property_address": property_address or None},
            )
        ]

    if search_limit and search_limit > 0:
        all_metadata = all_metadata[:search_limit]
    await driver._emit_status(
        f"Miami-Dade recorder: downloading {len(all_metadata)} result document(s) "
        f"for {label or 'search'} before moving to the next name..."
    )

    documents: list[RecordedDocument] = []
    results_page = driver.page

    for idx, metadata in enumerate(all_metadata):
        await driver._emit_status(
            f"Miami-Dade recorder: processing result {idx + 1} of {len(all_metadata)}..."
        )

        if idx > 0:
            await _close_stale_recordpage_tabs(driver, keep=results_page)
            await driver.set_active_page(results_page)
            if "searchresults" not in driver.page.url.lower():
                try:
                    await driver.page.goto(search_results_url, wait_until="domcontentloaded")
                except Exception as exc:
                    logger.debug("Failed to return to search results page: %s", exc)
            await driver.polite_delay(1.5)

        card_book, card_page = _resolve_book_page_numbers(metadata, "", "")
        card_metadata = await _scrape_miami_dade_search_result_card_metadata(driver, idx)
        if card_metadata:
            metadata = _merge_search_result_metadata(card_metadata, metadata)

        opened = await _open_search_result_at_index(driver, idx)
        if not opened:
            await driver._emit_status(
                f"Could not open search result #{idx + 1}; skipping document download."
            )
            continue

        await driver.polite_delay(2.0)
        await driver.save_browser_preview()

        record_meta = await _scrape_first_result_metadata(driver)
        metadata = _merge_search_result_metadata(card_metadata or metadata, record_meta or {})
        if card_book and card_page and prefer_fallback_book_page:
            metadata["book_page"] = format_book_page_label(card_book, card_page)
        elif card_book and card_page:
            metadata["book_page"] = format_book_page_label(card_book, card_page)

        book_number, page_number = _resolve_book_page_numbers(
            metadata,
            fallback_book,
            fallback_page,
            prefer_fallback=prefer_fallback_book_page,
        )
        if not prefer_fallback_book_page and card_book and card_page:
            book_number, page_number = card_book, card_page
        if prefer_fallback_book_page and fallback_book and fallback_page:
            scraped_book, scraped_page = _resolve_book_page_numbers(metadata, "", "")
            if scraped_book and scraped_page and (
                scraped_book != fallback_book or scraped_page != fallback_page
            ):
                await driver._emit_status(
                    "Warning: recorder page shows book "
                    f"{scraped_book}/{scraped_page} but requested "
                    f"{fallback_book}/{fallback_page}; using requested book/page."
                )
        if not book_number or not page_number:
            await driver._emit_status(
                f"Result #{idx + 1} missing book/page metadata; skipping PDF download."
            )
            continue

        metadata["source_url"] = driver.page.url
        party_names = await _collect_document_party_names(driver, metadata)

        await _open_document_image(driver)
        await driver.polite_delay(2.0)
        await driver.save_browser_preview()

        # Only explicit party-name searches should be tagged as name_searcher.
        # search_label is display-only (book/page, address, etc.) and must not become searched_name.
        effective_searched_name = searched_name.strip() if searched_name and searched_name.strip() else ""
        pdf_path = await _download_document_pdf(
            driver,
            book_number,
            page_number,
            metadata=metadata,
            result_index=idx,
            searched_name=effective_searched_name,
        )
        if not pdf_path:
            pdf_path = await driver.screenshot_on_failure(f"miami_dade_document_image_{idx + 1}")
        await driver.save_browser_preview()

        documents.append(
            apply_party_names_to_recorded_document(
                _build_recorded_document(
                    metadata,
                    book_number,
                    page_number,
                    pdf_path,
                    book_type=book_type,
                    property_address=metadata.get("property_address") or property_address,
                    result_index=idx,
                    searched_name=effective_searched_name,
                ),
                party_names,
            )
        )

        for pg in list(driver.context.pages):
            if pg != results_page and "recordpage" in pg.url.lower():
                try:
                    await pg.close()
                except Exception:
                    pass

    await _close_stale_recordpage_tabs(driver, keep=results_page)
    if driver._page_is_alive(results_page):
        await driver.set_active_page(results_page)
    if reset_session_after:
        await _reset_miami_dade_recorder_session(driver)

    if not documents:
        if prefer_fallback_book_page:
            return []
        screenshot = await driver.screenshot_on_failure("miami_dade_download_failed")
        return [
            RecordedDocument(
                document_type="Search Result",
                book_page=label or None,
                source_url=driver.page.url,
                screenshot_path=screenshot,
                ocr_json={"status": "download_failed", "property_address": property_address or None},
            )
        ]

    await driver._emit_status(
        f"Miami-Dade recorder: downloaded {len(documents)} document(s) for {label or 'search'}."
    )
    return documents


async def _scrape_miami_dade_search_result_card_metadata(
    driver: "BaseDriver",
    index: int,
) -> dict[str, str]:
    """Scrape one SearchResults card before opening its record detail page."""
    try:
        result = await driver.page.evaluate(
            """(index) => {
                const cards = [...document.querySelectorAll('.TitleSearchTab')];
                const card = cards[index];
                if (!card) return {};

                const text = card.innerText || '';
                const getAfter = (label) => {
                    const reNext = new RegExp(label + '\\\\s*:?\\\\s*\\n+([^\\n]+)', 'i');
                    const m = text.match(reNext);
                    if (m && m[1]) {
                        const val = m[1].trim();
                        if (!/(party name|document type|rec date|rec book|clerk|address|misc ref|block number|plat book)/i.test(val)) {
                            return val.split(',')[0].trim();
                        }
                    }
                    const reSame = new RegExp(label + '\\\\s*:\\\\s*([^\\n,]+)', 'i');
                    const m2 = text.match(reSame);
                    if (m2 && m2[1]) return m2[1].trim();
                    return '';
                };

                const cfnMatch = text.match(/(\\b20\\d\\d\\s*R\\s*\\d+)/i);
                const clerkFile = getAfter("Clerk's File Number") || getAfter('Clerk File Number') || '';
                const docType = getAfter('Document Type') || '';
                const bookPage = getAfter('Rec(?:ording)? Book\\\\/Page') || getAfter('Rec Book\\\\/Page') || '';
                const recDate = getAfter('Rec(?:ording)? Date') || getAfter('Rec Date') || '';
                const legal = getAfter('Legal Description') || '';
                const partyVal = getAfter('Party Name') || '';
                let grantor = '';
                let grantee = '';
                if (partyVal && partyVal.includes('/')) {
                    const parts = partyVal.split('/');
                    grantee = parts[0].trim();
                    grantor = parts.slice(1).join('/').trim();
                }

                return {
                    instrument_number: (clerkFile || (cfnMatch ? cfnMatch[1].trim() : '')).split(',')[0].trim(),
                    book_page: bookPage,
                    document_type: docType,
                    recording_date: recDate,
                    grantor,
                    grantee,
                    legal_description: legal,
                    property_address: getAfter('Address') || '',
                    party_name: partyVal,
                    card_index: String(index),
                };
            }""",
            index,
        )
        return result or {}
    except Exception as exc:
        logger.debug("Could not scrape Miami-Dade search result card #%s: %s", index + 1, exc)
        return {}


def _merge_search_result_metadata(
    card_metadata: dict[str, str],
    record_metadata: dict[str, str],
) -> dict[str, str]:
    """Prefer SearchResults card fields, then fill gaps from the record detail page."""
    merged = dict(record_metadata or {})
    card = card_metadata or {}
    for key in (
        "property_address",
        "party_name",
        "grantor",
        "grantee",
        "document_type",
        "recording_date",
        "instrument_number",
        "book_page",
        "legal_description",
    ):
        value = card.get(key)
        if value and str(value).strip():
            merged[key] = str(value).strip()
    for key, value in (record_metadata or {}).items():
        if not str(merged.get(key) or "").strip() and value and str(value).strip():
            merged[key] = str(value).strip()
    return merged


async def _scrape_all_search_results_metadata(
    driver: "BaseDriver",
    *,
    scroll_first: bool = False,
) -> list[dict[str, str]]:
    try:
        results = await driver.page.evaluate(
            """async (scrollFirst) => {
                const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                if (scrollFirst) {
                    let previous = 0;
                    for (let i = 0; i < 30; i++) {
                        window.scrollTo(0, document.body.scrollHeight);
                        await sleep(350);
                        const count = document.querySelectorAll('.TitleSearchTab').length;
                        if (count > 0 && count === previous && i > 2) break;
                        previous = count;
                    }
                    window.scrollTo(0, 0);
                    await sleep(300);
                }

                const cards = [...document.querySelectorAll('.TitleSearchTab')];
                const scrapeCard = (text) => {
                    const getAfter = (label) => {
                        const reNext = new RegExp(label + '\\\\s*:?\\\\s*\\n+([^\\n]+)', 'i');
                        const m = text.match(reNext);
                        if (m && m[1]) {
                            const val = m[1].trim();
                            if (!/(party name|document type|rec date|rec book|clerk|address|misc ref|block number|plat book)/i.test(val)) {
                                return val.split(',')[0].trim();
                            }
                        }
                        const reSame = new RegExp(label + '\\\\s*:\\\\s*([^\\n,]+)', 'i');
                        const m2 = text.match(reSame);
                        if (m2 && m2[1]) return m2[1].trim();
                        return '';
                    };

                    const cfnMatch = text.match(/(\\b20\\d\\d\\s*R\\s*\\d+)/i);
                    const clerkFile = getAfter("Clerk's File Number") || getAfter('Clerk File Number') || '';

                    const docType = getAfter('Document Type') || '';
                    const bookPage = getAfter('Rec(?:ording)? Book\\\\/Page') || getAfter('Rec Book\\\\/Page') || '';
                    const recDate = getAfter('Rec(?:ording)? Date') || getAfter('Rec Date') || '';
                    const legal = getAfter('Legal Description') || '';
                    const partyVal = getAfter('Party Name') || '';
                    let grantor = '';
                    let grantee = '';
                    if (partyVal && partyVal.includes('/')) {
                        const parts = partyVal.split('/');
                        grantee = parts[0].trim();
                        grantor = parts.slice(1).join('/').trim();
                    }

                    return {
                        instrument_number: (clerkFile || (cfnMatch ? cfnMatch[1].trim() : '')).split(',')[0].trim(),
                        book_page: bookPage,
                        document_type: docType,
                        recording_date: recDate,
                        grantor,
                        grantee,
                        legal_description: legal,
                        property_address: getAfter('Address') || '',
                        party_name: partyVal,
                    };
                };

                const scraped = [];
                for (let i = 0; i < cards.length; i++) {
                    const item = scrapeCard(cards[i].innerText || '');
                    item.card_index = String(i);
                    if (item.instrument_number || item.book_page || item.party_name) {
                        scraped.push(item);
                    }
                }
                return scraped;
            }""",
            scroll_first,
        )
        return results or []
    except Exception as exc:
        logger.debug("Could not scrape all Miami-Dade result metadata: %s", exc)
        return []


async def _close_stale_recordpage_tabs(driver: "BaseDriver", *, keep: Any = None) -> None:
    """Close record detail tabs so the next search result opens on the correct document."""
    for pg in list(driver.context.pages):
        if keep is not None and pg == keep:
            continue
        try:
            if "recordpage" in pg.url.lower():
                await pg.close()
        except Exception:
            pass

    if not driver._page_is_alive():
        await driver.ensure_page_alive()


async def _reset_miami_dade_recorder_session(
    driver: "BaseDriver",
    *,
    recorder_home_url: str = MIAMI_DADE_RECORDER_SEARCH_URL,
) -> bool:
    """Recover a live Miami-Dade recorder tab before the next queued book/page search."""
    await _close_stale_recordpage_tabs(driver)
    if not await driver.ensure_page_alive():
        return False

    survivor = None
    for pg in list(driver.context.pages):
        if not driver._page_is_alive(pg):
            continue
        try:
            url = pg.url.lower()
        except Exception:
            continue
        if "officialrecords" in url and "recordpage" not in url and not url.endswith(".pdf"):
            survivor = pg
            break

    if survivor is not None:
        await driver.set_active_page(survivor)
        return True

    try:
        await driver._emit_status("Resetting Miami-Dade recorder browser tab for next book/page...")
        await driver.page.goto(recorder_home_url, wait_until="domcontentloaded", timeout=60_000)
        await driver.polite_delay(1.5)
        return True
    except Exception as exc:
        logger.warning("Could not reset Miami-Dade recorder session: %s", exc)
        return await driver.ensure_page_alive()


async def _open_search_result_at_index(driver: "BaseDriver", index: int) -> bool:
    current_url = driver.page.url.lower()
    if "recordpage" in current_url:
        if index == 0:
            await driver.save_browser_preview()
            return True
        await _close_stale_recordpage_tabs(driver)

    await driver._emit_status(f"Opening search result #{index + 1} in record detail page...")

    for sel in (".TitleSearchTabExpand", ".TitleSearchTab"):
        try:
            targets = driver.page.locator(sel)
            count = await targets.count()
            if count <= index:
                continue
            target = targets.nth(index)
            if not await target.is_visible(timeout=2_000):
                continue
            await target.scroll_into_view_if_needed()
            expand = target.locator(".TitleSearchTabExpand, [class*='expand' i], button").first
            try:
                if await expand.count() > 0 and await expand.is_visible(timeout=500):
                    target = expand
            except Exception:
                pass
            try:
                async with driver.context.expect_page(timeout=15_000) as page_info:
                    await target.click(timeout=5_000)
                popup = await page_info.value
                await popup.wait_for_load_state("domcontentloaded")
                await driver.set_active_page(popup)
                await driver._emit_status(f"Opened record details for result #{index + 1}.")
                return True
            except Exception as exc:
                logger.debug("Result click expect_page failed on %s: %s", sel, exc)
                try:
                    await target.click(timeout=3_000)
                    await driver.polite_delay(2.0)
                    if "recordpage" in driver.page.url.lower():
                        await driver._emit_status(f"Opened record details for result #{index + 1}.")
                        return True
                except Exception as click_exc:
                    logger.debug("Result click retry failed on %s: %s", sel, click_exc)
        except Exception as exc:
            logger.debug("Search result selector %s failed: %s", sel, exc)

    return False


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

                const docType = getAfter('Document Type') || getAfter("Clerk's File Number") || '';
                const bookPage = getAfter('Rec(?:ording)? Book\\/Page') || getAfter('Rec Book\\/Page') || '';
                const recDate = getAfter('Rec(?:ording)? Date') || getAfter('Rec Date') || '';
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
                    instrument_number: cfnMatch ? cfnMatch[1].trim() : '',
                    book_page: bookPage,
                    document_type: docType,
                    recording_date: recDate,
                    grantor,
                    grantee,
                    legal_description: [legal, subdiv].filter(Boolean).join(', '),
                    property_address: getAfter('Address') || '',
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
    if "recordpage" in driver.page.url.lower():
        await driver.set_active_page(driver.page)
        await driver._emit_status("Opened record details in new page.")
        return True

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


def _sanitize_storage_slug(value: str, *, max_len: int = 48) -> str:
    slug = re.sub(r"[^\w]+", "_", (value or "").strip().upper()).strip("_")
    return slug[:max_len] if slug else "unknown"


def _recorder_pdf_storage_key(
    book_number: str,
    page_number: str,
    metadata: Optional[dict[str, Any]] = None,
    *,
    result_index: int = 0,
    searched_name: str = "",
) -> tuple[str, str]:
    """Build unique folder/file names so multiple results for one book/page do not overwrite."""
    suffix = f"_{result_index + 1}" if result_index > 0 else ""
    inst = str((metadata or {}).get("instrument_number") or "").strip()
    inst_clean = re.sub(r"[^\w]+", "_", inst).strip("_")
    if inst_clean and result_index > 0:
        suffix = f"_{inst_clean}_{result_index + 1}"
    elif inst_clean:
        suffix = f"_{inst_clean}"
    leaf = f"{book_number}_{page_number}{suffix}"
    if searched_name.strip():
        name_slug = _sanitize_storage_slug(searched_name)
        folder_name = f"name_search/{name_slug}/{leaf}"
        pdf_filename = f"{leaf}.pdf"
    else:
        folder_name = f"recorder_{book_number}_{page_number}{suffix}"
        pdf_filename = f"{folder_name}.pdf"
    return folder_name, pdf_filename


async def _download_document_pdf(
    driver: "BaseDriver",
    book_number: str,
    page_number: str,
    metadata: Optional[dict[str, Any]] = None,
    *,
    result_index: int = 0,
    searched_name: str = "",
) -> Optional[str]:
    folder_name, pdf_filename = _recorder_pdf_storage_key(
        book_number,
        page_number,
        metadata,
        result_index=result_index,
        searched_name=searched_name,
    )
    png_filename = pdf_filename.replace(".pdf", ".png")

    local_storage_dir = Path("local_storage").resolve() / folder_name
    local_storage_dir.mkdir(parents=True, exist_ok=True)

    downloads_dir = Path("downloads").resolve() / folder_name
    downloads_dir.mkdir(parents=True, exist_ok=True)

    screenshot_dir = driver.screenshot_dir.resolve()
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_folder = screenshot_dir / folder_name
    screenshot_folder.mkdir(parents=True, exist_ok=True)

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
        "instrument_number": meta.get("instrument_number"),
        "document_type": meta.get("document_type"),
        "recording_date": meta.get("recording_date"),
        "grantor": meta.get("grantor"),
        "grantee": meta.get("grantee"),
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
            await loc.scroll_into_view_if_needed()
            await loc.click()
            await driver.polite_delay(0.05)
            await driver.page.keyboard.press("Control+A")
            await driver.page.keyboard.press("Backspace")
            try:
                await loc.press_sequentially(value, delay=30)
            except Exception:
                await loc.fill(value)
            await driver.polite_delay(0.1)
            curr = await loc.input_value()
            if curr != value:
                await loc.evaluate(_SET_REACT_INPUT_VALUE_JS, value)
                curr = await loc.input_value()
            await loc.blur()
            await driver.polite_delay(0.15)
            if curr == value:
                return True
        except Exception:
            continue
    return False
