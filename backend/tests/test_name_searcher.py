from app.extraction.miami_dade_name_searches import (
    build_names_to_search,
    dedupe_equivalent_party_names,
    collect_current_owner_names_for_search,
    collect_current_owner_search_names,
    collect_recorder_party_names_for_search,
    collect_related_individual_names_from_documents,
    dedupe_party_names,
    expand_name_search_variations,
    build_name_search_queue,
    is_base_name_for_search,
    parse_miami_dade_party_name_fields,
    sanitize_miami_dade_party_name_for_search,
    should_apply_address_filter_for_name_search,
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


def test_collect_current_owner_names_for_search_uses_assessor_owner():
    names = collect_current_owner_names_for_search(
        property_record={
            "owner_name": "FERNANDEZ AURELIO; TORRES MARIA",
            "raw_json": {
                "owner_rows": [
                    {"Owner Name": "FERNANDEZ AURELIO"},
                    {"Owner Name": "TORRES MARIA"},
                ]
            },
        },
    )
    assert names == ["FERNANDEZ AURELIO", "TORRES MARIA"]
    recorder_names = collect_recorder_party_names_for_search(
        [
            {
                "ocr_json": {
                    "grantor": "OLD GRANTOR",
                    "grantee": "OLD GRANTEE",
                }
            }
        ]
    )
    assert "OLD GRANTOR" in recorder_names
    assert "OLD GRANTOR" not in names


def test_expand_compound_surname_variations_like_manual_title_search():
    variants = expand_name_search_variations("CORTES RIOS JUAN C")
    assert "CORTES RIOS JUAN C" in variants
    assert "CORTES-RIOS JUAN C" in variants
    assert "CORTESRIOS JUAN C" in variants
    assert "CORTES JUAN C" in variants
    assert "RIOS JUAN C" in variants


def test_dedupe_equivalent_party_names_collapses_entity_aliases():
    names = dedupe_equivalent_party_names(
        [
            "MIAMI EDGE INVESTMENTS INC",
            "MIAMI EDGE INVESTMENTS",
            "CORTES RIOS JUAN C",
        ]
    )
    assert names == ["MIAMI EDGE INVESTMENTS INC", "CORTES RIOS JUAN C"]


def test_build_names_to_search_expands_entity_owner_name():
    names = build_names_to_search(["MIAMI EDGE INVESTMENTS INC"], expand_variations=True)
    assert names == ["MIAMI EDGE INVESTMENTS INC"]
    variants = expand_name_search_variations("MIAMI EDGE INVESTMENTS INC")
    assert "MIAMI EDGE INVESTMENTS" in variants


def test_collect_related_individual_names_from_owner_documents():
    documents = [
        {
            "grantee": "MIAMI EDGE INVESTMENTS INC A FLORIDA CORPORATION",
            "grantor": "CORTES RIOS JUAN C",
            "ocr_json": {
                "grantee": "MIAMI EDGE INVESTMENTS INC A FLORIDA CORPORATION",
                "grantor": "CORTES RIOS JUAN C",
                "party_names": ["CORTES RIOS JUAN C", "MIAMI EDGE INVESTMENTS INC"],
            },
        },
        {
            "grantee": "MIAMI EDGE INVESTMENTS INC",
            "grantor": "FUENTES JUAN P",
            "ocr_json": {
                "grantee": "MIAMI EDGE INVESTMENTS INC",
                "grantor": "FUENTES JUAN P",
            },
        },
    ]
    related = collect_related_individual_names_from_documents(
        documents,
        ["MIAMI EDGE INVESTMENTS INC"],
    )
    assert "CORTES RIOS JUAN C" in related
    assert "FUENTES JUAN P" in related


def test_collect_current_owner_search_names_includes_chain_parties():
    names = collect_current_owner_search_names(
        property_record={"owner_name": "MIAMI EDGE INVESTMENTS INC"},
        chain_of_title=[
            {"grantor": "CORTES RIOS JUAN C", "grantee": "MIAMI EDGE INVESTMENTS INC"},
            {"grantor": "FUENTES JUAN P", "grantee": "CORTES RIOS JUAN C"},
        ],
    )
    assert "MIAMI EDGE INVESTMENTS INC" in names
    assert "CORTES RIOS JUAN C" in names
    assert "FUENTES JUAN P" in names


def test_collect_current_owner_names_prefers_explicit_input_owner():
    names = collect_current_owner_names_for_search(
        input_owner_name="MORALES JUAN A",
        ctx_owner_name="OTHER OWNER",
    )
    assert names == ["MORALES JUAN A", "OTHER OWNER"]


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


def test_is_base_name_for_search_recognizes_original_party_names():
    base_names = ["MIAMI EDGE INVESTMENTS INC", "CORTES RIOS JUAN C"]
    assert is_base_name_for_search("MIAMI EDGE INVESTMENTS INC", base_names)
    assert is_base_name_for_search("CORTES RIOS JUAN C", base_names)
    assert not is_base_name_for_search("CORTES JUAN C", base_names)


def test_build_name_search_queue_marks_variations():
    queue = build_name_search_queue(["CORTES RIOS JUAN C"], expand_variations=True)
    flags = {name: is_variation for name, is_variation in queue}
    assert flags["CORTES RIOS JUAN C"] is False
    assert flags.get("CORTES-RIOS JUAN C") is True
    assert flags.get("CORTES JUAN C") is True


def test_should_apply_address_filter_only_for_individual_variations():
    address = "1918 NW 53 ST"

    assert not should_apply_address_filter_for_name_search(
        "MIAMI EDGE INVESTMENTS INC",
        property_address=address,
        is_name_variation=False,
    )
    assert not should_apply_address_filter_for_name_search(
        "CORTES RIOS JUAN C",
        property_address=address,
        is_name_variation=False,
    )
    assert should_apply_address_filter_for_name_search(
        "CORTES-RIOS JUAN C",
        property_address=address,
        is_name_variation=True,
    )
    assert not should_apply_address_filter_for_name_search(
        "CORTES-RIOS JUAN C",
        property_address="",
        is_name_variation=True,
    )
