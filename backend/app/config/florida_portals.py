"""Florida county property portal URLs and parcel ID normalization."""

import re
from typing import Optional

from app.config.schneider_portals import (
    FL_SCHNEIDER_APP_PATTERN,
    is_florida_schneider_portal,
    normalize_schneider_search_url,
)

# Orange County Property Appraiser (Angular SPA)
ORANGE_SEARCH_URL = "https://ocpaweb.ocpafl.org/parcelsearch"

# Major Florida counties with custom (non-Schneider) portals
FL_CUSTOM_ASSESSOR_HOSTS: dict[str, str] = {
    "orange": "ocpaweb.ocpafl.org",
    "miami-dade": "miamidade.gov",
    "broward": "bcpa.net",
    "baker": "bakerpa.com",
    "collier": "collierappraiser.com",
    "desoto": "desotopa.com",
    "brevard": "bcpao.us",
    "hillsborough": "hcpafl.org",
    "lee": "leepa.org",
    "pinellas": "pcpao.org",
    "palm-beach": "pbcgov.org",
    "duval": "coj.net",
}

# Florida PA platform — Columbia and other counties (e.g. columbia.floridapa.com/gis/)
FLORIDA_PA_HOST_SUFFIX = ".floridapa.com"
COLUMBIA_SEARCH_URL = "https://columbia.floridapa.com/gis/"

# Counties that host the floridapa.com GIS stack on their own domain.
FL_PA_CUSTOM_HOSTS: dict[str, str] = {
    "desoto": "desotopa.com",
}
FL_PA_GIS_ENTRY_URLS: dict[str, str] = {
    "desoto": "https://www.desotopa.com/GIS/",
}

DESOTO_HOME_URL = "https://www.desotopa.com/"
DESOTO_GIS_ENTRY_URL = "https://www.desotopa.com/GIS/"

# Orange County Comptroller official records
ORANGE_RECORDER_HOST = "or.occompt.com"

# Miami-Dade Property Appraiser (Angular SPA)
MIAMI_DADE_SEARCH_URL = "https://apps.miamidadepa.gov/propertysearch/#/"

# Brevard County Property Appraiser (BCPAO Angular SPA)
BREVARD_SEARCH_URL = "https://www.bcpao.us/PropertySearch/#/nav/Search"

# Collier County Property Appraiser (frameset site — search loads in rbottom frame)
COLLIER_HOME_URL = "https://www.collierappraiser.com/"
COLLIER_SEARCH_URL = "https://www.collierappraiser.com/Main_Search/search_rp.html"


def extract_miami_dade_folio_from_url(url: str) -> Optional[str]:
    """Extract a folio from Miami-Dade Property Search hash URLs."""
    if not url:
        return None
    match = re.search(r"[?&]folio=([^&#]+)", url, re.I)
    if match:
        return match.group(1).strip()
    match = re.search(r"#/folio/([^/?&#]+)", url, re.I)
    if match:
        return match.group(1).strip()
    return None


def normalize_miami_dade_property_search_url(url: str) -> str:
    """Rewrite Miami-Dade property search URLs to the working Property Appraiser host.

    NETR and legacy links often point at apps.miamidade.gov/propertysearch, which
    returns HTTP 503. The live Angular SPA is hosted on apps.miamidadepa.gov.
    """
    if not url:
        return url
    lower = url.lower()
    if "propertysearch" not in lower:
        return url
    if "miamidade.gov" not in lower and "miamidadepa.gov" not in lower:
        return url

    folio = extract_miami_dade_folio_from_url(url)
    if folio:
        return build_miami_dade_property_search_url(folio)
    return MIAMI_DADE_SEARCH_URL


def build_miami_dade_property_search_url(folio: str, base_url: Optional[str] = None) -> str:
    """Build a direct Miami-Dade Property Search URL for a folio number."""
    folio_value = normalize_florida_parcel(folio, county="miami-dade")
    _ = base_url  # legacy callers may pass NETR/GIS URLs — always use the PA host
    return f"https://apps.miamidadepa.gov/propertysearch/#/?folio={folio_value}"

# Miami-Dade Clerk official records
MIAMI_DADE_RECORDER_HOST = "miamidadeclerk.gov"
MIAMI_DADE_RECORDER_SEARCH_URL = "https://onlineservices.miamidadeclerk.gov/officialrecords"

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


def is_desoto_assessor(url: str) -> bool:
    return "desotopa.com" in url.lower()


def get_florida_pa_county_from_url(url: str) -> Optional[str]:
    match = re.search(r"https?://([a-z0-9-]+)\.floridapa\.com", url.lower())
    if match:
        return match.group(1)
    return None


def get_florida_pa_gis_county_from_url(url: str) -> Optional[str]:
    county = get_florida_pa_county_from_url(url)
    if county:
        return county
    lower = url.lower()
    for slug, host in FL_PA_CUSTOM_HOSTS.items():
        if host in lower:
            return slug
    return None


def is_florida_pa_gis_assessor(url: str) -> bool:
    return is_florida_pa_assessor(url) or get_florida_pa_gis_county_from_url(url) is not None


def resolve_florida_pa_gis_url(county: Optional[str], assessor_url: str) -> str:
    slug = (county or "").lower().replace(" ", "-")
    if slug in FL_PA_GIS_ENTRY_URLS:
        return FL_PA_GIS_ENTRY_URLS[slug]
    if is_florida_pa_assessor(assessor_url):
        pa_county = get_florida_pa_county_from_url(assessor_url)
        if pa_county:
            return f"https://{pa_county}.floridapa.com/gis/"
    for host_slug, host in FL_PA_CUSTOM_HOSTS.items():
        if host in assessor_url.lower():
            return FL_PA_GIS_ENTRY_URLS.get(host_slug, f"https://www.{host}/GIS/")
    return assessor_url


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
    if is_florida_schneider_portal(url):
        return "schneider"
    return None


def is_orange_county_assessor(url: str) -> bool:
    return "ocpaweb.ocpafl.org" in url.lower() or "ocpafl.org/parcel" in url.lower()


def is_miami_dade_assessor(url: str) -> bool:
    lower = url.lower()
    return (
        "miamidadepa.gov" in lower and "propertysearch" in lower
    ) or (
        "miamidade.gov" in lower and "propertysearch" in lower
    )


def is_miami_dade_recorder(url: str) -> bool:
    lower = url.lower()
    return MIAMI_DADE_RECORDER_HOST in lower or "onlineservices.miamidadeclerk.gov" in lower


def is_miami_dade_gis(url: str) -> bool:
    lower = url.lower()
    return is_miami_dade_assessor(url) or (
        "miamidade.gov" in lower and any(token in lower for token in ("gis", "mapping", "map"))
    )


def is_broward_assessor(url: str) -> bool:
    return "bcpa.net" in url.lower()


def is_brevard_assessor(url: str) -> bool:
    return "bcpao.us" in url.lower()


def is_collier_assessor(url: str) -> bool:
    return "collierappraiser.com" in url.lower()


def is_hillsborough_assessor(url: str) -> bool:
    return "hcpafl.org" in url.lower()


def is_florida_schneider(url: str) -> bool:
    return is_florida_schneider_portal(url)


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


def resolve_florida_county_sources(county: str, parcel: str = "") -> "CountySources":
    """Best-effort portal URLs when NETR is not in the pipeline."""
    from app.extraction.schemas import CountySources

    county_slug = (county or "").lower().replace(" ", "-")
    assessor_url: Optional[str] = None
    recorder_url: Optional[str] = None
    gis_url: Optional[str] = None
    treasurer_url: Optional[str] = None

    if county_slug == "miami-dade":
        assessor_url = MIAMI_DADE_SEARCH_URL
        recorder_url = MIAMI_DADE_RECORDER_SEARCH_URL
        gis_url = MIAMI_DADE_SEARCH_URL
    elif county_slug == "orange":
        assessor_url = ORANGE_SEARCH_URL
    elif county_slug == "collier":
        assessor_url = COLLIER_HOME_URL
    elif county_slug == "desoto":
        assessor_url = DESOTO_HOME_URL

    if parcel:
        treasurer_url = resolve_florida_tax_url(county_slug, parcel)
    elif county_slug in FL_CUSTOM_TAX_URLS:
        treasurer_url = FL_CUSTOM_TAX_URLS[county_slug]

    return CountySources(
        assessor_url=assessor_url,
        recorder_url=recorder_url,
        gis_url=gis_url,
        treasurer_url=treasurer_url,
    )


def resolve_florida_recorder_url(recorder_url: str, county: Optional[str] = None) -> str:
    """Normalize NETR recorder links for Florida county clerk portals."""
    county_slug = (county or "").lower().replace(" ", "-")
    if county_slug == "miami-dade" or is_miami_dade_recorder(recorder_url):
        return MIAMI_DADE_RECORDER_SEARCH_URL

    if not is_myflorida_county_recorder(recorder_url):
        return recorder_url

    lower = recorder_url.lower().rstrip("/")
    if "/orisearch/" in lower:
        return recorder_url

    county_id = FL_MYFLORIDA_COUNTY_IDS.get(county_slug)
    if county_id:
        return f"https://www.{MYFLORIDA_COUNTY_HOST}/orisearch/{county_id}"
    return recorder_url


def resolve_florida_assessor_url(assessor_url: str) -> str:
    normalized = normalize_miami_dade_property_search_url(assessor_url)
    if normalized != assessor_url:
        return normalized

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
    if is_brevard_assessor(assessor_url):
        return BREVARD_SEARCH_URL
    if is_collier_assessor(assessor_url):
        return COLLIER_HOME_URL
    if is_desoto_assessor(assessor_url):
        return DESOTO_HOME_URL
    if is_miami_dade_assessor(assessor_url) or (
        "miamidade.gov" in assessor_url.lower() and "/pa" in assessor_url.lower()
    ):
        folio = extract_miami_dade_folio_from_url(assessor_url)
        if folio:
            return build_miami_dade_property_search_url(folio)
        return MIAMI_DADE_SEARCH_URL
    if is_florida_schneider(assessor_url):
        return normalize_schneider_search_url(assessor_url)
    return assessor_url


def normalize_florida_parcel(parcel: str, county: Optional[str] = None) -> str:
    """Normalize parcel/folio/PIN for Florida county searches."""
    cleaned = parcel.strip()
    if not cleaned:
        return cleaned

    digits = re.sub(r"\D", "", cleaned)

    if county == "collier":
        digits = re.sub(r"\D", "", cleaned)
        return digits or cleaned

    if county == "brevard" or re.search(r"[A-Za-z*]", cleaned):
        # Brevard parcel IDs are alphanumeric (e.g. 22-35-31-AV-*-7, 20G-35-03-XY-234-5.67)
        return re.sub(r"\s+", "", cleaned).upper()

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


def format_miami_dade_address_for_search(address: str) -> str:
    """Normalize address for Miami-Dade PA search (street before first comma)."""
    return format_florida_pa_address_for_search(address)


def format_miami_dade_recorder_address_for_search(address: str) -> str:
    """Normalize address for Miami-Dade clerk Property/Condo recorder search.

    The official records portal matches street addresses when the value is
    prefixed with a single leading space (e.g. `` 9956 SW 157 ST``).
    """
    cleaned = format_miami_dade_address_for_search(address)
    if not cleaned:
        return cleaned
    if cleaned.startswith(" "):
        return cleaned
    return f" {cleaned}"


FLORIDA_TAX_HOST_SUFFIX = ".floridatax.us"

# Counties using floridatax.us (small/mid-size FL counties served by TaxSys/GovTech)
FL_FLORIDATAX_COUNTIES: set[str] = {
    "columbia",
    "alachua",
    "baker",
    "bay",
    "bradford",
    "brevard",
    "calhoun",
    "charlotte",
    "citrus",
    "clay",
    "collier",
    "desoto",
    "dixie",
    "flagler",
    "franklin",
    "gadsden",
    "gilchrist",
    "glades",
    "gulf",
    "hamilton",
    "hardee",
    "hendry",
    "hernando",
    "highlands",
    "holmes",
    "indian-river",
    "jackson",
    "jefferson",
    "lafayette",
    "lake",
    "leon",
    "levy",
    "liberty",
    "madison",
    "manatee",
    "marion",
    "martin",
    "monroe",
    "nassau",
    "okaloosa",
    "okeechobee",
    "orange",
    "osceola",
    "pasco",
    "polk",
    "putnam",
    "santa-rosa",
    "sarasota",
    "seminole",
    "st-johns",
    "st-lucie",
    "sumter",
    "suwannee",
    "taylor",
    "union",
    "volusia",
    "wakulla",
    "walton",
    "washington",
}

FL_COUNTY_TAXES_NET: dict[str, str] = {
    "miami-dade": "fl-miamidade",
    "broward": "fl-broward",
    "palm-beach": "fl-palmbeach",
    "hillsborough": "fl-hillsborough",
    "pinellas": "fl-pinellas",
    "duval": "fl-duval",
    "lee": "fl-lee",
    "polk": "fl-polk",
    "volusia": "fl-volusia",
    "pasco": "fl-pasco",
    "seminole": "fl-seminole",
    "orange": "fl-orange",
    "osceola": "fl-osceola",
}

# Counties that use county-taxes.com (GovTech/Tyler EasySmartPay platform)
# Direct URL format: https://{slug}.county-taxes.com/public/real_estate/parcels/{folio_digits}
FL_COUNTY_TAXES_COM: dict[str, str] = {
    "miami-dade": "miamidade",
    "broward": "broward",
    "palm-beach": "pbctax",
    "hillsborough": "hillstax",
    "pinellas": "pinellas",
    "duval": "duval",
    "lee": "leetc",
    "polk": "polktaxes",
    "volusia": "volusia",
    "pasco": "pascotax",
    "seminole": "seminole",
    "orange": "orangetax",
    "osceola": "osceola",
}

# Counties with fully custom portals (not floridatax.us or county-taxes.com)
FL_CUSTOM_TAX_URLS: dict[str, str] = {
    "miami-dade": "https://county-taxes.net/fl-miamidade/property-tax",
    "broward": "https://county-taxes.net/fl-broward/property-tax",
    "palm-beach": "https://county-taxes.net/fl-palmbeach/property-tax",
    "hillsborough": "https://county-taxes.net/fl-hillsborough/property-tax",
    "pinellas": "https://county-taxes.net/fl-pinellas/property-tax",
    "duval": "https://county-taxes.net/fl-duval/property-tax",
    "lee": "https://county-taxes.net/fl-lee/property-tax",
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


def _folio_digits(parcel: str) -> str:
    """Strip all non-digit characters from a parcel/folio number."""
    return re.sub(r"\D", "", parcel.strip())


def resolve_florida_tax_url(county: str, parcel: str) -> str:
    """Build a direct PropertyDetail URL for the correct FL county tax collector site."""
    county_slug = county.lower().replace(" ", "-")

    # Address/owner searches need the portal landing page; a blank parcel must
    # never produce a malformed PropertyDetail?p= URL.
    if not (parcel or "").strip():
        if county_slug in FL_FLORIDATAX_COUNTIES:
            return f"https://{county_slug}.floridatax.us/"
        if county_slug in FL_COUNTY_TAXES_NET:
            return f"https://county-taxes.net/{FL_COUNTY_TAXES_NET[county_slug]}/property-tax"
        if county_slug in FL_COUNTY_TAXES_COM:
            return f"https://{FL_COUNTY_TAXES_COM[county_slug]}.county-taxes.com/"

    # Grant Street Group's county-taxes.net portal (Miami-Dade etc.)
    net_slug = FL_COUNTY_TAXES_NET.get(county_slug)
    if net_slug:
        return f"https://county-taxes.net/{net_slug}/property-tax"

    # Counties on county-taxes.com — build direct parcel detail URL
    county_taxes_slug = FL_COUNTY_TAXES_COM.get(county_slug)
    if county_taxes_slug:
        folio = _folio_digits(parcel) or parcel.strip()
        return f"https://{county_taxes_slug}.county-taxes.com/public/real_estate/parcels/{folio}"

    # Floridatax.us counties — build PropertyDetail URL with tax account
    if county_slug in FL_FLORIDATAX_COUNTIES:
        account = florida_pa_parcel_to_tax_account(parcel)
        return f"https://{county_slug}.floridatax.us/PropertyDetail?p={account}"

    # Default: try floridatax.us for any unknown FL county
    account = florida_pa_parcel_to_tax_account(parcel)
    return f"https://{county_slug}.floridatax.us/PropertyDetail?p={account}"


def is_florida_tax_site(url: str) -> bool:
    """Return True if url is a recognized FL county tax collector portal."""
    lower = url.lower()
    return (
        "floridatax.us" in lower
        or "county-taxes.com" in lower
        or "county-taxes.net" in lower
    )
