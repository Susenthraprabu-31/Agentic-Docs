"""Generate natural-language Playwright instructions by probing county portal pages."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from app.agents.county_resolver import CountyResolver
from app.config.settings import get_settings
from app.drivers.base.base_driver import BaseDriver
from app.drivers.netronline.netronline_driver import NETR_BASE, NetronlineDriver
from app.drivers.page_search_ai import PageSearchAI
from app.drivers.playwright_instructions import _click_by_visible_text, apply_playwright_instructions
from app.extraction.schemas import CountySources, QueryType

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCREENSHOTS_DIR = BACKEND_ROOT / "screenshots"

FIELD_LABELS = {
    QueryType.OWNER: "owner field",
    QueryType.PARCEL: "parcel field",
    QueryType.ADDRESS: "address field",
    QueryType.BOOK_PAGE: "book and page fields",
}

SYSTEM_PROMPT_INSTRUCTION_WRITER = """You analyze property county portal websites and write Playwright automation instructions for a human-readable instruction field.

Given:
- node_id: assessor | recorder | gis | tax | netr
- query_type: address | owner | parcel
- query_value: example search value used during the live probe
- actions_taken: steps already executed successfully during the probe (navigation, instructions, search)
- search_succeeded: whether the probe completed a search submit
- page snapshots: page snapshots before and after search
- resolved_url: county portal URL that was opened

Return ONLY valid JSON:
{
  "layout_type": "top_nav_landing | sidebar_nav | inline_form | tabbed_search | gated",
  "instructions": "Click Search Records and Tax Details, click parcel tab, fill parcel field, click Search, wait for results",
  "confidence": "high|medium|low",
  "reasoning": "one short sentence explaining the layout",
  "nav_click_text": "visible link/button text to open search, or null"
}

Rules for instructions text (must match our parser):
- Plain English steps separated by commas
- Use verbs: Click, fill, click Search, wait for results
- Prefer documenting actions_taken when search_succeeded is true
- For navigation links use exact visible link text from snapshots, NOT CSS selectors
- parcel query_type -> "parcel field" or "folio field"; owner -> "owner field"; address -> "address field"
- tabbed sites -> include "click {query_type} tab" before fill step
- If Cloudflare, terms modal, or captcha detected -> prefix with "Complete Cloudflare verification, then" or "Accept terms, then"
- Never invent link text not present in the snapshot elements
- Always end with "wait for results" when a search is submitted"""

SEARCH_NAV_KEYWORDS = (
    "search",
    "record",
    "tax detail",
    "property search",
    "parcel",
    "official record",
    "land record",
    "property record",
)


def _portal_type(node_id: str) -> str:
    if node_id == "recorder":
        return "recorder"
    return "assessor"


def _snapshot_has_search_inputs(snapshot: dict[str, Any]) -> bool:
    elements = snapshot.get("elements") or []
    return any(el.get("kind") == "input" for el in elements)


def _guess_nav_search_text(snapshot: dict[str, Any]) -> str | None:
    candidates: list[tuple[int, str]] = []
    for el in snapshot.get("elements") or []:
        tag = el.get("tag") or ""
        kind = el.get("kind") or ""
        if tag not in ("a", "button") and kind not in ("button", "search_button"):
            continue
        text = (el.get("text") or "").strip()
        if len(text) < 4:
            continue
        lower = text.lower()
        score = sum(1 for kw in SEARCH_NAV_KEYWORDS if kw in lower)
        if score > 0:
            candidates.append((score, text))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], -len(item[1])))
    return candidates[0][1]


def _selector_to_link_text(selector: str | None, snapshot: dict[str, Any]) -> str | None:
    if not selector or str(selector).strip().lower() in ("null", "none", ""):
        return None
    match = re.search(r':has-text\("([^"]+)"\)', str(selector))
    if match:
        return match.group(1).strip()
    sel_lower = str(selector).lower()
    for el in snapshot.get("elements") or []:
        el_sel = el.get("selector") or ""
        if el_sel == selector or el_sel.lower() == sel_lower:
            text = (el.get("text") or "").strip()
            if text:
                return text
    return None


def _plan_to_instruction_steps(
    plan: dict[str, Any],
    query_type: QueryType,
    snapshot: dict[str, Any],
) -> list[str]:
    steps: list[str] = []
    nav_text = _selector_to_link_text(plan.get("tab_selector"), snapshot)
    if nav_text:
        steps.append(f"Click {nav_text}")
    elif plan.get("tab_selector"):
        steps.append(f"click {query_type.value} tab")

    if plan.get("radio_selector"):
        radio_text = _selector_to_link_text(plan.get("radio_selector"), snapshot)
        if radio_text:
            steps.append(f"Click {radio_text}")

    steps.append(f"fill {FIELD_LABELS[query_type]}")
    steps.append("click Search")
    steps.append("wait for results")
    return steps


def _actions_to_instructions(actions: list[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for step in actions:
        cleaned = step.strip().rstrip(",")
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ", ".join(ordered)


def _resolve_portal_url(sources: CountySources, node_id: str) -> str | None:
    mapping = {
        "assessor": sources.assessor_url,
        "recorder": sources.recorder_url,
        "gis": sources.gis_url,
        "tax": sources.treasurer_url,
    }
    return mapping.get(node_id)


class InstructionWriterAI:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.page_ai = PageSearchAI()
        self._client: Any = None

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.openai_api_key)

    def _get_client(self) -> Any:
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not set in backend .env")
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.settings.openai_api_key)
        return self._client

    async def write_instructions(
        self,
        snapshots: list[dict[str, Any]],
        *,
        node_id: str,
        query_type: QueryType,
        query_value: str = "",
        actions_taken: list[str] | None = None,
        search_succeeded: bool = False,
        resolved_url: str = "",
        cloudflare_blocked: bool = False,
        terms_modal: bool = False,
    ) -> dict[str, Any]:
        if not self.is_configured:
            raise ValueError("OPENAI_API_KEY is not set in backend .env")

        if search_succeeded and actions_taken:
            deterministic = _actions_to_instructions(actions_taken)
            if deterministic:
                return {
                    "instructions": deterministic,
                    "layout_type": "inline_form" if _snapshot_has_search_inputs(snapshots[-1]) else "top_nav_landing",
                    "confidence": "high",
                    "reasoning": "Instructions recorded from successful Playwright probe search.",
                    "nav_click_text": None,
                }

        client = self._get_client()
        model_name = getattr(self.settings, "openai_browser_model", None) or "gpt-4o-mini"

        user_payload: dict[str, Any] = {
            "node_id": node_id,
            "query_type": query_type.value,
            "query_value": query_value,
            "pages": snapshots,
            "actions_taken": actions_taken or [],
            "search_succeeded": search_succeeded,
            "resolved_url": resolved_url,
            "cloudflare_detected": cloudflare_blocked,
            "terms_modal_detected": terms_modal,
        }

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model_name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_INSTRUCTION_WRITER},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            temperature=0.2,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        plan = json.loads(raw)
        instructions = str(plan.get("instructions") or "").strip()
        if not instructions:
            raise ValueError("AI did not return Playwright instructions")

        return {
            "instructions": instructions,
            "layout_type": str(plan.get("layout_type") or "inline_form"),
            "confidence": str(plan.get("confidence") or "medium"),
            "reasoning": str(plan.get("reasoning") or ""),
            "nav_click_text": plan.get("nav_click_text"),
        }


async def _probe_page(
    driver: BaseDriver,
    url: str,
) -> tuple[list[dict[str, Any]], bool, bool, list[str]]:
    """Navigate, optionally follow nav to search page, return snapshots + gate flags + actions."""
    actions: list[str] = []
    await driver.safe_goto(url, wait_selector="body")
    await driver.dismiss_netronline_modals()
    await driver.dismiss_schneider_terms()

    cloudflare_blocked = await driver.is_cloudflare_blocked()
    if cloudflare_blocked:
        cleared = await driver.wait_for_cloudflare_clear(max_wait=60)
        cloudflare_blocked = not cleared
        if cloudflare_blocked:
            actions.append("Complete Cloudflare verification")

    page_ai = PageSearchAI()
    snapshots: list[dict[str, Any]] = []
    snapshot1 = await page_ai.extract_snapshot(driver)
    snapshots.append(snapshot1)

    terms_modal = False
    try:
        content = (await driver.page.content()).lower()
        terms_modal = "terms and conditions" in content or "disclaimer" in content
        if terms_modal:
            actions.append("Accept terms")
    except Exception:
        pass

    if not _snapshot_has_search_inputs(snapshot1):
        nav_text = _guess_nav_search_text(snapshot1)
        if nav_text:
            clicked = await _click_by_visible_text(driver, nav_text)
            if clicked:
                actions.append(f"Click {nav_text}")
                await driver.polite_delay(1.5)
                await driver.dismiss_schneider_terms()
                snapshot2 = await page_ai.extract_snapshot(driver)
                snapshots.append(snapshot2)

    return snapshots, cloudflare_blocked, terms_modal, actions


async def _perform_search_probe(
    driver: BaseDriver,
    *,
    node_id: str,
    query_type: QueryType,
    query_value: str,
    playwright_notes: str | None,
    prior_actions: list[str],
) -> tuple[list[str], bool, dict[str, Any] | None]:
    """Run existing Playwright instructions first, then AI search; return actions + post-search snapshot."""
    actions = list(prior_actions)
    portal = _portal_type(node_id)
    notes = (playwright_notes or "").strip()
    page_ai = PageSearchAI()

    if notes:
        await driver._emit_status("Running Playwright instructions before writing new steps...")
        if await apply_playwright_instructions(
            driver,
            notes,
            query_type,
            query_value,
            portal_type=portal,
        ):
            if notes not in actions:
                actions.append(notes)

    if not query_value.strip():
        return actions, False, None

    await driver._emit_status(f"Probing search with {query_type.value} value from Input node...")
    snapshot = await page_ai.extract_snapshot(driver)
    if not snapshot.get("elements"):
        return actions, False, None

    plan = await page_ai.plan_search(
        snapshot,
        query_type,
        query_value,
        portal_type=portal,
        user_instructions=notes or None,
    )
    if not plan:
        return actions, False, snapshot

    search_ok = await page_ai.execute_plan(driver, plan, query_value)
    if search_ok:
        for step in _plan_to_instruction_steps(plan, query_type, snapshot):
            if step not in actions:
                actions.append(step)
        await driver.polite_delay(2.0)
        post_snapshot = await page_ai.extract_snapshot(driver)
        return actions, True, post_snapshot

    return actions, False, snapshot


async def _resolve_target_url(
    driver: NetronlineDriver,
    resolver: CountyResolver,
    *,
    node_id: str,
    state: str,
    county: str,
    url_override: str | None,
) -> str:
    if url_override and url_override.strip():
        return url_override.strip()

    if node_id == "netr":
        state_slug = state.strip().upper()
        county_slug = county.strip().lower().replace(" ", "-")
        return f"{NETR_BASE}/state/{state_slug}/county/{county_slug}"

    sources = await resolver.resolve(state, county)
    portal_url = _resolve_portal_url(sources, node_id)
    if not portal_url:
        raise ValueError(
            f"No {node_id} URL found for {county}, {state}. "
            "Set a URL on the node or pick a county in the Input node."
        )
    return portal_url


async def generate_playwright_instructions(
    *,
    node_id: str,
    state: str,
    county: str,
    query_type: QueryType,
    url: str | None = None,
    query_value: str = "",
    playwright_notes: str | None = None,
) -> dict[str, Any]:
    """Open county portal URL, run search probe, return instruction text."""
    valid_nodes = {"assessor", "recorder", "gis", "tax", "netr"}
    if node_id not in valid_nodes:
        raise ValueError(f"Unsupported node_id: {node_id}")

    if not county.strip():
        raise ValueError("County is required — set it in the Input node.")

    if node_id != "netr" and not query_value.strip():
        raise ValueError("Search value is required — set it in the Input node before generating instructions.")

    writer = InstructionWriterAI()
    if not writer.is_configured:
        raise ValueError("OPENAI_API_KEY is not set in backend .env")

    driver = NetronlineDriver(screenshot_dir=SCREENSHOTS_DIR)
    try:
        await driver.start()
        resolver = CountyResolver(driver)
        target_url = await _resolve_target_url(
            driver,
            resolver,
            node_id=node_id,
            state=state,
            county=county,
            url_override=url,
        )

        snapshots, cloudflare_blocked, terms_modal, nav_actions = await _probe_page(driver, target_url)

        search_actions, search_succeeded, post_snapshot = await _perform_search_probe(
            driver,
            node_id=node_id,
            query_type=query_type,
            query_value=query_value,
            playwright_notes=playwright_notes,
            prior_actions=nav_actions,
        )
        if post_snapshot:
            snapshots.append(post_snapshot)

        result = await writer.write_instructions(
            snapshots,
            node_id=node_id,
            query_type=query_type,
            query_value=query_value,
            actions_taken=search_actions,
            search_succeeded=search_succeeded,
            resolved_url=target_url,
            cloudflare_blocked=cloudflare_blocked,
            terms_modal=terms_modal,
        )
        result["resolved_url"] = target_url
        result["search_succeeded"] = search_succeeded

        if cloudflare_blocked and not result["instructions"].lower().startswith("complete cloudflare"):
            result["instructions"] = (
                "Complete Cloudflare verification, then " + result["instructions"]
            )
            result["layout_type"] = "gated"

        return result
    finally:
        await driver.stop()
