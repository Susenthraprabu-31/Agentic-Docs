from app.extraction.miami_dade_name_searches import (
    collect_recorder_party_names_for_search,
    dedupe_party_names,
    expand_name_search_variations,
    parse_miami_dade_party_name_fields,
    sanitize_miami_dade_party_name_for_search,
    build_name_searcher_report_entries,
    group_documents_by_name_search,
    resolve_name_searches_for_report,
)


def test_parse_miami_dade_party_name_fields_person():
    parsed = parse_miami_dade_party_name_fields("TORRES JORGE L")
    assert parsed["kind"] == "person"
    assert parsed["last_name"] == "TORRES"
    assert parsed["first_name"] == "JORGE"
    assert parsed["middle_name"] == "L"


def test_parse_miami_dade_party_name_fields_middle_initial_only():
    parsed = parse_miami_dade_party_name_fields("MORALES A")
    assert parsed["kind"] == "person"
    assert parsed["last_name"] == "MORALES"
    assert parsed["first_name"] == ""
    assert parsed["middle_name"] == "A"


def test_parse_miami_dade_party_name_fields_company():
    parsed = parse_miami_dade_party_name_fields("HAMLET DEV #4 LTD")
    assert parsed["kind"] == "company"
    assert parsed["company_name"] == "HAMLET DEV #4 LTD"


def test_sanitize_miami_dade_party_name_removes_commas_and_unwraps_entity():
    assert sanitize_miami_dade_party_name_for_search("INC, D R HORTON") == "D R HORTON INC"
    assert sanitize_miami_dade_party_name_for_search("D R HORTON, INC") == "D R HORTON INC"
    assert sanitize_miami_dade_party_name_for_search("MORALES, JUAN A") == "MORALES JUAN A"


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


def test_name_search_pdf_storage_key_uses_separate_folder():
    from app.drivers.recorder.miami_dade_recorder import _recorder_pdf_storage_key

    recorder_folder, _ = _recorder_pdf_storage_key("8802", "373")
    name_folder, _ = _recorder_pdf_storage_key(
        "8802",
        "373",
        searched_name="MORALES JUAN A",
    )
    assert recorder_folder.startswith("recorder_")
    assert name_folder == "name_search/MORALES_JUAN_A/8802_373"
    assert recorder_folder != name_folder


def test_group_documents_by_name_search():
    documents = [
        {
            "document_type": "DEED - DEE",
            "book_page": "31687/1679",
            "ocr_json": {"source": "recorder"},
        },
        {
            "document_type": "MORTGAGE - MOR",
            "book_page": "8802/373",
            "ocr_json": {"source": "name_searcher", "searched_name": "MORALES JUAN A"},
        },
        {
            "document_type": "CIVIL COURT PAPER - CVP",
            "book_page": "16212/2056",
            "ocr_json": {"source": "name_searcher", "searched_name": "D R HORTON INC"},
        },
    ]
    groups, primary = group_documents_by_name_search(
        documents,
        [
            {"name": "MORALES JUAN A", "source": "31687/1679"},
            {"name": "D R HORTON INC", "source": "31687/1679"},
        ],
    )
    assert len(primary) == 1
    assert primary[0]["book_page"] == "31687/1679"
    assert len(groups) == 2
    assert groups[0]["name"] == "MORALES JUAN A"
    assert groups[0]["document_count"] == 1
    assert groups[1]["name"] == "D R HORTON INC"


def test_group_documents_treats_book_page_searched_name_as_recorder():
    documents = [
        {
            "document_type": "DEED - DEE",
            "book_page": "31687/1679",
            "ocr_json": {
                "source": "name_searcher",
                "searched_name": "31687/1679",
                "storage_category": "name_searcher",
            },
        },
        {
            "document_type": "MORTGAGE - MOR",
            "book_page": "8802/373",
            "ocr_json": {"source": "name_searcher", "searched_name": "MORALES JUAN A"},
        },
    ]
    groups, primary = group_documents_by_name_search(documents)
    assert len(primary) == 1
    assert primary[0]["book_page"] == "31687/1679"
    assert len(groups) == 1
    assert groups[0]["name"] == "MORALES JUAN A"


def test_group_documents_excludes_assessor_from_recorder_primary():
    documents = [
        {
            "document_type": "Sale",
            "ocr_json": {"source": "assessor_sales"},
        },
        {
            "document_type": "Assessor Summary Report",
            "ocr_json": {"source": "assessor", "folder_name": "assessor/summary"},
        },
        {
            "document_type": "DEED - DEE",
            "book_page": "31687/1679",
            "ocr_json": {"source": "recorder"},
        },
    ]
    groups, primary = group_documents_by_name_search(documents)
    assert len(primary) == 1
    assert primary[0]["document_type"] == "DEED - DEE"
    assert len(groups) == 0


def test_official_documents_zip_uses_name_search_subfolders(tmp_path):
    import zipfile
    from app.api.routes.reports import _build_official_documents_zip

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")

    docs = [
        ("name_search", "DEED - DEE - 8802/373", pdf_path, "MORALES_JUAN_A"),
        ("name_search", "DEED - DEE - 16212/2056", pdf_path, "D_R_HORTON_INC"),
    ]
    archive = _build_official_documents_zip("run123", docs)
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
    assert "name_search/MORALES_JUAN_A/DEED_-_DEE_-_8802_373.pdf" in names
    assert "name_search/D_R_HORTON_INC/DEED_-_DEE_-_16212_2056.pdf" in names


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
