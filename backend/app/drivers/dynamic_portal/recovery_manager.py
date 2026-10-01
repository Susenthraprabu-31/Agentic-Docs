"""Recovery Manager: Orchestrates self-healing, alternate sources, and safe blocking exits."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.drivers.dynamic_portal.cloudflare_detector import CloudflareDetector
from app.drivers.dynamic_portal.portal_analyzer import PortalAnalyzer
from app.drivers.dynamic_portal.portal_cache import PortalCache
from app.drivers.dynamic_portal.schemas import (
    BlockingType,
    CompactBrowserState,
    DetectionResult,
    PortalAnalysis,
    PortalMapping,
    RunErrorStatus,
)

logger = logging.getLogger(__name__)


class RecoveryManager:
    """Coordinates self-healing on selector failure, alternate portal selection, and safe exits."""

    def __init__(self, portal_cache: Optional[PortalCache] = None) -> None:
        self.cache = portal_cache or PortalCache()
        self.analyzer = PortalAnalyzer()
        self.cf_detector = CloudflareDetector()

    async def attempt_self_healing(
        self,
        page_or_frame: Any,
        state: str,
        county: str,
        portal_type: str,
        cached_mapping: PortalMapping,
    ) -> Optional[PortalMapping]:
        """
        Self-healing flow:
        1. Invalidate stale cache
        2. Re-analyze active page with PortalAnalyzer
        3. Verify new selectors
        4. If verified, update cache and return new mapping
        5. If re-analysis fails, return None (triggers manual review)
        """
        logger.info("Triggering self-healing for %s %s (%s)...", county, state, portal_type)
        self.cache.invalidate(state, county, portal_type)

        browser_state: CompactBrowserState = await self.analyzer.capture_state(page_or_frame)
        new_analysis: PortalAnalysis = await self.analyzer.analyze(browser_state, portal_type=portal_type)

        if not new_analysis.is_search_page or not new_analysis.search_fields:
            logger.warning("Self-healing re-analysis could not identify valid search fields.")
            return None

        # Build updated mapping
        search_fields_dict = {
            k: v.model_dump() for k, v in new_analysis.search_fields.items()
        }
        new_fingerprint = self.cache.compute_fingerprint(
            browser_state.url, browser_state.title, browser_state
        )

        updated_mapping = PortalMapping(
            county=county,
            state=state,
            domain=new_fingerprint.domain,
            portal_type=portal_type,
            search_page_url=browser_state.url,
            navigation_path=cached_mapping.navigation_path,
            search_fields=search_fields_dict,
            submit_selector=new_analysis.submit_button_selector,
            tab_selectors=new_analysis.tab_selectors,
            iframe_selector=new_analysis.iframe_selector,
            fingerprint=new_fingerprint,
        )

        # Validate before saving
        is_valid = await self.cache.validate_cached_mapping(
            updated_mapping, page_or_frame, browser_state
        )
        if is_valid:
            self.cache.save_mapping(state, county, updated_mapping)
            logger.info("Self-healing successful. New mapping saved for %s %s.", county, state)
            return updated_mapping

        logger.warning("Newly generated self-healing mapping failed validation.")
        return None

    def find_approved_alternate_source(
        self,
        current_url: str,
        alternate_urls: List[str],
    ) -> Optional[str]:
        """
        Checks whether an approved alternate portal/source exists when current source is blocked.
        """
        clean = lambda u: (u or "").strip().rstrip("/")
        curr = clean(current_url)
        for alt in alternate_urls:
            candidate = clean(alt)
            if candidate and candidate != curr:
                return candidate
        return None
