from app.config.florida_portals import (
    COLLIER_HOME_URL,
    is_collier_assessor,
    normalize_florida_parcel,
    resolve_florida_assessor_url,
)
from app.drivers.assessor.florida_assessor import COLLIER_TAB_BY_QUERY
from app.extraction.schemas import QueryType


def test_collier_assessor_detection():
    assert is_collier_assessor("https://www.collierappraiser.com/")
    assert is_collier_assessor("http://collierappraiser.com/Main_Search/search_rp.html")


def test_resolve_collier_assessor_url():
    assert (
        resolve_florida_assessor_url("https://www.collierappraiser.com/")
        == COLLIER_HOME_URL
    )


def test_normalize_collier_parcel_digits_only():
    assert normalize_florida_parcel("26659-512-000", county="collier") == "26659512000"


def test_collier_tab_mapping():
    assert COLLIER_TAB_BY_QUERY[QueryType.PARCEL] == ("Parcel ID", "Parcel ID:")
    assert COLLIER_TAB_BY_QUERY[QueryType.ADDRESS] == ("Site Address", "Site Address:")
