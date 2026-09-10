import asyncio
import logging
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional, TypeVar, Union

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Route, async_playwright

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

StatusCallback = Callable[[str], Union[None, Awaitable[None]]]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT_MS = 45_000
NAVIGATION_TIMEOUT_MS = 45_000
ACTION_DELAY_SEC = 1.5
MAX_RETRIES = 3

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
"""

# Block heavy ad/tracker requests — NETR never reaches networkidle because of ads
BLOCKED_URL_FRAGMENTS = (
    "googlesyndication",
    "doubleclick",
    "google-analytics",
    "googletagmanager",
    "facebook.net",
    "adservice",
    "taboola",
    "outbrain",
    "adnxs",
    "criteo",
)

# Strict markers only — avoid false positives on normal county pages
CLOUDFLARE_BLOCK_MARKERS = (
    "sorry, you have been blocked",
    "you have been blocked",
    "unable to access schneidercorp.com",
)
CLOUDFLARE_CHALLENGE_MARKERS = (
    "cf-browser-verification",
    "challenge-platform",
    "checking your browser",
    "performing security verification",
    "verify you are human",
    "security service to protect against malicious bots",
)
CLOUDFLARE_CHALLENGE_TITLES = (
    "just a moment",
    "attention required",
)


class BaseDriver:
    def __init__(self, screenshot_dir: Optional[Path] = None) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self.screenshot_dir = screenshot_dir or Path("screenshots")
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.status_callback: Optional[StatusCallback] = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._context

    async def _emit_status(self, message: str) -> None:
        logger.info(message)
        if not self.status_callback:
            return
        result = self.status_callback(message)
        if asyncio.iscoroutine(result):
            await result

    async def start(self, headless: bool | None = None) -> None:
        settings = get_settings()
        if headless is None:
            headless = settings.playwright_headless

        self._playwright = await async_playwright().start()
        launch_kwargs: dict = {
            "headless": headless,
            "slow_mo": 30 if not headless else 0,
            "args": [
                "--disable-blink-features=AutomationControlled",
            ],
        }
        if settings.playwright_channel:
            launch_kwargs["channel"] = settings.playwright_channel

        profile_dir = settings.playwright_user_data_dir.strip()
        if profile_dir:
            profile_path = Path(profile_dir)
            profile_path.mkdir(parents=True, exist_ok=True)
            context_kwargs: dict = {
                "viewport": {"width": 1366, "height": 900},
                "locale": "en-US",
            }
            if not settings.playwright_channel:
                context_kwargs["user_agent"] = USER_AGENT

            self._context = await self._playwright.chromium.launch_persistent_context(
                str(profile_path.resolve()),
                **launch_kwargs,
                **context_kwargs,
            )
            self._browser = None
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        else:
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
            context_kwargs = {
                "user_agent": USER_AGENT,
                "viewport": {"width": 1366, "height": 900},
                "locale": "en-US",
            }
            self._context = await self._browser.new_context(**context_kwargs)
            self._page = await self._context.new_page()

        self._context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        await self._apply_stealth()
        await self._setup_request_blocking()

    async def _apply_stealth(self) -> None:
        try:
            await self._context.add_init_script(STEALTH_INIT_SCRIPT)
        except Exception as exc:
            logger.debug("Stealth init script skipped: %s", exc)

    async def _setup_request_blocking(self) -> None:
        async def _handle_route(route: Route) -> None:
            url = route.request.url.lower()
            if any(fragment in url for fragment in BLOCKED_URL_FRAGMENTS):
                await route.abort()
            else:
                await route.continue_()

        try:
            await self._context.route("**/*", _handle_route)
        except Exception as exc:
            logger.debug("Request blocking not enabled: %s", exc)

    async def has_actionable_page_content(self, page: Optional[Page] = None) -> bool:
        """True when a county portal page has loaded (not a bare Cloudflare interstitial)."""
        pg = page or self.page
        try:
            url = pg.url.lower()
            if "schneidercorp.com" in url or "qpublic.net" in url:
                if "keyvalue=" in url:
                    return True
                widget_count = await pg.locator(".widgetLabel, .widgetValue, #ctlBodyPane").count()
                if widget_count >= 2:
                    return True
                if await pg.locator(
                    "#ctlBodyPane_ctl02_ctl01_txtParcelID, #ctlBodyPane_ctl01_ctl01_txtAddress"
                ).count():
                    return True
            body_len = await pg.evaluate("() => (document.body?.innerText || '').trim().length")
            if body_len > 800 and await pg.locator("table, form, .widgetLabel").count():
                return True
            return False
        except Exception:
            return False

    async def is_cloudflare_blocked(self, page: Optional[Page] = None) -> bool:
        pg = page or self.page
        if await self.has_actionable_page_content(pg):
            return False
        try:
            title = (await pg.title()).lower()
            if any(t in title for t in CLOUDFLARE_CHALLENGE_TITLES):
                return True
            if "attention required" in title and "cloudflare" in title:
                return True
            content = (await pg.content()).lower()
            if any(marker in content for marker in CLOUDFLARE_BLOCK_MARKERS):
                return True
            if any(marker in content for marker in CLOUDFLARE_CHALLENGE_MARKERS):
                body_len = await pg.evaluate("() => (document.body?.innerText || '').trim().length")
                return body_len < 500
            return False
        except Exception:
            return False

    async def is_cloudflare_challenge(self, page: Optional[Page] = None) -> bool:
        """True when user can solve a checkbox challenge (not a hard block)."""
        pg = page or self.page
        try:
            content = (await pg.content()).lower()
            return any(marker in content for marker in CLOUDFLARE_CHALLENGE_MARKERS)
        except Exception:
            return False

    async def wait_for_cloudflare_clear(
        self,
        max_wait: int | None = None,
        success_selector: str | None = None,
    ) -> bool:
        """In headed mode, pause until the user completes Cloudflare verification."""
        if success_selector:
            try:
                if await self.page.locator(success_selector).is_visible(timeout=2000):
                    return True
            except Exception:
                pass

        if not await self.is_cloudflare_blocked():
            return True

        settings = get_settings()
        wait_seconds = max_wait or settings.playwright_cloudflare_wait_seconds

        if settings.playwright_headless:
            await self._emit_status(
                "Cloudflare blocked headless browser. Set PLAYWRIGHT_HEADLESS=false and retry."
            )
            return False

        if await self.is_cloudflare_challenge():
            await self._emit_status(
                "Cloudflare check — click 'Verify you are human' in the browser window. "
                "Automation will continue automatically after verification."
            )
        else:
            await self._emit_status(
                "Cloudflare verification required — complete the check in the browser window, "
                "automation will continue automatically..."
            )

        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            if await self.has_actionable_page_content():
                await self._emit_status("Property page loaded — continuing automation.")
                return True
            if not await self.is_cloudflare_blocked():
                await self.polite_delay(1.5)
                await self._emit_status("Cloudflare verification passed — continuing automation.")
                return True
            if success_selector:
                try:
                    if await self.page.locator(success_selector).is_visible(timeout=500):
                        await self._emit_status("Search form ready — continuing automation.")
                        return True
                except Exception:
                    pass

        if success_selector:
            try:
                if await self.page.locator(success_selector).is_visible(timeout=2000):
                    await self._emit_status("Search form ready — continuing after Cloudflare wait.")
                    return True
            except Exception:
                pass

        await self._emit_status("Cloudflare verification timed out.")
        return False

    async def safe_goto(
        self,
        url: str,
        wait_selector: Optional[str] = None,
        timeout: int = NAVIGATION_TIMEOUT_MS,
    ) -> None:
        """Navigate without networkidle — ad-heavy sites like NETR never go idle."""
        last_error: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                if "schneidercorp.com" in url.lower():
                    has_form = await self.page.locator(
                        "#ctlBodyPane_ctl02_ctl01_txtParcelID, #ctlBodyPane_ctl01_ctl01_txtAddress"
                    ).count()
                    if not has_form and not await self.wait_for_cloudflare_clear(max_wait=45):
                        raise RuntimeError("Cloudflare blocked access to county portal")
                elif await self.is_cloudflare_blocked():
                    await self.wait_for_cloudflare_clear(max_wait=45)

                if wait_selector:
                    try:
                        await self.page.wait_for_selector(wait_selector, timeout=20_000)
                    except Exception:
                        if await self.is_cloudflare_blocked():
                            cleared = await self.wait_for_cloudflare_clear()
                            if cleared and wait_selector:
                                await self.page.wait_for_selector(wait_selector, timeout=20_000)
                        else:
                            logger.debug("Selector %s not found on %s, continuing", wait_selector, url)
                await self.polite_delay(1.5)
                return
            except Exception as exc:
                last_error = exc
                logger.warning("safe_goto attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, exc)
                if attempt < MAX_RETRIES:
                    await self.polite_delay(2.0)
        raise last_error or RuntimeError(f"Failed to navigate to {url}")

    async def stop(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    async def __aenter__(self) -> "BaseDriver":
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.stop()

    async def polite_delay(self, seconds: float = ACTION_DELAY_SEC) -> None:
        await asyncio.sleep(seconds)

    async def dismiss_schneider_terms(self, page: Optional[Page] = None) -> None:
        pg = page or self.page
        selectors = [
            '[aria-label="Terms and Conditions"] button:has-text("Accept")',
            '[aria-label="Terms and Conditions"] a:has-text("Accept")',
            '[aria-label="Terms and Conditions"] .btn-primary',
            '.modal.in button:has-text("Accept")',
            '.modal.in button:has-text("I Accept")',
            '.modal.in button:has-text("Agree")',
            '.modal.in a:has-text("Accept")',
            '.modal.in a:has-text("I Accept")',
            '.modal.in .btn-primary',
            '.modal.in input[type="submit"]',
            '.modal-footer button',
            '.modal-footer .btn-primary',
        ]
        for selector in selectors:
            try:
                btn = pg.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible(timeout=800):
                    await btn.click(force=True)
                    await self.polite_delay(0.5)
                    return
            except Exception:
                pass

    async def dismiss_netronline_modals(self, page: Optional[Page] = None) -> None:
        pg = page or self.page
        selectors = [
            "button:has-text('Close')",
            "button:has-text('Accept')",
            "button:has-text('I Agree')",
            "button:has-text('Continue')",
            "button:has-text('No Thanks')",
            ".modal button.close",
            ".modal .close",
            "[aria-label='Close']",
            "#adblock-close",
        ]
        for selector in selectors:
            try:
                btn = pg.locator(selector).first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    await self.polite_delay(0.5)
            except Exception:
                pass

    async def screenshot_on_failure(self, name: str) -> Optional[str]:
        try:
            path = self.screenshot_dir / f"{name}.png"
            await self.page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception as exc:
            logger.warning("Screenshot failed: %s", exc)
            return None

    async def with_retry(
        self,
        fn: Callable[[], T],
        label: str = "operation",
        retries: int = MAX_RETRIES,
    ) -> T:
        last_error: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                result = fn()
                if asyncio.iscoroutine(result):
                    return await result
                return result
            except Exception as exc:
                last_error = exc
                logger.warning("%s attempt %d/%d failed: %s", label, attempt, retries, exc)
                if attempt < retries:
                    await self.screenshot_on_failure(f"{label}_retry_{attempt}")
                    await self.polite_delay(2.0)
        raise last_error or RuntimeError(f"{label} failed after {retries} retries")
