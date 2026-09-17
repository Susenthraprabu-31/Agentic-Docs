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
from app.config.florida_portals import resolve_florida_recorder_url, resolve_florida_tax_url, MIAMI_DADE_SEARCH_URL
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
    """Prefer Input node canvas data over top-level API fields."""
    for canvas_id in parsed.order:
        node = parsed.node_map.get(canvas_id, {})
        if node.get("node_id") != "input":
            continue
        data = node.get("data") or {}
        if data.get("state"):
            state = str(data["state"]).strip().upper()
        if data.get("county"):
            county = str(data["county"]).strip().lower()
        if data.get("query_type"):
            try:
                query_type = QueryType(str(data["query_type"]).strip().lower())
            except ValueError:
                pass
        if data.get("query_value"):
            query_value = str(data["query_value"]).strip()
        if data.get("book_number"):
            book_number = str(data["book_number"]).strip()
        else:
            book_number = None
        if data.get("page_number"):
            page_number = str(data["page_number"]).strip()
        else:
            page_number = None
        if query_type == QueryType.BOOK_PAGE:
            book_page_parts = parse_book_page(query_value, book_number, page_number)
            if book_page_parts:
                book_number, page_number = book_page_parts
                query_value = format_book_page_label(book_number, page_number)
        break
    return state, county, query_type, query_value


def _apply_input_data_to_ctx(data: dict[str, Any], ctx: RunContext) -> None:
    if data.get("state"):
        ctx.state = str(data["state"]).strip().upper()
    if data.get("county"):
        ctx.county = str(data["county"]).strip().lower()
    if data.get("query_type"):
        try:
            ctx.query_type = QueryType(str(data["query_type"]).strip().lower())
        except ValueError:
            pass
    if data.get("query_value"):
        ctx.query_value = str(data["query_value"]).strip()
    if data.get("book_number"):
        ctx.book_number = str(data["book_number"]).strip()
    if data.get("page_number"):
        ctx.page_number = str(data["page_number"]).strip()
    if ctx.query_type == QueryType.BOOK_PAGE:
        book_page_parts = parse_book_page(ctx.query_value, ctx.book_number, ctx.page_number)
        if book_page_parts:
            ctx.book_number, ctx.page_number = book_page_parts
            ctx.query_value = format_book_page_label(ctx.book_number, ctx.page_number)
    elif ctx.query_type == QueryType.PARCEL and ctx.query_value:
        ctx.parcel = ctx.query_value


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
                parcel=query_value if query_type == QueryType.PARCEL else None,
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
            await self.run_logger.source_skipped(SourceType.ASSESSOR, "Browser not started")
            return
        url = _data_str(data, "url") or (ctx.sources.assessor_url if ctx.sources else "")
        if not url:
            await self.run_logger.source_skipped(SourceType.ASSESSOR, "No assessor URL — connect NETR or set URL on node")
            return
        if ctx.query_type == QueryType.BOOK_PAGE:
            await self.run_logger.source_skipped(
                SourceType.ASSESSOR, "Book/page search applies to Recorder node only"
            )
            return
        notes = _data_str(data, "playwright_notes") or None
        if notes:
            driver.playwright_notes = notes
        ctx.total_records += await self._search_assessor(
            driver, url, ctx.query_type, ctx.query_value, ctx.state, ctx.county, playwright_notes=notes
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
            await self.run_logger.source_skipped(SourceType.RECORDER, "Browser not started")
            return
        url = _data_str(data, "url") or (ctx.sources.recorder_url if ctx.sources else "")
        if not url:
            await self.run_logger.source_skipped(SourceType.RECORDER, "No recorder URL — connect NETR or set URL on node")
            return
        if ctx.query_type == QueryType.BOOK_PAGE:
            book_page_parts = parse_book_page(ctx.query_value, ctx.book_number, ctx.page_number)
            if not book_page_parts:
                await self.run_logger.source_skipped(
                    SourceType.RECORDER, "Book/page search requires book number and page number in Input node"
                )
                return
            ctx.book_number, ctx.page_number = book_page_parts
        notes = _data_str(data, "playwright_notes") or None
        if notes:
            driver.playwright_notes = notes
        ctx.total_records += await self._search_recorder(
            driver,
            url,
            ctx.query_type,
            ctx.query_value,
            ctx.state,
            ctx.county,
            playwright_notes=notes,
            book_number=ctx.book_number,
            page_number=ctx.page_number,
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
                normalized = await self.normalizer.normalize("assessor", html_snippet, parcel)
                self.records_repo.insert(
                    self.run_id,
                    {
                        "source": "assessor",
                        "apn": normalized.apn or parcel.apn,
                        "owner_name": normalized.owner_name or parcel.owner_name,
                        "property_address": normalized.property_address or parcel.property_address,
                        "legal_description": normalized.legal_description or parcel.legal_description,
                        "assessed_value": normalized.assessed_value,
                        "raw_json": parcel.raw_json,
                    },
                )
                await self.run_logger.record_found(
                    SourceType.ASSESSOR,
                    apn=normalized.apn or parcel.apn,
                    owner_name=normalized.owner_name or parcel.owner_name,
                    property_address=normalized.property_address or parcel.property_address,
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
            )
            base._page = recorder.page
            base._browser_stream = recorder._browser_stream
            await recorder.save_browser_preview()
            count = 0
            for doc in documents:
                if doc.screenshot_path and doc.screenshot_path.lower().endswith(".pdf"):
                    if not doc.ocr_json:
                        doc.ocr_json = {"download_path": doc.screenshot_path}
                elif doc.screenshot_path:
                    doc = await self.ocr.extract_document(doc.screenshot_path, doc.document_type)
                normalized = await self.normalizer.normalize(
                    "recorder",
                    json.dumps(doc.ocr_json) if doc.ocr_json else query_value,
                    doc,
                )
                self.documents_repo.insert(
                    self.run_id,
                    {
                        "document_type": normalized.document_type,
                        "recording_date": normalized.recording_date.isoformat() if normalized.recording_date else None,
                        "book_page": normalized.book_page,
                        "instrument_number": normalized.instrument_number,
                        "grantor": normalized.grantor,
                        "grantee": normalized.grantee,
                        "source_url": normalized.source_url or getattr(doc, "source_url", None) or url,
                        "screenshot_path": normalized.screenshot_path or getattr(doc, "screenshot_path", None),
                        "ocr_json": normalized.ocr_json,
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
            await self.run_logger.node_started("GISNode", url=url)
            await self.run_logger.source_started(SourceType.GIS, url)
            path = await gis.capture_parcel_map(url, parcel, query_type, query_value)
            await gis.save_browser_preview()
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
