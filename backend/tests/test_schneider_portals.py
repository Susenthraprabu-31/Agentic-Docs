from app.config.assessor_portals import resolve_assessor_search_url
from app.config.schneider_portals import (
    is_florida_schneider_portal,
    is_honolulu_schneider,
    is_qpublic_global_landing_url,
    is_same_schneider_portal,
    is_schneider_portal,
    is_schneider_search_url,
    normalize_schneider_search_url,
    schneider_portal_key,
    schneider_warmup_url,
    should_use_global_qpublic_search,
)

ALACHUA_SEARCH = (
    "https://qpublic.schneidercorp.com/Application.aspx"
    "?AppID=1081&LayerID=26490&PageTypeID=2&PageID=10768"
)
ALACHUA_REPORT = (
    "https://qpublic.schneidercorp.com/Application.aspx"
    "?AppID=1081&LayerID=26490&PageTypeID=4&PageID=10770&KeyValue=08194-000-000"
)
BAY_SEARCH = (
    "https://qpublic.schneidercorp.com/Application.aspx"
    "?App=BayCountyFL&PageType=Search"
)
BAY_LANDING = (
    "https://qpublic.schneidercorp.com/Application.aspx?App=BayCountyFL"
)
HONOLULU_SEARCH = (
    "https://qpublic.schneidercorp.com/Application.aspx"
    "?App=HonoluluCountyHI&PageType=Search"
)


def test_is_schneider_portal():
    assert is_schneider_portal(ALACHUA_SEARCH)
    assert is_schneider_portal("https://www.qpublic.net/hi/honolulu/")
    assert not is_schneider_portal("https://ocpaweb.ocpafl.org/")


def test_is_honolulu_schneider():
    assert is_honolulu_schneider(HONOLULU_SEARCH)
    assert is_honolulu_schneider("https://www.qpublic.net/hi/honolulu/")
    assert not is_honolulu_schneider(ALACHUA_SEARCH)


def test_is_florida_schneider_portal_appid_style():
    assert is_florida_schneider_portal(ALACHUA_SEARCH)
    assert is_florida_schneider_portal(BAY_SEARCH)
    assert not is_florida_schneider_portal(HONOLULU_SEARCH)


def test_is_schneider_search_url_appid_style():
    assert is_schneider_search_url(ALACHUA_SEARCH)
    assert is_schneider_search_url(BAY_SEARCH)
    assert not is_schneider_search_url(ALACHUA_REPORT)


def test_normalize_schneider_search_url_app_name():
    normalized = normalize_schneider_search_url(BAY_LANDING)
    assert "PageType=Search" in normalized
    assert "App=BayCountyFL" in normalized


def test_normalize_schneider_search_url_appid_report_to_search():
    normalized = normalize_schneider_search_url(ALACHUA_REPORT)
    assert "PageTypeID=2" in normalized
    assert "KeyValue=" not in normalized
    assert "AppID=1081" in normalized


def test_normalize_schneider_search_url_preserves_alachua_search():
    assert normalize_schneider_search_url(ALACHUA_SEARCH) == ALACHUA_SEARCH


def test_resolve_assessor_search_url_alachua_appid():
    resolved = resolve_assessor_search_url(ALACHUA_SEARCH)
    assert "PageTypeID=2" in resolved
    assert is_schneider_search_url(resolved)


def test_schneider_warmup_url():
    assert schneider_warmup_url(ALACHUA_SEARCH) is None
    assert schneider_warmup_url(BAY_LANDING) == "https://qpublic.schneidercorp.com/#search"


def test_qpublic_global_landing_detection():
    assert is_qpublic_global_landing_url("https://qpublic.schneidercorp.com/#search")
    assert is_qpublic_global_landing_url("https://qpublic.schneidercorp.com/")
    assert not is_qpublic_global_landing_url(ALACHUA_SEARCH)
    assert schneider_warmup_url(HONOLULU_SEARCH) is None
    assert schneider_warmup_url("https://www.qpublic.net/hi/honolulu/") == (
        "https://www.qpublic.net/hi/honolulu/"
    )
    assert schneider_warmup_url("https://ocpaweb.ocpafl.org/") is None


def test_schneider_portal_key_and_same_portal():
    assert schneider_portal_key(ALACHUA_SEARCH) == "appid:1081"
    assert schneider_portal_key(BAY_SEARCH) == "app:baycountyfl"
    assert is_same_schneider_portal(ALACHUA_SEARCH, ALACHUA_REPORT)
    assert not is_same_schneider_portal(ALACHUA_SEARCH, BAY_SEARCH)


def test_should_use_global_qpublic_search():
    assert not should_use_global_qpublic_search(ALACHUA_SEARCH)
    assert not should_use_global_qpublic_search(BAY_SEARCH)
    assert should_use_global_qpublic_search("https://qpublic.schneidercorp.com/#search")
