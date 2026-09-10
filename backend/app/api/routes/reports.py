from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.report.pdf_exporter import is_valid_pdf
from app.report.report_builder import ReportBuilder

router = APIRouter(prefix="/reports", tags=["reports"])


def _report_payload(report: dict) -> dict:
    return {
        "id": report["id"],
        "run_id": report["run_id"],
        "report_json": report.get("report_json", {}),
        "pdf_path": report.get("pdf_path"),
        "storage_path": report.get("storage_path"),
        "storage_url": report.get("storage_url"),
        "created_at": report.get("created_at"),
    }


@router.get("/by-run/{run_id}")
async def get_report_by_run(run_id: str) -> dict:
    builder = ReportBuilder()
    report = builder.get_report_by_run(run_id)
    if not report:
        try:
            report = await builder.build_and_save(run_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Report not available: {exc}") from exc
    return _report_payload(report)


@router.get("/{report_id}")
async def get_report(report_id: str) -> dict:
    builder = ReportBuilder()
    report = builder.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return _report_payload(report)


@router.get("/{report_id}/download")
async def download_report(report_id: str) -> FileResponse:
    builder = ReportBuilder()
    report = builder.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    try:
        report = await builder.ensure_pdf(report)
        report = builder.upload_pdf_to_storage(report)
        pdf_path = report.get("pdf_path")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {exc}") from exc

    if not pdf_path or not is_valid_pdf(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file not found")

    response = FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"property_report_{report['run_id']}.pdf",
    )
    if report.get("storage_url"):
        response.headers["X-PDF-Storage-Url"] = report["storage_url"]
    if report.get("storage_path"):
        response.headers["X-PDF-Storage-Path"] = report["storage_path"]
    return response
