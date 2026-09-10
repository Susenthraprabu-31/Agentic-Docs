from fastapi import APIRouter, HTTPException

from app.db.repositories.documents_repository import DocumentsRepository
from app.db.repositories.records_repository import RecordsRepository
from app.db.repositories.runs_repository import RunsRepository
from app.extraction.schemas import QueryType, RunDetailResponse, RunEvent, RunRecord, RunStatus, SourceStatus, SourceType

router = APIRouter(prefix="/runs", tags=["runs"])

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
