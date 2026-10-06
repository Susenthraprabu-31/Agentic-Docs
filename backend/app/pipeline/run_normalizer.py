"""Run-level record/document deduplication for canvas workflows."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.db.repositories.documents_repository import DocumentsRepository
    from app.db.repositories.records_repository import RecordsRepository

_SOURCE_PRIORITY = {"assessor": 0, "tax_record": 1}


def _record_key(rec: dict) -> str | None:
    source = rec.get("source") or "unknown"
    apn = rec.get("apn")
    if apn:
        # Assessor and tax collector records share APN but serve different report sections.
        return f"{str(apn).strip().upper()}:{source}"
    return f"__no_apn__:{source}:{id(rec)}"


def _document_key(doc: dict) -> str:
    """Build a deduplication key that keeps distinct recorder book/page entries."""
    ocr = doc.get("ocr_json") or {}
    book_page = str(doc.get("book_page") or "").strip().upper()
    book_number = str(ocr.get("book_number") or "").strip()
    page_number = str(ocr.get("page_number") or "").strip()
    if not book_page and book_number and page_number:
        book_page = f"{book_number}/{page_number}".upper()

    instrument = str(
        doc.get("instrument_number") or ocr.get("clerk_file_number") or ""
    ).strip().upper()
    folder = str(ocr.get("folder_name") or "").strip().upper()

    if book_page and instrument:
        return f"bp:{book_page}|inst:{instrument}"
    if book_page:
        return f"bp:{book_page}"
    if instrument:
        return f"inst:{instrument}"
    if folder:
        return f"folder:{folder}"
    doc_id = doc.get("id")
    if doc_id:
        return f"id:{doc_id}"
    return f"__doc__:{id(doc)}"


def deduplicate_records(records: list[dict]) -> list[dict]:
    """Keep one record per APN+source pair (assessor and tax_record may share APN)."""
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
    """Keep one document per unique book/page (and instrument when present)."""
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
