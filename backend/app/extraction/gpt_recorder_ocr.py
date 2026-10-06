import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Any, Optional

from app.config.settings import get_settings
from app.extraction.recording_details_parser import parse_recording_details
from app.extraction.schemas import RecordedDocument

logger = logging.getLogger(__name__)

RECORDER_GPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string"},
        "recorded_date": {"type": "string"},
        "executed_date": {"type": "string"},
        "book_page": {"type": "string"},
        "book": {"type": "string"},
        "page": {"type": "string"},
        "instrument_number": {"type": "string"},
        "clerk_file_number": {"type": "string"},
        "grantor": {"type": "string"},
        "grantee": {"type": "string"},
        "grantors": {"type": "array", "items": {"type": "string"}},
        "grantees": {"type": "array", "items": {"type": "string"}},
        "legal_description": {"type": "string"},
        "property_address": {"type": "string"},
        "sale_price": {"type": "string"},
        "consideration": {"type": "string"},
        "documentary_stamps": {"type": "string"},
        "recording_fee": {"type": "string"},
        "deed_doc_fee": {"type": "string"},
        "parcel_id": {"type": "string"},
        "folio_number": {"type": "string"},
        "order_number": {"type": "string"},
        "prepared_by": {"type": "string"},
        "ocr_text": {"type": "string"},
    },
    "additionalProperties": True,
}

RECORDER_GPT_PROMPT = """You are extracting structured recording details from a county recorder document image or PDF.
Read the full document carefully and return JSON matching the schema.

Rules:
- Use exact values visible on the document (dates, book/page, CFN/instrument numbers, parties, legal description, address).
- For Miami-Dade style documents, CFN is the clerk file / instrument number (e.g. 2003 R 823605).
- book_page format should be like 21794/3635 when both are present.
- grantors and grantees may be multiple; include arrays when helpful.
- ocr_text should contain the main body text you read (up to 8000 characters).
- If a field is not present, omit it rather than guessing."""


class GptRecorderOcrService:
    """GPT vision OCR for the recorder document viewer (Mistral remains used in the pipeline)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Any = None
        self._client_error: str | None = None

    def is_enabled(self) -> bool:
        return bool(self.settings.gpt_recorder_ocr_enabled and self.settings.openai_api_key)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.settings.openai_api_key:
            self._client_error = "OpenAI API key not configured"
            return None
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.settings.openai_api_key)
            self._client_error = None
        except Exception as exc:
            self._client_error = f"OpenAI client init failed: {exc}"
            logger.warning(self._client_error)
        return self._client

    def _client_unavailable_message(self) -> str:
        if not self.settings.openai_api_key:
            return "OpenAI API key not configured"
        return self._client_error or "OpenAI client is unavailable"

    async def extract_document(
        self,
        file_path: str,
        document_hint: Optional[str] = None,
    ) -> RecordedDocument:
        if not self.settings.gpt_recorder_ocr_enabled:
            return RecordedDocument(
                document_type=document_hint or "Unknown",
                screenshot_path=file_path,
                ocr_json={
                    "error": "GPT recorder OCR is disabled (set GPT_RECORDER_OCR_ENABLED=true to re-enable)",
                    "gpt_analyzed": False,
                    "ocr_skipped": True,
                },
            )

        client = self._get_client()
        path = Path(file_path)
        if not client:
            return RecordedDocument(
                document_type=document_hint or "Unknown",
                ocr_json={"error": self._client_unavailable_message(), "gpt_analyzed": False},
            )

        if not path.exists():
            return RecordedDocument(ocr_json={"error": f"File not found: {file_path}", "gpt_analyzed": False})

        suffix = path.suffix.lower()
        if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
            return RecordedDocument(
                screenshot_path=file_path,
                ocr_json={"error": f"Unsupported file type: {path.suffix}", "gpt_analyzed": False},
            )

        hint = document_hint or "Recorded Document"
        user_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": f"{RECORDER_GPT_PROMPT}\n\nDocument hint: {hint}",
            }
        ]

        uploaded_file_id: str | None = None
        try:
            if suffix == ".pdf":
                uploaded = await asyncio.to_thread(
                    lambda: client.files.create(file=path.open("rb"), purpose="user_data")
                )
                uploaded_file_id = uploaded.id
                user_content.append({"type": "file", "file": {"file_id": uploaded_file_id}})
            else:
                mime = "image/png" if suffix == ".png" else "image/jpeg"
                data = base64.b64encode(path.read_bytes()).decode("utf-8")
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{data}"},
                    }
                )

            response = await asyncio.to_thread(
                lambda: client.chat.completions.create(
                    model=self.settings.gpt_recorder_ocr_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You extract county recorder document fields into JSON.",
                        },
                        {"role": "user", "content": user_content},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "recorder_document",
                            "schema": RECORDER_GPT_SCHEMA,
                        },
                    },
                    max_tokens=4096,
                )
            )
            content = response.choices[0].message.content or "{}"
            structured = json.loads(content)
            if not isinstance(structured, dict):
                structured = {}

            ocr_text = str(structured.get("ocr_text") or "").strip()
            parsed = parse_recording_details(ocr_text, document_hint=document_hint) if ocr_text else {}
            recording_details = {**parsed, **{k: v for k, v in structured.items() if v and k != "ocr_text"}}
            if ocr_text:
                recording_details["ocr_text"] = ocr_text[:8000]
            recording_details = {k: v for k, v in recording_details.items() if v not in (None, "", [])}

            merged_ocr: dict[str, Any] = {
                "recording_details": recording_details,
                "gpt_analyzed": True,
                "gpt_ocr_model": self.settings.gpt_recorder_ocr_model,
                "ocr_engine": "gpt",
                "ocr_source": suffix.lstrip("."),
            }
            for key in (
                "legal_description",
                "property_address",
                "clerk_file_number",
                "instrument_number",
                "book_page",
                "book",
                "page",
                "recorded_date",
                "executed_date",
                "sale_price",
                "consideration",
                "documentary_stamps",
                "recording_fee",
                "parcel_id",
                "folio_number",
                "order_number",
                "prepared_by",
            ):
                value = recording_details.get(key)
                if value:
                    merged_ocr[key] = value

            grantors = recording_details.get("grantors") or []
            grantees = recording_details.get("grantees") or []
            if grantors:
                merged_ocr["grantors"] = grantors
            if grantees:
                merged_ocr["grantees"] = grantees

            book_page = recording_details.get("book_page")
            if book_page and "/" in str(book_page):
                book, _, page = str(book_page).partition("/")
                merged_ocr.setdefault("book_number", book.strip())
                merged_ocr.setdefault("page_number", page.strip())

            return RecordedDocument(
                document_type=recording_details.get("document_type") or document_hint,
                grantor=recording_details.get("grantor") or (grantors[0] if grantors else None),
                grantee=recording_details.get("grantee") or (grantees[0] if grantees else None),
                book_page=book_page,
                instrument_number=recording_details.get("instrument_number")
                or recording_details.get("clerk_file_number"),
                ocr_json=merged_ocr,
                screenshot_path=file_path,
            )
        except Exception as exc:
            error_message = str(exc)
            logger.error("GPT recorder OCR failed: %s", error_message)
            return RecordedDocument(
                screenshot_path=file_path,
                ocr_json={"error": error_message, "gpt_analyzed": False},
            )
        finally:
            if uploaded_file_id and client:
                try:
                    await asyncio.to_thread(lambda: client.files.delete(uploaded_file_id))
                except Exception:
                    pass
