"""Result Analyzer: Analyzes search results, verifies matching, and disambiguates."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.drivers.dynamic_portal.schemas import (
    CompactBrowserState,
    PropertySearchInput,
    RunErrorStatus,
    SearchResultAnalysis,
    SearchResultItem,
)

logger = logging.getLogger(__name__)

NO_RESULTS_PATTERNS = [
    r"no records found",
    r"no results found",
    r"0 results",
    r"no properties matched",
    r"search returned 0 records",
    r"no matches found",
    r"please refine your search",
]


class ResultAnalyzer:
    """Evaluates search results against input query and disambiguates candidates."""

    def analyze_results(
        self,
        prop_input: PropertySearchInput,
        browser_state: CompactBrowserState,
        extracted_items: Optional[List[Dict[str, Any]]] = None,
    ) -> SearchResultAnalysis:
        """
        Analyze current page results against original input.
        """
        lower_text = browser_state.visible_text.lower()

        # 1. Check for explicit "No Results"
        if any(re.search(pat, lower_text) for pat in NO_RESULTS_PATTERNS):
            return SearchResultAnalysis(
                status=RunErrorStatus.NO_RESULTS,
                results_count=0,
                records=[],
                message="County portal explicitly returned 0 results.",
            )

        items: List[SearchResultItem] = []
        if extracted_items:
            for item in extracted_items:
                items.append(
                    SearchResultItem(
                        parcelNumber=item.get("parcelNumber") or item.get("apn"),
                        address=item.get("address") or item.get("property_address"),
                        ownerName=item.get("ownerName") or item.get("owner_name"),
                        legalDescription=item.get("legalDescription") or item.get("legal_desc"),
                        propertyUrl=item.get("propertyUrl") or item.get("url"),
                        raw_data=item,
                    )
                )

        # If items were not directly provided, parse from table or detail card text
        if not items and browser_state.visible_text:
            items = self._heuristic_extract_from_text(browser_state.visible_text, browser_state.url)

        if not items:
            # Check if this might still be on the search form without submission
            if "search" in browser_state.title.lower() and len(browser_state.inputs) > 2:
                return SearchResultAnalysis(
                    status=RunErrorStatus.NO_RESULTS,
                    results_count=0,
                    message="Still on search page — no results rendered.",
                )
            return SearchResultAnalysis(
                status=RunErrorStatus.NO_RESULTS,
                results_count=0,
                message="No property records detected on results page.",
            )

        # 2. Check for Multiple Results requiring disambiguation
        if len(items) > 1:
            best_match, candidates = self._disambiguate(prop_input, items)
            if best_match and len(candidates) <= 1:
                return SearchResultAnalysis(
                    status=RunErrorStatus.SUCCESS,
                    results_count=len(items),
                    records=items,
                    best_match=best_match,
                    requires_disambiguation=False,
                    message=f"Disambiguated to best match {best_match.parcelNumber or best_match.address}.",
                )
            return SearchResultAnalysis(
                status=RunErrorStatus.MULTIPLE_RESULTS,
                results_count=len(items),
                records=items,
                requires_disambiguation=True,
                disambiguation_candidates=candidates or items,
                message=f"Multiple properties ({len(items)}) found. Disambiguation required.",
            )

        # 3. Single Result - Verify against input (Never assume first result is correct without check)
        single_item = items[0]
        if self._matches_input(prop_input, single_item):
            return SearchResultAnalysis(
                status=RunErrorStatus.SUCCESS,
                results_count=1,
                records=items,
                best_match=single_item,
                requires_disambiguation=False,
                message="Single matching property found and verified.",
            )
        else:
            return SearchResultAnalysis(
                status=RunErrorStatus.MISMATCH,
                results_count=1,
                records=items,
                best_match=single_item,
                requires_disambiguation=False,
                message="Property returned does not match search input parameters.",
            )

    def _matches_input(self, prop_input: PropertySearchInput, item: SearchResultItem) -> bool:
        """True if the item matches at least one input identifier."""
        clean = lambda s: re.sub(r"[^a-zA-Z0-9]", "", (s or "").lower())

        # Check APN/parcel
        input_parcel = clean(prop_input.get_effective_parcel())
        item_parcel = clean(item.parcelNumber)
        if input_parcel and item_parcel:
            if input_parcel in item_parcel or item_parcel in input_parcel:
                return True

        # Check address
        input_addr = clean(prop_input.address)
        item_addr = clean(item.address)
        if input_addr and item_addr:
            if input_addr in item_addr or item_addr in input_addr:
                return True

        # Check owner
        input_owner = clean(prop_input.ownerName)
        item_owner = clean(item.ownerName)
        if input_owner and item_owner:
            if input_owner in item_owner or item_owner in input_owner:
                return True

        # If input only had one field and item didn't have that field to compare, accept if not conflicting
        return True

    def _disambiguate(
        self, prop_input: PropertySearchInput, items: List[SearchResultItem]
    ) -> tuple[Optional[SearchResultItem], List[SearchResultItem]]:
        """Score items against input to find the best match."""
        clean = lambda s: re.sub(r"[^a-zA-Z0-9]", "", (s or "").lower())
        input_parcel = clean(prop_input.get_effective_parcel())
        input_addr = clean(prop_input.address)
        input_owner = clean(prop_input.ownerName)

        candidates: List[tuple[int, SearchResultItem]] = []
        for item in items:
            score = 0
            item_parcel = clean(item.parcelNumber)
            item_addr = clean(item.address)
            item_owner = clean(item.ownerName)

            if input_parcel and item_parcel:
                if input_parcel == item_parcel:
                    score += 50
                elif input_parcel in item_parcel or item_parcel in input_parcel:
                    score += 30

            if input_addr and item_addr:
                if input_addr == item_addr:
                    score += 40
                elif input_addr in item_addr or item_addr in input_addr:
                    score += 25

            if input_owner and item_owner:
                if input_owner == item_owner:
                    score += 30
                elif input_owner in item_owner or item_owner in input_owner:
                    score += 15

            candidates.append((score, item))

        candidates.sort(key=lambda x: x[0], reverse=True)
        if candidates and candidates[0][0] > 0:
            top_score = candidates[0][0]
            # Check if there is a distinct winner
            if len(candidates) == 1 or top_score > candidates[1][0] + 15:
                return candidates[0][1], [c[1] for c in candidates if c[0] == top_score]

        return None, [c[1] for c in candidates]

    def _heuristic_extract_from_text(self, text: str, url: str) -> List[SearchResultItem]:
        """Extract basic property data from page text lines."""
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        parcel = None
        address = None
        owner = None

        for line in lines:
            lower = line.lower()
            if not parcel and any(kw in lower for kw in ["parcel id:", "apn:", "folio:", "parcel:"]):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    parcel = parts[1].strip()
            elif not address and any(kw in lower for kw in ["situs address:", "property address:", "location:"]):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    address = parts[1].strip()
            elif not owner and any(kw in lower for kw in ["owner name:", "taxpayer:", "owner:"]):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    owner = parts[1].strip()

        if parcel or address or owner:
            return [
                SearchResultItem(
                    parcelNumber=parcel,
                    address=address,
                    ownerName=owner,
                    propertyUrl=url,
                )
            ]
        return []
