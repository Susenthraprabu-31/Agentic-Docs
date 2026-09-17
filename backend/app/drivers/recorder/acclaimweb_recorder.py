"""Harris AcclaimWeb official records portals (Brevard, Broward, etc.)."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from app.extraction.schemas import QueryType

if TYPE_CHECKING:
    from app.drivers.recorder.gila_recorder_driver import GilaRecorderDriver

logger = logging.getLogger(__name__)

ACCLAIM_NAME_SEARCH_PATH = "/AcclaimWeb/search/SearchTypeName"
ACCLAIM_DISCLAIMER_PATH = "/AcclaimWeb/search/Disclaimer?st=/AcclaimWeb/search/SearchTypeName"

SEARCH_ON_NAME = "#SearchOnName"
SEARCH_BUTTON = "#btnSearch"
GRANTOR_RADIO = "#Direct"
GRANTEE_RADIO = "#Reverse"
ALL_PARTIES_RADIO = "#Both"
DISCLAIMER_BUTTON = "#btnButton"


def resolve_party_type_from_notes(notes: str) -> str | None:
    """
    Parse party type from Playwright instructions.
    Returns grantor, grantee, all, or None to leave the site default (usually All).
    """
    if not notes or not notes.strip():
        return None
    notes_lower = notes.lower()
    if "grantee" in notes_lower:
        return "grantee"
    if "grantor" in notes_lower:
        return "grantor"
    if any(
        phrase in notes_lower
        for phrase in (
            "all name",
            "search by all",
            "by all name",
            "all parties",
            "party all",
            "search all",
        )
    ):
        return "all"
    if re.search(r"\ball\b", notes_lower) and "name" in notes_lower:
        return "all"
    return None


def is_acclaimweb_recorder(url: str) -> bool:
    return "acclaimweb" in (url or "").lower()


def _acclaim_base_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


async def prepare_acclaimweb_name_search(driver: "GilaRecorderDriver", page_url: str) -> bool:
    """Navigate to party name search and accept disclaimer."""
    base = _acclaim_base_url(page_url or driver.page.url)
    target = urljoin(base, ACCLAIM_NAME_SEARCH_PATH)

    if ACCLAIM_NAME_SEARCH_PATH.lower() not in driver.page.url.lower():
        await driver._emit_status("Opening AcclaimWeb party name search...")
        await driver.safe_goto(target, timeout=90_000)
        await driver.polite_delay(1.5)

    if not await _accept_acclaimweb_disclaimer(driver, base):
        await driver._emit_status("Waiting for AcclaimWeb disclaimer...")
        if not await _accept_acclaimweb_disclaimer(driver, base):
            return False

    try:
        await driver.page.wait_for_selector(SEARCH_ON_NAME, state="visible", timeout=20_000)
        return True
    except Exception:
        return await driver.page.locator(SEARCH_ON_NAME).is_visible()


async def _accept_acclaimweb_disclaimer(driver: "GilaRecorderDriver", base: str) -> bool:
    if await driver.page.locator(SEARCH_ON_NAME).is_visible():
        return True

    for sel in [
        DISCLAIMER_BUTTON,
        'input[type="submit"][value*="accept" i]',
        'input#btnButton',
        'button:has-text("I accept")',
    ]:
        try:
            btn = driver.page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible(timeout=3_000):
                await driver._emit_status("Accepting AcclaimWeb disclaimer...")
                await btn.click(force=True)
                await driver.page.wait_for_load_state("domcontentloaded")
                await driver.polite_delay(2.0)
                if await driver.page.locator(SEARCH_ON_NAME).is_visible():
                    return True
        except Exception as exc:
            logger.debug("AcclaimWeb disclaimer click failed for %s: %s", sel, exc)

    # Fallback: POST disclaimer form (Brevard uses this pattern)
    try:
        await driver.page.evaluate(
            """async (postUrl) => {
                const form = document.querySelector('form[action*="Disclaimer"]');
                if (!form) return false;
                const data = new FormData(form);
                const body = new URLSearchParams(data).toString();
                const resp = await fetch(postUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body,
                    credentials: 'same-origin',
                });
                if (resp.ok) {
                    document.open();
                    document.write(await resp.text());
                    document.close();
                    return true;
                }
                return false;
            }""",
            urljoin(base, ACCLAIM_DISCLAIMER_PATH),
        )
        await driver.polite_delay(2.0)
        return await driver.page.locator(SEARCH_ON_NAME).is_visible()
    except Exception as exc:
        logger.debug("AcclaimWeb disclaimer POST failed: %s", exc)
    return False


async def _select_party_type_from_notes(driver: "GilaRecorderDriver", notes: str = "") -> None:
    """Only change party type radio when instructions explicitly request it."""
    party = resolve_party_type_from_notes(notes)
    if party == "grantee":
        await driver._emit_status("Selecting Grantee (from Playwright instructions)...")
        await _click_if_visible(driver, GRANTEE_RADIO)
    elif party == "grantor":
        await driver._emit_status("Selecting Grantor (from Playwright instructions)...")
        await _click_if_visible(driver, GRANTOR_RADIO)
    elif party == "all":
        await driver._emit_status("Selecting All parties (from Playwright instructions)...")
        await _click_if_visible(driver, ALL_PARTIES_RADIO)


async def _click_if_visible(driver: "GilaRecorderDriver", selector: str) -> bool:
    try:
        loc = driver.page.locator(selector).first
        if await loc.count() > 0 and await loc.is_visible(timeout=2_000):
            await loc.click(force=True)
            await driver.polite_delay(0.3)
            return True
    except Exception:
        pass
    return False


async def _fill_search_on_name(driver: "GilaRecorderDriver", value: str) -> bool:
    if not value:
        return False
    try:
        loc = driver.page.locator(SEARCH_ON_NAME).first
        await loc.wait_for(state="visible", timeout=10_000)
        await loc.click()
        await loc.fill("")
        try:
            await loc.press_sequentially(value, delay=25)
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
        entered = await loc.input_value()
        return entered.strip() == value.strip() or bool(entered.strip())
    except Exception as exc:
        logger.warning("AcclaimWeb fill failed: %s", exc)
        return False


async def _click_acclaimweb_search(driver: "GilaRecorderDriver") -> bool:
    for sel in [SEARCH_BUTTON, 'input[type="submit"][value="Search"]', 'button:has-text("Search")']:
        if await _click_if_visible(driver, sel):
            try:
                await driver.page.wait_for_load_state("domcontentloaded")
            except Exception:
                pass
            await driver.polite_delay(2.0)
            return True
    return False


async def search_acclaimweb_party_name(
    driver: "GilaRecorderDriver",
    query_type: QueryType,
    query_value: str,
    *,
    notes: str = "",
) -> bool:
    """Fill AcclaimWeb party name search and submit."""
    if not await prepare_acclaimweb_name_search(driver, driver.page.url):
        await driver._emit_status("Could not open AcclaimWeb party name search form.")
        return False

    await _select_party_type_from_notes(driver, notes)
    await driver._emit_status(f"Entering party name: {query_value}")
    if not await _fill_search_on_name(driver, query_value):
        await driver._emit_status("Could not fill AcclaimWeb party name field.")
        return False

    await driver._emit_status("Clicking AcclaimWeb Search...")
    return await _click_acclaimweb_search(driver)


def format_acclaimweb_party_name(query_value: str) -> str:
    value = query_value.strip()
    if not value or "," in value:
        return value
    parts = value.split()
    if len(parts) >= 2 and not re.search(r"\d{3,}", value):
        return f"{parts[-1]}, {' '.join(parts[:-1])}"
    return value
