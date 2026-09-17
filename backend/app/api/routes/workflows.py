"""
Workflow CRUD routes — save/load pipeline graphs to/from Supabase and local JSON files.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.db.supabase_client import get_supabase, supabase_call, get_memory_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflows", tags=["workflows"])

WORKFLOWS_DIR = Path("local_storage/workflows").resolve()
WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)


# ── Helpers for local JSON file persistence ───────────────────────────────────

def _save_to_json_file(record: dict[str, Any]) -> None:
    try:
        wf_id = record.get("id")
        if not wf_id:
            return
        file_path = WORKFLOWS_DIR / f"{wf_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        logger.info("Saved workflow JSON file to %s", file_path)
    except Exception as exc:
        logger.warning("Failed to save workflow JSON file: %s", exc)


def _load_from_json_files() -> list[dict[str, Any]]:
    records = []
    try:
        for file_path in WORKFLOWS_DIR.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "id" in data:
                        records.append(data)
            except Exception:
                continue
    except Exception as exc:
        logger.warning("Failed reading workflows directory: %s", exc)
    return records


def _delete_json_file(wf_id: str) -> None:
    try:
        file_path = WORKFLOWS_DIR / f"{wf_id}.json"
        if file_path.exists():
            file_path.unlink()
    except Exception as exc:
        logger.warning("Failed deleting workflow JSON file: %s", exc)


# ── Pydantic schemas ─────────────────────────────────────────────────────────

class WorkflowSaveRequest(BaseModel):
    id: Optional[str] = None  # if set, update existing; else create new
    name: str
    description: str = ""
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    metadata: dict[str, Any] = {}


class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    metadata: dict[str, Any]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=list[WorkflowResponse])
async def list_workflows():
    """Return all saved workflows from Supabase, falling back to local JSON files."""
    supabase = get_supabase()

    if supabase:
        result = supabase_call(
            lambda: supabase.table("workflows")
            .select("*")
            .order("updated_at", desc=True)
            .execute(),
            label="list_workflows",
        )
        if result and result.data:
            # Sync to local JSON files as well
            for row in result.data:
                _save_to_json_file(row)
            return result.data

    # Fallback to local JSON files on disk
    local_records = _load_from_json_files()
    if local_records:
        return sorted(local_records, key=lambda w: w.get("updated_at", ""), reverse=True)

    # Memory fallback
    store = get_memory_store()
    workflows = getattr(store, "workflows", {})
    return sorted(workflows.values(), key=lambda w: w.get("updated_at", ""), reverse=True)


@router.post("", response_model=WorkflowResponse)
async def save_workflow(body: WorkflowSaveRequest):
    """Create or update a workflow in Supabase and local JSON storage."""
    supabase = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    wf_id = body.id or str(uuid4())

    payload = {
        "name": body.name,
        "description": body.description,
        "nodes": body.nodes,
        "edges": body.edges,
        "metadata": body.metadata,
    }

    saved_record: Optional[dict[str, Any]] = None

    if supabase:
        try:
            if body.id:
                # Update existing
                result = supabase_call(
                    lambda: supabase.table("workflows")
                    .update(payload)
                    .eq("id", body.id)
                    .select()
                    .execute(),
                    label="update_workflow",
                )
            else:
                # Insert new
                result = supabase_call(
                    lambda: supabase.table("workflows")
                    .insert(payload)
                    .select()
                    .execute(),
                    label="create_workflow",
                )

            if result and result.data:
                saved_record = result.data[0]
        except Exception as exc:
            logger.warning("Supabase save error, using fallback: %s", exc)

    if not saved_record:
        # Fallback / local record
        store = get_memory_store()
        if not hasattr(store, "workflows"):
            store.workflows = {}  # type: ignore[attr-defined]

        created_at = store.workflows.get(wf_id, {}).get("created_at", now)  # type: ignore[attr-defined]
        saved_record = {
            "id": wf_id,
            **payload,
            "created_at": created_at,
            "updated_at": now,
        }
        store.workflows[wf_id] = saved_record  # type: ignore[attr-defined]

    # Save to local JSON file
    _save_to_json_file(saved_record)

    return saved_record


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: str):
    """Fetch a single workflow by ID."""
    supabase = get_supabase()

    if supabase:
        result = supabase_call(
            lambda: supabase.table("workflows")
            .select("*")
            .eq("id", workflow_id)
            .single()
            .execute(),
            label="get_workflow",
        )
        if result and result.data:
            _save_to_json_file(result.data)
            return result.data

    # Check local JSON file
    file_path = WORKFLOWS_DIR / f"{workflow_id}.json"
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    store = get_memory_store()
    workflows = getattr(store, "workflows", {})
    if workflow_id in workflows:
        return workflows[workflow_id]

    raise HTTPException(status_code=404, detail="Workflow not found")


@router.get("/{workflow_id}/export")
async def export_workflow(workflow_id: str):
    """Download workflow as a JSON file."""
    wf = await get_workflow(workflow_id)
    safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in wf.get("name", "workflow")).strip("_")
    content = json.dumps(wf, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.json"'},
    )


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(workflow_id: str):
    """Delete a workflow."""
    supabase = get_supabase()

    if supabase:
        supabase_call(
            lambda: supabase.table("workflows")
            .delete()
            .eq("id", workflow_id)
            .execute(),
            label="delete_workflow",
        )

    _delete_json_file(workflow_id)

    store = get_memory_store()
    workflows = getattr(store, "workflows", {})
    workflows.pop(workflow_id, None)
