from app.drivers.recorder.gila_recorder_driver import _format_recorder_search_value
from app.drivers.recorder.miami_dade_recorder import (
    DEFAULT_MIAMI_DADE_BOOK_TYPE,
    resolve_miami_dade_book_type_value,
)
from app.extraction.book_page import format_book_page, format_book_page_label, parse_book_page
from app.extraction.schemas import QueryType


def test_default_miami_dade_book_type_is_deed():
    assert DEFAULT_MIAMI_DADE_BOOK_TYPE == "Deed"


def test_resolve_miami_dade_book_type_value():
    assert resolve_miami_dade_book_type_value("Deed") == "D"
    assert resolve_miami_dade_book_type_value("DB - Deeds") == "D"
    assert resolve_miami_dade_book_type_value("Official Records") == "O"
    assert resolve_miami_dade_book_type_value("PLT - Plat Book") == "P"
    assert resolve_miami_dade_book_type_value("MAP - Map Book") == "M"


def test_parse_book_page_from_fields():
    assert parse_book_page("", "1494", "2483") == ("1494", "2483")


def test_parse_book_page_from_query_value():
    assert parse_book_page("1494/2483") == ("1494", "2483")
    assert parse_book_page("1494 / 2483") == ("1494", "2483")
    assert parse_book_page("1494-2483") == ("1494", "2483")


def test_format_book_page():
    assert format_book_page("1494", "2483") == "1494/2483"
    assert format_book_page_label("1494", "2483") == "1494 / 2483"


def test_recorder_search_value_book_page():
    result = _format_recorder_search_value(QueryType.BOOK_PAGE, "1494/2483")
    assert result == "1494 / 2483"
