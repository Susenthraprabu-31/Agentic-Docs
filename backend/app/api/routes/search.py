from fastapi import APIRouter, HTTPException

from app.extraction.schemas import SearchRequest, SearchResponse
from app.queue.job_queue import enqueue_run
from app.db.repositories.runs_repository import RunsRepository

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def create_search(request: SearchRequest) -> SearchResponse:
    repo = RunsRepository()
    run = repo.create_run(
        state=request.state.upper(),
        county=request.county.lower(),
        query_type=request.query_type.value,
        query_value=request.query_value.strip(),
    )
    if not run.get("id"):
        raise HTTPException(status_code=500, detail="Failed to create run")

    await enqueue_run(
        run_id=run["id"],
        state=request.state.upper(),
        county=request.county.lower(),
        query_type=request.query_type,
        query_value=request.query_value.strip(),
    )
    return SearchResponse(run_id=run["id"])
