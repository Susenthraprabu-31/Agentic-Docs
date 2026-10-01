"""Persist Cloudflare / portal cookies per host so counties reuse trusted sessions."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from app.drivers.base.base_driver import BaseDriver

logger = logging.getLogger(__name__)

SESSION_DIR = Path(__file__).resolve().parents[2] / "local_storage" / "browser_sessions"


def portal_session_key(url: str) -> str:
    host = urlparse(url).netloc.lower().replace(":", "_")
    return host or "unknown"


def session_file_for(url: str) -> Path:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_DIR / f"{portal_session_key(url)}.json"


async def load_portal_cookies(driver: "BaseDriver", url: str) -> bool:
    path = session_file_for(url)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        cookies = payload.get("cookies") or []
        if cookies and driver.context:
            await driver.context.add_cookies(cookies)
            logger.info("Loaded %d cookies for %s", len(cookies), portal_session_key(url))
            return True
    except Exception as exc:
        logger.debug("Could not load portal cookies for %s: %s", url, exc)
    return False


async def save_portal_cookies(driver: "BaseDriver", url: str) -> None:
    if not driver.context:
        return
    try:
        cookies = await driver.context.cookies()
        host = portal_session_key(url)
        relevant = [
            cookie
            for cookie in cookies
            if host in (cookie.get("domain") or "").lstrip(".").lower()
            or any(token in (cookie.get("domain") or "").lower() for token in ("schneidercorp", "qpublic", "cloudflare"))
        ]
        if not relevant:
            relevant = cookies
        path = session_file_for(url)
        path.write_text(
            json.dumps({"domain": host, "cookies": relevant}, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved %d cookies for %s", len(relevant), host)
    except Exception as exc:
        logger.debug("Could not save portal cookies for %s: %s", url, exc)
