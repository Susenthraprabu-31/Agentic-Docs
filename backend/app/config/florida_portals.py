"""Florida county property portal URLs and parcel ID normalization."""

import re
from typing import Optional

# Orange County Property Appraiser (Angular SPA)
ORANGE_SEARCH_URL = "https://ocpaweb.ocpafl.org/parcelsearch"

# Major Florida counties with custom (non-Schneider) portals
FL_CUSTOM_ASSESSOR_HOSTS: dict[str, str] = {
    "orange": "ocpaweb.ocpafl.org",
    "miami-dade": "miamidade.gov",
    "broward": "bcpa.net",
    "hillsborough": "hcpafl.org",
    "lee": "leepa.org",
    "pinellas": "pcpao.org",
    "palm-beach": "pbcgov.org",
    "duval": "coj.net",
}

# Florida PA platform — Columbia and other counties (e.g. columbia.floridapa.com/gis/)
FLORIDA_PA_HOST_SUFFIX = ".floridapa.com"
COLUMBIA_SEARCH_URL = "https://columbia.floridapa.com/gis/"

# Schneider / qPublic (Beacon) — many smaller FL counties
FL_SCHNEIDER_APP_PATTERN = re.compile(r"app=([a-z]+countyfl)", re.I)

# Orange County Comptroller official records
ORANGE_RECORDER_HOST = "or.occompt.com"

# Miami-Dade Clerk
MIAMI_DADE_RECORDER_HOST = "miamidadeclerk.gov"

# Broward Clerk (AcclaimWeb)
BROWARD_RECORDER_HOST = "officialrecords.broward.org"

# Hillsborough Clerk
HILLSBOROUGH_RECORDER_HOST = "hillsclerk.com"

# MyFloridaCounty.com — Columbia and other smaller FL counties
MYFLORIDA_COUNTY_HOST = "myfloridacounty.com"
FL_MYFLORIDA_COUNTY_IDS: dict[str, str] = {
    "columbia": "12",
}


def is_florida_pa_assessor(url: str) -> bool:
    return FLORIDA_PA_HOST_SUFFIX in url.lower()


def get_florida_pa_county_from_url(url: str) -> Optional[str]:
    match = re.search(r"https?://([a-z0-9-]+)\.floridapa\.com", url.lower())
    if match:
        return match.group(1)
    return None


def get_florida_county_from_url(url: str) -> Optional[str]:
    lower = url.lower()
    pa_county = get_florida_pa_county_from_url(url)
    if pa_county:
        return pa_county
    for slug, host in FL_CUSTOM_ASSESSOR_HOSTS.items():
        if host in lower:
            return slug
    match = FL_SCHNEIDER_APP_PATTERN.search(lower)
    if match:
        return match.group(1).replace("countyfl", "").replace("county", "")
    if "schneidercorp.com" in lower and "countyfl" in lower:
        return "schneider"
    return None


def is_orange_county_assessor(url: str) -> bool:
    return "ocpaweb.ocpafl.org" in url.lower() or "ocpafl.org/parcel" in url.lower()


def is_miami_dade_assessor(url: str) -> bool:
    return "miamidade.gov" in url.lower() and "propertysearch" in url.lower()


def is_broward_assessor(url: str) -> bool:
    return "bcpa.net" in url.lower()


def is_hillsborough_assessor(url: str) -> bool:
    return "hcpafl.org" in url.lower()


def is_florida_schneider(url: str) -> bool:
    lower = url.lower()
    return "schneidercorp.com" in lower and "countyfl" in lower


def is_florida_recorder(url: str) -> bool:
    lower = url.lower()
    return any(
        host in lower
        for host in (
            ORANGE_RECORDER_HOST,
            MIAMI_DADE_RECORDER_HOST,
            BROWARD_RECORDER_HOST,
            HILLSBOROUGH_RECORDER_HOST,
            MYFLORIDA_COUNTY_HOST,
            "acclaimweb",
            "officialrecords",
        )
    )


def is_myflorida_county_recorder(url: str) -> bool:
    return MYFLORIDA_COUNTY_HOST in url.lower()


def resolve_florida_recorder_url(recorder_url: str, county: Optional[str] = None) -> str:
    """Normalize NETR recorder links for Florida county clerk portals."""
    if not is_myflorida_county_recorder(recorder_url):
        return recorder_url

    lower = recorder_url.lower().rstrip("/")
    if "/orisearch/" in lower:
        return recorder_url

    county_slug = (county or "").lower().replace(" ", "-")
    county_id = FL_MYFLORIDA_COUNTY_IDS.get(county_slug)
    if county_id:
        return f"https://www.{MYFLORIDA_COUNTY_HOST}/orisearch/{county_id}"
    return recorder_url


def resolve_florida_assessor_url(assessor_url: str) -> str:
    if is_florida_pa_assessor(assessor_url):
        lower = assessor_url.lower().rstrip("/")
        if "/gis" not in lower:
            # NETR often links to county homepage — open the GIS record search page
            county = get_florida_pa_county_from_url(assessor_url)
            if county:
                return f"https://{county}.floridapa.com/gis/"
        return assessor_url
    if is_orange_county_assessor(assessor_url):
        return ORANGE_SEARCH_URL
    if is_florida_schneider(assessor_url):
        lower = assessor_url.lower()
        if "pagetype=search" not in lower:
            sep = "&" if "?" in assessor_url else "?"
            return f"{assessor_url}{sep}PageType=Search"
    return assessor_url


def normalize_florida_parcel(parcel: str, county: Optional[str] = None) -> str:
    """Normalize parcel/folio/PIN for Florida county searches."""
    cleaned = parcel.strip()
    if not cleaned:
        return cleaned

    digits = re.sub(r"\D", "", cleaned)

    if county == "orange" or (county is None and len(digits) in (10, 12, 15, 16)):
        # Orange PIN: often 10-16 digits; display format 22-21-31-1234-00-010
        if len(digits) >= 10:
            d = digits[:16].zfill(16) if len(digits) < 16 else digits[:16]
            return f"{d[0:2]}-{d[2:4]}-{d[4:6]}-{d[6:10]}-{d[10:12]}-{d[12:16]}"
        return cleaned

    if county == "miami-dade" or (county is None and len(digits) == 13):
        # Miami-Dade folio: 13 digits, often formatted with dashes
        if len(digits) == 13:
            return f"{digits[0:2]}-{digits[2:6]}-{digits[6:9]}-{digits[9:13]}"
        return digits or cleaned

    if county == "broward":
        return digits or cleaned

    if county == "hillsborough":
        # Hillsborough PIN can be 9+ digits
        return digits or cleaned

    if county == "columbia" or (county and county.endswith("floridapa")):
        return normalize_florida_pa_parcel(cleaned)

    # Florida PA platform (##-##-##-#####-###) — 14 digits
    if len(digits) == 14:
        return normalize_florida_pa_parcel(cleaned)

    # Schneider FL counties — digits only
    if len(digits) >= 6:
        return digits

    return cleaned


def normalize_florida_pa_parcel(parcel: str) -> str:
    """Format parcel for floridapa.com counties: ##-##-##-#####-###."""
    if re.match(r"^\d{2}-\d{2}-\d{2}-\d{5}-\d{3}$", parcel.strip()):
        return parcel.strip()
    digits = re.sub(r"\D", "", parcel)
    if len(digits) >= 14:
        d = digits[:14]
        return f"{d[0:2]}-{d[2:4]}-{d[4:6]}-{d[6:11]}-{d[11:14]}"
    return parcel.strip()


def parse_florida_pa_address(address: str) -> tuple[str, str]:
    """Split house number and street for display; floridapa uses one StreetName field."""
    cleaned = format_florida_pa_address_for_search(address)
    match = re.match(r"^(\d[\d\-]*)\s+(.+)$", cleaned)
    if match:
        return match.group(1), match.group(2)
    return "", cleaned


def format_florida_pa_address_for_search(address: str) -> str:
    """Normalize address for floridapa StreetName (*HouseNumber StreetName in one field)."""
    cleaned = re.sub(r"\s+", " ", address.strip())
    if "," in cleaned:
        cleaned = cleaned.split(",", 1)[0].strip()
    return cleaned


FLORIDA_TAX_HOST_SUFFIX = ".floridatax.us"
FL_COUNTY_TAX_HOSTS: dict[str, str] = {
    "columbia": "columbia.floridatax.us",
}


def florida_pa_parcel_to_tax_account(parcel: str) -> str:
    """Convert floridapa parcel ID to tax collector account (e.g. 00-00-00-12003-001 → R12003-001)."""
    normalized = normalize_florida_pa_parcel(parcel)
    parts = normalized.split("-")
    if len(parts) >= 2:
        return f"R{parts[-2]}-{parts[-1]}"
    if normalized.upper().startswith("R"):
        return normalized.upper()
    return normalized


def resolve_florida_tax_url(county: str, parcel: str) -> str:
    """Build PropertyDetail URL for Florida county tax collector sites."""
    county_slug = county.lower().replace(" ", "-")
    host = FL_COUNTY_TAX_HOSTS.get(county_slug, f"{county_slug}{FLORIDA_TAX_HOST_SUFFIX}")
    account = florida_pa_parcel_to_tax_account(parcel)
    return f"https://{host}/PropertyDetail?p={account}"


def supports_florida_tax_record(state: str, county: str) -> bool:
    return state.upper() == "FL" and county.lower().replace(" ", "-") in FL_COUNTY_TAX_HOSTS
