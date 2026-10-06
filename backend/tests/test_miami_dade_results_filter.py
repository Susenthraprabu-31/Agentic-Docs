import re

from app.config.florida_portals import format_miami_dade_address_for_search


def _parse_results_returned_count(body_text: str) -> int:
    match = re.search(r"(\d+)\s+results?\s+returned", body_text, re.I)
    return int(match.group(1)) if match else 0


def test_parse_results_returned_count():
    assert _parse_results_returned_count("418 RESULTS RETURNED") == 418
    assert _parse_results_returned_count("1 result returned") == 1
    assert _parse_results_returned_count("No matches") == 0


def test_name_search_address_filter_uses_street_only():
    address = "24324 SW 118 CT, Miami, FL 33175"
    assert format_miami_dade_address_for_search(address) == "24324 SW 118 CT"
