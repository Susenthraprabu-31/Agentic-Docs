"""Run Playwright async work in a dedicated thread with a Windows-compatible event loop."""

import asyncio
import sys
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="playwright")


def _run_coro_in_new_loop(coro: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
        asyncio.set_event_loop(None)


def run_async_in_playwright_thread(coro_factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """
    Execute async Playwright code in a worker thread with its own event loop.

    Use a coroutine factory (callable) so the coroutine is created inside the
    worker thread's loop, not bound to uvicorn's running loop.
    """

    def _worker() -> T:
        return _run_coro_in_new_loop(coro_factory())

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _worker()

    return _executor.submit(_worker).result()
