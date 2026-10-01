"""Florida county assessor automation (Orange, Miami-Dade, Broward, Hillsborough, Schneider)."""

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Optional

from playwright.async_api import Frame

from app.config.florida_portals import (
    BREVARD_SEARCH_URL,
    COLLIER_HOME_URL,
    COLLIER_SEARCH_URL,
    DESOTO_GIS_ENTRY_URL,
    DESOTO_HOME_URL,
    FL_PA_CUSTOM_HOSTS,
    ORANGE_SEARCH_URL,
    get_florida_county_from_url,
    get_florida_pa_county_from_url,
    get_florida_pa_gis_county_from_url,
    is_brevard_assessor,
    is_broward_assessor,
    is_collier_assessor,
    is_desoto_assessor,
    is_florida_pa_assessor,
    is_florida_pa_gis_assessor,
    resolve_florida_pa_gis_url,
    is_hillsborough_assessor,
    is_miami_dade_assessor,
    is_orange_county_assessor,
    normalize_florida_parcel,
    format_florida_pa_address_for_search,
    format_miami_dade_address_for_search,
    MIAMI_DADE_SEARCH_URL,
    normalize_miami_dade_property_search_url,
    normalize_florida_pa_parcel,
    resolve_florida_assessor_url,
)
from app.config.schneider_portals import (
    is_florida_schneider_portal,
    is_honolulu_schneider,
    normalize_schneider_search_url,
)
from app.extraction.florida_extractors import (
    FLORIDA_PA_DETAIL_JS,
    FLORIDA_SCRAPE_JS,
    extract_florida_parcel_from_html,
    extract_valid_miami_dade_folio,
    is_valid_miami_dade_extraction,
    parcel_record_from_florida_data,
    parcel_record_from_florida_pa_detail,
    parcel_record_from_miami_dade_detail,
    MIAMI_DADE_DETAIL_JS,
)
from app.drivers.form_fill import (
    _commit_fill,
    click_property_search_button,
    fill_first_visible_input,
    fill_input_by_accessible_name,
    is_fillable_input,
)
from app.drivers.page_search_ai import execute_ai_page_search
from app.drivers.playwright_instructions import apply_playwright_instructions, is_template_playwright_notes
from app.extraction.schemas import ParcelRecord, QueryType

if TYPE_CHECKING:
    from app.drivers.assessor.gila_assessor_driver import GilaAssessorDriver

logger = logging.getLogger(__name__)

FLORIDA_PARCEL_INPUTS = [
    'input[formcontrolname*="parcel" i]',
    'input[placeholder*="parcel" i]',
    'input[aria-label*="parcel" i]',
    'input[aria-label*="Parcel ID" i]',
    'input[name*="parcel" i]',
    'input[id*="parcel" i]',
    'input[placeholder*="folio" i]',
    'input[aria-label*="folio" i]',
    'input[name*="folio" i]',
    'input[placeholder*="pin" i]',
    'input[name*="pin" i]',
    'input[placeholder*="strap" i]',
]

FLORIDA_OWNER_INPUTS = [
    'input[formcontrolname*="owner" i]',
    'input[placeholder*="owner" i]',
    'input[aria-label*="owner" i]',
    'input[name*="owner" i]',
    'input[id*="owner" i]',
    'input[placeholder*="name" i]',
]

FLORIDA_ADDRESS_INPUTS = [
    'input[formcontrolname*="address" i]',
    'input[placeholder*="address" i]',
    'input[aria-label*="address" i]',
    'input[name*="address" i]',
    'input[id*="address" i]',
    'input[placeholder*="street" i]',
]


async def search_florida_assessor(
    driver: "GilaAssessorDriver",
    assessor_url: str,
    query_type: QueryType,
    query_value: str,
) -> list[ParcelRecord]:
    search_url = resolve_florida_assessor_url(assessor_url)
    if is_florida_schneider_portal(search_url) or is_florida_schneider_portal(assessor_url):
        search_url = normalize_schneider_search_url(search_url)
    county = get_florida_county_from_url(search_url) or get_florida_county_from_url(assessor_url)

    if is_florida_pa_gis_assessor(search_url) or is_florida_pa_gis_assessor(assessor_url):
        pa_county = (
            get_florida_pa_gis_county_from_url(search_url)
            or get_florida_pa_gis_county_from_url(assessor_url)
        )
        gis_url = resolve_florida_pa_gis_url(
            pa_county,
            assessor_url if is_florida_pa_gis_assessor(assessor_url) else search_url,
        )
        return await _search_florida_pa(
            driver,
            gis_url,
            query_type,
            query_value,
            county=pa_county,
            landing_url=search_url,
        )

    if is_miami_dade_assessor(search_url) or is_miami_dade_assessor(assessor_url):
        return await _search_miami_dade(driver, search_url, query_type, query_value)

    if is_orange_county_assessor(search_url) or is_orange_county_assessor(assessor_url):
        return await _search_orange_county(driver, search_url, query_type, query_value)

    if is_brevard_assessor(search_url) or is_brevard_assessor(assessor_url) or county == "brevard":
        return await _search_brevard_bcpao(driver, search_url, query_type, query_value)

    if is_collier_assessor(search_url) or is_collier_assessor(assessor_url) or county == "collier":
        return await _search_collier_appraiser(driver, search_url, query_type, query_value)

    if is_broward_assessor(search_url) or is_broward_assessor(assessor_url):
        return await _search_florida_spa(
            driver, search_url, query_type, query_value, county="broward"
        )

    if is_hillsborough_assessor(search_url) or is_hillsborough_assessor(assessor_url):
        return await _search_florida_spa(
            driver, search_url, query_type, query_value, county="hillsborough"
        )

    if (
        (is_florida_schneider_portal(search_url) or is_florida_schneider_portal(assessor_url))
        and not is_honolulu_schneider(search_url)
        and not is_honolulu_schneider(assessor_url)
    ):
        return await driver._search_qpublic(search_url, query_type, query_value)

    return await _search_florida_spa(driver, search_url, query_type, query_value, county=county)


FLORIDA_PA_RESULTS_JS = """
() => {
  const row = document.querySelector('tr.hv, tr td.pointer[onclick*="Detail"]')?.closest('tr');
  if (!row) return null;
  const cells = [...row.querySelectorAll('td')].map((td) => (td.innerText || '').replace(/\\s+/g, ' ').trim());
  const parcel = (cells[1] || '').replace(/\\s+/g, '');
  const ownerHtml = row.querySelectorAll('td')[2];
  const owner = ownerHtml ? ownerHtml.innerText.replace(/\\s+/g, ' ').trim() : (cells[2] || '');
  return {
    parcel,
    owner,
    address: cells[3] || '',
    legal: cells[4] || '',
    cells,
  };
}
"""


async def _wait_for_florida_pa_gis_shell(driver: "GilaAssessorDriver", timeout_ms: int = 90_000) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        url = driver.page.url.lower()
        if "/gis" in url:
            markers = driver.page.locator("#recordSearch_tabs, #button1, #recordSearch_background")
            if await markers.count() > 0:
                return True
        await asyncio.sleep(0.5)
    return False


async def _open_florida_pa_gis_portal(
    driver: "GilaAssessorDriver",
    gis_entry_url: str,
    *,
    county: str | None = None,
    landing_url: str | None = None,
) -> None:
    """Open a floridapa.com GIS portal, including custom-hosted counties like DeSoto."""
    county_slug = (county or "").lower().replace(" ", "-")
    homepage = landing_url or DESOTO_HOME_URL
    entry = gis_entry_url or DESOTO_GIS_ENTRY_URL

    if county_slug in FL_PA_CUSTOM_HOSTS or is_desoto_assessor(entry) or is_desoto_assessor(homepage):
        await driver._emit_status("Opening DeSoto County Property Appraiser...")
        await driver.safe_goto(homepage)
        await driver.polite_delay(1.5)

        if "/gis" not in driver.page.url.lower():
            await driver._emit_status("Clicking Property Record Search...")
            clicked = False
            for sel in (
                'a[href*="/GIS/"]',
                'a:has-text("Property Record Search")',
                'a:has-text("Record Search / GIS Map")',
            ):
                try:
                    link = driver.page.locator(sel).first
                    if await link.count() > 0 and await link.is_visible(timeout=2_000):
                        await link.click()
                        clicked = True
                        break
                except Exception:
                    continue
            if clicked:
                await driver.page.wait_for_load_state("domcontentloaded")
                await driver.polite_delay(3.0)
            else:
                await driver.page.goto(entry, wait_until="domcontentloaded", timeout=60_000)
        else:
            await driver.page.goto(entry, wait_until="domcontentloaded", timeout=60_000)

        if not await _wait_for_florida_pa_gis_shell(driver):
            await driver._emit_status("Waiting for DeSoto GIS map to finish loading...")
            await driver.polite_delay(3.0)
        return

    await driver.page.goto(entry, wait_until="networkidle", timeout=90_000)


async def _ensure_florida_pa_record_search_tab(driver: "GilaAssessorDriver"):
    search_frame = await _wait_for_florida_pa_frame(driver, "recordSearch_1_Form", timeout_ms=4_000)
    if search_frame:
        return search_frame

    await driver._emit_status("Opening Record Search tab...")
    try:
        await driver.page.evaluate(
            "() => { if (typeof ClickTab === 'function') ClickTab(1, false); }"
        )
    except Exception:
        pass

    for sel in ('#tab1 td[onclick*="ClickTab(1"]', 'td:has-text("Record Search")'):
        try:
            tab = driver.page.locator(sel).first
            if await tab.count() > 0 and await tab.is_visible(timeout=1_500):
                await tab.click()
                break
        except Exception:
            continue

    await driver.polite_delay(1.5)
    return await _wait_for_florida_pa_frame(driver, "recordSearch_1_Form", timeout_ms=25_000)


async def _search_florida_pa(
    driver: "GilaAssessorDriver",
    search_url: str,
    query_type: QueryType,
    query_value: str,
    county: str | None = None,
    landing_url: str | None = None,
) -> list[ParcelRecord]:
    """Columbia and other floridapa.com counties — disclaimer, iframe search, Run Search."""
    county_label = (county or "Florida").replace("-", " ").title()
    await driver._emit_status(f"Opening {county_label} Property Appraiser GIS search...")
    await _open_florida_pa_gis_portal(
        driver,
        search_url,
        county=county,
        landing_url=landing_url,
    )

    await _dismiss_florida_pa_disclaimer(driver)

    search_frame = await _ensure_florida_pa_record_search_tab(driver)
    if not search_frame:
        await driver._emit_status("Could not load property search form.")
        return []

    await _dismiss_florida_pa_disclaimer_in_frame(search_frame)

    filled = False
    parcel_value = normalize_florida_pa_parcel(query_value) if query_type == QueryType.PARCEL else ""
    if query_type == QueryType.PARCEL:
        await driver._emit_status(f"Searching parcel {parcel_value}...")
        filled = await _fill_florida_pa_input(search_frame, "#PIN", parcel_value)
    elif query_type == QueryType.OWNER:
        await driver._emit_status(f"Searching owner {query_value}...")
        filled = await _fill_florida_pa_input(search_frame, "#OwnerName", query_value)
    elif query_type == QueryType.ADDRESS:
        address_query = format_florida_pa_address_for_search(query_value)
        await driver._emit_status(f"Searching address {address_query}...")
        filled = await _fill_florida_pa_input(
            search_frame,
            'input[name="StreetName"]',
            address_query,
        )
    else:
        filled = False

    if not filled:
        await driver._emit_status("Could not find search field on property search form.")
        return []

    await _click_florida_pa_run_search(search_frame)
    await driver.page.wait_for_timeout(2_000)

    results_frame = await _wait_for_florida_pa_frame(driver, "recordSearch_2_Results", timeout_ms=20_000)
    if not results_frame:
        await driver._emit_status("No search results found.")
        return []

    await driver._emit_status("Opening parcel details from search results...")
    if await _open_florida_pa_detail(driver, results_frame):
        await driver.page.wait_for_timeout(2_500)
        detail_records = await _extract_florida_pa_detail(driver, fallback_parcel=parcel_value or None)
        if detail_records:
            return detail_records

    return await _extract_florida_pa_results(driver)


async def _dismiss_florida_pa_disclaimer(driver: "GilaAssessorDriver") -> bool:
    """Click #button1 — 'I agree, please continue' on the main GIS page."""
    for _ in range(20):
        try:
            btn = driver.page.locator("#button1").first
            if await btn.count() > 0 and await btn.is_visible(timeout=400):
                await btn.click(force=True)
                await driver.page.wait_for_timeout(500)
                return True
        except Exception:
            pass

        for sel in [
            'input[value*="I agree, please continue" i]',
            'button:has-text("I agree, please continue")',
        ]:
            try:
                btn = driver.page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible(timeout=300):
                    await btn.click(force=True)
                    await driver.page.wait_for_timeout(500)
                    return True
            except Exception:
                continue
        await driver.page.wait_for_timeout(250)
    return False


async def _dismiss_florida_pa_disclaimer_in_frame(frame) -> bool:
    try:
        btn = frame.locator("#button1").first
        if await btn.count() > 0 and await btn.is_visible(timeout=500):
            await btn.click(force=True)
            await frame.wait_for_timeout(300)
            return True
    except Exception:
        pass
    return False


async def _wait_for_florida_pa_frame(driver: "GilaAssessorDriver", url_part: str, timeout_ms: int = 20_000):
    elapsed = 0
    while elapsed < timeout_ms:
        try:
            if driver.page.is_closed():
                return None
            for frame in driver.page.frames:
                if url_part in frame.url:
                    return frame
            await driver.page.wait_for_timeout(300)
        except Exception as exc:
            if "closed" in str(exc).lower():
                return None
            logger.debug("Florida PA frame wait interrupted: %s", exc)
            return None
        elapsed += 300
    return None


async def _fill_florida_pa_input(frame, selector: str, value: str, timeout_ms: int = 5_000) -> bool:
    for sel in selector.split(","):
        sel = sel.strip()
        if not sel:
            continue
        try:
            loc = frame.locator(sel).first
            await loc.wait_for(state="visible", timeout=timeout_ms)
            await loc.click()
            await loc.fill(value)
            return True
        except Exception as exc:
            logger.debug("Florida PA fill failed for %s: %s", sel, exc)
    return False


async def _click_florida_pa_run_search(frame) -> None:
    for sel in ["#submit_RecordSearch", 'input[name="submit_RecordSearch"]', 'input[value*="Run Search" i]']:
        try:
            btn = frame.locator(sel).first
            if await btn.count() > 0:
                await btn.click(force=True)
                return
        except Exception:
            continue


async def _extract_florida_pa_results(driver: "GilaAssessorDriver") -> list[ParcelRecord]:
    results_frame = await _wait_for_florida_pa_frame(driver, "recordSearch_2_Results", timeout_ms=20_000)
    if not results_frame:
        return []

    try:
        data = await results_frame.evaluate(FLORIDA_PA_RESULTS_JS)
        if data and (data.get("parcel") or data.get("owner")):
            parcel_raw = ""
            cells = data.get("cells") or []
            if len(cells) > 1:
                parcel_raw = str(cells[1])
            else:
                parcel_raw = data.get("parcel") or ""
            parcel_id = re.sub(r"\s+", "-", parcel_raw.replace("\n", " ").strip())
            parcel_id = normalize_florida_pa_parcel(parcel_id) if parcel_id else ""
            owner = data.get("owner") or ""
            if "(" in owner:
                owner = owner.split("(")[0].strip()
            return [
                ParcelRecord(
                    apn=parcel_id or None,
                    owner_name=owner or None,
                    property_address=(data.get("address") or None),
                    legal_desc=(data.get("legal") or None),
                    source="assessor",
                    raw_json={
                        "source_url": results_frame.url,
                        "platform": "floridapa.com",
                        "search_results": data,
                    },
                )
            ]
    except Exception as exc:
        logger.debug("Florida PA results scrape failed: %s", exc)

    html = await results_frame.content()
    parcel = extract_florida_parcel_from_html(html, results_frame.url)
    if parcel.apn or parcel.owner_name or parcel.property_address:
        parcel.raw_json = {**parcel.raw_json, "platform": "floridapa.com"}
        return [parcel]
    return []


async def _open_florida_pa_detail(driver: "GilaAssessorDriver", results_frame=None) -> bool:
    if results_frame is None:
        results_frame = await _wait_for_florida_pa_frame(driver, "recordSearch_2_Results", timeout_ms=8_000)
    if not results_frame:
        return False
    try:
        detail_cell = results_frame.locator('td.pointer[onclick*="Detail"], td[onclick*="Detail"]').first
        if await detail_cell.count() > 0:
            await detail_cell.click(force=True)
            return True
    except Exception as exc:
        logger.debug("Florida PA detail click failed: %s", exc)
    return False


async def _extract_florida_pa_detail(
    driver: "GilaAssessorDriver",
    fallback_parcel: str | None = None,
) -> list[ParcelRecord]:
    detail_frame = await _wait_for_florida_pa_frame(driver, "recordSearch_3_Details", timeout_ms=20_000)
    if not detail_frame:
        return []

    try:
        data = await detail_frame.evaluate(FLORIDA_PA_DETAIL_JS)
        if data:
            parcel = parcel_record_from_florida_pa_detail(data, detail_frame.url)
            if parcel.apn and not re.search(r"\d{2}-\d{2}-\d{2}-\d{5}-\d{3}", parcel.apn):
                parcel.apn = None
            if parcel.apn:
                parcel.apn = normalize_florida_pa_parcel(parcel.apn)
            elif fallback_parcel:
                parcel.apn = normalize_florida_pa_parcel(fallback_parcel)
            if parcel.apn or parcel.owner_name or parcel.property_address:
                await driver._emit_status("Saved full parcel details from Property Appraiser.")
                return [parcel]
    except Exception as exc:
        logger.debug("Florida PA detail scrape failed: %s", exc)

    html = await detail_frame.content()
    parcel = extract_florida_parcel_from_html(html, detail_frame.url)
    if parcel.apn or parcel.owner_name or parcel.property_address:
        parcel.raw_json = {**parcel.raw_json, "platform": "floridapa.com", "detail_page": True}
        return [parcel]
    return []


MIAMI_DADE_FOLIO_LINK_RE = re.compile(r"\b\d{2}-\d{4}-\d{3}-\d{4}\b")


def _is_miami_dade_possible_match_results_text(body: str) -> bool:
    """True when Miami-Dade PA shows a possible-match results list."""
    if not body:
        return False
    return bool(
        re.search(
            r"exact match not found|possible match(?:\(es\))?|click on the folio number",
            body,
            re.I,
        )
    )


def _is_miami_dade_detail_body_text(body: str) -> bool:
    """Heuristic detail-page detection from visible page text."""
    if not body:
        return False
    if _is_miami_dade_possible_match_results_text(body):
        return False
    lower = body.lower()
    if "property search criteria" in lower and "sales information" not in lower:
        return False
    if MIAMI_DADE_FOLIO_LINK_RE.search(body) and "owner" in lower:
        detail_markers = (
            "sales information",
            "assessment information",
            "property information",
            "just value",
            "assessed value",
            "land value",
        )
        if any(marker in lower for marker in detail_markers):
            return True
        if _is_miami_dade_possible_match_results_text(body):
            return False
    return bool(MIAMI_DADE_FOLIO_LINK_RE.search(body) and "owner" in lower)


MIAMI_DADE_TAB_LABELS = {
    QueryType.ADDRESS: ("ADDRESS", "Address"),
    QueryType.OWNER: ("OWNER NAME", "Owner Name", "Owner"),
    QueryType.PARCEL: ("FOLIO", "Folio", "Parcel"),
}

MIAMI_DADE_TAB_SELECTORS = {
    QueryType.PARCEL: [
        '[role="tab"]:has-text("FOLIO")',
        '[role="tab"]:has-text("Folio")',
        'button:has-text("Folio")',
        'a:has-text("Folio")',
    ],
    QueryType.OWNER: [
        '[role="tab"]:has-text("OWNER NAME")',
        '[role="tab"]:has-text("Owner Name")',
        '[role="tab"]:has-text("Owner")',
        'button:has-text("Owner Name")',
        'a:has-text("Owner Name")',
    ],
    QueryType.ADDRESS: [
        '[role="tab"]:has-text("ADDRESS")',
        '[role="tab"]:has-text("Address")',
        'button:has-text("Address")',
        'a:has-text("Address")',
    ],
}

MIAMI_DADE_INPUT_SELECTORS = {
    QueryType.PARCEL: [
        'input[placeholder*="Enter Folio" i]',
        'input[placeholder*="folio" i]',
        'input[formcontrolname*="folio" i]',
    ],
    QueryType.OWNER: [
        'input[placeholder*="Enter Owner" i]',
        'input[placeholder*="owner" i]',
        'input[formcontrolname*="owner" i]',
    ],
    QueryType.ADDRESS: [
        'input[placeholder*="Enter Address" i]',
        'input[placeholder*="address" i]',
        'input[formcontrolname*="address" i]',
    ],
}


async def _search_miami_dade(
    driver: "GilaAssessorDriver",
    search_url: str,
    query_type: QueryType,
    query_value: str,
) -> list[ParcelRecord]:
    target = normalize_miami_dade_property_search_url(
        MIAMI_DADE_SEARCH_URL if is_miami_dade_assessor(search_url) else search_url
    )
    await driver._emit_status("Opening Miami-Dade Property Appraiser search...")
    await driver.safe_goto(
        target,
        wait_selector="mat-tab-group, [role='tab'], input[type='text'], app-root",
        timeout=60_000,
    )
    await driver.polite_delay(1.5)

    if await driver.is_cloudflare_blocked():
        cleared = await driver.wait_for_cloudflare_clear(max_wait=120)
        if not cleared:
            return []

    try:
        await driver.page.wait_for_selector(
            'mat-tab-group, [role="tab"], input[type="text"]',
            state="visible",
            timeout=20_000,
        )
    except Exception:
        pass

    search_value = query_value
    if query_type == QueryType.PARCEL:
        search_value = normalize_florida_parcel(query_value, county="miami-dade")
    elif query_type == QueryType.ADDRESS:
        search_value = format_miami_dade_address_for_search(query_value)

    notes = getattr(driver, "playwright_notes", None) or ""
    meaningful_notes = "" if is_template_playwright_notes(notes) else notes.strip()

    await driver._emit_status(f"Preparing Miami-Dade {query_type.value} search for: {search_value[:60]}...")
    await _click_miami_dade_search_tab(driver, query_type)
    await driver.polite_delay(0.8)

    if query_type == QueryType.PARCEL:
        await driver._emit_status(f"Searching folio {search_value}...")
    elif query_type == QueryType.ADDRESS:
        await driver._emit_status(f"Searching address {search_value}...")
    elif query_type == QueryType.OWNER:
        await driver._emit_status(f"Searching owner {search_value}...")

    records = await _run_miami_dade_form_search(driver, query_type, search_value)
    if records:
        return records

    await _click_miami_dade_search_tab(driver, query_type)
    if await execute_ai_page_search(
        driver,
        query_type,
        search_value,
        user_instructions=meaningful_notes or None,
    ):
        records = await _collect_miami_dade_search_results(driver, query_type, search_value)
        if records:
            return records

    if meaningful_notes:
        await _click_miami_dade_search_tab(driver, query_type)
        if await apply_playwright_instructions(driver, meaningful_notes, query_type, search_value):
            records = await _collect_miami_dade_search_results(driver, query_type, search_value)
            if records:
                return records

    await driver._emit_status("Could not find Miami-Dade search field.")
    await driver.screenshot_on_failure("miami_dade_no_search_field")
    return []


async def _collect_miami_dade_search_results(
    driver: "GilaAssessorDriver",
    query_type: QueryType,
    search_value: str,
) -> list[ParcelRecord]:
    await driver.polite_delay(3.0)
    if await _open_miami_dade_result(driver, search_value):
        await driver.polite_delay(2.5)
    records = await _extract_miami_dade_detail(
        driver, fallback_folio=search_value if query_type == QueryType.PARCEL else None
    )
    if records:
        return records
    await driver._emit_status("Miami-Dade detail extraction did not return valid parcel fields.")
    return []


async def _run_miami_dade_form_search(
    driver: "GilaAssessorDriver",
    query_type: QueryType,
    search_value: str,
) -> list[ParcelRecord]:
    filled = await _fill_miami_dade_search_field(driver, query_type, search_value)
    if not filled:
        return []

    await _click_miami_dade_search_button(driver)
    return await _collect_miami_dade_search_results(driver, query_type, search_value)


async def _fill_miami_dade_search_field(
    driver: "GilaAssessorDriver",
    query_type: QueryType,
    search_value: str,
) -> bool:
    selectors = MIAMI_DADE_INPUT_SELECTORS.get(query_type, [])
    if await _fill_first_visible(driver, selectors, search_value):
        return True
    if query_type == QueryType.ADDRESS:
        return await _fill_first_visible(driver, FLORIDA_ADDRESS_INPUTS, search_value)
    if query_type == QueryType.OWNER:
        return await _fill_first_visible(driver, FLORIDA_OWNER_INPUTS, search_value)
    if query_type == QueryType.PARCEL:
        return await _fill_first_visible(driver, FLORIDA_PARCEL_INPUTS, search_value)
    return False


async def _click_miami_dade_search_tab(driver: "GilaAssessorDriver", query_type: QueryType) -> bool:
    labels = MIAMI_DADE_TAB_LABELS.get(query_type, ())
    for label in labels:
        try:
            tab = driver.page.get_by_role("tab", name=re.compile(rf"^{re.escape(label)}$", re.I))
            if await tab.count() > 0 and await tab.first.is_visible(timeout=2_000):
                await tab.first.click(force=True)
                await driver.polite_delay(0.5)
                await driver._emit_status(f"Miami-Dade: opened {label} search tab")
                return True
        except Exception:
            continue

    for sel in MIAMI_DADE_TAB_SELECTORS.get(query_type, []):
        try:
            tab = driver.page.locator(sel).first
            if await tab.count() > 0 and await tab.is_visible(timeout=2_000):
                await tab.click(force=True)
                await driver.polite_delay(0.5)
                await driver._emit_status(f"Miami-Dade: opened {query_type.value} search tab")
                return True
        except Exception:
            continue
    return False


async def _click_miami_dade_search_button(driver: "GilaAssessorDriver") -> None:
    for sel in [
        'button:has-text("Search")',
        'input[type="submit"]',
        'button[type="submit"]',
        'img[alt*="search" i]',
        '[aria-label*="search" i]',
    ]:
        try:
            btn = driver.page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible(timeout=2_000):
                await btn.click(force=True)
                await driver.page.wait_for_load_state("domcontentloaded")
                return
        except Exception:
            continue
    await _click_florida_search(driver)


async def _is_miami_dade_possible_match_results_page(driver: "GilaAssessorDriver") -> bool:
    try:
        body = await driver.page.inner_text("body")
        return _is_miami_dade_possible_match_results_text(body)
    except Exception:
        return False


async def _click_miami_dade_folio_result_link(
    driver: "GilaAssessorDriver",
    query_value: str = "",
) -> bool:
    """Click the folio hyperlink on Miami-Dade search / possible-match results."""
    if await _is_miami_dade_detail_page(driver):
        return True

    await driver._emit_status("Miami-Dade: opening folio from search results...")

    query_is_folio = bool(extract_valid_miami_dade_folio(query_value))
    target_folio = extract_valid_miami_dade_folio(query_value) if query_is_folio else None

    folio_locator = driver.page.locator("a").filter(
        has_text=MIAMI_DADE_FOLIO_LINK_RE
    )
    count = await folio_locator.count()
    for index in range(min(count, 8)):
        link = folio_locator.nth(index)
        try:
            if not await link.is_visible(timeout=1_500):
                continue
        except Exception:
            continue

        folio_text = (await link.inner_text()).strip()
        folio_match = MIAMI_DADE_FOLIO_LINK_RE.search(folio_text)
        if not folio_match:
            continue
        folio_value = folio_match.group(0)
        if target_folio and folio_value != target_folio:
            continue

        if not query_is_folio and query_value:
            try:
                container_text = await link.evaluate(
                    """(el) => {
                      const card = el.closest('mat-card, .mat-card, .card, .result, .search-result, tr, div');
                      return card ? card.innerText : el.innerText;
                    }"""
                )
                if container_text and not _miami_dade_result_matches_address_query(
                    query_value, str(container_text)
                ):
                    continue
            except Exception:
                pass

        try:
            await link.scroll_into_view_if_needed()
            await link.click(force=True)
        except Exception:
            try:
                await link.evaluate("(el) => el.click()")
            except Exception as exc:
                logger.debug("Could not click Miami-Dade folio link: %s", exc)
                continue

        await driver.polite_delay(2.5)
        if await _is_miami_dade_detail_page(driver):
            await driver._emit_status(
                f"Miami-Dade: opened property details for folio {folio_value}."
            )
            return True

    clicked_folio = await driver.page.evaluate(
        """() => {
          const folioRe = /\\b(\\d{2}-\\d{4}-\\d{3}-\\d{4})\\b/;
          for (const link of document.querySelectorAll('a')) {
            const text = (link.innerText || link.textContent || '').trim();
            const match = text.match(folioRe);
            if (!match) continue;
            link.click();
            return match[1];
          }
          return null;
        }"""
    )
    if clicked_folio:
        await driver._emit_status(
            f"Miami-Dade: opened property details for folio {clicked_folio}."
        )
        await driver.polite_delay(2.5)
        return await _is_miami_dade_detail_page(driver)

    return False


def _miami_dade_result_matches_address_query(query: str, result_text: str) -> bool:
    """Loose address match for possible-match cards (TER vs TERR, etc.)."""

    def compact(value: str) -> str:
        normalized = value.upper()
        normalized = re.sub(
            r"\b(STREET|ST|ROAD|RD|AVENUE|AVE|TERRACE|TER|TERR|DRIVE|DR|LANE|LN|COURT|CT|BOULEVARD|BLVD)\b",
            "",
            normalized,
        )
        return re.sub(r"[^A-Z0-9]", "", normalized)

    query_compact = compact(query)
    result_compact = compact(result_text)
    if not query_compact:
        return True

    query_number = re.match(r"^(\d+)", query.strip())
    if query_number and query_number.group(1) not in result_text:
        return False

    if query_compact in result_compact or result_compact in query_compact:
        return True

    min_len = min(len(query_compact), len(result_compact), 8)
    return min_len >= 6 and query_compact[:min_len] == result_compact[:min_len]


async def _open_miami_dade_result(driver: "GilaAssessorDriver", query_value: str) -> bool:
    if await _is_miami_dade_detail_page(driver):
        return True

    if await _is_miami_dade_possible_match_results_page(driver):
        if await _click_miami_dade_folio_result_link(driver, query_value):
            return True

    if await _click_miami_dade_folio_result_link(driver, query_value):
        return True

    query_is_folio = bool(extract_valid_miami_dade_folio(query_value))
    folio_digits = re.sub(r"\D", "", query_value) if query_is_folio else ""
    for sel in [
        "mat-row",
        "table tbody tr",
        ".result-row",
        ".search-result",
        "a[href*='folio']",
        "a[href*='detail']",
    ]:
        try:
            rows = driver.page.locator(sel)
            count = await rows.count()
            for i in range(min(count, 10)):
                row = rows.nth(i)
                text = (await row.inner_text()).strip()
                if not text or text.lower() in ("search", "folio", "owner", "address"):
                    continue
                if query_is_folio and folio_digits and folio_digits not in re.sub(r"\D", "", text):
                    continue
                if not query_is_folio and query_value and not _miami_dade_result_matches_address_query(
                    query_value, text
                ):
                    continue
                link = row.locator("a, button, td.pointer, [role='button']").first
                if await link.count() > 0:
                    await link.click(force=True)
                else:
                    await row.click(force=True)
                await driver.polite_delay(2.0)
                return await _is_miami_dade_detail_page(driver)
        except Exception:
            continue
    return await _open_florida_result(driver, query_value)


async def _is_miami_dade_detail_page(driver: "GilaAssessorDriver") -> bool:
    url = driver.page.url.lower()
    if "propertysearch" in url and any(token in url for token in ("detail", "folio", "property")):
        if "folio=" in url or "#/folio/" in url:
            return True
    try:
        body = await driver.page.inner_text("body")
        if _is_miami_dade_detail_body_text(body):
            return True
    except Exception:
        pass
    for sel in [
        "text=Sales Information",
        "text=SALES INFORMATION",
        "text=Assessment Information",
        "text=ASSESSMENT INFORMATION",
        "text=Property Information",
        "text=PROPERTY INFORMATION",
        "text=Just Value",
        "text=Assessed Value",
    ]:
        try:
            if await driver.page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


async def _prepare_miami_dade_detail_page(driver: "GilaAssessorDriver") -> None:
    """Scroll the detail page so lazy sections load before scraping."""
    for sel in [
        "text=PROPERTY INFORMATION",
        "text=Property Information",
        "text=Folio",
        "text=Property Address",
    ]:
        try:
            await driver.page.wait_for_selector(sel, state="visible", timeout=12_000)
            break
        except Exception:
            continue

    try:
        await driver.page.evaluate(
            """async () => {
              const delay = (ms) => new Promise((r) => setTimeout(r, ms));
              const height = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
              const steps = Math.max(12, Math.ceil(height / 400));
              for (let i = 0; i <= steps; i++) {
                window.scrollTo(0, (height * i) / steps);
                await delay(500);
              }
              window.scrollTo(0, document.body.scrollHeight);
              await delay(800);
              window.scrollTo(0, 0);
              await delay(300);
            }"""
        )
    except Exception:
        pass

    for sel in [
        "text=ASSESSMENT INFORMATION",
        "text=Assessment Information",
        "text=SALES INFORMATION",
        "text=Sales Information",
        "text=EXTRA FEATURES",
    ]:
        try:
            await driver.page.wait_for_selector(sel, state="attached", timeout=8_000)
            break
        except Exception:
            continue

    await driver.polite_delay(2.0)


async def _extract_miami_dade_detail(
    driver: "GilaAssessorDriver",
    fallback_folio: str | None = None,
) -> list[ParcelRecord]:
    if not await _is_miami_dade_detail_page(driver):
        return []

    await _prepare_miami_dade_detail_page(driver)

    for attempt in range(2):
        try:
            data = await driver.page.evaluate(MIAMI_DADE_DETAIL_JS)
            if data:
                parcel = parcel_record_from_miami_dade_detail(data, driver.page.url)
                if not parcel.apn and fallback_folio:
                    parcel.apn = extract_valid_miami_dade_folio(fallback_folio)
                if is_valid_miami_dade_extraction(parcel):
                    await driver._emit_status("Saved Miami-Dade parcel details from Property Appraiser.")
                    assessor_docs = await _download_miami_dade_assessor_documents(driver, parcel)
                    if assessor_docs:
                        existing = getattr(driver, "downloaded_assessor_documents", None) or []
                        driver.downloaded_assessor_documents = [*existing, *assessor_docs]
                        parcel.raw_json = {
                            **(parcel.raw_json or {}),
                            "assessor_documents": [
                                {
                                    "document_type": doc.get("document_type"),
                                    "file_path": doc.get("screenshot_path"),
                                    "report_type": (doc.get("ocr_json") or {}).get("report_type"),
                                }
                                for doc in assessor_docs
                            ],
                        }
                    return [parcel]
        except Exception as exc:
            logger.debug("Miami-Dade detail scrape failed (attempt %s): %s", attempt + 1, exc)

        if attempt == 0:
            await driver._emit_status("Retrying Miami-Dade extraction after full-page scroll...")
            await _prepare_miami_dade_detail_page(driver)

    logger.debug("Miami-Dade detail scrape returned no valid structured fields.")
    return []


async def _download_miami_dade_assessor_documents(
    driver: "GilaAssessorDriver",
    parcel: ParcelRecord,
) -> list[dict[str, Any]]:
    from app.drivers.assessor.miami_dade_assessor_reports import download_miami_dade_assessor_reports

    folio = parcel.apn or str((parcel.raw_json or {}).get("folio") or "")
    if not folio:
        return []
    try:
        return await download_miami_dade_assessor_reports(driver, folio)
    except Exception as exc:
        logger.warning("Miami-Dade assessor report download failed: %s", exc)
        return []


async def _open_miami_dade_direct_folio_url(
    driver: "GilaAssessorDriver",
    url: str,
    folio: str,
) -> bool:
    """Open Miami-Dade property detail using the folio hash route."""
    await driver._emit_status(f"Opening Miami-Dade property detail for folio {folio}...")
    try:
        await driver.safe_goto(
            url,
            wait_selector="mat-tab-group, [role='tab'], app-root, text=Folio",
            timeout=60_000,
        )
    except Exception as exc:
        logger.warning("Direct Miami-Dade folio navigation failed: %s", exc)
        return False

    await driver.polite_delay(2.0)
    for _ in range(20):
        if await _is_miami_dade_detail_page(driver):
            return True
        await driver.page.wait_for_timeout(1_000)
    return await _is_miami_dade_detail_page(driver)


async def navigate_miami_dade_property_search(
    driver: "GilaAssessorDriver",
    query_type: QueryType,
    query_value: str,
    parcel: str | None = None,
    gis_url: str | None = None,
) -> bool:
    """Open Miami-Dade property search and land on a parcel detail page."""
    from app.config.florida_portals import (
        build_miami_dade_property_search_url,
        extract_miami_dade_folio_from_url,
    )

    folio = parcel
    if not folio and gis_url:
        folio = extract_miami_dade_folio_from_url(gis_url)
    if not folio and query_type == QueryType.PARCEL and query_value:
        folio = normalize_florida_parcel(query_value, county="miami-dade")
    elif folio:
        folio = normalize_florida_parcel(folio, county="miami-dade")

    if await _is_miami_dade_detail_page(driver):
        if folio:
            try:
                body = await driver.page.inner_text("body")
                if re.sub(r"\D", "", folio) in re.sub(r"\D", "", body):
                    return True
            except Exception:
                return True
        else:
            return True

    if folio:
        direct_url = build_miami_dade_property_search_url(folio, gis_url)
        if await _open_miami_dade_direct_folio_url(driver, direct_url, folio):
            return True
        await driver._emit_status("Direct folio URL did not load detail page — trying form search...")

    search_value = folio or query_value
    qt = QueryType.PARCEL if folio else query_type
    base_url = gis_url or MIAMI_DADE_SEARCH_URL
    records = await _search_miami_dade(driver, base_url, qt, search_value)
    return bool(records) or await _is_miami_dade_detail_page(driver)


COLLIER_TAB_BY_QUERY = {
    QueryType.PARCEL: ("Parcel ID", "Parcel ID:"),
    QueryType.ADDRESS: ("Site Address", "Site Address:"),
    QueryType.OWNER: ("Owner", "Owner:"),
}


def _collier_content_frame(driver: "GilaAssessorDriver") -> Optional[Frame]:
    for frame in driver.page.frames:
        name = (frame.name or "").lower()
        url = frame.url.lower()
        if name == "rbottom" or "main_search" in url:
            return frame
    return None


def _collier_nav_frame(driver: "GilaAssessorDriver") -> Optional[Frame]:
    for frame in driver.page.frames:
        if frame.name == "main" and "buttons.html" in frame.url.lower():
            return frame
    return None


async def _collier_frame_is_blocked(frame: Frame) -> bool:
    url = frame.url.lower()
    return "blocked" in url or "/security/" in url


async def _wait_for_collier_search_frame(
    driver: "GilaAssessorDriver",
    timeout_ms: int = 120_000,
) -> Optional[Frame]:
    deadline = time.monotonic() + (timeout_ms / 1000)
    warned = False
    while time.monotonic() < deadline:
        frame = _collier_content_frame(driver)
        if not frame:
            await asyncio.sleep(0.5)
            continue

        if await _collier_frame_is_blocked(frame):
            if not warned:
                await driver._emit_status(
                    "Collier County security check — complete verification in the Live Browser, then wait."
                )
                warned = True
            await asyncio.sleep(2.0)
            continue

        markers = [
            'text=Real Property Search',
            'text=Parcel ID',
            'text=Site Address',
            'input[type="text"]',
        ]
        for marker in markers:
            try:
                loc = frame.locator(marker).first
                if await loc.count() > 0 and await loc.is_visible(timeout=1_000):
                    return frame
            except Exception:
                continue
        await asyncio.sleep(1.0)
    return None


async def _open_collier_property_search(driver: "GilaAssessorDriver") -> Optional[Frame]:
    await driver._emit_status("Opening Collier County Property Appraiser...")
    await driver.safe_goto(COLLIER_HOME_URL, wait_selector="frame")
    await driver.polite_delay(2.0)

    nav = _collier_nav_frame(driver)
    if nav:
        link = nav.locator('a.navbtn[href*="search_rp.html"]').filter(has_text="Property Search").first
        if await link.count() == 0:
            link = nav.locator('a[href*="search_rp.html"]').first
        if await link.count() > 0:
            await driver._emit_status("Clicking Property Search...")
            await link.click()
            await driver.polite_delay(2.0)
    else:
        frame = _collier_content_frame(driver)
        if frame:
            await frame.goto(COLLIER_SEARCH_URL, wait_until="domcontentloaded", timeout=45_000)

    return await _wait_for_collier_search_frame(driver)


async def _select_collier_search_tab(frame: Frame, query_type: QueryType) -> bool:
    tab_name, _ = COLLIER_TAB_BY_QUERY.get(query_type, ("Owner", "Owner:"))
    if query_type == QueryType.OWNER:
        return True

    selectors = [
        f'a.ui-tabs-anchor:has-text("{tab_name}")',
        f'li a:has-text("{tab_name}")',
        f'.nav-tabs a:has-text("{tab_name}")',
        f'button:has-text("{tab_name}")',
        f'text={tab_name}',
    ]
    for sel in selectors:
        try:
            tab = frame.locator(sel).first
            if await tab.count() == 0 or not await tab.is_visible(timeout=1_500):
                continue
            await tab.click()
            await asyncio.sleep(0.5)
            return True
        except Exception:
            continue
    return False


async def _fill_collier_search_field(
    driver: "GilaAssessorDriver",
    frame: Frame,
    query_type: QueryType,
    value: str,
) -> bool:
    _, label = COLLIER_TAB_BY_QUERY.get(query_type, ("Owner", "Owner:"))
    if await fill_input_by_accessible_name(driver, label, value, root=frame):
        return True
    if await fill_input_by_accessible_name(driver, label.rstrip(":"), value, root=frame):
        return True

    for sel in ['input[type="text"]', 'input[type="search"]']:
        try:
            loc = frame.locator(sel)
            count = await loc.count()
            for index in range(count):
                item = loc.nth(index)
                if not await is_fillable_input(item, timeout_ms=1_000):
                    continue
                await _commit_fill(item, value)
                return True
        except Exception:
            continue
    return False


async def _click_collier_search_submit(driver: "GilaAssessorDriver", frame: Frame) -> bool:
    if await click_property_search_button(driver, root=frame):
        return True

    for sel in [
        'input[type="submit"][value="Search"]',
        'button:has-text("Search")',
        'input[value="Search"]',
    ]:
        try:
            btn = frame.locator(sel).first
            if await btn.count() == 0 or not await btn.is_visible(timeout=1_500):
                continue
            label = re.sub(r"\s+", " ", (await btn.inner_text() or await btn.get_attribute("value") or "").strip())
            if label.lower() != "search":
                continue
            await btn.click()
            return True
        except Exception:
            continue
    return False


async def _open_collier_result(
    driver: "GilaAssessorDriver",
    frame: Frame,
    query_value: str,
) -> bool:
    url = frame.url.lower()
    if any(token in url for token in ("recorddetail", "parceldetail")):
        return True

    query_digits = re.sub(r"\D", "", query_value)
    selectors = [
        'a[href*="RecordDetail"]',
        'a[href*="FolioID"]',
        'a[href*="parceldetail"]',
        "table tbody tr a",
        "table a",
    ]
    for sel in selectors:
        try:
            links = frame.locator(sel)
            count = await links.count()
            for index in range(min(count, 10)):
                link = links.nth(index)
                if not await link.is_visible(timeout=1_000):
                    continue
                text = (await link.inner_text()).strip()
                href = (await link.get_attribute("href") or "").lower()
                if not text and not href:
                    continue
                if text.lower() in ("search", "clear", "back", "map"):
                    continue
                if query_digits and query_digits not in re.sub(r"\D", "", text + href):
                    if query_value.lower() not in text.lower():
                        continue
                await link.click()
                await driver.polite_delay(2.0)
                return True
        except Exception:
            continue
    return "recorddetail" in frame.url.lower()


async def _extract_collier_records(
    driver: "GilaAssessorDriver",
    frame: Frame,
) -> list[ParcelRecord]:
    try:
        data = await frame.evaluate(FLORIDA_SCRAPE_JS)
        if data:
            parcel = parcel_record_from_florida_data(data, frame.url)
            if parcel.apn or parcel.owner_name or parcel.property_address:
                return [parcel]
    except Exception as exc:
        logger.debug("Collier DOM scrape failed: %s", exc)

    html = await frame.content()
    parcel = extract_florida_parcel_from_html(html, frame.url)
    if parcel.apn or parcel.owner_name or parcel.property_address:
        return [parcel]
    return []


async def _search_collier_appraiser(
    driver: "GilaAssessorDriver",
    search_url: str,
    query_type: QueryType,
    query_value: str,
) -> list[ParcelRecord]:
    """Collier County — frameset portal with Property Search tabs for parcel/address."""
    frame = await _open_collier_property_search(driver)
    if not frame:
        await driver._emit_status("Could not open Collier County Property Search page.")
        return []

    search_value = query_value
    if query_type == QueryType.PARCEL:
        search_value = normalize_florida_parcel(query_value, county="collier")
        await driver._emit_status(f"Searching parcel {search_value}...")
    elif query_type == QueryType.ADDRESS:
        search_value = format_florida_pa_address_for_search(query_value)
        await driver._emit_status(f"Searching address {search_value}...")
    else:
        await driver._emit_status(f"Searching owner {search_value}...")

    if not await _select_collier_search_tab(frame, query_type):
        tab_name = COLLIER_TAB_BY_QUERY.get(query_type, ("Owner", "Owner:"))[0]
        await driver._emit_status(f"Could not open the {tab_name} search tab — trying default form.")

    if not await _fill_collier_search_field(driver, frame, query_type, search_value):
        notes = (driver.playwright_notes or "").strip() or None
        await driver._emit_status("Analyzing Collier search form with AI...")
        if not await execute_ai_page_search(driver, query_type, search_value, user_instructions=notes):
            await driver._emit_status("Could not find Collier County search field.")
            return []

    if not await _click_collier_search_submit(driver, frame):
        await driver._emit_status("Could not click Search on Collier County portal.")
        return []

    await driver.polite_delay(2.5)
    frame = _collier_content_frame(driver) or frame

    if await _open_collier_result(driver, frame, search_value):
        await driver.polite_delay(2.0)
        frame = _collier_content_frame(driver) or frame

    records = await _extract_collier_records(driver, frame)
    if records:
        return records

    await driver._emit_status("Could not extract property details from Collier County assessor page.")
    return []


async def _search_brevard_bcpao(
    driver: "GilaAssessorDriver",
    search_url: str,
    query_type: QueryType,
    query_value: str,
) -> list[ParcelRecord]:
    """Brevard County BCPAO — fill Parcel ID / Owner / Address and click Search."""
    target = BREVARD_SEARCH_URL if is_brevard_assessor(search_url) else search_url
    await driver._emit_status("Opening Brevard County property appraiser portal...")
    await driver.safe_goto(target, wait_selector='[role="textbox"]')
    await driver.dismiss_netronline_modals()
    await driver.polite_delay(2.5)

    if await driver.is_cloudflare_blocked():
        cleared = await driver.wait_for_cloudflare_clear(max_wait=120)
        if not cleared:
            return []

    search_value = query_value
    if query_type == QueryType.PARCEL:
        search_value = normalize_florida_parcel(query_value, county="brevard")
        await driver._emit_status(f"Searching parcel {search_value}...")
        filled = await fill_input_by_accessible_name(driver, "Parcel ID:", search_value)
    elif query_type == QueryType.OWNER:
        await driver._emit_status(f"Searching owner {search_value}...")
        filled = await fill_input_by_accessible_name(driver, "Owner Name:", search_value)
    elif query_type == QueryType.ADDRESS:
        await driver._emit_status(f"Searching address {search_value}...")
        filled = await fill_input_by_accessible_name(driver, "Site Address:", search_value)
    else:
        filled = False

    if not filled:
        notes = (driver.playwright_notes or "").strip() or None
        await driver._emit_status("Analyzing Brevard search form with AI...")
        filled = await execute_ai_page_search(
            driver, query_type, search_value, user_instructions=notes
        )

    if not filled:
        await driver._emit_status("Could not find Brevard County search field.")
        return []

    if not await click_property_search_button(driver):
        await _click_florida_search(driver)

    await driver.polite_delay(2.5)

    if await _open_florida_result(driver, search_value):
        await driver.polite_delay(2.0)

    records = await _extract_florida_records(driver)
    if records:
        return records

    html = await driver.page.content()
    parcel = extract_florida_parcel_from_html(html, driver.page.url)
    if parcel.apn or parcel.owner_name or parcel.property_address:
        return [parcel]
    return []


async def _search_orange_county(
    driver: "GilaAssessorDriver",
    search_url: str,
    query_type: QueryType,
    query_value: str,
) -> list[ParcelRecord]:
    await driver._emit_status("Opening Orange County Property Appraiser search...")
    target = ORANGE_SEARCH_URL if is_orange_county_assessor(search_url) else search_url
    await driver.page.goto(target, wait_until="domcontentloaded", timeout=30_000)
    await driver.polite_delay(2.0)

    if not await _wait_for_florida_search_form(driver):
        await driver._emit_status("Waiting for Orange County search page to load...")
        await driver.polite_delay(3.0)

    parcel_value = normalize_florida_parcel(query_value, county="orange")

    if query_type == QueryType.PARCEL:
        filled = await _fill_first_visible(driver, FLORIDA_PARCEL_INPUTS, parcel_value)
    elif query_type == QueryType.OWNER:
        filled = await _fill_first_visible(driver, FLORIDA_OWNER_INPUTS, query_value)
    elif query_type == QueryType.ADDRESS:
        filled = await _fill_first_visible(driver, FLORIDA_ADDRESS_INPUTS, query_value)
    else:
        filled = False

    if not filled:
        notes = (driver.playwright_notes or "").strip() or None
        await driver._emit_status("Analyzing Orange County search form with AI...")
        filled = await execute_ai_page_search(
            driver, query_type, query_value, user_instructions=notes
        )

    if not filled:
        fallback_value = parcel_value if query_type == QueryType.PARCEL else query_value
        filled = await fill_first_visible_input(
            driver, ['input[type="text"]', 'input[type="search"]'], fallback_value
        )

    if not filled:
        await driver._emit_status("Could not find Orange County search field.")
        return []

    await _click_florida_search(driver)
    await driver.polite_delay(2.5)

    if await _open_florida_result(driver, parcel_value if query_type == QueryType.PARCEL else query_value):
        await driver.polite_delay(2.0)

    return await _extract_florida_records(driver)


async def _search_florida_spa(
    driver: "GilaAssessorDriver",
    search_url: str,
    query_type: QueryType,
    query_value: str,
    county: str | None = None,
) -> list[ParcelRecord]:
    county_label = (county or "Florida").replace("-", " ").title()
    await driver._emit_status(f"Opening {county_label} property appraiser portal...")
    await driver.safe_goto(search_url, wait_selector="input, form, app-root")
    await driver.dismiss_netronline_modals()
    await driver.polite_delay(2.5)

    if await driver.is_cloudflare_blocked():
        cleared = await driver.wait_for_cloudflare_clear(max_wait=120)
        if not cleared:
            return []

    if not await _wait_for_florida_search_form(driver):
        await driver.polite_delay(2.0)

    notes = (driver.playwright_notes or "").strip() or None
    if notes:
        if await apply_playwright_instructions(driver, notes, query_type, query_value):
            filled = True
        else:
            filled = False
    else:
        filled = False

    search_value = query_value
    if query_type == QueryType.PARCEL:
        search_value = normalize_florida_parcel(query_value, county=county)

    if not filled:
        if query_type == QueryType.PARCEL:
            filled = await _fill_first_visible(driver, FLORIDA_PARCEL_INPUTS, search_value)
        elif query_type == QueryType.OWNER:
            filled = await _fill_first_visible(driver, FLORIDA_OWNER_INPUTS, search_value)
        elif query_type == QueryType.ADDRESS:
            filled = await _fill_first_visible(driver, FLORIDA_ADDRESS_INPUTS, search_value)

    if not filled:
        await driver._emit_status("Analyzing county search form with AI...")
        if await execute_ai_page_search(
            driver, query_type, search_value, user_instructions=notes
        ):
            filled = True

    if not filled:
        filled = await fill_first_visible_input(
            driver, ['input[type="text"]', 'input[type="search"]'], search_value
        )

    if not filled:
        await driver._try_search_form(query_type, search_value)
    else:
        await _click_florida_search(driver)

    await driver.polite_delay(2.5)

    if await _open_florida_result(driver, search_value):
        await driver.polite_delay(2.0)

    records = await _extract_florida_records(driver)
    if records:
        return records

    html = await driver.page.content()
    parcel = extract_florida_parcel_from_html(html, driver.page.url)
    if parcel.apn or parcel.owner_name or parcel.property_address:
        return [parcel]
    return []


async def _wait_for_florida_search_form(driver: "GilaAssessorDriver") -> bool:
    selectors = FLORIDA_PARCEL_INPUTS + FLORIDA_OWNER_INPUTS + ['input[type="text"]', "form"]
    for sel in selectors:
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible(timeout=8_000):
                return True
        except Exception:
            continue
    return False


async def _fill_first_visible(driver: "GilaAssessorDriver", selectors: list[str], value: str) -> bool:
    return await fill_first_visible_input(driver, selectors, value)


async def _click_florida_search(driver: "GilaAssessorDriver") -> None:
    if await click_property_search_button(driver):
        await driver.page.wait_for_load_state("domcontentloaded")
        return

    for sel in [
        'button[type="submit"]',
        'input[type="submit"]',
        '[aria-label*="search" i]',
        'mat-icon:has-text("search")',
    ]:
        try:
            buttons = driver.page.locator(sel)
            count = await buttons.count()
            for index in range(count):
                btn = buttons.nth(index)
                if not await btn.is_visible(timeout=2_000):
                    continue
                if not await btn.is_enabled():
                    continue
                await btn.click()
                await driver.page.wait_for_load_state("domcontentloaded")
                return
        except Exception:
            continue


FLORIDA_RESULTS_URL_HINTS = (
    "searchresults",
    "search-results",
    "search_results",
    "/results",
    "recordsearch",
)

FLORIDA_DETAIL_URL_HINTS = (
    "propertydetails",
    "parcelsummary",
    "parceldetail",
    "propertydetail",
    "record.aspx",
    "keyvalue=",
    "/folio/",
    "nav/details",
)


def _normalize_parcel_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def _parcel_tokens_match(query_value: Optional[str], candidate: str) -> bool:
    if not query_value:
        return True
    query = _normalize_parcel_token(query_value)
    cand = _normalize_parcel_token(candidate)
    if not query or not cand:
        return True
    return query in cand or cand in query


async def _has_florida_detail_markers(driver: "GilaAssessorDriver") -> bool:
    for sel in [
        "text=Legal Description",
        "text=Just Value",
        "text=Land Value",
        "text=Building Value",
        "text=Assessed Value",
        "text=Market Value",
    ]:
        try:
            if await driver.page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


async def _is_florida_results_page(driver: "GilaAssessorDriver") -> bool:
    url = driver.page.url.lower()
    if any(hint in url for hint in FLORIDA_RESULTS_URL_HINTS):
        return True
    try:
        title = (await driver.page.title() or "").lower()
        if "search result" in title:
            return True
    except Exception:
        pass
    try:
        body = (await driver.page.inner_text("body")).lower()
        if "click parcel" in body and "search result" in body:
            return True
        if "parcel number" in body and "owner's name" in body and not await _has_florida_detail_markers(driver):
            return True
    except Exception:
        pass
    return False


async def _click_parcel_number_in_results(
    driver: "GilaAssessorDriver",
    query_value: Optional[str] = None,
) -> bool:
    """Open the first parcel detail page from a county search-results table."""
    await driver._emit_status("Clicking parcel number in search results...")

    detail_link_selectors = [
        'a[href*="propertydetails"]',
        'a[href*="parcelsummary"]',
        'a[href*="parceldetail"]',
        'a[href*="propertydetail"]',
        "table tbody tr td a",
        "table tbody tr a",
        "mat-row a",
        ".result-row a",
        ".search-result a",
        "table a",
        ".list-group-item a",
    ]
    skip_text = {
        "search",
        "map",
        "print",
        "back",
        "contact",
        "terms of use",
        "view parcel on map",
        "gis",
    }

    for sel in detail_link_selectors:
        try:
            links = driver.page.locator(sel)
            count = await links.count()
            for index in range(min(count, 12)):
                link = links.nth(index)
                if not await link.is_visible(timeout=1_000):
                    continue
                text = re.sub(r"\s+", " ", (await link.inner_text()).strip())
                href = (await link.get_attribute("href") or "").lower()
                text_lower = text.lower()
                if not text or any(skip in text_lower for skip in skip_text):
                    continue
                if "map" in href and not any(
                    token in href for token in ("propertydetails", "parcelsummary", "parceldetail", "propertydetail")
                ):
                    continue
                parcelish = re.sub(r"[^A-Za-z0-9]", "", text)
                if len(parcelish) < 6 and not any(
                    token in href for token in ("propertydetails", "parcelsummary", "parceldetail", "propertydetail", "parcel", "folio")
                ):
                    continue
                if not _parcel_tokens_match(query_value, text) and not _parcel_tokens_match(query_value, href):
                    continue
                try:
                    async with driver.page.expect_navigation(timeout=20_000):
                        await link.click()
                except Exception:
                    await link.click()
                await driver.polite_delay(2.0)
                return True
        except Exception:
            continue
    return False


async def _open_florida_result(
    driver: "GilaAssessorDriver",
    query_value: Optional[str] = None,
) -> bool:
    if await _is_florida_detail_page(driver):
        return True

    if await _is_florida_results_page(driver):
        if await _click_parcel_number_in_results(driver, query_value):
            return await _is_florida_detail_page(driver)

    result_selectors = [
        'a[href*="propertydetails"]',
        'a[href*="parcelsummary"]',
        'a[href*="parceldetail"]',
        "table tbody tr a",
        "mat-row a",
        ".result-row a",
        ".search-result a",
        "a[href*='folio']",
        "table a",
        ".list-group-item a",
    ]
    for sel in result_selectors:
        try:
            links = driver.page.locator(sel)
            count = await links.count()
            for i in range(min(count, 8)):
                link = links.nth(i)
                text = (await link.inner_text()).strip()
                href = (await link.get_attribute("href") or "").lower()
                if not text or text.lower() in ("search", "map", "print", "back"):
                    continue
                if re.search(r"\d", text) or any(
                    token in href for token in ("propertydetails", "parcelsummary", "parceldetail", "folio", "detail")
                ):
                    try:
                        async with driver.page.expect_navigation(timeout=20_000):
                            await link.click()
                    except Exception:
                        await link.click()
                    await driver.polite_delay(1.5)
                    return True
        except Exception:
            continue
    return await _is_florida_detail_page(driver)


async def _is_florida_detail_page(driver: "GilaAssessorDriver") -> bool:
    if await _is_florida_results_page(driver):
        return False

    url = driver.page.url.lower()
    if any(token in url for token in FLORIDA_DETAIL_URL_HINTS):
        return True
    if "propertysearch" in url and any(token in url for token in ("detail", "folio")):
        return True

    if await _has_florida_detail_markers(driver):
        return True

    for sel in [
        "text=Parcel ID",
        "text=Site Address",
        "text=Owner Name",
        "text=Owner's Name",
    ]:
        try:
            if await driver.page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


async def _wait_for_florida_detail_content(driver: "GilaAssessorDriver") -> None:
    """Wait for JS-populated county detail pages before scraping."""
    if not await _is_florida_detail_page(driver):
        return

    selectors = ["#owner_name", "#site_address", "#main_parcel", "text=Owner & Property Information"]
    for sel in selectors:
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() == 0:
                continue
            await loc.wait_for(state="attached", timeout=15_000)
            if sel.startswith("#"):
                await driver.page.wait_for_function(
                    """(id) => {
                        const el = document.getElementById(id);
                        return !!(el && (el.innerText || '').trim().length > 2);
                    }""",
                    sel.lstrip("#"),
                    timeout=15_000,
                )
            return
        except Exception:
            continue
    await driver.polite_delay(2.0)


async def _extract_florida_records(driver: "GilaAssessorDriver") -> list[ParcelRecord]:
    await _wait_for_florida_detail_content(driver)

    try:
        data = await driver.page.evaluate(FLORIDA_SCRAPE_JS)
        if data:
            parcel = parcel_record_from_florida_data(data, driver.page.url)
            if parcel.apn or parcel.owner_name or parcel.property_address:
                await driver._emit_status(
                    f"Extracted assessor data: owner={parcel.owner_name or 'n/a'}, "
                    f"address={parcel.property_address or 'n/a'}, parcel={parcel.apn or 'n/a'}"
                )
                return [parcel]
    except Exception as exc:
        logger.debug("Florida DOM scrape failed: %s", exc)

    html = await driver.page.content()
    parcel = extract_florida_parcel_from_html(html, driver.page.url)
    if parcel.apn or parcel.owner_name or parcel.property_address:
        await driver._emit_status(
            f"Extracted assessor data from HTML: owner={parcel.owner_name or 'n/a'}, "
            f"address={parcel.property_address or 'n/a'}, parcel={parcel.apn or 'n/a'}"
        )
        return [parcel]

    await driver._emit_status("Could not extract property details from assessor page.")
    return []
