from app.config.assessor_portals import resolve_assessor_search_url
from app.config.florida_portals import (
    ORANGE_SEARCH_URL,
    build_miami_dade_property_search_url,
    extract_miami_dade_folio_from_url,
    resolve_florida_county_sources,
    is_broward_assessor,
    is_florida_pa_assessor,
    is_florida_schneider,
    is_miami_dade_assessor,
    is_miami_dade_recorder,
    is_orange_county_assessor,
    is_florida_recorder,
    is_myflorida_county_recorder,
    MIAMI_DADE_SEARCH_URL,
    MIAMI_DADE_RECORDER_SEARCH_URL,
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
    parcel_record_from_miami_dade_detail,
)


def test_orange_county_detection():
    assert is_orange_county_assessor("https://ocpaweb.ocpafl.org/parcelsearch")
    assert is_orange_county_assessor("https://www.ocpafl.org/parcelsearch")


def test_miami_dade_detection():
    assert is_miami_dade_assessor("https://apps.miamidadepa.gov/propertysearch/#/")
    assert is_miami_dade_assessor("https://www.miamidade.gov/Apps/PA/propertysearch/#/")
    assert is_miami_dade_recorder("https://www.miamidadeclerk.gov/clerk/home.page")
    assert is_miami_dade_recorder("https://onlineservices.miamidadeclerk.gov/officialrecords")


def test_resolve_miami_dade_urls():
    assert resolve_florida_assessor_url("https://www.miamidade.gov/pa/") == MIAMI_DADE_SEARCH_URL
    assert resolve_florida_recorder_url(
        "https://www.miamidadeclerk.gov/clerk/home.page",
        "miami-dade",
    ) == MIAMI_DADE_RECORDER_SEARCH_URL


def test_miami_dade_folio_url_helpers():
    sample = "https://apps.miamidadepa.gov/PropertySearch/#/?folio=30-4009-094-0070"
    assert extract_miami_dade_folio_from_url(sample) == "30-4009-094-0070"
    built = build_miami_dade_property_search_url("30-4009-094-0070", sample)
    assert built.endswith("/#/?folio=30-4009-094-0070")
    assert "miamidadepa.gov" in built


def test_resolve_florida_county_sources_miami_dade():
    sources = resolve_florida_county_sources("miami-dade", "30-4009-096-0060")
    assert sources.assessor_url == MIAMI_DADE_SEARCH_URL
    assert sources.recorder_url == MIAMI_DADE_RECORDER_SEARCH_URL
    assert sources.gis_url == MIAMI_DADE_SEARCH_URL
    assert "county-taxes.net" in (sources.treasurer_url or "")


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


def test_parcel_record_from_miami_dade_detail():
    parcel = parcel_record_from_miami_dade_detail(
        {
            "folio": "30-4009-096-0060",
            "owner": "MARIA C MARRERO LE REM ZORAIDA C MARRERO",
            "property_address": "2125 SW 93 CT",
            "mailing_address": "2125 SW 93 CT MIAMI FL 33165",
            "subdivision": "WESTCHESTER PARK SEC 11 AMEND",
            "full_legal_description": (
                "WESTCHESTER PARK SEC 11 AMEND PB 137-3 LOT 58A BLK 1 "
                "LOT SIZE 6553 SQ FT OR 14043-2589 0389 1"
            ),
            "assessed_value": "$204,900",
            "bedrooms": "3",
            "bathrooms": "2",
            "living_area": "1,646",
            "year_built": "1989",
            "assessment_information_table": {
                "headers": ["", "2026", "2025", "2024"],
                "rows": [
                    ["Assessed Value", "$204,900", "$198,000", "$190,000"],
                    ["Market Value", "$505,056", "$480,000", "$460,000"],
                ],
            },
            "sales_history": [
                {
                    "sale_date": "07/27/2010",
                    "sale_price": "$100",
                    "book_page": "1494 / 2483",
                    "qualification": "Corrective, tax or QCD; min consideration",
                    "previous_owner": "MARIA C MARRERO",
                }
            ],
            "land_information": {"land use": "GENERAL", "calc value": "$281,779"},
            "building_information": {"year built": "1989", "living sq. ft.": "1,945"},
            "extra_features": [{"feature": "Patio - Concrete Slab", "calc value": "$1,404"}],
            "fields": {
                "folio": "30-4009-096-0060",
                "owner": "MARIA C MARRERO LE REM ZORAIDA C MARRERO",
                "property address": "2125 SW 93 CT",
            },
        },
        source_url="https://apps.miamidadepa.gov/propertysearch/#/",
    )
    assert parcel.apn == "30-4009-096-0060"
    assert parcel.owner_name == "MARIA C MARRERO LE REM ZORAIDA C MARRERO"
    assert parcel.property_address == "2125 SW 93 CT"
    assert parcel.assessed_value == 204900.0
    assert "WESTCHESTER PARK" in (parcel.legal_desc or "")
    assert len(parcel.raw_json["assessment_information_table"]["rows"]) == 2
    assert len(parcel.raw_json["chain_of_title"]) == 1


def test_extract_valid_miami_dade_folio():
    from app.extraction.florida_extractors import extract_valid_miami_dade_folio

    assert extract_valid_miami_dade_folio("30-4009-096-0060") == "30-4009-096-0060"
    assert extract_valid_miami_dade_folio("SEARCH:") is None
    assert extract_valid_miami_dade_folio("Folio # 30-4009-096-0060") == "30-4009-096-0060"


def test_is_valid_miami_dade_legal_desc():
    from app.extraction.florida_extractors import is_valid_miami_dade_legal_desc

    assert is_valid_miami_dade_legal_desc("WESTCHESTER PARK SEC 11 AMEND PB 137-3 LOT 58A BLK 1")
    assert not is_valid_miami_dade_legal_desc("Patio - Concrete Slab 2011 408 $1,404")


def test_parse_currency_value_ignores_bare_years():
    from app.extraction.florida_extractors import _parse_currency_value

    assert _parse_currency_value("$250,000") == 250000.0
    assert _parse_currency_value("2026") is None
    assert _parse_currency_value("$2026") == 2026.0


def test_miami_dade_section_fields_in_raw_json():
    parcel = parcel_record_from_miami_dade_detail(
        {
            "folio": "30-4009-096-0060",
            "owner": "MARIA C MARRERO",
            "property_address": "2125 SW 93 CT",
            "assessed_value": "$204,900",
            "full_legal_description": "WESTCHESTER PARK SEC 11 AMEND\nPB 137-3\nLOT 58A BLK 1",
            "assessment_information_table": {
                "headers": ["", "2026", "2025", "2024"],
                "rows": [
                    ["Land Value", "$281,779", "$270,000", "$255,000"],
                    ["Assessed Value", "$204,900", "$198,000", "$190,000"],
                ],
            },
            "benefits_information_table": {
                "headers": ["Benefit", "Type", "2026", "2025", "2024"],
                "rows": [["Homestead", "Exemption", "$25,000", "$25,000", "$25,000"]],
            },
            "sales_information_table": {
                "headers": ["Previous Sale", "Price", "OR Book-Page", "Qualification Description", "Previous Owner 1"],
                "rows": [["07/27/2010", "$100", "1494 / 2483", "Corrective, tax or QCD", "MARIA C MARRERO"]],
            },
            "sales_history": [
                {
                    "sale_date": "07/27/2010",
                    "sale_price": "$100",
                    "book_page": "1494 / 2483",
                    "qualification": "Corrective, tax or QCD",
                    "previous_owner": "MARIA C MARRERO",
                }
            ],
        }
    )
    assert parcel.raw_json["assessment_information_table"]["rows"][0][0] == "Land Value"
    assert parcel.raw_json["benefits_information_table"]["headers"][0] == "Benefit"
    assert len(parcel.raw_json["chain_of_title"]) == 1


def test_miami_dade_garbage_extraction_rejected():
    from app.extraction.florida_extractors import is_garbage_assessor_text, is_valid_miami_dade_extraction

    assert is_garbage_assessor_text(
        "Property search criteria ADDRESS OWNER NAME SUBDIVISION NAME FOLIO SEARCH"
    )
    parcel = parcel_record_from_miami_dade_detail(
        {
            "folio": "30-4009-096-0060",
            "owner": "Property search criteria ADDRESS OWNER NAME SUBDIVISION NAME FOLIO",
            "property_address": "2125 SW 93 CT",
        }
    )
    assert not is_valid_miami_dade_extraction(parcel)


def test_parcel_record_from_florida_data():
    parcel = parcel_record_from_florida_data(
        {"folio": "01-4138-019-0430", "owner name": "JANE DOE"},
        source_url="https://example.com",
    )
    assert parcel.apn == "01-4138-019-0430"
    assert parcel.owner_name == "JANE DOE"
    assert parcel.raw_json["source_url"] == "https://example.com"
