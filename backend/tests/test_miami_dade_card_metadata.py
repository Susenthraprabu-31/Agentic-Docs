from app.drivers.recorder.miami_dade_recorder import _merge_search_result_metadata


def test_merge_search_result_metadata_prefers_card_address_and_parties():
    card = {
        "party_name": "VILA SONIA H ET AL / WHOM CONCERNED",
        "grantee": "VILA SONIA H ET AL",
        "grantor": "WHOM CONCERNED",
        "property_address": "9856 SW 157 ST",
        "book_page": "15755/674",
        "instrument_number": "1992 R 502438",
    }
    record = {
        "grantor": "GENERIC GRANTOR",
        "grantee": "GENERIC GRANTEE",
        "legal_description": "LOT 6",
    }
    merged = _merge_search_result_metadata(card, record)
    assert merged["property_address"] == "9856 SW 157 ST"
    assert merged["grantee"] == "VILA SONIA H ET AL"
    assert merged["grantor"] == "WHOM CONCERNED"
    assert merged["legal_description"] == "LOT 6"


def test_merge_search_result_metadata_keeps_distinct_party_rows():
    first = _merge_search_result_metadata(
        {
            "party_name": "TORRES JORGE L ET AL / WHOM CONCERNED",
            "grantee": "TORRES JORGE L ET AL",
            "grantor": "WHOM CONCERNED",
            "book_page": "15755/674",
        },
        {},
    )
    second = _merge_search_result_metadata(
        {
            "party_name": "WHOM CONCERNED / TORRES JORGE L ET AL",
            "grantee": "WHOM CONCERNED",
            "grantor": "TORRES JORGE L ET AL",
            "book_page": "15755/674",
        },
        {},
    )
    assert first["party_name"] != second["party_name"]
    assert first["grantee"] != second["grantee"]
