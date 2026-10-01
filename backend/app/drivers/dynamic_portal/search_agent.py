"""Search Agent: Selects optimal search strategy and emits structured browser actions."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.drivers.dynamic_portal.schemas import (
    BrowserAction,
    CompactBrowserState,
    PortalAnalysis,
    PropertySearchInput,
    SearchPlan,
)

logger = logging.getLogger(__name__)


class SearchAgent:
    """Formulates structured action plans for property searches based on portal layout."""

    def plan_search(
        self,
        prop_input: PropertySearchInput,
        analysis: PortalAnalysis,
        browser_state: Optional[CompactBrowserState] = None,
    ) -> SearchPlan:
        """
        Produce structured actions according to the strict priority strategy:
        1. Parcel / APN / Folio
        2. Property Address
        3. Owner Name
        4. Account Number / other verified identifier
        """
        actions: List[BrowserAction] = []
        fields = analysis.search_fields
        tabs = analysis.tab_selectors

        # 1. Check Parcel / APN / Folio
        effective_parcel = prop_input.get_effective_parcel()
        if effective_parcel and ("parcel" in fields or "folio" in fields or "account" in fields):
            field_key = "parcel" if "parcel" in fields else ("folio" if "folio" in fields else "account")
            mapping = fields[field_key]

            # If a tab is required to activate parcel search, click it first
            if "parcel" in tabs and tabs["parcel"]:
                actions.append(
                    BrowserAction(
                        action="click",
                        selector=tabs["parcel"],
                        description="Switch to Parcel/Folio search tab",
                    )
                )
                actions.append(BrowserAction(action="wait", timeout_ms=500))

            # Fill parcel field
            actions.append(
                BrowserAction(
                    action="fill",
                    selector=mapping.selector,
                    value=effective_parcel,
                    description=f"Fill {mapping.label or 'Parcel Number'} with {effective_parcel}",
                )
            )

            # Click search/submit
            if analysis.submit_button_selector:
                actions.append(
                    BrowserAction(
                        action="click",
                        selector=analysis.submit_button_selector,
                        description="Click search submit button",
                    )
                )

            return SearchPlan(
                status="ready",
                strategy="parcel",
                actions=actions,
                reasoning=f"Using primary parcel search for '{effective_parcel}' using selector {mapping.selector}.",
            )

        # 2. Check Address
        if prop_input.address and "address" in fields:
            mapping = fields["address"]

            if "address" in tabs and tabs["address"]:
                actions.append(
                    BrowserAction(
                        action="click",
                        selector=tabs["address"],
                        description="Switch to Address search tab",
                    )
                )
                actions.append(BrowserAction(action="wait", timeout_ms=500))

            actions.append(
                BrowserAction(
                    action="fill",
                    selector=mapping.selector,
                    value=prop_input.address,
                    description=f"Fill Address with '{prop_input.address}'",
                )
            )

            if analysis.submit_button_selector:
                actions.append(
                    BrowserAction(
                        action="click",
                        selector=analysis.submit_button_selector,
                        description="Click search submit button",
                    )
                )

            return SearchPlan(
                status="ready",
                strategy="address",
                actions=actions,
                reasoning=f"Using address search for '{prop_input.address}' using selector {mapping.selector}.",
            )

        # 3. Check Owner Name
        if prop_input.ownerName and "owner" in fields:
            mapping = fields["owner"]

            if "owner" in tabs and tabs["owner"]:
                actions.append(
                    BrowserAction(
                        action="click",
                        selector=tabs["owner"],
                        description="Switch to Owner Name search tab",
                    )
                )
                actions.append(BrowserAction(action="wait", timeout_ms=500))

            actions.append(
                BrowserAction(
                    action="fill",
                    selector=mapping.selector,
                    value=prop_input.ownerName,
                    description=f"Fill Owner Name with '{prop_input.ownerName}'",
                )
            )

            if analysis.submit_button_selector:
                actions.append(
                    BrowserAction(
                        action="click",
                        selector=analysis.submit_button_selector,
                        description="Click search submit button",
                    )
                )

            return SearchPlan(
                status="ready",
                strategy="owner",
                actions=actions,
                reasoning=f"Using owner search for '{prop_input.ownerName}' using selector {mapping.selector}.",
            )

        # If a generic single search input is available (e.g. unified search bar)
        if len(fields) == 1:
            field_key = list(fields.keys())[0]
            mapping = fields[field_key]
            val_to_use = effective_parcel or prop_input.address or prop_input.ownerName
            if val_to_use:
                actions.append(
                    BrowserAction(
                        action="fill",
                        selector=mapping.selector,
                        value=val_to_use,
                        description=f"Fill search field with '{val_to_use}'",
                    )
                )
                if analysis.submit_button_selector:
                    actions.append(
                        BrowserAction(
                            action="click",
                            selector=analysis.submit_button_selector,
                            description="Click search submit button",
                        )
                    )
                return SearchPlan(
                    status="ready",
                    strategy=field_key,
                    actions=actions,
                    reasoning=f"Filled unified search input with '{val_to_use}'.",
                )

        return SearchPlan(
            status="cannot_search",
            strategy=None,
            actions=[],
            reasoning="Portal fields do not match provided property input identifiers.",
        )
