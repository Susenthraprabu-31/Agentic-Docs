from app.db.repositories.documents_repository import DocumentsRepository
from app.db.repositories.records_repository import RecordsRepository
from app.db.supabase_client import get_memory_store
from app.pipeline.run_normalizer import (
    deduplicate_documents,
    deduplicate_records,
    normalize_run_data,
)


def test_deduplicate_records_prefers_assessor():
    records = [
        {"id": "1", "source": "tax_record", "apn": "123", "owner_name": "Tax Owner"},
        {"id": "2", "source": "assessor", "apn": "123", "owner_name": "Assessor Owner"},
    ]
    result = deduplicate_records(records)
    assert len(result) == 1
    assert result[0]["owner_name"] == "Assessor Owner"


def test_deduplicate_documents_by_instrument():
    docs = [
        {"id": "1", "instrument_number": "ABC123", "grantor": "A"},
        {"id": "2", "instrument_number": "ABC123", "grantor": "B"},
        {"id": "3", "book_page": "1/2", "grantor": "C"},
    ]
    result = deduplicate_documents(docs)
    assert len(result) == 2


def test_normalize_run_data_removes_duplicate_rows():
    run_id = "normalize-run-test"
    mem = get_memory_store()
    mem.records.clear()
    mem.documents.clear()

    records_repo = RecordsRepository()
    documents_repo = DocumentsRepository()

    records_repo.insert(run_id, {"source": "tax_record", "apn": "123", "owner_name": "Tax Owner"})
    records_repo.insert(run_id, {"source": "assessor", "apn": "123", "owner_name": "Assessor Owner"})
    records_repo.insert(run_id, {"source": "assessor", "apn": "456", "owner_name": "Other Owner"})
    documents_repo.insert(run_id, {"instrument_number": "ABC123", "grantor": "A"})
    documents_repo.insert(run_id, {"instrument_number": "ABC123", "grantor": "B"})
    documents_repo.insert(run_id, {"document_type": "gis_map", "screenshot_path": "screenshots/gis_map.png"})

    stats = normalize_run_data(run_id, records_repo, documents_repo)

    assert stats["records_before"] == 3
    assert stats["records_after"] == 2
    assert stats["records_removed"] == 1
    assert stats["documents_before"] == 3
    assert stats["documents_after"] == 2
    assert stats["documents_removed"] == 1

    remaining_records = records_repo.list_by_run(run_id)
    remaining_documents = documents_repo.list_by_run(run_id)
    assert len(remaining_records) == 2
    assert any(r["owner_name"] == "Assessor Owner" for r in remaining_records)
    assert len(remaining_documents) == 2
    assert any(d.get("document_type") == "gis_map" for d in remaining_documents)
