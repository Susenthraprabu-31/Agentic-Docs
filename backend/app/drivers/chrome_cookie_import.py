"""Import Cloudflare / portal cookies from the user's regular Chrome into automation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Iterable
from urllib.parse import urlparse

from app.drivers.browser_sessions import save_portal_cookies

if TYPE_CHECKING:
    from app.drivers.base.base_driver import BaseDriver

logger = logging.getLogger(__name__)

SCHNEIDER_DOMAINS = ("schneidercorp.com", "qpublic.net", "cloudflare.com")


def _to_playwright_cookie(cookie: object) -> dict:
    same_site = "Lax"
    http_only = False
    rest = getattr(cookie, "_rest", None) or {}
    if isinstance(rest, dict):
        http_only = bool(rest.get("HttpOnly") or rest.get("httponly"))
    expires = getattr(cookie, "expires", None)
    return {
        "name": cookie.name,
        "value": cookie.value,
        "domain": cookie.domain,
        "path": cookie.path or "/",
        "expires": float(expires) if expires else -1,
        "httpOnly": http_only,
        "secure": bool(getattr(cookie, "secure", False)),
        "sameSite": same_site,
    }


def read_system_chrome_cookies(
    domains: Iterable[str] = SCHNEIDER_DOMAINS,
) -> list[dict]:
    """Read cookies from the user's installed Chrome (Windows/macOS/Linux)."""
    try:
        import browser_cookie3
    except ImportError:
        logger.warning("browser-cookie3 not installed — run: pip install browser-cookie3")
        return []

    collected: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for domain in domains:
        try:
            for cookie in browser_cookie3.chrome(domain_name=domain):
                key = (cookie.name, cookie.domain, cookie.path or "/")
                if key in seen:
                    continue
                seen.add(key)
                collected.append(_to_playwright_cookie(cookie))
        except Exception as exc:
            logger.debug("System Chrome cookie read failed for %s: %s", domain, exc)
    return collected


async def apply_system_chrome_cookies(
    driver: "BaseDriver",
    url: str | None = None,
    domains: Iterable[str] = SCHNEIDER_DOMAINS,
) -> int:
    """Inject cookies from regular Chrome into the automation browser context."""
    if not driver.context:
        return 0

    cookies = read_system_chrome_cookies(domains=domains)
    if not cookies:
        return 0

    try:
        await driver.context.add_cookies(cookies)
        logger.info("Imported %d cookies from system Chrome", len(cookies))
        if url:
            await save_portal_cookies(driver, url)
        return len(cookies)
    except Exception as exc:
        logger.warning("Could not apply system Chrome cookies: %s", exc)
        return 0


def portal_domains_for_url(url: str) -> tuple[str, ...]:
    host = urlparse(url).netloc.lower()
    if "schneidercorp.com" in host or "qpublic.net" in host:
        return SCHNEIDER_DOMAINS
    return (host,) if host else SCHNEIDER_DOMAINS
