"""Batch Queue & Concurrency Processor for multi-order workflows."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.agents.orchestrator import Orchestrator
from app.db.repositories.batches_repository import BatchesRepository
from app.db.repositories.runs_repository import RunsRepository
from app.extraction.book_page import format_book_page, parse_book_page
from app.extraction.schemas import QueryType
from app.pipeline.graph_executor import requires_report, resolve_pipeline_graph
from app.pipeline.workflow_templates import get_workflow_graph
from app.queue.playwright_runner import run_async_in_playwright_thread
from app.report.report_builder import ReportBuilder

logger = logging.getLogger(__name__)

# Active background batch tasks
_active_batch_tasks: dict[str, asyncio.Task[Any]] = {}
_cancelled_batches: set[str] = set()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_batch_cancelled(batch_id: str) -> bool:
    return batch_id in _cancelled_batches


def cancel_batch(batch_id: str) -> None:
    _cancelled_batches.add(batch_id)
    task = _active_batch_tasks.get(batch_id)
    if task and not task.done():
        task.cancel()

    repo = BatchesRepository()
    repo.update_batch(batch_id, status="cancelled", completed_at=_now_iso())
    orders = repo.get_orders(batch_id)
    for order in orders:
        if order.get("status") in ("pending", "queued"):
            repo.update_order(order["id"], status="cancelled", error_message="Batch cancelled by user")


async def enqueue_batch(batch_id: str) -> None:
    """Spawn background worker to process batch orders with controlled concurrency."""
    _cancelled_batches.discard(batch_id)

    task = asyncio.create_task(_process_batch(batch_id))
    _active_batch_tasks[batch_id] = task

    def _done_cb(t: asyncio.Task[Any]) -> None:
        _active_batch_tasks.pop(batch_id, None)
        if not t.cancelled() and t.exception():
            logger.error("Batch %s failed with error: %s", batch_id, t.exception())

    task.add_done_callback(_done_cb)


async def _process_batch(batch_id: str) -> None:
    repo = BatchesRepository()
    batch = repo.get_batch(batch_id)
    if not batch:
        logger.error("Batch not found: %s", batch_id)
        return

    repo.update_batch(batch_id, status="running")
    orders = repo.get_orders(batch_id)
    # Playwright uses one shared Chrome profile — run orders one at a time.
    concurrency = 1
    semaphore = asyncio.Semaphore(concurrency)

    async def _process_single_order(order: dict[str, Any]) -> None:
        if is_batch_cancelled(batch_id):
            repo.update_order(order["id"], status="cancelled", error_message="Batch cancelled")
            return

        async with semaphore:
            if is_batch_cancelled(batch_id):
                repo.update_order(order["id"], status="cancelled", error_message="Batch cancelled")
                return

            order_id = order["id"]
            state = str(order.get("state") or "FL").upper()
            county = str(order.get("county") or "miami-dade").lower()
            query_type_str = str(order.get("query_type") or "book_page").lower()
            query_val = str(order.get("query_value") or "")
            book_num = order.get("book_number")
            page_num = order.get("page_number")

            # Parse query_type enum
            try:
                query_type = QueryType(query_type_str)
            except Exception:
                query_type = QueryType.BOOK_PAGE

            if query_type == QueryType.BOOK_PAGE:
                bp = parse_book_page(query_val, book_number=book_num, page_number=page_num)
                if bp:
                    book_num, page_num = bp
                    query_val = format_book_page(book_num, page_num)

            # Resolve pipeline graph for this order
            workflow_id = order.get("workflow_template") or batch.get("workflow_template") or "recorder_deed"
            pipeline_graph = get_workflow_graph(workflow_id, batch.get("custom_graph"))

            try:
                parsed = resolve_pipeline_graph(pipeline_graph)
            except Exception as exc:
                repo.update_order(order_id, status="failed", error_message=f"Pipeline error: {exc}")
                _update_batch_progress(repo, batch_id)
                return

            # Create individual Run record
            runs_repo = RunsRepository()
            run = runs_repo.create_run(
                state=state,
                county=county,
                query_type=query_type.value,
                query_value=query_val,
            )
            run_id = run["id"]

            plan_json = {
                "pipeline_graph": pipeline_graph,
                "steps": parsed.step_node_ids,
                "state": state,
                "county": county,
                "query_type": query_type.value,
                "query_value": query_val,
                "batch_id": batch_id,
                "order_id": order_id,
            }
            if book_num and page_num:
                plan_json["book_number"] = book_num
                plan_json["page_number"] = page_num

            runs_repo.update_run(run_id, plan_json=plan_json)
            repo.update_order(order_id, run_id=run_id, status="running")

            # Execute run in thread with isolated Playwright event loop
            error_msg: str | None = None
            try:
                def _run_worker():
                    async def _coro():
                        orchestrator = Orchestrator(run_id)
                        try:
                            await orchestrator.execute(
                                state,
                                county,
                                query_type,
                                query_val,
                                pipeline_graph=pipeline_graph,
                            )
                        finally:
                            if requires_report(parsed.step_node_ids):
                                builder = ReportBuilder()
                                if not builder.get_report_by_run(run_id):
                                    await builder.build_and_save(run_id)

                    run_async_in_playwright_thread(_coro)

                await asyncio.to_thread(_run_worker)

            except Exception as exc:
                error_msg = str(exc)
                logger.warning("Order %s (run %s) failed: %s", order_id, run_id, exc)

            # Check outcome
            run_after = runs_repo.get_run(run_id) or {}
            run_status = run_after.get("status")
            builder = ReportBuilder()
            report = builder.get_report_by_run(run_id)

            if run_status == "completed" or (report and report.get("id")):
                repo.update_order(
                    order_id,
                    status="completed",
                    report_id=report.get("id") if report else None,
                    completed_at=_now_iso(),
                )
            else:
                repo.update_order(
                    order_id,
                    status="failed",
                    error_message=error_msg or run_after.get("error_message") or "Order processing failed",
                    completed_at=_now_iso(),
                )

            _update_batch_progress(repo, batch_id)
            # Gentle cooldown between items
            await asyncio.sleep(1.5)

    # Launch orders
    pending_orders = [o for o in orders if o.get("status") in ("pending", "queued")]
    tasks = [_process_single_order(o) for o in pending_orders]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # Finalize batch status
    final_orders = repo.get_orders(batch_id)
    completed_count = sum(1 for o in final_orders if o.get("status") == "completed")
    failed_count = sum(1 for o in final_orders if o.get("status") == "failed")
    cancelled_count = sum(1 for o in final_orders if o.get("status") == "cancelled")

    if cancelled_count > 0 and (completed_count + failed_count < len(final_orders)):
        final_status = "cancelled"
    elif failed_count == 0:
        final_status = "completed"
    elif completed_count > 0:
        final_status = "partially_failed"
    else:
        final_status = "failed"

    repo.update_batch(
        batch_id,
        status=final_status,
        completed_orders=completed_count,
        failed_orders=failed_count,
        completed_at=_now_iso(),
    )


def _update_batch_progress(repo: BatchesRepository, batch_id: str) -> None:
    orders = repo.get_orders(batch_id)
    completed = sum(1 for o in orders if o.get("status") == "completed")
    failed = sum(1 for o in orders if o.get("status") == "failed")
    running = sum(1 for o in orders if o.get("status") == "running")
    repo.update_batch(
        batch_id,
        completed_orders=completed,
        failed_orders=failed,
        running_orders=running,
    )
