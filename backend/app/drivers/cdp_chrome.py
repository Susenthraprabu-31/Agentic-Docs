"""Start and verify a real Chrome instance for CDP attach (Cloudflare-safe)."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_CDP_PORT = 9222


def _cdp_version_url(cdp_url: str) -> str:
    base = cdp_url.rstrip("/")
    return f"{base}/json/version"


def is_cdp_chrome_running(cdp_url: str = DEFAULT_CDP_URL) -> bool:
    try:
        with urllib.request.urlopen(_cdp_version_url(cdp_url), timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _chrome_executable() -> str | None:
    if sys.platform == "win32":
        candidates = [
            os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(
                os.environ.get("ProgramFiles(x86)", ""),
                "Google",
                "Chrome",
                "Application",
                "chrome.exe",
            ),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        ]
    elif sys.platform == "darwin":
        candidates = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ]
    for path in candidates:
        if path and Path(path).exists():
            return path
    return None


def default_cdp_profile_dir() -> Path:
    from app.config.settings import get_settings

    custom = (get_settings().playwright_cdp_profile_dir or "").strip()
    if custom:
        return Path(custom)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "DonoChromeProfile"
    return Path.home() / ".dono-chrome-profile"


def rotate_cdp_profile() -> Path | None:
    """Rename the current CDP profile so the next launch starts clean."""
    profile = default_cdp_profile_dir()
    if not profile.exists():
        return None
    backup = profile.with_name(f"{profile.name}.blocked.{int(time.time())}")
    try:
        profile.rename(backup)
        logger.info("Rotated CDP profile to %s", backup)
        return backup
    except OSError as exc:
        logger.warning("Could not rotate CDP profile: %s", exc)
        return None


def launch_cdp_chrome(
    cdp_port: int = DEFAULT_CDP_PORT,
    profile_dir: Path | None = None,
    start_url: str = "about:blank",
) -> None:
    """Launch Chrome with remote debugging — no Playwright automation flags."""
    chrome = _chrome_executable()
    if not chrome:
        raise RuntimeError("Google Chrome not found. Install Chrome to use county portals.")

    profile = profile_dir or default_cdp_profile_dir()
    profile.mkdir(parents=True, exist_ok=True)

    args = [
        chrome,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={profile}",
        start_url,
    ]
    logger.info("Launching CDP Chrome (profile=%s, port=%s)", profile, cdp_port)
    subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


async def ensure_cdp_chrome(
    cdp_url: str = DEFAULT_CDP_URL,
    wait_seconds: int = 25,
) -> bool:
    """Ensure CDP Chrome is running; auto-launch if needed."""
    if is_cdp_chrome_running(cdp_url):
        return True

    try:
        port = int(cdp_url.rsplit(":", 1)[-1].rstrip("/"))
    except ValueError:
        port = DEFAULT_CDP_PORT

    try:
        launch_cdp_chrome(cdp_port=port)
    except Exception as exc:
        logger.error("Could not launch CDP Chrome: %s", exc)
        return False

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        await asyncio.sleep(1)
        if is_cdp_chrome_running(cdp_url):
            logger.info("CDP Chrome ready at %s", cdp_url)
            return True

    return False
