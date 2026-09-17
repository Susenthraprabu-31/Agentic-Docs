import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.agents.county_resolver import CountyResolver
from app.agents.extraction_normalizer import ExtractionNormalizer
from app.agents.openai_agent import OpenAIAgentService
from app.agents.run_logger import RunLogger
from app.db.repositories.documents_repository import DocumentsRepository
from app.db.repositories.records_repository import RecordsRepository
from app.db.repositories.runs_repository import RunsRepository
from app.config.florida_portals import (
    MIAMI_DADE_SEARCH_URL,
    resolve_florida_county_sources,
    resolve_florida_recorder_url,
    resolve_florida_tax_url,
)
from app.drivers.assessor.gila_assessor_driver import GilaAssessorDriver
from app.drivers.base.base_driver import BaseDriver
from app.drivers.gis.gila_gis_driver import GilaGisDriver
from app.drivers.netronline.netronline_driver import NetronlineDriver
from app.drivers.browser_registry import register_driver, unregister_driver
from app.drivers.recorder.gila_recorder_driver import GilaRecorderDriver
from app.drivers.tax.florida_tax_driver import FloridaTaxDriver
from app.extraction.document_ocr import DocumentOcrService
from app.config.platform_rules import get_assessor_platform_rules, get_recorder_platform_rules
from app.extraction.book_page import format_book_page_label, parse_book_page
from app.extraction.schemas import CountySources, QueryType, RunStatus, SourceType
from app.agents.ai_agent_coordinator import wait_for_pending
from app.pipeline.graph_executor import ParsedPipelineGraph, requires_browser, resolve_pipeline_graph
from app.report.pdf_exporter import is_valid_pdf
from app.report.report_builder import ReportBuilder

logger = logging.getLogger(__name__)


def _detect_platform(url: str, rules: list[tuple[str, str]]) -> Optional[str]:
    if not url:
        return None
    lower = url.lower()
    for fragment, platform in rules:
        if fragment.lower() in lower:
            return platform
    return None

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCREENSHOTS_DIR = BACKEND_ROOT / "screenshots"

NODE_EVENT_NAMES = {
    "input": "InputNode",
    "netr": "NETRResolverNode",
    "platform": "PlatformDetectorNode",
    "assessor": "AssessorNode",
    "recorder": "RecorderNode",
    "gis": "GISNode",
    "tax": "TaxNode",
    "ai_agent": "AIAgentNode",
    "normalizer": "NormalizerNode",
    "report": "ReportNode",
    "output": "OutputNode",
}


@dataclass
class RunContext:
    state: str
    county: str
    query_type: QueryType
    query_value: str
    total_records: int = 0
    address: Optional[str] = None
    parcel: Optional[str] = None
    owner_name: Optional[str] = None
    book_number: Optional[str] = None
    page_number: Optional[str] = None
    sources: Optional[CountySources] = None
    report_id: Optional[str] = None


def _data_str(data: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        val = data.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return default


def _resolve_search_params_from_graph(
    parsed: ParsedPipelineGraph,
    state: str,
    county: str,
    query_type: QueryType,
    query_value: str,
) -> tuple[str, str, QueryType, str]:
    """Prefer Input node canvas data over top-level API fields, and intelligently detect query type based on provided inputs."""
    for canvas_id in parsed.order:
        node = parsed.node_map.get(canvas_id, {})
        if node.get("node_id") != "input":
            continue
        data = node.get("data") or {}
        if data.get("state"):
            state = str(data["state"]).strip().upper()
        if data.get("county"):
            county = str(data["county"]).strip().lower()

        owner_val = _data_str(data, "ownerName", "owner_name")
        address_val = _data_str(data, "address", "property_address")
        parcel_val = _data_str(data, "parcelNumber", "parcel_number")
        book_val = _data_str(data, "bookNumber", "book_number") or None
        page_val = _data_str(data, "pageNumber", "page_number") or None

        raw_qtype = _data_str(data, "query_type", "queryType").lower()
        node_qtype: Optional[QueryType] = None
        if raw_qtype:
            try:
                node_qtype = QueryType(raw_qtype)
            except ValueError:
                pass

        raw_qval = _data_str(data, "query_value", "queryValue")

        # Based strictly on what input is provided:
        # If address is present and owner_name is not present, the user searched by address!
        if address_val and not owner_val and not parcel_val and not (book_val or page_val):
            query_type = QueryType.ADDRESS
            query_value = address_val
        elif parcel_val and not owner_val and not address_val and not (book_val or page_val):
            query_type = QueryType.PARCEL
            query_value = parcel_val
        elif (book_val or page_val) and not owner_val and not address_val and not parcel_val:
            query_type = QueryType.BOOK_PAGE
            query_value = format_book_page_label(book_val, page_val) if (book_val and page_val) else (book_val or page_val or "")
        elif owner_val and not address_val and not parcel_val and not (book_val or page_val):
            query_type = QueryType.OWNER
            query_value = owner_val
        elif node_qtype:
            query_type = node_qtype
            if query_type == QueryType.ADDRESS and address_val:
                query_value = address_val
            elif query_type == QueryType.OWNER and owner_val:
                query_value = owner_val
            elif query_type == QueryType.PARCEL and parcel_val:
                query_value = parcel_val
            elif raw_qval:
                query_value = raw_qval
        elif raw_qval:
            query_value = raw_qval

        if query_type == QueryType.BOOK_PAGE:
            book_page_parts = parse_book_page(query_value, book_val, page_val)
            if book_page_parts:
                b_num, p_num = book_page_parts
                query_value = format_book_page_label(b_num, p_num)
        break
    return state, county, query_type, query_value


def _apply_input_data_to_ctx(data: dict[str, Any], ctx: RunContext) -> None:
    if data.get("state"):
        ctx.state = str(data["state"]).strip().upper()
    if data.get("county"):
        ctx.county = str(data["county"]).strip().lower()

    owner_val = _data_str(data, "ownerName", "owner_name")
    address_val = _data_str(data, "address", "property_address")
    parcel_val = _data_str(data, "parcelNumber", "parcel_number")
    book_val = _data_str(data, "bookNumber", "book_number") or None
    page_val = _data_str(data, "pageNumber", "page_number") or None

    if address_val:
        ctx.address = address_val
    if owner_val:
        ctx.owner_name = owner_val
    if parcel_val:
        ctx.parcel = parcel_val
    if book_val:
        ctx.book_number = book_val
    if page_val:
        ctx.page_number = page_val

    raw_qtype = _data_str(data, "query_type", "queryType").lower()
    node_qtype: Optional[QueryType] = None
    if raw_qtype:
        try:
            node_qtype = QueryType(raw_qtype)
        except ValueError:
            pass

    raw_qval = _data_str(data, "query_value", "queryValue")

    if address_val and not owner_val and not parcel_val and not (book_val or page_val):
        ctx.query_type = QueryType.ADDRESS
        ctx.query_value = address_val
    elif parcel_val and not owner_val and not address_val and not (book_val or page_val):
        ctx.query_type = QueryType.PARCEL
        ctx.query_value = parcel_val
    elif (book_val or page_val) and not owner_val and not address_val and not parcel_val:
        ctx.query_type = QueryType.BOOK_PAGE
        ctx.query_value = format_book_page_label(book_val, page_val) if (book_val and page_val) else (book_val or page_val or "")
    elif owner_val and not address_val and not parcel_val and not (book_val or page_val):
        ctx.query_type = QueryType.OWNER
        ctx.query_value = owner_val
    elif node_qtype:
        ctx.query_type = node_qtype
        if ctx.query_type == QueryType.ADDRESS and address_val:
            ctx.query_value = address_val
        elif ctx.query_type == QueryType.OWNER and owner_val:
            ctx.query_value = owner_val
        elif ctx.query_type == QueryType.PARCEL and parcel_val:
            ctx.query_value = parcel_val
        elif raw_qval:
            ctx.query_value = raw_qval
    elif raw_qval:
        ctx.query_value = raw_qval

    if ctx.query_type == QueryType.BOOK_PAGE:
        book_page_parts = parse_book_page(ctx.query_value, ctx.book_number, ctx.page_number)
        if book_page_parts:
            ctx.book_number, ctx.page_number = book_page_parts
            ctx.query_value = format_book_page_label(ctx.book_number, ctx.page_number)
    elif ctx.query_type == QueryType.PARCEL and ctx.query_value:
        ctx.parcel = ctx.query_value
    elif ctx.query_type == QueryType.ADDRESS and ctx.query_value:
        ctx.address = ctx.query_value
    elif ctx.query_type == QueryType.OWNER and ctx.query_value:
        ctx.owner_name = ctx.query_value


class Orchestrator:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.runs_repo = RunsRepository()
        self.records_repo = RecordsRepository()
        self.documents_repo = DocumentsRepository()
        self.run_logger = RunLogger(run_id)
        self.normalizer = ExtractionNormalizer()
        self.ocr = DocumentOcrService()
        self.ai_agent = OpenAIAgentService()
        self.sources: Optional[CountySources] = None

    async def execute(
        self,
        state: str,
        county: str,
        query_type: QueryType,
        query_value: str,
        pipeline_graph: Optional[dict[str, Any]] = None,
        node_overrides: Optional[list[dict]] = None,
    ) -> dict[str, Any]:
        parsed = resolve_pipeline_graph(pipeline_graph)
        state, county, query_type, query_value = _resolve_search_params_from_graph(
            parsed, state, county, query_type, query_value
        )
        self.runs_repo.update_run(
            self.run_id,
            status=RunStatus.RUNNING.value,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        plan: dict[str, Any] = {
            "steps": parsed.step_node_ids,
            "pipeline_graph": pipeline_graph,
            "state": state,
            "county": county,
            "query_type": query_type.value,
            "query_value": query_value,
        }
        self.runs_repo.update_run(self.run_id, plan_json=plan)

        driver: Optional[NetronlineDriver] = None
        resolver: Optional[CountyResolver] = None
        needs_browser = requires_browser(parsed.step_node_ids)

        try:
            if needs_browser:
                driver = NetronlineDriver(screenshot_dir=SCREENSHOTS_DIR)

                async def _status(msg: str) -> None:
                    await self.run_logger.log("human_action_required", message=msg)

                driver.status_callback = _status
                driver.preview_run_id = self.run_id
                await driver.start()
                await driver.start_live_stream(self.run_id)
                register_driver(self.run_id, driver)
                resolver = CountyResolver(driver)

            ctx = RunContext(
                state=state,
                county=county,
                query_type=query_type,
                query_value=query_value,
                address=query_value if query_type == QueryType.ADDRESS else None,
                parcel=query_value if query_type == QueryType.PARCEL else None,
                owner_name=query_value if query_type == QueryType.OWNER else None,
            )
            if query_type == QueryType.BOOK_PAGE:
                book_page_parts = parse_book_page(query_value)
                if book_page_parts:
                    ctx.book_number, ctx.page_number = book_page_parts

            for canvas_id in parsed.order:
                node = parsed.node_map[canvas_id]
                node_id = node.get("node_id", "")
                data = node.get("data") or {}

                if not node.get("enabled", True):
                    await self._log_node_skipped(node_id, "Node disabled")
                    continue

                event_name = NODE_EVENT_NAMES.get(node_id, node_id)
                await self.run_logger.log(
                    "pipeline_step",
                    node=event_name,
                    message=f"Running {event_name}",
                    step_node_id=node_id,
                )
                await self._dispatch_node(node_id, data, ctx, driver, resolver, canvas_id=canvas_id)

            self.sources = ctx.sources
            self.runs_repo.update_run(
                self.run_id,
                status=RunStatus.COMPLETED.value,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.run_logger.run_completed(total_records=ctx.total_records, report_id=ctx.report_id)
            return {
                "run_id": self.run_id,
                "total_records": ctx.total_records,
                "sources": ctx.sources.model_dump() if ctx.sources else {},
                "steps": parsed.step_node_ids,
            }

        except Exception as exc:
            logger.exception("Run %s failed", self.run_id)
            self.runs_repo.update_run(
                self.run_id,
                status=RunStatus.FAILED.value,
                error_message=str(exc),
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.run_logger.log("run_failed", message=str(exc))
            raise
        finally:
            if driver:
                unregister_driver(self.run_id)
                await driver.stop()

    async def _log_node_skipped(self, node_id: str, reason: str) -> None:
        event = NODE_EVENT_NAMES.get(node_id, node_id)
        await self.run_logger.log("node_completed", node=event, message=f"Skipped — {reason}")

    def _refresh_parcel(self, ctx: RunContext) -> None:
        if ctx.parcel:
            return
        records = self.records_repo.list_by_run(self.run_id)
        assessor_record = next((r for r in records if r.get("source") == "assessor"), records[0] if records else None)
        if assessor_record:
            ctx.parcel = assessor_record.get("apn")
            ctx.owner_name = assessor_record.get("owner_name")

    def _parcel_for_sources(self, ctx: RunContext) -> str:
        if ctx.parcel:
            return ctx.parcel
        if ctx.query_type == QueryType.PARCEL and ctx.query_value:
            return ctx.query_value
        return ""

    def _ensure_ctx_sources(self, ctx: RunContext) -> None:
        if ctx.sources:
            return
        if ctx.state.upper() == "FL":
            ctx.sources = resolve_florida_county_sources(ctx.county, self._parcel_for_sources(ctx))

    def _resolve_portal_url(
        self,
        ctx: RunContext,
        data: dict[str, Any],
        source_attr: str,
    ) -> str:
        self._ensure_ctx_sources(ctx)
        explicit = _data_str(data, "url")
        if explicit:
            return explicit
        if ctx.sources:
            url = getattr(ctx.sources, source_attr, None)
            if url:
                return str(url)
        if ctx.state.upper() == "FL":
            fallback = resolve_florida_county_sources(ctx.county, self._parcel_for_sources(ctx))
            url = getattr(fallback, source_attr, None)
            if url:
                if ctx.sources:
                    setattr(ctx.sources, source_attr, url)
                else:
                    ctx.sources = fallback
                return str(url)
        return ""

    async def _dispatch_node(
        self,
        node_id: str,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
    ) -> None:
        handlers = {
            "input": self._node_input,
            "netr": self._node_netr,
            "platform": self._node_platform,
            "assessor": self._node_assessor,
            "recorder": self._node_recorder,
            "gis": self._node_gis,
            "tax": self._node_tax,
            "normalizer": self._node_normalizer,
            "report": self._node_report,
            "output": self._node_output,
        }
        if node_id == "ai_agent":
            await self._node_ai_agent(data, ctx, driver, resolver, canvas_id=canvas_id)
            return
        handler = handlers.get(node_id)
        if not handler:
            await self.run_logger.log("node_completed", node=node_id, message=f"Unknown node type: {node_id}")
            return
        await handler(data, ctx, driver, resolver)

    async def _node_input(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
    ) -> None:
        await self.run_logger.node_started("InputNode")
        _apply_input_data_to_ctx(data, ctx)
        await self.run_logger.node_completed(
            "InputNode",
            state=ctx.state,
            county=ctx.county,
            query_type=ctx.query_type.value,
            query_value=ctx.query_value,
            address=ctx.address,
            owner_name=ctx.owner_name,
            parcel=ctx.parcel,
        )

    async def _node_netr(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
    ) -> None:
        if not driver or not resolver:
            await self.run_logger.source_skipped(SourceType.NETRONLINE, "Browser not required for this run")
            return
        notes = _data_str(data, "playwright_notes") or None
        custom_url = _data_str(data, "url") or None
        if notes:
            driver.playwright_notes = notes
        t0 = time.monotonic()
        await self.run_logger.node_started("NETRResolverNode", url=custom_url or None)
        await self.run_logger.source_started(
            SourceType.NETRONLINE,
            custom_url or "https://publicrecords.netronline.com/",
        )
        ctx.sources = await resolver.resolve(ctx.state, ctx.county, start_url=custom_url or None)
        duration = int((time.monotonic() - t0) * 1000)
        links_found = sum(
            1
            for u in [
                ctx.sources.assessor_url,
                ctx.sources.recorder_url,
                ctx.sources.treasurer_url,
                ctx.sources.gis_url,
            ]
            if u
        )
        await self.run_logger.source_completed(
            SourceType.NETRONLINE, records_found=links_found, duration_ms=duration
        )
        await self.run_logger.node_completed("NETRResolverNode", records_found=links_found)

    async def _node_platform(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
    ) -> None:
        assessor_url = ctx.sources.assessor_url if ctx.sources else ""
        recorder_url = ctx.sources.recorder_url if ctx.sources else ""
        await self.run_logger.node_started("PlatformDetectorNode")
        await self.run_logger.node_completed(
            "PlatformDetectorNode",
            assessor_platform=_detect_platform(assessor_url, get_assessor_platform_rules()),
            recorder_platform=_detect_platform(recorder_url, get_recorder_platform_rules()),
        )

    async def _node_assessor(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
    ) -> None:
        if not driver:
            await self.run_logger.node_started("AssessorNode")
            await self.run_logger.source_skipped(SourceType.ASSESSOR, "Browser not started")
            await self.run_logger.node_completed("AssessorNode", detail="Skipped — browser not started")
            return
        url = self._resolve_portal_url(ctx, data, "assessor_url")
        if not url:
            await self.run_logger.node_started("AssessorNode")
            await self.run_logger.source_skipped(SourceType.ASSESSOR, "No assessor URL — connect NETR or set URL on node")
            await self.run_logger.node_completed("AssessorNode", detail="Skipped — no assessor URL")
            return
        if ctx.query_type == QueryType.BOOK_PAGE:
            await self.run_logger.node_started("AssessorNode")
            await self.run_logger.source_skipped(
                SourceType.ASSESSOR, "Book/page search applies to Recorder node only"
            )
            await self.run_logger.node_completed("AssessorNode", detail="Skipped — book/page search")
            return
        notes = _data_str(data, "playwright_notes") or None
        if notes:
            driver.playwright_notes = notes

        search_qt = ctx.query_type
        search_qv = ctx.query_value
        if search_qt == QueryType.ADDRESS and ctx.address:
            search_qv = ctx.address
        elif search_qt == QueryType.OWNER and ctx.owner_name:
            search_qv = ctx.owner_name
        elif search_qt == QueryType.PARCEL and ctx.parcel:
            search_qv = ctx.parcel

        ctx.total_records += await self._search_assessor(
            driver, url, search_qt, search_qv, ctx.state, ctx.county, playwright_notes=notes
        )
        self._refresh_parcel(ctx)

    async def _node_recorder(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
    ) -> None:
        if not driver:
            await self.run_logger.node_started("RecorderNode")
            await self.run_logger.source_skipped(SourceType.RECORDER, "Browser not started")
            await self.run_logger.node_completed("RecorderNode", detail="Skipped — browser not started")
            return
        url = self._resolve_portal_url(ctx, data, "recorder_url")
        if ctx.state.upper() == "FL" and url:
            url = resolve_florida_recorder_url(url, ctx.county)
        if not url:
            await self.run_logger.node_started("RecorderNode")
            await self.run_logger.source_skipped(SourceType.RECORDER, "No recorder URL — connect NETR or set URL on node")
            await self.run_logger.node_completed("RecorderNode", detail="Skipped — no recorder URL")
            return
        if ctx.query_type == QueryType.BOOK_PAGE:
            book_page_parts = parse_book_page(ctx.query_value, ctx.book_number, ctx.page_number)
            if not book_page_parts:
                await self.run_logger.source_skipped(
                    SourceType.RECORDER, "Book/page search requires book number and page number in Input node"
                )
                return
            ctx.book_number, ctx.page_number = book_page_parts

        recorder_qt = ctx.query_type
        recorder_qv = ctx.query_value
        self._refresh_parcel(ctx)

        if ctx.book_number and ctx.page_number:
            recorder_qt = QueryType.BOOK_PAGE
            recorder_qv = format_book_page_label(ctx.book_number, ctx.page_number)
            await self.run_logger.log(
                "node_step",
                node="RecorderNode",
                message=f"Using book {ctx.book_number} / page {ctx.page_number} from Input for recorder search",
            )
        elif recorder_qt == QueryType.ADDRESS:
            # County recorders search by owner/party name, parcel, or book/page — not street address.
            if ctx.owner_name:
                recorder_qt = QueryType.OWNER
                recorder_qv = ctx.owner_name
                await self.run_logger.log(
                    "node_step",
                    node="RecorderNode",
                    message=f"Using owner '{ctx.owner_name}' (resolved from assessor address search) for recorder records search",
                )
            elif ctx.parcel:
                recorder_qt = QueryType.PARCEL
                recorder_qv = ctx.parcel
                await self.run_logger.log(
                    "node_step",
                    node="RecorderNode",
                    message=f"Using parcel '{ctx.parcel}' (resolved from assessor address search) for recorder records search",
                )
            else:
                await self.run_logger.node_started("RecorderNode")
                await self.run_logger.source_skipped(
                    SourceType.RECORDER,
                    "Address input search requires owner name, parcel, or book/page for recorder lookup",
                )
                await self.run_logger.node_completed(
                    "RecorderNode", detail="Skipped — no owner, parcel, or book/page resolved"
                )
                return

        notes = _data_str(data, "playwright_notes") or None
        if notes:
            driver.playwright_notes = notes
        ctx.total_records += await self._search_recorder(
            driver,
            url,
            recorder_qt,
            recorder_qv,
            ctx.state,
            ctx.county,
            playwright_notes=notes,
            book_number=ctx.book_number,
            page_number=ctx.page_number,
            available_values={
                "book": ctx.book_number or "",
                "page": ctx.page_number or "",
                "owner": ctx.owner_name or "",
                "parcel": ctx.parcel or "",
                "address": ctx.address or "",
                "query_value": recorder_qv or ctx.query_value or "",
            },
        )

    async def _node_gis(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
    ) -> None:
        if not driver:
            await self.run_logger.source_skipped(SourceType.GIS, "Browser not started")
            return
        self._refresh_parcel(ctx)
        gis_url = _data_str(data, "url") or (ctx.sources.gis_url if ctx.sources else "")
        if not _data_str(data, "url") and ctx.county == "miami-dade" and ctx.parcel:
            gis_url = MIAMI_DADE_SEARCH_URL
        if not gis_url:
            await self.run_logger.source_skipped(SourceType.GIS, "No GIS URL")
            return
        if not ctx.parcel:
            await self.run_logger.source_skipped(SourceType.GIS, "No parcel ID resolved for GIS map")
            return
        notes = _data_str(data, "playwright_notes") or None
        if notes:
            driver.playwright_notes = notes
        await self._capture_gis(
            driver, gis_url, ctx.parcel, ctx.query_type, ctx.query_value, playwright_notes=notes
        )

    async def _node_tax(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
    ) -> None:
        if not driver:
            await self.run_logger.source_skipped(SourceType.TAX_RECORD, "Browser not started")
            return
        self._refresh_parcel(ctx)
        tax_url = _data_str(data, "url") or None
        # If no parcel was resolved from assessor, fall back to the raw query value
        # when the user searched by parcel — this lets Tax run standalone.
        if not ctx.parcel and ctx.query_type == QueryType.PARCEL and ctx.query_value:
            ctx.parcel = ctx.query_value
        if not ctx.parcel:
            await self.run_logger.source_skipped(
                SourceType.TAX_RECORD, "No parcel ID resolved for tax record lookup"
            )
            return
        if not tax_url and ctx.state.upper() != "FL":
            await self.run_logger.source_skipped(SourceType.TAX_RECORD, "Tax URL required for non-FL counties")
            return
        notes = _data_str(data, "playwright_notes") or None
        if notes:
            driver.playwright_notes = notes
        ctx.total_records += await self._search_tax_record(
            driver, ctx.state, ctx.county, ctx.parcel, ctx.owner_name,
            tax_url=tax_url, playwright_notes=notes,
            query_type=ctx.query_type, query_value=ctx.query_value,
        )

    async def _node_ai_agent(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
    ) -> None:
        config = {
            "agent_name": _data_str(data, "agent_name", default="OpenAI Agent"),
            "instructions": _data_str(data, "instructions"),
            "user_prompt": _data_str(data, "user_prompt"),
            "model": _data_str(data, "model", default="gpt-4o"),
            "temperature": data.get("temperature", 0.7),
            "max_tokens": data.get("max_tokens", 1000),
        }
        records = self.records_repo.list_by_run(self.run_id)
        documents = self.documents_repo.list_by_run(self.run_id)
        context_data = {
            "run_id": self.run_id,
            "state": ctx.state,
            "county": ctx.county,
            "query_value": ctx.query_value,
            "records": records,
            "documents": documents,
            "sources": ctx.sources.model_dump() if ctx.sources else {},
        }
        agent_name = config["agent_name"]
        await self.run_logger.node_started(
            "AIAgentNode", agent_name=agent_name, model=config.get("model"), canvas_id=canvas_id
        )
        await self.run_logger.log(
            "ai_agent_invoke",
            node="AIAgentNode",
            message="POST /runs/{id}/ai-agent/execute — check Network tab",
            canvas_id=canvas_id,
            config=config,
            context_data=context_data,
        )
        try:
            await wait_for_pending(self.run_id, canvas_id)
        except TimeoutError as exc:
            await self.run_logger.node_failed("AIAgentNode", str(exc))
        except ValueError as exc:
            await self.run_logger.node_failed("AIAgentNode", str(exc))

    async def _node_normalizer(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
    ) -> None:
        await self.run_logger.node_started("NormalizerNode")
        await self.run_logger.node_completed("NormalizerNode", detail="Records merged by run")

    async def _node_report(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
    ) -> None:
        await self.run_logger.node_started("ReportNode")
        try:
            builder = ReportBuilder()
            report = await builder.build_and_save(self.run_id)
            ctx.report_id = report.get("id")
            await self.run_logger.node_completed(
                "ReportNode",
                detail="PDF report generated",
                report_id=ctx.report_id,
            )
        except Exception as exc:
            await self.run_logger.node_failed("ReportNode", str(exc))
            raise

    async def _node_output(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
    ) -> None:
        await self.run_logger.node_started("OutputNode")
        await self.run_logger.node_completed("OutputNode", total_records=ctx.total_records)

    def _persist_assessor_chain_of_title(self, parcel: Any) -> int:
        chain = (parcel.raw_json or {}).get("chain_of_title") or []
        source_url = (parcel.raw_json or {}).get("source_url")
        saved = 0
        for entry in chain:
            if not isinstance(entry, dict):
                continue
            grantor = entry.get("grantor")
            grantee = entry.get("grantee")
            doc_type = entry.get("document_type") or "Sale"
            recording_date = entry.get("recording_date")
            sale_price = entry.get("sale_price")
            instrument_number = entry.get("instrument_number")
            if not any([grantor, grantee, recording_date, sale_price, instrument_number]):
                continue
            self.documents_repo.insert(
                self.run_id,
                {
                    "document_type": doc_type,
                    "recording_date": recording_date,
                    "grantor": grantor,
                    "grantee": grantee,
                    "book_page": entry.get("book_page"),
                    "instrument_number": entry.get("instrument_number"),
                    "source_url": source_url,
                    "ocr_json": {
                        "sale_price": sale_price,
                        "source": "assessor_sales",
                        "section": "sales_information",
                    },
                },
            )
            saved += 1
        return saved

    async def _search_assessor(
        self,
        base: BaseDriver,
        url: str,
        query_type: QueryType,
        query_value: str,
        state: str,
        county: str,
        playwright_notes: Optional[str] = None,
    ) -> int:
        t0 = time.monotonic()
        assessor = GilaAssessorDriver()
        assessor._page = base.page
        assessor._context = base.context
        assessor._browser = base._browser
        assessor._playwright = base._playwright
        assessor.screenshot_dir = base.screenshot_dir
        assessor.status_callback = base.status_callback
        assessor.playwright_notes = playwright_notes
        assessor.preview_run_id = base.preview_run_id
        assessor._browser_stream = base._browser_stream
        if playwright_notes:
            await self.run_logger.log("node_started", node="AssessorNode", message=f"Playwright notes: {playwright_notes[:120]}")

        try:
            await self.run_logger.node_started("AssessorNode", url=url)
            await self.run_logger.source_started(SourceType.ASSESSOR, url)
            parcels = await assessor.search(url, query_type, query_value, state=state, county=county)
            base._page = assessor.page
            base._browser_stream = assessor._browser_stream
            await assessor.save_browser_preview()
            count = 0
            for parcel in parcels:
                html_snippet = json.dumps(parcel.raw_json) if parcel.raw_json else ""
                try:
                    normalized = await self.normalizer.normalize("assessor", html_snippet, parcel)
                except Exception as norm_err:
                    logger.warning("Assessor normalization failed: %s, falling back to raw parcel", norm_err)
                    normalized = parcel

                leg_desc = (
                    getattr(normalized, "legal_description", None)
                    or getattr(normalized, "legal_desc", None)
                    or getattr(parcel, "legal_description", None)
                    or getattr(parcel, "legal_desc", None)
                )
                assessed_val = getattr(normalized, "assessed_value", None) or getattr(parcel, "assessed_value", None)
                apn = getattr(normalized, "apn", None) or getattr(parcel, "apn", None)
                owner = getattr(normalized, "owner_name", None) or getattr(parcel, "owner_name", None)
                addr = getattr(normalized, "property_address", None) or getattr(parcel, "property_address", None)

                self.records_repo.insert(
                    self.run_id,
                    {
                        "source": "assessor",
                        "apn": apn,
                        "owner_name": owner,
                        "property_address": addr,
                        "legal_description": leg_desc,
                        "assessed_value": assessed_val,
                        "raw_json": parcel.raw_json,
                    },
                )
                try:
                    self._persist_assessor_chain_of_title(parcel)
                except Exception as chain_err:
                    logger.warning("Failed to persist assessor chain of title: %s", chain_err)

                await self.run_logger.record_found(
                    SourceType.ASSESSOR,
                    apn=apn,
                    owner_name=owner,
                    property_address=addr,
                )
                count += 1
            duration = int((time.monotonic() - t0) * 1000)
            await self.run_logger.source_completed(SourceType.ASSESSOR, records_found=count, duration_ms=duration)
            await self.run_logger.node_completed("AssessorNode", records_found=count)
            return count
        except Exception as exc:
            await self.run_logger.node_failed("AssessorNode", str(exc))
            await self.run_logger.source_failed(SourceType.ASSESSOR, str(exc))
            await assessor.screenshot_on_failure("assessor_error")
            return 0

    async def _search_recorder(
        self,
        base: BaseDriver,
        url: str,
        query_type: QueryType,
        query_value: str,
        state: str,
        county: str,
        playwright_notes: Optional[str] = None,
        book_number: Optional[str] = None,
        page_number: Optional[str] = None,
        available_values: Optional[dict[str, str]] = None,
    ) -> int:
        t0 = time.monotonic()
        recorder = GilaRecorderDriver()
        recorder._page = base.page
        recorder._context = base.context
        recorder._browser = base._browser
        recorder._playwright = base._playwright
        recorder.screenshot_dir = base.screenshot_dir
        recorder.status_callback = base.status_callback
        recorder.playwright_notes = playwright_notes
        recorder.preview_run_id = base.preview_run_id
        recorder._browser_stream = base._browser_stream

        search_url = url
        if state.upper() == "FL":
            search_url = resolve_florida_recorder_url(url, county)

        try:
            await self.run_logger.node_started("RecorderNode", url=search_url)
            if playwright_notes:
                await self.run_logger.log(
                    "node_started",
                    node="RecorderNode",
                    message=f"Playwright notes: {playwright_notes[:120]}",
                )
            await self.run_logger.source_started(SourceType.RECORDER, search_url)
            documents = await recorder.search(
                search_url,
                query_type,
                query_value,
                book_number=book_number,
                page_number=page_number,
                available_values=available_values,
            )
            base._page = recorder._page
            base._browser_stream = recorder._browser_stream
            await base.stabilize_browser_session()
            await recorder.save_browser_preview()
            count = 0
            for doc in documents:
                orig_doc = doc
                if doc.screenshot_path and doc.screenshot_path.lower().endswith(".pdf"):
                    if not doc.ocr_json:
                        doc.ocr_json = {"download_path": doc.screenshot_path}
                elif doc.screenshot_path:
                    try:
                        extracted = await self.ocr.extract_document(doc.screenshot_path, doc.document_type)
                        if extracted and extracted.ocr_json and "error" not in extracted.ocr_json:
                            doc = extracted
                    except Exception as ocr_err:
                        logger.warning("Document OCR failed, keeping original: %s", ocr_err)
                normalized = await self.normalizer.normalize(
                    "recorder",
                    json.dumps(doc.ocr_json) if doc.ocr_json else query_value,
                    doc,
                )
                merged_ocr = {
                    **(getattr(orig_doc, "ocr_json", None) or {}),
                    **(getattr(doc, "ocr_json", None) or {}),
                    **(getattr(normalized, "ocr_json", None) or {}),
                }
                for key in (
                    "download_path",
                    "pdf_path",
                    "folder_name",
                    "pdf_file",
                    "image_path",
                    "book_number",
                    "page_number",
                    "clerk_file_number",
                    "legal_description",
                    "recording_date",
                ):
                    val = (
                        (orig_doc.ocr_json or {}).get(key)
                        if getattr(orig_doc, "ocr_json", None)
                        else None
                    ) or (
                        (doc.ocr_json or {}).get(key)
                        if getattr(doc, "ocr_json", None)
                        else None
                    )
                    if val:
                        merged_ocr[key] = val
                screenshot_path = (
                    getattr(orig_doc, "screenshot_path", None)
                    or getattr(doc, "screenshot_path", None)
                    or getattr(normalized, "screenshot_path", None)
                    or merged_ocr.get("download_path")
                )
                if screenshot_path and str(screenshot_path).lower().endswith(".pdf"):
                    merged_ocr.setdefault("download_path", screenshot_path)

                doc_type = (
                    getattr(normalized, "document_type", None)
                    or getattr(orig_doc, "document_type", None)
                    or getattr(doc, "document_type", None)
                )
                bk_pg = (
                    getattr(normalized, "book_page", None)
                    or getattr(orig_doc, "book_page", None)
                    or getattr(doc, "book_page", None)
                    or (f"{merged_ocr['book_number']}/{merged_ocr['page_number']}" if "book_number" in merged_ocr and "page_number" in merged_ocr else None)
                )
                inst_num = (
                    getattr(normalized, "instrument_number", None)
                    or getattr(orig_doc, "instrument_number", None)
                    or getattr(doc, "instrument_number", None)
                    or merged_ocr.get("clerk_file_number")
                )
                grantor_name = (
                    getattr(normalized, "grantor", None)
                    or getattr(orig_doc, "grantor", None)
                    or getattr(doc, "grantor", None)
                )
                grantee_name = (
                    getattr(normalized, "grantee", None)
                    or getattr(orig_doc, "grantee", None)
                    or getattr(doc, "grantee", None)
                )
                rec_date = (
                    normalized.recording_date.isoformat()
                    if getattr(normalized, "recording_date", None)
                    else (
                        orig_doc.recording_date.isoformat()
                        if getattr(orig_doc, "recording_date", None)
                        else None
                    )
                )
                self.documents_repo.insert(
                    self.run_id,
                    {
                        "document_type": doc_type,
                        "recording_date": rec_date,
                        "book_page": bk_pg,
                        "instrument_number": inst_num,
                        "grantor": grantor_name,
                        "grantee": grantee_name,
                        "source_url": getattr(normalized, "source_url", None) or getattr(orig_doc, "source_url", None) or getattr(doc, "source_url", None) or url,
                        "screenshot_path": screenshot_path,
                        "ocr_json": merged_ocr,
                    },
                )
                await self.run_logger.record_found(
                    SourceType.RECORDER,
                    document_type=normalized.document_type,
                    instrument_number=normalized.instrument_number,
                    book_page=normalized.book_page,
                    grantor=normalized.grantor,
                    grantee=normalized.grantee,
                    screenshot_path=normalized.screenshot_path or getattr(doc, "screenshot_path", None),
                )
                count += 1
            duration = int((time.monotonic() - t0) * 1000)
            await self.run_logger.source_completed(SourceType.RECORDER, records_found=count, duration_ms=duration)
            await self.run_logger.node_completed("RecorderNode", records_found=count)
            return count
        except Exception as exc:
            await self.run_logger.node_failed("RecorderNode", str(exc))
            await self.run_logger.source_failed(SourceType.RECORDER, str(exc))
            await recorder.screenshot_on_failure("recorder_error")
            return 0

    async def _search_tax_record(
        self,
        base: BaseDriver,
        state: str,
        county: str,
        apn: str,
        owner_name: Optional[str],
        tax_url: Optional[str] = None,
        playwright_notes: Optional[str] = None,
        query_type: Optional[QueryType] = None,
        query_value: Optional[str] = None,
    ) -> int:
        t0 = time.monotonic()
        tax = FloridaTaxDriver(screenshot_dir=base.screenshot_dir)
        tax._page = base.page
        tax._context = base.context
        tax._browser = base._browser
        tax._playwright = base._playwright
        tax.status_callback = base.status_callback
        tax.playwright_notes = playwright_notes
        tax.preview_run_id = base.preview_run_id
        tax._browser_stream = base._browser_stream

        detail_url = tax_url or resolve_florida_tax_url(county, apn)
        try:
            if not await base.ensure_browser_ready():
                await self.run_logger.node_failed(
                    "TaxNode", "Browser is not available for tax lookup"
                )
                await self.run_logger.source_failed(
                    SourceType.TAX_RECORD, "Browser is not available for tax lookup"
                )
                return 0
            await base.stabilize_browser_session()
            await self.run_logger.node_started("TaxNode", url=detail_url)
            await self.run_logger.source_started(SourceType.TAX_RECORD, detail_url)
            # Pass the portal_url so the driver navigates to the correct URL.
            # Also pass query_type/query_value so the search portal path can search by
            # the right field (parcel, owner, etc.) instead of always defaulting to APN.
            record = await tax.fetch_tax_record(
                county, apn, owner_name,
                portal_url=tax_url or None,
                query_type=query_type,
                query_value=query_value,
            )
            await tax.save_browser_preview()
            if not record:
                await self.run_logger.source_failed(
                    SourceType.TAX_RECORD, "Could not capture tax bill details from county tax site."
                )
                return 0

            self.records_repo.insert(
                self.run_id,
                {
                    "source": "tax_record",
                    "apn": apn,
                    "owner_name": record.owner_name or owner_name,
                    "property_address": record.property_address,
                    "assessed_value": record.amount_due,
                    "raw_json": record.raw_json,
                },
            )
            saved_pdfs: set[str] = set()
            tax_doc_candidates: list[tuple[str, str]] = []
            for bill_doc in record.raw_json.get("downloaded_bills") or []:
                pdf_path = bill_doc.get("pdf_path")
                if pdf_path and bill_doc.get("pdf_downloaded", True):
                    tax_doc_candidates.append((bill_doc.get("bill") or "Annual Bill", pdf_path))
            for bill in record.raw_json.get("last_two_bills") or []:
                pdf_path = bill.get("pdf_path")
                if pdf_path and bill.get("pdf_downloaded", True):
                    bill_name = (bill.get("bill_summary") or {}).get("bill") or bill.get("bill_title") or "Annual Bill"
                    tax_doc_candidates.append((bill_name, pdf_path))

            tax_bill_dir = Path("screenshots") / "tax_bills" / self.run_id
            if tax_bill_dir.is_dir():
                for pdf in sorted(tax_bill_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
                    tax_doc_candidates.append((pdf.stem.replace("_", " "), str(pdf.resolve())))

            for bill_name, pdf_path in tax_doc_candidates:
                if pdf_path in saved_pdfs or not is_valid_pdf(pdf_path):
                    continue
                saved_pdfs.add(pdf_path)
                self.documents_repo.insert(
                    self.run_id,
                    {
                        "document_type": "tax_bill",
                        "source_url": record.source_url,
                        "screenshot_path": pdf_path,
                        "ocr_json": {
                            "download_path": pdf_path,
                            "source": "tax_bill",
                            "bill": bill_name,
                        },
                    },
                )
                await self.run_logger.record_found(
                    SourceType.TAX_RECORD,
                    apn=apn,
                    message=f"Downloaded tax bill PDF: {bill_name}",
                )
            await self.run_logger.record_found(
                SourceType.TAX_RECORD,
                apn=apn,
                tax_account=record.tax_account,
                tax_year=record.tax_year,
            )
            duration = int((time.monotonic() - t0) * 1000)
            await self.run_logger.source_completed(
                SourceType.TAX_RECORD, records_found=1, duration_ms=duration
            )
            await self.run_logger.node_completed("TaxNode", records_found=1)
            return 1
        except Exception as exc:
            await self.run_logger.node_failed("TaxNode", str(exc))
            await self.run_logger.source_failed(SourceType.TAX_RECORD, str(exc))
            await tax.screenshot_on_failure("tax_record_error")
            return 0

    async def _capture_gis(
        self,
        base: BaseDriver,
        url: str,
        parcel: str,
        query_type: QueryType,
        query_value: str,
        playwright_notes: Optional[str] = None,
    ) -> bool:
        t0 = time.monotonic()
        gis = GilaGisDriver(screenshot_dir=base.screenshot_dir)
        gis._page = base.page
        gis._context = base.context
        gis._browser = base._browser
        gis._playwright = base._playwright
        gis.status_callback = base.status_callback
        gis.playwright_notes = playwright_notes
        try:
            if not await gis.ensure_browser_ready():
                await self.run_logger.node_failed("GISNode", "Browser is not available for GIS map capture")
                await self.run_logger.source_failed(SourceType.GIS, "Browser is not available for GIS map capture")
                return False
            await self.run_logger.node_started("GISNode", url=url)
            await self.run_logger.source_started(SourceType.GIS, url)
            path = await gis.capture_parcel_map(url, parcel, query_type, query_value)
            await gis.save_browser_preview()
            base._page = gis._page
            await base.stabilize_browser_session()
            duration = int((time.monotonic() - t0) * 1000)
            await self.run_logger.source_completed(
                SourceType.GIS, records_found=1 if path else 0, duration_ms=duration, screenshot_path=path
            )
            await self.run_logger.node_completed("GISNode", records_found=1 if path else 0)
            return bool(path)
        except Exception as exc:
            await self.run_logger.node_failed("GISNode", str(exc))
            await self.run_logger.source_failed(SourceType.GIS, str(exc))
            return False
