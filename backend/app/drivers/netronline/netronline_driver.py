import logging
import re
from typing import Any, Optional
from urllib.parse import urljoin

from playwright.async_api import Page

from app.drivers.base.base_driver import BaseDriver
from app.extraction.schemas import CountySources

logger = logging.getLogger(__name__)

NETR_BASE = "https://publicrecords.netronline.com"

# NETR county pages use many different office names — match broadly
ASSESSOR_PATTERNS = [
    r"assessor",
    r"tax assessment",
    r"property tax",
    r"real property",
    r"property assessment",
    r"property appraiser",
    r"appraisal",
    r"parcel search",
    r"tax assessor",
]
RECORDER_PATTERNS = [
    r"recorder",
    r"conveyance",
    r"recording",
    r"register of deeds",
    r"deed",
    r"land record",
    r"clerk.*record",
    r"clerk of courts",
    r"comptroller",
    r"official records",
]
TREASURER_PATTERNS = [
    r"treasurer",
    r"tax collector",
    r"tax office",
]
GIS_PATTERNS = [
    r"\bgis\b",
    r"mapping",
    r"map viewer",
    r"parcel map",
]
SKIP_PATTERNS = [
    r"historic aerial",
    r"netr mapping",
    r"help us keep",
    r"county-taxes\.net",
    r"tax collector",
    r"pay.*tax",
]


def _classify_office(name: str) -> Optional[str]:
    lower = name.lower()
    if any(re.search(p, lower) for p in SKIP_PATTERNS):
        return None
    if any(re.search(p, lower) for p in ASSESSOR_PATTERNS):
        return "assessor"
    if any(re.search(p, lower) for p in RECORDER_PATTERNS):
        return "recorder"
    if any(re.search(p, lower) for p in TREASURER_PATTERNS):
        return "treasurer"
    if any(re.search(p, lower) for p in GIS_PATTERNS):
        return "gis"
    return None


NETR_REDIRECT_HOSTS = ("map.netronline.com", "publicrecords.netronline.com")


def _is_external_portal(href: str) -> bool:
    if not href or href == "#" or not href.startswith("http"):
        return False
    return not any(host in href for host in NETR_REDIRECT_HOSTS)


def _pick_online_url(links: list[dict[str, str]], allow_map: bool = False) -> Optional[str]:
    for link in links:
        text = link.get("text", "").lower()
        href = link.get("href", "")
        if not href or href == "#":
            continue
        if "county-taxes.net" in href.lower():
            continue
        if "go to data online" in text and _is_external_portal(href):
            return href
    if allow_map:
        for link in links:
            text = link.get("text", "").lower()
            href = link.get("href", "")
            if text.strip() == "map" and href:
                return href
    for link in links:
        href = link.get("href", "")
        if _is_external_portal(href):
            return href
    return None


class NetronlineDriver(BaseDriver):
    async def resolve_county_sources(self, state: str, county: str) -> CountySources:
        county_url = f"{NETR_BASE}/state/{state.upper()}/county/{county.lower()}"
        await self.safe_goto(
            county_url,
            wait_selector='a:has-text("Go to Data Online"), table',
        )
        await self.dismiss_netronline_modals()

        rows = await self._extract_directory_rows()
        logger.info("NETR %s: found %d directory rows", county_url, len(rows))

        sources = CountySources()
        unmatched: list[dict[str, Any]] = []

        for row in rows:
            name = row.get("name", "").strip()
            if not name or name.lower() in ("name", "phone", "online", "report"):
                continue

            allow_map = _classify_office(name) == "gis"
            href = _pick_online_url(row.get("links", []), allow_map=allow_map)
            if not href:
                continue

            phone_match = re.search(r"\(\d{3}\)\s*\d{3}-\d{4}", row.get("text", ""))
            phone = phone_match.group(0) if phone_match else None

            office = _classify_office(name)
            if office == "assessor" and not sources.assessor_url:
                sources.assessor_url = href
                if phone:
                    sources.phones["assessor"] = phone
            elif office == "recorder" and not sources.recorder_url:
                sources.recorder_url = href
                if phone:
                    sources.phones["recorder"] = phone
            elif office == "treasurer" and not sources.treasurer_url:
                sources.treasurer_url = href
                if phone:
                    sources.phones["treasurer"] = phone
            elif office == "gis" and not sources.gis_url:
                sources.gis_url = href
                if phone:
                    sources.phones["gis"] = phone
            else:
                unmatched.append({"name": name, "url": href})

        # Assign remaining "Go to Data Online" links by position if keywords missed
        if not sources.assessor_url and unmatched:
            sources.assessor_url = unmatched.pop(0)["url"]
        if not sources.recorder_url and unmatched:
            sources.recorder_url = unmatched.pop(0)["url"]
        if not sources.gis_url and unmatched:
            sources.gis_url = unmatched.pop(0)["url"]

        if not any([sources.assessor_url, sources.recorder_url, sources.gis_url]):
            sources = await self._fallback_parse_all_links()

        logger.info("NETR resolved sources: %s", sources.model_dump())
        return sources

    async def _extract_directory_rows(self) -> list[dict[str, Any]]:
        """Extract directory rows via browser DOM — supports NETR div-table and HTML table layouts."""
        return await self.page.evaluate(
            """() => {
                const rows = [];
                const seen = new Set();

                const collectRow = (container, name) => {
                    const text = (container.innerText || '').trim();
                    if (!text || text.length < 5) return;
                    const links = [...container.querySelectorAll('a')].map(a => ({
                        text: (a.innerText || '').trim(),
                        href: a.href || a.getAttribute('href') || ''
                    }));
                    const hasOnline = links.some(l =>
                        /go to data online/i.test(l.text) ||
                        l.text.toLowerCase() === 'map'
                    );
                    if (!hasOnline) return;
                    const rowName = (name || text.split('\\n')[0]).trim();
                    if (!rowName || /^(name|phone|online|report)$/i.test(rowName)) return;
                    const key = rowName.slice(0, 100);
                    if (seen.has(key)) return;
                    seen.add(key);
                    rows.push({ name: rowName, text, links });
                };

                // NETR modern layout: div.div-table-row
                document.querySelectorAll('.div-table-row').forEach(row => {
                    const nameCol =
                        row.querySelector('.column-1') ||
                        row.querySelector('.div-table-col:first-child');
                    const name = nameCol ? nameCol.innerText.trim().split('\\n')[0] : '';
                    collectRow(row, name);
                });

                // Legacy HTML table layout
                document.querySelectorAll('table tr').forEach(tr => {
                    const nameCell = tr.querySelector('td');
                    const name = nameCell ? nameCell.innerText.trim().split('\\n')[0] : '';
                    collectRow(tr, name);
                });

                // Last resort: walk up from each online link
                if (rows.length === 0) {
                    document.querySelectorAll('a').forEach(a => {
                        const t = (a.innerText || '').trim();
                        if (!/go to data online/i.test(t) && t.toLowerCase() !== 'map') return;
                        const container =
                            a.closest('.div-table-row') ||
                            a.closest('tr') ||
                            a.parentElement;
                        if (!container) return;
                        const name = container.innerText.trim().split('\\n')[0];
                        collectRow(container, name);
                    });
                }
                return rows;
            }"""
        )

    async def _fallback_parse_all_links(self) -> CountySources:
        sources = CountySources()
        links = await self.page.locator('a:has-text("Go to Data Online"), a:has-text("Map")').all()
        collected: list[str] = []

        for link in links:
            try:
                href = await link.get_attribute("href")
                if not href:
                    continue
                if not href.startswith("http"):
                    href = urljoin(NETR_BASE, href)
                if "netronline.com" in href:
                    continue
                parent = link.locator("xpath=ancestor::tr[1]")
                parent_text = ""
                if await parent.count() > 0:
                    parent_text = await parent.first.inner_text()
                office = _classify_office(parent_text)
                if office == "assessor" and not sources.assessor_url:
                    sources.assessor_url = href
                elif office == "recorder" and not sources.recorder_url:
                    sources.recorder_url = href
                elif office == "gis" and not sources.gis_url:
                    sources.gis_url = href
                else:
                    collected.append(href)
            except Exception as exc:
                logger.debug("Link parse skip: %s", exc)

        if not sources.assessor_url and collected:
            sources.assessor_url = collected.pop(0)
        if not sources.recorder_url and collected:
            sources.recorder_url = collected.pop(0)
        if not sources.gis_url and collected:
            sources.gis_url = collected.pop(0)

        return sources

    async def navigate_to_portal(self, url: str) -> Page:
        await self.safe_goto(url)
        await self.dismiss_netronline_modals()
        return self.page
