import html
import io
import re
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.db.repositories.documents_repository import DocumentsRepository
from app.db.repositories.records_repository import RecordsRepository
from app.report.pdf_exporter import PdfExporter, is_valid_pdf
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


def _resolve_existing_path(path: str | Path | None) -> Path | None:
    if not path:
        return None
    try:
        p = Path(path).resolve()
    except Exception:
        return None
    if p.is_file() and p.stat().st_size > 0:
        return p
    return None


def _resolve_pdf_path(path: str | Path | None) -> Path | None:
    p = _resolve_existing_path(path)
    if p and is_valid_pdf(p):
        return p
    return None


def _resolve_recorder_pdf(doc: dict) -> Path | None:
    ocr = doc.get("ocr_json") or {}
    folder_name = ocr.get("folder_name")
    pdf_file = ocr.get("pdf_file")
    screenshot = doc.get("screenshot_path")
    candidates: list[str | Path] = [
        ocr.get("download_path"),
        ocr.get("pdf_path"),
    ]
    if screenshot and str(screenshot).lower().endswith(".pdf"):
        candidates.append(screenshot)
    if folder_name:
        names = {pdf_file, f"{folder_name}.pdf", f"recorder_{folder_name.removeprefix('recorder_')}.pdf"}
        names.discard(None)
        for name in names:
            candidates.extend([
                Path("local_storage") / folder_name / name,
                Path("downloads") / folder_name / name,
                Path("screenshots") / folder_name / name,
                Path("screenshots") / name,
            ])
    for candidate in candidates:
        resolved = _resolve_pdf_path(candidate)
        if resolved:
            return resolved
    return None


def _recorder_doc_label(doc: dict) -> str:
    ocr = doc.get("ocr_json") or {}
    parts = [
        doc.get("document_type"),
        doc.get("book_page"),
        doc.get("instrument_number"),
        ocr.get("folder_name"),
    ]
    label = " - ".join(str(p) for p in parts if p)
    return label or "recorder_document"


def _media_type_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext == ".png":
        return "image/png"
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    return "application/octet-stream"


def _build_tax_official_html(tax_record: dict) -> str:
    raw = tax_record.get("raw_json") or {}
    account = html.escape(str(raw.get("account_number") or raw.get("fields", {}).get("property tax account") or ""))
    owner = html.escape(str(raw.get("owner") or raw.get("fields", {}).get("owner name") or ""))
    situs = html.escape(str(raw.get("situs") or raw.get("fields", {}).get("property address") or ""))
    amount_due = html.escape(str(raw.get("amount_due") or raw.get("fields", {}).get("amount due") or ""))
    status = html.escape(str(raw.get("amount_due_message") or raw.get("fields", {}).get("status") or ""))

    sections: list[str] = [
        "<h1>Official Tax Bill Records</h1>",
        "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%'>",
        f"<tr><th>Account</th><td>{account}</td></tr>",
        f"<tr><th>Owner</th><td>{owner}</td></tr>",
        f"<tr><th>Property Address</th><td>{situs}</td></tr>",
        f"<tr><th>Amount Due</th><td>{amount_due}</td></tr>",
        f"<tr><th>Status</th><td>{status}</td></tr>",
        "</table>",
    ]

    history = raw.get("account_history") or []
    if history:
        sections.append("<h2>Account History</h2><table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%'>")
        for row in history:
            if isinstance(row, dict):
                cells = "".join(f"<td>{html.escape(str(v))}</td>" for v in row.values())
            else:
                cells = f"<td>{html.escape(str(row))}</td>"
            sections.append(f"<tr>{cells}</tr>")
        sections.append("</table>")

    for bill in raw.get("last_two_bills") or []:
        bill_name = html.escape(
            str((bill.get("bill_summary") or {}).get("bill") or bill.get("bill_title") or "Annual Bill")
        )
        sections.append(f"<h2>{bill_name}</h2>")
        summary = bill.get("bill_summary") or {}
        if summary:
            sections.append("<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%'>")
            for key, value in summary.items():
                sections.append(
                    f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
                )
            sections.append("</table>")

        for table_key in ("ad_valorem_taxes", "non_ad_valorem_assessments"):
            table = bill.get(table_key) or {}
            rows = table.get("rows") or []
            headers = table.get("headers") or []
            if not rows:
                continue
            title = "Ad Valorem Taxes" if table_key == "ad_valorem_taxes" else "Non-Ad Valorem Assessments"
            sections.append(f"<h3>{title}</h3>")
            sections.append("<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%'>")
            if headers:
                sections.append("<tr>" + "".join(f"<th>{html.escape(str(h))}</th>" for h in headers) + "</tr>")
            for row in rows:
                if isinstance(row, list):
                    sections.append("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>")
                elif isinstance(row, dict):
                    sections.append("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in row.values()) + "</tr>")
            sections.append("</table>")

        if bill.get("legal_description"):
            sections.append(f"<p><strong>Legal Description:</strong> {html.escape(str(bill['legal_description']))}</p>")

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>body{font-family:Arial,sans-serif;margin:24px;color:#111}"
        "h1,h2,h3{margin-top:1.2em}table{margin:12px 0}</style></head><body>"
        + "".join(sections)
        + "</body></html>"
    )


async def _ensure_tax_official_pdf(run_id: str) -> Path | None:
    records_repo = RecordsRepository()
    tax_record = next(
        (r for r in records_repo.list_by_run(run_id) if r.get("source") == "tax_record"),
        None,
    )
    if not tax_record:
        return None

    raw = tax_record.get("raw_json") or {}
    if not raw.get("last_two_bills") and not raw.get("account_history") and not raw.get("account_number"):
        return None

    out_dir = Path("screenshots") / "tax_bills" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = out_dir / "tax_official_documents.pdf"
    if out_pdf.exists() and out_pdf.stat().st_size > 0:
        return out_pdf

    exporter = PdfExporter(output_dir=out_dir)
    await exporter.html_to_pdf(_build_tax_official_html(tax_record), "tax_official_documents.pdf")
    return out_pdf if out_pdf.exists() and out_pdf.stat().st_size > 0 else None


def _collect_official_document_paths(run_id: str) -> list[tuple[str, str, Path]]:
    """Gather recorder + tax official PDFs for this run.

    Returns tuples of (category, label, path) where category is ``recorder`` or ``tax``.
    """
    docs_repo = DocumentsRepository()
    records_repo = RecordsRepository()
    tax_results: list[tuple[str, str, Path]] = []
    recorder_results: list[tuple[str, str, Path]] = []
    seen: set[str] = set()

    def add(category: str, bucket: list[tuple[str, str, Path]], label: str, path: Path | None) -> None:
        if not path:
            return
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        bucket.append((category, label, path))

    for doc in docs_repo.list_by_run(run_id):
        if doc.get("run_id") not in (None, run_id):
            continue
        doc_type = (doc.get("document_type") or "").lower()
        ocr = doc.get("ocr_json") or {}
        if doc_type == "tax_bill":
            label = ocr.get("bill") or "tax_bill"
            add("tax", tax_results, label, _resolve_pdf_path(ocr.get("download_path")))
            continue
        if ocr.get("source") == "assessor_sales":
            continue
        label = _recorder_doc_label(doc)
        add("recorder", recorder_results, label, _resolve_recorder_pdf(doc))

    tax_record = next(
        (r for r in records_repo.list_by_run(run_id) if r.get("source") == "tax_record"),
        None,
    )
    if tax_record:
        raw = tax_record.get("raw_json") or {}
        acct = re.sub(r"[^\w\-]+", "_", raw.get("tax_account") or raw.get("account_number") or "account").strip("_")
        for item in raw.get("downloaded_bills") or []:
            label = item.get("bill") or "tax_bill"
            add("tax", tax_results, label, _resolve_pdf_path(item.get("pdf_path")))
        for bill in raw.get("last_two_bills") or []:
            bill_name = (bill.get("bill_summary") or {}).get("bill") or bill.get("bill_title") or "tax_bill"
            add("tax", tax_results, bill_name, _resolve_pdf_path(bill.get("pdf_path")))

        for root in (Path("screenshots"), Path("local_storage"), Path("downloads")):
            for folder in (run_id, acct):
                if not folder:
                    continue
                tax_run_dir = root / "tax_bills" / folder
                if tax_run_dir.is_dir():
                    for pdf in sorted(tax_run_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
                        add("tax", tax_results, pdf.stem.replace("_", " "), _resolve_pdf_path(pdf))

    return recorder_results + tax_results


def _build_official_documents_zip(run_id: str, docs: list[tuple[str, str, Path]]) -> io.BytesIO:
    zip_buffer = io.BytesIO()
    used_names: set[str] = set()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for category, label, path in docs:
            safe_label = re.sub(r"[^\w\-.]+", "_", label).strip("_") or "document"
            arcname = f"{category}/{safe_label}{path.suffix}"
            if arcname in used_names:
                stem = Path(arcname).stem
                suffix = Path(arcname).suffix
                idx = 2
                while arcname in used_names:
                    arcname = f"{category}/{stem}_{idx}{suffix}"
                    idx += 1
            used_names.add(arcname)
            zf.write(path, arcname=arcname)
    zip_buffer.seek(0)
    return zip_buffer


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
async def download_run_document(run_id: str):
    """Download official recorder + tax PDFs for a run as a ZIP archive."""
    docs = _collect_official_document_paths(run_id)
    if not docs:
        generated = await _ensure_tax_official_pdf(run_id)
        if generated and is_valid_pdf(generated):
            docs = [("tax", "Tax Bills", generated)]
    if not docs:
        raise HTTPException(
            status_code=404,
            detail=(
                "Official documents not found for this run. "
                "Ensure the Recorder and Tax nodes finished and saved PDFs, then try again."
            ),
        )

    zip_buffer = _build_official_documents_zip(run_id, docs)
    filename = f"official_documents_{run_id[:8]}.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
        p = _resolve_existing_path(cp)
        if p:
            media_type = "application/pdf" if p.suffix.lower() == ".pdf" else "image/png"
            return FileResponse(path=str(p), media_type=media_type, filename=p.name)

    raise HTTPException(status_code=404, detail="Document file not found on local disk")
