from app.agents.orchestrator import Orchestrator, RunContext
from app.extraction.assessor_book_page import (
    enrich_raw_json_with_latest_book_page,
    extract_latest_book_page,
)
from app.extraction.book_page import parse_book_page
from app.extraction.schemas import QueryType


def _assessor_record(chain: list[dict], sales: list[dict] | None = None) -> dict:
    raw_json = {"chain_of_title": chain}
    if sales is not None:
        raw_json["sales_history"] = sales
    return {"source": "assessor", "raw_json": raw_json}


def test_parse_book_page_assessor_formats():
    assert parse_book_page("1494 / 2483") == ("1494", "2483")
    assert parse_book_page("1494/2483") == ("1494", "2483")
    assert parse_book_page("Book 1494 Page 2483") == ("1494", "2483")
    assert parse_book_page("book: 1494 page: 2483") == ("1494", "2483")


def test_extract_latest_book_page_picks_most_recent_sale():
    record = _assessor_record(
        [
            {
                "recording_date": "6/1/2010",
                "book_page": "1000 / 2000",
                "document_type": "WD",
            },
            {
                "recording_date": "7/27/2023",
                "book_page": "1494 / 2483",
                "document_type": "WD",
            },
        ]
    )
    result = extract_latest_book_page(record)
    assert result is not None
    book, page, entry = result
    assert book == "1494"
    assert page == "2483"
    assert entry["recording_date"] == "7/27/2023"


def test_extract_latest_book_page_falls_back_to_first_entry_without_dates():
    record = _assessor_record(
        [
            {"book_page": "1111 / 2222", "document_type": "WD"},
            {"book_page": "3333 / 4444", "document_type": "WD"},
        ]
    )
    result = extract_latest_book_page(record)
    assert result == ("1111", "2222", record["raw_json"]["chain_of_title"][0])


def test_enrich_raw_json_with_latest_book_page():
    raw_json = {
        "chain_of_title": [
            {"recording_date": "7/27/2023", "book_page": "1494 / 2483", "document_type": "WD"},
        ]
    }
    enriched = enrich_raw_json_with_latest_book_page(raw_json)
    assert enriched["latest_book_page"] == {
        "book": "1494",
        "page": "2483",
        "source": "sales_information",
        "recording_date": "7/27/2023",
        "document_type": "WD",
    }


def test_refresh_book_page_from_assessor_does_not_override_input():
    orch = Orchestrator("run-book-page-test")
    ctx = RunContext(
        state="FL",
        county="miami-dade",
        query_type=QueryType.ADDRESS,
        query_value="123 Main St",
        book_number="9999",
        page_number="8888",
        book_page_source="input",
    )
    orch.records_repo.insert(
        "run-book-page-test",
        _assessor_record(
            [{"recording_date": "7/27/2023", "book_page": "1494 / 2483", "document_type": "WD"}]
        ),
    )

    refreshed = orch._refresh_book_page_from_assessor(ctx)

    assert refreshed is False
    assert ctx.book_number == "9999"
    assert ctx.page_number == "8888"
    assert ctx.book_page_source == "input"


def test_refresh_book_page_from_assessor_populates_context_from_assessor():
    orch = Orchestrator("run-book-page-test-2")
    ctx = RunContext(
        state="FL",
        county="miami-dade",
        query_type=QueryType.ADDRESS,
        query_value="123 Main St",
    )
    orch.records_repo.insert(
        "run-book-page-test-2",
        _assessor_record(
            [{"recording_date": "7/27/2023", "book_page": "1494 / 2483", "document_type": "WD"}]
        ),
    )

    refreshed = orch._refresh_book_page_from_assessor(ctx)

    assert refreshed is True
    assert ctx.book_number == "1494"
    assert ctx.page_number == "2483"
    assert ctx.book_page_source == "assessor"
