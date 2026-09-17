"""Registry of active Playwright drivers keyed by run_id (for Live preview interaction)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.drivers.base.base_driver import BaseDriver

_active: dict[str, "BaseDriver"] = {}


def register_driver(run_id: str, driver: "BaseDriver") -> None:
    _active[run_id] = driver


def unregister_driver(run_id: str) -> None:
    _active.pop(run_id, None)


def get_driver(run_id: str) -> Optional["BaseDriver"]:
    return _active.get(run_id)
