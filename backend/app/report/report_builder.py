import base64
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.request import urlopen

import logging

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

from app.db.repositories.documents_repository import DocumentsRepository
from app.db.repositories.records_repository import RecordsRepository
from app.db.repositories.runs_repository import RunsRepository
from app.db.report_storage import (
    enrich_report_storage,
    merge_storage_into_report_json,
    persist_report_storage,
)
from app.db.supabase_client import get_memory_store, get_supabase
from app.extraction.miami_dade_name_searches import (
    build_name_searcher_report_entries,
    resolve_name_searches_for_report,
)
from app.report.pdf_exporter import DEFAULT_REPORTS_DIR, PdfExporter
from app.storage.document_paths import resolve_document_preview_path, resolve_document_preview_url
from app.storage.report_pdf_storage import ReportPdfStorage

TEMPLATE_DIR = Path(__file__).parent / "templates"
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _embed_image_from_url(image_url: str | None) -> str | None:
    if not image_url or not image_url.startswith("http"):
        return None
    try:
        with urlopen(image_url, timeout=30) as response:
            raw = response.read()
        if not raw:
            return None
        content_type = response.headers.get_content_type() if hasattr(response, "headers") else "image/png"
        mime = content_type if content_type.startswith("image/") else "image/png"
        encoded = base64.b64encode(raw).decode("utf-8")
        return f"data:{mime};base64,{encoded}"
    except Exception as exc:
        logger.debug("Could not embed image from storage URL %s: %s", image_url, exc)
        return None


def _embed_image_as_data_uri(image_path: str | None, *, storage_url: str | None = None) -> str | None:
    """Embed a local screenshot or Supabase preview URL as a base64 data URI for PDF rendering."""
    if storage_url:
        embedded = _embed_image_from_url(storage_url)
        if embedded:
            return embedded

    if not image_path:
        return None

    candidates = [
        Path(image_path),
        BACKEND_ROOT / image_path,
        Path.cwd() / image_path,
        BACKEND_ROOT / "local_storage" / Path(image_path).name,
        BACKEND_ROOT / "local_storage" / Path(image_path).stem / Path(image_path).name,
        BACKEND_ROOT / "downloads" / Path(image_path).name,
        BACKEND_ROOT / "downloads" / Path(image_path).stem / Path(image_path).name,
        BACKEND_ROOT / "screenshots" / Path(image_path).name,
        BACKEND_ROOT / "screenshots" / Path(image_path).stem / Path(image_path).name,
        Path.cwd() / "screenshots" / Path(image_path).name,
        Path.cwd() / "local_storage" / Path(image_path).name,
    ]

    path_obj = Path(image_path)
    if len(path_obj.parts) >= 2:
        candidates.extend(
            [
                BACKEND_ROOT / "local_storage" / Path(*path_obj.parts[-2:]),
                Path("local_storage") / Path(*path_obj.parts[-2:]),
            ]
        )

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if resolved.is_file() and resolved.stat().st_size > 0:
                mime = "image/png" if resolved.suffix.lower() == ".png" else "image/jpeg"
                encoded = base64.b64encode(resolved.read_bytes()).decode("utf-8")
                return f"data:{mime};base64,{encoded}"
        except Exception:
            pass
    logger.warning("Image not found for PDF embed: %s", image_path)
    return None


def _find_gis_screenshot_file(event_path: str | None, folio: str | None) -> Path | None:
    """Locate a captured GIS map PNG on disk."""
    candidates: list[Path] = []
    if event_path:
        candidates.extend(
            [
                Path(event_path),
                BACKEND_ROOT / event_path,
                BACKEND_ROOT / "screenshots" / Path(event_path).name,
                Path.cwd() / Path(event_path).name,
            ]
        )
    if folio:
        safe_name = str(folio).replace("/", "-")
        candidates.extend(
            [
                BACKEND_ROOT / "screenshots" / f"gis_map_{safe_name}.png",
                Path.cwd() / "screenshots" / f"gis_map_{safe_name}.png",
            ]
        )

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        try:
            resolved = candidate.resolve()
            if resolved.is_file() and resolved.stat().st_size > 0:
                return resolved
        except Exception:
            continue

    screenshots_dir = BACKEND_ROOT / "screenshots"
    if folio and screenshots_dir.is_dir():
        folio_digits = "".join(ch for ch in str(folio) if ch.isdigit())
        for png in screenshots_dir.glob("gis_map_*.png"):
            if folio_digits and folio_digits in png.stem.replace("-", ""):
                return png.resolve()

    return None


def _extract_gis_screenshot_path(
    events: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> str | None:
    screenshot_path: str | None = None
    for event in events:
        payload = event.get("payload") or {}
        if event.get("source") == "gis" and event.get("event_type") == "source_completed":
            screenshot_path = payload.get("screenshot_path") or screenshot_path
        if payload.get("node") == "GISNode" and event.get("event_type") == "node_completed":
            screenshot_path = payload.get("screenshot_path") or screenshot_path

    for doc in documents:
        ocr = doc.get("ocr_json") or {}
        if doc.get("document_type") == "gis_map" or ocr.get("source") == "gis":
            screenshot_path = (
                doc.get("screenshot_path")
                or ocr.get("image_path")
                or screenshot_path
            )
    return screenshot_path


def _resolve_gis_screenshot(
    events: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    property_record: dict[str, Any] | None,
    query_value: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Return local path, embedded data URI, and public URL for the GIS map."""
    event_path = _extract_gis_screenshot_path(events, documents)
    folio = (property_record or {}).get("apn") or query_value
    file_path = _find_gis_screenshot_file(event_path, folio)
    if not file_path:
        return None, None, None

    data_uri = _embed_image_as_data_uri(str(file_path))
    public_url = f"/screenshots/{file_path.name}"
    return str(file_path.resolve()), data_uri, public_url


def _format_markdown_to_html(md_text: str) -> str:
    """Format markdown text with headings, bullet points, and bold tags into clean HTML."""
    if not md_text:
        return ""
    import html as html_lib
    import re
    lines = md_text.splitlines()
    html_lines: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue

        if stripped.startswith("#### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            title = html_lib.escape(stripped[5:].strip())
            html_lines.append(f"<h5 style=\"margin: 12px 0 6px 0; color: #334155; font-size: 13px; font-weight: 700;\">{title}</h5>")
            continue
        if stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            title = html_lib.escape(stripped[4:].strip())
            html_lines.append(f"<h4 style=\"margin: 16px 0 8px 0; color: #4338ca; font-size: 14px; font-weight: 700;\">{title}</h4>")
            continue
        if stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            title = html_lib.escape(stripped[3:].strip())
            html_lines.append(f"<h3 style=\"margin: 18px 0 8px 0; color: #1e1b4b; font-size: 15px; font-weight: 700;\">{title}</h3>")
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_lines.append("<ul style=\"margin: 4px 0 8px 18px; padding-left: 0;\">")
                in_list = True
            content = html_lib.escape(stripped[2:].strip())
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
            html_lines.append(f"<li style=\"margin-bottom: 4px; line-height: 1.5;\">{content}</li>")
            continue

        if in_list:
            html_lines.append("</ul>")
            in_list = False

        content = html_lib.escape(stripped)
        content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
        html_lines.append(f"<p style=\"margin: 6px 0; line-height: 1.5;\">{content}</p>")

    if in_list:
        html_lines.append("</ul>")
    return "\n".join(html_lines)


def _resolve_ai_agent_data(
    run: dict[str, Any],
    documents: list[dict[str, Any]],
) -> tuple[Optional[str], Optional[str], dict[str, Any]]:
    """Extract AI agent response, model name, and metadata from run or documents."""
    plan_json = run.get("plan_json") or {}
    ai_response = plan_json.get("ai_agent_response") or plan_json.get("chatbot_response")
    ai_model = plan_json.get("ai_agent_model") or plan_json.get("chatbot_model")
    ai_meta: dict[str, Any] = {}

    node_results = plan_json.get("node_results") or {}
    ai_node = node_results.get("ai_agent") or node_results.get("chatbot") or {}
    if not isinstance(ai_node, dict):
        ai_node = {}

    if not ai_response:
        ai_response = ai_node.get("content")
    if not ai_model:
        ai_model = ai_node.get("model")

    # If still not found, search all node results for an AI agent payload
    if not ai_response:
        for val in node_results.values():
            if isinstance(val, dict) and val.get("content") and (val.get("model") or val.get("agent_name")):
                ai_response = val.get("content")
                ai_model = val.get("model") or ai_model
                ai_node = val
                break

    # If still not found, check existing documents for an AI analysis or chatbot document
    if not ai_response:
        for d in documents:
            ocr = d.get("ocr_json") or {}
            if ocr.get("source") in ("ai_agent", "chatbot") or d.get("document_type") in ("AI Title Analysis", "AI Chatbot Response"):
                ai_response = d.get("notes") or ocr.get("ai_response")
                ai_model = ocr.get("model") or ai_model
                break

    if ai_node:
        ai_meta = {
            "model": ai_model or ai_node.get("model"),
            "agent_name": ai_node.get("agent_name"),
            "duration_ms": ai_node.get("duration_ms"),
            "prompt_tokens": ai_node.get("prompt_tokens"),
            "completion_tokens": ai_node.get("completion_tokens"),
            "total_tokens": ai_node.get("total_tokens"),
        }

    return ai_response, ai_model, ai_meta


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

        gis_screenshot_path, gis_screenshot_data_uri, gis_screenshot_url = _resolve_gis_screenshot(
            events,
            documents,
            property_record,
            run.get("query_value"),
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

        # Enrich documents with image data URIs, folder info, and file names for report embedding
        for d in documents:
            sp = d.get("screenshot_path")
            ocr = d.get("ocr_json") or {}
            dl_path = ocr.get("download_path") or sp
            folder_name = ocr.get("folder_name")
            if folder_name:
                d["folder_name"] = folder_name

            if dl_path:
                d["download_path"] = str(dl_path)
                d["file_name"] = Path(dl_path).name

            if ocr.get("source") == "assessor":
                if ocr.get("pdf_storage_url"):
                    d["pdf_storage_url"] = ocr.get("pdf_storage_url")
                continue

            preview_url = resolve_document_preview_url(d)
            preview_path = resolve_document_preview_path(d, Path(sp) if sp else None)
            img_candidate = str(preview_path) if preview_path else ocr.get("image_path")

            if preview_url or img_candidate:
                data_uri = _embed_image_as_data_uri(
                    str(img_candidate) if img_candidate else None,
                    storage_url=preview_url,
                )
                if data_uri:
                    d["image_data_uri"] = data_uri
                if preview_url:
                    d["preview_storage_url"] = preview_url

        # Extract AI agent response and metadata if present in run or documents
        ai_agent_response, ai_agent_model, ai_agent_meta = _resolve_ai_agent_data(run, documents)

        # Ensure an official AI Title Analysis or Chatbot document is inserted into documents_repo
        has_ai_doc = any(
            d.get("document_type") in ("AI Title Analysis", "AI Chatbot Response")
            or (d.get("ocr_json") or {}).get("source") in ("ai_agent", "chatbot")
            for d in documents
        )
        if ai_agent_response and not has_ai_doc:
            is_chatbot = (ai_agent_meta or {}).get("agent_name") == "Title Chatbot" or "chatbot" in str(ai_agent_meta or {})
            doc_type = "AI Chatbot Response" if is_chatbot else "AI Title Analysis"
            doc_prefix = "CB" if is_chatbot else "AI"
            doc_row = {
                "document_type": doc_type,
                "recording_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "instrument_number": f"{doc_prefix}-{run_id[:8].upper()}",
                "grantor": f"OpenAI ({ai_agent_model or 'gpt-4o'})",
                "grantee": (property_record.get("owner_name") if property_record else None) or "Title Production Report",
                "notes": ai_agent_response,
                "ocr_json": {
                    "source": "chatbot" if is_chatbot else "ai_agent",
                    "model": ai_agent_model or "gpt-4o",
                    "ai_response": ai_agent_response,
                    **(ai_agent_meta or {}),
                },
            }
            try:
                saved_doc = self.documents_repo.insert(run_id, doc_row)
                documents.append(saved_doc)
            except Exception as exc:
                logger.warning("Could not persist %s document: %s", doc_type, exc)
                documents.append(doc_row)

        ai_agent_html = _format_markdown_to_html(ai_agent_response) if ai_agent_response else ""
        plan_json = run.get("plan_json") or {}
        name_searches = resolve_name_searches_for_report(
            plan_json,
            documents=documents,
        )

        report_json: dict[str, Any] = {
            "run_id": run_id,
            "state": run["state"],
            "county": run["county"],
            "query_type": run["query_type"],
            "query_value": run["query_value"],
            "search_scope": (run.get("plan_json") or {}).get("search_scope", "full"),
            "search_limit": (run.get("plan_json") or {}).get("search_limit"),
            "property": property_record,
            "tax_record": tax_record,
            "records": records,
            "documents": documents,
            "chain_of_title": chain_of_title,
            "name_searches": name_searches,
            "sources_trail": sources_trail,
            "gis_screenshot_path": gis_screenshot_path,
            "gis_screenshot_url": gis_screenshot_url,
            "gis_screenshot_data_uri": gis_screenshot_data_uri,
            "ai_agent_response": ai_agent_response,
            "ai_agent_model": ai_agent_model,
            "ai_agent_meta": ai_agent_meta,
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
            name_searches=name_searches,
            gis_screenshot_data_uri=gis_screenshot_data_uri,
            ai_agent_response=ai_agent_response,
            ai_agent_model=ai_agent_model,
            ai_agent_meta=ai_agent_meta,
            ai_agent_html=ai_agent_html,
            generated_at=report_json["generated_at"],
        )
        return report_json, html


    def refresh_report_json(self, report: dict[str, Any]) -> dict[str, Any]:
        """Re-render report_json from current run data without regenerating the PDF."""
        run_id = report.get("run_id")
        if not run_id:
            return report
        run = self.runs_repo.get_run(run_id)
        if not run:
            return report

        report_json, _ = self._render_report_html(run_id, run)
        updated = {**report, "report_json": report_json}

        mem = get_memory_store()
        mem.reports[run_id] = updated

        client = get_supabase()
        if client:
            try:
                client.table("reports").update({"report_json": report_json}).eq("id", report["id"]).execute()
            except Exception as exc:
                logger.warning("Supabase report_json refresh failed: %s", exc)

        return updated

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

        report_json = merge_storage_into_report_json(
            report.get("report_json"),
            upload.path,
            upload.url,
        )
        report = enrich_report_storage({
            **report,
            "report_json": report_json,
            "storage_path": upload.path,
            "storage_url": upload.url,
        })

        mem = get_memory_store()
        mem.reports[run_id] = report

        client = get_supabase()
        if client:
            if not persist_report_storage(
                client,
                report_id=report["id"],
                storage_path=upload.path,
                storage_url=upload.url,
                report_json=report_json,
            ):
                logger.warning("Supabase report storage update failed for run %s", run_id)

        return report

    def get_report_by_run(self, run_id: str) -> Optional[dict[str, Any]]:
        mem_report = get_memory_store().reports.get(run_id)
        if mem_report:
            return enrich_report_storage(mem_report)
        client = get_supabase()
        if client:
            try:
                result = client.table("reports").select("*").eq("run_id", run_id).execute()
                if result.data:
                    report = enrich_report_storage(result.data[0])
                    get_memory_store().reports[run_id] = report
                    return report
            except Exception as exc:
                logger.warning("Supabase report fetch failed: %s", exc)
        return None

    def get_report(self, report_id: str) -> Optional[dict[str, Any]]:
        for report in get_memory_store().reports.values():
            if report.get("id") == report_id:
                return enrich_report_storage(report)

        client = get_supabase()
        if client:
            try:
                result = client.table("reports").select("*").eq("id", report_id).execute()
                if result.data:
                    report = enrich_report_storage(result.data[0])
                    get_memory_store().reports[report["run_id"]] = report
                    return report
            except Exception as exc:
                logger.warning("Supabase report fetch failed: %s", exc)
        return None
