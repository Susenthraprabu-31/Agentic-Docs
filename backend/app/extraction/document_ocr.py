import base64
import logging
from pathlib import Path
from typing import Any, Optional

from app.config.settings import get_settings
from app.extraction.schemas import RecordedDocument

logger = logging.getLogger(__name__)


class DocumentOcrService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None and self.settings.mistral_api_key:
            try:
                from mistralai import Mistral

                self._client = Mistral(api_key=self.settings.mistral_api_key)
            except Exception as exc:
                logger.warning("Mistral client init failed: %s", exc)
        return self._client

    async def extract_document(
        self,
        image_path: str,
        document_hint: Optional[str] = None,
    ) -> RecordedDocument:
        client = self._get_client()
        if not client:
            return RecordedDocument(
                document_type=document_hint or "Unknown",
                ocr_json={"error": "Mistral API key not configured"},
            )

        path = Path(image_path)
        if not path.exists():
            return RecordedDocument(ocr_json={"error": f"File not found: {image_path}"})

        image_b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        data_uri = f"data:{mime};base64,{image_b64}"

        try:
            response = client.ocr.process(
                model="mistral-ocr-latest",
                document={"type": "image_url", "image_url": data_uri},
                include_image_base64=False,
            )
            ocr_json = response.model_dump() if hasattr(response, "model_dump") else {"raw": str(response)}
            text = self._extract_text(ocr_json)
            return RecordedDocument(
                document_type=document_hint or self._guess_doc_type(text),
                grantor=self._extract_field(text, ["grantor", "from"]),
                grantee=self._extract_field(text, ["grantee", "to"]),
                book_page=self._extract_field(text, ["book", "page"]),
                instrument_number=self._extract_field(text, ["instrument", "document number"]),
                ocr_json=ocr_json,
                screenshot_path=image_path,
            )
        except Exception as exc:
            logger.error("Mistral OCR failed: %s", exc)
            return RecordedDocument(
                screenshot_path=image_path,
                ocr_json={"error": str(exc)},
            )

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
                snippet = text[idx : idx + 80].split("\n")[0]
                if ":" in snippet:
                    return snippet.split(":", 1)[1].strip()
        return None

    def _guess_doc_type(self, text: str) -> Optional[str]:
        types = ["deed", "mortgage", "lien", "release", "easement", "warranty deed"]
        lower = text.lower()
        for t in types:
            if t in lower:
                return t.title()
        return None
