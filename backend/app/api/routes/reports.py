from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.db.repositories.documents_repository import DocumentsRepository
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


@router.get("/run/{run_id}/document/download")
async def download_run_document(run_id: str) -> FileResponse:
    """Download the official recorded document PDF or snapshot for a given run."""
    docs_repo = DocumentsRepository()
    docs = docs_repo.list_by_run(run_id)

    # 1. Search document metadata paths
    for doc in docs:
        ocr = doc.get("ocr_json") or {}
        candidate_paths = [
            ocr.get("download_path"),
            doc.get("screenshot_path"),
            ocr.get("image_path"),
        ]
        folder_name = ocr.get("folder_name")
        if folder_name:
            candidate_paths.extend([
                Path("local_storage") / folder_name / f"{folder_name}.pdf",
                Path("downloads") / folder_name / f"{folder_name}.pdf",
                Path("screenshots") / folder_name / f"{folder_name}.pdf",
                Path("local_storage") / folder_name / f"{folder_name}.png",
            ])

        for cp in candidate_paths:
            if cp:
                p = Path(cp).resolve()
                if p.is_file() and p.stat().st_size > 0:
                    media_type = "application/pdf" if p.suffix.lower() == ".pdf" else "image/png"
                    return FileResponse(path=str(p), media_type=media_type, filename=p.name)

    # 2. Search local_storage / downloads / screenshots folders for any matching recorder PDF
    for root_dir in (Path("local_storage"), Path("downloads"), Path("screenshots")):
        if root_dir.exists():
            for pdf in root_dir.rglob("recorder_*.pdf"):
                if pdf.is_file() and pdf.stat().st_size > 0:
                    return FileResponse(path=str(pdf), media_type="application/pdf", filename=pdf.name)

    raise HTTPException(status_code=404, detail="Official recorded document not found for this run")


@router.get("/documents/{doc_id}/download")
async def download_document_by_id(doc_id: str) -> FileResponse:
    """Download a recorded document directly by document ID."""
    from app.db.supabase_client import get_memory_store, get_supabase
    mem = get_memory_store()
    doc = next((d for d in mem.documents if d.get("id") == doc_id), None)
    if not doc:
        client = get_supabase()
        if client:
            res = client.table("documents").select("*").eq("id", doc_id).execute()
            if res and res.data:
                doc = res.data[0]

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    ocr = doc.get("ocr_json") or {}
    candidates = [
        ocr.get("download_path"),
        doc.get("screenshot_path"),
        ocr.get("image_path"),
    ]
    folder_name = ocr.get("folder_name")
    if folder_name:
        candidates.extend([
            Path("local_storage") / folder_name / f"{folder_name}.pdf",
            Path("downloads") / folder_name / f"{folder_name}.pdf",
            Path("screenshots") / folder_name / f"{folder_name}.pdf",
        ])

    for cp in candidates:
        if cp:
            p = Path(cp).resolve()
            if p.is_file() and p.stat().st_size > 0:
                media_type = "application/pdf" if p.suffix.lower() == ".pdf" else "image/png"
                return FileResponse(path=str(p), media_type=media_type, filename=p.name)

    raise HTTPException(status_code=404, detail="Document file not found on local disk")