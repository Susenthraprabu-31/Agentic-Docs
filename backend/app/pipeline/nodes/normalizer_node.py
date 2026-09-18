"""Node — Normalizer / merge.

Post-processes records and documents collected by parallel leaf nodes:
  - Deduplicates parcel records by APN (assessor wins over tax for same APN)
  - Deduplicates documents by instrument_number or book_page
"""
from __future__ import annotations

import logging

from app.pipeline.base_node import BaseNode, PipelineContext
from app.pipeline.run_normalizer import deduplicate_documents, deduplicate_records

logger = logging.getLogger(__name__)


class NormalizerNode(BaseNode):
    """Merge and deduplicate results from parallel leaf nodes."""

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        run_logger = ctx._run_logger
        if run_logger:
            await run_logger.node_started(self.name)

        before_records = len(ctx.records)
        before_docs = len(ctx.documents)

        ctx.records = deduplicate_records(ctx.records)
        ctx.documents = deduplicate_documents(ctx.documents)

        logger.info(
            "NormalizerNode: records %d→%d, documents %d→%d",
            before_records, len(ctx.records),
            before_docs, len(ctx.documents),
        )

        if run_logger:
            await run_logger.node_completed(
                self.name,
                records_before=before_records,
                records_after=len(ctx.records),
                documents_before=before_docs,
                documents_after=len(ctx.documents),
            )

        return ctx
