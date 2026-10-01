from app.drivers.assessor.florida_assessor import (
    _is_miami_dade_detail_body_text,
    _is_miami_dade_possible_match_results_text,
    _miami_dade_result_matches_address_query,
)


POSSIBLE_MATCH_BODY = """
Exact match not found for search criteria entered. 1 possible match(es) are listed below.
Click on the Folio number to view property details.
FOLIO 30-4009-094-0410
SUB-DIVISION WESTCHESTER PARK SEC II
OWNER GLADYS ROMERO SARDINAS TRS
PROP. ADDR 9423 SW 21 TER
"""

DETAIL_BODY = """
Folio 30-4009-094-0410
Owner GLADYS ROMERO SARDINAS TRS
Property Information
Sales Information
Assessment Information
Just Value $350,000
"""


def test_possible_match_results_text_detection():
    assert _is_miami_dade_possible_match_results_text(POSSIBLE_MATCH_BODY)
    assert not _is_miami_dade_possible_match_results_text(DETAIL_BODY)


def test_detail_body_text_rejects_possible_match_page():
    assert not _is_miami_dade_detail_body_text(POSSIBLE_MATCH_BODY)
    assert _is_miami_dade_detail_body_text(DETAIL_BODY)


def test_address_query_matches_ter_vs_terr():
    result_text = "9423 SW 21 TER UNINCORPORATED COUNTY"
    assert _miami_dade_result_matches_address_query("9423 SW 21 TERR", result_text)
    assert _miami_dade_result_matches_address_query("9423 SW 21 TER", result_text)
