from app.config.assessor_portals import (
    HONOLULU_LANDING_URL,
    HONOLULU_PROPERTY_SEARCH_URL,
    HONOLULU_SEARCH_URL,
    is_honolulu_schneider,
    resolve_assessor_search_url,
)
from app.drivers.assessor.gila_assessor_driver import _normalize_honolulu_parcel


def test_resolve_honolulu_landing_stays_on_landing():
    assert resolve_assessor_search_url(HONOLULU_LANDING_URL) == HONOLULU_LANDING_URL


def test_honolulu_property_search_intermediate_url():
    assert HONOLULU_PROPERTY_SEARCH_URL.endswith("search.html")


def test_honolulu_schneider_detection():
    assert is_honolulu_schneider(HONOLULU_SEARCH_URL)
    assert is_honolulu_schneider(HONOLULU_LANDING_URL)


def test_normalize_honolulu_parcel():
    assert _normalize_honolulu_parcel("390300650010") == "390300650010"
    assert _normalize_honolulu_parcel("3-9030-065-0010") == "390300650010"
