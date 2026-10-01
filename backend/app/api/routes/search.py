from fastapi import APIRouter, HTTPException

from app.extraction.book_page import format_book_page, parse_book_page
from app.extraction.schemas import QueryType, SearchRequest, SearchResponse
from app.pipeline.graph_executor import GraphValidationError, get_input_node_data, resolve_pipeline_graph
from app.queue.job_queue import enqueue_run
from app.db.repositories.runs_repository import RunsRepository

router = APIRouter(prefix="/search", tags=["search"])


def _resolve_search_value(request: SearchRequest) -> tuple[str, str | None, str | None]:
    query_value = (request.query_value or "").strip()
    book = request.book_number
    page = request.page_number

    if request.query_type == QueryType.BOOK_PAGE:
        parsed = parse_book_page(
            query_value,
            book_number=book,
            page_number=page,
        )
        if parsed:
            book, page = parsed
            return format_book_page(book, page), book, page
        return query_value, book, page

    return query_value, None, None


@router.post("", response_model=SearchResponse)
async def create_search(request: SearchRequest) -> SearchResponse:
    if not request.pipeline_graph:
        raise HTTPException(status_code=400, detail="pipeline_graph is required")

    try:
        parsed = resolve_pipeline_graph(request.pipeline_graph.model_dump())
    except GraphValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    query_value, book_number, page_number = _resolve_search_value(request)

    repo = RunsRepository()
    run = repo.create_run(
        state=request.state.upper(),
        county=request.county.lower(),
        query_type=request.query_type.value,
        query_value=query_value,
    )
    if not run.get("id"):
        raise HTTPException(status_code=500, detail="Failed to create run")

    pipeline_graph = request.pipeline_graph.model_dump()
    plan_json = {
        "pipeline_graph": pipeline_graph,
        "steps": parsed.step_node_ids,
        "state": request.state.upper(),
        "county": request.county.lower(),
        "query_type": request.query_type.value,
        "query_value": query_value,
    }
    if book_number and page_number:
        plan_json["book_number"] = book_number
        plan_json["page_number"] = page_number
    if request.address:
        plan_json["address"] = request.address
    if request.owner_name:
        plan_json["owner_name"] = request.owner_name
    if request.parcel_number:
        plan_json["parcel_number"] = request.parcel_number

    input_data = get_input_node_data(pipeline_graph)
    raw_scope = str(input_data.get("searchScope") or input_data.get("search_scope") or "full").strip().lower()
    plan_json["search_scope"] = raw_scope if raw_scope in ("current", "full") else "full"
    raw_limit = input_data.get("searchLimit", input_data.get("search_limit"))
    if raw_limit is not None:
        try:
            limit_val = int(raw_limit)
            if limit_val > 0:
                plan_json["search_limit"] = limit_val
        except (TypeError, ValueError):
            pass

    repo.update_run(run["id"], plan_json=plan_json)

    await enqueue_run(
        run_id=run["id"],
        state=request.state.upper(),
        county=request.county.lower(),
        query_type=request.query_type,
        query_value=query_value,
        pipeline_graph=pipeline_graph,
    )
    return SearchResponse(run_id=run["id"])
