import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.db.repositories.runs_repository import RunsRepository
from app.extraction.schemas import SourceType

logger = logging.getLogger(__name__)

_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


class RunLogger:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.repo = RunsRepository()
        self._subscribers: list[Callable[[dict[str, Any]], Any]] = []

    def subscribe(self, callback: Callable[[dict[str, Any]], Any]) -> None:
        self._subscribers.append(callback)

    async def _notify(self, event: dict[str, Any]) -> None:
        for cb in self._subscribers:
            result = cb(event)
            if asyncio.iscoroutine(result):
                await result

        schedule_broadcast_run_event(self.run_id, event)

    async def log(
        self,
        event_type: str,
        source: Optional[SourceType | str] = None,
        message: Optional[str] = None,
        records_found: int = 0,
        **extra: Any,
    ) -> dict[str, Any]:
        source_val = source.value if isinstance(source, SourceType) else source
        payload: dict[str, Any] = {
            "message": message,
            "records_found": records_found,
            **extra,
        }
        try:
            event = self.repo.add_event(self.run_id, event_type, source_val, payload)
        except Exception as exc:
            logger.warning("Failed to persist run event, using in-memory fallback: %s", exc)
            event = {
                "id": str(uuid.uuid4()),
                "run_id": self.run_id,
                "event_type": event_type,
                "source": source_val,
                "payload": payload,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        await self._notify(event)
        return event

    async def source_started(self, source: SourceType, url: Optional[str] = None) -> None:
        await self.log("source_started", source=source, message=f"Searching {source.value}...", url=url)

    async def source_completed(
        self,
        source: SourceType,
        records_found: int = 0,
        duration_ms: Optional[int] = None,
        **extra: Any,
    ) -> None:
        await self.log(
            "source_completed",
            source=source,
            message=f"{source.value} complete — {records_found} record(s) found",
            records_found=records_found,
            duration_ms=duration_ms,
            **extra,
        )

    async def source_skipped(self, source: SourceType, reason: str) -> None:
        await self.log("source_skipped", source=source, message=reason, reason=reason)

    async def source_failed(self, source: SourceType, error: str) -> None:
        await self.log("source_failed", source=source, message=error, reason=error)

    async def record_found(self, source: SourceType, **fields: Any) -> None:
        await self.log("record_found", source=source, records_found=1, **fields)

    async def run_completed(self, report_id: Optional[str] = None, total_records: int = 0) -> None:
        await self.log(
            "run_completed",
            message="Research run complete",
            report_id=report_id,
            total_records=total_records,
        )


# Global pub/sub for WebSocket connections keyed by run_id
_run_subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}


def subscribe_run(run_id: str) -> asyncio.Queue[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _run_subscribers.setdefault(run_id, []).append(queue)
    return queue


def unsubscribe_run(run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
    subs = _run_subscribers.get(run_id, [])
    if queue in subs:
        subs.remove(queue)


async def broadcast_run_event(run_id: str, event: dict[str, Any]) -> None:
    for queue in _run_subscribers.get(run_id, []):
        await queue.put(event)


def schedule_broadcast_run_event(run_id: str, event: dict[str, Any]) -> None:
    """Thread-safe: push run events to WebSocket clients on the main uvicorn loop."""
    if _main_loop and _main_loop.is_running():
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is not _main_loop:
            asyncio.run_coroutine_threadsafe(broadcast_run_event(run_id, event), _main_loop)
            return

    if _main_loop and _main_loop.is_running():
        _main_loop.create_task(broadcast_run_event(run_id, event))
