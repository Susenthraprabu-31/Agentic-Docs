import logging
import time
from functools import lru_cache
from typing import Any, Callable, Optional, TypeVar

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

try:
    from supabase import Client, create_client
except ImportError:
    Client = Any  # type: ignore[misc, assignment]
    create_client = None  # type: ignore[assignment]

T = TypeVar("T")


class InMemoryStore:
    """Fallback when Supabase is not configured or transient network errors occur."""

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.run_events: list[dict[str, Any]] = []
        self.records: list[dict[str, Any]] = []
        self.documents: list[dict[str, Any]] = []
        self.reports: dict[str, dict[str, Any]] = {}


_memory = InMemoryStore()


def get_memory_store() -> InMemoryStore:
    return _memory


def supabase_call(operation: Callable[[], T], *, label: str = "supabase", retries: int = 3) -> Optional[T]:
    """Run a Supabase operation with retries — returns None on persistent failure."""
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            logger.warning("%s attempt %d/%d failed: %s", label, attempt, retries, exc)
            if attempt < retries:
                time.sleep(0.4 * attempt)
    logger.error("%s failed after %d attempts: %s", label, retries, last_error)
    return None


@lru_cache
def get_supabase() -> Optional["Client"]:
    settings = get_settings()
    if not settings.supabase_configured or create_client is None:
        return None
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
