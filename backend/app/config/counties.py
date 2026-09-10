"""County -> driver mapping and supported county metadata."""

COUNTY_DRIVER_MAP: dict[str, dict[str, str]] = {
    "AZ:gila": {
        "assessor": "GilaAssessorDriver",
        "recorder": "GilaRecorderDriver",
        "gis": "GilaGisDriver",
    },
    "HI:honolulu_oahu": {
        "assessor": "GilaAssessorDriver",
        "recorder": "GilaRecorderDriver",
        "gis": "GilaGisDriver",
    },
    "FL:orange": {
        "assessor": "GilaAssessorDriver",
        "recorder": "GilaRecorderDriver",
        "gis": "GilaGisDriver",
    },
    "FL:miami-dade": {
        "assessor": "GilaAssessorDriver",
        "recorder": "GilaRecorderDriver",
        "gis": "GilaGisDriver",
    },
    "FL:broward": {
        "assessor": "GilaAssessorDriver",
        "recorder": "GilaRecorderDriver",
        "gis": "GilaGisDriver",
    },
    "FL:hillsborough": {
        "assessor": "GilaAssessorDriver",
        "recorder": "GilaRecorderDriver",
        "gis": "GilaGisDriver",
    },
}

# Florida counties with dedicated automation (others use Schneider qPublic when available)
FL_SUPPORTED_COUNTIES: dict[str, str] = {
    "orange": "Orange County — OCPA parcel search",
    "miami-dade": "Miami-Dade — Property Appraiser + Clerk",
    "broward": "Broward — BCPA + Clerk AcclaimWeb",
    "hillsborough": "Hillsborough — HCPA + Clerk",
    "bay": "Bay County — Schneider qPublic",
    "flagler": "Flagler County — Schneider qPublic",
    "levy": "Levy County — Schneider qPublic",
    "alachua": "Alachua County — Schneider qPublic",
    "columbia": "Columbia County — floridapa.com GIS search",
}


def get_county_key(state: str, county: str) -> str:
    return f"{state.lower()}:{county.lower()}"


def is_florida_county_supported(county: str) -> bool:
    slug = county.lower()
    if slug in FL_SUPPORTED_COUNTIES:
        return True
    return slug.endswith("countyfl") or slug in FL_SUPPORTED_COUNTIES
