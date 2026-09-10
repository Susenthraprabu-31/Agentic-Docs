import re
from typing import Any, Optional

from bs4 import BeautifulSoup

from app.extraction.schemas import ParcelRecord, RecordedDocument


def _clean(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned or None


def _parse_value(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


def extract_parcel_from_html(html: str) -> ParcelRecord:
    soup = BeautifulSoup(html, "lxml")
    data: dict[str, Any] = {}

    for row in soup.select("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            key = _clean(cells[0].get_text())
            val = _clean(cells[1].get_text())
            if key and val:
                data[key.lower()] = val

    # qPublic Schneider widget labels (Honolulu detail pages)
    for label in soup.select(".widgetLabel, th.widgetLabel, span.widgetLabel, .field-label"):
        key = _clean(label.get_text())
        if not key:
            continue
        val_el = (
            label.find_next(class_="widgetValue")
            or label.find_next(class_="value")
            or label.find_next(["span", "td", "div"])
        )
        if val_el and val_el is not label:
            val = _clean(val_el.get("value") or val_el.get_text())
            if val and val.lower() != key.lower():
                data[key.lower()] = val

    for row in soup.select("div.row, .form-group, .property-item"):
        label_el = row.select_one(".widgetLabel, label, strong, b")
        value_el = row.select_one(".widgetValue, .value, span:last-child, td:last-child")
        if label_el and value_el:
            key = _clean(label_el.get_text())
            val = _clean(value_el.get_text())
            if key and val:
                data[key.lower()] = val

    for label in soup.select("label, .field-label, span.label"):
        key = _clean(label.get_text())
        if not key:
            continue
        sibling = label.find_next(["span", "td", "div", "input"])
        if sibling:
            val = _clean(sibling.get("value") or sibling.get_text())
            if val:
                data[key.lower()] = val

    # qPublic / Schneider Corp and standard assessor field names
    apn = (
        data.get("apn")
        or data.get("parcel")
        or data.get("parcel number")
        or data.get("parcel #")
        or data.get("parcel id")
        or data.get("pin")
        or data.get("tax id")
        or data.get("tmk")
        or data.get("tmk (tax map key)")
    )
    owner = (
        data.get("owner")
        or data.get("owner name")
        or data.get("owner(s)")
        or data.get("owner names")
        or data.get("owner names(s)")
    )
    legal = (
        data.get("legal")
        or data.get("legal description")
        or data.get("description")
        or data.get("project name")
    )
    address = (
        data.get("address")
        or data.get("property address")
        or data.get("situs address")
        or data.get("location")
        or data.get("location address")
        or data.get("situs")
    )
    value_text = (
        data.get("assessed value")
        or data.get("total property assessed value")
        or data.get("total net taxable value")
        or data.get("total value")
        or data.get("market value")
        or data.get("value")
    )

    # qPublic label:value pairs in page text
    for span in soup.select("span, div, td, th"):
        label = _clean(span.get_text())
        if not label or ":" not in label:
            continue
        parts = label.split(":", 1)
        if len(parts) != 2:
            continue
        key, val = parts[0].strip().lower(), parts[1].strip()
        if key and val and key not in data:
            data[key] = val

    if not apn:
        apn = data.get("parcel number") or data.get("parcel id")
    if not owner:
        owner = data.get("owner names") or data.get("owner name(s)")
    if not address:
        address = data.get("location address") or data.get("physical address")
    if not apn:
        apn = data.get("tmk") or data.get("parcel id (tmk)")
    if not value_text:
        value_text = data.get("total property assessed value") or data.get("total net taxable value")

    return ParcelRecord(
        apn=apn,
        owner_name=owner,
        legal_desc=legal,
        assessed_value=_parse_value(value_text),
        property_address=address,
        source="assessor",
        raw_json=data,
    )


def extract_documents_from_html(html: str) -> list[RecordedDocument]:
    soup = BeautifulSoup(html, "lxml")
    documents: list[RecordedDocument] = []

    tables = soup.select("table")
    for table in tables:
        headers = [_clean(th.get_text()) for th in table.select("th")]
        if not headers or not any(headers):
            first_row = table.select("tr")[0] if table.select("tr") else None
            if first_row:
                headers = [_clean(td.get_text()) for td in first_row.select("td")]

        for row in table.select("tr")[1:]:
            cells = [_clean(td.get_text()) for td in row.select("td")]
            if len(cells) < 2:
                continue

            row_data = {}
            for i, cell in enumerate(cells):
                if i < len(headers) and headers[i]:
                    row_data[headers[i].lower()] = cell

            doc = RecordedDocument(
                document_type=row_data.get("type") or row_data.get("document type") or row_data.get("doc type"),
                book_page=row_data.get("book/page") or row_data.get("book page") or row_data.get("book"),
                instrument_number=row_data.get("instrument") or row_data.get("instrument #") or row_data.get("doc #"),
                grantor=row_data.get("grantor"),
                grantee=row_data.get("grantee"),
            )
            if any([doc.document_type, doc.book_page, doc.instrument_number, doc.grantor]):
                documents.append(doc)

    return documents
