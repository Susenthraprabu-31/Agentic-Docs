"""Cross-thread coordinator: orchestrator waits, browser HTTP POST completes."""
from __future__ import annotations

import asyncio
import time
from typing import Any

_pending: dict[str, dict[str, Any]] = {}


def _key(run_id: str, canvas_id: str) -> str:
    return f"{run_id}:{canvas_id}"


def register_pending(run_id: str, canvas_id: str) -> None:
    _pending[_key(run_id, canvas_id)] = {"status": "pending"}


def complete_pending(run_id: str, canvas_id: str, result: dict[str, Any]) -> bool:
    key = _key(run_id, canvas_id)
    entry = _pending.get(key)
    if not entry or entry.get("status") != "pending":
        return False
    _pending[key] = {"status": "done", "result": result}
    return True


def fail_pending(run_id: str, canvas_id: str, error: str) -> bool:
    key = _key(run_id, canvas_id)
    entry = _pending.get(key)
    if not entry or entry.get("status") != "pending":
        return False
    _pending[key] = {"status": "error", "error": error}
    return True


async def wait_for_pending(run_id: str, canvas_id: str, timeout: float = 180.0) -> dict[str, Any]:
    register_pending(run_id, canvas_id)
    key = _key(run_id, canvas_id)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            entry = _pending.get(key)
            if entry:
                if entry.get("status") == "done":
                    return entry["result"]
                if entry.get("status") == "error":
                    raise ValueError(entry.get("error") or "AI agent request failed")
            await asyncio.sleep(0.25)
        raise TimeoutError("Timed out waiting for AI agent HTTP request from browser")
    finally:
        _pending.pop(key, None)
