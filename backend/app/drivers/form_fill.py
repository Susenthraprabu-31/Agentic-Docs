"""Safe Playwright form filling — skips hidden and debug inputs."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Union

from playwright.async_api import Frame, Page

if TYPE_CHECKING:
    from app.drivers.base.base_driver import BaseDriver

PageLike = Union[Page, Frame]


def _page_root(driver: "BaseDriver", root: PageLike | None = None) -> PageLike:
    return root if root is not None else driver.page

logger = logging.getLogger(__name__)

SKIP_INPUT_TYPES = frozenset({"hidden", "checkbox", "radio", "submit", "button", "file", "image"})
DEBUG_INPUT_RE = re.compile(r"(debug|cssnoprint|cssdebug|dummy|honeypot)", re.I)
EXACT_BUTTON_NAME_RE = re.compile(r"^Search$", re.I)


def _looks_like_debug_input(attrs: dict[str, Any]) -> bool:
    joined = " ".join(
        str(attrs.get(key) or "")
        for key in ("id", "name", "className", "class")
    )
    return bool(DEBUG_INPUT_RE.search(joined))


async def is_fillable_input(locator: Any, timeout_ms: int = 500) -> bool:
    """Return True when a locator points at a visible, editable search field."""
    try:
        if await locator.count() == 0:
            return False
        if not await locator.is_visible(timeout=timeout_ms):
            return False
        if not await locator.is_editable(timeout=timeout_ms):
            return False
        attrs = await locator.evaluate(
            """(el) => ({
                type: (el.type || '').toLowerCase(),
                ariaHidden: el.getAttribute('aria-hidden'),
                tabIndex: el.getAttribute('tabindex'),
                id: el.id || '',
                name: el.name || '',
                className: el.className || '',
                readOnly: !!el.readOnly,
                disabled: !!el.disabled,
            })"""
        )
        if attrs.get("type") in SKIP_INPUT_TYPES:
            return False
        if attrs.get("ariaHidden") == "true":
            return False
        if attrs.get("readOnly") or attrs.get("disabled"):
            return False
        if _looks_like_debug_input(attrs):
            return False
        return True
    except Exception:
        return False


async def _commit_fill(locator: Any, value: str) -> None:
    await locator.click()
    await locator.fill(value)
    await locator.evaluate(
        """(el, val) => {
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        value,
    )


async def fill_input_by_accessible_name(
    driver: "BaseDriver",
    accessible_name: str,
    value: str,
    *,
    role: str = "textbox",
    timeout_ms: int = 5_000,
    root: PageLike | None = None,
) -> bool:
    """Fill a field by its accessible label (e.g. 'Parcel ID:')."""
    if not value or not accessible_name:
        return False
    try:
        loc = _page_root(driver, root).get_by_role(role, name=accessible_name).first
        if await loc.count() > 0 and await is_fillable_input(loc, timeout_ms=min(timeout_ms, 1_500)):
            await _commit_fill(loc, value)
            return True
    except Exception as exc:
        logger.debug("Fill by label failed for %s: %s", accessible_name, exc)
    return False


async def click_enabled_button(
    driver: "BaseDriver",
    name: str,
    *,
    exact: bool = False,
    timeout_ms: int = 5_000,
    root: PageLike | None = None,
) -> bool:
    """Click the first visible, enabled button with the given accessible name."""
    try:
        button_name = re.compile(rf"^{re.escape(name)}$", re.I) if exact else name
        buttons = _page_root(driver, root).get_by_role("button", name=button_name)
        count = await buttons.count()
        for index in range(count):
            btn = buttons.nth(index)
            if not await btn.is_visible(timeout=min(timeout_ms, 1_500)):
                continue
            if not await btn.is_enabled():
                continue
            if exact:
                label = re.sub(r"\s+", " ", (await btn.inner_text()).strip())
                if label.lower() != name.lower():
                    continue
            await btn.click()
            return True
    except Exception as exc:
        logger.debug("Click enabled button failed for %s: %s", name, exc)
    return False


async def click_property_search_button(
    driver: "BaseDriver",
    *,
    root: PageLike | None = None,
) -> bool:
    """Click the green Search button — exact match so RESEARCH nav is never clicked."""
    page = _page_root(driver, root)
    try:
        await driver.page.keyboard.press("Escape")
    except Exception:
        pass

    if await click_enabled_button(driver, "Search", exact=True, root=root):
        return True

    try:
        buttons = page.locator("button").filter(has_text=EXACT_BUTTON_NAME_RE)
        count = await buttons.count()
        for index in range(count):
            btn = buttons.nth(index)
            if not await btn.is_visible(timeout=1_500):
                continue
            if not await btn.is_enabled():
                continue
            await btn.click()
            return True
    except Exception as exc:
        logger.debug("Exact Search button click failed: %s", exc)
    return False


async def fill_first_visible_input(
    driver: "BaseDriver",
    selectors: list[str],
    value: str,
    *,
    timeout_ms: int = 5_000,
    root: PageLike | None = None,
) -> bool:
    """Fill the first visible, editable input matched by any selector."""
    if not value or not selectors:
        return False

    page = _page_root(driver, root)
    for sel in selectors:
        try:
            loc = page.locator(sel)
            count = await loc.count()
            for index in range(count):
                item = loc.nth(index)
                if not await is_fillable_input(item, timeout_ms=min(timeout_ms, 1_500)):
                    continue
                await _commit_fill(item, value)
                return True
        except Exception as exc:
            logger.debug("Fill failed for %s: %s", sel, exc)
            continue
    return False
