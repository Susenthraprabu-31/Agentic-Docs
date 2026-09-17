"""Execute user Playwright instructions from node editor text fields."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from app.extraction.book_page import parse_book_page
from app.drivers.recorder.miami_dade_recorder import select_miami_dade_book_type, DEFAULT_MIAMI_DADE_BOOK_TYPE
from app.extraction.schemas import QueryType
from app.drivers.recorder.acclaimweb_recorder import resolve_party_type_from_notes

if TYPE_CHECKING:
    from app.drivers.base.base_driver import BaseDriver

logger = logging.getLogger(__name__)

ADDRESS_TAB_SELECTORS = [
    '[role="tab"]:has-text("Address")',
    'button:has-text("Address")',
    'a:has-text("Address")',
    'mat-tab:has-text("Address")',
    '#address-tab',
    '[data-tab="address"]',
]

OWNER_TAB_SELECTORS = [
    '[role="tab"]:has-text("Owner")',
    'button:has-text("Owner Name")',
    'button:has-text("Owner")',
    'a:has-text("Owner")',
]

PARCEL_TAB_SELECTORS = [
    '[role="tab"]:has-text("Folio")',
    '[role="tab"]:has-text("Parcel")',
    'button:has-text("Folio")',
    'button:has-text("Parcel")',
]

ADDRESS_INPUT_SELECTORS = [
    'input[placeholder*="address" i]',
    'input[formcontrolname*="address" i]',
    'input[name*="address" i]',
    'input[id*="address" i]',
    'input[aria-label*="address" i]',
]

OWNER_INPUT_SELECTORS = [
    'input[placeholder*="owner" i]',
    'input[formcontrolname*="owner" i]',
    'input[name*="owner" i]',
    'input[id*="owner" i]',
]

PARCEL_INPUT_SELECTORS = [
    'input[placeholder*="folio" i]',
    'input[placeholder*="parcel" i]',
    'input[formcontrolname*="folio" i]',
    'input[name*="parcel" i]',
]

BOOK_PAGE_TAB_SELECTORS = [
    'a:has-text("Recording Book/Page")',
    'span:has-text("Recording Book/Page")',
    'li:has-text("Recording Book/Page") a',
    'button:has-text("Book/Page")',
]

BOOK_INPUT_SELECTORS = [
    'input[placeholder="BOOK" i]',
    'input[placeholder*="book" i]',
    'input[name*="book" i]',
    'input[id*="book" i]',
]

PAGE_INPUT_SELECTORS = [
    'input[placeholder="PAGE" i]',
    'input[placeholder*="page" i]',
    'input[name*="page" i]',
    'input[id*="page" i]',
]

SEARCH_BUTTON_SELECTORS = [
    'button:has-text("Search")',
    'input[type="submit"]',
    'button[type="submit"]',
    'input[value*="Search" i]',
    '[aria-label*="search" i]',
    'img[alt*="search" i]',
]

GRANTOR_RADIO_SELECTORS = [
    "#Direct",
    'input[type="radio"][value="Direct"]',
    'input[type="radio"][value*="Grantor" i]',
    'label:has-text("Grantor")',
]

GRANTEE_RADIO_SELECTORS = [
    "#Reverse",
    'input[type="radio"][value="Reverse"]',
    'input[type="radio"][value*="Grantee" i]',
    'label:has-text("Grantee")',
]

ALL_PARTY_RADIO_SELECTORS = [
    "#Both",
    'input[type="radio"][value="Both"]',
    'label:has-text("All")',
]

RECORDER_SEARCH_BUTTON_SELECTORS = [
    "#btnSearch",
    'input[type="submit"][value="Search"]',
    'button:has-text("Search")',
    'input[type="submit"]',
]

RESULT_ROW_SELECTORS = [
    "table tbody tr a",
    "table tbody tr",
    "mat-row",
    ".result-row",
    ".search-result",
    "tr.hv",
    '[class*="result" i] a',
    '[class*="card" i] button[aria-label*="Expand" i]',
    'a:has-text("Clerk\'s File Number")',
]


def _extract_click_link_text(notes: str) -> str | None:
    """Pull link/button label from phrases like: click the Search Records and Tax Details."""
    quoted = re.search(r'click\s+(?:the\s+)?["\']([^"\']+)["\']', notes, re.I)
    if quoted:
        return quoted.group(1).strip()

    match = re.search(
        r"click\s+(?:the\s+)?(.+?)(?:\s+then\b|\s*,\s*|\s+and\s+(?:fill|enter|type|wait|click|press)\b|$)",
        notes,
        re.I,
    )
    if not match:
        return None

    text = match.group(1).strip().rstrip(".")
    generic = {
        "address",
        "owner",
        "parcel",
        "folio",
        "search",
        "search button",
        "submit",
        "tab",
        "address tab",
        "owner tab",
        "parcel tab",
    }
    if text.lower() in generic:
        return None
    return text or None


async def _click_by_visible_text(driver: "BaseDriver", text: str) -> bool:
    """Click a nav link or button whose visible label matches user instruction text."""
    raw = text.strip()
    if not raw:
        return False

    variants: list[str] = []
    for candidate in (raw, raw.upper(), raw.title(), " ".join(word.capitalize() for word in raw.split())):
        cleaned = candidate.strip()
        if cleaned and cleaned not in variants:
            variants.append(cleaned)

    for variant in variants:
        try:
            link = driver.page.get_by_role("link", name=re.compile(re.escape(variant), re.I))
            if await link.count() > 0 and await link.first.is_visible(timeout=2_000):
                await link.first.click(force=True)
                await driver.polite_delay(1.0)
                return True
        except Exception as exc:
            logger.debug("Role link click failed for %r: %s", variant, exc)

        for sel in (
            f'a:has-text("{variant}")',
            f'button:has-text("{variant}")',
            f'[role="button"]:has-text("{variant}")',
            f'nav a:has-text("{variant}")',
            f'li a:has-text("{variant}")',
        ):
            if await _click_first_visible(driver, [sel], timeout_ms=2_000):
                return True

    # Fuzzy: match longest substring of consecutive words (handles minor wording differences)
    words = [w for w in re.split(r"\s+", raw) if len(w) > 2]
    for length in range(len(words), 1, -1):
        for start in range(0, len(words) - length + 1):
            phrase = " ".join(words[start : start + length])
            try:
                link = driver.page.get_by_role("link", name=re.compile(re.escape(phrase), re.I))
                if await link.count() > 0 and await link.first.is_visible(timeout=1_500):
                    await link.first.click(force=True)
                    await driver.polite_delay(1.0)
                    return True
            except Exception:
                pass
    return False


async def _click_first_visible(driver: "BaseDriver", selectors: list[str], timeout_ms: int = 3000) -> bool:
    for sel in selectors:
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible(timeout=timeout_ms):
                await loc.click(force=True)
                await driver.polite_delay(0.5)
                return True
        except Exception as exc:
            logger.debug("Click failed for %s: %s", sel, exc)
    return False


async def _fill_first_visible(driver: "BaseDriver", selectors: list[str], value: str) -> bool:
    if not value:
        return False
    for sel in selectors:
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible(timeout=3000):
                await loc.click()
                await loc.fill(value)
                return True
        except Exception as exc:
            logger.debug("Fill failed for %s: %s", sel, exc)
    return False


def _selectors_for_query_type(query_type: QueryType) -> tuple[list[str], list[str]]:
    if query_type == QueryType.ADDRESS:
        return ADDRESS_TAB_SELECTORS, ADDRESS_INPUT_SELECTORS
    if query_type == QueryType.OWNER:
        return OWNER_TAB_SELECTORS, OWNER_INPUT_SELECTORS
    if query_type == QueryType.BOOK_PAGE:
        return BOOK_PAGE_TAB_SELECTORS, BOOK_INPUT_SELECTORS
    return PARCEL_TAB_SELECTORS, PARCEL_INPUT_SELECTORS


async def apply_playwright_instructions(
    driver: "BaseDriver",
    notes: str,
    query_type: QueryType,
    query_value: str,
    *,
    portal_type: str = "assessor",
) -> bool:
    """
    Parse natural-language Playwright instructions and perform actions.
    Returns True if at least one action succeeded.
    """
    if not notes or not notes.strip():
        return False

    if isinstance(query_value, QueryType):
        logger.warning("apply_playwright_instructions: query_value was QueryType — check call site argument order")
        query_value = ""

    notes_lower = notes.lower()
    await driver._emit_status(f"Applying Playwright instructions: {notes[:80]}...")

    tab_selectors, input_selectors = _selectors_for_query_type(query_type)
    if portal_type == "recorder":
        input_selectors = [
            "#SearchOnName",
            'input[name="SearchOnName"]',
            'input[name*="name" i]',
            'input[name*="grantor" i]',
            'input[name*="grantee" i]',
            'input[name*="party" i]',
            'input[placeholder*="name" i]',
            'input[id*="name" i]',
            'input[name*="folio" i]',
            'input[name*="instrument" i]',
            'input[name*="parcel" i]',
        ] + input_selectors
        if query_type == QueryType.BOOK_PAGE:
            input_selectors = BOOK_INPUT_SELECTORS + PAGE_INPUT_SELECTORS

    acted = False
    filled = False

    link_text = _extract_click_link_text(notes)
    if link_text and "click" in notes_lower:
        await driver._emit_status(f"Playwright: clicking link «{link_text}»...")
        acted = await _click_by_visible_text(driver, link_text) or acted

    skip_patterns = (
        "auto-scrape publicrecords",
        "maps portal urls to platform",
        "merge & deduplicate",
        "generate pdf report",
        "finalize run results",
    )
    if any(p in notes_lower for p in skip_patterns):
        return False

    if portal_type == "recorder":
        party = resolve_party_type_from_notes(notes)
        if party == "grantee":
            await driver._emit_status("Playwright: selecting Grantee...")
            acted = await _click_first_visible(driver, GRANTEE_RADIO_SELECTORS) or acted
        elif party == "grantor":
            await driver._emit_status("Playwright: selecting Grantor...")
            acted = await _click_first_visible(driver, GRANTOR_RADIO_SELECTORS) or acted
        elif party == "all":
            await driver._emit_status("Playwright: selecting All parties...")
            acted = await _click_first_visible(driver, ALL_PARTY_RADIO_SELECTORS) or acted

    # Tab selection — honor explicit note keywords, else use query_type when notes mention tabs
    if any(k in notes_lower for k in ("address tab", "address search", "click address")):
        acted = await _click_first_visible(driver, ADDRESS_TAB_SELECTORS) or acted
    elif any(k in notes_lower for k in ("owner tab", "owner search", "click owner")):
        acted = await _click_first_visible(driver, OWNER_TAB_SELECTORS) or acted
    elif any(k in notes_lower for k in ("parcel tab", "folio tab", "click parcel", "click folio")):
        acted = await _click_first_visible(driver, PARCEL_TAB_SELECTORS) or acted
    elif any(k in notes_lower for k in ("book/page", "book page", "recording book")):
        acted = await _click_first_visible(driver, BOOK_PAGE_TAB_SELECTORS) or acted
    elif link_text:
        pass  # navigation link already handled above
    elif any(k in notes_lower for k in ("click", "tab", "open")):
        acted = await _click_first_visible(driver, tab_selectors) or acted

    # Custom CSS selector in notes: selector: #myInput or fill #myInput
    selector_match = re.search(r"(?:selector|fill|click)\s*[:=]?\s*([#.\[][\w\-\[\]=\"' .]+)", notes, re.I)
    custom_selector = selector_match.group(1).strip() if selector_match else None

    fill_value = str(query_value).strip() if query_value else ""
    if fill_value.lower() in {t.value for t in QueryType} and fill_value.lower() == query_type.value:
        logger.warning("Refusing to fill search field with query type %r instead of a name", fill_value)
        fill_value = ""

    should_fill = fill_value and (
        portal_type == "recorder"
        or any(k in notes_lower for k in ("fill", "enter", "type", "input", "search field", "wait for results"))
    )
    if should_fill and query_type == QueryType.BOOK_PAGE:
        book_page_parts = parse_book_page(fill_value)
        if book_page_parts:
            book_number, page_number = book_page_parts
            book_filled = await _fill_first_visible(driver, BOOK_INPUT_SELECTORS, book_number)
            page_filled = await _fill_first_visible(driver, PAGE_INPUT_SELECTORS, page_number)
            if book_filled and page_filled:
                await select_miami_dade_book_type(driver, DEFAULT_MIAMI_DADE_BOOK_TYPE)
            filled = book_filled and page_filled
            acted = filled or acted
    elif should_fill:
        if custom_selector:
            try:
                loc = driver.page.locator(custom_selector).first
                if await loc.count() > 0:
                    await loc.click()
                    await loc.fill(fill_value)
                    filled = True
                    acted = True
            except Exception as exc:
                logger.debug("Custom selector fill failed: %s", exc)
        else:
            filled = await _fill_first_visible(driver, input_selectors, fill_value)
            if not filled:
                filled = await _fill_first_visible(
                    driver, ['input[type="text"]', 'input[type="search"]'], fill_value
                )
            acted = filled or acted

    # Submit search when instructions mention search, or after a successful fill
    should_search = portal_type == "recorder" or any(
        k in notes_lower for k in ("search", "submit", "run search", "click search", "press enter", "wait for results")
    )
    search_buttons = RECORDER_SEARCH_BUTTON_SELECTORS if portal_type == "recorder" else SEARCH_BUTTON_SELECTORS
    if filled or should_search:
        if await _click_first_visible(driver, search_buttons):
            acted = True
            await driver.polite_delay(2.0)
        else:
            try:
                await driver.page.keyboard.press("Enter")
                acted = True
                await driver.polite_delay(2.0)
            except Exception:
                pass

    return acted


async def apply_playwright_post_search(driver: "BaseDriver", notes: str) -> bool:
    """Run post-search steps from instructions (e.g. expand first result row)."""
    if not notes or not notes.strip():
        return False
    notes_lower = notes.lower()
    if not any(k in notes_lower for k in ("expand", "open", "click")) or not any(
        k in notes_lower for k in ("result", "row", "first")
    ):
        return False

    await driver.polite_delay(2.0)
    for sel in [
        '.t-window-titlebar-close',
        'a:has-text("Close")',
        'button:has-text("Close")',
    ]:
        try:
            close = driver.page.locator(sel).first
            if await close.count() > 0 and await close.is_visible(timeout=1_000):
                text = (await driver.page.locator(".t-window-content").inner_text()).lower()
                if "no names found" in text or "try your search again" in text:
                    await driver._emit_status("No matching names found for this search.")
                    await close.click(force=True)
                    return False
        except Exception:
            pass

    await driver._emit_status("Expanding first search result (Playwright instructions)...")
    opened = await _click_first_visible(driver, RESULT_ROW_SELECTORS)
    if not opened:
        return False

    notes_lower = notes.lower()
    if "document image" in notes_lower:
        await driver._emit_status("Opening Document Image (Playwright instructions)...")
        for sel in [
            'a:has-text("Document Image")',
            'span:has-text("Document Image")',
            'li:has-text("Document Image") a',
        ]:
            if await _click_first_visible(driver, [sel]):
                await driver.polite_delay(2.0)
                break
    return True
