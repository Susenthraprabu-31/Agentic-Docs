"""Run-level record/document deduplication for canvas workflows."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.db.repositories.documents_repository import DocumentsRepository
    from app.db.repositories.records_repository import RecordsRepository

_SOURCE_PRIORITY = {"assessor": 0, "tax_record": 1}


def _record_key(rec: dict) -> str | None:
    apn = rec.get("apn")
    if apn:
        return str(apn).strip().upper()
    source = rec.get("source") or "unknown"
    return f"__no_apn__:{source}:{id(rec)}"


def _document_key(doc: dict) -> str:
    instrument = doc.get("instrument_number")
    if instrument:
        return f"inst:{str(instrument).strip().upper()}"
    book_page = doc.get("book_page")
    if book_page:
        return f"bp:{str(book_page).strip().upper()}"
    return f"__doc__:{id(doc)}"


def deduplicate_records(records: list[dict]) -> list[dict]:
    """Keep one record per APN; prefer assessor over tax_record."""
    by_key: dict[str, dict] = {}
    for rec in records:
        key = _record_key(rec)
        if key is None:
            continue
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = rec
            continue
        existing_prio = _SOURCE_PRIORITY.get(existing.get("source", ""), 99)
        new_prio = _SOURCE_PRIORITY.get(rec.get("source", ""), 99)
        if new_prio < existing_prio:
            by_key[key] = rec
    return list(by_key.values())


def deduplicate_documents(documents: list[dict]) -> list[dict]:
    """Keep one document per instrument_number or book_page."""
    by_key: dict[str, dict] = {}
    for doc in documents:
        by_key[_document_key(doc)] = doc
    return list(by_key.values())


def _ids_to_remove(original: list[dict[str, Any]], kept: list[dict[str, Any]]) -> list[str]:
    kept_ids = {item["id"] for item in kept if item.get("id")}
    return [item["id"] for item in original if item.get("id") and item["id"] not in kept_ids]


def normalize_run_data(
    run_id: str,
    records_repo: "RecordsRepository",
    documents_repo: "DocumentsRepository",
) -> dict[str, int]:
    """Deduplicate persisted run records/documents and remove duplicate rows."""
    records = records_repo.list_by_run(run_id)
    documents = documents_repo.list_by_run(run_id)

    before_records = len(records)
    before_docs = len(documents)

    kept_records = deduplicate_records(records)
    kept_documents = deduplicate_documents(documents)

    record_ids = _ids_to_remove(records, kept_records)
    document_ids = _ids_to_remove(documents, kept_documents)

    records_removed = records_repo.delete_by_ids(run_id, record_ids)
    documents_removed = documents_repo.delete_by_ids(run_id, document_ids)

    return {
        "records_before": before_records,
        "records_after": before_records - records_removed,
        "documents_before": before_docs,
        "documents_after": before_docs - documents_removed,
        "records_removed": records_removed,
        "documents_removed": documents_removed,
    }
