"""Document Agent: Discovers, downloads, validates, and hashes property documents."""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from app.drivers.dynamic_portal.schemas import CompactBrowserState, DocumentItem
from app.report.pdf_exporter import is_valid_pdf

logger = logging.getLogger(__name__)

DOCUMENT_TYPES = [
    ("deed", "Deed"),
    ("mortgage", "Mortgage"),
    ("release", "Release"),
    ("assignment", "Assignment"),
    ("lien", "Lien"),
    ("tax", "Tax Document"),
    ("plat", "Plat Map"),
    ("warranty", "Warranty Deed"),
    ("quitclaim", "Quit Claim Deed"),
    ("instrument", "Recorded Instrument"),
]


class DocumentAgent:
    """Discovers and downloads recorded documents with integrity and deduplication checks."""

    def __init__(self, download_dir: Optional[Path] = None) -> None:
        self.download_dir = download_dir or (Path("screenshots") / "dynamic_downloads")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.seen_hashes: Set[str] = set()

    def identify_documents(self, state: CompactBrowserState) -> List[DocumentItem]:
        """Inspect links and buttons for recorded document links."""
        docs: List[DocumentItem] = []
        seen_selectors: Set[str] = set()

        for link in state.links:
            text = (link.text or "").lower()
            href = (link.href or "").lower()
            title = link.text or "Recorded Document"

            # Check if link points to a PDF or document viewer
            is_doc_link = href.endswith(".pdf") or "/pdf" in href or "viewdocument" in href or "getimage" in href
            matched_type = "Recorded Instrument"
            for kw, dtype in DOCUMENT_TYPES:
                if kw in text or kw in href:
                    matched_type = dtype
                    is_doc_link = True
                    break

            if is_doc_link and link.selector not in seen_selectors:
                seen_selectors.add(link.selector)
                docs.append(
                    DocumentItem(
                        title=title,
                        document_type=matched_type,
                        link_selector=link.selector,
                        download_url=link.href,
                    )
                )

        return docs

    def validate_file(self, file_path: Path) -> tuple[bool, int, Optional[str]]:
        """
        Validate:
        1. File exists
        2. Size > 0
        3. Valid PDF header (%PDF) if expected
        4. SHA-256 hash for deduplication
        Returns (is_valid, size_bytes, sha256_hash)
        """
        if not file_path.exists():
            return False, 0, None

        size = file_path.stat().st_size
        if size == 0:
            return False, 0, None

        # Calculate sha256
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        digest = h.hexdigest()

        # Check duplicate
        if digest in self.seen_hashes:
            logger.info("Duplicate document file skipped: %s (hash: %s)", file_path.name, digest[:12])
            return False, size, digest

        # PDF check
        valid_pdf = is_valid_pdf(str(file_path))
        if not valid_pdf:
            # Check raw magic bytes in case pdf_exporter had strict requirement
            with open(file_path, "rb") as f:
                header = f.read(1024)
                if b"%PDF" in header:
                    valid_pdf = True

        return valid_pdf, size, digest

    async def download_document(
        self,
        page: Any,
        doc_item: DocumentItem,
        run_id: str,
    ) -> Optional[DocumentItem]:
        """
        Trigger download in Playwright and validate integrity.
        """
        if not doc_item.link_selector:
            return None

        run_folder = self.download_dir / run_id
        run_folder.mkdir(parents=True, exist_ok=True)

        try:
            loc = page.locator(doc_item.link_selector).first
            if await loc.count() == 0:
                return None

            async with page.expect_download(timeout=15000) as download_info:
                await loc.click(force=True)

            download = await download_info.value
            suggested_name = download.suggested_filename or f"doc_{int(time.time())}.pdf"
            target_path = run_folder / suggested_name
            await download.save_as(target_path)

            is_valid, size, digest = self.validate_file(target_path)
            if not is_valid:
                logger.warning("Downloaded document failed validation: %s", target_path)
                return None

            self.seen_hashes.add(digest)
            doc_item.file_path = str(target_path)
            doc_item.file_size_bytes = size
            doc_item.is_valid_pdf = True
            doc_item.sha256_hash = digest
            return doc_item

        except Exception as exc:
            logger.warning("Document download failed for %s: %s", doc_item.title, exc)
            return None
