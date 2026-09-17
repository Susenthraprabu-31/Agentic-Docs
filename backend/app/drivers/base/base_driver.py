import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional, TypeVar, Union

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Route, async_playwright

from app.config.settings import get_settings
from app.drivers.browser_stream import BrowserStream

logger = logging.getLogger(__name__)

# Chrome allows only one process per user-data-dir; serialize persistent launches.
_profile_launch_lock = threading.Lock()

T = TypeVar("T")

StatusCallback = Callable[[str], Union[None, Awaitable[None]]]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT_MS = 45_000
NAVIGATION_TIMEOUT_MS = 45_000
ACTION_DELAY_SEC = 1.5
MAX_RETRIES = 3

STEALTH_INIT_SCRIPT = """
try {
    delete Object.getPrototypeOf(navigator).webdriver;
} catch (e) {}
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
if (!window.chrome) {
    window.chrome = {};
}
if (!window.chrome.runtime) {
    window.chrome.runtime = {
        connect: function() {},
        sendMessage: function() {}
    };
}
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

# Angular/React SPAs often never reach domcontentloaded before Playwright times out.
SPA_NAVIGATION_PROFILES: tuple[dict[str, object], ...] = (
    {
        "fragments": ("miamidadepa.gov", "propertysearch"),
        "wait_selector": "app-root, mat-tab-group, [role='tab'], input[type='text']",
        "timeout_ms": 60_000,
    },
    {
        "fragments": ("county-taxes.net",),
        "wait_selector": "input[type='text'], input[type='search'], iframe",
        "timeout_ms": 90_000,
    },
    {
        "fragments": ("county-taxes.com",),
        "wait_selector": "input[type='text'], input[type='search'], iframe",
        "timeout_ms": 90_000,
    },
    {
        "fragments": ("ocpaweb.ocpafl.org",),
        "wait_selector": "app-root, input, form",
        "timeout_ms": 60_000,
    },
    {
        "fragments": ("miamidadeclerk.gov", "officialrecords"),
        "wait_selector": (
            "#bookType, #recordingBookNumber, #recordingPageNumber, "
            "input[type='text'], form, button, app-root"
        ),
        "timeout_ms": 60_000,
    },
    {
        "fragments": ("officialrecords.broward.org",),
        "wait_selector": "input[type='text'], form, button, #MainContent",
        "timeout_ms": 60_000,
    },
    {
        "fragments": ("myfloridacounty.com",),
        "wait_selector": "input[type='text'], form, button, iframe",
        "timeout_ms": 60_000,
    },
)


def spa_navigation_profile(url: str) -> Optional[dict[str, object]]:
    lower = url.lower()
    for profile in SPA_NAVIGATION_PROFILES:
        fragments = profile.get("fragments") or ()
        if all(fragment in lower for fragment in fragments):
            return profile
    return None


class BaseDriver:
    def __init__(self, screenshot_dir: Optional[Path] = None) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self.screenshot_dir = screenshot_dir or Path("screenshots")
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.status_callback: Optional[StatusCallback] = None
        self.playwright_notes: Optional[str] = None
        self.preview_run_id: Optional[str] = None
        self._browser_stream: Optional[BrowserStream] = None

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
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ]
        if headless:
            launch_args.append("--headless=new")

        launch_kwargs: dict = {
            "headless": headless,
            "slow_mo": 0,
            "args": launch_args,
            "ignore_default_args": ["--enable-automation"],
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
                "user_agent": USER_AGENT,
                "accept_downloads": True,
            }

            self._context = await self._launch_persistent_context(
                profile_path,
                launch_kwargs,
                context_kwargs,
            )
            self._browser = None
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        else:
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
            context_kwargs = {
                "user_agent": USER_AGENT,
                "viewport": {"width": 1366, "height": 900},
                "locale": "en-US",
                "accept_downloads": True,
            }
            self._context = await self._browser.new_context(**context_kwargs)
            self._page = await self._context.new_page()

        self._context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        await self._apply_stealth()
        await self._setup_request_blocking()

    async def _launch_persistent_context(
        self,
        profile_path: Path,
        launch_kwargs: dict,
        context_kwargs: dict,
    ):
        last_error: Optional[Exception] = None
        for attempt in range(1, 3):
            with _profile_launch_lock:
                try:
                    return await self._playwright.chromium.launch_persistent_context(
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

    async def start_live_stream(self, run_id: str) -> None:
        """Begin CDP screencast → WebSocket frames for in-app browser preview."""
        self.preview_run_id = run_id
        if self._browser_stream:
            await self._browser_stream.stop()
        self._browser_stream = BrowserStream()
        await self._browser_stream.start(self.page, run_id)

    def _page_is_alive(self, page: Optional[Page] = None) -> bool:
        candidate = page or self._page
        if candidate is None:
            return False
        try:
            return not candidate.is_closed()
        except Exception:
            return False

    def _context_is_alive(self) -> bool:
        if self._context is None:
            return False
        try:
            _ = self._context.pages
            return True
        except Exception:
            return False

    async def ensure_page_alive(self) -> bool:
        """Recover a usable page when the active tab was closed by a prior node."""
        if not self._context_is_alive():
            return False
        if self._page_is_alive():
            return True

        for pg in list(self._context.pages):
            if self._page_is_alive(pg):
                self._page = pg
                if self.preview_run_id:
                    try:
                        await self.start_live_stream(self.preview_run_id)
                    except Exception as exc:
                        logger.debug("Failed to restart live stream on recovered page: %s", exc)
                return True

        try:
            self._page = await self._context.new_page()
            if self.preview_run_id:
                try:
                    await self.start_live_stream(self.preview_run_id)
                except Exception as exc:
                    logger.debug("Failed to start live stream on new page: %s", exc)
            return True
        except Exception as exc:
            logger.warning("Could not create replacement browser page: %s", exc)
            return False

    async def restart(self, headless: bool | None = None) -> None:
        """Restart Playwright after the browser window or context was closed."""
        preview_run_id = self.preview_run_id
        status_callback = self.status_callback
        playwright_notes = self.playwright_notes
        screenshot_dir = self.screenshot_dir
        await self.stop()
        self.preview_run_id = preview_run_id
        self.status_callback = status_callback
        self.playwright_notes = playwright_notes
        self.screenshot_dir = screenshot_dir
        await self.start(headless=headless)

    async def ensure_browser_ready(self) -> bool:
        """Ensure a live browser page exists, restarting the session if needed."""
        if await self.ensure_page_alive():
            return True
        try:
            await self._emit_status("Browser session ended — restarting for next step...")
            await self.restart()
            if self.preview_run_id:
                await self.start_live_stream(self.preview_run_id)
            return self._page_is_alive()
        except Exception as exc:
            logger.warning("Could not restart browser session: %s", exc)
            return False

    async def stabilize_browser_session(self) -> bool:
        """Keep one healthy tab open before the next pipeline node runs."""
        if not self._context_is_alive():
            return await self.ensure_browser_ready()

        pages: list[Page] = []
        try:
            for pg in list(self._context.pages):
                if self._page_is_alive(pg):
                    pages.append(pg)
        except Exception:
            return await self.ensure_browser_ready()

        if not pages:
            return await self.ensure_browser_ready()

        def _page_rank(pg: Page) -> int:
            try:
                url = pg.url.lower()
            except Exception:
                return 0
            if "officialrecords" in url and "recordpage" not in url:
                return 5
            if "propertysearch" in url or "miamidadepa" in url:
                return 4
            if "county-taxes" in url:
                return 4
            if "recordpage" in url:
                return 2
            if url.endswith(".pdf") or "/pdf" in url:
                return 1
            return 3

        best = max(pages, key=_page_rank)
        self._page = best
        for pg in pages:
            if pg is not best:
                try:
                    await pg.close()
                except Exception:
                    pass

        if self.preview_run_id:
            try:
                await self.start_live_stream(self.preview_run_id)
            except Exception as exc:
                logger.debug("Failed to refresh live stream after stabilization: %s", exc)
        return True

    async def set_active_page(self, new_page: Page) -> None:
        """Switch active page and transfer live browser screencast to the new page."""
        self._page = new_page
        if self.preview_run_id:
            try:
                await self.start_live_stream(self.preview_run_id)
            except Exception as exc:
                logger.debug("Failed to transfer live stream to new page: %s", exc)
        try:
            await self.save_browser_preview()
        except Exception:
            pass

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

    async def _spa_shell_ready(self, selector: str) -> bool:
        try:
            if await self.page.locator(selector).first.count() > 0:
                return True
            return bool(
                await self.page.evaluate(
                    """() => {
                        const root = document.querySelector('app-root');
                        if (root && root.children.length > 0) return true;
                        const tabs = document.querySelector('mat-tab-group, [role="tablist"]');
                        return !!tabs;
                    }"""
                )
            )
        except Exception:
            return False

    async def has_actionable_page_content(self, page: Optional[Page] = None) -> bool:
        """True when a county portal page has loaded (not a bare Cloudflare interstitial)."""
        pg = page or self.page
        try:
            url = pg.url.lower()
            if "miamidadepa.gov" in url and "propertysearch" in url:
                if await pg.locator("mat-tab-group, [role='tab'], input[type='text']").count():
                    return True
                if await pg.locator("app-root").count():
                    return True
            if "miamidadeclerk.gov" in url and "officialrecords" in url:
                if await pg.locator(
                    "#bookType, #recordingBookNumber, input[type='text'], form, button"
                ).count():
                    return True
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

    async def is_cloudflare_hard_block(self, page: Optional[Page] = None) -> bool:
        pg = page or self.page
        try:
            content = (await pg.content()).lower()
            return any(marker in content for marker in CLOUDFLARE_BLOCK_MARKERS)
        except Exception:
            return False

    async def click_at_normalized(self, x: float, y: float) -> None:
        """Click within the page viewport using normalized 0–1 coordinates (Live preview)."""
        x_clamped = max(0.0, min(1.0, x))
        y_clamped = max(0.0, min(1.0, y))
        viewport = self.page.viewport_size or {"width": 1366, "height": 900}
        px = int(x_clamped * viewport["width"])
        py = int(y_clamped * viewport["height"])
        await self.page.mouse.click(px, py)
        await self.polite_delay(0.3)

    async def wait_for_cloudflare_clear(
        self,
        max_wait: int | None = None,
        success_selector: str | None = None,
    ) -> bool:
        """Pause until Cloudflare clears — user can click in the Live preview panel."""
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

        if await self.is_cloudflare_hard_block():
            await self._emit_status(
                "Cloudflare hard block ('Sorry, you have been blocked'). "
                "Delete backend/.playwright-profile, restart the backend, or try a different network."
            )
            return False

        if self.preview_run_id:
            await self._emit_status(
                "Cloudflare check — click 'Verify you are human' in the Live preview on the right. "
                "Automation continues automatically after verification."
            )
        elif settings.playwright_headless:
            await self._emit_status(
                "Cloudflare blocked. Run the pipeline to use the Live preview for verification."
            )
            return False
        else:
            await self._emit_status(
                "Cloudflare verification required — complete the check to continue..."
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

    def _cloudflare_error_message(self) -> str:
        if self.preview_run_id:
            return (
                "Cloudflare blocked access to county portal. "
                "Click 'Verify you are human' in the Live preview on the right, then Run again."
            )
        return (
            "Cloudflare blocked access to county portal. "
            "Click Run and complete verification in the Live preview panel on the right."
        )

    async def safe_goto(
        self,
        url: str,
        wait_selector: Optional[str] = None,
        timeout: int = NAVIGATION_TIMEOUT_MS,
    ) -> None:
        """Navigate without networkidle — ad-heavy sites like NETR never go idle."""
        spa_profile = spa_navigation_profile(url)
        shell_selector = wait_selector or (
            str(spa_profile["wait_selector"]) if spa_profile else None
        )
        nav_timeout = int(spa_profile["timeout_ms"]) if spa_profile else timeout
        wait_until = "commit" if spa_profile else "domcontentloaded"

        last_error: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if not await self.ensure_page_alive():
                    raise RuntimeError("Browser page is not available")
                await self.page.goto(url, wait_until=wait_until, timeout=nav_timeout)

                if shell_selector:
                    try:
                        await self.page.wait_for_selector(shell_selector, timeout=25_000, state="attached")
                    except Exception:
                        if not await self._spa_shell_ready(shell_selector):
                            raise TimeoutError(
                                f"SPA shell not ready after navigation to {url}"
                            )

                if "schneidercorp.com" in url.lower():
                    has_form = await self.page.locator(
                        "#ctlBodyPane_ctl02_ctl01_txtParcelID, #ctlBodyPane_ctl01_ctl01_txtAddress"
                    ).count()
                    if not has_form and not await self.wait_for_cloudflare_clear(max_wait=45):
                        raise ValueError(self._cloudflare_error_message())
                elif await self.is_cloudflare_blocked():
                    await self.wait_for_cloudflare_clear(max_wait=45)

                if wait_selector and wait_selector != shell_selector:
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
                await self.save_browser_preview()
                return
            except Exception as exc:
                last_error = exc
                if spa_profile and shell_selector and await self._spa_shell_ready(shell_selector):
                    logger.info(
                        "Navigation reported an error for %s but SPA shell is ready — continuing",
                        url,
                    )
                    await self.polite_delay(1.5)
                    await self.save_browser_preview()
                    return
                logger.warning("safe_goto attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, exc)
                if attempt < MAX_RETRIES:
                    await self.polite_delay(2.0)
        raise last_error or RuntimeError(f"Failed to navigate to {url}")

    async def stop(self) -> None:
        if self._browser_stream:
            try:
                await self._browser_stream.stop()
            except Exception as exc:
                logger.debug("Browser stream stop skipped: %s", exc)
            self._browser_stream = None
        if self._context:
            try:
                await self._context.close()
            except Exception as exc:
                logger.debug("Browser context close skipped: %s", exc)
        if self._browser:
            try:
                await self._browser.close()
            except Exception as exc:
                logger.debug("Browser close skipped: %s", exc)
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as exc:
                logger.debug("Playwright stop skipped: %s", exc)
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

    async def save_browser_preview(self) -> Optional[str]:
        """Capture current page for the in-app browser preview panel."""
        if not self.preview_run_id or not self._page:
            return None
        try:
            path = self.screenshot_dir / f"preview_{self.preview_run_id}.png"
            await self.page.screenshot(path=str(path), full_page=False)
            return str(path)
        except Exception as exc:
            logger.debug("Browser preview capture failed: %s", exc)
            return None

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
