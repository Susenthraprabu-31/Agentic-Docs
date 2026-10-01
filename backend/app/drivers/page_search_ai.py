"""Use GPT to analyze a loaded page and perform property search actions."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any, Optional

from app.agents.llm_client import chat_completions_create
from app.config.settings import get_settings
from app.extraction.schemas import QueryType

if TYPE_CHECKING:
    from app.drivers.base.base_driver import BaseDriver

logger = logging.getLogger(__name__)

PAGE_SNAPSHOT_JS = """
() => {
  const out = [];
  const seen = new Set();

  function esc(s) {
    return (s || '').replace(/\\\\/g, '\\\\').replace(/"/g, '\\\\"').trim();
  }

  function selectorFor(el) {
    if (!el || el.offsetParent === null && getComputedStyle(el).display === 'none') return null;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.opacity === '0') return null;

    if (el.id && !/^\\d/.test(el.id)) return `#${CSS.escape(el.id)}`;

    const role = el.getAttribute('role');
    const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 60);
    if (role === 'tab' && text) return `[role="tab"]:has-text("${esc(text)}")`;

    if (el.getAttribute('aria-hidden') === 'true') return null;
    if ((el.className || '').match(/cssDebug|cssNoPrint/i)) return null;
    if (el.id && /debug/i.test(el.id)) return null;

    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      const type = (el.type || 'text').toLowerCase();
      if (type === 'hidden' || type === 'checkbox' || type === 'radio') return null;
      const ph = el.getAttribute('placeholder');
      if (ph) return `${el.tagName.toLowerCase()}[placeholder="${esc(ph)}"]`;
      const name = el.getAttribute('name');
      if (name) return `${el.tagName.toLowerCase()}[name="${esc(name)}"]`;
      const fc = el.getAttribute('formcontrolname');
      if (fc) return `input[formcontrolname="${esc(fc)}"]`;
      const aria = el.getAttribute('aria-label');
      if (aria) return `${el.tagName.toLowerCase()}[aria-label="${esc(aria)}"]`;
    }

    if ((el.tagName === 'BUTTON' || el.tagName === 'A' || el.tagName === 'SPAN') && text) {
      const lower = text.toLowerCase();
      if (lower.length <= 40 && /search|address|owner|folio|parcel|submit|go|find|book|page|reset/i.test(lower)) {
        return `${el.tagName.toLowerCase()}:has-text("${esc(text)}")`;
      }
    }

    const aria = el.getAttribute('aria-label');
    if (aria && /search/i.test(aria)) {
      return `[aria-label="${esc(aria)}"]`;
    }
    return null;
  }

  function push(el, kind) {
    const sel = selectorFor(el);
    if (!sel || seen.has(sel)) return;
    seen.add(sel);
    const text = (el.innerText || el.textContent || el.value || '').replace(/\\s+/g, ' ').trim().slice(0, 80);
    const placeholder = el.getAttribute('placeholder') || '';
    const name = el.getAttribute('name') || '';
    const role = el.getAttribute('role') || '';
    out.push({
      kind,
      selector: sel,
      tag: el.tagName.toLowerCase(),
      text,
      placeholder,
      name,
      role,
      type: el.type || '',
    });
  }

  document.querySelectorAll('[role="tab"], mat-tab, .mat-tab-label, button, a, input, textarea, select, label, [aria-label]').forEach((el) => {
    try {
      const rect = el.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2) return;
      if (rect.bottom < 0 || rect.top > innerHeight * 2) return;
      let kind = 'control';
      const role = el.getAttribute('role');
      const tag = el.tagName;
      if (role === 'tab' || tag === 'MAT-TAB') kind = 'tab';
      else if (tag === 'INPUT' && (el.type || '').toLowerCase() === 'radio') kind = 'radio';
      else if (tag === 'INPUT' || tag === 'TEXTAREA') kind = 'input';
      else if (/search/i.test(el.innerText || '') || /search/i.test(el.getAttribute('aria-label') || '')) kind = 'search_button';
      else if (tag === 'BUTTON' || tag === 'A') kind = 'button';
      else if (tag === 'LABEL') kind = 'label';
      push(el, kind);
    } catch (_) {}
  });

  return {
    url: location.href,
    title: document.title,
    elements: out.slice(0, 100),
  };
}
"""

SYSTEM_PROMPT_ASSESSOR = """You analyze property appraiser / assessor websites and return Playwright CSS selectors to run a search.

Given:
- query_type: address | owner | parcel (parcel may be labeled folio, APN, TMK, PIN, strap, etc.)
- query_value: the value to search for
- page snapshot: visible tabs, inputs, and buttons with suggested selectors

Return ONLY valid JSON:
{
  "tab_selector": "selector to click the correct search tab, or null if not needed",
  "radio_selector": "selector for radio option if needed, or null",
  "input_selector": "selector for the text field to fill",
  "submit_selector": "selector for search/submit button, or null to press Enter",
  "use_enter_key": false,
  "confidence": "high|medium|low",
  "reasoning": "one short sentence"
}

Rules:
- Match query_type to the correct tab/field (address -> address field, parcel -> folio/parcel field, owner -> owner name field).
- Prefer selectors from the snapshot exactly as given.
- Use tab_selector when the site has separate tabs for Address, Owner, Folio/Parcel.
- When user_instructions say to click a menu or nav link first (e.g. "Search Records and Tax Details"), set tab_selector to that link/button from the snapshot before filling a field.
- If the page is a landing page with no search input yet, set input_selector to null and tab_selector to the nav link that opens search.
- submit_selector can be a magnifying glass button or img with search alt text.
- Never invent selectors not based on snapshot elements."""

SYSTEM_PROMPT_RECORDER = """You analyze county clerk / official records / recorder websites and decide which fields the loaded page is asking for.

Given:
- available_values: book, page, owner, parcel, address, query_value (some may be empty)
- query_type: address | owner | parcel | book_page  (hint only — trust the visible form more)
- page snapshot: visible nav links, inputs, radios, and buttons with selectors

Return ONLY valid JSON:
{
  "search_kind": "book_page|owner|parcel|address|instrument",
  "tab_selector": "selector to open the matching search menu/tab, or null",
  "radio_selector": "selector for Grantor/Grantee/All radio if needed, or null",
  "fills": [
    {"selector": "css selector from snapshot", "value_key": "book|page|owner|parcel|address|query_value"}
  ],
  "input_selector": "legacy single-field selector, or null when fills is used",
  "submit_selector": "Search button selector, or null to press Enter",
  "use_enter_key": false,
  "confidence": "high|medium|low",
  "reasoning": "one short sentence"
}

Rules:
- Match the VISIBLE form, not query_type. If the heading or labels say Recording Book/Page, BOOK, PAGE — search_kind MUST be book_page.
- For book_page: fill the book field with available_values.book and the page field with available_values.page. NEVER put parcel, folio, or address into a book or page input.
- If the form asks for folio/parcel/APN, use parcel. If it asks for name/grantor/grantee/party, use owner.
- If Book/Page fields are visible and book+page values are provided, prefer book_page even when query_type is address or parcel.
- Prefer selectors from the snapshot exactly as given.
- Never invent selectors not based on snapshot elements.
- Do not submit until the correct fields are identified."""

SYSTEM_PROMPT = SYSTEM_PROMPT_ASSESSOR


class PageSearchAI:
    def __init__(self) -> None:
        self.settings = get_settings()
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

    async def extract_snapshot(self, driver: "BaseDriver") -> dict[str, Any]:
        try:
            return await driver.page.evaluate(PAGE_SNAPSHOT_JS)
        except Exception as exc:
            logger.warning("Page snapshot failed: %s", exc)
            return {"url": driver.page.url, "title": "", "elements": []}

    async def plan_search(
        self,
        snapshot: dict[str, Any],
        query_type: QueryType,
        query_value: str,
        *,
        model: Optional[str] = None,
        portal_type: str = "assessor",
        user_instructions: Optional[str] = None,
        available_values: Optional[dict[str, str]] = None,
    ) -> Optional[dict[str, Any]]:
        if not self.is_configured:
            return None

        client = self._get_client()
        default_model = "gpt-4o" if portal_type == "recorder" else "gpt-4o-mini"
        model_name = model or (
            "gpt-4o" if portal_type == "recorder" else getattr(self.settings, "openai_browser_model", None) or default_model
        )
        system_prompt = SYSTEM_PROMPT_RECORDER if portal_type == "recorder" else SYSTEM_PROMPT_ASSESSOR

        user_payload: dict[str, Any] = {
            "query_type": query_type.value,
            "query_value": query_value,
            "page": snapshot,
        }
        if user_instructions:
            user_payload["user_instructions"] = user_instructions
        if available_values:
            user_payload["available_values"] = {k: v for k, v in available_values.items() if v}

        try:
            response, _provider = await chat_completions_create(
                openai_client=client,
                create_kwargs={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": json.dumps(user_payload, ensure_ascii=False),
                        },
                    ],
                    "temperature": 0.1,
                    "max_tokens": 600,
                    "response_format": {"type": "json_object"},
                },
            )
            raw = response.choices[0].message.content or "{}"
            plan = json.loads(raw)
            logger.info(
                "AI page search plan: model=%s confidence=%s reasoning=%s",
                model_name,
                plan.get("confidence"),
                plan.get("reasoning"),
            )
            return plan
        except Exception as exc:
            logger.warning("AI page search planning failed: %s", exc)
            return None

    async def execute_plan(
        self,
        driver: "BaseDriver",
        plan: dict[str, Any],
        query_value: str,
        values: Optional[dict[str, str]] = None,
    ) -> bool:
        tab_sel = plan.get("tab_selector")
        radio_sel = plan.get("radio_selector")
        input_sel = plan.get("input_selector")
        submit_sel = plan.get("submit_selector")
        use_enter = bool(plan.get("use_enter_key"))
        value_map = {k: v for k, v in (values or {}).items() if v}
        value_map.setdefault("query_value", query_value)

        acted = False

        if tab_sel and str(tab_sel).strip().lower() not in ("null", "none", ""):
            if await _click_selector(driver, str(tab_sel).strip()):
                acted = True
                await driver.polite_delay(1.2)

        if radio_sel and str(radio_sel).strip().lower() not in ("null", "none", ""):
            if await _click_selector(driver, str(radio_sel).strip()):
                acted = True
                await driver.polite_delay(0.5)

        fills = plan.get("fills") if isinstance(plan.get("fills"), list) else []
        filled_any = False
        for item in fills:
            if not isinstance(item, dict):
                continue
            selector = str(item.get("selector") or "").strip()
            key = str(item.get("value_key") or "query_value").strip()
            val = value_map.get(key)
            if selector and val and await _fill_selector(driver, selector, val):
                filled_any = True
                acted = True

        if not filled_any:
            if not input_sel or not str(input_sel).strip() or str(input_sel).strip().lower() in ("null", "none"):
                return acted
            if await _fill_selector(driver, str(input_sel).strip(), query_value):
                acted = True
            else:
                return acted

        if submit_sel and str(submit_sel).strip().lower() not in ("null", "none", ""):
            if await _click_selector(driver, str(submit_sel).strip()):
                await driver.polite_delay(2.0)
                return True

        if use_enter:
            try:
                await driver.page.keyboard.press("Enter")
                await driver.polite_delay(2.0)
                return True
            except Exception:
                pass

        # Default: try common search buttons after fill
        for sel in [
            'button:has-text("Search")',
            'input[type="submit"]',
            '[aria-label*="search" i]',
            'img[alt*="search" i]',
        ]:
            if await _click_selector(driver, sel):
                await driver.polite_delay(2.0)
                return True

        try:
            await driver.page.keyboard.press("Enter")
            await driver.polite_delay(2.0)
            return acted
        except Exception:
            return acted


async def _click_selector(driver: "BaseDriver", selector: str) -> bool:
    try:
        loc = driver.page.locator(selector).first
        if await loc.count() > 0 and await loc.is_visible(timeout=5_000):
            await loc.click(force=True)
            return True
    except Exception as exc:
        logger.debug("AI click failed %s: %s", selector, exc)
    return False


async def _fill_selector(driver: "BaseDriver", selector: str, value: str) -> bool:
    from app.drivers.form_fill import fill_first_visible_input

    return await fill_first_visible_input(driver, [selector], value, timeout_ms=5_000)


async def execute_ai_page_search(
    driver: "BaseDriver",
    query_type: QueryType,
    query_value: str,
    *,
    portal_type: str = "assessor",
    user_instructions: Optional[str] = None,
) -> bool:
    """
    Analyze the current page with GPT and perform search actions.
    Returns True if the search field was filled and submit was attempted.
    """
    ai = PageSearchAI()
    if not ai.is_configured:
        await driver._emit_status("OpenAI key not configured — skipping AI page analysis.")
        return False

    if await driver.is_cloudflare_blocked():
        await driver._emit_status(
            "Cloudflare is blocking the county portal — complete verification in Live Browser, then re-run."
        )
        cleared = await driver.wait_for_portal_access(
            success_selector="input, form, #ctlBodyPane, .widgetLabel",
        )
        if not cleared or await driver.is_cloudflare_blocked():
            return False

    portal_label = "recorder" if portal_type == "recorder" else query_type.value
    await driver._emit_status(f"Analyzing page with AI ({portal_label} search)...")
    snapshot = await ai.extract_snapshot(driver)
    if not snapshot.get("elements"):
        await driver._emit_status("AI could not read interactive elements on this page.")
        return False

    plan = await ai.plan_search(
        snapshot,
        query_type,
        query_value,
        portal_type=portal_type,
        user_instructions=user_instructions,
    )
    if not plan:
        await driver._emit_status("AI could not plan search actions for this page.")
        return False

    reasoning = plan.get("reasoning") or "planned search actions"
    await driver._emit_status(f"AI: {reasoning}")

    success = await ai.execute_plan(driver, plan, query_value)
    if success:
        await driver._emit_status("AI completed search form fill and submit.")
    else:
        await driver._emit_status("AI planned actions but could not fill the search field.")
    return success


async def execute_ai_recorder_search(
    driver: "BaseDriver",
    query_type: QueryType,
    query_value: str,
    available_values: Optional[dict[str, str]] = None,
    *,
    user_instructions: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Analyze a recorder/clerk page with GPT-4o and fill the fields the site is asking for.

    Returns (success, search_kind).
    """
    ai = PageSearchAI()
    if not ai.is_configured:
        await driver._emit_status("OpenAI key not configured — skipping AI recorder page analysis.")
        return False, None

    values = {k: str(v).strip() for k, v in (available_values or {}).items() if v and str(v).strip()}
    values.setdefault("query_value", query_value)

    await driver._emit_status("Analyzing recorder page with GPT-4o to choose the correct search fields...")
    snapshot = await ai.extract_snapshot(driver)
    if not snapshot.get("elements"):
        await driver._emit_status("AI could not read interactive elements on this recorder page.")
        return False, None

    plan = await ai.plan_search(
        snapshot,
        query_type,
        query_value,
        model="gpt-4o",
        portal_type="recorder",
        user_instructions=user_instructions,
        available_values=values,
    )
    if not plan:
        await driver._emit_status("GPT-4o could not plan recorder search actions for this page.")
        return False, None

    search_kind = str(plan.get("search_kind") or "").strip().lower() or None
    reasoning = plan.get("reasoning") or "planned recorder search"
    await driver._emit_status(f"GPT-4o: {reasoning}")

    fill_value = query_value
    if search_kind == "book_page" and values.get("book") and values.get("page"):
        fill_value = f"{values['book']} / {values['page']}"
    elif search_kind == "owner" and values.get("owner"):
        fill_value = values["owner"]
    elif search_kind == "parcel" and values.get("parcel"):
        fill_value = values["parcel"]
    elif search_kind == "address" and values.get("address"):
        fill_value = values["address"]

    success = await ai.execute_plan(driver, plan, fill_value, values=values)
    if success:
        await driver._emit_status("GPT-4o filled the recorder fields the page is asking for.")
    else:
        await driver._emit_status("GPT-4o planned recorder actions but could not fill the form.")
    return success, search_kind
