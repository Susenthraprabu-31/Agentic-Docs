"""Direct assessor portal search URLs when NETR only provides a landing page."""

from app.config.florida_portals import (
    ORANGE_SEARCH_URL,
    is_florida_pa_assessor,
    is_florida_schneider,
    is_orange_county_assessor,
    resolve_florida_assessor_url,
)

HONOLULU_LANDING_URL = "https://www.qpublic.net/hi/honolulu/"
HONOLULU_PROPERTY_SEARCH_URL = "https://www.qpublic.net/hi/honolulu/search.html"
HONOLULU_SEARCH_URL = (
    "https://qpublic.schneidercorp.com/Application.aspx"
    "?App=HonoluluCountyHI&PageType=Search"
)

# NETR links to qpublic.net landing pages — enter via landing (less bot-like than direct deep link).
ASSESSOR_SEARCH_URLS: dict[str, str] = {
    "qpublic.net/hi/honolulu": HONOLULU_LANDING_URL,
    "honolulucountyhi": HONOLULU_SEARCH_URL,
    "ocpaweb.ocpafl.org": ORANGE_SEARCH_URL,
    "ocpafl.org": ORANGE_SEARCH_URL,
}


def resolve_assessor_search_url(assessor_url: str) -> str:
    lower = assessor_url.lower()
    for key, search_url in ASSESSOR_SEARCH_URLS.items():
        if key in lower:
            return search_url
    if is_florida_pa_assessor(assessor_url):
        return resolve_florida_assessor_url(assessor_url)
    if is_orange_county_assessor(assessor_url):
        return ORANGE_SEARCH_URL
    if is_florida_schneider(assessor_url):
        return resolve_florida_assessor_url(assessor_url)
    if "schneidercorp.com" in lower and "pagetype=search" in lower:
        return assessor_url
    return assessor_url


def is_honolulu_schneider(url: str) -> bool:
    lower = url.lower()
    return "honolulucountyhi" in lower or "qpublic.net/hi/honolulu" in lower
