import asyncio
import logging
from typing import Any

from app.agents.orchestrator import Orchestrator
from app.extraction.schemas import QueryType
from app.queue.playwright_runner import run_async_in_playwright_thread
from app.report.report_builder import ReportBuilder

logger = logging.getLogger(__name__)

_running_tasks: dict[str, asyncio.Task[Any]] = {}


async def enqueue_run(
    run_id: str,
    state: str,
    county: str,
    query_type: QueryType,
    query_value: str,
) -> None:
    task = asyncio.create_task(_execute_run(run_id, state, county, query_type, query_value))
    _running_tasks[run_id] = task

    def _on_done(t: asyncio.Task[Any]) -> None:
        _running_tasks.pop(run_id, None)
        if not t.cancelled() and t.exception():
            logger.error("Background run %s failed: %s", run_id, t.exception())

    task.add_done_callback(_on_done)


def _execute_run_in_thread(
    run_id: str,
    state: str,
    county: str,
    query_type: QueryType,
    query_value: str,
) -> None:
    async def _coro() -> None:
        orchestrator = Orchestrator(run_id)
        try:
            await orchestrator.execute(state, county, query_type, query_value)
        finally:
            # Always build a report so /reports/by-run/{id} never 404s
            builder = ReportBuilder()
            await builder.build_and_save(run_id)

    run_async_in_playwright_thread(_coro)


async def _execute_run(
    run_id: str,
    state: str,
    county: str,
    query_type: QueryType,
    query_value: str,
) -> None:
    try:
        await asyncio.to_thread(
            _execute_run_in_thread,
            run_id,
            state,
            county,
            query_type,
            query_value,
        )
    except Exception as exc:
        logger.exception("Background run %s failed: %s", run_id, exc)


def get_task_status(run_id: str) -> str | None:
    task = _running_tasks.get(run_id)
    if task is None:
        return None
    if task.done():
        return "done"
    return "running"
