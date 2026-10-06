from app.agents.orchestrator import Orchestrator, RunContext, _apply_input_data_to_ctx
from app.extraction.assessor_book_page import extract_all_book_pages, extract_latest_book_page
from app.extraction.schemas import QueryType
from app.pipeline.graph_executor import get_input_node_data
from tests.test_assessor_book_page import _assessor_record


def test_get_input_node_data_reads_search_scope():
    graph = {
        "nodes": [
            {
                "id": "input",
                "node_id": "input",
                "data": {"searchScope": "current", "searchLimit": 5},
            }
        ],
        "edges": [],
    }
    data = get_input_node_data(graph)
    assert data["searchScope"] == "current"
    assert data["searchLimit"] == 5


def test_apply_input_data_to_ctx_sets_search_scope_and_limit():
    ctx = RunContext(state="FL", county="miami-dade", query_type=QueryType.ADDRESS, query_value="123 Main")
    _apply_input_data_to_ctx(
        {
            "searchScope": "current",
            "searchLimit": 10,
            "address": "123 Main",
        },
        ctx,
    )
    assert ctx.search_scope == "current"
    assert ctx.search_limit == 10


def test_current_search_uses_only_latest_assessor_sale():
    record = _assessor_record(
        [
            {"book_page": "31687/1679", "recording_date": "2019-11-13"},
            {"book_page": "30576/2086", "recording_date": "2017-06-16"},
            {"book_page": "28175/0053", "recording_date": "2012-06-29"},
        ]
    )
    all_pages = extract_all_book_pages(record)
    latest = extract_latest_book_page(record)
    assert len(all_pages) == 3
    assert latest is not None
    assert (latest[0], latest[1]) == (all_pages[0][0], all_pages[0][1])


def test_get_assessor_sales_book_pages_respects_search_scope():
    assessor = _assessor_record(
        [
            {"book_page": "31687/1679", "recording_date": "2019-11-13"},
            {"book_page": "30576/2086", "recording_date": "2017-06-16"},
            {"book_page": "28175/0053", "recording_date": "2012-06-29"},
        ]
    )
    orchestrator = Orchestrator("run-test-scope")

    def _mock_assessor_record():
        return assessor

    orchestrator._get_assessor_record = _mock_assessor_record

    current_ctx = RunContext(
        state="FL",
        county="miami-dade",
        query_type=QueryType.PARCEL,
        query_value="30-6924-001-0030",
        search_scope="current",
    )
    full_ctx = RunContext(
        state="FL",
        county="miami-dade",
        query_type=QueryType.PARCEL,
        query_value="30-6924-001-0030",
        search_scope="full",
    )

    current_pages = orchestrator._get_assessor_sales_book_pages(current_ctx)
    full_pages = orchestrator._get_assessor_sales_book_pages(full_ctx)

    assert len(current_pages) == 1
    assert current_pages[0][:2] == ("31687", "1679")
    assert len(full_pages) == 3
    assert [page[:2] for page in full_pages] == [
        ("31687", "1679"),
        ("30576", "2086"),
        ("28175", "53"),
    ]


def test_get_assessor_sales_book_pages_skips_explicit_input_book_page():
    orchestrator = Orchestrator("run-test-scope")
    orchestrator._get_assessor_record = lambda: _assessor_record(
        [{"book_page": "31687/1679", "recording_date": "2019-11-13"}]
    )

    ctx = RunContext(
        state="FL",
        county="miami-dade",
        query_type=QueryType.BOOK_PAGE,
        query_value="31687/1679",
        book_number="31687",
        page_number="1679",
        book_page_source="input",
        search_scope="full",
    )

    assert orchestrator._get_assessor_sales_book_pages(ctx) == []


def test_resolve_annual_bills_capture_count_respects_search_scope():
    from app.drivers.tax.florida_tax_driver import resolve_annual_bills_capture_count

    assert resolve_annual_bills_capture_count("full", 13) == 13
    assert resolve_annual_bills_capture_count("current", 13) == 2
    assert resolve_annual_bills_capture_count("full", 0) == 0
    assert resolve_annual_bills_capture_count("current", 1) == 1
