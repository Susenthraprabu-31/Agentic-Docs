import logging
import re
from functools import lru_cache
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

NETR_BASE = "https://publicrecords.netronline.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 DonoMVP/1.0"
)


def _county_slug_from_href(href: str, state: str) -> str | None:
    pattern = rf"/state/{state.upper()}/county/([a-z0-9_-]+)"
    match = re.search(pattern, href, re.IGNORECASE)
    return match.group(1).lower() if match else None


@lru_cache(maxsize=60)
def fetch_counties_for_state(state: str) -> list[dict[str, str]]:
    """Fetch county list from NETR Online state page."""
    state_code = state.upper()
    url = f"{NETR_BASE}/state/{state_code}"

    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            html = response.text
    except Exception as exc:
        logger.warning("Failed to fetch counties for %s: %s", state_code, exc)
        return []

    soup = BeautifulSoup(html, "lxml")
    counties: dict[str, str] = {}

    for link in soup.find_all("a", href=True):
        href = link["href"]
        slug = _county_slug_from_href(href, state_code)
        if not slug:
            continue
        name = link.get_text(strip=True) or slug.replace("-", " ").title()
        if name.lower() in ("go to data online", "fix", "report"):
            continue
        counties[slug] = name

    if not counties:
        for link in soup.select('a[href*="/county/"]'):
            href = link.get("href", "")
            full_href = urljoin(NETR_BASE, href)
            slug = _county_slug_from_href(full_href, state_code)
            if slug:
                name = link.get_text(strip=True) or slug.replace("-", " ").title()
                counties[slug] = name

    return [{"slug": slug, "name": name} for slug, name in sorted(counties.items(), key=lambda x: x[1])]
