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


def is_valid_sale_date(value: Any) -> bool:
    """Return True when value parses as a Miami-Dade assessor sale date."""
    return _parse_sale_date(value) is not None


def _entry_date(entry: dict[str, Any]) -> Optional[datetime]:
    return _parse_sale_date(entry.get("recording_date")) or _parse_sale_date(entry.get("sale_date"))


def _entries_with_book_page(assessor_record: dict[str, Any]) -> list[dict[str, Any]]:
    raw = assessor_record.get("raw_json") or {}
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add_entry(entry: dict[str, Any]) -> None:
        book_page = str(entry.get("book_page") or "").strip()
        if not book_page:
            return
        key = f"{book_page}|{entry.get('recording_date')}|{entry.get('sale_date')}"
        if key in seen:
            return
        seen.add(key)
        entries.append(entry)

    for source_list in (raw.get("chain_of_title") or [], raw.get("sales_history") or []):
        if not isinstance(source_list, list):
            continue
        for entry in source_list:
            if not isinstance(entry, dict):
                continue
            if not is_valid_sale_date(entry.get("recording_date") or entry.get("sale_date")):
                continue
            _add_entry(entry)

    sales_table = raw.get("sales_information_table") or {}
    table_rows = sales_table.get("rows") or []
    row_links = sales_table.get("row_links") or []
    headers = [str(h or "").strip().lower() for h in (sales_table.get("headers") or [])]
    book_idx = next(
        (i for i, header in enumerate(headers) if "book" in header and "page" in header),
        2,
    )
    date_idx = next(
        (i for i, header in enumerate(headers) if "sale" in header or "previous" in header),
        0,
    )
    price_idx = next((i for i, header in enumerate(headers) if "price" in header), 1)

    for idx, row in enumerate(table_rows):
        if not isinstance(row, list) or len(row) <= book_idx:
            continue
        book_page = str(row[book_idx] or "").strip()
        if not book_page:
            continue
        sale_date = row[date_idx] if len(row) > date_idx else ""
        if not is_valid_sale_date(sale_date):
            continue
        entry: dict[str, Any] = {
            "book_page": book_page,
            "recording_date": sale_date,
            "sale_date": sale_date,
            "sale_price": row[price_idx] if len(row) > price_idx else "",
            "document_type": "Sale",
            "source": "sales_information_table",
        }
        if idx < len(row_links) and isinstance(row_links[idx], list) and len(row_links[idx]) > book_idx:
            recorder_url = row_links[idx][book_idx]
            if recorder_url:
                entry["recorder_url"] = recorder_url
        _add_entry(entry)

    return entries


def _normalize_recorder_page_number(page_number: str) -> str:
    """Strip leading zeros so assessor values like 0670 match recorder book/page forms."""
    page = str(page_number or "").strip()
    if page.isdigit():
        return str(int(page))
    return page


def extract_all_book_pages(
    assessor_record: dict[str, Any],
) -> list[tuple[str, str, dict[str, Any]]]:
    """Return all unique assessor sales book/page pairs, most recent sale first."""
    entries = _entries_with_book_page(assessor_record)
    if not entries:
        return []

    dated_entries = [(entry, _entry_date(entry)) for entry in entries]
    dated_entries.sort(
        key=lambda item: item[1] or datetime.min,
        reverse=True,
    )

    results: list[tuple[str, str, dict[str, Any]]] = []
    seen: set[str] = set()
    for entry, _ in dated_entries:
        parsed = parse_book_page(query_value=str(entry.get("book_page") or ""))
        if not parsed:
            continue
        book, page = parsed
        page = _normalize_recorder_page_number(page)
        key = f"{book}/{page}"
        if key in seen:
            continue
        seen.add(key)
        results.append((book, page, entry))
    return results


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
    book, page = parsed
    return book, _normalize_recorder_page_number(page), best_entry


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
