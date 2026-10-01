"""Portal Analyzer: Extracts compact DOM representation and identifies search components."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.agents.llm_client import chat_completions_create
from app.config.settings import get_settings
from app.drivers.dynamic_portal.schemas import (
    CompactBrowserState,
    CompactElement,
    CompactIframe,
    PortalAnalysis,
    PropertySearchInput,
    SearchFieldMapping,
)

logger = logging.getLogger(__name__)

# Lightweight client-side snapshot script that runs directly in Playwright
COMPACT_DOM_SNAPSHOT_JS = """
() => {
  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const esc = (s) => (s || '').replace(/\\\\/g, '\\\\').replace(/"/g, '\\\\"').trim();

  function buildSelector(el) {
    if (!el) return null;
    // 1. Associated label
    let labelText = '';
    if (el.id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lbl && clean(lbl.innerText)) labelText = clean(lbl.innerText);
    }
    if (!labelText && el.closest('label')) {
      labelText = clean(el.closest('label').innerText);
    }

    // Check visible & enabled
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    const isVisible = rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
    const isEnabled = !el.disabled;

    // Ordered selector preference:
    // 1. label association
    if (labelText && labelText.length <= 40 && el.id && !/^\\d/.test(el.id)) {
      return { sel: `#${CSS.escape(el.id)}`, labelText, isVisible, isEnabled };
    }
    // 2. role + accessible name
    const role = el.getAttribute('role');
    const ariaLabel = el.getAttribute('aria-label');
    if (role && ariaLabel) {
      return { sel: `[role="${role}"][aria-label="${esc(ariaLabel)}"]`, labelText, isVisible, isEnabled };
    }
    if (ariaLabel) {
      return { sel: `[aria-label="${esc(ariaLabel)}"]`, labelText, isVisible, isEnabled };
    }
    // 3. name
    const name = el.getAttribute('name');
    if (name) {
      const tag = el.tagName.toLowerCase();
      return { sel: `${tag}[name="${esc(name)}"]`, labelText, isVisible, isEnabled };
    }
    // 4. ID (if not starting with digit / purely random)
    if (el.id && !/^\\d/.test(el.id) && !/^ember\\d+/i.test(el.id)) {
      return { sel: `#${CSS.escape(el.id)}`, labelText, isVisible, isEnabled };
    }
    // 5. placeholder
    const ph = el.getAttribute('placeholder');
    if (ph) {
      return { sel: `${el.tagName.toLowerCase()}[placeholder="${esc(ph)}"]`, labelText, isVisible, isEnabled };
    }
    // Specific text for buttons/links/tabs
    const text = clean(el.innerText || el.textContent || '').slice(0, 60);
    if ((el.tagName === 'BUTTON' || el.tagName === 'A' || role === 'tab') && text) {
      return { sel: `${el.tagName.toLowerCase()}:has-text("${esc(text)}")`, labelText, isVisible, isEnabled };
    }
    return null;
  }

  const inputs = [];
  const buttons = [];
  const links = [];
  const selects = [];
  const iframes = [];
  const dialogs = [];

  // 1. Query inputs & textareas
  document.querySelectorAll('input:not([type="hidden"]), textarea').forEach((el) => {
    const info = buildSelector(el);
    if (!info) return;
    inputs.push({
      tag: el.tagName.toLowerCase(),
      selector: info.sel,
      text: clean(el.value || ''),
      name: el.name || '',
      id: el.id || '',
      type: (el.type || 'text').toLowerCase(),
      placeholder: el.placeholder || '',
      role: el.getAttribute('role') || '',
      aria_label: el.getAttribute('aria-label') || '',
      label_text: info.labelText || '',
      is_visible: info.isVisible,
      is_enabled: info.isEnabled,
    });
  });

  // 2. Query buttons & search triggers
  document.querySelectorAll('button, input[type="submit"], input[type="button"], [role="button"]').forEach((el) => {
    const info = buildSelector(el);
    if (!info) return;
    const text = clean(el.innerText || el.value || el.getAttribute('aria-label') || '');
    buttons.push({
      tag: el.tagName.toLowerCase(),
      selector: info.sel,
      text,
      name: el.getAttribute('name') || '',
      id: el.id || '',
      type: el.getAttribute('type') || '',
      role: el.getAttribute('role') || 'button',
      aria_label: el.getAttribute('aria-label') || '',
      is_visible: info.isVisible,
      is_enabled: info.isEnabled,
    });
  });

  // 3. Query links & tab controls
  document.querySelectorAll('a[href], [role="tab"], mat-tab, .tab-link').forEach((el) => {
    const text = clean(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
    if (!text && !el.getAttribute('title')) return;
    const info = buildSelector(el);
    if (!info) return;
    links.push({
      tag: el.tagName.toLowerCase(),
      selector: info.sel,
      text: text.slice(0, 80),
      href: el.getAttribute('href') || '',
      role: el.getAttribute('role') || (el.tagName === 'A' ? 'link' : 'tab'),
      aria_label: el.getAttribute('aria-label') || '',
      is_visible: info.isVisible,
      is_enabled: info.isEnabled,
    });
  });

  // 4. Query selects
  document.querySelectorAll('select').forEach((el) => {
    const info = buildSelector(el);
    if (!info) return;
    selects.push({
      tag: 'select',
      selector: info.sel,
      text: clean(el.value || ''),
      name: el.name || '',
      id: el.id || '',
      label_text: info.labelText || '',
      is_visible: info.isVisible,
      is_enabled: info.isEnabled,
    });
  });

  // 5. Query iframes
  document.querySelectorAll('iframe').forEach((el) => {
    const src = el.getAttribute('src') || '';
    const id = el.id || '';
    const name = el.getAttribute('name') || '';
    const title = el.getAttribute('title') || '';
    let sel = 'iframe';
    if (id) sel = `iframe#${CSS.escape(id)}`;
    else if (name) sel = `iframe[name="${esc(name)}"]`;
    else if (src) sel = `iframe[src*="${esc(src.slice(0, 30))}"]`;
    iframes.push({ selector: sel, src, id, name, title });
  });

  // 6. Query dialogs & modals
  document.querySelectorAll('[role="dialog"], dialog, .modal, .ui-dialog').forEach((el) => {
    if (el.offsetParent !== null) {
      dialogs.push(clean(el.innerText || '').slice(0, 100));
    }
  });

  const fullText = clean(document.body ? document.body.innerText : '').slice(0, 3000);

  return {
    url: location.href,
    title: document.title,
    visible_text: fullText,
    inputs: inputs.slice(0, 40),
    buttons: buttons.slice(0, 30),
    links: links.slice(0, 50),
    selects: selects.slice(0, 15),
    iframes: iframes.slice(0, 10),
    dialogs: dialogs.slice(0, 5),
  };
}
"""

PARCEL_KEYWORDS = ["parcel", "apn", "folio", "pin", "strap", "tax id", "parcel id", "parcel number", "account number", "tmk"]
ADDRESS_KEYWORDS = ["address", "street", "location", "situs", "property address"]
OWNER_KEYWORDS = ["owner", "name", "taxpayer", "grantor", "grantee", "party name"]
SEARCH_SUBMIT_KEYWORDS = ["search", "submit", "find", "go", "lookup", "query"]


class PortalAnalyzer:
    """Extracts compact browser state and analyzes search form layout."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._openai_client = None

    def _get_openai(self) -> Any:
        if self._openai_client is None and self.settings.openai_api_key:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=self.settings.openai_api_key)
        return self._openai_client

    async def capture_state(self, page: Any) -> CompactBrowserState:
        """Evaluate DOM JS in Playwright page to generate CompactBrowserState."""
        try:
            raw = await page.evaluate(COMPACT_DOM_SNAPSHOT_JS)
            return CompactBrowserState(
                url=raw.get("url", ""),
                title=raw.get("title", ""),
                visible_text=raw.get("visible_text", ""),
                inputs=[CompactElement(**inp) for inp in raw.get("inputs", [])],
                buttons=[CompactElement(**btn) for btn in raw.get("buttons", [])],
                links=[CompactElement(**lnk) for lnk in raw.get("links", [])],
                selects=[CompactElement(**sel) for sel in raw.get("selects", [])],
                iframes=[CompactIframe(**ifr) for ifr in raw.get("iframes", [])],
                dialogs=raw.get("dialogs", []),
            )
        except Exception as exc:
            logger.warning("DOM snapshot evaluation failed: %s", exc)
            url = ""
            title = ""
            try:
                url = page.url
                title = await page.title()
            except Exception:
                pass
            return CompactBrowserState(url=url, title=title)

    def analyze_heuristic(self, state: CompactBrowserState) -> PortalAnalysis:
        """
        Heuristically inspect input fields, labels, placeholders, and buttons.
        Works deterministically without external LLM calls whenever clear markers exist.
        """
        search_fields: Dict[str, SearchFieldMapping] = {}
        tab_selectors: Dict[str, str] = {}
        submit_btn_selector: Optional[str] = None

        # 1. Match search tabs (e.g. "Search by Parcel", "Search by Address")
        for link in state.links:
            text_lower = link.text.lower()
            role = (link.role or "").lower()
            if role == "tab" or "tab" in link.selector:
                if any(kw in text_lower for kw in PARCEL_KEYWORDS):
                    tab_selectors["parcel"] = link.selector
                elif any(kw in text_lower for kw in ADDRESS_KEYWORDS):
                    tab_selectors["address"] = link.selector
                elif any(kw in text_lower for kw in OWNER_KEYWORDS):
                    tab_selectors["owner"] = link.selector

        # 2. Match inputs to canonical property fields
        for inp in state.inputs:
            if not inp.is_visible or not inp.is_enabled:
                continue
            text_signals = " ".join([
                inp.label_text or "",
                inp.placeholder or "",
                inp.name or "",
                inp.id or "",
                inp.aria_label or "",
            ]).lower()

            # Skip radio or checkbox inputs as primary text inputs
            if inp.type in ("radio", "checkbox", "hidden"):
                continue

            # Check Parcel / APN / Folio
            if any(kw in text_signals for kw in PARCEL_KEYWORDS):
                if "parcel" not in search_fields or "parcel" in inp.placeholder.lower():
                    search_fields["parcel"] = SearchFieldMapping(
                        field_type="parcel",
                        selector=inp.selector,
                        label=inp.label_text or inp.placeholder,
                        input_type=inp.type,
                        confidence=0.95,
                    )
            # Check Address
            elif any(kw in text_signals for kw in ADDRESS_KEYWORDS):
                if "address" not in search_fields or "address" in inp.placeholder.lower():
                    search_fields["address"] = SearchFieldMapping(
                        field_type="address",
                        selector=inp.selector,
                        label=inp.label_text or inp.placeholder,
                        input_type=inp.type,
                        confidence=0.95,
                    )
            # Check Owner Name
            elif any(kw in text_signals for kw in OWNER_KEYWORDS):
                if "owner" not in search_fields:
                    search_fields["owner"] = SearchFieldMapping(
                        field_type="owner",
                        selector=inp.selector,
                        label=inp.label_text or inp.placeholder,
                        input_type=inp.type,
                        confidence=0.90,
                    )

        # 3. Match submit/search button
        for btn in state.buttons:
            text_lower = btn.text.lower()
            aria_lower = (btn.aria_label or "").lower()
            if any(kw in text_lower or kw in aria_lower for kw in SEARCH_SUBMIT_KEYWORDS):
                submit_btn_selector = btn.selector
                break

        has_search_inputs = bool(search_fields)
        page_type = "search_form" if has_search_inputs else "landing_page"

        # Check if results are already visible
        lower_body = state.visible_text.lower()
        if "search results" in lower_body or "parcels found" in lower_body or "records matching" in lower_body:
            page_type = "results_page"

        # Check if iframe container exists
        iframe_sel = state.iframes[0].selector if state.iframes else None

        return PortalAnalysis(
            page_type=page_type,
            is_search_page=has_search_inputs,
            search_fields=search_fields,
            submit_button_selector=submit_btn_selector,
            tab_selectors=tab_selectors,
            iframe_selector=iframe_sel,
            reasoning=f"Heuristic detected {len(search_fields)} search fields and {len(tab_selectors)} tabs.",
            confidence=0.92 if has_search_inputs else 0.70,
        )

    async def analyze(
        self,
        state: CompactBrowserState,
        portal_type: str = "assessor",
    ) -> PortalAnalysis:
        """
        Analyze page state: attempts fast heuristic first; falls back to OpenAI
        if fields are ambiguous and OpenAI key is configured.
        """
        heuristic = self.analyze_heuristic(state)
        if heuristic.is_search_page and heuristic.confidence >= 0.90:
            return heuristic

        # If heuristic did not find clear fields, and OpenAI is available, run compact analysis
        client = self._get_openai()
        if not client:
            return heuristic

        system_prompt = (
            "You are an expert county government portal analyzer. "
            "Given compact page inputs, buttons, and text, identify the property search fields. "
            "Map fields strictly to canonical types: 'parcel', 'address', 'owner', 'account'. "
            "Return valid JSON matching this schema: {"
            "  \"is_search_page\": boolean,"
            "  \"page_type\": \"search_form\"|\"landing_page\"|\"results_page\"|\"blocked\","
            "  \"search_fields\": {\"parcel\": {\"selector\": \"...\"}, \"address\": {\"selector\": \"...\"}},"
            "  \"submit_button_selector\": string or null,"
            "  \"tab_selectors\": {\"address\": string, \"parcel\": string},"
            "  \"reasoning\": string"
            "}. Rules: NEVER invent selectors. Only pick from provided inputs/buttons."
        )

        compact_payload = {
            "portal_type": portal_type,
            "url": state.url,
            "title": state.title,
            "inputs": [
                {
                    "selector": inp.selector,
                    "label": inp.label_text,
                    "placeholder": inp.placeholder,
                    "name": inp.name,
                    "id": inp.id,
                }
                for inp in state.inputs
            ],
            "buttons": [{"selector": btn.selector, "text": btn.text} for btn in state.buttons],
            "summary_text": state.visible_text[:600],
        }

        try:
            response, _provider = await chat_completions_create(
                openai_client=client,
                create_kwargs={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(compact_payload)},
                    ],
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"},
                },
            )
            raw = json.loads(response.choices[0].message.content or "{}")
            fields: Dict[str, SearchFieldMapping] = {}
            for f_type, f_data in (raw.get("search_fields") or {}).items():
                if isinstance(f_data, dict) and f_data.get("selector"):
                    fields[f_type] = SearchFieldMapping(
                        field_type=f_type,
                        selector=str(f_data["selector"]),
                        confidence=0.95,
                    )

            return PortalAnalysis(
                page_type=raw.get("page_type") or heuristic.page_type,
                is_search_page=bool(raw.get("is_search_page", bool(fields))),
                search_fields=fields or heuristic.search_fields,
                submit_button_selector=raw.get("submit_button_selector") or heuristic.submit_button_selector,
                tab_selectors=raw.get("tab_selectors") or heuristic.tab_selectors,
                iframe_selector=heuristic.iframe_selector,
                reasoning=raw.get("reasoning") or "AI analyzed compact DOM elements.",
                confidence=0.95,
            )
        except Exception as exc:
            logger.warning("AI portal analysis failed: %s, falling back to heuristic", exc)
            return heuristic
