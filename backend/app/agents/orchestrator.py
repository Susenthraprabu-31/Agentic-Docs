import json
import logging
import time
from dataclasses import dataclass, field
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
    build_miami_dade_property_search_url,
    extract_miami_dade_folio_from_url,
    is_miami_dade_gis,
    normalize_florida_parcel,
    normalize_miami_dade_property_search_url,
    resolve_florida_county_sources,
    resolve_florida_assessor_url,
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
from app.storage.document_asset_storage import DocumentAssetStorage
from app.config.platform_rules import get_assessor_platform_rules, get_recorder_platform_rules
from app.extraction.assessor_book_page import (
    enrich_raw_json_with_latest_book_page,
    extract_all_book_pages,
    extract_latest_book_page,
)
from app.extraction.book_page import format_book_page_label, parse_book_page
from app.extraction.miami_dade_name_searches import (
    collect_recorder_party_names_for_search,
    dedupe_party_names,
    expand_name_search_variations,
    build_name_searcher_report_entries,
)
from app.extraction.schemas import CountySources, QueryType, RunStatus, SourceType
from app.agents.ai_agent_coordinator import complete_pending, fail_pending, wait_for_pending
from app.pipeline.graph_executor import ParsedPipelineGraph, get_input_node_data, requires_browser, resolve_pipeline_graph
from app.pipeline.run_normalizer import normalize_run_data
from app.queue.run_cancellation import RunCancelledError, check_run_cancelled, clear_run_cancelled
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
    "portal_gate": "PortalGateNode",
    "assessor": "AssessorNode",
    "recorder": "RecorderNode",
    "name_searcher": "NameSearcherNode",
    "gis": "GISNode",
    "tax": "TaxNode",
    "ai_agent": "AIAgentNode",
    "chatbot": "ChatbotNode",
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
    book_page_source: Optional[str] = None
    sources: Optional[CountySources] = None
    report_id: Optional[str] = None
    node_results: dict[str, Any] = field(default_factory=dict)
    last_completed_node_result: Any = None
    last_completed_node_id: Optional[str] = None
    automation_mode: str = "legacy"
    search_limit: Optional[int] = None
    search_scope: str = "full"


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

        # Prefer explicit address query type, then address when book/page are incomplete.
        if raw_qtype == "address" and address_val and not owner_val and not parcel_val:
            query_type = QueryType.ADDRESS
            query_value = address_val
        elif address_val and not owner_val and not parcel_val and not (book_val and page_val):
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

    raw_limit = data.get("searchLimit", data.get("search_limit"))
    if raw_limit is not None:
        try:
            limit_val = int(raw_limit)
            ctx.search_limit = limit_val if limit_val > 0 else None
        except (TypeError, ValueError):
            ctx.search_limit = None

    raw_scope = _data_str(data, "searchScope", "search_scope", default="full").lower()
    ctx.search_scope = raw_scope if raw_scope in ("current", "full") else "full"

    raw_qtype = _data_str(data, "query_type", "queryType").lower()
    node_qtype: Optional[QueryType] = None
    if raw_qtype:
        try:
            node_qtype = QueryType(raw_qtype)
        except ValueError:
            pass

    raw_qval = _data_str(data, "query_value", "queryValue")

    if raw_qtype == "address" and address_val and not owner_val and not parcel_val:
        ctx.query_type = QueryType.ADDRESS
        ctx.query_value = address_val
    elif address_val and not owner_val and not parcel_val and not (book_val and page_val):
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
            ctx.book_page_source = "input"
            ctx.query_value = format_book_page_label(ctx.book_number, ctx.page_number)
    elif book_val and page_val:
        ctx.book_page_source = "input"
    elif ctx.query_type == QueryType.PARCEL and ctx.query_value:
        ctx.parcel = ctx.query_value
    elif ctx.query_type == QueryType.ADDRESS and ctx.query_value:
        ctx.address = ctx.query_value
    elif ctx.query_type == QueryType.OWNER and ctx.query_value:
        ctx.owner_name = ctx.query_value

    from app.config.settings import get_settings
    default_mode = getattr(get_settings(), "automation_mode", "legacy")
    ctx.automation_mode = _data_str(data, "automation_mode", "automationMode", default=default_mode).lower()


class Orchestrator:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.runs_repo = RunsRepository()
        self.records_repo = RecordsRepository()
        self.documents_repo = DocumentsRepository()
        self.run_logger = RunLogger(run_id)
        self.normalizer = ExtractionNormalizer()
        self.ocr = DocumentOcrService()
        self.document_storage = DocumentAssetStorage()
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
        input_data = get_input_node_data(pipeline_graph)
        raw_scope = _data_str(input_data, "searchScope", "search_scope", default="full").lower()
        plan["search_scope"] = raw_scope if raw_scope in ("current", "full") else "full"
        raw_limit = input_data.get("searchLimit", input_data.get("search_limit"))
        if raw_limit is not None:
            try:
                limit_val = int(raw_limit)
                if limit_val > 0:
                    plan["search_limit"] = limit_val
            except (TypeError, ValueError):
                pass
        self.runs_repo.update_run(self.run_id, plan_json=plan)

        driver: Optional[NetronlineDriver] = None
        resolver: Optional[CountyResolver] = None
        needs_browser = requires_browser(parsed.step_node_ids)

        try:
            if needs_browser:
                driver = NetronlineDriver(screenshot_dir=SCREENSHOTS_DIR)

                async def _status(msg: str) -> None:
                    lower = msg.lower()
                    needs_human = any(
                        token in lower
                        for token in (
                            "cloudflare",
                            "verify you are human",
                            "captcha",
                            "human verification",
                            "complete the check",
                            "you have been blocked",
                        )
                    )
                    if needs_human:
                        await self.run_logger.log("human_action_required", message=msg)
                    else:
                        await self.run_logger.log("node_step", message=msg)

                driver.status_callback = _status
                driver.preview_run_id = self.run_id
                await driver.start()
                await driver.start_live_stream(self.run_id)
                await driver.save_browser_preview()
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

            input_data = get_input_node_data(pipeline_graph)
            if input_data:
                _apply_input_data_to_ctx(input_data, ctx)

            for canvas_id in parsed.order:
                check_run_cancelled(self.run_id)
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
                await self._dispatch_node(
                    node_id,
                    data,
                    ctx,
                    driver,
                    resolver,
                    canvas_id=canvas_id,
                    pipeline_graph=pipeline_graph,
                    parsed=parsed,
                )

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

        except RunCancelledError as exc:
            logger.info("Run %s cancelled by user", self.run_id)
            self.runs_repo.update_run(
                self.run_id,
                status=RunStatus.CANCELLED.value,
                error_message=str(exc),
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.run_logger.log("run_cancelled", message=str(exc))
            return {
                "run_id": self.run_id,
                "total_records": 0,
                "cancelled": True,
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
            clear_run_cancelled(self.run_id)
            if driver:
                unregister_driver(self.run_id)
                await driver.stop()

    async def _log_node_skipped(self, node_id: str, reason: str) -> None:
        event = NODE_EVENT_NAMES.get(node_id, node_id)
        await self.run_logger.log("node_completed", node=event, message=f"Skipped — {reason}")

    def _get_assessor_record(self) -> Optional[dict[str, Any]]:
        records = self.records_repo.list_by_run(self.run_id)
        return next(
            (r for r in records if r.get("source") == "assessor"),
            records[0] if records else None,
        )

    def _refresh_parcel(self, ctx: RunContext) -> None:
        if ctx.parcel:
            return
        assessor_record = self._get_assessor_record()
        if assessor_record:
            ctx.parcel = assessor_record.get("apn")
            ctx.owner_name = assessor_record.get("owner_name")

    def _refresh_book_page_from_assessor(self, ctx: RunContext) -> bool:
        """Populate book/page from assessor sales info when Input did not provide them."""
        if ctx.book_number and ctx.page_number:
            return False
        assessor_record = self._get_assessor_record()
        if not assessor_record:
            return False
        result = extract_latest_book_page(assessor_record)
        if not result:
            return False
        ctx.book_number, ctx.page_number, _ = result
        ctx.book_page_source = "assessor"
        return True

    def _get_assessor_sales_book_pages(
        self,
        ctx: RunContext,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        """Return assessor sales book/page pairs for queued recorder lookup."""
        if ctx.book_page_source == "input" and ctx.book_number and ctx.page_number:
            return []
        assessor_record = self._get_assessor_record()
        if not assessor_record:
            return []
        if ctx.search_scope == "current":
            latest = extract_latest_book_page(assessor_record)
            if not latest:
                return []
            book, page, entry = latest
            return [(book, page, entry)]
        return extract_all_book_pages(assessor_record)

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
            return self._normalize_portal_url(source_attr, explicit)
        if ctx.sources:
            url = getattr(ctx.sources, source_attr, None)
            if url:
                return self._normalize_portal_url(source_attr, str(url))
        if ctx.state.upper() == "FL":
            fallback = resolve_florida_county_sources(ctx.county, self._parcel_for_sources(ctx))
            url = getattr(fallback, source_attr, None)
            if url:
                normalized = self._normalize_portal_url(source_attr, str(url))
                if ctx.sources:
                    setattr(ctx.sources, source_attr, normalized)
                else:
                    ctx.sources = fallback
                    setattr(ctx.sources, source_attr, normalized)
                return normalized
        return ""

    def _normalize_portal_url(self, source_attr: str, url: str) -> str:
        if source_attr in ("assessor_url", "gis_url"):
            url = normalize_miami_dade_property_search_url(url)
            if source_attr == "assessor_url" and self._is_florida_assessor_portal(url):
                url = resolve_florida_assessor_url(url)
        return url

    @staticmethod
    def _is_florida_assessor_portal(url: str) -> bool:
        lower = url.lower()
        return lower.startswith("http") and (
            "floridapa.com" in lower
            or "miamidade.gov" in lower
            or "miamidadepa.gov" in lower
            or "ocpafl.org" in lower
            or "schneidercorp.com" in lower
        )

    def _normalize_document_row(self, doc: dict[str, Any]) -> dict[str, Any]:
        row = dict(doc)
        ocr = row.get("ocr_json")
        if isinstance(ocr, str):
            try:
                row["ocr_json"] = json.loads(ocr)
            except Exception:
                row["ocr_json"] = {}
        elif not isinstance(ocr, dict):
            row["ocr_json"] = {}
        return row

    def _record_node_result(self, ctx: RunContext, node_id: str, canvas_id: str, result: Any) -> None:
        if canvas_id:
            ctx.node_results[canvas_id] = result
        ctx.node_results[node_id] = result
        ctx.last_completed_node_result = result
        ctx.last_completed_node_id = node_id
        try:
            run_row = self.runs_repo.get_run(self.run_id) or {}
            plan = run_row.get("plan_json") or {}
            if isinstance(plan, dict):
                self.runs_repo.update_run(
                    self.run_id,
                    plan_json={**plan, "node_results": dict(ctx.node_results)},
                )
        except Exception as exc:
            logger.warning("Could not persist node_results for run %s: %s", self.run_id, exc)

    async def _dispatch_node(
        self,
        node_id: str,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
        pipeline_graph: Optional[dict[str, Any]] = None,
        parsed: Optional[ParsedPipelineGraph] = None,
    ) -> None:
        handlers = {
            "input": self._node_input,
            "netr": self._node_netr,
            "platform": self._node_platform,
            "portal_gate": self._node_portal_gate,
            "assessor": self._node_assessor,
            "recorder": self._node_recorder,
            "name_searcher": self._node_name_searcher,
            "gis": self._node_gis,
            "tax": self._node_tax,
            "normalizer": self._node_normalizer,
            "report": self._node_report,
            "output": self._node_output,
        }
        if node_id in ("ai_agent", "chatbot"):
            await self._node_ai_agent(
                data,
                ctx,
                driver,
                resolver,
                canvas_id=canvas_id,
                pipeline_graph=pipeline_graph,
                parsed=parsed,
                node_id=node_id,
            )
            return
        handler = handlers.get(node_id)
        if not handler:
            await self.run_logger.log("node_completed", node=node_id, message=f"Unknown node type: {node_id}")
            return
        await handler(data, ctx, driver, resolver, canvas_id=canvas_id)

    async def _node_input(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
    ) -> None:
        await self.run_logger.node_started("InputNode")
        _apply_input_data_to_ctx(data, ctx)
        input_result = {
            "state": ctx.state,
            "county": ctx.county,
            "query_type": ctx.query_type.value,
            "query_value": ctx.query_value,
            "address": ctx.address,
            "owner_name": ctx.owner_name,
            "parcel": ctx.parcel,
            "book_number": ctx.book_number,
            "page_number": ctx.page_number,
            "search_scope": ctx.search_scope,
            "search_limit": ctx.search_limit,
        }
        self._record_node_result(ctx, "input", canvas_id, input_result)
        await self.run_logger.node_completed(
            "InputNode",
            state=ctx.state,
            county=ctx.county,
            query_type=ctx.query_type.value,
            query_value=ctx.query_value,
            address=ctx.address,
            owner_name=ctx.owner_name,
            parcel=ctx.parcel,
            result=input_result,
        )

    def _known_florida_county_sources(self, ctx: RunContext) -> Optional[CountySources]:
        """Skip slow NETR scraping when Florida portal URLs are already known."""
        if ctx.state.upper() != "FL":
            return None
        sources = resolve_florida_county_sources(ctx.county, self._parcel_for_sources(ctx))
        if sources.assessor_url:
            return sources
        return None

    async def _node_netr(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
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

        if not custom_url:
            known_sources = self._known_florida_county_sources(ctx)
            if known_sources:
                ctx.sources = known_sources
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
                netr_result = {
                    "links_found": links_found,
                    "assessor_url": ctx.sources.assessor_url,
                    "recorder_url": ctx.sources.recorder_url,
                    "tax_url": ctx.sources.treasurer_url,
                    "gis_url": ctx.sources.gis_url,
                    "skipped_netr_scrape": True,
                }
                self._record_node_result(ctx, "netr", canvas_id, netr_result)
                await self.run_logger.log(
                    "node_step",
                    node="NETRResolverNode",
                    message=(
                        f"Using known {ctx.county.title()} FL portal URLs "
                        "(skipped NETR browser scrape)"
                    ),
                )
                await self.run_logger.source_completed(
                    SourceType.NETRONLINE, records_found=links_found, duration_ms=duration
                )
                await self.run_logger.node_completed(
                    "NETRResolverNode", records_found=links_found, result=netr_result
                )
                return

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
        netr_result = {
            "links_found": links_found,
            "assessor_url": getattr(ctx.sources, "assessor_url", None) if ctx.sources else None,
            "recorder_url": getattr(ctx.sources, "recorder_url", None) if ctx.sources else None,
            "tax_url": getattr(ctx.sources, "tax_url", None) if ctx.sources else None,
            "gis_url": getattr(ctx.sources, "gis_url", None) if ctx.sources else None,
        }
        self._record_node_result(ctx, "netr", canvas_id, netr_result)
        await self.run_logger.source_completed(
            SourceType.NETRONLINE, records_found=links_found, duration_ms=duration
        )
        await self.run_logger.node_completed("NETRResolverNode", records_found=links_found, result=netr_result)

    async def _node_platform(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
    ) -> None:
        assessor_url = ctx.sources.assessor_url if ctx.sources else ""
        recorder_url = ctx.sources.recorder_url if ctx.sources else ""
        await self.run_logger.node_started("PlatformDetectorNode")
        assessor_p = _detect_platform(assessor_url, get_assessor_platform_rules())
        recorder_p = _detect_platform(recorder_url, get_recorder_platform_rules())
        platform_result = {
            "assessor_platform": assessor_p,
            "recorder_platform": recorder_p,
        }
        self._record_node_result(ctx, "platform", canvas_id, platform_result)
        await self.run_logger.node_completed(
            "PlatformDetectorNode",
            assessor_platform=assessor_p,
            recorder_platform=recorder_p,
            result=platform_result,
        )

    async def _node_portal_gate(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
    ) -> None:
        """Open county portal and wait for Cloudflare / human verification before scraping."""
        from app.config.schneider_portals import (
            is_schneider_portal,
            is_schneider_search_url,
            normalize_schneider_search_url,
            schneider_warmup_url,
        )
        from app.config.settings import get_settings
        from app.drivers.browser_sessions import load_portal_cookies, save_portal_cookies

        await self.run_logger.node_started("PortalGateNode")
        if not driver:
            await self.run_logger.node_completed("PortalGateNode", detail="Skipped — browser not started")
            return

        portal = _data_str(data, "portalType", "portal_type", default="assessor").lower()
        source_map = {
            "assessor": "assessor_url",
            "recorder": "recorder_url",
            "tax": "treasurer_url",
            "gis": "gis_url",
        }
        source_attr = source_map.get(portal, "assessor_url")
        url = _data_str(data, "url")
        if not url:
            url = self._resolve_portal_url(ctx, data, source_attr)
        if not url and ctx.sources:
            url = getattr(ctx.sources, source_attr, None) or ""

        if not url:
            await self.run_logger.node_completed("PortalGateNode", detail="Skipped — no portal URL")
            return

        county_label = (ctx.county or "county").replace("-", " ").title()
        await driver._emit_status(f"Opening {county_label} portal — complete security check if shown...")
        await load_portal_cookies(driver, url)

        try:
            if is_schneider_portal(url):
                target = normalize_schneider_search_url(url)
                if is_schneider_search_url(url):
                    opened = await driver.safe_schneider_goto(
                        target,
                        wait_selector="#ctlBodyPane, .widgetLabel, input, form, table",
                    )
                    if not opened:
                        logger.warning("Portal gate could not open county search URL: %s", target)
                else:
                    warmup = schneider_warmup_url(url)
                    if warmup:
                        await driver.page.goto(warmup, wait_until="domcontentloaded", timeout=45_000)
                        await driver.polite_delay(2.0)
                    await driver.safe_schneider_goto(
                        target,
                        wait_selector="#ctlBodyPane, .widgetLabel, input, form, table",
                    )
            else:
                await driver.safe_goto(url, wait_selector="input, form, table")
            await driver.dismiss_schneider_terms()
        except Exception as exc:
            logger.warning("Portal gate navigation failed for %s: %s", url, exc)

        settings = get_settings()
        ready = await driver.wait_for_portal_access(
            max_wait=settings.playwright_cloudflare_wait_seconds,
            success_selector="#ctlBodyPane, .widgetLabel, input, form, table, mat-tab-group",
        )
        if ready:
            await save_portal_cookies(driver, url)
            gate_result = {"portal": portal, "url": url, "ready": True}
            self._record_node_result(ctx, "portal_gate", canvas_id, gate_result)
            await self.run_logger.node_completed(
                "PortalGateNode",
                detail="Portal access ready",
                result=gate_result,
            )
            return

        gate_result = {"portal": portal, "url": url, "ready": False}
        self._record_node_result(ctx, "portal_gate", canvas_id, gate_result)

        # Determine whether this is a hard block (Error 1020) vs a solvable challenge
        is_hard_block = await driver.is_cloudflare_hard_block()
        is_schneider = any(h in url.lower() for h in ("schneidercorp.com", "qpublic.net"))

        if is_hard_block and is_schneider:
            block_msg = (
                "⛔ ACCESS DENIED — Cloudflare has permanently blocked this server's IP address "
                "from schneidercorp.com / qPublic portals (Error 1020 — 'Sorry, you have been blocked'). "
                "This is NOT a solvable CAPTCHA. Completing verification will NOT fix this. "
                "To resolve: (1) Set PLAYWRIGHT_CDP_URL=http://127.0.0.1:9222 in backend/.env to use "
                "your real Chrome browser instead of Playwright's automated Chromium, "
                "(2) Use a VPN or residential proxy to change your IP, or "
                "(3) Search the county assessor website manually and enter data directly."
            )
        elif is_hard_block:
            block_msg = (
                f"⛔ ACCESS DENIED — Cloudflare has permanently blocked access to {url} (Error 1020). "
                "This is an IP-level ban, not a solvable CAPTCHA. "
                "Try: set PLAYWRIGHT_CDP_URL in backend/.env to use your real Chrome, or use a VPN."
            )
        else:
            block_msg = (
                "Complete the security check in Live Browser (Output tab), then re-run the pipeline. "
                "Cookies are saved automatically after verification succeeds."
            )

        await self.run_logger.log("human_action_required", message=block_msg)
        await self.run_logger.node_completed(
            "PortalGateNode",
            detail="Access denied — Cloudflare hard block" if is_hard_block else "Security check not completed",
            result=gate_result,
        )

    async def _node_assessor(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
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

        node_mode = _data_str(data, "automation_mode", "automationMode") or ctx.automation_mode
        if node_mode == "ai_dynamic":
            ctx.total_records += await self._search_assessor_dynamic(
                driver, url, ctx, data, canvas_id=canvas_id
            )
        else:
            ctx.total_records += await self._search_assessor(
                driver, url, search_qt, search_qv, ctx.state, ctx.county, playwright_notes=notes
            )
        self._refresh_parcel(ctx)
        if self._refresh_book_page_from_assessor(ctx):
            await self.run_logger.log(
                "node_step",
                node="AssessorNode",
                message=(
                    f"Resolved book {ctx.book_number} / page {ctx.page_number} "
                    "from Assessor Sales Information for downstream Recorder search"
                ),
            )
        assessor_rec = self._get_assessor_record()
        assessor_records = [r for r in self.records_repo.list_by_run(self.run_id) if r.get("source") == "assessor"]
        assessor_result = {
            "records_found": len(assessor_records),
            "parcel": ctx.parcel,
            "owner_name": ctx.owner_name,
            "address": ctx.address,
            "property": assessor_rec,
        }
        self._record_node_result(ctx, "assessor", canvas_id, assessor_result)

    async def _node_recorder(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
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
            ctx.book_page_source = "input"

        explicit_input_book_page = (
            ctx.book_page_source == "input" and ctx.book_number and ctx.page_number
        )

        recorder_qt = ctx.query_type
        recorder_qv = ctx.query_value
        self._refresh_parcel(ctx)
        if not explicit_input_book_page:
            self._refresh_book_page_from_assessor(ctx)
        sales_book_pages = self._get_assessor_sales_book_pages(ctx)

        scope_label = "Current Search" if ctx.search_scope == "current" else "Full Search"
        await self.run_logger.log(
            "node_step",
            node="RecorderNode",
            message=f"Recorder search scope: {scope_label}",
        )

        notes = _data_str(data, "playwright_notes") or None
        if notes:
            driver.playwright_notes = notes
        node_mode = _data_str(data, "automation_mode", "automationMode") or ctx.automation_mode
        recorder_handled = False

        if sales_book_pages:
            labels = [format_book_page_label(book, page) for book, page, _ in sales_book_pages]
            await self.run_logger.log(
                "node_step",
                node="RecorderNode",
                message=(
                    f"{scope_label}: downloading recorder documents for "
                    f"{len(sales_book_pages)} assessor sales book/page "
                    f"{'entry' if len(sales_book_pages) == 1 else 'entries'}: "
                    f"{', '.join(labels)}"
                ),
            )
            if node_mode == "ai_dynamic":
                ctx.total_records += await self._search_recorder_dynamic(
                    driver, url, ctx, data, canvas_id=canvas_id
                )
            else:
                ctx.total_records += await self._search_recorder_sales_book_page_queue(
                    driver,
                    url,
                    ctx,
                    sales_book_pages,
                    playwright_notes=notes,
                )
            recorder_handled = True
        elif ctx.book_number and ctx.page_number:
            recorder_qt = QueryType.BOOK_PAGE
            recorder_qv = format_book_page_label(ctx.book_number, ctx.page_number)
            source_label = (
                "Assessor Sales Information (latest sale)"
                if ctx.book_page_source == "assessor"
                else "Input"
            )
            await self.run_logger.log(
                "node_step",
                node="RecorderNode",
                message=(
                    f"{scope_label}: using book {ctx.book_number} / page {ctx.page_number} "
                    f"from {source_label} for recorder search"
                ),
            )
        elif (
            ctx.county == "miami-dade"
            and ctx.address
            and ctx.query_type == QueryType.ADDRESS
        ):
            recorder_qt = QueryType.ADDRESS
            recorder_qv = ctx.address
            await self.run_logger.log(
                "node_step",
                node="RecorderNode",
                message=f"Using Miami-Dade Property/Condo address search for '{ctx.address}'",
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

        if not recorder_handled:
            if node_mode == "ai_dynamic":
                ctx.total_records += await self._search_recorder_dynamic(
                    driver, url, ctx, data, canvas_id=canvas_id
                )
            else:
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
                    search_limit=ctx.search_limit,
                    available_values={
                        "book": ctx.book_number or "",
                        "page": ctx.page_number or "",
                        "owner": ctx.owner_name or "",
                        "parcel": ctx.parcel or "",
                        "address": ctx.address or "",
                        "query_value": recorder_qv or ctx.query_value or "",
                    },
                )
        docs = self.documents_repo.list_by_run(self.run_id)
        recorder_result = {
            "documents_found": len(docs),
            "documents": docs,
            "book_number": ctx.book_number,
            "page_number": ctx.page_number,
        }
        self._record_node_result(ctx, "recorder", canvas_id, recorder_result)

    async def _node_name_searcher(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
    ) -> None:
        await self.run_logger.node_started("NameSearcherNode")
        if not driver:
            await self.run_logger.source_skipped(
                SourceType.RECORDER, "Browser not started — name search skipped"
            )
            await self.run_logger.node_completed(
                "NameSearcherNode", detail="Skipped — browser not started"
            )
            return

        url = self._resolve_portal_url(ctx, data, "recorder_url")
        if ctx.state.upper() == "FL" and url:
            url = resolve_florida_recorder_url(url, ctx.county)
        if not url:
            await self.run_logger.source_skipped(
                SourceType.RECORDER,
                "No recorder URL — connect NETR or set URL before Name Searcher",
            )
            await self.run_logger.node_completed(
                "NameSearcherNode", detail="Skipped — no recorder URL"
            )
            return

        recorder_result = ctx.node_results.get("recorder") or {}
        documents = recorder_result.get("documents")
        if not isinstance(documents, list) or not documents:
            documents = self.documents_repo.list_by_run(self.run_id)

        normalized_documents = [
            self._normalize_document_row(doc)
            for doc in documents
            if isinstance(doc, dict)
        ]
        base_names = collect_recorder_party_names_for_search(normalized_documents)
        if not base_names:
            await self.run_logger.source_skipped(
                SourceType.RECORDER,
                "No party names found on recorder documents — run Recorder node first",
            )
            await self.run_logger.node_completed(
                "NameSearcherNode", detail="Skipped — no party names extracted"
            )
            self._record_node_result(
                ctx,
                "name_searcher",
                canvas_id,
                {"names_searched": [], "documents_added": 0, "source_names": []},
            )
            return

        expand_variations = bool(
            data.get("expandVariations")
            or data.get("expand_variations")
            or _data_str(data, "expandVariations", "expand_variations").lower()
            in ("1", "true", "yes", "on")
        )
        party_type = _data_str(data, "partyType", "party_type") or "both"
        max_names_raw = data.get("maxNames") or data.get("max_names") or 0
        try:
            max_names = int(max_names_raw)
        except (TypeError, ValueError):
            max_names = 0

        search_names = list(base_names)
        if expand_variations:
            expanded: list[str] = []
            for base_name in base_names:
                expanded.extend(expand_name_search_variations(base_name))
            search_names = dedupe_party_names(expanded)

        if max_names > 0:
            search_names = search_names[:max_names]

        name_search_entries = build_name_searcher_report_entries(
            normalized_documents,
            search_names,
        )

        node_search_limit = data.get("searchLimit") or data.get("search_limit")
        search_limit = ctx.search_limit
        if node_search_limit is not None:
            try:
                parsed_limit = int(node_search_limit)
                search_limit = parsed_limit if parsed_limit > 0 else None
            except (TypeError, ValueError):
                pass

        notes = _data_str(data, "playwright_notes") or None
        party_notes = notes or ""
        if party_type == "grantor":
            party_notes = f"{party_notes} grantor".strip()
        elif party_type == "grantee":
            party_notes = f"{party_notes} grantee".strip()
        elif party_type in ("both", "all"):
            party_notes = f"{party_notes} all parties".strip()

        await self.run_logger.log(
            "node_step",
            node="NameSearcherNode",
            message=(
                f"Extracted {len(base_names)} party name(s) from recorder documents; "
                f"searching {len(search_names)} name variation(s): "
                f"{', '.join(search_names[:8])}"
                f"{'...' if len(search_names) > 8 else ''}"
            ),
        )

        added = await self._search_recorder_name_queue(
            driver,
            url,
            ctx,
            search_names,
            playwright_notes=party_notes or None,
            search_limit=search_limit,
        )
        ctx.total_records += added

        all_docs = self.documents_repo.list_by_run(self.run_id)
        result = {
            "source_names": base_names,
            "names_searched": search_names,
            "name_search_entries": name_search_entries,
            "documents_added": added,
            "documents_found": len(all_docs),
            "expand_variations": expand_variations,
            "party_type": party_type,
        }
        self._record_node_result(ctx, "name_searcher", canvas_id, result)
        await self.run_logger.node_completed(
            "NameSearcherNode",
            records_found=added,
            detail=f"Searched {len(search_names)} name(s), added {added} document(s)",
        )

    async def _node_gis(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
    ) -> None:
        if not driver:
            await self.run_logger.source_skipped(SourceType.GIS, "Browser not started")
            return
        self._refresh_parcel(ctx)
        if not ctx.parcel and ctx.query_type == QueryType.PARCEL and ctx.query_value:
            ctx.parcel = ctx.query_value

        gis_url = self._resolve_portal_url(ctx, data, "gis_url")
        folio_from_url = extract_miami_dade_folio_from_url(gis_url) if gis_url else None
        if folio_from_url and not ctx.parcel:
            ctx.parcel = normalize_florida_parcel(folio_from_url, county=ctx.county or "miami-dade")

        if (is_miami_dade_gis(gis_url or "") or ctx.county == "miami-dade") and not gis_url:
            gis_url = MIAMI_DADE_SEARCH_URL

        parcel = ctx.parcel or folio_from_url or (
            ctx.query_value if ctx.query_type == QueryType.PARCEL else ""
        )
        if parcel and is_miami_dade_gis(gis_url or "") and not folio_from_url:
            gis_url = build_miami_dade_property_search_url(parcel, gis_url or MIAMI_DADE_SEARCH_URL)

        if not gis_url:
            await self.run_logger.source_skipped(SourceType.GIS, "No GIS URL")
            return
        if not parcel and not folio_from_url:
            await self.run_logger.source_skipped(
                SourceType.GIS, "No parcel/folio available for GIS map capture"
            )
            return

        notes = _data_str(data, "playwright_notes") or None
        if notes:
            driver.playwright_notes = notes
        await self._capture_gis(
            driver,
            gis_url,
            parcel,
            ctx.query_type,
            ctx.query_value,
            playwright_notes=notes,
        )
        gis_result = {
            "parcel": parcel,
            "gis_url": gis_url,
        }
        self._record_node_result(ctx, "gis", canvas_id, gis_result)

    async def _node_tax(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
    ) -> None:
        if not driver:
            await self.run_logger.source_skipped(SourceType.TAX_RECORD, "Browser not started")
            return
        self._refresh_parcel(ctx)
        tax_url = _data_str(data, "url") or None
        if not tax_url and ctx.state.upper() == "FL":
            self._ensure_ctx_sources(ctx)
            tax_url = (getattr(ctx.sources, "treasurer_url", None) if ctx.sources else None) or resolve_florida_tax_url(
                ctx.county, ctx.parcel or ""
            )
        # If no parcel was resolved from assessor, fall back to the raw query value
        # when the user searched by parcel — this lets Tax run standalone.
        if not ctx.parcel and ctx.query_type == QueryType.PARCEL and ctx.query_value:
            ctx.parcel = ctx.query_value
        if not ctx.parcel and ctx.query_type not in (QueryType.ADDRESS, QueryType.OWNER):
            await self.run_logger.source_skipped(
                SourceType.TAX_RECORD,
                "No parcel ID resolved for tax record lookup; provide a parcel or use address/owner search",
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
        tax_records = [r for r in self.records_repo.list_by_run(self.run_id) if r.get("source") == "tax"]
        tax_result = {
            "records_found": len(tax_records),
            "records": tax_records,
            "parcel": ctx.parcel,
        }
        self._record_node_result(ctx, "tax", canvas_id, tax_result)

    async def _node_ai_agent(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
        pipeline_graph: Optional[dict[str, Any]] = None,
        parsed: Optional[ParsedPipelineGraph] = None,
        node_id: str = "ai_agent",
    ) -> None:
        is_chatbot = node_id == "chatbot"
        node_type_name = "ChatbotNode" if is_chatbot else "AIAgentNode"
        default_agent_name = "Title Chatbot" if is_chatbot else "OpenAI Agent"
        default_instructions = (
            "You are a conversational AI Title Search Assistant. Answer user questions clearly and concisely using the pipeline data."
            if is_chatbot
            else "You are a helpful AI assistant."
        )

        config = {
            "agent_name": _data_str(data, "agent_name", default=default_agent_name),
            "instructions": _data_str(data, "instructions", default=default_instructions),
            "user_prompt": _data_str(data, "user_prompt"),
            "model": _data_str(data, "model", default="gpt-4o"),
            "temperature": data.get("temperature", 0.7),
            "max_tokens": data.get("max_tokens", 1000),
        }
        records = self.records_repo.list_by_run(self.run_id)
        documents = self.documents_repo.list_by_run(self.run_id)

        # Resolve predecessor node to pass previous_result
        prev_canvas_id: Optional[str] = None
        prev_node_id: Optional[str] = None
        if pipeline_graph and canvas_id:
            edges = pipeline_graph.get("edges") or []
            for edge in edges:
                if edge.get("target") == canvas_id:
                    prev_canvas_id = edge.get("source")
                    if prev_canvas_id and parsed and prev_canvas_id in parsed.node_map:
                        prev_node_id = parsed.node_map[prev_canvas_id].get("node_id")
                    break

        if not prev_node_id and parsed and canvas_id:
            try:
                idx = parsed.order.index(canvas_id)
                if idx > 0:
                    prev_canvas_id = parsed.order[idx - 1]
                    prev_node_id = parsed.node_map[prev_canvas_id].get("node_id")
            except (ValueError, IndexError):
                pass

        if not prev_node_id:
            prev_node_id = ctx.last_completed_node_id

        previous_result = None
        if prev_canvas_id and prev_canvas_id in ctx.node_results:
            previous_result = ctx.node_results[prev_canvas_id]
        elif prev_node_id and prev_node_id in ctx.node_results:
            previous_result = ctx.node_results[prev_node_id]
        else:
            previous_result = ctx.last_completed_node_result

        report_result = ctx.node_results.get("report")

        context_data = {
            "run_id": self.run_id,
            "state": ctx.state,
            "county": ctx.county,
            "query_value": ctx.query_value,
            "previous_node": prev_node_id or "previous",
            "previous_result": previous_result,
            "report": report_result,
            "node_results": dict(ctx.node_results),
            "records": records,
            "documents": documents,
            "sources": ctx.sources.model_dump() if ctx.sources else {},
        }
        agent_name = config.get("agent_name") or default_agent_name
        await self.run_logger.node_started(
            node_type_name, agent_name=agent_name, model=config.get("model"), canvas_id=canvas_id
        )
        await self.run_logger.log(
            "chatbot_invoke" if is_chatbot else "ai_agent_invoke",
            node=node_type_name,
            message=f"Executing {agent_name} ({config.get('model', 'gpt-4o')})...",
            canvas_id=canvas_id,
            config=config,
            context_data=context_data,
        )
        try:
            t0 = time.monotonic()
            ai_result = await self.ai_agent.run(
                instructions=config.get("instructions") or default_instructions,
                user_prompt=config.get("user_prompt") or "",
                model=config.get("model") or "gpt-4o",
                temperature=float(config.get("temperature") or 0.7),
                max_tokens=int(config.get("max_tokens") or 1000),
                context_data=context_data,
            )
            duration = int((time.monotonic() - t0) * 1000)
            preview = (ai_result.get("content") or "")[:500]

            ai_result_payload = {
                **ai_result,
                "agent_name": agent_name,
                "duration_ms": duration,
            }

            self._record_node_result(ctx, node_id, canvas_id, ai_result_payload)

            # Persist official AI Analysis/Chatbot document into documents_repo
            doc_type = "AI Chatbot Response" if is_chatbot else "AI Title Analysis"
            doc_data = {
                "document_type": doc_type,
                "recording_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "instrument_number": f"{'CB' if is_chatbot else 'AI'}-{self.run_id[:8].upper()}",
                "grantor": f"OpenAI ({ai_result.get('model', 'gpt-4o')})",
                "grantee": ctx.owner_name or "Title Production Report",
                "notes": ai_result.get("content"),
                "ocr_json": {
                    "source": node_id,
                    "agent_name": agent_name,
                    "model": ai_result.get("model"),
                    "prompt_tokens": ai_result.get("prompt_tokens"),
                    "completion_tokens": ai_result.get("completion_tokens"),
                    "duration_ms": duration,
                    "ai_response": ai_result.get("content"),
                },
            }
            try:
                self.documents_repo.insert(self.run_id, doc_data)
            except Exception as exc:
                logger.warning("Failed to insert %s document: %s", doc_type, exc)

            # Persist to run plan
            run = self.runs_repo.get_run(self.run_id) or {}
            plan = run.get("plan_json") or {}
            updated_node_results = dict(ctx.node_results)
            updated_node_results[node_id] = ai_result_payload
            if canvas_id:
                updated_node_results[canvas_id] = ai_result_payload

            plan_updates = {
                **plan,
                "node_results": updated_node_results,
            }
            if is_chatbot:
                plan_updates["chatbot_response"] = ai_result.get("content")
                plan_updates["chatbot_model"] = ai_result.get("model")
                if not plan.get("ai_agent_response"):
                    plan_updates["ai_agent_response"] = ai_result.get("content")
            else:
                plan_updates["ai_agent_response"] = ai_result.get("content")
                plan_updates["ai_agent_model"] = ai_result.get("model")

            self.runs_repo.update_run(
                self.run_id,
                plan_json=plan_updates,
            )

            complete_pending(self.run_id, canvas_id, ai_result)

            await self.run_logger.node_completed(
                node_type_name,
                agent_name=agent_name,
                model=ai_result.get("model"),
                duration_ms=duration,
                detail=preview,
                prompt_tokens=ai_result.get("prompt_tokens"),
                completion_tokens=ai_result.get("completion_tokens"),
                result=ai_result_payload,
            )
        except Exception as exc:
            fail_pending(self.run_id, canvas_id, str(exc))
            await self.run_logger.node_failed(node_type_name, str(exc))
            raise

    async def _node_normalizer(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
    ) -> None:
        await self.run_logger.node_started("NormalizerNode")
        stats = normalize_run_data(self.run_id, self.records_repo, self.documents_repo)
        detail = (
            f"Records {stats['records_before']}→{stats['records_after']}, "
            f"documents {stats['documents_before']}→{stats['documents_after']}"
        )
        normalizer_result = {
            "stats": stats,
            "detail": detail,
        }
        self._record_node_result(ctx, "normalizer", canvas_id, normalizer_result)
        await self.run_logger.node_completed("NormalizerNode", detail=detail, result=normalizer_result, **stats)

    async def _node_report(
        self,
        data: dict[str, Any],
        ctx: RunContext,
        driver: Optional[NetronlineDriver],
        resolver: Optional[CountyResolver],
        canvas_id: str = "",
    ) -> None:
        await self.run_logger.node_started("ReportNode")
        try:
            builder = ReportBuilder()
            report = await builder.build_and_save(self.run_id)
            ctx.report_id = report.get("id")
            report_json = report.get("report_json") or {}
            report_result = {
                "report_id": ctx.report_id,
                "pdf_path": report.get("pdf_path"),
                "storage_url": report.get("storage_url"),
                "pdf_url": f"/reports/run/{self.run_id}",
                "property": report_json.get("property") or {},
                "tax_record": report_json.get("tax_record") or {},
                "chain_of_title": report_json.get("chain_of_title") or [],
                "documents_count": len(report_json.get("documents") or []),
                "documents": report_json.get("documents") or [],
                "sources_trail": report_json.get("sources_trail") or [],
                "ai_agent_response": report_json.get("ai_agent_response"),
                "ai_agent_model": report_json.get("ai_agent_model"),
                "status": "ready",
            }
            self._record_node_result(ctx, "report", canvas_id, report_result)
            await self.run_logger.node_completed(
                "ReportNode",
                detail="PDF report generated",
                report_id=ctx.report_id,
                result=report_result,
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
        canvas_id: str = "",
    ) -> None:
        await self.run_logger.node_started("OutputNode")
        output_result = {
            "total_records": ctx.total_records,
            "report_id": ctx.report_id,
            "node_results": dict(ctx.node_results),
        }
        self._record_node_result(ctx, "output", canvas_id, output_result)
        await self.run_logger.node_completed("OutputNode", total_records=ctx.total_records, result=output_result)

    def _persist_assessor_chain_of_title(self, parcel: Any) -> int:
        from app.extraction.assessor_book_page import is_valid_sale_date

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
            if recording_date and not is_valid_sale_date(recording_date):
                continue
            sale_price = entry.get("sale_price")
            instrument_number = entry.get("instrument_number")
            book_page = entry.get("book_page")
            if not any([grantor, grantee, recording_date, sale_price, instrument_number, book_page]):
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
        assessor.inherit_browser_from(base)
        assessor.playwright_notes = playwright_notes or assessor.playwright_notes
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
                raw_json = enrich_raw_json_with_latest_book_page(parcel.raw_json or {})

                self.records_repo.insert(
                    self.run_id,
                    {
                        "source": "assessor",
                        "apn": apn,
                        "owner_name": owner,
                        "property_address": addr,
                        "legal_description": leg_desc,
                        "assessed_value": assessed_val,
                        "raw_json": raw_json,
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

            assessor_documents = getattr(assessor, "downloaded_assessor_documents", []) or []
            for doc in assessor_documents:
                file_path = doc.get("screenshot_path")
                if not file_path or not str(file_path).lower().endswith(".pdf"):
                    continue
                ocr_json = self.document_storage.upload_and_merge(
                    self.run_id,
                    doc.get("ocr_json") or {"source": "assessor", "storage_category": "assessor"},
                    file_path,
                )
                self.documents_repo.insert(
                    self.run_id,
                    {
                        "document_type": doc.get("document_type", "Assessor Report"),
                        "instrument_number": doc.get("instrument_number"),
                        "source_url": doc.get("source_url") or url,
                        "screenshot_path": file_path,
                        "ocr_json": ocr_json,
                    },
                )

            duration = int((time.monotonic() - t0) * 1000)
            await self.run_logger.source_completed(SourceType.ASSESSOR, records_found=count, duration_ms=duration)
            await self.run_logger.node_completed("AssessorNode", records_found=count)
            return count
        except Exception as exc:
            await self.run_logger.node_failed("AssessorNode", str(exc))
            await self.run_logger.source_failed(SourceType.ASSESSOR, str(exc))
            await assessor.screenshot_on_failure("assessor_error")
            return 0

    async def _persist_recorder_documents(
        self,
        documents: list[Any],
        search_url: str,
        query_value: str,
    ) -> int:
        count = 0
        for doc in documents:
            ocr = getattr(doc, "ocr_json", None) or {}
            if ocr.get("status") in (
                "no_records_found",
                "download_failed",
                "no_result_cards",
                "timeout",
            ):
                continue
            if not (
                doc.screenshot_path and str(doc.screenshot_path).lower().endswith(".pdf")
            ):
                continue
            orig_doc = doc
            if doc.screenshot_path and doc.screenshot_path.lower().endswith(".pdf"):
                if not doc.ocr_json:
                    doc.ocr_json = {"download_path": doc.screenshot_path}
                if not (doc.ocr_json or {}).get("mistral_analyzed"):
                    try:
                        extracted = await self.ocr.extract_document(doc.screenshot_path, doc.document_type)
                        if extracted and extracted.ocr_json and "error" not in extracted.ocr_json:
                            doc = extracted
                    except Exception as ocr_err:
                        logger.warning("Document OCR failed, keeping original: %s", ocr_err)
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
                "recording_details",
                "mistral_analyzed",
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

            merged_ocr = self.document_storage.upload_and_merge(
                self.run_id,
                merged_ocr,
                screenshot_path,
            )

            doc_type = (
                getattr(normalized, "document_type", None)
                or getattr(orig_doc, "document_type", None)
                or getattr(doc, "document_type", None)
            )
            bk_pg = (
                getattr(normalized, "book_page", None)
                or getattr(orig_doc, "book_page", None)
                or getattr(doc, "book_page", None)
                or (
                    f"{merged_ocr['book_number']}/{merged_ocr['page_number']}"
                    if "book_number" in merged_ocr and "page_number" in merged_ocr
                    else None
                )
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
                    "source_url": getattr(normalized, "source_url", None)
                    or getattr(orig_doc, "source_url", None)
                    or getattr(doc, "source_url", None)
                    or search_url,
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
        return count

    async def _search_recorder_sales_book_page_queue(
        self,
        base: BaseDriver,
        url: str,
        ctx: RunContext,
        sales_book_pages: list[tuple[str, str, dict[str, Any]]],
        playwright_notes: Optional[str] = None,
    ) -> int:
        """Download recorder documents for every assessor sales book/page entry, one at a time."""
        from app.drivers.recorder.miami_dade_recorder import (
            miami_dade_book_page_search_and_download,
            miami_dade_open_assessor_recorder_link_and_download,
            miami_dade_prepare_recorder_queue_step,
        )

        recorder = GilaRecorderDriver()
        recorder.inherit_browser_from(base)
        recorder.playwright_notes = playwright_notes or recorder.playwright_notes

        search_url = url
        if ctx.state.upper() == "FL":
            search_url = resolve_florida_recorder_url(url, ctx.county)

        t0 = time.monotonic()
        total = 0
        queue_size = len(sales_book_pages)

        try:
            await self.run_logger.node_started("RecorderNode", url=search_url)
            await self.run_logger.source_started(SourceType.RECORDER, search_url)

            for idx, (book_number, page_number, sale_entry) in enumerate(sales_book_pages):
                position = idx + 1
                sale_date = sale_entry.get("recording_date") or sale_entry.get("sale_date") or ""
                await self.run_logger.log(
                    "node_step",
                    node="RecorderNode",
                    message=(
                        f"Recorder queue: fetching book {book_number} / page {page_number} "
                        f"({position} of {queue_size})"
                        + (f" — sale date {sale_date}" if sale_date else "")
                    ),
                )

                try:
                    if not await miami_dade_prepare_recorder_queue_step(recorder):
                        await self.run_logger.log(
                            "node_step",
                            node="RecorderNode",
                            message=(
                                f"Recorder queue: could not recover browser tab before "
                                f"{book_number} / {page_number}; skipping."
                            ),
                        )
                        continue

                    queued_labels = [
                        format_book_page_label(book, page)
                        for book, page, _ in sales_book_pages[idx + 1 :]
                    ]
                    if queued_labels:
                        await self.run_logger.log(
                            "node_step",
                            node="RecorderNode",
                            message=f"Queued next recorder downloads: {', '.join(queued_labels)}",
                        )

                    query_value = format_book_page_label(book_number, page_number)
                    recorder_url = str(sale_entry.get("recorder_url") or "").strip()
                    documents: list[Any] = []

                    if recorder_url:
                        documents = await miami_dade_open_assessor_recorder_link_and_download(
                            recorder,
                            recorder_url,
                            book_number,
                            page_number,
                            search_limit=None,
                        )

                    if not documents:
                        if idx == 0 and not recorder_url:
                            documents = await recorder.search(
                                search_url,
                                QueryType.BOOK_PAGE,
                                query_value,
                                book_number=book_number,
                                page_number=page_number,
                                search_limit=None,
                            )
                        else:
                            await recorder._emit_status(
                                f"Miami-Dade recorder: falling back to book/page search for {query_value}..."
                            )
                            documents = await miami_dade_book_page_search_and_download(
                                recorder,
                                book_number,
                                page_number,
                                search_limit=None,
                            )

                    await recorder.save_browser_preview()

                    persisted = await self._persist_recorder_documents(
                        documents,
                        search_url,
                        query_value,
                    )
                    total += persisted
                    await self.run_logger.log(
                        "node_step",
                        node="RecorderNode",
                        message=(
                            f"Recorder queue: saved {persisted} document(s) for "
                            f"{book_number} / {page_number} ({position} of {queue_size})"
                        ),
                    )
                except Exception as exc:
                    logger.warning(
                        "Recorder queue failed for book %s page %s: %s",
                        book_number,
                        page_number,
                        exc,
                    )
                    await self.run_logger.log(
                        "node_step",
                        node="RecorderNode",
                        message=(
                            f"Recorder queue: failed for {book_number} / {page_number} "
                            f"({position} of {queue_size}): {exc}"
                        ),
                    )
                    await recorder.screenshot_on_failure(
                        f"recorder_queue_{book_number}_{page_number}"
                    )
                    continue

            base._page = recorder._page
            base._browser_stream = recorder._browser_stream
            await base.stabilize_browser_session()
            duration = int((time.monotonic() - t0) * 1000)
            await self.run_logger.source_completed(
                SourceType.RECORDER, records_found=total, duration_ms=duration
            )
            await self.run_logger.node_completed("RecorderNode", records_found=total)
            return total
        except Exception as exc:
            await self.run_logger.node_failed("RecorderNode", str(exc))
            await self.run_logger.source_failed(SourceType.RECORDER, str(exc))
            await recorder.screenshot_on_failure("recorder_error")
            return total

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
        search_limit: Optional[int] = None,
        available_values: Optional[dict[str, str]] = None,
    ) -> int:
        t0 = time.monotonic()
        recorder = GilaRecorderDriver()
        recorder.inherit_browser_from(base)
        recorder.playwright_notes = playwright_notes or recorder.playwright_notes

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
                search_limit=search_limit,
            )
            base._page = recorder._page
            base._browser_stream = recorder._browser_stream
            await base.stabilize_browser_session()
            await recorder.save_browser_preview()
            count = await self._persist_recorder_documents(documents, search_url, query_value)
            duration = int((time.monotonic() - t0) * 1000)
            await self.run_logger.source_completed(SourceType.RECORDER, records_found=count, duration_ms=duration)
            await self.run_logger.node_completed("RecorderNode", records_found=count)
            return count
        except Exception as exc:
            await self.run_logger.node_failed("RecorderNode", str(exc))
            await self.run_logger.source_failed(SourceType.RECORDER, str(exc))
            await recorder.screenshot_on_failure("recorder_error")
            return 0

    async def _search_recorder_name_queue(
        self,
        base: BaseDriver,
        url: str,
        ctx: RunContext,
        names: list[str],
        *,
        playwright_notes: Optional[str] = None,
        search_limit: Optional[int] = None,
    ) -> int:
        """Run recorder party-name searches for each extracted name."""
        from app.config.florida_portals import is_miami_dade_recorder
        from app.drivers.recorder.miami_dade_recorder import miami_dade_prepare_recorder_queue_step
        from app.drivers.recorder.acclaimweb_recorder import (
            format_acclaimweb_party_name,
            is_acclaimweb_recorder,
        )

        if not names:
            return 0

        t0 = time.monotonic()
        recorder = GilaRecorderDriver()
        recorder.inherit_browser_from(base)
        recorder.playwright_notes = playwright_notes or recorder.playwright_notes

        search_url = url
        if ctx.state.upper() == "FL":
            search_url = resolve_florida_recorder_url(url, ctx.county)

        total = 0
        try:
            await self.run_logger.source_started(SourceType.RECORDER, search_url)
            for idx, name in enumerate(names):
                await self.run_logger.log(
                    "node_step",
                    node="NameSearcherNode",
                    message=f"Name search {idx + 1}/{len(names)}: {name}",
                )

                if idx > 0 and (
                    is_miami_dade_recorder(search_url)
                    or (recorder.page and is_miami_dade_recorder(recorder.page.url))
                ):
                    await miami_dade_prepare_recorder_queue_step(recorder)

                if is_acclaimweb_recorder(search_url) or (
                    recorder.page and is_acclaimweb_recorder(recorder.page.url)
                ):
                    query_value = format_acclaimweb_party_name(name)
                else:
                    query_value = name

                documents = await recorder.search(
                    search_url,
                    QueryType.OWNER,
                    query_value,
                    search_limit=search_limit,
                )
                await recorder.save_browser_preview()
                total += await self._persist_recorder_documents(
                    documents, search_url, query_value
                )

            base._page = recorder._page
            base._browser_stream = recorder._browser_stream
            await base.stabilize_browser_session()
            duration = int((time.monotonic() - t0) * 1000)
            await self.run_logger.source_completed(
                SourceType.RECORDER, records_found=total, duration_ms=duration
            )
            return total
        except Exception as exc:
            await self.run_logger.node_failed("NameSearcherNode", str(exc))
            await self.run_logger.source_failed(SourceType.RECORDER, str(exc))
            await recorder.screenshot_on_failure("name_searcher_error")
            return total

    # ------------------------------------------------------------------
    # Dynamic AI-guided portal search methods (ai_dynamic automation mode)
    # ------------------------------------------------------------------

    async def _search_assessor_dynamic(
        self,
        base: "NetronlineDriver",
        url: str,
        ctx: RunContext,
        data: dict[str, Any],
        canvas_id: str = "",
    ) -> int:
        """Run AI-guided dynamic portal search for assessor records.

        Uses DynamicPortalEngine to discover and interact with any county
        assessor portal without hard-coded selectors, then persists records
        identically to the legacy _search_assessor path.
        """
        from app.drivers.dynamic_portal import DynamicPortalEngine
        from app.drivers.dynamic_portal.schemas import PropertySearchInput

        t0 = time.monotonic()
        await self.run_logger.node_started("AssessorNode", url=url)
        await self.run_logger.source_started(SourceType.ASSESSOR, url)

        prop_input = PropertySearchInput(
            address=ctx.address,
            parcelNumber=ctx.parcel,
            ownerName=ctx.owner_name,
            county=ctx.county,
            state=ctx.state,
        )

        engine = DynamicPortalEngine()

        async def _emit(msg: str) -> None:
            lower = msg.lower()
            needs_human = any(
                token in lower
                for token in ("cloudflare", "captcha", "verify you are human", "you have been blocked")
            )
            if needs_human:
                await self.run_logger.log("human_action_required", message=msg)
            else:
                await self.run_logger.log("node_step", node="AssessorNode", message=msg)

        try:
            result = await engine.execute_search(
                page=base.page,
                start_url=url,
                prop_input=prop_input,
                portal_type="assessor",
                status_emitter=_emit,
                run_id=self.run_id,
            )
        except Exception as exc:
            await self.run_logger.node_failed("AssessorNode", str(exc))
            await self.run_logger.source_failed(SourceType.ASSESSOR, str(exc))
            logger.warning("Dynamic assessor search raised exception: %s", exc)
            return 0

        status = result.get("status")
        records = result.get("records") or []
        documents = result.get("documents") or []
        requires_manual = result.get("requires_manual_review", False)
        message = result.get("message", "")

        if requires_manual:
            await self.run_logger.log(
                "human_action_required",
                node="AssessorNode",
                message=f"Dynamic portal search requires manual review: {message}",
            )

        count = 0
        for rec in records:
            apn = rec.get("parcelNumber") or rec.get("apn")
            owner = rec.get("ownerName") or rec.get("owner_name")
            addr = rec.get("address") or rec.get("property_address")
            legal = rec.get("legalDescription") or rec.get("legal_description")
            raw_json = enrich_raw_json_with_latest_book_page(rec.get("raw_data") or rec)

            self.records_repo.insert(
                self.run_id,
                {
                    "source": "assessor",
                    "apn": apn,
                    "owner_name": owner,
                    "property_address": addr,
                    "legal_description": legal,
                    "raw_json": raw_json,
                },
            )
            await self.run_logger.record_found(
                SourceType.ASSESSOR,
                apn=apn,
                owner_name=owner,
                property_address=addr,
            )
            count += 1

        # Persist any documents discovered (e.g. deed scans from assessor detail page)
        for doc in documents:
            if not doc.get("file_path") and not doc.get("download_url"):
                continue
            self.documents_repo.insert(
                self.run_id,
                {
                    "document_type": doc.get("document_type", "assessor_document"),
                    "source_url": doc.get("download_url") or url,
                    "screenshot_path": doc.get("file_path"),
                    "ocr_json": {
                        "source": "assessor_dynamic",
                        "title": doc.get("title"),
                        "download_url": doc.get("download_url"),
                        "file_path": doc.get("file_path"),
                        "sha256": doc.get("sha256_hash"),
                    },
                },
            )

        duration = int((time.monotonic() - t0) * 1000)
        await self.run_logger.source_completed(SourceType.ASSESSOR, records_found=count, duration_ms=duration)
        await self.run_logger.node_completed("AssessorNode", records_found=count)
        return count

    async def _search_recorder_dynamic(
        self,
        base: "NetronlineDriver",
        url: str,
        ctx: RunContext,
        data: dict[str, Any],
        canvas_id: str = "",
    ) -> int:
        """Run AI-guided dynamic portal search for recorder documents.

        Uses DynamicPortalEngine to discover and interact with any county
        recorder portal without hard-coded selectors, then persists documents
        identically to the legacy _search_recorder path.
        """
        from app.drivers.dynamic_portal import DynamicPortalEngine
        from app.drivers.dynamic_portal.schemas import PropertySearchInput

        t0 = time.monotonic()
        await self.run_logger.node_started("RecorderNode", url=url)
        await self.run_logger.source_started(SourceType.RECORDER, url)

        # Prefer book/page if available; otherwise use resolved parcel or owner
        recorder_qt = ctx.query_type
        recorder_qv = ctx.query_value
        if ctx.book_number and ctx.page_number:
            recorder_qt = QueryType.BOOK_PAGE
            recorder_qv = format_book_page_label(ctx.book_number, ctx.page_number)

        prop_input = PropertySearchInput(
            address=ctx.address,
            parcelNumber=ctx.parcel,
            ownerName=ctx.owner_name,
            county=ctx.county,
            state=ctx.state,
        )
        # Override with effective search values
        if recorder_qt == QueryType.PARCEL and ctx.parcel:
            prop_input = PropertySearchInput(
                parcelNumber=ctx.parcel, county=ctx.county, state=ctx.state
            )
        elif recorder_qt == QueryType.OWNER and ctx.owner_name:
            prop_input = PropertySearchInput(
                ownerName=ctx.owner_name, county=ctx.county, state=ctx.state
            )
        elif recorder_qt == QueryType.ADDRESS and ctx.address:
            prop_input = PropertySearchInput(
                address=ctx.address, county=ctx.county, state=ctx.state
            )

        engine = DynamicPortalEngine()

        async def _emit(msg: str) -> None:
            lower = msg.lower()
            needs_human = any(
                token in lower
                for token in ("cloudflare", "captcha", "verify you are human", "you have been blocked")
            )
            if needs_human:
                await self.run_logger.log("human_action_required", message=msg)
            else:
                await self.run_logger.log("node_step", node="RecorderNode", message=msg)

        try:
            result = await engine.execute_search(
                page=base.page,
                start_url=url,
                prop_input=prop_input,
                portal_type="recorder",
                status_emitter=_emit,
                run_id=self.run_id,
            )
        except Exception as exc:
            await self.run_logger.node_failed("RecorderNode", str(exc))
            await self.run_logger.source_failed(SourceType.RECORDER, str(exc))
            logger.warning("Dynamic recorder search raised exception: %s", exc)
            return 0

        status = result.get("status")
        records = result.get("records") or []
        documents = result.get("documents") or []
        requires_manual = result.get("requires_manual_review", False)
        message = result.get("message", "")

        if requires_manual:
            await self.run_logger.log(
                "human_action_required",
                node="RecorderNode",
                message=f"Dynamic recorder search requires manual review: {message}",
            )

        count = 0
        for doc in documents:
            doc_type = doc.get("document_type", "recorded_document")
            file_path = doc.get("file_path")
            download_url = doc.get("download_url")

            # Attempt OCR on downloaded PDFs/images
            if file_path:
                try:
                    extracted = await self.ocr.extract_document(file_path, doc_type)
                    if extracted and extracted.ocr_json and "error" not in extracted.ocr_json:
                        merged_ocr = extracted.ocr_json
                    else:
                        merged_ocr = {"download_path": file_path, "source": "recorder_dynamic"}
                except Exception as ocr_err:
                    logger.warning("Dynamic recorder OCR failed: %s", ocr_err)
                    merged_ocr = {"download_path": file_path, "source": "recorder_dynamic"}
            else:
                merged_ocr = {
                    "source": "recorder_dynamic",
                    "title": doc.get("title"),
                    "download_url": download_url,
                    "sha256": doc.get("sha256_hash"),
                }

            self.documents_repo.insert(
                self.run_id,
                {
                    "document_type": doc_type,
                    "source_url": download_url or url,
                    "screenshot_path": file_path,
                    "ocr_json": merged_ocr,
                },
            )
            await self.run_logger.record_found(
                SourceType.RECORDER,
                document_type=doc_type,
                screenshot_path=file_path,
            )
            count += 1

        # Also persist any property records found on result pages
        for rec in records:
            grantor = rec.get("ownerName") or rec.get("grantor")
            addr = rec.get("address") or rec.get("property_address")
            parcel_num = rec.get("parcelNumber")
            if any([grantor, addr, parcel_num]):
                self.documents_repo.insert(
                    self.run_id,
                    {
                        "document_type": "property_record",
                        "source_url": rec.get("propertyUrl") or url,
                        "grantor": grantor,
                        "ocr_json": {
                            "source": "recorder_dynamic_result",
                            "parcel": parcel_num,
                            "address": addr,
                            "legal_description": rec.get("legalDescription"),
                            **rec.get("raw_data", {}),
                        },
                    },
                )
                count += 1

        duration = int((time.monotonic() - t0) * 1000)
        await self.run_logger.source_completed(SourceType.RECORDER, records_found=count, duration_ms=duration)
        await self.run_logger.node_completed("RecorderNode", records_found=count)
        return count

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
        tax.inherit_browser_from(base)
        tax.playwright_notes = playwright_notes or tax.playwright_notes

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
        gis.inherit_browser_from(base)
        gis.playwright_notes = playwright_notes or gis.playwright_notes
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
            if path:
                self.documents_repo.insert(
                    self.run_id,
                    {
                        "document_type": "gis_map",
                        "source_url": url,
                        "screenshot_path": path,
                        "ocr_json": {
                            "source": "gis",
                            "image_path": path,
                            "folio": parcel or query_value,
                        },
                    },
                )
            duration = int((time.monotonic() - t0) * 1000)
            await self.run_logger.source_completed(
                SourceType.GIS, records_found=1 if path else 0, duration_ms=duration, screenshot_path=path
            )
            await self.run_logger.node_completed(
                "GISNode",
                records_found=1 if path else 0,
                screenshot_path=path,
            )
            return bool(path)
        except Exception as exc:
            await self.run_logger.node_failed("GISNode", str(exc))
            await self.run_logger.source_failed(SourceType.GIS, str(exc))
            return False
