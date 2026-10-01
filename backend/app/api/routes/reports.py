import html
import io
import re
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from app.db.repositories.documents_repository import DocumentsRepository
from app.db.repositories.records_repository import RecordsRepository
from app.extraction.document_ocr import DocumentOcrService, is_rate_limit_error
from app.extraction.recording_details_parser import build_recording_details_from_document
from app.storage.document_asset_storage import DocumentAssetStorage
from app.storage.document_paths import resolve_document_preview_path, resolve_document_preview_url
from app.report.excel_generator import generate_chain_sheet_excel
from app.report.pdf_exporter import PdfExporter, is_valid_pdf
from app.report.report_builder import ReportBuilder

router = APIRouter(prefix="/reports", tags=["reports"])
documents_repo = DocumentsRepository()
ocr_service = DocumentOcrService()
document_storage = DocumentAssetStorage()


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
    if ocr.get("source") in ("assessor", "assessor_sales"):
        return None
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


def _resolve_assessor_pdf(doc: dict) -> Path | None:
    ocr = doc.get("ocr_json") or {}
    if ocr.get("source") not in ("assessor",):
        return None

    candidates: list[str | Path] = [
        ocr.get("download_path"),
        doc.get("screenshot_path"),
    ]
    folder_name = ocr.get("folder_name")
    file_name = ocr.get("file_name")
    if folder_name and file_name:
        candidates.extend([
            Path("local_storage") / folder_name / file_name,
            Path("downloads") / folder_name / file_name,
            Path("screenshots") / folder_name / file_name,
        ])
        if folder_name.startswith("assessor/"):
            legacy_folder = f"assessor_{folder_name.split('/', 1)[1]}"
            candidates.extend([
                Path("local_storage") / legacy_folder / file_name,
                Path("downloads") / legacy_folder / file_name,
            ])
    if folder_name:
        candidates.extend([
            Path("local_storage") / folder_name,
            Path("downloads") / folder_name,
        ])

    for candidate in candidates:
        resolved = _resolve_pdf_path(candidate)
        if resolved:
            return resolved
        candidate_path = _resolve_existing_path(candidate)
        if candidate_path and candidate_path.is_dir():
            pdfs = sorted(
                candidate_path.glob("*.pdf"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if pdfs:
                return pdfs[0]
    return None


def _fetch_document_record(doc_id: str) -> dict | None:
    from app.db.supabase_client import get_memory_store, get_supabase

    mem = get_memory_store()
    doc = next((d for d in mem.documents if d.get("id") == doc_id), None)
    if doc:
        return doc

    client = get_supabase()
    if client:
        res = client.table("documents").select("*").eq("id", doc_id).execute()
        if res and res.data:
            return res.data[0]
    return None


def _resolve_document_file(doc: dict) -> Path | None:
    ocr = doc.get("ocr_json") or {}
    source = ocr.get("source")
    if source == "assessor":
        return _resolve_assessor_pdf(doc)
    if source == "assessor_sales":
        return None

    resolved = _resolve_recorder_pdf(doc)
    if resolved:
        return resolved

    candidates: list[str | Path] = [
        ocr.get("download_path"),
        doc.get("screenshot_path"),
        ocr.get("pdf_path"),
        ocr.get("image_path"),
    ]
    folder_name = ocr.get("folder_name")
    file_name = ocr.get("file_name") or ocr.get("pdf_file")
    if folder_name and file_name:
        candidates.extend([
            Path("local_storage") / folder_name / file_name,
            Path("downloads") / folder_name / file_name,
            Path("screenshots") / folder_name / file_name,
        ])

    for candidate in candidates:
        resolved_pdf = _resolve_pdf_path(candidate)
        if resolved_pdf:
            return resolved_pdf
        existing = _resolve_existing_path(candidate)
        if existing and existing.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            return existing
    return None


def _resolve_document_preview_image(doc: dict, file_path: Path | None = None) -> Path | None:
    preview_url = resolve_document_preview_url(doc)
    if preview_url:
        return None
    return resolve_document_preview_path(doc, file_path)


def _public_storage_path(path: Path | None) -> str | None:
    if not path:
        return None
    resolved = path.resolve()
    for root_name in ("local_storage", "downloads", "screenshots"):
        root = Path(root_name).resolve()
        try:
            rel = resolved.relative_to(root)
            return f"/{root_name}/{rel.as_posix()}"
        except ValueError:
            continue
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


def _resolve_document_ocr_source(doc: dict, file_path: Path | None = None) -> Path | None:
    preview_path = _resolve_document_preview_image(doc, file_path)
    if preview_path and preview_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        return preview_path

    if file_path and file_path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
        return file_path

    ocr = doc.get("ocr_json") or {}
    for candidate in (ocr.get("image_path"), ocr.get("preview_path"), doc.get("screenshot_path")):
        existing = _resolve_existing_path(candidate)
        if existing and existing.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
            return existing
    return None


def _ocr_status_for(doc: dict) -> str:
    ocr = doc.get("ocr_json") or {}
    if ocr.get("mistral_analyzed"):
        return "ready"
    if ocr.get("ocr_fallback") and ocr.get("recording_details"):
        return "fallback"
    if ocr.get("error"):
        return "error"
    return "pending"


def _serialize_document_response(doc: dict, file_path: Path | None = None) -> dict:
    doc_id = doc.get("id")
    preview_path = _resolve_document_preview_image(doc, file_path)
    ocr = doc.get("ocr_json") or {}
    recording_details = ocr.get("recording_details") or {}
    preview_url = resolve_document_preview_url(doc) or _public_storage_path(preview_path)
    file_url = ocr.get("pdf_storage_url") or ocr.get("download_storage_url")
    if not file_url and file_path and doc_id:
        file_url = f"/reports/documents/{doc_id}/file?inline=1"

    return {
        "id": doc_id,
        "run_id": doc.get("run_id"),
        "document_type": doc.get("document_type") or recording_details.get("document_type"),
        "recording_date": doc.get("recording_date") or recording_details.get("recorded_date") or ocr.get("recording_date"),
        "book_page": doc.get("book_page") or recording_details.get("book_page") or ocr.get("book_page"),
        "instrument_number": doc.get("instrument_number")
        or recording_details.get("instrument_number")
        or recording_details.get("clerk_file_number")
        or ocr.get("clerk_file_number"),
        "grantor": doc.get("grantor") or recording_details.get("grantor"),
        "grantee": doc.get("grantee") or recording_details.get("grantee"),
        "source_url": doc.get("source_url"),
        "file_name": file_path.name if file_path else ocr.get("file_name"),
        "file_url": file_url,
        "download_url": ocr.get("pdf_storage_url") or (f"/reports/documents/{doc_id}/file" if doc_id else None),
        "preview_url": preview_url,
        "recording_details": recording_details,
        "ocr_json": ocr,
        "ocr_status": _ocr_status_for(doc),
    }


async def _analyze_document_ocr(doc: dict, *, force: bool = False) -> dict:
    ocr = doc.get("ocr_json") or {}
    if ocr.get("mistral_analyzed") and ocr.get("recording_details") and not force:
        return doc

    file_path = _resolve_document_file(doc)
    source_path = _resolve_document_ocr_source(doc, file_path)
    if not source_path:
        raise HTTPException(status_code=404, detail="No OCR source file found for this document")

    extracted = await ocr_service.extract_document(
        str(source_path),
        doc.get("document_type"),
    )
    extracted_ocr = extracted.ocr_json or {}
    error_message = str(extracted_ocr.get("error") or "")
    if error_message:
        if is_rate_limit_error(error_message):
            fallback_details = build_recording_details_from_document(doc, ocr)
            merged_ocr = {
                **ocr,
                **extracted_ocr,
                "recording_details": fallback_details,
                "ocr_fallback": True,
                "mistral_analyzed": False,
            }
            updates = {"ocr_json": merged_ocr}
            doc_id = doc.get("id")
            if not doc_id:
                raise HTTPException(status_code=500, detail="Document is missing an id")
            updated = documents_repo.update(doc_id, updates)
            result = updated or {**doc, **updates}
            file_path = _resolve_document_file(result)
            response = _serialize_document_response(result, file_path)
            response["ocr_warning"] = (
                "Mistral OCR rate limit reached. Showing recorder metadata already saved for this document. "
                "Please wait a minute and click Re-analyze."
            )
            return response

        raise HTTPException(status_code=502, detail=error_message)

    merged_ocr = {**ocr, **extracted_ocr}
    recording_details = merged_ocr.get("recording_details") or {}
    merged_ocr = document_storage.upload_and_merge(
        doc.get("run_id") or "",
        merged_ocr,
        doc.get("screenshot_path"),
    )
    updates: dict = {
        "ocr_json": merged_ocr,
    }
    if extracted.document_type:
        updates["document_type"] = extracted.document_type
    if extracted.grantor:
        updates["grantor"] = extracted.grantor
    if extracted.grantee:
        updates["grantee"] = extracted.grantee
    if extracted.book_page:
        updates["book_page"] = extracted.book_page
    if extracted.instrument_number:
        updates["instrument_number"] = extracted.instrument_number
    if recording_details.get("recorded_date") and not doc.get("recording_date"):
        updates["recording_date"] = recording_details["recorded_date"]

    doc_id = doc.get("id")
    if not doc_id:
        raise HTTPException(status_code=500, detail="Document is missing an id")

    updated = documents_repo.update(doc_id, updates)
    return updated or {**doc, **updates}


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
    """Gather recorder, assessor, and tax official PDFs for this run.

    Returns tuples of (category, label, path) where category is ``recorder``,
    ``assessor``, or ``tax``.
    """
    docs_repo = DocumentsRepository()
    records_repo = RecordsRepository()
    tax_results: list[tuple[str, str, Path]] = []
    recorder_results: list[tuple[str, str, Path]] = []
    assessor_results: list[tuple[str, str, Path]] = []
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
        if ocr.get("source") == "assessor":
            label = doc.get("document_type") or "assessor_report"
            add("assessor", assessor_results, label, _resolve_assessor_pdf(doc))
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

    return assessor_results + recorder_results + tax_results


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
    else:
        report = builder.refresh_report_json(report)
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


@router.get("/run/{run_id}/excel/download")
async def download_run_excel(run_id: str):
    """Generate and download the Chain Sheet Excel (.xlsx) spreadsheet for a run."""
    builder = ReportBuilder()
    report = builder.get_report_by_run(run_id)
    if not report:
        try:
            report = await builder.build_and_save(run_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Report not available to export Excel: {exc}") from exc
    else:
        report = builder.refresh_report_json(report)

    report_json = report.get("report_json") or {}
    from app.db.repositories.runs_repository import RunsRepository
    runs_repo = RunsRepository()
    run_dict = runs_repo.get_run(run_id) or {}

    excel_buffer = generate_chain_sheet_excel(report_json, run_dict)

    parcel = (
        (report_json.get("property") or {}).get("apn")
        or report_json.get("query_value")
        or run_dict.get("parcel")
        or run_id[:8]
    )
    safe_parcel = re.sub(r"[^\w\-]+", "_", str(parcel))
    filename = f"chain_sheet_{safe_parcel}_{run_id[:8]}.xlsx"

    return StreamingResponse(
        excel_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/{report_id}/excel/download")
async def download_report_excel(report_id: str):
    """Generate and download the Chain Sheet Excel (.xlsx) spreadsheet by report ID."""
    builder = ReportBuilder()
    report = builder.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    report = builder.refresh_report_json(report)
    run_id = report.get("run_id") or report_id

    report_json = report.get("report_json") or {}
    from app.db.repositories.runs_repository import RunsRepository
    runs_repo = RunsRepository()
    run_dict = runs_repo.get_run(run_id) or {}

    excel_buffer = generate_chain_sheet_excel(report_json, run_dict)

    parcel = (
        (report_json.get("property") or {}).get("apn")
        or report_json.get("query_value")
        or run_dict.get("parcel")
        or run_id[:8]
    )
    safe_parcel = re.sub(r"[^\w\-]+", "_", str(parcel))
    filename = f"chain_sheet_{safe_parcel}_{run_id[:8]}.xlsx"

    return StreamingResponse(
        excel_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str) -> dict:
    """Return document metadata plus resolved file and preview URLs for the viewer."""
    doc = _fetch_document_record(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    ocr = doc.get("ocr_json") or {}
    if doc.get("run_id") and not (ocr.get("pdf_storage_url") or ocr.get("png_storage_url")):
        merged_ocr = document_storage.upload_and_merge(
            doc.get("run_id"),
            ocr,
            doc.get("screenshot_path"),
        )
        if merged_ocr != ocr:
            updated = documents_repo.update(doc_id, {"ocr_json": merged_ocr})
            doc = updated or {**doc, "ocr_json": merged_ocr}
            ocr = doc.get("ocr_json") or {}

    if not ocr.get("recording_details"):
        fallback = build_recording_details_from_document(doc, ocr)
        if fallback:
            ocr = {**ocr, "recording_details": fallback, "ocr_fallback": not ocr.get("mistral_analyzed")}
            doc = {**doc, "ocr_json": ocr}

    file_path = _resolve_document_file(doc)
    return _serialize_document_response(doc, file_path)


@router.post("/documents/{doc_id}/ocr")
async def analyze_document_ocr(doc_id: str, force: bool = Query(default=False)) -> dict:
    """Run Mistral OCR on a document and persist structured recording details."""
    doc = _fetch_document_record(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await _analyze_document_ocr(doc, force=force)
    if isinstance(result, dict) and result.get("id"):
        return result

    updated = result
    file_path = _resolve_document_file(updated)
    return _serialize_document_response(updated, file_path)


@router.get("/documents/{doc_id}/file")
async def get_document_file(doc_id: str, inline: bool = False) -> FileResponse:
    """Stream the document PDF or preview image for inline viewing or download."""
    doc = _fetch_document_record(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = _resolve_document_file(doc)
    if not file_path:
        raise HTTPException(status_code=404, detail="Document file not found on local disk")

    disposition = "inline" if inline else "attachment"
    return FileResponse(
        path=str(file_path),
        media_type=_media_type_for(file_path),
        filename=file_path.name,
        headers={"Content-Disposition": f'{disposition}; filename="{file_path.name}"'},
    )


@router.get("/documents/{doc_id}/download")
async def download_document_by_id(doc_id: str) -> FileResponse:
    """Download a recorded document directly by document ID."""
    return await get_document_file(doc_id, inline=False)
