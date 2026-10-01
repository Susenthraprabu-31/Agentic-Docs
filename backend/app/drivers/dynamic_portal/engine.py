"""Dynamic Portal Engine: Main orchestrator for AI-guided portal discovery, execution, and document retrieval."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from app.drivers.dynamic_portal.action_validator import ActionValidator
from app.drivers.dynamic_portal.cloudflare_detector import CloudflareDetector
from app.drivers.dynamic_portal.document_agent import DocumentAgent
from app.drivers.dynamic_portal.navigation_agent import NavigationAgent
from app.drivers.dynamic_portal.portal_analyzer import PortalAnalyzer
from app.drivers.dynamic_portal.portal_cache import PortalCache
from app.drivers.dynamic_portal.recovery_manager import RecoveryManager
from app.drivers.dynamic_portal.result_analyzer import ResultAnalyzer
from app.drivers.dynamic_portal.schemas import (
    BlockingType,
    CompactBrowserState,
    DetectionResult,
    DocumentItem,
    PortalAnalysis,
    PortalMapping,
    PropertySearchInput,
    RunErrorStatus,
    SearchFieldMapping,
    SearchPlan,
    SearchResultAnalysis,
)

logger = logging.getLogger(__name__)


class DynamicPortalEngine:
    """Coordinates navigation, page intelligence, structured execution, and document downloads."""

    def __init__(
        self,
        portal_cache: Optional[PortalCache] = None,
        cf_detector: Optional[CloudflareDetector] = None,
        analyzer: Optional[PortalAnalyzer] = None,
        nav_agent: Optional[NavigationAgent] = None,
        action_validator: Optional[ActionValidator] = None,
        result_analyzer: Optional[ResultAnalyzer] = None,
        doc_agent: Optional[DocumentAgent] = None,
        recovery_manager: Optional[RecoveryManager] = None,
    ) -> None:
        self.cache = portal_cache or PortalCache()
        self.cf_detector = cf_detector or CloudflareDetector()
        self.analyzer = analyzer or PortalAnalyzer()
        self.nav_agent = nav_agent or NavigationAgent()
        self.validator = action_validator or ActionValidator()
        self.result_analyzer = result_analyzer or ResultAnalyzer()
        self.doc_agent = doc_agent or DocumentAgent()
        self.recovery = recovery_manager or RecoveryManager(self.cache)

    async def execute_search(
        self,
        page: Any,
        start_url: str,
        prop_input: PropertySearchInput,
        portal_type: str = "assessor",
        status_emitter: Optional[Callable[[str], Any]] = None,
        run_id: str = "default",
        alternate_urls: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Execute dynamic portal workflow:
        1. Cache Check -> 2. Blocking Check -> 3. Navigation Discovery ->
        4. Field Mapping -> 5. Action Execution -> 6. Result Analysis ->
        7. Document Retrieval.
        """
        async def _emit(msg: str):
            logger.info("[%s %s] %s", prop_input.county, portal_type, msg)
            if status_emitter:
                res = status_emitter(msg)
                if asyncio.iscoroutine(res):
                    await res

        async def _try_approved_alternate(
            blocking: DetectionResult,
            stage: str,
        ) -> Optional[Dict[str, Any]]:
            """Use only a caller-supplied, approved fallback; never evade a block."""
            if not alternate_urls:
                return None
            alt_url = self.recovery.find_approved_alternate_source(start_url, alternate_urls)
            if not alt_url:
                return None
            await _emit(
                f"{stage} blocked ({blocking.type.value}). Switching to caller-approved alternate source: {alt_url}"
            )
            return await self.execute_search(
                page,
                alt_url,
                prop_input,
                portal_type=portal_type,
                status_emitter=status_emitter,
                run_id=run_id,
                alternate_urls=[],
            )

        state = prop_input.state
        county = prop_input.county
        active_target = page
        active_analysis: Optional[PortalAnalysis] = None
        nav_path: List[str] = []

        # A hard Cloudflare denial does not resolve through retries. Persisting this
        # domain-level circuit breaker prevents every new county run from making the
        # same blocked request until the portal owner restores approved access.
        from app.config.settings import get_settings
        blocked_record = self.cache.get_active_hard_block(
            start_url, get_settings().portal_hard_block_cooldown_minutes
        )
        if blocked_record:
            blocked = DetectionResult(
                blocked=True,
                type=BlockingType.ACCESS_DENIED,
                confidence=1.0,
                recommendedAction="MANUAL_REVIEW_REQUIRED",
                details=blocked_record,
            )
            alternate_result = await _try_approved_alternate(blocked, "Primary portal")
            if alternate_result is not None:
                return alternate_result
            return {
                "status": RunErrorStatus.ACCESS_DENIED,
                "records": [],
                "documents": [],
                "requires_manual_review": True,
                "message": "Portal is temporarily quarantined after a hard access denial. Request approved access or configure an official alternate source.",
            }

        # 1. Fast-Path: Check Portal Cache
        cached_mapping = self.cache.load_mapping(state, county, portal_type=portal_type)
        if cached_mapping:
            await _emit("Found cached portal mapping — testing fast-path validation...")
            try:
                if page.url != cached_mapping.search_page_url:
                    await page.goto(cached_mapping.search_page_url, wait_until="domcontentloaded", timeout=30_000)

                browser_state = await self.analyzer.capture_state(page)
                if await self.cache.validate_cached_mapping(cached_mapping, page, browser_state):
                    await _emit("Cached portal mapping validated successfully! Reusing deterministic path.")
                    # Reconstruct PortalAnalysis from cached mapping
                    fields = {}
                    for k, v in cached_mapping.search_fields.items():
                        fields[k] = SearchFieldMapping(
                            field_type=k,
                            selector=v.get("selector") if isinstance(v, dict) else str(v),
                        )
                    active_analysis = PortalAnalysis(
                        page_type="search_form",
                        is_search_page=True,
                        search_fields=fields,
                        submit_button_selector=cached_mapping.submit_selector,
                        tab_selectors=cached_mapping.tab_selectors,
                        iframe_selector=cached_mapping.iframe_selector,
                    )
                    nav_path = cached_mapping.navigation_path
                else:
                    await _emit("Cached selectors changed or failed validation. Running self-healing...")
                    healed = await self.recovery.attempt_self_healing(
                        page, state, county, portal_type, cached_mapping
                    )
                    if healed:
                        await _emit("Self-healing established updated mapping.")
                        cached_mapping = healed
                    else:
                        await _emit("Self-healing required fresh navigation discovery.")
                        cached_mapping = None
            except Exception as cache_err:
                logger.warning("Cache fast-path evaluation failed: %s", cache_err)
                cached_mapping = None

        # 2. Navigation Discovery (if fast-path not active)
        if not active_analysis:
            await _emit(f"Discovering property search navigation starting from {start_url}...")
            nav_result = await self.nav_agent.discover_search_page(
                page, start_url, portal_type=portal_type, status_emitter=_emit
            )
            if nav_result["status"] != "search_found":
                error_status = nav_result.get("error_status", RunErrorStatus.NAVIGATION_FAILED)
                if nav_result.get("status") == "blocked":
                    blocking = nav_result.get("blocking_result")
                    if isinstance(blocking, DetectionResult):
                        if blocking.type == BlockingType.ACCESS_DENIED:
                            self.cache.record_hard_block(start_url, blocking.details.get("reason", ""))
                        alternate_result = await _try_approved_alternate(blocking, "Navigation")
                        if alternate_result is not None:
                            return alternate_result

                return {
                    "status": error_status,
                    "records": [],
                    "documents": [],
                    "requires_manual_review": nav_result.get("requires_manual_review", True),
                    "message": f"Navigation ended with status: {nav_result['status']}",
                }

            active_analysis = nav_result["analysis"]
            active_target = nav_result.get("active_page", page)
            nav_path = nav_result.get("navigation_path", [])

            # Check if search is inside an iframe
            if active_analysis.iframe_selector:
                await _emit(f"Switching target context into iframe: {active_analysis.iframe_selector}")
                active_target = page.frame_locator(active_analysis.iframe_selector)

        # 3. Formulate Search Plan via Search Agent
        from app.drivers.dynamic_portal.search_agent import SearchAgent
        search_agent = SearchAgent()
        plan: SearchPlan = search_agent.plan_search(prop_input, active_analysis)

        if plan.status != "ready" or not plan.actions:
            await _emit(f"Search planning could not find matching input fields: {plan.reasoning}")
            return {
                "status": RunErrorStatus.NO_RESULTS,
                "records": [],
                "documents": [],
                "requires_manual_review": True,
                "message": plan.reasoning,
            }

        await _emit(f"Search strategy chosen: '{plan.strategy}' ({len(plan.actions)} structured actions)")

        # 4. Action Validator & Execution
        executed_successfully = True
        for action in plan.actions:
            await _emit(f"Executing action [{action.action}]: {action.description or action.selector}")
            result = await self.validator.execute_action(
                active_target, action, current_url=page.url
            )
            if not result.success:
                await _emit(f"Action validation / execution failed: {result.error_message}")
                executed_successfully = False
                break

        if not executed_successfully:
            # Trigger self-healing if selector failed
            if cached_mapping:
                await _emit("Cached action failed during execution. Triggering self-healing retry...")
                healed = await self.recovery.attempt_self_healing(
                    active_target, state, county, portal_type, cached_mapping
                )
                if healed:
                    # Retry once with newly healed mapping
                    return await self.execute_search(
                        page, start_url, prop_input, portal_type=portal_type,
                        status_emitter=status_emitter, run_id=run_id
                    )

            return {
                "status": RunErrorStatus.ACTION_VALIDATION_FAILED,
                "records": [],
                "documents": [],
                "requires_manual_review": True,
                "message": "Action validation failed during execution.",
            }

        # Polite wait for result loading
        await asyncio.sleep(2.0)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass

        # 5. Cloudflare / Blocking check post-submission
        post_state = await self.analyzer.capture_state(page)
        cf_check: DetectionResult = self.cf_detector.detect_blocking(
            url=post_state.url,
            title=post_state.title,
            visible_text=post_state.visible_text,
        )
        if cf_check.blocked:
            await _emit(f"Post-search blocking detected ({cf_check.type.value}).")
            if cf_check.type == BlockingType.ACCESS_DENIED:
                self.cache.record_hard_block(start_url, cf_check.details.get("reason", ""))
            alternate_result = await _try_approved_alternate(cf_check, "Search submission")
            if alternate_result is not None:
                return alternate_result
            return {
                "status": self.cf_detector.to_run_error_status(cf_check.type),
                "records": [],
                "documents": [],
                "requires_manual_review": True,
                "message": f"Blocked after search submission ({cf_check.type.value}): {cf_check.details.get('reason', 'manual review required')}",
            }

        # 6. Result Analysis
        result_eval: SearchResultAnalysis = self.result_analyzer.analyze_results(
            prop_input, post_state
        )
        await _emit(f"Result evaluation status: {result_eval.status.value} - {result_eval.message}")

        if result_eval.status != RunErrorStatus.SUCCESS:
            return {
                "status": result_eval.status,
                "records": [r.model_dump() for r in result_eval.records],
                "documents": [],
                "requires_manual_review": result_eval.requires_disambiguation or result_eval.status != RunErrorStatus.SUCCESS,
                "requires_disambiguation": result_eval.requires_disambiguation,
                "message": result_eval.message,
            }

        # 7. Document Discovery & Download (if recorder or relevant)
        downloaded_docs: List[DocumentItem] = []
        doc_candidates = self.doc_agent.identify_documents(post_state)
        if doc_candidates:
            await _emit(f"Discovered {len(doc_candidates)} document download link(s). Downloading...")
            for candidate in doc_candidates[:5]:  # Bounded download count
                dl_result = await self.doc_agent.download_document(page, candidate, run_id=run_id)
                if dl_result:
                    downloaded_docs.append(dl_result)
                    await _emit(f"Downloaded and validated {dl_result.document_type}: {dl_result.title}")

        # 8. Cache verified successful portal mapping for fast-path reuse
        try:
            self.cache.clear_hard_block(start_url)
            fields_dict = {k: v.model_dump() for k, v in active_analysis.search_fields.items()}
            fingerprint = self.cache.compute_fingerprint(page.url, post_state.title, post_state)
            mapping_to_save = PortalMapping(
                county=county,
                state=state,
                domain=fingerprint.domain,
                portal_type=portal_type,
                search_page_url=page.url,
                navigation_path=nav_path,
                search_fields=fields_dict,
                submit_selector=active_analysis.submit_button_selector,
                tab_selectors=active_analysis.tab_selectors,
                iframe_selector=active_analysis.iframe_selector,
                fingerprint=fingerprint,
            )
            self.cache.save_mapping(state, county, mapping_to_save)
        except Exception as save_err:
            logger.debug("Failed to cache successful mapping: %s", save_err)

        return {
            "status": RunErrorStatus.SUCCESS,
            "records": [r.model_dump() for r in result_eval.records],
            "best_match": result_eval.best_match.model_dump() if result_eval.best_match else None,
            "documents": [d.model_dump() for d in downloaded_docs],
            "requires_manual_review": False,
            "message": result_eval.message,
        }
