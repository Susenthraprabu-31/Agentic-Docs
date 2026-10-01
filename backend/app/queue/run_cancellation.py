"""Cooperative cancellation for in-flight pipeline runs."""

from __future__ import annotations

_cancelled_runs: set[str] = set()


class RunCancelledError(Exception):
    """Raised when the user stops a pipeline run."""


def is_run_cancelled(run_id: str) -> bool:
    return run_id in _cancelled_runs


def mark_run_cancelled(run_id: str) -> None:
    _cancelled_runs.add(run_id)


def clear_run_cancelled(run_id: str) -> None:
    _cancelled_runs.discard(run_id)


def check_run_cancelled(run_id: str | None) -> None:
    if run_id and is_run_cancelled(run_id):
        raise RunCancelledError("Pipeline stopped by user")
