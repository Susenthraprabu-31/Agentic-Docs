"""Node — Normalizer / merge.

Post-processes records and documents collected by parallel leaf nodes:
  - Deduplicates parcel records by APN (assessor wins over tax for same APN)
  - Deduplicates documents by instrument_number or book_page
"""
from __future__ import annotations

import logging

from app.pipeline.base_node import BaseNode, PipelineContext

logger = logging.getLogger(__name__)

_SOURCE_PRIORITY = {"assessor": 0, "tax_record": 1}


def _record_key(rec: dict) -> str | None:
    apn = rec.get("apn")
    if apn:
        return str(apn).strip().upper()
    source = rec.get("source") or "unknown"
    return f"__no_apn__:{source}:{id(rec)}"


def _document_key(doc: dict) -> str:
    instrument = doc.get("instrument_number")
    if instrument:
        return f"inst:{str(instrument).strip().upper()}"
    book_page = doc.get("book_page")
    if book_page:
        return f"bp:{str(book_page).strip().upper()}"
    return f"__doc__:{id(doc)}"


def deduplicate_records(records: list[dict]) -> list[dict]:
    """Keep one record per APN; prefer assessor over tax_record."""
    by_key: dict[str, dict] = {}
    for rec in records:
        key = _record_key(rec)
        if key is None:
            continue
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = rec
            continue
        existing_prio = _SOURCE_PRIORITY.get(existing.get("source", ""), 99)
        new_prio = _SOURCE_PRIORITY.get(rec.get("source", ""), 99)
        if new_prio < existing_prio:
            by_key[key] = rec
    return list(by_key.values())


def deduplicate_documents(documents: list[dict]) -> list[dict]:
    """Keep one document per instrument_number or book_page."""
    by_key: dict[str, dict] = {}
    for doc in documents:
        by_key[_document_key(doc)] = doc
    return list(by_key.values())


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
