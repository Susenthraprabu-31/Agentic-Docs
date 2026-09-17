"""Parse and format recorder book/page search values."""
from __future__ import annotations

import re
from typing import Optional

BOOK_PAGE_SPLIT_RE = re.compile(r"^\s*(\d+)\s*[/\-]\s*(\d+)\s*$")


def parse_book_page(
    query_value: str = "",
    book_number: Optional[str] = None,
    page_number: Optional[str] = None,
) -> Optional[tuple[str, str]]:
    book = (book_number or "").strip()
    page = (page_number or "").strip()
    if book and page:
        return book, page

    value = (query_value or "").strip()
    if not value:
        return None

    match = BOOK_PAGE_SPLIT_RE.match(value)
    if match:
        return match.group(1), match.group(2)
    return None


def format_book_page(book_number: str, page_number: str) -> str:
    return f"{book_number.strip()}/{page_number.strip()}"


def format_book_page_label(book_number: str, page_number: str) -> str:
    return f"{book_number.strip()} / {page_number.strip()}"
