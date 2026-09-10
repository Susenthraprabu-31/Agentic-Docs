"""Upload generated report PDFs to Supabase Storage."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.config.settings import get_settings
from app.db.supabase_client import get_supabase, supabase_call

logger = logging.getLogger(__name__)


@dataclass
class StorageUploadResult:
    path: str
    url: str


class ReportPdfStorage:
    def upload(self, pdf_path: str | Path, run_id: str) -> Optional[StorageUploadResult]:
        settings = get_settings()
        client = get_supabase()
        if not client:
            logger.info("Supabase not configured — skipping PDF upload to storage")
            return None

        path = Path(pdf_path)
        if not path.is_file():
            logger.warning("PDF file not found for storage upload: %s", pdf_path)
            return None

        bucket = settings.supabase_storage_bucket
        object_path = f"reports/property_report_{run_id}.pdf"
        pdf_bytes = path.read_bytes()

        def _upload() -> StorageUploadResult:
            storage = client.storage.from_(bucket)
            storage.upload(
                object_path,
                pdf_bytes,
                file_options={"content-type": "application/pdf", "upsert": "true"},
            )
            public_url = storage.get_public_url(object_path)
            return StorageUploadResult(path=object_path, url=public_url)

        try:
            result = supabase_call(_upload, label="report_pdf_storage_upload")
            if result:
                logger.info("Uploaded report PDF to Supabase storage: %s", result.path)
            return result
        except Exception as exc:
            logger.warning("Report PDF storage upload failed: %s", exc)
            return None

    def ensure_bucket_exists(self) -> bool:
        """Create the reports bucket if missing (requires service role)."""
        settings = get_settings()
        client = get_supabase()
        if not client:
            return False

        bucket = settings.supabase_storage_bucket

        def _ensure() -> bool:
            buckets = client.storage.list_buckets()
            ids = {b.id for b in buckets}
            if bucket in ids:
                return True
            client.storage.create_bucket(bucket, options={"public": True})
            return True

        return supabase_call(_ensure, label="ensure_storage_bucket") or False
