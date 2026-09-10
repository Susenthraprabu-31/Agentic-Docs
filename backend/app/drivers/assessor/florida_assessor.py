"""Florida county assessor automation (Orange, Miami-Dade, Broward, Hillsborough, Schneider)."""

import logging
import re
from typing import TYPE_CHECKING

from app.config.florida_portals import (
    ORANGE_SEARCH_URL,
    get_florida_county_from_url,
    get_florida_pa_county_from_url,
    is_broward_assessor,
    is_florida_pa_assessor,
    is_florida_schneider,
    is_hillsborough_assessor,
    is_miami_dade_assessor,
    is_orange_county_assessor,
    normalize_florida_parcel,
    format_florida_pa_address_for_search,
    normalize_florida_pa_parcel,
    resolve_florida_assessor_url,
)
from app.extraction.florida_extractors import (
    FLORIDA_PA_DETAIL_JS,
    FLORIDA_SCRAPE_JS,
    extract_florida_parcel_from_html,
    parcel_record_from_florida_data,
    parcel_record_from_florida_pa_detail,
)
from app.extraction.schemas import ParcelRecord, QueryType

if TYPE_CHECKING:
    from app.drivers.assessor.gila_assessor_driver import GilaAssessorDriver

logger = logging.getLogger(__name__)

FLORIDA_PARCEL_INPUTS = [
    'input[formcontrolname*="parcel" i]',
    'input[placeholder*="parcel" i]',
    'input[aria-label*="parcel" i]',
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
    county = get_florida_county_from_url(search_url) or get_florida_county_from_url(assessor_url)

    if is_florida_pa_assessor(search_url) or is_florida_pa_assessor(assessor_url):
        pa_county = get_florida_pa_county_from_url(search_url) or get_florida_pa_county_from_url(assessor_url)
        return await _search_florida_pa(driver, search_url, query_type, query_value, county=pa_county)

    if is_orange_county_assessor(search_url) or is_orange_county_assessor(assessor_url):
        return await _search_orange_county(driver, search_url, query_type, query_value)

    if is_miami_dade_assessor(search_url) or is_miami_dade_assessor(assessor_url):
        return await _search_florida_spa(
            driver, search_url, query_type, query_value, county="miami-dade"
        )

    if is_broward_assessor(search_url) or is_broward_assessor(assessor_url):
        return await _search_florida_spa(
            driver, search_url, query_type, query_value, county="broward"
        )

    if is_hillsborough_assessor(search_url) or is_hillsborough_assessor(assessor_url):
        return await _search_florida_spa(
            driver, search_url, query_type, query_value, county="hillsborough"
        )

    if is_florida_schneider(search_url) or is_florida_schneider(assessor_url):
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


async def _search_florida_pa(
    driver: "GilaAssessorDriver",
    search_url: str,
    query_type: QueryType,
    query_value: str,
    county: str | None = None,
) -> list[ParcelRecord]:
    """Columbia and other floridapa.com counties — disclaimer, iframe search, Run Search."""
    county_label = (county or "Florida").replace("-", " ").title()
    await driver._emit_status(f"Opening {county_label} Property Appraiser GIS search...")
    await driver.page.goto(search_url, wait_until="networkidle", timeout=60_000)

    await _dismiss_florida_pa_disclaimer(driver)

    search_frame = await _wait_for_florida_pa_frame(driver, "recordSearch_1_Form", timeout_ms=25_000)
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
        for frame in driver.page.frames:
            if url_part in frame.url:
                return frame
        await driver.page.wait_for_timeout(300)
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
        if not filled:
            filled = await _fill_first_visible(driver, ['input[type="text"]'], parcel_value)
    elif query_type == QueryType.OWNER:
        filled = await _fill_first_visible(driver, FLORIDA_OWNER_INPUTS, query_value)
    elif query_type == QueryType.ADDRESS:
        filled = await _fill_first_visible(driver, FLORIDA_ADDRESS_INPUTS, query_value)
    else:
        filled = False

    if not filled:
        await driver._emit_status("Could not find Orange County search field.")
        return []

    await _click_florida_search(driver)
    await driver.polite_delay(2.5)

    if await _open_florida_result(driver):
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

    if query_type == QueryType.PARCEL:
        parcel_value = normalize_florida_parcel(query_value, county=county)
        filled = await _fill_first_visible(driver, FLORIDA_PARCEL_INPUTS, parcel_value)
        if not filled:
            filled = await _fill_first_visible(driver, ['input[type="text"]'], parcel_value)
    elif query_type == QueryType.OWNER:
        filled = await _fill_first_visible(driver, FLORIDA_OWNER_INPUTS, query_value)
    elif query_type == QueryType.ADDRESS:
        filled = await _fill_first_visible(driver, FLORIDA_ADDRESS_INPUTS, query_value)
    else:
        filled = False

    if not filled:
        await driver._try_search_form(query_type, query_value)
    else:
        await _click_florida_search(driver)

    await driver.polite_delay(2.5)

    if await _open_florida_result(driver):
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
    for sel in selectors:
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible(timeout=2_000):
                await loc.click()
                await loc.fill(value)
                return True
        except Exception:
            continue
    return False


async def _click_florida_search(driver: "GilaAssessorDriver") -> None:
    for sel in [
        'button:has-text("Search")',
        'button[type="submit"]',
        'input[type="submit"]',
        'a:has-text("Search")',
        '[aria-label*="search" i]',
        'mat-icon:has-text("search")',
    ]:
        try:
            btn = driver.page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible(timeout=2_000):
                await btn.click()
                await driver.page.wait_for_load_state("domcontentloaded")
                return
        except Exception:
            continue


async def _open_florida_result(driver: "GilaAssessorDriver") -> bool:
    if await _is_florida_detail_page(driver):
        return True

    result_selectors = [
        "table tbody tr a",
        "mat-row a",
        ".result-row a",
        ".search-result a",
        "a[href*='parcel']",
        "a[href*='folio']",
        "a[href*='detail']",
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
                if re.search(r"\d", text) or "parcel" in href or "folio" in href or "detail" in href:
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
    url = driver.page.url.lower()
    if any(token in url for token in ("detail", "parcel", "folio", "property", "record")):
        return True
    for sel in [
        "text=Owner",
        "text=Parcel ID",
        "text=Site Address",
        "text=Legal Description",
        "text=Just Value",
    ]:
        try:
            if await driver.page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


async def _extract_florida_records(driver: "GilaAssessorDriver") -> list[ParcelRecord]:
    try:
        data = await driver.page.evaluate(FLORIDA_SCRAPE_JS)
        if data:
            parcel = parcel_record_from_florida_data(data, driver.page.url)
            if parcel.apn or parcel.owner_name or parcel.property_address:
                return [parcel]
    except Exception as exc:
        logger.debug("Florida DOM scrape failed: %s", exc)

    html = await driver.page.content()
    parcel = extract_florida_parcel_from_html(html, driver.page.url)
    if parcel.apn or parcel.owner_name or parcel.property_address:
        return [parcel]
    return []
