"""Centralized Playwright browser launch for compliant portal automation."""

from __future__ import annotations

import asyncio
import logging
import random
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional, Union

from playwright.async_api import Browser, BrowserContext, Page, Playwright

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str], Union[None, Awaitable[None]]]

DEFAULT_TIMEOUT_MS = 45_000
CLOUDFLARE_RETRY_WAIT_SEC = 5.0
HUMAN_DELAY_MIN_SEC = 1.5
HUMAN_DELAY_MAX_SEC = 4.0

USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)

STEALTH_INIT_SCRIPT = """
try {
    delete Object.getPrototypeOf(navigator).webdriver;
} catch (e) {}
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
if (!window.chrome) {
    window.chrome = {};
}
if (!window.chrome.runtime) {
    window.chrome.runtime = {
        connect: function() {},
        sendMessage: function() {}
    };
}
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);
"""

CLOUDFLARE_CHALLENGE_TITLES = (
    "just a moment",
    "attention required",
)


class CDPConnectionError(RuntimeError):
    """Raised when CDP Chrome is required but unavailable."""


@dataclass
class BrowserSession:
    browser: Optional[Browser]
    context: BrowserContext
    page: Page
    user_agent: str
    connected_via_cdp: bool = False


def pick_user_agent() -> str:
    """Pick a realistic User-Agent for this browser session."""
    return random.choice(USER_AGENTS)


async def human_delay(
    min_sec: float = HUMAN_DELAY_MIN_SEC,
    max_sec: float = HUMAN_DELAY_MAX_SEC,
    *,
    run_id: str | None = None,
) -> None:
    """Pause between page actions with a human-like random delay."""
    from app.queue.run_cancellation import check_run_cancelled

    settings = get_settings()
    check_run_cancelled(run_id)
    if not settings.use_human_delays:
        return
    await asyncio.sleep(random.uniform(min_sec, max_sec))
    check_run_cancelled(run_id)


def is_cloudflare_challenge_title(title: str) -> bool:
    """True when the page title indicates an active Cloudflare challenge."""
    lower = (title or "").lower()
    return any(marker in lower for marker in CLOUDFLARE_CHALLENGE_TITLES)


def resolve_profile_path(use_persistent_profile: bool) -> Optional[Path]:
    """Resolve the Chrome user-data directory for persistent contexts."""
    settings = get_settings()
    if False:  # User Chrome profiles are not used by automation.
        chrome_dir = (settings.chrome_user_data_dir or "").strip()
        if chrome_dir:
            profile = Path(chrome_dir)
            profile.mkdir(parents=True, exist_ok=True)
            return profile
        logger.info(
            "USE_CHROME_PROFILE=true but CHROME_USER_DATA_DIR is unset — using a clean context"
        )
        return None

    if use_persistent_profile:
        fallback = (settings.playwright_user_data_dir or "").strip()
        if fallback:
            profile = Path(fallback)
            profile.mkdir(parents=True, exist_ok=True)
            return profile
    return None


def build_proxy_config() -> Optional[dict[str, str]]:
    """Proxy routing is intentionally unsupported for portal automation."""
    return None

    settings = get_settings()
    if not settings.use_proxy:
        return None
    proxy_url = (settings.proxy_url or "").strip()
    if not proxy_url:
        logger.warning("USE_PROXY=true but PROXY_URL is empty — proxy disabled")
        return None
    return {"server": proxy_url}


def build_launch_kwargs(headless: bool) -> dict:
    settings = get_settings()
    launch_kwargs: dict = {
        "headless": headless,
        "args": ["--headless=new"] if headless else [],
    }
    if settings.playwright_channel:
        launch_kwargs["channel"] = settings.playwright_channel
    proxy = build_proxy_config()
    if proxy:
        launch_kwargs["proxy"] = proxy
    return launch_kwargs


def build_context_kwargs(user_agent: str) -> dict:
    settings = get_settings()
    context_kwargs: dict = {
        "viewport": {"width": 1366, "height": 900},
        "locale": "en-US",
        "accept_downloads": True,
    }
    # Installed Chrome already has a native UA — a mismatched custom UA can trigger blocks.
    if not settings.playwright_channel:
        context_kwargs["user_agent"] = user_agent
    proxy = build_proxy_config()
    if proxy:
        context_kwargs["proxy"] = proxy
    return context_kwargs


async def apply_stealth(context: BrowserContext, page: Page, *, skip: bool = False) -> None:
    """Compatibility no-op: anti-bot evasion is not supported."""
    return None


async def import_cookies_for_url(context: BrowserContext, url: str) -> int:
    """Compatibility no-op: importing browser clearance cookies is unsupported."""
    return 0


async def launch_persistent_context(
    playwright: Playwright,
    profile_path: Path,
    launch_kwargs: dict,
    context_kwargs: dict,
    profile_launch_lock: threading.Lock,
) -> BrowserContext:
    last_error: Optional[Exception] = None
    for attempt in range(1, 3):
        with profile_launch_lock:
            try:
                return await playwright.chromium.launch_persistent_context(
                    str(profile_path.resolve()),
                    **launch_kwargs,
                    **context_kwargs,
                )
            except Exception as exc:
                last_error = exc
                if "TargetClosedError" not in type(exc).__name__:
                    raise
        if attempt < 2:
            logger.warning(
                "Persistent Chrome profile busy (attempt %d/2), retrying in 2s: %s",
                attempt,
                last_error,
            )
            await asyncio.sleep(2)
    raise last_error or RuntimeError("Failed to launch persistent Chrome context")


async def create_browser_session(
    playwright: Playwright,
    *,
    headless: bool,
    use_persistent_profile: bool,
    profile_launch_lock: threading.Lock,
    emit_status: Optional[StatusCallback] = None,
) -> BrowserSession:
    """Launch or attach a browser without anti-bot evasion behavior."""
    settings = get_settings()
    user_agent = pick_user_agent()

    async def _status(message: str) -> None:
        if not emit_status:
            return
        result = emit_status(message)
        if asyncio.iscoroutine(result):
            await result

    cdp_url = (settings.playwright_cdp_url or "").strip()
    if cdp_url:
        from app.drivers.cdp_chrome import ensure_cdp_chrome

        await _status("Starting trusted Chrome for county portals...")
        if not await ensure_cdp_chrome(cdp_url):
            msg = (
                "Could not start CDP Chrome. Close all Chrome windows and run the pipeline again, "
                "or run: backend/scripts/launch_chrome_cdp.ps1"
            )
            await _status(msg)
            if settings.playwright_cdp_required:
                raise CDPConnectionError(msg)
        else:
            try:
                browser = await playwright.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = context.pages[0] if context.pages else await context.new_page()
                context.set_default_timeout(DEFAULT_TIMEOUT_MS)
                await apply_stealth(context, page, skip=True)
                logger.info("Playwright connected over CDP at %s", cdp_url)
                return BrowserSession(
                    browser=browser,
                    context=context,
                    page=page,
                    user_agent=user_agent,
                    connected_via_cdp=True,
                )
            except Exception as exc:
                logger.error("CDP connect failed at %s: %s", cdp_url, exc)
                msg = (
                    "CDP Chrome connection failed. Close Chrome, re-run the pipeline "
                    "(Chrome will auto-start), or run backend/scripts/launch_chrome_cdp.ps1"
                )
                await _status(msg)
                if settings.playwright_cdp_required:
                    raise CDPConnectionError(msg) from exc

    if settings.playwright_cdp_required and not cdp_url:
        raise CDPConnectionError(
            "Set PLAYWRIGHT_CDP_URL=http://127.0.0.1:9222 in backend/.env "
            "to avoid Cloudflare blocks on county portals."
        )

    launch_kwargs = build_launch_kwargs(headless)
    context_kwargs = build_context_kwargs(user_agent)
    profile_path = resolve_profile_path(use_persistent_profile)
    skip_stealth = bool(settings.playwright_channel)

    if profile_path:
        context = await launch_persistent_context(
            playwright,
            profile_path,
            launch_kwargs,
            context_kwargs,
            profile_launch_lock,
        )
        browser = None
        page = context.pages[0] if context.pages else await context.new_page()
    else:
        browser = await playwright.chromium.launch(**launch_kwargs)
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

    context.set_default_timeout(DEFAULT_TIMEOUT_MS)
    await apply_stealth(context, page, skip=skip_stealth)
    logger.info(
        "Launched browser (headless=%s, profile=%s, proxy=%s, ua=%s...)",
        headless,
        profile_path or "clean",
        bool(build_proxy_config()),
        user_agent[:48],
    )
    return BrowserSession(
        browser=browser,
        context=context,
        page=page,
        user_agent=user_agent,
        connected_via_cdp=False,
    )


async def navigate_with_cloudflare_retry(
    page: Page,
    navigate: Callable[[], Awaitable[None]],
) -> bool:
    """
    Run navigation and retry once when Cloudflare challenge titles are detected.

    Returns True when a Cloudflare title retry was performed.
    """
    await navigate()
    # Security pages are not retried here; the caller detects and stops safely.
    return False

    try:
        title = await page.title()
    except Exception:
        return False

    if not is_cloudflare_challenge_title(title):
        return False

    logger.warning(
        "Cloudflare challenge detected (title: %s) — retrying once after %.0fs",
        title,
        CLOUDFLARE_RETRY_WAIT_SEC,
    )
    await asyncio.sleep(CLOUDFLARE_RETRY_WAIT_SEC)
    await navigate()
    return True
