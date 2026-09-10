import json
import logging
from typing import Any, Literal, Union

from app.config.settings import get_settings
from app.extraction.schemas import ParcelRecord, RecordedDocument

logger = logging.getLogger(__name__)

PARCEL_SCHEMA = {
    "type": "object",
    "properties": {
        "apn": {"type": "string"},
        "owner_name": {"type": "string"},
        "legal_desc": {"type": "string"},
        "assessed_value": {"type": "number"},
        "property_address": {"type": "string"},
    },
    "additionalProperties": True,
}

DOCUMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string"},
        "recording_date": {"type": "string"},
        "book_page": {"type": "string"},
        "instrument_number": {"type": "string"},
        "grantor": {"type": "string"},
        "grantee": {"type": "string"},
    },
    "additionalProperties": True,
}


class ExtractionNormalizer:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None and self.settings.openai_api_key:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=self.settings.openai_api_key)
            except Exception as exc:
                logger.warning("OpenAI client init failed: %s", exc)
        return self._client

    async def normalize(
        self,
        source: Literal["assessor", "recorder"],
        raw_text: str,
        partial: Union[ParcelRecord, RecordedDocument, dict[str, Any], None] = None,
    ) -> Union[ParcelRecord, RecordedDocument]:
        if partial and isinstance(partial, (ParcelRecord, RecordedDocument)):
            if self._is_complete(partial):
                return partial

        client = self._get_client()
        if not client:
            return self._fallback(source, raw_text, partial)

        schema = PARCEL_SCHEMA if source == "assessor" else DOCUMENT_SCHEMA
        prompt = (
            f"Extract structured {source} record fields from this text. "
            f"Return JSON matching the schema.\n\n{raw_text[:8000]}"
        )
        if partial:
            partial_dict = partial.model_dump() if hasattr(partial, "model_dump") else partial
            prompt += f"\n\nPartial data already extracted:\n{json.dumps(partial_dict, default=str)}"

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You extract public records fields into JSON."},
                    {"role": "user", "content": prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": f"{source}_record", "schema": schema},
                },
            )
            content = response.choices[0].message.content or "{}"
            data = json.loads(content)
            if source == "assessor":
                merged_raw: dict[str, Any] = {}
                if isinstance(partial, ParcelRecord) and partial.raw_json:
                    merged_raw.update(partial.raw_json)
                merged_raw.update(data)
                field_values: dict[str, Any] = {"source": "assessor", "raw_json": merged_raw}
                for field in ("apn", "owner_name", "legal_desc", "assessed_value", "property_address"):
                    ai_val = data.get(field)
                    partial_val = getattr(partial, field, None) if isinstance(partial, ParcelRecord) else None
                    field_values[field] = ai_val or partial_val
                return ParcelRecord(**field_values)
            return RecordedDocument(**{k: v for k, v in data.items() if k in RecordedDocument.model_fields}, ocr_json=data)
        except Exception as exc:
            logger.warning("OpenAI normalizer failed, using fallback: %s", exc)
            return self._fallback(source, raw_text, partial)

    def _is_complete(self, record: Union[ParcelRecord, RecordedDocument]) -> bool:
        if isinstance(record, ParcelRecord):
            return bool(record.apn or (record.owner_name and record.property_address))
        return bool(record.document_type or record.instrument_number or record.book_page)

    def _fallback(
        self,
        source: Literal["assessor", "recorder"],
        raw_text: str,
        partial: Any,
    ) -> Union[ParcelRecord, RecordedDocument]:
        if isinstance(partial, ParcelRecord):
            return partial
        if isinstance(partial, RecordedDocument):
            return partial
        if source == "assessor":
            return ParcelRecord(source="assessor", raw_json={"text": raw_text[:2000]})
        return RecordedDocument(ocr_json={"text": raw_text[:2000]})
