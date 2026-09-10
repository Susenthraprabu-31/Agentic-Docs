from app.drivers.netronline.netronline_driver import _classify_office, _pick_online_url


def test_honolulu_office_names():
    assert _classify_office("Honolulu/Oahu (City/County) Real Property Tax Assessment") == "assessor"
    assert _classify_office("Bureau of Conveyances (Statewide Recording)") == "recorder"
    assert _classify_office("State Mapping/GIS") == "gis"
    assert _classify_office("Historic Aerials") is None


def test_gila_office_names():
    assert _classify_office("Gila Assessor") == "assessor"
    assert _classify_office("Gila Recorder") == "recorder"
    assert _classify_office("Gila Mapping / GIS") == "gis"


def test_pick_online_url():
    links = [
        {"text": "Fix", "href": "#"},
        {"text": "Go to Data Online", "href": "https://qpublic.schneidercorp.com/test"},
    ]
    assert _pick_online_url(links) == "https://qpublic.schneidercorp.com/test"


def test_florida_office_names():
    assert _classify_office("Orange County Property Appraiser") == "assessor"
    assert _classify_office("Orange County Comptroller Official Records") == "recorder"
    assert _classify_office("Broward County Tax Collector") is None
    assert _classify_office("Broward County GIS Mapping") == "gis"


def test_pick_online_url_skips_tax_payment_portal():
    links = [
        {"text": "Go to Data Online", "href": "https://county-taxes.net/broward/property-tax"},
        {"text": "Go to Data Online", "href": "https://web.bcpa.net/BcpaClient/"},
    ]
    assert _pick_online_url(links) == "https://web.bcpa.net/BcpaClient/"


def test_pick_online_url_ignores_netr_map_for_recorder():
    links = [
        {"text": "Map", "href": "https://map.netronline.com/hawaii-honolulu/15"},
        {"text": "Go to Data Online", "href": "https://qpublic.schneidercorp.com/Application.aspx?App=HonoluluCountyHI&PageType=Search"},
    ]
    assert _pick_online_url(links) == "https://qpublic.schneidercorp.com/Application.aspx?App=HonoluluCountyHI&PageType=Search"
    assert _pick_online_url(links, allow_map=True) == "https://qpublic.schneidercorp.com/Application.aspx?App=HonoluluCountyHI&PageType=Search"
