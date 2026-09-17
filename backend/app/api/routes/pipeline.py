import asyncio
import logging

from fastapi import APIRouter, HTTPException

from app.drivers.instruction_writer_ai import generate_playwright_instructions
from app.extraction.schemas import GenerateInstructionsRequest, GenerateInstructionsResponse
from app.queue.playwright_runner import run_async_in_playwright_thread

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _run_instruction_probe(body: GenerateInstructionsRequest) -> dict:
    async def _coro() -> dict:
        return await generate_playwright_instructions(
            node_id=body.node_id,
            state=body.state,
            county=body.county,
            query_type=body.query_type,
            url=body.url,
            query_value=body.query_value or "",
            playwright_notes=body.playwright_notes,
        )

    return run_async_in_playwright_thread(_coro)


@router.post("/generate-instructions", response_model=GenerateInstructionsResponse)
async def generate_instructions(body: GenerateInstructionsRequest) -> GenerateInstructionsResponse:
    """Probe a county portal page and generate natural-language Playwright instructions."""
    try:
        result = await asyncio.to_thread(_run_instruction_probe, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Instruction generation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return GenerateInstructionsResponse(
        instructions=result["instructions"],
        layout_type=result.get("layout_type", "inline_form"),
        confidence=result.get("confidence", "medium"),
        reasoning=result.get("reasoning", ""),
        resolved_url=result.get("resolved_url", ""),
    )
