from app.extraction.miami_dade_name_searches import (
    collect_recorder_party_names_for_search,
    dedupe_party_names,
    expand_name_search_variations,
    parse_miami_dade_party_name_fields,
    build_name_searcher_report_entries,
    resolve_name_searches_for_report,
)


def test_parse_miami_dade_party_name_fields_person():
    parsed = parse_miami_dade_party_name_fields("TORRES JORGE L")
    assert parsed["kind"] == "person"
    assert parsed["last_name"] == "TORRES"
    assert parsed["first_name"] == "JORGE"
    assert parsed["middle_name"] == "L"


def test_parse_miami_dade_party_name_fields_company():
    parsed = parse_miami_dade_party_name_fields("HAMLET DEV #4 LTD")
    assert parsed["kind"] == "company"
    assert parsed["company_name"] == "HAMLET DEV #4 LTD"


def test_collect_recorder_party_names_for_search():
    documents = [
        {
            "document_type": "Warranty Deed",
            "ocr_json": {
                "party_names": ["ROMERO GLADYS", "WESTCHESTER CORP"],
                "grantor": "ROMERO GLADYS",
                "grantee": "WESTCHESTER CORP",
            },
        },
        {
            "document_type": "AI Title Analysis",
            "ocr_json": {"party_names": ["IGNORE ME"]},
        },
    ]
    names = collect_recorder_party_names_for_search(documents)
    assert "ROMERO GLADYS" in names
    assert "WESTCHESTER CORP" in names
    assert "IGNORE ME" not in names


def test_build_name_searcher_report_entries_uses_searched_names_only():
    documents = [
        {
            "ocr_json": {
                "party_names": ["MORALES JUAN A"],
                "book_number": "31687",
                "page_number": "1679",
            },
            "book_page": "31687/1679",
        }
    ]
    entries = build_name_searcher_report_entries(documents, ["MORALES JUAN A", "MORALES JUAN"])
    assert len(entries) == 2
    assert entries[0]["name"] == "MORALES JUAN A"
    assert entries[0]["source"] == "31687/1679"


def test_resolve_name_searches_for_report_from_node_results():
    plan_json = {
        "node_results": {
            "name_searcher": {
                "names_searched": ["MORALES JUAN A", "D R HORTON INC"],
                "name_search_entries": [
                    {"name": "MORALES JUAN A", "source": "31687/1679"},
                    {"name": "D R HORTON INC", "source": "31687/1679"},
                ],
            }
        }
    }
    entries = resolve_name_searches_for_report(plan_json)
    assert len(entries) == 2
    assert entries[0]["name"] == "MORALES JUAN A"
    assert entries[1]["name"] == "D R HORTON INC"
