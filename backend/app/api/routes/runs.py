from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.db.repositories.documents_repository import DocumentsRepository
from app.db.repositories.records_repository import RecordsRepository
from app.db.repositories.runs_repository import RunsRepository
from app.drivers.browser_registry import get_driver
from app.extraction.schemas import QueryType, RunDetailResponse, RunEvent, RunRecord, RunStatus, SourceStatus, SourceType
from app.queue.job_queue import cancel_run, is_run_active

router = APIRouter(prefix="/runs", tags=["runs"])

BACKEND_ROOT = Path(__file__).resolve().parents[3]
SCREENSHOTS_DIR = BACKEND_ROOT / "screenshots"

SOURCE_ORDER = [
    SourceType.NETRONLINE,
    SourceType.ASSESSOR,
    SourceType.TAX_RECORD,
    SourceType.GIS,
    SourceType.RECORDER,
]


def _build_sources_panel(events: list[dict]) -> list[dict]:
    status_map: dict[str, dict] = {
        s.value: {"source": s.value, "status": SourceStatus.PENDING.value, "records_found": 0, "message": None}
        for s in SOURCE_ORDER
    }
    for e in events:
        src = e.get("source")
        if not src or src not in status_map:
            continue
        et = e.get("event_type", "")
        payload = e.get("payload") or {}
        if et == "source_started":
            status_map[src]["status"] = SourceStatus.IN_PROGRESS.value
            status_map[src]["message"] = payload.get("message")
        elif et == "source_completed":
            status_map[src]["status"] = SourceStatus.DONE.value
            status_map[src]["records_found"] = payload.get("records_found", 0)
            status_map[src]["message"] = payload.get("message")
        elif et == "source_skipped":
            status_map[src]["status"] = SourceStatus.SKIPPED.value
            status_map[src]["message"] = payload.get("reason") or payload.get("message")
        elif et == "source_failed":
            status_map[src]["status"] = SourceStatus.FAILED.value
            status_map[src]["message"] = payload.get("reason") or payload.get("message")
    return [status_map[s.value] for s in SOURCE_ORDER]


@router.get("/{run_id}/preview.png")
async def get_run_preview(run_id: str) -> FileResponse:
    """Latest Playwright viewport screenshot for the in-app browser panel."""
    path = SCREENSHOTS_DIR / f"preview_{run_id}.png"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Preview not available yet")
    return FileResponse(path, media_type="image/png")


class PreviewClickRequest(BaseModel):
    x: float = Field(ge=0, le=1, description="Normalized horizontal click position")
    y: float = Field(ge=0, le=1, description="Normalized vertical click position")


@router.post("/{run_id}/preview-click")
async def preview_click(run_id: str, body: PreviewClickRequest) -> dict:
    """Forward a click from the Live preview panel to the headless Playwright page."""
    driver = get_driver(run_id)
    if not driver:
        raise HTTPException(status_code=404, detail="No active browser for this run")
    try:
        await driver.click_at_normalized(body.x, body.y)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/{run_id}/cancel")
async def cancel_run_job(run_id: str) -> dict:
    """Stop a running pipeline cooperatively."""
    repo = RunsRepository()
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    status = run.get("status")
    if status in (RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value):
        return {"ok": True, "run_id": run_id, "status": status, "already_finished": True}

    cancel_run(run_id)
    if not is_run_active(run_id):
        repo.update_run(
            run_id,
            status=RunStatus.CANCELLED.value,
            error_message="Pipeline stopped by user",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
    return {"ok": True, "run_id": run_id, "status": RunStatus.CANCELLED.value}


@router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run(run_id: str) -> RunDetailResponse:
    repo = RunsRepository()
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    events_raw = repo.get_events(run_id)
    events = [RunEvent(**e) for e in events_raw]
    records = RecordsRepository().list_by_run(run_id)
    documents = DocumentsRepository().list_by_run(run_id)

    return RunDetailResponse(
        run=RunRecord(
            id=run["id"],
            state=run["state"],
            county=run["county"],
            query_type=QueryType(run["query_type"]),
            query_value=run["query_value"],
            status=RunStatus(run["status"]),
            plan_json=run.get("plan_json"),
            error_message=run.get("error_message"),
            started_at=run.get("started_at"),
            completed_at=run.get("completed_at"),
            created_at=run.get("created_at"),
        ),
        events=events,
        records_count=len(records),
        documents_count=len(documents),
        records=records,
        documents=documents,
        sources=_build_sources_panel(events_raw),
    )
