import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

from app.queue.playwright_runner import run_async_in_playwright_thread

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = BACKEND_ROOT / "reports"


def is_valid_pdf(path: str | Path | None) -> bool:
    if not path:
        return False
    file_path = Path(path)
    if not file_path.is_file() or file_path.suffix.lower() != ".pdf":
        return False
    try:
        with file_path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


class PdfExporter:
    def __init__(self, output_dir: Optional[Path] = None) -> None:
        self.output_dir = output_dir or DEFAULT_REPORTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def _render_pdf(self, html: str, pdf_path: Path) -> str:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(html, wait_until="domcontentloaded")
            await page.pdf(path=str(pdf_path), format="A4", print_background=True)
            await browser.close()

        if not is_valid_pdf(pdf_path):
            raise RuntimeError(f"Playwright did not produce a valid PDF at {pdf_path}")

        return str(pdf_path.resolve())

    async def html_to_pdf(self, html: str, filename: str) -> str:
        pdf_path = (self.output_dir / filename).resolve()
        html_path = pdf_path.with_suffix(".html")
        html_path.write_text(html, encoding="utf-8")

        def _render() -> str:
            return run_async_in_playwright_thread(lambda: self._render_pdf(html, pdf_path))

        try:
            if sys.platform == "win32":
                return _render()

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return await self._render_pdf(html, pdf_path)

            return _render()
        except Exception as exc:
            logger.error("PDF export failed: %s", exc)
            raise RuntimeError(f"PDF export failed: {exc}") from exc
