from pathlib import Path

from app.report.report_builder import (
    _extract_gis_screenshot_path,
    _find_gis_screenshot_file,
    _resolve_gis_screenshot,
)


def test_extract_gis_screenshot_path_from_events_and_documents():
    events = [
        {
            "event_type": "source_completed",
            "source": "gis",
            "payload": {"screenshot_path": "screenshots/gis_map_30-4009-094-0070.png"},
        },
        {
            "event_type": "node_completed",
            "payload": {
                "node": "GISNode",
                "screenshot_path": "screenshots/gis_map_30-4009-094-0070.png",
            },
        },
    ]
    documents = [
        {
            "document_type": "gis_map",
            "screenshot_path": "screenshots/gis_map_doc.png",
            "ocr_json": {"source": "gis", "image_path": "screenshots/gis_map_doc.png"},
        }
    ]

    assert _extract_gis_screenshot_path(events, []) == "screenshots/gis_map_30-4009-094-0070.png"
    assert _extract_gis_screenshot_path([], documents) == "screenshots/gis_map_doc.png"


def test_find_gis_screenshot_file_by_folio(tmp_path, monkeypatch):
    screenshots_dir = tmp_path / "screenshots"
    screenshots_dir.mkdir()
    png = screenshots_dir / "gis_map_30-4009-094-0070.png"
    png.write_bytes(b"fake-png")

    monkeypatch.chdir(tmp_path)
    found = _find_gis_screenshot_file(None, "30-4009-094-0070")
    assert found == png.resolve()


def test_resolve_gis_screenshot_returns_public_url(tmp_path, monkeypatch):
    screenshots_dir = tmp_path / "screenshots"
    screenshots_dir.mkdir()
    png = screenshots_dir / "gis_map_30-4009-094-0070.png"
    png.write_bytes(b"fake-png")

    monkeypatch.chdir(tmp_path)
    events = [
        {
            "event_type": "source_completed",
            "source": "gis",
            "payload": {"screenshot_path": str(png)},
        }
    ]

    path, data_uri, public_url = _resolve_gis_screenshot(events, [], None, "30-4009-094-0070")
    assert path == str(png.resolve())
    assert data_uri and data_uri.startswith("data:image/png;base64,")
    assert public_url == "/screenshots/gis_map_30-4009-094-0070.png"
