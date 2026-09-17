"""Live browser screencast — streams JPEG frames to the UI via WebSocket."""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import TYPE_CHECKING, Optional

from app.agents.run_logger import schedule_broadcast_run_event

if TYPE_CHECKING:
    from playwright.async_api import CDPSession, Page

logger = logging.getLogger(__name__)

MIN_FRAME_INTERVAL_SEC = 0.12  # ~8 fps cap for websocket bandwidth


class BrowserStream:
    """CDP Page.startScreencast with preview-poll fallback."""

    def __init__(self) -> None:
        self._cdp: Optional[CDPSession] = None
        self._run_id: Optional[str] = None
        self._last_frame_ts: float = 0.0
        self._poll_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self, page: Page, run_id: str) -> None:
        self._run_id = run_id
        self._running = True
        try:
            self._cdp = await page.context.new_cdp_session(page)
            self._cdp.on(
                "Page.screencastFrame",
                lambda params: asyncio.create_task(self._on_screencast_frame(params)),
            )
            await self._cdp.send(
                "Page.startScreencast",
                {
                    "format": "jpeg",
                    "quality": 72,
                    "everyNthFrame": 1,
                    "maxWidth": 1280,
                    "maxHeight": 800,
                },
            )
            logger.info("Browser screencast started for run %s", run_id)
        except Exception as exc:
            logger.warning("CDP screencast unavailable, using preview poll: %s", exc)
            self._cdp = None
            self._poll_task = asyncio.create_task(self._preview_poll_loop(page, run_id))

    async def _on_screencast_frame(self, params: dict) -> None:
        if not self._running or not self._run_id:
            return
        session_id = params.get("sessionId")
        data = params.get("data")
        if self._cdp and session_id:
            try:
                await self._cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
            except Exception:
                pass
        if not data:
            return
        now = time.monotonic()
        if now - self._last_frame_ts < MIN_FRAME_INTERVAL_SEC:
            return
        self._last_frame_ts = now
        self._broadcast_frame(self._run_id, data)

    async def _preview_poll_loop(self, page: Page, run_id: str) -> None:
        """Fallback when CDP screencast is not available."""
        while self._running and self._run_id == run_id:
            try:
                if page.is_closed():
                    break
                png_bytes = await page.screenshot(full_page=False, type="jpeg", quality=72)
                b64 = base64.b64encode(png_bytes).decode("ascii")
                self._broadcast_frame(run_id, b64)
            except Exception as exc:
                logger.debug("Preview poll frame failed: %s", exc)
            await asyncio.sleep(0.35)

    @staticmethod
    def _broadcast_frame(run_id: str, frame_b64: str) -> None:
        schedule_broadcast_run_event(
            run_id,
            {
                "event_type": "browser_frame",
                "run_id": run_id,
                "payload": {"frame": frame_b64},
            },
        )

    async def stop(self) -> None:
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self._poll_task = None
        if self._cdp:
            try:
                await self._cdp.send("Page.stopScreencast")
                await self._cdp.detach()
            except Exception:
                pass
        self._cdp = None
        self._run_id = None
