from app.extraction.document_ocr import is_rate_limit_error
from app.extraction.recording_details_parser import build_recording_details_from_document


def test_is_rate_limit_error():
    assert is_rate_limit_error('API error occurred: Status 429. Body: {"type":"rate_limited"}')
    assert not is_rate_limit_error("File not found")


def test_build_recording_details_from_document():
    doc = {
        "document_type": "DEED - DEE",
        "book_page": "14164/373",
        "instrument_number": "1989 R 231562",
        "grantor": "TERRA TITLE CORPORATION",
        "grantee": "MARTHA BUSTILLO",
        "recording_date": "1989-06-15",
        "ocr_json": {
            "legal_description": "LOT 5 BLOCK 2",
            "book_number": "14164",
            "page_number": "373",
        },
    }
    details = build_recording_details_from_document(doc)
    assert details["book_page"] == "14164/373"
    assert details["grantor"] == "TERRA TITLE CORPORATION"
    assert details["legal_description"] == "LOT 5 BLOCK 2"
