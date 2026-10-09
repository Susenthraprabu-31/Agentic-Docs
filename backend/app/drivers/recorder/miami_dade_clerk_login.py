"""Automatic login for Miami-Dade Clerk official records (Turnstile / Register-Login)."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from app.config.florida_portals import MIAMI_DADE_RECORDER_SEARCH_URL
from app.config.settings import get_settings

if TYPE_CHECKING:
    from app.drivers.base.base_driver import BaseDriver

logger = logging.getLogger(__name__)

MIAMI_DADE_CLERK_LOGIN_URL = "https://www2.miamidadeclerk.gov/usermanagementservices"


def miami_dade_clerk_credentials_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.miami_dade_clerk_auto_login
        and settings.miami_dade_clerk_username.strip()
        and settings.miami_dade_clerk_password
    )


async def is_miami_dade_clerk_logged_in(driver: "BaseDriver") -> bool:
    """Return True when the clerk portal shows an authenticated session."""
    try:
        return bool(
            await driver.page.evaluate(
                """() => {
                    const text = (document.body?.innerText || '').toLowerCase();
                    const url = window.location.href.toLowerCase();
                    if (url.includes('usermanagementservices')) {
                        const hasPassword = document.querySelector('input[type="password"]');
                        const hasLoginBtn = [...document.querySelectorAll('button, input[type="submit"]')]
                            .some((el) => /login/i.test((el.textContent || el.value || '').trim()));
                        if (hasPassword && hasLoginBtn) return false;
                    }
                    if (text.includes('my account')) return true;
                    if (text.includes('log out') || text.includes('logout')) return true;
                    const loginLink = [...document.querySelectorAll('a')].find((el) =>
                        /register\\s*\\/\\s*login/i.test((el.textContent || '').trim())
                    );
                    if (loginLink && loginLink.offsetParent !== null) return false;
                    return url.includes('officialrecords');
                }"""
            )
        )
    except Exception as exc:
        logger.debug("Could not detect Miami-Dade clerk login state: %s", exc)
        return False


async def _fill_first_visible(driver: "BaseDriver", selectors: list[str], value: str) -> bool:
    for sel in selectors:
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible(timeout=2_000):
                await loc.click()
                await loc.fill(value)
                return True
        except Exception:
            continue
    return False


async def _click_first_visible(driver: "BaseDriver", selectors: list[str]) -> bool:
    for sel in selectors:
        try:
            loc = driver.page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible(timeout=2_000):
                await loc.click()
                return True
        except Exception:
            continue
    return False


async def _open_miami_dade_clerk_login_page(driver: "BaseDriver") -> bool:
    current = (driver.page.url or "").lower()
    if "usermanagementservices" in current:
        return True

    if "officialrecords" in current or "miamidadeclerk.gov" in current:
        clicked = await _click_first_visible(
            driver,
            [
                'a:has-text("Register/Login")',
                'a:has-text("Register")',
                'a:has-text("Login")',
            ],
        )
        if clicked:
            await driver.polite_delay(2.0)
            await driver.page.wait_for_load_state("domcontentloaded")
            if "usermanagementservices" in (driver.page.url or "").lower():
                return True

    try:
        await driver.page.goto(
            MIAMI_DADE_CLERK_LOGIN_URL,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await driver.polite_delay(1.5)
        return "usermanagementservices" in (driver.page.url or "").lower()
    except Exception as exc:
        logger.debug("Could not open Miami-Dade clerk login page: %s", exc)
        return False


async def login_miami_dade_clerk(
    driver: "BaseDriver",
    username: str,
    password: str,
) -> bool:
    """Submit the Miami-Dade User Management System login form."""
    username = username.strip()
    if not username or not password:
        return False

    if not await _open_miami_dade_clerk_login_page(driver):
        await driver._emit_status("Miami-Dade clerk login: could not open login page.")
        return False

    await driver._emit_status("Miami-Dade clerk login: entering credentials...")
    user_filled = await _fill_first_visible(
        driver,
        [
            'input[name="UserName"]',
            'input[name="username"]',
            'input[name="email"]',
            'input[id*="username" i]',
            'input[id*="userid" i]',
            'input[type="email"]',
            'input[placeholder*="User ID" i]',
            'input[placeholder*="Email" i]',
        ],
        username,
    )
    if not user_filled:
        user_filled = await _fill_first_visible(
            driver,
            ['label:has-text("User ID") ~ input', 'label:has-text("Email") ~ input'],
            username,
        )

    password_filled = await _fill_first_visible(
        driver,
        ['input[type="password"]', 'input[name="Password"]', 'input[name="password"]'],
        password,
    )

    if not user_filled or not password_filled:
        await driver._emit_status(
            "Miami-Dade clerk login: could not find username/password fields on login page."
        )
        await driver.screenshot_on_failure("miami_dade_clerk_login_form_missing")
        return False

    clicked = await _click_first_visible(
        driver,
        [
            'button:has-text("LOGIN")',
            'input[type="submit"][value*="LOGIN" i]',
            'button[type="submit"]',
            'input[type="submit"]',
        ],
    )
    if not clicked:
        await driver._emit_status("Miami-Dade clerk login: LOGIN button not found.")
        return False

    await driver.polite_delay(3.0)
    try:
        await driver.page.wait_for_load_state("domcontentloaded", timeout=30_000)
    except Exception:
        pass

    body_text = ""
    try:
        body_text = await driver.page.inner_text("body")
    except Exception:
        pass
    if re.search(r"invalid|incorrect|failed|error", body_text or "", re.I):
        await driver._emit_status(
            "Miami-Dade clerk login: login may have failed — check MIAMI_DADE_CLERK_USERNAME "
            "and MIAMI_DADE_CLERK_PASSWORD in .env."
        )
        await driver.screenshot_on_failure("miami_dade_clerk_login_failed")
        return False

    await driver._emit_status("Miami-Dade clerk login: credentials submitted.")
    return True


async def ensure_miami_dade_clerk_logged_in(
    driver: "BaseDriver",
    *,
    return_url: str | None = None,
) -> bool:
    """Log in to Miami-Dade clerk when credentials are configured and session is missing."""
    if not miami_dade_clerk_credentials_configured():
        return False

    if await is_miami_dade_clerk_logged_in(driver):
        return True

    settings = get_settings()
    await driver._emit_status(
        "Miami-Dade recorder: session not authenticated — attempting automatic clerk login..."
    )
    logged_in = await login_miami_dade_clerk(
        driver,
        settings.miami_dade_clerk_username,
        settings.miami_dade_clerk_password,
    )
    if not logged_in:
        return False

    target = return_url or MIAMI_DADE_RECORDER_SEARCH_URL
    try:
        await driver.page.goto(target, wait_until="domcontentloaded", timeout=60_000)
        await driver.polite_delay(2.0)
    except Exception as exc:
        logger.debug("Could not return to official records after login: %s", exc)

    if await is_miami_dade_clerk_logged_in(driver):
        await driver._emit_status("Miami-Dade recorder: automatic clerk login succeeded.")
        return True

    await driver._emit_status(
        "Miami-Dade recorder: login submitted but session could not be verified."
    )
    return False
