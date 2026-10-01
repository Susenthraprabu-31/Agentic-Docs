"""Resolve local document preview/PDF paths from OCR metadata."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _existing_file(*candidates: str | Path | None) -> Path | None:
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        for path in (Path(candidate), BACKEND_ROOT / candidate):
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            try:
                resolved = path.resolve()
                if resolved.is_file() and resolved.stat().st_size > 0:
                    return resolved
            except Exception:
                continue
    return None


def resolve_document_pdf_path(doc: dict[str, Any]) -> Path | None:
    ocr = doc.get("ocr_json") or {}
    folder_name = ocr.get("folder_name")
    return _existing_file(
        ocr.get("download_path"),
        doc.get("screenshot_path"),
        ocr.get("pdf_path"),
        Path("local_storage") / folder_name / ocr.get("pdf_file") if folder_name and ocr.get("pdf_file") else None,
        Path("local_storage") / folder_name / f"{Path(str(folder_name)).name}.pdf" if folder_name else None,
    )


def resolve_document_preview_path(doc: dict[str, Any], pdf_path: Path | None = None) -> Path | None:
    ocr = doc.get("ocr_json") or {}
    if ocr.get("source") == "assessor":
        return None

    if pdf_path is None:
        pdf_path = resolve_document_pdf_path(doc)

    folder_name = ocr.get("folder_name")
    if pdf_path and "local_storage" in pdf_path.as_posix().replace("\\", "/"):
        derived_folder = pdf_path.parent.name
        if derived_folder and (
            not folder_name or not (BACKEND_ROOT / "local_storage" / folder_name).exists()
        ):
            folder_name = str(pdf_path.parent.relative_to(BACKEND_ROOT / "local_storage")).replace("\\", "/")

    png_file = ocr.get("png_file")
    if folder_name and not png_file:
        png_file = f"{Path(str(folder_name)).name}.png"

    preview = _existing_file(
        ocr.get("png_path"),
        ocr.get("image_path"),
        ocr.get("preview_path"),
        Path("local_storage") / folder_name / png_file if folder_name and png_file else None,
    )
    if preview:
        return preview

    if folder_name:
        for meta_path in (
            BACKEND_ROOT / "local_storage" / folder_name / "metadata.json",
            Path("local_storage") / folder_name / "metadata.json",
        ):
            if not meta_path.is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                preview = _existing_file(meta.get("png_path"))
                if preview:
                    return preview
            except Exception as exc:
                logger.debug("Could not read metadata preview path from %s: %s", meta_path, exc)

    if pdf_path and pdf_path.suffix.lower() == ".pdf":
        sibling = pdf_path.with_suffix(".png")
        if sibling.is_file() and sibling.stat().st_size > 0:
            return sibling

    screenshot = doc.get("screenshot_path")
    if screenshot and str(screenshot).lower().endswith(".pdf"):
        sibling = Path(screenshot).with_suffix(".png")
        if sibling.is_file() and sibling.stat().st_size > 0:
            return sibling
    return None


def resolve_document_preview_url(doc: dict[str, Any]) -> str | None:
    ocr = doc.get("ocr_json") or {}
    for key in ("preview_storage_url", "png_storage_url", "preview_url"):
        value = ocr.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None
