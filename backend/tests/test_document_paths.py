import json
from pathlib import Path

from app.storage.document_paths import resolve_document_preview_path, resolve_document_preview_url


def test_resolve_document_preview_path_from_metadata(tmp_path, monkeypatch):
    folder = tmp_path / "local_storage" / "recorder_31687_1679_2019_R_711430"
    folder.mkdir(parents=True)
    png_path = folder / "recorder_31687_1679_2019_R_711430.png"
    png_path.write_bytes(b"fakepng")
    (folder / "metadata.json").write_text(
        json.dumps({"png_path": str(png_path)}),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    doc = {
        "ocr_json": {
            "folder_name": "recorder_31687_1679_2019_R_711430",
            "image_path": "local_storage/recorder_31687_1679/recorder_31687_1679.png",
        }
    }
    resolved = resolve_document_preview_path(doc)
    assert resolved == png_path.resolve()


def test_resolve_document_preview_url_prefers_supabase():
    doc = {
        "ocr_json": {
            "preview_storage_url": "https://example.supabase.co/storage/v1/object/public/docs/preview.png"
        }
    }
    assert resolve_document_preview_url(doc) == doc["ocr_json"]["preview_storage_url"]


def test_resolve_document_preview_path_skips_assessor():
    doc = {"ocr_json": {"source": "assessor", "folder_name": "assessor/123"}}
    assert resolve_document_preview_path(doc) is None
