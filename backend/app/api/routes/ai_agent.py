import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.ai_agent_coordinator import complete_pending, fail_pending
from app.agents.openai_agent import OpenAIAgentService
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
    result = await _execute_openai(body.config, body.context_data)
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
        if not body.context_data:
            records = RecordsRepository().list_by_run(run_id)
            documents = DocumentsRepository().list_by_run(run_id)
            body.context_data = {
                "run_id": run_id,
                "state": run.get("state"),
                "county": run.get("county"),
                "query_value": run.get("query_value"),
                "records": records,
                "documents": documents,
            }

        result = await _execute_openai(body.config, body.context_data)
        duration = int((time.monotonic() - t0) * 1000)
        preview = (result.get("content") or "")[:500]

        await logger.node_completed(
            "AIAgentNode",
            agent_name=agent_name,
            model=result.get("model"),
            duration_ms=duration,
            message=preview,
            prompt_tokens=result.get("prompt_tokens"),
            completion_tokens=result.get("completion_tokens"),
        )

        run_row = repo.get_run(run_id) or {}
        plan = run_row.get("plan_json") or {}
        if isinstance(plan, dict):
            repo.update_run(
                run_id,
                plan_json={**plan, "ai_agent_response": result.get("content")},
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
