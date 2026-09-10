import base64
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import logging

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

from app.db.repositories.documents_repository import DocumentsRepository
from app.db.repositories.records_repository import RecordsRepository
from app.db.repositories.runs_repository import RunsRepository
from app.db.supabase_client import get_memory_store, get_supabase, supabase_call
from app.report.pdf_exporter import DEFAULT_REPORTS_DIR, PdfExporter
from app.storage.report_pdf_storage import ReportPdfStorage

TEMPLATE_DIR = Path(__file__).parent / "templates"
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _embed_image_as_data_uri(image_path: str | None) -> str | None:
    """Embed a local screenshot as a base64 data URI for PDF rendering."""
    if not image_path:
        return None

    candidates = [
        Path(image_path),
        BACKEND_ROOT / image_path,
        BACKEND_ROOT / "screenshots" / Path(image_path).name,
        Path.cwd() / image_path,
        Path.cwd() / "screenshots" / Path(image_path).name,
    ]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            mime = "image/png" if resolved.suffix.lower() == ".png" else "image/jpeg"
            encoded = base64.b64encode(resolved.read_bytes()).decode("utf-8")
            return f"data:{mime};base64,{encoded}"
    logger.warning("GIS screenshot not found for PDF embed: %s", image_path)
    return None


def _resolve_gis_screenshot_data_uri(
    event_path: str | None,
    property_record: dict[str, Any] | None,
) -> str | None:
    data_uri = _embed_image_as_data_uri(event_path)
    if data_uri:
        return data_uri

    apn = (property_record or {}).get("apn")
    if not apn:
        return None

    safe_name = str(apn).replace("/", "-")
    for candidate in (
        BACKEND_ROOT / "screenshots" / f"gis_map_{safe_name}.png",
        Path.cwd() / "screenshots" / f"gis_map_{safe_name}.png",
    ):
        if candidate.is_file():
            return _embed_image_as_data_uri(str(candidate.resolve()))
    return None


class ReportBuilder:
    def __init__(self) -> None:
        self.runs_repo = RunsRepository()
        self.records_repo = RecordsRepository()
        self.documents_repo = DocumentsRepository()
        self.pdf_exporter = PdfExporter(output_dir=DEFAULT_REPORTS_DIR)
        self.pdf_storage = ReportPdfStorage()
        self.env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)

    def _render_report_html(self, run_id: str, run: dict[str, Any]) -> tuple[dict[str, Any], str]:
        records = self.records_repo.list_by_run(run_id)
        documents = self.documents_repo.list_by_run(run_id)
        events = self.runs_repo.get_events(run_id)

        property_record = next(
            (r for r in records if r.get("source") == "assessor"),
            records[0] if records else None,
        )
        tax_record = next((r for r in records if r.get("source") == "tax_record"), None)
        sources_trail = []
        gis_screenshot_path: str | None = None

        for e in events:
            payload = e.get("payload") or {}
            sources_trail.append(
                {
                    "source": e.get("source"),
                    "event_type": e.get("event_type"),
                    "message": payload.get("message"),
                    "records_found": payload.get("records_found", 0),
                }
            )
            # Capture the GIS screenshot path from the gis source_completed event
            if e.get("source") == "gis" and e.get("event_type") == "source_completed":
                gis_screenshot_path = payload.get("screenshot_path")

        gis_screenshot_data_uri = _resolve_gis_screenshot_data_uri(
            gis_screenshot_path, property_record
        )

        # Extract chain of title from the assessor raw_json
        chain_of_title: list[dict[str, Any]] = []
        if property_record:
            raw_json = property_record.get("raw_json") or {}
            chain_of_title = raw_json.get("chain_of_title") or []

        # Also pull chain entries from documents (saved by _persist_assessor_chain_of_title)
        chain_docs = [
            d for d in documents
            if (d.get("ocr_json") or {}).get("source") == "assessor_sales"
        ]

        report_json: dict[str, Any] = {
            "run_id": run_id,
            "state": run["state"],
            "county": run["county"],
            "query_type": run["query_type"],
            "query_value": run["query_value"],
            "property": property_record,
            "tax_record": tax_record,
            "records": records,
            "documents": documents,
            "chain_of_title": chain_of_title,
            "sources_trail": sources_trail,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        template = self.env.get_template("property_report.html")
        html = template.render(
            state=run["state"],
            county=run["county"],
            query_type=run["query_type"],
            query_value=run["query_value"],
            property=property_record,
            tax_record=tax_record,
            documents=documents,
            chain_of_title=chain_of_title,
            chain_docs=chain_docs,
            gis_screenshot_data_uri=gis_screenshot_data_uri,
            generated_at=report_json["generated_at"],
        )
        return report_json, html


    async def build_and_save(self, run_id: str) -> dict[str, Any]:
        run = self.runs_repo.get_run(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")

        existing = self.get_report_by_run(run_id)
        report_id = existing["id"] if existing else str(uuid.uuid4())

        report_json, html = self._render_report_html(run_id, run)
        pdf_path = await self.pdf_exporter.html_to_pdf(html, f"report_{run_id}.pdf")
        html_path = str(Path(pdf_path).with_suffix(".html"))

        row = {
            "id": report_id,
            "run_id": run_id,
            "report_json": report_json,
            "html_path": html_path,
            "pdf_path": pdf_path,
            "created_at": existing.get("created_at") if existing else datetime.now(timezone.utc).isoformat(),
        }

        mem = get_memory_store()
        mem.reports[run_id] = row

        client = get_supabase()
        if client:
            try:
                existing_db = client.table("reports").select("id").eq("run_id", run_id).execute()
                if existing_db.data:
                    result = client.table("reports").update(row).eq("run_id", run_id).execute()
                else:
                    result = client.table("reports").insert(row).execute()
                if result.data:
                    mem.reports[run_id] = result.data[0]
                    return result.data[0]
            except Exception as exc:
                logger.warning("Supabase report save failed, using local copy: %s", exc)

        return row

    async def ensure_pdf(self, report: dict[str, Any]) -> dict[str, Any]:
        run_id = report["run_id"]
        run = self.runs_repo.get_run(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")

        report_json, html = self._render_report_html(run_id, run)
        pdf_path = await self.pdf_exporter.html_to_pdf(html, f"report_{run_id}.pdf")
        report = {
            **report,
            "report_json": report_json,
            "pdf_path": pdf_path,
            "html_path": str(Path(pdf_path).with_suffix(".html")),
        }

        mem = get_memory_store()
        mem.reports[run_id] = report

        client = get_supabase()
        if client:
            try:
                client.table("reports").update(
                    {
                        "pdf_path": report["pdf_path"],
                        "html_path": report["html_path"],
                        "report_json": report_json,
                    }
                ).eq("id", report["id"]).execute()
            except Exception as exc:
                logger.warning("Supabase report PDF update failed: %s", exc)

        return report

    def upload_pdf_to_storage(self, report: dict[str, Any]) -> dict[str, Any]:
        """Upload the local PDF to Supabase Storage and persist storage metadata."""
        pdf_path = report.get("pdf_path")
        run_id = report.get("run_id")
        if not pdf_path or not run_id:
            return report

        self.pdf_storage.ensure_bucket_exists()
        upload = self.pdf_storage.upload(pdf_path, run_id)
        if not upload:
            return report

        report = {
            **report,
            "storage_path": upload.path,
            "storage_url": upload.url,
        }

        mem = get_memory_store()
        mem.reports[run_id] = report

        client = get_supabase()
        if client:
            try:
                supabase_call(
                    lambda: client.table("reports")
                    .update({"storage_path": upload.path, "storage_url": upload.url})
                    .eq("id", report["id"])
                    .execute(),
                    label="report_storage_update",
                )
            except Exception as exc:
                logger.warning("Supabase report storage update failed: %s", exc)

        return report

    def get_report_by_run(self, run_id: str) -> Optional[dict[str, Any]]:
        mem_report = get_memory_store().reports.get(run_id)
        if mem_report:
            return mem_report
        client = get_supabase()
        if client:
            try:
                result = client.table("reports").select("*").eq("run_id", run_id).execute()
                if result.data:
                    get_memory_store().reports[run_id] = result.data[0]
                    return result.data[0]
            except Exception as exc:
                logger.warning("Supabase report fetch failed: %s", exc)
        return None

    def get_report(self, report_id: str) -> Optional[dict[str, Any]]:
        for report in get_memory_store().reports.values():
            if report.get("id") == report_id:
                return report

        client = get_supabase()
        if client:
            try:
                result = client.table("reports").select("*").eq("id", report_id).execute()
                if result.data:
                    report = result.data[0]
                    get_memory_store().reports[report["run_id"]] = report
                    return report
            except Exception as exc:
                logger.warning("Supabase report fetch failed: %s", exc)
        return None
