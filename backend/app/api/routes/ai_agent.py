import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.ai_agent_coordinator import complete_pending, fail_pending
from app.agents.llm_client import llm_configured, llm_not_configured_message
from app.agents.run_logger import RunLogger
from app.config.settings import get_settings
from app.db.repositories.documents_repository import DocumentsRepository
from app.db.repositories.records_repository import RecordsRepository
from app.db.repositories.runs_repository import RunsRepository

router = APIRouter(tags=["ai-agent"])


class AIAgentConfig(BaseModel):
    agent_name: Optional[str] = "OpenAI Agent"
    instructions: Optional[str] = "You are a helpful AI assistant."
    user_prompt: Optional[str] = ""
    model: Optional[str] = "gpt-4o"
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1000


class AIAgentExecuteRequest(BaseModel):
    canvas_id: str
    config: AIAgentConfig = Field(default_factory=AIAgentConfig)
    context_data: dict[str, Any] = Field(default_factory=dict)


class AIAgentTestRequest(BaseModel):
    config: AIAgentConfig = Field(default_factory=AIAgentConfig)
    context_data: dict[str, Any] = Field(default_factory=dict)


async def _execute_openai(
    config: AIAgentConfig,
    context_data: dict[str, Any],
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not set in backend .env. Add the key and restart the server.",
        )
    service = OpenAIAgentService()
    return await service.run(
        instructions=config.instructions or "You are a helpful AI assistant.",
        user_prompt=config.user_prompt or "",
        model=config.model or "gpt-4o",
        temperature=float(config.temperature or 0.7),
        max_tokens=int(config.max_tokens or 1000),
        context_data=context_data,
    )


@router.post("/ai-agent/test")
async def test_ai_agent(body: AIAgentTestRequest) -> dict[str, Any]:
    """Standalone test — visible in browser Network tab."""
    t0 = time.monotonic()
    context = dict(body.context_data or {})
    prev_node = str(context.get("previous_node") or "previous").lower().strip()

    sample_property = {
        "apn": "30-4009-094-0050",
        "address": "9441 SW 21 ST",
        "owner": "John Smith",
        "legal_description": "SUB NO 2 LOT 5 BLK 4",
    }
    sample_report = {
        "status": "sample_data",
        "report_id": "test-sample-report",
        "property": sample_property,
        "tax_record": {"status": "Paid", "gross_tax": 4520.18, "delinquent": False},
        "chain_of_title": [
            {"document_type": "Warranty Deed", "recording_date": "2021-04-15", "grantor": "Alice Baker", "grantee": "John Smith"}
        ],
        "documents_count": 3,
    }
    sample_assessor = {
        "records_found": 1,
        "parcel": "30-4009-094-0050",
        "owner_name": "John Smith",
        "address": "9441 SW 21 ST",
        "property": sample_property,
    }
    sample_recorder = {
        "documents_found": 3,
        "documents": sample_report["chain_of_title"],
        "book_number": "1494",
        "page_number": "2483",
    }
    sample_tax = {
        "records_found": 1,
        "records": [sample_report["tax_record"]],
        "parcel": "30-4009-094-0050",
    }
    sample_gis = {
        "parcel": "30-4009-094-0050",
        "gis_url": "https://gisweb.miamidade.gov/propertysearch/",
    }
    sample_normalizer = {
        "stats": {"records_before": 3, "records_after": 3, "documents_before": 3, "documents_after": 3},
        "detail": "Records normalized (deduplicated 0)",
    }
    sample_input = {
        "state": "FL",
        "county": "miami-dade",
        "query_type": "address",
        "query_value": "9441 SW 21 ST",
        "address": "9441 SW 21 ST",
        "parcel": "30-4009-094-0050",
    }

    node_samples = {
        "assessor": sample_assessor,
        "recorder": sample_recorder,
        "tax": sample_tax,
        "gis": sample_gis,
        "report": sample_report,
        "normalizer": sample_normalizer,
        "input": sample_input,
    }

    if "previous_result" not in context:
        chosen_prev = node_samples.get(prev_node, sample_report)
        context["previous_result"] = chosen_prev
        context.setdefault("report", sample_report)

    # Populate node_results with all sample nodes so tokens like {{workflow.assessor}}, {{workflow.tax}}, etc. work during tests
    node_results = dict(context.get("node_results") or {})
    for k, v in node_samples.items():
        node_results.setdefault(k, v)
    context["node_results"] = node_results

    result = await _execute_openai(body.config, context)
    return {
        **result,
        "duration_ms": int((time.monotonic() - t0) * 1000),
        "endpoint": "POST /ai-agent/test",
    }


@router.post("/runs/{run_id}/ai-agent/execute")
async def execute_run_ai_agent(run_id: str, body: AIAgentExecuteRequest) -> dict[str, Any]:
    """Pipeline AI node — browser triggers OpenAI via this HTTP call (Network tab)."""
    repo = RunsRepository()
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    logger = RunLogger(run_id)
    agent_name = body.config.agent_name or "OpenAI Agent"
    t0 = time.monotonic()

    try:
        run_row = repo.get_run(run_id) or {}
        plan = run_row.get("plan_json") or {}
        node_results = plan.get("node_results") if isinstance(plan, dict) else {}
        node_results = dict(node_results or {})

        # If already completed by the backend orchestrator directly, return cached result
        if isinstance(plan, dict) and plan.get("ai_agent_response"):
            cached = node_results.get(body.canvas_id) or node_results.get("ai_agent")
            if cached and isinstance(cached, dict):
                return {
                    **cached,
                    "endpoint": f"POST /runs/{run_id}/ai-agent/execute (cached)",
                }

        if not body.context_data:
            records = RecordsRepository().list_by_run(run_id)
            documents = DocumentsRepository().list_by_run(run_id)
            report_result = node_results.get("report")
            if not report_result:
                from app.report.report_builder import ReportBuilder
                rep = ReportBuilder().get_report_by_run(run_id)
                if rep:
                    report_result = {
                        "report_id": rep.get("id"),
                        "pdf_url": f"/reports/run/{run_id}",
                        "property": (rep.get("report_json") or {}).get("property") or {},
                        "tax_record": (rep.get("report_json") or {}).get("tax_record") or {},
                        "chain_of_title": (rep.get("report_json") or {}).get("chain_of_title") or [],
                        "documents_count": len((rep.get("report_json") or {}).get("documents") or []),
                    }
                    node_results["report"] = report_result

            body.context_data = {
                "run_id": run_id,
                "state": run.get("state"),
                "county": run.get("county"),
                "query_value": run.get("query_value"),
                "records": records,
                "documents": documents,
                "report": report_result,
                "previous_result": report_result or (list(node_results.values())[-1] if node_results else None),
                "node_results": node_results,
            }
        else:
            # Ensure report and node_results are present if available in plan
            if "node_results" not in body.context_data and node_results:
                body.context_data["node_results"] = node_results
            if "report" not in body.context_data and "report" in node_results:
                body.context_data["report"] = node_results["report"]
            if "previous_result" not in body.context_data and "report" in node_results:
                body.context_data["previous_result"] = node_results["report"]

        result = await _execute_openai(body.config, body.context_data)
        duration = int((time.monotonic() - t0) * 1000)
        preview = (result.get("content") or "")[:500]

        ai_result_payload = {
            **result,
            "agent_name": agent_name,
            "duration_ms": duration,
        }

        await logger.node_completed(
            "AIAgentNode",
            agent_name=agent_name,
            model=result.get("model"),
            duration_ms=duration,
            detail=preview,
            prompt_tokens=result.get("prompt_tokens"),
            completion_tokens=result.get("completion_tokens"),
            result=ai_result_payload,
        )

        if isinstance(plan, dict):
            updated_results = {**node_results, "ai_agent": ai_result_payload}
            if body.canvas_id:
                updated_results[body.canvas_id] = ai_result_payload
            repo.update_run(
                run_id,
                plan_json={
                    **plan,
                    "ai_agent_response": result.get("content"),
                    "node_results": updated_results,
                },
            )

        if not complete_pending(run_id, body.canvas_id, result):
            # Still return result for direct Test calls / late responses
            pass

        return {
            **result,
            "duration_ms": duration,
            "endpoint": f"POST /runs/{run_id}/ai-agent/execute",
        }
    except HTTPException:
        fail_pending(run_id, body.canvas_id, "OpenAI API key not configured")
        await logger.node_failed("AIAgentNode", "OPENAI_API_KEY not configured in backend .env")
        raise
    except Exception as exc:
        fail_pending(run_id, body.canvas_id, str(exc))
        await logger.node_failed("AIAgentNode", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
