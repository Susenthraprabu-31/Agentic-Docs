from pathlib import Path

from app.drivers.assessor.miami_dade_assessor_reports import (
    MIAMI_DADE_REPORT_TYPES,
    _assessor_report_paths,
    _folio_storage_key,
)


def test_folio_storage_key():
    assert _folio_storage_key("30-6924-001-0030") == "3069240010030"


def test_assessor_report_paths():
    dest, filename, folder_name = _assessor_report_paths("30-6924-001-0030", "assessor_summary")
    assert dest.name == "assessor_summary_3069240010030.pdf"
    assert folder_name == "assessor/3069240010030"
    assert dest.parent.as_posix().endswith("local_storage/assessor/3069240010030")


def test_report_types_include_summary_and_detailed():
    report_types = {item[0] for item in MIAMI_DADE_REPORT_TYPES}
    assert report_types == {"summary", "detailed"}
