from app.db.report_storage import enrich_report_storage, merge_storage_into_report_json


def test_merge_storage_into_report_json():
    merged = merge_storage_into_report_json({"foo": "bar"}, "reports/a.pdf", "https://example/a.pdf")
    assert merged["foo"] == "bar"
    assert merged["storage_path"] == "reports/a.pdf"
    assert merged["storage_url"] == "https://example/a.pdf"


def test_enrich_report_storage_from_report_json():
    report = {
        "id": "1",
        "run_id": "run-1",
        "report_json": {
            "storage_path": "reports/property_report_run-1.pdf",
            "storage_url": "https://example/property_report_run-1.pdf",
        },
    }
    enriched = enrich_report_storage(report)
    assert enriched["storage_path"] == "reports/property_report_run-1.pdf"
    assert enriched["storage_url"] == "https://example/property_report_run-1.pdf"
