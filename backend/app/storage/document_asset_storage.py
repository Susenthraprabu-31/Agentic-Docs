"""Upload recorder/assessor document files to Supabase Storage."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from app.config.settings import get_settings
from app.db.supabase_client import get_supabase, supabase_call
from app.storage.report_pdf_storage import StorageUploadResult

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class DocumentAssetStorage:
    def upload_and_merge(
        self,
        run_id: str,
        ocr_json: dict[str, Any],
        screenshot_path: str | None = None,
    ) -> dict[str, Any]:
        """Upload local document assets to Supabase and return merged OCR metadata."""
        merged = dict(ocr_json or {})
        category = merged.get("storage_category") or merged.get("source") or "documents"
        if category in ("assessor_sales", "ai_agent", "chatbot", "gis"):
            return merged

        folder_name = str(merged.get("folder_name") or "").strip()
        pdf_path = self._resolve_local_file(
            merged.get("download_path"),
            screenshot_path,
            merged.get("pdf_path"),
            folder_name or None,
            merged.get("pdf_file"),
        )
        if pdf_path and "local_storage" in pdf_path.as_posix().replace("\\", "/"):
            derived_folder = pdf_path.parent.relative_to(self._local_storage_root()).as_posix()
            if derived_folder and (not folder_name or not (self._local_storage_root() / folder_name).exists()):
                folder_name = derived_folder
                merged["folder_name"] = folder_name

        if not folder_name and not pdf_path:
            return merged

        png_path = self._resolve_local_file(
            merged.get("png_path"),
            merged.get("image_path"),
            folder_name=folder_name or None,
            file_name=merged.get("png_file"),
        )

        if pdf_path:
            pdf_upload = self.upload_file(
                pdf_path,
                self._object_path(run_id, category, folder_name, pdf_path.name),
                "application/pdf",
            )
            if pdf_upload:
                merged["pdf_storage_path"] = pdf_upload.path
                merged["pdf_storage_url"] = pdf_upload.url
                merged["download_storage_url"] = pdf_upload.url

        if png_path:
            png_upload = self.upload_file(
                png_path,
                self._object_path(run_id, category, folder_name, png_path.name),
                "image/png",
            )
            if png_upload:
                merged["png_storage_path"] = png_upload.path
                merged["png_storage_url"] = png_upload.url
                merged["preview_storage_url"] = png_upload.url
                merged["image_path"] = str(png_path.resolve())

        return merged

    def upload_file(
        self,
        local_path: str | Path,
        object_path: str,
        content_type: str,
    ) -> Optional[StorageUploadResult]:
        settings = get_settings()
        client = get_supabase()
        path = Path(local_path)
        if not client:
            logger.info("Supabase not configured — skipping document upload: %s", object_path)
            return None
        if not path.is_file() or path.stat().st_size <= 0:
            logger.warning("Document file not found for storage upload: %s", local_path)
            return None

        bucket = settings.supabase_storage_bucket
        file_bytes = path.read_bytes()

        def _upload() -> StorageUploadResult:
            storage = client.storage.from_(bucket)
            storage.upload(
                object_path,
                file_bytes,
                file_options={"content-type": content_type, "upsert": "true"},
            )
            public_url = storage.get_public_url(object_path)
            return StorageUploadResult(path=object_path, url=public_url)

        try:
            result = supabase_call(_upload, label="document_asset_storage_upload")
            if result:
                logger.info("Uploaded document asset to Supabase storage: %s", result.path)
            return result
        except Exception as exc:
            logger.warning("Document asset storage upload failed for %s: %s", object_path, exc)
            return None

    def _object_path(self, run_id: str, category: str, folder_name: str, filename: str) -> str:
        safe_folder = folder_name.replace("\\", "/").strip("/")
        safe_name = filename.replace("\\", "/").split("/")[-1]
        safe_category = category.replace("\\", "/").strip("/") or "documents"
        return f"runs/{run_id}/{safe_category}/{safe_folder}/{safe_name}"

    def _local_storage_root(self) -> Path:
        return BACKEND_ROOT / "local_storage"

    def _resolve_local_file(
        self,
        *paths: str | Path | None,
        folder_name: str | None = None,
        file_name: str | None = None,
    ) -> Path | None:
        candidates: list[Path] = []
        for candidate in paths:
            if candidate:
                candidates.append(Path(candidate))

        if folder_name and file_name:
            candidates.extend(
                [
                    BACKEND_ROOT / "local_storage" / folder_name / file_name,
                    Path("local_storage") / folder_name / file_name,
                    BACKEND_ROOT / "downloads" / folder_name / file_name,
                    Path("downloads") / folder_name / file_name,
                ]
            )

        if folder_name:
            meta_candidates = [
                BACKEND_ROOT / "local_storage" / folder_name / "metadata.json",
                Path("local_storage") / folder_name / "metadata.json",
            ]
            for meta_path in meta_candidates:
                if meta_path.is_file():
                    try:
                        import json

                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        for key in ("png_path", "pdf_path"):
                            value = meta.get(key)
                            if value:
                                candidates.append(Path(value))
                    except Exception:
                        pass

        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            for resolved in (candidate, BACKEND_ROOT / candidate):
                try:
                    path = resolved.resolve()
                    if path.is_file() and path.stat().st_size > 0:
                        return path
                except Exception:
                    continue
        return None
