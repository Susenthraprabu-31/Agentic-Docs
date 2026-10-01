from app.config.florida_portals import (
    DESOTO_GIS_ENTRY_URL,
    DESOTO_HOME_URL,
    get_florida_pa_gis_county_from_url,
    is_desoto_assessor,
    is_florida_pa_gis_assessor,
    resolve_florida_assessor_url,
    resolve_florida_pa_gis_url,
)


def test_desoto_assessor_detection():
    assert is_desoto_assessor("https://www.desotopa.com/")
    assert is_florida_pa_gis_assessor("https://www.desotopa.com/GIS/")


def test_desoto_county_slug_from_url():
    assert get_florida_pa_gis_county_from_url("https://www.desotopa.com/") == "desoto"


def test_resolve_desoto_urls():
    assert resolve_florida_assessor_url("https://www.desotopa.com/") == DESOTO_HOME_URL
    assert resolve_florida_pa_gis_url("desoto", "https://www.desotopa.com/") == DESOTO_GIS_ENTRY_URL
