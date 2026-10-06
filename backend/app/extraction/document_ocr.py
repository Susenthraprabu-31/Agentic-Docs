import asyncio
import base64
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config.settings import get_settings
from app.extraction.recording_details_parser import parse_recording_details
from app.extraction.schemas import RecordedDocument

logger = logging.getLogger(__name__)

RATE_LIMIT_PATTERN = re.compile(r"rate limit|rate_limited|status 429|\b429\b", re.I)
_rate_limit_until: float = 0.0


def is_rate_limit_error(message: str | None) -> bool:
    return bool(message and RATE_LIMIT_PATTERN.search(message))


class DocumentOcrService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Any = None
        self._client_error: str | None = None

    def is_enabled(self) -> bool:
        return bool(self.settings.mistral_ocr_enabled and self.settings.mistral_api_key)

    def is_rate_limited(self) -> bool:
        global _rate_limit_until
        return _rate_limit_until > datetime.now(timezone.utc).timestamp()

    def rate_limit_remaining_seconds(self) -> int:
        global _rate_limit_until
        remaining = int(_rate_limit_until - datetime.now(timezone.utc).timestamp())
        return max(0, remaining)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.settings.mistral_api_key:
            self._client_error = "Mistral API key not configured"
            return None
        try:
            try:
                from mistralai.client import Mistral
            except ImportError:
                from mistralai import Mistral

            self._client = Mistral(api_key=self.settings.mistral_api_key)
            self._client_error = None
        except Exception as exc:
            self._client_error = f"Mistral client init failed: {exc}"
            logger.warning(self._client_error)
        return self._client

    def _client_unavailable_message(self) -> str:
        if not self.settings.mistral_api_key:
            return "Mistral API key not configured"
        return self._client_error or "Mistral OCR client is unavailable"

    async def extract_document(
        self,
        file_path: str,
        document_hint: Optional[str] = None,
    ) -> RecordedDocument:
        """Run Mistral OCR on a PDF or image and return structured recording details."""
        if not self.settings.mistral_ocr_enabled:
            return RecordedDocument(
                document_type=document_hint or "Unknown",
                screenshot_path=file_path,
                ocr_json={
                    "error": "Mistral OCR is disabled (set MISTRAL_OCR_ENABLED=true to re-enable)",
                    "mistral_analyzed": False,
                    "ocr_skipped": True,
                },
            )

        if self.is_rate_limited():
            remaining = self.rate_limit_remaining_seconds()
            return RecordedDocument(
                document_type=document_hint or "Unknown",
                screenshot_path=file_path,
                ocr_json={
                    "error": (
                        f"Mistral OCR rate limited — retry after {remaining}s "
                        f"or upgrade your Mistral plan"
                    ),
                    "mistral_analyzed": False,
                    "rate_limited": True,
                    "ocr_skipped": True,
                },
            )

        client = self._get_client()
        path = Path(file_path)
        if not client:
            return RecordedDocument(
                document_type=document_hint or "Unknown",
                ocr_json={"error": self._client_unavailable_message()},
            )

        if not path.exists():
            return RecordedDocument(ocr_json={"error": f"File not found: {file_path}"})

        document_payload = self._build_document_payload(path)
        if not document_payload:
            return RecordedDocument(
                screenshot_path=file_path,
                ocr_json={"error": f"Unsupported file type: {path.suffix}"},
            )

        try:
            response = await self._process_with_retry(client, document_payload)
            ocr_json = response.model_dump() if hasattr(response, "model_dump") else {"raw": str(response)}
            text = self._extract_text(ocr_json)
            recording_details = parse_recording_details(text, document_hint=document_hint)
            recording_details["ocr_text"] = text[:8000] if text else None
            recording_details = {k: v for k, v in recording_details.items() if v}

            merged_ocr = {
                **ocr_json,
                "recording_details": recording_details,
                "mistral_analyzed": True,
                "mistral_ocr_model": self.settings.mistral_ocr_model,
                "ocr_source": path.suffix.lower().lstrip("."),
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
            if book_page and "/" in book_page:
                book, _, page = book_page.partition("/")
                merged_ocr.setdefault("book_number", book.strip())
                merged_ocr.setdefault("page_number", page.strip())

            return RecordedDocument(
                document_type=recording_details.get("document_type")
                or document_hint
                or self._guess_doc_type(text),
                grantor=recording_details.get("grantor")
                or (grantors[0] if grantors else None),
                grantee=recording_details.get("grantee")
                or (grantees[0] if grantees else None),
                book_page=book_page or self._extract_field(text, ["book", "page"]),
                instrument_number=recording_details.get("instrument_number")
                or recording_details.get("clerk_file_number")
                or self._extract_field(text, ["instrument", "document number", "cfn"]),
                ocr_json=merged_ocr,
                screenshot_path=file_path,
            )
        except Exception as exc:
            error_message = str(exc)
            logger.error("Mistral OCR failed: %s", error_message)
            ocr_json: dict[str, Any] = {
                "error": error_message,
                "mistral_analyzed": False,
            }
            if is_rate_limit_error(error_message):
                global _rate_limit_until
                cooldown = max(30.0, self.settings.mistral_ocr_rate_limit_cooldown_seconds)
                _rate_limit_until = datetime.now(timezone.utc).timestamp() + cooldown
                ocr_json["rate_limited"] = True
                ocr_json["rate_limited_at"] = datetime.now(timezone.utc).isoformat()
                ocr_json["ocr_skipped"] = True
                logger.warning(
                    "Mistral OCR rate limited; pausing OCR requests for %.0fs",
                    cooldown,
                )
            return RecordedDocument(
                screenshot_path=file_path,
                ocr_json=ocr_json,
            )

    async def _process_with_retry(self, client: Any, document_payload: dict[str, Any]) -> Any:
        max_retries = max(1, self.settings.mistral_ocr_max_retries)
        base_delay = max(0.5, self.settings.mistral_ocr_retry_base_seconds)
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                return client.ocr.process(
                    model=self.settings.mistral_ocr_model,
                    document=document_payload,
                    include_image_base64=False,
                    extract_header=True,
                    extract_footer=True,
                )
            except Exception as exc:
                last_error = exc
                message = str(exc)
                if not is_rate_limit_error(message) or attempt >= max_retries - 1:
                    raise
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Mistral OCR rate limited; retrying in %.1fs (%s/%s)",
                    delay,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(delay)

        if last_error:
            raise last_error
        raise RuntimeError("Mistral OCR failed without an error")

    def _build_document_payload(self, path: Path) -> Optional[dict[str, Any]]:
        suffix = path.suffix.lower()
        if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
            return None

        data = base64.b64encode(path.read_bytes()).decode("utf-8")
        if suffix == ".pdf":
            return {
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{data}",
            }

        mime = "image/png" if suffix == ".png" else "image/jpeg"
        return {
            "type": "image_url",
            "image_url": f"data:{mime};base64,{data}",
        }

    def _extract_text(self, ocr_json: dict[str, Any]) -> str:
        pages = ocr_json.get("pages", [])
        parts = []
        for page in pages:
            if isinstance(page, dict) and "markdown" in page:
                parts.append(page["markdown"])
        return "\n".join(parts)

    def _extract_field(self, text: str, keywords: list[str]) -> Optional[str]:
        lower = text.lower()
        for kw in keywords:
            idx = lower.find(kw)
            if idx >= 0:
                snippet = text[idx : idx + 120].split("\n")[0]
                if ":" in snippet:
                    return snippet.split(":", 1)[1].strip()
        return None

    def _guess_doc_type(self, text: str) -> Optional[str]:
        types = [
            "corporate warranty deed",
            "warranty deed",
            "quit claim deed",
            "mortgage",
            "lien",
            "release",
            "easement",
            "deed",
        ]
        lower = text.lower()
        for doc_type in types:
            if doc_type in lower:
                return doc_type.title()
        return None
