"""Navigation Agent: Discovers county property search locations with bounded safety."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

from app.drivers.dynamic_portal.cloudflare_detector import CloudflareDetector
from app.drivers.dynamic_portal.portal_analyzer import PortalAnalyzer
from app.drivers.dynamic_portal.schemas import (
    CompactBrowserState,
    CompactElement,
    DetectionResult,
    PortalAnalysis,
    RunErrorStatus,
)

logger = logging.getLogger(__name__)

# Search navigation target keywords weighted by relevance
PRIMARY_SEARCH_KEYWORDS = [
    ("real estate search", 100),
    ("property search", 95),
    ("parcel search", 95),
    ("property records", 90),
    ("real estate", 85),
    ("property lookup", 85),
    ("advanced search", 80),
    ("assessor", 75),
    ("recorder", 75),
    ("search property", 75),
    ("tax search", 70),
    ("official records", 70),
    ("gis mapping", 65),
    ("parcel map", 65),
    ("public records", 60),
    ("records", 50),
    ("search", 40),
]

DISQUALIFIED_LINK_KEYWORDS = [
    "privacy policy", "terms of use", "contact us", "departments",
    "careers", "employment", "calendar", "meetings", "elections",
    "sheriff", "police", "parks", "library", "health", "covid", "faq"
]


class NavigationAgent:
    """Explores county sites safely to discover property search forms."""

    def __init__(
        self,
        max_depth: int = 5,
        max_pages: int = 15,
        max_time_seconds: int = 120,
    ) -> None:
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.max_time_seconds = max_time_seconds
        self.visited_urls: Set[str] = set()
        self.navigation_path: List[str] = []
        self.analyzer = PortalAnalyzer()
        self.cf_detector = CloudflareDetector()

    def score_link(self, link: CompactElement, current_url: str) -> int:
        """Score link relevance for property search discovery."""
        text = (link.text or "").lower().strip()
        aria = (link.aria_label or "").lower().strip()
        href = (link.href or "").lower().strip()

        combined = f"{text} {aria} {href}"

        # Negative filter
        if any(bad in combined for bad in DISQUALIFIED_LINK_KEYWORDS):
            return -100

        score = 0
        for kw, weight in PRIMARY_SEARCH_KEYWORDS:
            if kw in text:
                score += weight
            elif kw in aria:
                score += int(weight * 0.9)
            elif kw in href:
                score += int(weight * 0.6)

        # Bonus for links staying within government/official records domain
        parsed = urlparse(href)
        if parsed.netloc and any(gov in parsed.netloc for gov in [".gov", ".us", ".org", "qpublic", "schneidercorp", "beacon"]):
            score += 10

        return score

    async def discover_search_page(
        self,
        page: Any,
        start_url: str,
        portal_type: str = "assessor",
        status_emitter: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Navigate from start_url until a search page is found or boundaries are hit.
        Returns:
            {
                "status": "search_found" | "navigation_limit_reached" | "blocked" | "failed",
                "search_url": str,
                "analysis": PortalAnalysis,
                "navigation_path": list[str],
                "active_page_or_frame": Page/Frame,
            }
        """
        async def _emit(msg: str):
            if status_emitter:
                res = status_emitter(msg)
                if asyncio.iscoroutine(res):
                    await res

        deadline = time.monotonic() + self.max_time_seconds
        current_depth = 0
        pages_visited = 0
        active_target = page

        # Ensure start page is open
        try:
            curr_url = page.url
            if not curr_url or curr_url == "about:blank":
                await _emit(f"Opening initial portal URL: {start_url}")
                await page.goto(start_url, wait_until="domcontentloaded", timeout=45_000)
            self.visited_urls.add(page.url.rstrip("/"))
        except Exception as exc:
            logger.warning("Initial navigation failed: %s", exc)
            return {
                "status": "failed",
                "error": str(exc),
                "error_status": RunErrorStatus.NETWORK_ERROR,
                "navigation_path": self.navigation_path,
            }

        while current_depth < self.max_depth and pages_visited < self.max_pages:
            if time.monotonic() > deadline:
                await _emit("Navigation time limit exceeded.")
                return {
                    "status": "navigation_limit_reached",
                    "requires_manual_review": True,
                    "error_status": RunErrorStatus.NAVIGATION_LIMIT_REACHED,
                    "navigation_path": self.navigation_path,
                }

            pages_visited += 1
            current_url = active_target.url
            title = await active_target.title()

            # 1. Cloudflare / Blocking check
            text_body = await active_target.evaluate("() => document.body ? document.body.innerText : ''")
            cf_result: DetectionResult = self.cf_detector.detect_blocking(
                url=current_url,
                title=title,
                visible_text=text_body,
            )
            if cf_result.blocked:
                await _emit(f"Blocking detected ({cf_result.type.value}) - stopping automated navigation.")
                return {
                    "status": "blocked",
                    "blocking_result": cf_result,
                    "error_status": self.cf_detector.to_run_error_status(cf_result.type),
                    "requires_manual_review": True,
                    "navigation_path": self.navigation_path,
                }

            # 2. Portal Analysis of current page
            state: CompactBrowserState = await self.analyzer.capture_state(active_target)
            analysis: PortalAnalysis = await self.analyzer.analyze(state, portal_type=portal_type)

            # Check if property search fields exist on current page!
            if analysis.is_search_page:
                await _emit(f"Property search functionality found at {current_url}")
                return {
                    "status": "search_found",
                    "search_url": current_url,
                    "analysis": analysis,
                    "navigation_path": self.navigation_path,
                    "active_page": active_target,
                    "browser_state": state,
                }

            # Check if an iframe contains search fields
            for ifr in state.iframes:
                try:
                    frame = active_target.frame_locator(ifr.selector)
                    # Inspect iframe interior
                    has_input = await frame.locator('input:not([type="hidden"])').count() > 0
                    if has_input:
                        await _emit(f"Property search found inside iframe ({ifr.selector})")
                        analysis.iframe_selector = ifr.selector
                        analysis.is_search_page = True
                        return {
                            "status": "search_found",
                            "search_url": current_url,
                            "analysis": analysis,
                            "navigation_path": self.navigation_path,
                            "active_page": active_target,
                            "iframe_selector": ifr.selector,
                            "browser_state": state,
                        }
                except Exception:
                    pass

            # 3. Not a search page yet -> Pick best navigation link
            scored_links: List[tuple[int, CompactElement]] = []
            for link in state.links:
                href = link.href or ""
                resolved = urljoin(current_url, href).rstrip("/")
                if resolved in self.visited_urls:
                    continue
                score = self.score_link(link, current_url)
                if score > 0:
                    scored_links.append((score, link))

            if not scored_links:
                # Also check buttons that might say "Search Records" or "Property Search"
                for btn in state.buttons:
                    score = self.score_link(btn, current_url)
                    if score > 0:
                        scored_links.append((score, btn))

            if not scored_links:
                await _emit("No relevant property search links found from this page.")
                return {
                    "status": "search_not_found",
                    "requires_manual_review": True,
                    "error_status": RunErrorStatus.NAVIGATION_FAILED,
                    "navigation_path": self.navigation_path,
                }

            # Sort descending by score
            scored_links.sort(key=lambda x: x[0], reverse=True)
            best_score, best_element = scored_links[0]
            target_label = best_element.text or best_element.aria_label or best_element.selector

            await _emit(f"Navigating: Clicking '{target_label}' (relevance score: {best_score})")
            self.navigation_path.append(target_label)

            # Click link while watching for new tabs/popups
            try:
                context = page.context if hasattr(page, "context") else None
                new_page_promise = None
                if context:
                    new_page_promise = context.wait_for_event("page", timeout=5000)

                clicked = False
                loc = active_target.locator(best_element.selector).first
                if await loc.count() > 0:
                    await loc.click(timeout=10_000)
                    clicked = True

                # Check if a new tab opened
                if new_page_promise:
                    try:
                        new_tab = await new_page_promise
                        await new_tab.wait_for_load_state("domcontentloaded", timeout=15_000)
                        active_target = new_tab
                        await _emit(f"Search opened in new tab: {new_tab.url}")
                    except Exception:
                        pass

                if clicked:
                    try:
                        await active_target.wait_for_load_state("domcontentloaded", timeout=15_000)
                    except Exception:
                        pass
                    await asyncio.sleep(1.0)
                    self.visited_urls.add(active_target.url.rstrip("/"))
                    current_depth += 1
                else:
                    break

            except Exception as nav_err:
                logger.warning("Clicking navigation link failed: %s", nav_err)
                break

        # If loops end without finding search page
        return {
            "status": "navigation_limit_reached",
            "requires_manual_review": True,
            "error_status": RunErrorStatus.NAVIGATION_LIMIT_REACHED,
            "navigation_path": self.navigation_path,
        }
