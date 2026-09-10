from app.config.assessor_portals import resolve_assessor_search_url
from app.config.florida_portals import (
    ORANGE_SEARCH_URL,
    is_broward_assessor,
    is_florida_pa_assessor,
    is_florida_schneider,
    is_miami_dade_assessor,
    is_orange_county_assessor,
    is_florida_recorder,
    is_myflorida_county_recorder,
    normalize_florida_pa_parcel,
    normalize_florida_parcel,
    format_florida_pa_address_for_search,
    parse_florida_pa_address,
    resolve_florida_assessor_url,
    resolve_florida_recorder_url,
)
from app.extraction.florida_extractors import (
    extract_florida_parcel_from_html,
    parcel_record_from_florida_data,
    parcel_record_from_florida_pa_detail,
)


def test_orange_county_detection():
    assert is_orange_county_assessor("https://ocpaweb.ocpafl.org/parcelsearch")
    assert is_orange_county_assessor("https://www.ocpafl.org/parcelsearch")


def test_miami_dade_detection():
    assert is_miami_dade_assessor("https://www.miamidade.gov/Apps/PA/propertysearch/#/")


def test_broward_detection():
    assert is_broward_assessor("https://web.bcpa.net/BcpaClient/#/Record-Search")


def test_columbia_floridapa_detection():
    assert is_florida_pa_assessor("https://columbia.floridapa.com/gis/")
    assert resolve_florida_assessor_url("https://columbia.floridapa.com/") == (
        "https://columbia.floridapa.com/gis/"
    )


def test_normalize_columbia_parcel():
    assert normalize_florida_pa_parcel("12345612345678") == "12-34-56-12345-678"
    assert normalize_florida_parcel("12345612345678", county="columbia") == "12-34-56-12345-678"


def test_parse_florida_pa_address():
    assert parse_florida_pa_address("542 N MARION AVE") == ("542", "N MARION AVE")
    assert parse_florida_pa_address("542 N MARION AVE, LAKE CITY, FL") == (
        "542",
        "N MARION AVE",
    )
    assert parse_florida_pa_address("MARION AVE") == ("", "MARION AVE")


def test_format_florida_pa_address_for_search():
    assert format_florida_pa_address_for_search("542 N MARION AVE") == "542 N MARION AVE"
    assert format_florida_pa_address_for_search("542 N MARION AVE, LAKE CITY, FL") == (
        "542 N MARION AVE"
    )


def test_florida_schneider_detection():
    url = "https://qpublic.schneidercorp.com/Application.aspx?App=BayCountyFL&PageType=Search"
    assert is_florida_schneider(url)
    assert "PageType=Search" in resolve_florida_assessor_url(url)


def test_resolve_orange_search_url():
    assert resolve_assessor_search_url("https://ocpaweb.ocpafl.org/") == ORANGE_SEARCH_URL


def test_florida_tax_account_and_url():
    from app.config.florida_portals import florida_pa_parcel_to_tax_account, resolve_florida_tax_url

    assert florida_pa_parcel_to_tax_account("00-00-00-12003-001") == "R12003-001"
    assert florida_pa_parcel_to_tax_account("00-00-00-12005-000") == "R12005-000"
    assert resolve_florida_tax_url("columbia", "00-00-00-12003-001") == (
        "https://columbia.floridatax.us/PropertyDetail?p=R12003-001"
    )
    assert resolve_florida_tax_url("columbia", "00-00-00-12005-000") == (
        "https://columbia.floridatax.us/PropertyDetail?p=R12005-000"
    )


def test_myflorida_county_recorder_detection():
    url = "https://www.myfloridacounty.com/orisearch/12"
    assert is_florida_recorder(url)
    assert is_myflorida_county_recorder(url)
    assert resolve_florida_recorder_url(url, "columbia") == url
    assert resolve_florida_recorder_url(
        "https://www.myfloridacounty.com/",
        "columbia",
    ) == "https://www.myfloridacounty.com/orisearch/12"


def test_normalize_orange_parcel():
    assert normalize_florida_parcel("2221311234000010", county="orange") == "22-21-31-1234-00-0010"


def test_normalize_miami_dade_folio():
    assert normalize_florida_parcel("0141380190430", county="miami-dade") == "01-4138-019-0430"


def test_extract_florida_parcel_from_html():
    html = """
    <html><body>
    <table>
      <tr><th>Parcel ID</th><td>22-21-31-1234-00-010</td></tr>
      <tr><th>Owner</th><td>JOHN SMITH</td></tr>
      <tr><th>Site Address</th><td>123 MAIN ST ORLANDO FL</td></tr>
      <tr><th>Just Value</th><td>$350,000</td></tr>
    </table>
    </body></html>
    """
    parcel = extract_florida_parcel_from_html(html)
    assert parcel.apn == "22-21-31-1234-00-010"
    assert parcel.owner_name == "JOHN SMITH"
    assert parcel.property_address == "123 MAIN ST ORLANDO FL"
    assert parcel.assessed_value == 350000.0


def test_split_florida_pa_owner_single_line():
    from app.extraction.florida_extractors import _split_florida_pa_owner

    owner, mailing, _ = _split_florida_pa_owner(
        "MULLINS REGINALD T SR MULLINS SHIRLEY ANN 1010 NW DYSON TER LAKE CITY, FL 32055"
    )
    assert owner == "MULLINS REGINALD T SR"
    assert mailing == "1010 NW DYSON TER LAKE CITY, FL 32055"


def test_parcel_record_from_florida_pa_detail():
    parcel = parcel_record_from_florida_pa_detail(
        {
            "parcel": "00-00-00-12004-001 (40589)",
            "owner": "MULLINS REGINALD T SR\n1010 NW DYSON TER\nLAKE CITY, FL 32055",
            "site": "542 N MARION AVE, LAKE CITY",
            "description": "N DIV: COMM NW COR BLOCK 77",
            "assessed_value": "$60,293",
            "sales_history": [
                {
                    "sale_date": "6/1/2023",
                    "sale_price": "$100",
                    "book_page": "1494 / 2483",
                    "deed_type": "WD",
                }
            ],
        },
        source_url="https://columbia.floridapa.com/gis/recordSearch_3_Details/",
    )
    assert parcel.apn == "00-00-00-12004-001"
    assert parcel.owner_name == "MULLINS REGINALD T SR"
    assert parcel.assessed_value == 60293.0
    assert len(parcel.raw_json["chain_of_title"]) == 1
    assert parcel.raw_json["chain_of_title"][0]["sale_price"] == 100.0


def test_parcel_record_from_florida_data():
    parcel = parcel_record_from_florida_data(
        {"folio": "01-4138-019-0430", "owner name": "JANE DOE"},
        source_url="https://example.com",
    )
    assert parcel.apn == "01-4138-019-0430"
    assert parcel.owner_name == "JANE DOE"
    assert parcel.raw_json["source_url"] == "https://example.com"
