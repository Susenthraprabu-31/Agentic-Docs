"""Extract book/page from assessor sales information for recorder handoff."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.extraction.book_page import parse_book_page

_DATE_FORMATS = (
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y-%m-%d",
    "%m-%d-%Y",
)


def _parse_sale_date(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _entry_date(entry: dict[str, Any]) -> Optional[datetime]:
    return _parse_sale_date(entry.get("recording_date")) or _parse_sale_date(entry.get("sale_date"))


def _entries_with_book_page(assessor_record: dict[str, Any]) -> list[dict[str, Any]]:
    raw = assessor_record.get("raw_json") or {}
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    for source_list in (raw.get("chain_of_title") or [], raw.get("sales_history") or []):
        if not isinstance(source_list, list):
            continue
        for entry in source_list:
            if not isinstance(entry, dict):
                continue
            book_page = str(entry.get("book_page") or "").strip()
            if not book_page:
                continue
            key = f"{book_page}|{entry.get('recording_date')}|{entry.get('sale_date')}"
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)

    return entries


def extract_latest_book_page(
    assessor_record: dict[str, Any],
) -> Optional[tuple[str, str, dict[str, Any]]]:
    """Return book, page, and source entry for the most recent assessor sale."""
    entries = _entries_with_book_page(assessor_record)
    if not entries:
        return None

    dated_entries = [(entry, _entry_date(entry)) for entry in entries]
    dated = [(entry, dt) for entry, dt in dated_entries if dt is not None]
    best_entry = max(dated, key=lambda item: item[1])[0] if dated else entries[0]

    parsed = parse_book_page(query_value=str(best_entry.get("book_page") or ""))
    if not parsed:
        return None
    return parsed[0], parsed[1], best_entry


def enrich_raw_json_with_latest_book_page(raw_json: dict[str, Any]) -> dict[str, Any]:
    """Attach latest_book_page metadata for debugging and downstream visibility."""
    if not raw_json:
        return raw_json

    result = extract_latest_book_page({"raw_json": raw_json})
    if not result:
        return raw_json

    book, page, entry = result
    enriched = dict(raw_json)
    enriched["latest_book_page"] = {
        "book": book,
        "page": page,
        "source": "sales_information",
        "recording_date": entry.get("recording_date") or entry.get("sale_date"),
        "document_type": entry.get("document_type") or entry.get("deed_type"),
    }
    return enriched
