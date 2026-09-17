"""Node 0 — Input validation and context seeding."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db.repositories.runs_repository import RunsRepository
from app.extraction.schemas import QueryType, RunStatus
from app.pipeline.base_node import BaseNode, PipelineContext

logger = logging.getLogger(__name__)

_VALID_QUERY_TYPES = {qt.value for qt in QueryType}


class InputNode(BaseNode):
    """Validate and normalize search inputs; mark the run as started.

    Input:  raw state, county, query_type, query_value on PipelineContext
    Output: normalized fields on ctx; run status RUNNING in DB
    """

    def __init__(self, runs_repo: RunsRepository | None = None) -> None:
        self._runs_repo = runs_repo or RunsRepository()

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        run_logger = ctx._run_logger
        if run_logger:
            await run_logger.node_started(self.name)

        try:
            ctx.state = ctx.state.strip().upper()
            if len(ctx.state) != 2:
                raise ValueError(f"Invalid state code: {ctx.state!r}")

            ctx.county = ctx.county.strip().lower().replace(" ", "-").replace("_", "-")
            if not ctx.county:
                raise ValueError("County is required")

            ctx.query_type = ctx.query_type.strip().lower()
            if ctx.query_type not in _VALID_QUERY_TYPES:
                raise ValueError(
                    f"Invalid query_type: {ctx.query_type!r} "
                    f"(expected one of {sorted(_VALID_QUERY_TYPES)})"
                )

            ctx.query_value = ctx.query_value.strip()
            if not ctx.query_value:
                raise ValueError("query_value cannot be empty")

            self._runs_repo.update_run(
                ctx.run_id,
                status=RunStatus.RUNNING.value,
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            self._runs_repo.update_run(
                ctx.run_id,
                plan_json={
                    "steps": [
                        "input",
                        "netr_resolver",
                        "platform_detector",
                        "assessor + recorder (parallel)",
                        "gis + tax (parallel)",
                        "normalizer",
                        "report_generator",
                        "output",
                    ],
                    "state": ctx.state,
                    "county": ctx.county,
                    "query_type": ctx.query_type,
                    "query_value": ctx.query_value,
                },
            )

            logger.info(
                "InputNode: run=%s state=%s county=%s query=%s/%s",
                ctx.run_id, ctx.state, ctx.county, ctx.query_type, ctx.query_value,
            )

            if run_logger:
                await run_logger.node_completed(
                    self.name,
                    state=ctx.state,
                    county=ctx.county,
                    query_type=ctx.query_type,
                )
        except Exception as exc:
            if run_logger:
                await run_logger.node_failed(self.name, str(exc))
            raise

        return ctx
