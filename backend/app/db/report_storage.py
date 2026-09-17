"""Helpers for persisting report PDF storage metadata in Supabase."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.db.supabase_client import supabase_call

logger = logging.getLogger(__name__)

_STORAGE_COLUMNS_AVAILABLE: Optional[bool] = None


def enrich_report_storage(report: dict[str, Any]) -> dict[str, Any]:
    """Promote storage_path/storage_url from report_json when top-level fields are absent."""
    report_json = report.get("report_json") or {}
    if not isinstance(report_json, dict):
        return report

    storage_path = report.get("storage_path") or report_json.get("storage_path")
    storage_url = report.get("storage_url") or report_json.get("storage_url")
    if storage_path == report.get("storage_path") and storage_url == report.get("storage_url"):
        return report

    return {
        **report,
        "storage_path": storage_path,
        "storage_url": storage_url,
    }


def merge_storage_into_report_json(
    report_json: dict[str, Any] | None,
    storage_path: str,
    storage_url: str,
) -> dict[str, Any]:
    merged = dict(report_json or {})
    merged["storage_path"] = storage_path
    merged["storage_url"] = storage_url
    return merged


def reports_table_has_storage_columns(client: Any) -> bool:
    """Probe once whether the reports table has dedicated storage columns."""
    global _STORAGE_COLUMNS_AVAILABLE
    if _STORAGE_COLUMNS_AVAILABLE is not None:
        return _STORAGE_COLUMNS_AVAILABLE

    try:
        client.table("reports").select("storage_path,storage_url").limit(0).execute()
        _STORAGE_COLUMNS_AVAILABLE = True
    except Exception as exc:
        message = str(exc)
        if "PGRST204" in message or "storage_path" in message:
            _STORAGE_COLUMNS_AVAILABLE = False
            logger.info(
                "reports.storage_path/storage_url columns missing — "
                "persisting storage metadata in report_json instead. "
                "Apply backend/app/db/migrations/002_report_storage.sql in Supabase to add them."
            )
        else:
            logger.warning("Unable to probe reports storage columns: %s", exc)
            _STORAGE_COLUMNS_AVAILABLE = False
    return _STORAGE_COLUMNS_AVAILABLE


def persist_report_storage(
    client: Any,
    *,
    report_id: str,
    storage_path: str,
    storage_url: str,
    report_json: dict[str, Any] | None,
) -> bool:
    """Persist storage metadata, using dedicated columns when available."""
    merged_json = merge_storage_into_report_json(report_json, storage_path, storage_url)
    update_payload: dict[str, Any] = {"report_json": merged_json}

    has_storage_columns = reports_table_has_storage_columns(client)
    if has_storage_columns:
        update_payload["storage_path"] = storage_path
        update_payload["storage_url"] = storage_url

    result = supabase_call(
        lambda: client.table("reports").update(update_payload).eq("id", report_id).execute(),
        label="report_storage_update",
        retries=3 if has_storage_columns else 1,
    )
    return result is not None
