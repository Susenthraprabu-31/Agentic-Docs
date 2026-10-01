"""Action Validator: Validates structured actions for safety and execution integrity."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.drivers.dynamic_portal.schemas import ActionResult, BrowserAction

logger = logging.getLogger(__name__)

ALLOWED_ACTIONS = {
    "fill",
    "click",
    "select",
    "wait",
    "navigate",
    "scroll",
    "switch_frame",
    "open_tab",
}

# Dangerous payloads check (XSS/shell/code injection attempts)
DISALLOWED_PATTERNS = [
    r"<script\b",
    r"javascript:",
    r"(\b(eval|exec|system|child_process|spawn)\b)",
    r"__proto__",
]


class ActionValidationError(Exception):
    """Raised when an action violates safety or validation rules."""
    pass


class ActionValidator:
    """Validates and safely dispatches allowed browser actions to Playwright."""

    def __init__(self, allowed_domains: Optional[List[str]] = None) -> None:
        self.allowed_domains = [d.lower() for d in (allowed_domains or [])]
        self.action_history: List[ActionResult] = []

    def validate_action(
        self,
        action: BrowserAction,
        current_url: str = "",
    ) -> None:
        """Verify action against whitelist, parameters, and current page URL."""
        # 1. Allowed action check
        if action.action not in ALLOWED_ACTIONS:
            raise ActionValidationError(
                f"Action '{action.action}' is forbidden. Allowed: {sorted(ALLOWED_ACTIONS)}"
            )

        # 2. Selector check for interactive actions
        if action.action in ("fill", "click", "select") and not action.selector:
            raise ActionValidationError(f"Action '{action.action}' requires a valid selector.")

        # 3. Value check and sanitization for fill/select
        if action.action == "fill":
            if action.value is None:
                raise ActionValidationError("Fill action requires a non-null value string.")
            for pattern in DISALLOWED_PATTERNS:
                if re.search(pattern, action.value, re.IGNORECASE):
                    raise ActionValidationError(f"Suspicious payload detected in fill value: '{action.value}'")

        # 4. Domain boundary check if allowed_domains is provided
        if current_url and self.allowed_domains:
            parsed = urlparse(current_url)
            host = (parsed.netloc or "").lower()
            if host and not any(allowed in host for allowed in self.allowed_domains):
                logger.warning("Action target page %s is outside allowed domains: %s", host, self.allowed_domains)

    async def execute_action(
        self,
        page_or_frame: Any,
        action: BrowserAction,
        current_url: str = "",
    ) -> ActionResult:
        """
        Validate and execute the single structured action on Playwright Page or Frame.
        Never executes raw/arbitrary JavaScript or shell commands.
        """
        t0 = time.monotonic()
        try:
            self.validate_action(action, current_url=current_url)

            # Wait action
            if action.action == "wait":
                ms = min(action.timeout_ms or 1000, 10000)
                await asyncio.sleep(ms / 1000.0)
                res = ActionResult(success=True, action=action, duration_ms=int((time.monotonic() - t0) * 1000))
                self.action_history.append(res)
                return res

            # Scroll action
            if action.action == "scroll":
                await page_or_frame.evaluate("() => window.scrollBy(0, 400)")
                res = ActionResult(success=True, action=action, duration_ms=int((time.monotonic() - t0) * 1000))
                self.action_history.append(res)
                return res

            # Fill action
            if action.action == "fill":
                loc = page_or_frame.locator(action.selector).first
                if await loc.count() == 0:
                    raise ActionValidationError(f"Selector not found: {action.selector}")
                if not await loc.is_visible(timeout=5000):
                    raise ActionValidationError(f"Element not visible: {action.selector}")
                if not await loc.is_enabled(timeout=5000):
                    raise ActionValidationError(f"Element is disabled: {action.selector}")

                await loc.click(timeout=5000)
                await loc.fill("")
                try:
                    await loc.press_sequentially(str(action.value), delay=20)
                except Exception:
                    await loc.fill(str(action.value))

                # Trigger change and input events
                await loc.evaluate(
                    """(el, val) => {
                        el.value = val;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }""",
                    str(action.value),
                )
                res = ActionResult(success=True, action=action, duration_ms=int((time.monotonic() - t0) * 1000))
                self.action_history.append(res)
                return res

            # Click action
            if action.action == "click":
                loc = page_or_frame.locator(action.selector).first
                if await loc.count() == 0:
                    raise ActionValidationError(f"Selector not found: {action.selector}")
                if not await loc.is_visible(timeout=5000):
                    raise ActionValidationError(f"Element not visible: {action.selector}")

                await loc.click(force=True, timeout=10_000)
                res = ActionResult(success=True, action=action, duration_ms=int((time.monotonic() - t0) * 1000))
                self.action_history.append(res)
                return res

            # Select dropdown action
            if action.action == "select":
                loc = page_or_frame.locator(action.selector).first
                if await loc.count() == 0:
                    raise ActionValidationError(f"Selector not found: {action.selector}")
                await loc.select_option(value=action.value, timeout=5000)
                res = ActionResult(success=True, action=action, duration_ms=int((time.monotonic() - t0) * 1000))
                self.action_history.append(res)
                return res

            raise ActionValidationError(f"Unhandled validated action: {action.action}")

        except Exception as exc:
            duration = int((time.monotonic() - t0) * 1000)
            logger.warning("Action execution failed [%s %s]: %s", action.action, action.selector, exc)
            res = ActionResult(success=False, action=action, error_message=str(exc), duration_ms=duration)
            self.action_history.append(res)
            return res
