import asyncio

from app.extraction.gpt_recorder_ocr import GptRecorderOcrService


def test_gpt_recorder_ocr_disabled_returns_error():
    service = GptRecorderOcrService()
    service.settings.gpt_recorder_ocr_enabled = False

    doc = asyncio.run(service.extract_document("/tmp/missing.pdf", "DEED"))
    assert doc.ocr_json
    assert doc.ocr_json.get("gpt_analyzed") is False
    assert "disabled" in str(doc.ocr_json.get("error", "")).lower()


def test_is_recorder_viewer_document_excludes_tax_bills():
    from app.api.routes.reports import _is_recorder_viewer_document

    assert _is_recorder_viewer_document({"document_type": "tax_bill", "ocr_json": {"source": "tax_bill"}}) is False
    assert _is_recorder_viewer_document({"document_type": "DEED", "ocr_json": {"source": "recorder"}}) is True
