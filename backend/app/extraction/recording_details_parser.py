import re
from typing import Any, Optional


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip(" \t\n\r:;,.")
    return cleaned or None


def _first_match(pattern: str, text: str, flags: int = re.I) -> Optional[str]:
    match = re.search(pattern, text, flags)
    if not match:
        return None
    return _clean(match.group(1))


def _all_matches(pattern: str, text: str, flags: int = re.I) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for match in re.finditer(pattern, text, flags):
        value = _clean(match.group(1))
        if value and value.lower() not in seen:
            seen.add(value.lower())
            results.append(value)
    return results


def _split_party_names(value: Optional[str]) -> list[str]:
    if not value:
        return []
    parts = re.split(r"\s*(?:;| and |\band\b)\s*", value, flags=re.I)
    names = [_clean(part) for part in parts]
    return [name for name in names if name]


def parse_recording_details(text: str, *, document_hint: Optional[str] = None) -> dict[str, Any]:
    """Extract structured recording fields from OCR markdown/text."""
    if not text or not text.strip():
        return {}

    normalized = text.replace("\r", "\n")
    lower = normalized.lower()

    book = _first_match(r"(?:Book|Bk\.?)\s*[:#]?\s*(\d{1,6})", normalized)
    page = _first_match(r"(?:Page|Pg\.?)\s*[:#]?\s*(\d{1,6})", normalized)
    book_page = _first_match(r"(?:Book|Bk\.?)\s*[:#]?\s*(\d{1,6}\s*[/,]\s*\d{1,6})", normalized)
    if not book_page and book and page:
        book_page = f"{book}/{page}"

    instrument = _first_match(
        r"(?:CFN|Clerk File Number|Instrument(?:\s*(?:No\.?|Number|#))?)\s*[:#]?\s*([A-Z0-9][A-Z0-9 \-]{3,})",
        normalized,
    )
    if not instrument:
        instrument = _first_match(r"\b(\d{4}\s*R\s*\d+)\b", normalized)

    recorded_date = _first_match(
        r"(?:Recorded(?:\s+Date)?|Date\s+Recorded|Recording\s+Date)\s*[:#]?\s*([^\n]+)",
        normalized,
    )
    if not recorded_date:
        recorded_date = _first_match(
            r"\b(\d{1,2}/\d{1,2}/\d{4}(?:\s+\d{1,2}:\d{2}:\d{2}\s*(?:AM|PM)?)?)\b",
            normalized,
        )

    executed_date = _first_match(
        r"(?:Executed(?:\s+Date)?|Dated|Document\s+Date)\s*[:#]?\s*([^\n]+)",
        normalized,
    )
    if not executed_date and "day of" in lower:
        executed_date = _first_match(
            r"((?:\d{1,2}(?:st|nd|rd|th)?\s+day\s+of\s+[A-Za-z]+,?\s+\d{4})|(?:[A-Za-z]+\s+\d{1,2},?\s+\d{4}))",
            normalized,
        )

    grantor = _first_match(
        r"(?:Grantor(?:\(s\))?|GRANTOR)\s*[:#]?\s*([^\n]+)",
        normalized,
    )
    grantee = _first_match(
        r"(?:Grantee(?:\(s\))?|GRANTEE)\s*[:#]?\s*([^\n]+)",
        normalized,
    )

    sale_price = _first_match(
        r"(?:Sales?\s*Price|Sale\s*Amount|Purchase\s*Price)\s*[:#]?\s*(\$?\s*[\d,]+(?:\.\d{2})?)",
        normalized,
    )
    consideration = _first_match(
        r"(?:Consideration|Amount)\s*[:#]?\s*(\$?\s*[\d,]+(?:\.\d{2})?)",
        normalized,
    )
    documentary_stamps = _first_match(
        r"(?:Documentary\s*Stamps?|Doc(?:umentary)?\s*Stamp(?:s)?)\s*[:#]?\s*(\$?\s*[\d,]+(?:\.\d{2})?)",
        normalized,
    )
    recording_fee = _first_match(
        r"(?:Deed\s*Doc(?:ument)?\s*Fee|Recording\s*Fee|Doc\s*Fee)\s*[:#]?\s*(\$?\s*[\d,]+(?:\.\d{2})?)",
        normalized,
    )
    parcel_id = _first_match(
        r"(?:Parcel(?:\s*I\.?D\.?)?(?:\s*\(folio\))?(?:\s*(?:No\.?|Number|#))?|Folio(?:\s*(?:No\.?|Number|#))?)\s*[:#]?\s*([\d\-]+)",
        normalized,
    )
    order_number = _first_match(r"(?:Order\s*(?:No\.?|Number|#))\s*[:#]?\s*([A-Z0-9\-]+)", normalized)
    prepared_by = _first_match(
        r"(?:Prepared\s+By|Return\s+To|Prepared\s+For)\s*[:#]?\s*([^\n]+)",
        normalized,
    )

    legal_description = _first_match(
        r"(?:Legal\s+Description|Property\s+Description|Description)\s*[:#]?\s*([^\n]+(?:\n(?![A-Z][A-Za-z ]{2,20}:)[^\n]+)*)",
        normalized,
        re.I,
    )
    if not legal_description:
        legal_description = _first_match(
            r"((?:Lot\s+\d+.*?)(?:Miami-Dade County,?\s*Florida|Public Records)[^\n]*)",
            normalized,
            re.I | re.S,
        )

    property_address = _first_match(
        r"(?:Property\s+Address|Situs|Street\s+Address)\s*[:#]?\s*([^\n]+)",
        normalized,
    )

    document_type = document_hint
    if not document_type:
        for candidate in (
            "Corporate Warranty Deed",
            "Warranty Deed",
            "Quit Claim Deed",
            "Mortgage",
            "Deed of Trust",
            "Satisfaction of Mortgage",
            "Release",
            "Lien",
            "Easement",
        ):
            if candidate.lower() in lower:
                document_type = candidate
                break
        if not document_type and "deed" in lower:
            document_type = "Deed"

    grantors = _split_party_names(grantor)
    grantees = _split_party_names(grantee)

    details: dict[str, Any] = {
        "document_type": document_type,
        "recorded_date": recorded_date,
        "executed_date": executed_date,
        "book": book,
        "page": page,
        "book_page": book_page,
        "instrument_number": instrument,
        "clerk_file_number": instrument,
        "grantor": grantor,
        "grantee": grantee,
        "grantors": grantors,
        "grantees": grantees,
        "consideration": consideration or sale_price,
        "sale_price": sale_price,
        "documentary_stamps": documentary_stamps,
        "recording_fee": recording_fee,
        "deed_doc_fee": recording_fee,
        "parcel_id": parcel_id,
        "folio_number": parcel_id,
        "order_number": order_number,
        "prepared_by": prepared_by,
        "legal_description": legal_description,
        "property_address": property_address,
    }
    return {key: value for key, value in details.items() if value not in (None, "", [])}


def build_recording_details_from_document(
    doc: dict[str, Any],
    ocr: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build recording details from persisted recorder metadata when OCR is unavailable."""
    ocr = ocr or doc.get("ocr_json") or {}
    book_number = str(ocr.get("book_number") or "").strip()
    page_number = str(ocr.get("page_number") or "").strip()
    book_page = doc.get("book_page") or ocr.get("book_page")
    if not book_page and book_number and page_number:
        book_page = f"{book_number}/{page_number}"

    grantor = doc.get("grantor") or ocr.get("grantor")
    grantee = doc.get("grantee") or ocr.get("grantee")
    instrument = (
        doc.get("instrument_number")
        or ocr.get("clerk_file_number")
        or ocr.get("instrument_number")
    )

    details: dict[str, Any] = {
        "document_type": doc.get("document_type") or ocr.get("document_type"),
        "recorded_date": doc.get("recording_date") or ocr.get("recording_date"),
        "book": book_number or None,
        "page": page_number or None,
        "book_page": book_page,
        "instrument_number": instrument,
        "clerk_file_number": instrument,
        "grantor": grantor,
        "grantee": grantee,
        "grantors": _split_party_names(grantor),
        "grantees": _split_party_names(grantee),
        "legal_description": ocr.get("legal_description"),
        "property_address": ocr.get("property_address"),
        "source": "metadata_fallback",
    }
    return {key: value for key, value in details.items() if value not in (None, "", [])}
