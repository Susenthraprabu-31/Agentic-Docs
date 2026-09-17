from app.drivers.recorder.gila_recorder_driver import _format_recorder_search_value
from app.drivers.recorder.acclaimweb_recorder import format_acclaimweb_party_name, resolve_party_type_from_notes
from app.extraction.schemas import QueryType


def test_format_recorder_owner_name_to_last_first():
    result = _format_recorder_search_value(QueryType.OWNER, "Jasmine Mal")
    assert result == "Mal, Jasmine"


def test_format_recorder_keeps_existing_comma_name():
    result = _format_recorder_search_value(QueryType.OWNER, "Mal, Jasmine")
    assert result == "Mal, Jasmine"


def test_format_acclaimweb_party_name():
    assert format_acclaimweb_party_name("Leonora Mc") == "Mc, Leonora"


def test_format_acclaimweb_single_name_unchanged():
    assert format_acclaimweb_party_name("Leonora") == "Leonora"


def test_resolve_party_type_all_from_instructions():
    notes = "Search by all name, expand first result row and click search button"
    assert resolve_party_type_from_notes(notes) == "all"


def test_resolve_party_type_grantor_only_when_explicit():
    assert resolve_party_type_from_notes("Search by grantor name") == "grantor"
    assert resolve_party_type_from_notes("Search by owner name") is None
