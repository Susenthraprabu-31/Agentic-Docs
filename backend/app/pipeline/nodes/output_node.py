"""Node — Output / run finalization."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.db.repositories.runs_repository import RunsRepository
from app.extraction.schemas import RunStatus
from app.pipeline.base_node import BaseNode, PipelineContext

logger = logging.getLogger(__name__)


class OutputNode(BaseNode):
    """Finalize the run: persist COMPLETED status and emit summary.

    Input ctx fields:  records, documents, errors, platforms
    Output:            ctx.summary dict with run results
    """

    def __init__(self, runs_repo: RunsRepository | None = None) -> None:
        self._runs_repo = runs_repo or RunsRepository()

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        run_logger = ctx._run_logger
        if run_logger:
            await run_logger.node_started(self.name)

        total_records = len(ctx.records)
        summary: dict[str, Any] = {
            "run_id": ctx.run_id,
            "total_records": total_records,
            "total_documents": len(ctx.documents),
            "assessor_platform": ctx.assessor_platform,
            "recorder_platform": ctx.recorder_platform,
            "tax_platform": ctx.tax_platform,
            "errors": dict(ctx.errors),
        }

        self._runs_repo.update_run(
            ctx.run_id,
            status=RunStatus.COMPLETED.value,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

        if run_logger:
            await run_logger.run_completed(total_records=total_records)
            await run_logger.node_completed(
                self.name,
                total_records=total_records,
                total_documents=len(ctx.documents),
            )

        logger.info(
            "OutputNode: run %s complete — %d records, %d documents, errors=%s",
            ctx.run_id, total_records, len(ctx.documents), ctx.errors,
        )

        ctx.summary = summary
        return ctx
