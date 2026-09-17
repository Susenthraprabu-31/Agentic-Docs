import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.db.repositories.batches_repository import BatchesRepository
from app.db.repositories.documents_repository import DocumentsRepository
from app.db.repositories.runs_repository import RunsRepository
from app.pipeline.workflow_templates import list_workflow_templates
from app.queue.batch_processor import cancel_batch, enqueue_batch
from app.report.report_builder import ReportBuilder

router = APIRouter(prefix="/batches", tags=["batches"])


class BatchOrderInput(BaseModel):
    state: str = "FL"
    county: str = "miami-dade"
    query_type: str = "book_page"
    query_value: Optional[str] = ""
    book_number: Optional[str] = None
    page_number: Optional[str] = None
    workflow_template: Optional[str] = None


class CreateBatchRequest(BaseModel):
    name: Optional[str] = None
    workflow_template: str = "recorder_deed"
    concurrency: int = Field(default=2, ge=1, le=6)
    orders: list[BatchOrderInput]
    custom_graph: Optional[dict[str, Any]] = None


@router.get("/templates")
async def get_templates() -> list[dict[str, Any]]:
    """List standard workflow templates."""
    return list_workflow_templates()


@router.post("")
async def create_batch(req: CreateBatchRequest) -> dict[str, Any]:
    """Create a new batch job and queue orders for execution."""
    if not req.orders:
        raise HTTPException(status_code=400, detail="At least one order is required")

    repo = BatchesRepository()
    batch = repo.create_batch(
        name=req.name or f"Batch ({len(req.orders)} orders)",
        total_orders=len(req.orders),
        workflow_template=req.workflow_template,
        concurrency=req.concurrency,
        custom_graph=req.custom_graph,
    )

    for idx, o in enumerate(req.orders):
        q_val = o.query_value or ""
        if o.query_type == "book_page" and not q_val and o.book_number and o.page_number:
            q_val = f"{o.book_number.strip()}/{o.page_number.strip()}"

        repo.add_order(
            batch_id=batch["id"],
            state=o.state,
            county=o.county,
            query_type=o.query_type,
            query_value=q_val,
            book_number=o.book_number,
            page_number=o.page_number,
            workflow_template=o.workflow_template or req.workflow_template,
            order_index=idx,
        )

    await enqueue_batch(batch["id"])
    return {
        "batch_id": batch["id"],
        "name": batch["name"],
        "total_orders": len(req.orders),
        "status": "pending",
    }


@router.post("/parse-csv")
async def parse_csv_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    """Parse an uploaded CSV file and extract batch order candidates."""
    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    orders: list[dict[str, Any]] = []

    for row in reader:
        # Flexible column normalization
        norm_row = {k.strip().lower().replace(" ", "_"): v.strip() for k, v in row.items() if k and v}
        state = norm_row.get("state") or "FL"
        county = norm_row.get("county") or "miami-dade"
        query_type = norm_row.get("query_type") or norm_row.get("type") or "book_page"
        book = norm_row.get("book") or norm_row.get("book_number") or norm_row.get("book_no")
        page = norm_row.get("page") or norm_row.get("page_number") or norm_row.get("page_no")
        val = norm_row.get("query_value") or norm_row.get("value") or norm_row.get("search_value") or norm_row.get("parcel") or norm_row.get("address") or ""
        wf = norm_row.get("workflow") or norm_row.get("workflow_template")

        if not val and book and page:
            val = f"{book}/{page}"

        if val or (book and page):
            orders.append({
                "state": state.upper(),
                "county": county.lower(),
                "query_type": query_type.lower(),
                "query_value": val,
                "book_number": book,
                "page_number": page,
                "workflow_template": wf,
            })

    if not orders:
        raise HTTPException(status_code=400, detail="No valid order rows detected in CSV file.")

    return {
        "total_detected": len(orders),
        "orders": orders,
    }


@router.get("")
async def list_batches(limit: int = 50) -> list[dict[str, Any]]:
    """List recent batch jobs."""
    repo = BatchesRepository()
    return repo.list_batches(limit=limit)


@router.get("/{batch_id}")
async def get_batch(batch_id: str) -> dict[str, Any]:
    """Get full batch status including list of order items."""
    repo = BatchesRepository()
    batch = repo.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    orders = repo.get_orders(batch_id)
    return {
        "batch": batch,
        "orders": orders,
    }


@router.post("/{batch_id}/cancel")
async def cancel_batch_job(batch_id: str) -> dict[str, Any]:
    """Cancel remaining queued orders in a batch."""
    cancel_batch(batch_id)
    return {"status": "cancelled", "batch_id": batch_id}


@router.post("/{batch_id}/retry")
async def retry_failed(batch_id: str) -> dict[str, Any]:
    """Re-enqueue failed or cancelled orders in this batch."""
    repo = BatchesRepository()
    orders = repo.get_orders(batch_id)
    retried_count = 0
    for o in orders:
        if o.get("status") in ("failed", "cancelled"):
            repo.update_order(o["id"], status="pending", error_message=None)
            retried_count += 1

    if retried_count == 0:
        raise HTTPException(status_code=400, detail="No failed or cancelled orders to retry")

    repo.update_batch(batch_id, status="pending")
    await enqueue_batch(batch_id)
    return {"status": "retrying", "batch_id": batch_id, "retried_orders": retried_count}


@router.get("/{batch_id}/export")
async def export_batch_archive(batch_id: str) -> StreamingResponse:
    """Export all PDF reports and official deed files for a batch in a single ZIP archive."""
    repo = BatchesRepository()
    batch = repo.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    orders = repo.get_orders(batch_id)
    builder = ReportBuilder()
    docs_repo = DocumentsRepository()

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        summary_rows = [
            ["Order #", "State", "County", "Query Type", "Query Value", "Workflow", "Status", "Report ID", "File"]
        ]

        for idx, o in enumerate(orders):
            run_id = o.get("run_id")
            report_id = o.get("report_id")
            status = o.get("status")
            pdf_name = ""

            # Attach property report PDF
            if run_id:
                report = builder.get_report_by_run(run_id)
                if report and report.get("pdf_path"):
                    report_file = Path(report["pdf_path"])
                    if report_file.is_file():
                        arcname = f"reports/order_{idx+1}_{o['county']}_{report_file.name}"
                        zf.write(report_file, arcname=arcname)
                        pdf_name = report_file.name

                # Attach official deed PDF if present
                docs = docs_repo.list_by_run(run_id)
                for d in docs:
                    sp = d.get("screenshot_path") or (d.get("ocr_json") or {}).get("download_path")
                    if sp:
                        doc_path = Path(sp).resolve()
                        if doc_path.is_file():
                            zf.write(doc_path, arcname=f"documents/order_{idx+1}_{doc_path.name}")

            summary_rows.append([
                str(idx + 1),
                o.get("state", ""),
                o.get("county", ""),
                o.get("query_type", ""),
                o.get("query_value", ""),
                o.get("workflow_template", ""),
                status or "",
                report_id or "",
                pdf_name,
            ])

        # Write summary.csv inside the ZIP
        csv_buf = io.StringIO()
        csv_writer = csv.writer(csv_buf)
        csv_writer.writerows(summary_rows)
        zf.writestr("batch_summary.csv", csv_buf.getvalue())

    zip_buffer.seek(0)
    filename = f"batch_{batch['id'][:8]}_export.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
