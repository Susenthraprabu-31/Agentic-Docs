import asyncio
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional, TypeVar, Union

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Route, async_playwright

from app.config.settings import get_settings
from app.drivers.browser_factory import (
    CDPConnectionError,
    create_browser_session,
    human_delay,
    import_cookies_for_url,
    navigate_with_cloudflare_retry,
)
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

CLOUDFLARE_HARD_BLOCK_HELP = (
    "Cloudflare Error 1020 — this IP is permanently blocked from schneidercorp.com. "
    "Consumer VPNs (Windscribe, NordVPN, etc.) often use datacenter IPs that Cloudflare "
    "also blocks. Fix: (1) Close ALL Chrome windows, (2) Connect VPN, "
    "(3) Run backend/scripts/reset_dono_chrome_profile.ps1, (4) Restart backend, "
    "(5) Open a NEW tab in the CDP Chrome window and manually visit the county assessor URL, "
    "(6) If still blocked, try a different VPN city or use a residential proxy (IPRoyal/Smartproxy). "
    "Do NOT refresh the blocked page — open a fresh tab instead."
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
        "fragments": ("miamidade.gov", "propertysearch"),
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
    {
        "fragments": ("schneidercorp.com",),
        "wait_selector": (
            "#ctlBodyPane, .widgetLabel, #ctlBodyPane_ctl02_ctl01_txtParcelID, "
            "input[id*='Parcel' i], input[id*='Address' i]"
        ),
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
        self._cloudflare_recovery_attempted = False
        self._use_persistent_profile = True
        self._connected_via_cdp = False
        self._cancel_requested = False

    def inherit_browser_from(self, source: "BaseDriver") -> None:
        """Share an existing Playwright session (preserves CDP attach state)."""
        self._page = source._page
        self._context = source._context
        self._browser = source._browser
        self._playwright = source._playwright
        self._connected_via_cdp = source._connected_via_cdp
        self._browser_stream = source._browser_stream
        self.screenshot_dir = source.screenshot_dir
        self.status_callback = source.status_callback
        self.preview_run_id = source.preview_run_id
        if source.playwright_notes and not self.playwright_notes:
            self.playwright_notes = source.playwright_notes

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

    def request_cancellation(self) -> None:
        self._cancel_requested = True

    def _check_run_cancelled(self) -> None:
        from app.queue.run_cancellation import RunCancelledError, check_run_cancelled

        if self._cancel_requested:
            raise RunCancelledError("Pipeline stopped by user")
        check_run_cancelled(self.preview_run_id)

    async def _emit_status(self, message: str) -> None:
        self._check_run_cancelled()
        logger.info(message)
        if not self.status_callback:
            return
        result = self.status_callback(message)
        if asyncio.iscoroutine(result):
            await result

    async def start(
        self,
        headless: bool | None = None,
        use_persistent_profile: bool | None = None,
    ) -> None:
        settings = get_settings()
        if headless is None:
            headless = settings.playwright_headless
        # Live preview runs need a visible Chrome window — Cloudflare blocks headless bots.
        if self.preview_run_id:
            headless = False
        if use_persistent_profile is not None:
            self._use_persistent_profile = use_persistent_profile

        self._playwright = await async_playwright().start()

        try:
            session = await create_browser_session(
                self._playwright,
                headless=headless,
                use_persistent_profile=self._use_persistent_profile,
                profile_launch_lock=_profile_launch_lock,
                emit_status=self._emit_status,
            )
        except CDPConnectionError as exc:
            raise RuntimeError(str(exc)) from exc

        self._browser = session.browser
        self._context = session.context
        self._page = session.page
        self._connected_via_cdp = session.connected_via_cdp

        await self._setup_request_blocking()

        if self._connected_via_cdp:
            if await self._find_working_schneider_tab():
                await self._emit_status("Reusing your working county portal tab in Chrome.")
            else:
                await self._emit_status(
                    "Connected to Chrome via CDP — importing trusted cookies from your regular browser."
                )

    async def _bootstrap_trusted_portal_cookies(self, url: str | None = None) -> int:
        """Compatibility no-op: clearance-cookie import and challenge solvers are disabled."""
        return 0

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
        if self._connected_via_cdp:
            return await self.ensure_page_alive()

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

    async def _setup_request_blocking(self) -> None:
        if self._connected_via_cdp:
            return

        async def _handle_route(route: Route) -> None:
            url = route.request.url.lower()
            if any(host in url for host in ("schneidercorp.com", "qpublic.net", "challenges.cloudflare.com")):
                await route.continue_()
                return
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
                        if (root) {
                            if (root.querySelector('input[type="text"], mat-tab-group, [role="tab"]')) {
                                return true;
                            }
                            if (root.children.length > 0) return true;
                        }
                        const tabs = document.querySelector(
                            'mat-tab-group, [role="tablist"], [role="tab"]'
                        );
                        if (tabs) return true;
                        return !!document.querySelector('input[type="text"], input[type="search"]');
                    }"""
                )
            )
        except Exception:
            return False

    async def _wait_for_spa_shell(self, selector: str, timeout_ms: int = 45_000) -> bool:
        """Poll until an Angular/React SPA renders its interactive shell."""
        deadline = time.monotonic() + (timeout_ms / 1000)
        next_preview = 0.0
        while time.monotonic() < deadline:
            if await self._spa_shell_ready(selector):
                return True
            if await self.is_cloudflare_blocked():
                cleared = await self.wait_for_cloudflare_clear(
                    max_wait=min(45, int(deadline - time.monotonic())),
                    success_selector=selector,
                )
                if cleared and await self._spa_shell_ready(selector):
                    return True
            now = time.monotonic()
            if now >= next_preview:
                await self.save_browser_preview()
                next_preview = now + 2.0
            await asyncio.sleep(1.0)
        return await self._spa_shell_ready(selector)

    async def has_actionable_page_content(self, page: Optional[Page] = None) -> bool:
        """True when a county portal page has loaded (not a bare Cloudflare interstitial)."""
        pg = page or self.page
        try:
            url = pg.url.lower()
            if (
                ("miamidadepa.gov" in url or "miamidade.gov" in url)
                and "propertysearch" in url
            ):
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
                if await pg.locator(
                    'input[placeholder*="Search by name" i], input[placeholder*="parcel ID" i]'
                ).count():
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

    async def _focus_schneider_tab(self) -> None:
        """When attached over CDP, switch to an open Schneider/qPublic tab if present."""
        if await self._find_working_schneider_tab():
            return
        if not self._context:
            return
        for pg in self._context.pages:
            try:
                url = pg.url.lower()
                if "schneidercorp.com" in url or "qpublic.net" in url:
                    await self.set_active_page(pg)
                    return
            except Exception:
                continue

    async def _find_working_schneider_tab(self, page: Optional[Page] = None) -> bool:
        """Switch to a Schneider tab that is past Cloudflare and has search UI."""
        if not self._context:
            return False
        for pg in self._context.pages:
            try:
                url = pg.url.lower()
                if "schneidercorp.com" not in url and "qpublic.net" not in url:
                    continue
                if await self.is_cloudflare_hard_block(pg):
                    continue
                if await self.has_actionable_page_content(pg):
                    await self.set_active_page(pg)
                    return True
            except Exception:
                continue
        return False

    async def _open_fresh_portal_tab(self) -> None:
        """Open a clean tab in CDP Chrome so the user is not stuck on a blocked page."""
        if not self._context or not self._connected_via_cdp:
            return
        try:
            fresh = await self._context.new_page()
            await self.set_active_page(fresh)
            if self.preview_run_id:
                await self.start_live_stream(self.preview_run_id)
            await self._emit_status(
                "Opened a fresh Chrome tab — paste the county assessor URL here and complete any security check."
            )
        except Exception as exc:
            logger.debug("Could not open fresh portal tab: %s", exc)

    async def wait_for_manual_schneider_portal(
        self,
        max_wait: int | None = None,
        success_selector: str | None = None,
    ) -> bool:
        """Wait for the user to open a working county portal tab — never navigates."""
        settings = get_settings()
        wait_seconds = max_wait or settings.playwright_cloudflare_wait_seconds
        await self._emit_status(CLOUDFLARE_HARD_BLOCK_HELP)

        if await self._find_working_schneider_tab():
            return True

        deadline = time.monotonic() + wait_seconds
        last_hint = 0.0
        while time.monotonic() < deadline:
            self._check_run_cancelled()
            await self.save_browser_preview()
            await asyncio.sleep(2)

            if await self._find_working_schneider_tab():
                await self._emit_status("County portal ready in Chrome — continuing.")
                return True

            if success_selector:
                try:
                    if await self.page.locator(success_selector).first.is_visible(timeout=500):
                        await self._emit_status("County portal ready — continuing.")
                        return True
                except Exception:
                    pass

            now = time.monotonic()
            if now - last_hint >= 30:
                last_hint = now
                await self._emit_status(
                    "Still waiting — open a NEW tab in the CDP Chrome window, "
                    "paste the county assessor URL, and complete any security check."
                )

        await self._emit_status("Timed out waiting for county portal. Reset Chrome profile and try again.")
        return False

    async def safe_schneider_goto(
        self,
        url: str,
        wait_selector: str | None = None,
        timeout: int = 60_000,
    ) -> bool:
        """Navigate to a Schneider portal without re-triggering Cloudflare when already on-site."""
        from app.config.schneider_portals import (
            is_same_schneider_portal,
            is_schneider_portal,
            is_schneider_search_url,
            normalize_schneider_search_url,
        )

        if not is_schneider_portal(url):
            await self.safe_goto(url, wait_selector=wait_selector, timeout=timeout)
            return True

        target = normalize_schneider_search_url(url)
        if not await self.ensure_page_alive():
            return False

        try:
            current = self.page.url
        except Exception:
            current = ""

        if (
            is_schneider_portal(current)
            and await self.has_actionable_page_content()
            and not await self.is_cloudflare_blocked()
        ):
            if is_schneider_search_url(target) and is_same_schneider_portal(current, target):
                return True
            if is_schneider_search_url(target) and await self._has_schneider_county_form():
                return True

        if await self.is_cloudflare_hard_block() or await self.is_cloudflare_blocked():
            await self._bootstrap_trusted_portal_cookies(url=target)
            if await self._find_working_schneider_tab():
                return True
            if await self._retry_schneider_navigation_with_cookies(target, timeout):
                return True
            settings = get_settings()
            if self._connected_via_cdp:
                return await self.wait_for_manual_schneider_portal(
                    success_selector=wait_selector or (
                        "#ctlBodyPane, .widgetLabel, input[placeholder*='parcel' i], input"
                    ),
                )
            return False

        if self._connected_via_cdp and await self._find_working_schneider_tab():
            if is_schneider_search_url(target) and is_same_schneider_portal(self.page.url, target):
                return True

        await self._bootstrap_trusted_portal_cookies(url=target)
        try:
            await self.page.goto(target, wait_until="domcontentloaded", timeout=timeout)
            await self.dismiss_schneider_terms()
            await self.save_browser_preview()
        except Exception as exc:
            logger.warning("Schneider navigation failed for %s: %s", target, exc)
            if await self.has_actionable_page_content():
                return True
            return False

        if await self.is_cloudflare_blocked():
            cleared = await self.wait_for_portal_access(
                success_selector=wait_selector or "#ctlBodyPane, .widgetLabel, input",
            )
            if not cleared:
                return False

        if wait_selector:
            try:
                await self.page.wait_for_selector(wait_selector, timeout=20_000)
            except Exception:
                pass
        return await self.has_actionable_page_content() or await self._has_schneider_county_form()

    async def _retry_schneider_navigation_with_cookies(self, target: str, timeout: int) -> bool:
        """After importing system Chrome cookies, open county URL in a fresh tab."""
        if not self._context:
            return False
        try:
            fresh = await self._context.new_page()
            await self.set_active_page(fresh)
            await fresh.goto(target, wait_until="domcontentloaded", timeout=timeout)
            await self.dismiss_schneider_terms(fresh)
            if await self.is_cloudflare_blocked(fresh):
                return False
            return await self.has_actionable_page_content(fresh) or await self._has_schneider_county_form()
        except Exception as exc:
            logger.debug("Cookie-bootstrap navigation failed: %s", exc)
            return False

    async def _has_schneider_county_form(self) -> bool:
        try:
            selectors = (
                "#ctlBodyPane_ctl02_ctl01_txtParcelID",
                "#ctlBodyPane_ctl01_ctl01_txtAddress",
                'input[id*="Parcel" i]',
                'input[placeholder*="parcel" i]',
                'input[placeholder*="enter parcel" i]',
                'input[placeholder*="enter name" i]',
                'input[placeholder*="enter address" i]',
            )
            for sel in selectors:
                loc = self.page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible(timeout=1_000):
                    return True
        except Exception:
            pass
        return False

    def _rotate_flagged_profile(self) -> None:
        settings = get_settings()
        profile_dir = settings.playwright_user_data_dir.strip()
        if not profile_dir:
            return
        profile_path = Path(profile_dir)
        if not profile_path.exists():
            return
        backup = profile_path.with_name(f"{profile_path.name}.blocked.{int(time.time())}")
        try:
            shutil.move(str(profile_path), str(backup))
            logger.info("Rotated flagged Playwright profile to %s", backup)
        except Exception as exc:
            logger.warning("Could not rotate Playwright profile: %s", exc)

    async def _clear_schneider_cookies(self) -> None:
        if not self._context:
            return
        try:
            cookies = await self._context.cookies()
            keep = [
                cookie
                for cookie in cookies
                if not any(
                    token in (cookie.get("domain") or "").lower()
                    for token in ("schneidercorp", "qpublic", "cloudflare")
                )
            ]
            await self._context.clear_cookies()
            if keep:
                await self._context.add_cookies(keep)
        except Exception as exc:
            logger.debug("Schneider cookie clear skipped: %s", exc)

    async def recover_from_cloudflare_block(self) -> bool:
        """Clear flagged Schneider session state and restart the browser once."""
        if self._cloudflare_recovery_attempted:
            return False
        self._cloudflare_recovery_attempted = True

        settings = get_settings()
        if self._connected_via_cdp or settings.playwright_cdp_url.strip():
            await self._clear_schneider_cookies()
            if await self.is_cloudflare_hard_block():
                await self._emit_status(CLOUDFLARE_HARD_BLOCK_HELP)
            else:
                await self._emit_status(
                    "Cloudflare challenge in Chrome — open a NEW tab, visit the county portal, "
                    "complete verification, then wait. Automation continues automatically."
                )
            return False

        await self._emit_status(
            "Cloudflare block detected — clearing portal cookies and restarting browser..."
        )
        await self._clear_schneider_cookies()
        if not await self.is_cloudflare_hard_block():
            return True

        preview_run_id = self.preview_run_id
        status_callback = self.status_callback
        playwright_notes = self.playwright_notes
        screenshot_dir = self.screenshot_dir

        await self.stop()
        self._rotate_flagged_profile()

        self.preview_run_id = preview_run_id
        self.status_callback = status_callback
        self.playwright_notes = playwright_notes
        self.screenshot_dir = screenshot_dir
        self._use_persistent_profile = True

        await self.start(headless=False, use_persistent_profile=True)
        if preview_run_id:
            from app.drivers.browser_registry import register_driver

            register_driver(preview_run_id, self)
            await self.start_live_stream(preview_run_id)
        await self._emit_status("Fresh browser session started — retrying county portal.")
        return True

    async def click_at_normalized(self, x: float, y: float) -> None:
        """Click within the page viewport using normalized 0–1 coordinates (Live preview)."""
        x_clamped = max(0.0, min(1.0, x))
        y_clamped = max(0.0, min(1.0, y))
        viewport = self.page.viewport_size or {"width": 1366, "height": 900}
        px = int(x_clamped * viewport["width"])
        py = int(y_clamped * viewport["height"])
        await self.page.mouse.click(px, py)
        await self.polite_delay(0.3)

    async def wait_for_portal_access(
        self,
        max_wait: int | None = None,
        success_selector: str | None = None,
    ) -> bool:
        """Wait until a county portal is usable — user solves Cloudflare in Live Browser first.

        Distinguishes between:
        - Hard block (Error 1020 "Sorry, you have been blocked"): permanent IP ban,
          cannot be resolved by the user in the browser — exits immediately.
        - Solvable challenge ("Just a moment" / "Verify you are human"): waits for
          the user to complete verification in the Live Browser.
        """
        settings = get_settings()
        wait_seconds = max_wait or settings.playwright_cloudflare_wait_seconds

        if success_selector:
            try:
                if await self.page.locator(success_selector).first.is_visible(timeout=2000):
                    return True
            except Exception:
                pass

        if await self.has_actionable_page_content() and not await self.is_cloudflare_blocked():
            return True

        # ── Hard block (Error 1020) — when CDP Chrome is connected, wait for the user
        # to open the county site in their real Chrome window instead of failing immediately.
        is_hard_block = await self.is_cloudflare_hard_block()
        if is_hard_block:
            current_url = ""
            try:
                current_url = self.page.url
            except Exception:
                pass
            is_schneider = any(
                host in current_url.lower() for host in ("schneidercorp.com", "qpublic.net")
            )
            if self._connected_via_cdp:
                if await self._find_working_schneider_tab():
                    return True
                if await self.is_cloudflare_hard_block():
                    await self._open_fresh_portal_tab()
                    return await self.wait_for_manual_schneider_portal(success_selector=success_selector)
                await self._open_fresh_portal_tab()
                await self._emit_status(
                    "Cloudflare challenge in Chrome — use the new tab, visit the county portal, "
                    "complete verification, then wait. Automation continues automatically."
                )
            elif is_schneider:
                hard_block_msg = (
                    "ACCESS DENIED — Cloudflare has permanently blocked this IP address from "
                    "schneidercorp.com / qPublic portals (Error 1020). "
                    "Set PLAYWRIGHT_CDP_URL=http://127.0.0.1:9222 in backend/.env to use your "
                    "real Chrome browser, or use a residential proxy / VPN."
                )
                await self._emit_status(hard_block_msg)
                if not self._cloudflare_recovery_attempted:
                    if await self.recover_from_cloudflare_block():
                        return False
                return False
            else:
                hard_block_msg = (
                    f"ACCESS DENIED — Cloudflare permanently blocked this IP from {current_url}. "
                    "Try CDP Chrome (PLAYWRIGHT_CDP_URL in .env) or a VPN."
                )
                await self._emit_status(hard_block_msg)
                if not self._cloudflare_recovery_attempted:
                    if await self.recover_from_cloudflare_block():
                        return False
                return False

        # ── Solvable challenge: wait for user to complete verification ──
        if self.preview_run_id:
            await self._emit_status(
                "Security check — switch to Live Browser (Output tab), complete the verification "
                "(checkbox or 'Verify you are human'), then wait. Automation continues automatically."
            )
        elif not await self.is_cloudflare_blocked():
            return True
        elif not self._connected_via_cdp:
            if await self.recover_from_cloudflare_block():
                return False
            await self._emit_status(
                "Cloudflare challenge detected. Run with Live Browser to complete verification."
            )
            return False

        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            self._check_run_cancelled()
            await self.save_browser_preview()
            await asyncio.sleep(2)

            if await self.is_cloudflare_hard_block():
                if self._connected_via_cdp:
                    await self._focus_schneider_tab()
                    if await self.has_actionable_page_content():
                        await self._emit_status("County portal ready — continuing.")
                        return True
                else:
                    await self._emit_status(
                        "Cloudflare upgraded to a hard IP block during wait. "
                        "Cannot continue — use CDP Chrome or VPN and re-run."
                    )
                    return False

            if success_selector:
                try:
                    if await self.page.locator(success_selector).first.is_visible(timeout=500):
                        await self._emit_status("County portal ready — continuing.")
                        return True
                except Exception:
                    pass
            if await self.has_actionable_page_content() and not await self.is_cloudflare_blocked():
                await self._emit_status("County portal loaded — continuing.")
                return True
            if not await self.is_cloudflare_blocked():
                await self.polite_delay(1.5)
                return True

        await self._emit_status("Portal security check timed out — re-run after completing verification.")
        return False

    async def wait_for_cloudflare_clear(
        self,
        max_wait: int | None = None,
        success_selector: str | None = None,
    ) -> bool:
        """Pause until Cloudflare clears — user can click in the Live preview panel."""
        return await self.wait_for_portal_access(max_wait=max_wait, success_selector=success_selector)

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
        from app.config.florida_portals import normalize_miami_dade_property_search_url

        url = normalize_miami_dade_property_search_url(url)
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
                await import_cookies_for_url(self.context, url)

                async def _navigate() -> None:
                    await self.page.goto(url, wait_until=wait_until, timeout=nav_timeout)

                await navigate_with_cloudflare_retry(self.page, _navigate)
                await self.save_browser_preview()

                if shell_selector:
                    shell_timeout = min(nav_timeout, 60_000)
                    try:
                        await self.page.wait_for_selector(
                            shell_selector, timeout=min(25_000, shell_timeout), state="attached"
                        )
                    except Exception:
                        pass
                    if not await self._wait_for_spa_shell(shell_selector, timeout_ms=shell_timeout):
                        current_url = self.page.url
                        recovered = normalize_miami_dade_property_search_url(current_url)
                        if recovered != current_url and recovered != url:
                            logger.info(
                                "SPA shell missing at %s — retrying canonical Miami-Dade URL %s",
                                current_url,
                                recovered,
                            )
                            await self.page.goto(
                                recovered, wait_until=wait_until, timeout=nav_timeout
                            )
                            if await self._wait_for_spa_shell(shell_selector, timeout_ms=shell_timeout):
                                await self.polite_delay(1.5)
                                await self.save_browser_preview()
                                return
                        if spa_profile:
                            raise TimeoutError(
                                f"SPA shell not ready after navigation to {self.page.url or url}"
                            )
                        logger.debug(
                            "Optional selector %s not ready on %s — continuing",
                            shell_selector,
                            self.page.url or url,
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
        # CDP attach — disconnect Playwright only; never close the user's Chrome window.
        if self._connected_via_cdp:
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as exc:
                    logger.debug("Playwright stop skipped: %s", exc)
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
            self._connected_via_cdp = False
            return
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
        self._check_run_cancelled()
        settings = get_settings()
        if settings.use_human_delays:
            await human_delay(run_id=self.preview_run_id)
        else:
            await asyncio.sleep(seconds)
        self._check_run_cancelled()

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
