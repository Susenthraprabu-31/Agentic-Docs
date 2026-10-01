"""Download Miami-Dade Property Appraiser Summary and Detailed reports as PDFs."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from app.extraction.florida_extractors import extract_valid_miami_dade_folio

if TYPE_CHECKING:
    from app.drivers.assessor.gila_assessor_driver import GilaAssessorDriver

logger = logging.getLogger(__name__)

MIAMI_DADE_REPORT_TYPES: tuple[tuple[str, str, str], ...] = (
    ("summary", "Assessor Summary Report", "assessor_summary"),
    ("detailed", "Assessor Detailed Report", "assessor_detailed"),
)


def _folio_storage_key(folio: str) -> str:
    normalized = extract_valid_miami_dade_folio(folio) or folio.strip()
    digits = re.sub(r"\D", "", normalized)
    return digits or re.sub(r"[^\w.-]+", "_", normalized)


def assessor_storage_folder(folio: str) -> str:
    """Return the assessor storage folder path under local_storage."""
    return f"assessor/{_folio_storage_key(folio)}"


def _assessor_report_paths(folio: str, report_slug: str) -> tuple[Path, str, str]:
    folder_name = assessor_storage_folder(folio)
    pdf_filename = f"{report_slug}_{_folio_storage_key(folio)}.pdf"
    local_dir = Path("local_storage").resolve() / folder_name
    local_dir.mkdir(parents=True, exist_ok=True)
    return local_dir / pdf_filename, pdf_filename, folder_name


async def _wait_for_miami_dade_report_page(report_page: Any) -> None:
    for selector in [
        "text=Generated On",
        "text=PROPERTY INFORMATION",
        "text=Property Information",
        "text=Folio",
    ]:
        try:
            await report_page.wait_for_selector(selector, state="visible", timeout=30_000)
            break
        except Exception:
            continue
    await report_page.wait_for_timeout(4_000)


async def _save_report_page_pdf(report_page: Any, dest_pdf: Path) -> bool:
    try:
        await _wait_for_miami_dade_report_page(report_page)
        await report_page.emulate_media(media="print")
        await report_page.pdf(
            path=str(dest_pdf),
            format="Letter",
            print_background=True,
            margin={"top": "0.4in", "right": "0.4in", "bottom": "0.4in", "left": "0.4in"},
        )
        return dest_pdf.is_file() and dest_pdf.stat().st_size > 0
    except Exception as exc:
        logger.warning("Could not save Miami-Dade assessor report PDF to %s: %s", dest_pdf, exc)
        return False


async def _open_miami_dade_print_dialog(driver: "GilaAssessorDriver") -> bool:
    selectors = [
        '[aria-label="Print property report"]',
        'a[aria-label="Print property report"]',
        'img[alt="Print"]',
        'img[title="Print"]',
    ]
    for selector in selectors:
        try:
            button = driver.page.locator(selector).first
            if await button.count() > 0 and await button.is_visible(timeout=2_000):
                await button.click(force=True)
                await driver.polite_delay(1.0)
                if await driver.page.locator("text=PRINT REPORT").count() > 0:
                    return True
        except Exception:
            continue
    return False


async def _click_miami_dade_report_button(
    driver: "GilaAssessorDriver",
    report_type: str,
) -> Any | None:
    label = "Print Summary Report" if report_type == "summary" else "Print Detailed Report"
    selectors = [
        f'[aria-label="{label}"]',
        f'button:has-text("{ "Summary Report" if report_type == "summary" else "Detailed Report" }")',
    ]
    for selector in selectors:
        try:
            button = driver.page.locator(selector).first
            if await button.count() == 0 or not await button.is_visible(timeout=2_000):
                continue
            async with driver.context.expect_page(timeout=30_000) as page_info:
                await button.click(force=True)
            report_page = await page_info.value
            await report_page.wait_for_load_state("domcontentloaded")
            return report_page
        except Exception as exc:
            logger.debug("Report button click failed on %s: %s", selector, exc)
    return None


async def _open_miami_dade_report_window(
    driver: "GilaAssessorDriver",
    folio: str,
    report_type: str,
) -> Any | None:
    folio_digits = _folio_storage_key(folio)
    report_hash = f"#/report/{report_type}"
    try:
        async with driver.context.expect_page(timeout=30_000) as page_info:
            await driver.page.evaluate(
                """([folioValue, reportType, reportHash]) => {
                  sessionStorage.setItem('currentFolio', folioValue);
                  sessionStorage.setItem('currentParentFolio', folioValue);
                  sessionStorage.setItem('report_type', reportType);
                  window.open(reportHash, 'Report', 'height=760,width=1020,location=0,resizable=yes,toolbar=yes');
                }""",
                [folio_digits, report_type, report_hash],
            )
        report_page = await page_info.value
        await report_page.wait_for_load_state("domcontentloaded")
        return report_page
    except Exception as exc:
        logger.debug("Direct Miami-Dade report window open failed: %s", exc)
        return None


async def _download_single_miami_dade_assessor_report(
    driver: "GilaAssessorDriver",
    folio: str,
    report_type: str,
    document_type: str,
    report_slug: str,
) -> Optional[dict[str, Any]]:
    dest_pdf, pdf_filename, folder_name = _assessor_report_paths(folio, report_slug)
    if dest_pdf.is_file() and dest_pdf.stat().st_size > 0:
        return {
            "document_type": document_type,
            "book_page": None,
            "instrument_number": folio,
            "source_url": driver.page.url,
            "screenshot_path": str(dest_pdf),
            "ocr_json": {
                "source": "assessor",
                "storage_category": "assessor",
                "report_type": report_type,
                "folio": extract_valid_miami_dade_folio(folio) or folio,
                "download_path": str(dest_pdf),
                "folder_name": folder_name,
                "file_name": pdf_filename,
            },
        }

    report_page = None
    opened_dialog = await _open_miami_dade_print_dialog(driver)
    if opened_dialog:
        report_page = await _click_miami_dade_report_button(driver, report_type)
    if report_page is None:
        report_page = await _open_miami_dade_report_window(driver, folio, report_type)
    if report_page is None:
        await driver._emit_status(
            f"Miami-Dade assessor: could not open {document_type.lower()}."
        )
        return None

    saved = False
    try:
        await driver._emit_status(f"Miami-Dade assessor: saving {document_type}...")
        saved = await _save_report_page_pdf(report_page, dest_pdf)
    finally:
        try:
            await report_page.close()
        except Exception:
            pass

    if not saved:
        await driver._emit_status(
            f"Miami-Dade assessor: failed to save {document_type.lower()}."
        )
        return None

    await driver._emit_status(f"Miami-Dade assessor: saved {document_type}.")
    return {
        "document_type": document_type,
        "book_page": None,
        "instrument_number": extract_valid_miami_dade_folio(folio) or folio,
        "source_url": driver.page.url,
        "screenshot_path": str(dest_pdf),
        "ocr_json": {
            "source": "assessor",
            "storage_category": "assessor",
            "report_type": report_type,
            "folio": extract_valid_miami_dade_folio(folio) or folio,
            "download_path": str(dest_pdf),
            "folder_name": folder_name,
            "file_name": pdf_filename,
        },
    }


async def download_miami_dade_assessor_reports(
    driver: "GilaAssessorDriver",
    folio: str,
) -> list[dict[str, Any]]:
    """Download Summary and Detailed assessor reports for the active property page."""
    if not folio:
        return []

    documents: list[dict[str, Any]] = []
    for report_type, document_type, report_slug in MIAMI_DADE_REPORT_TYPES:
        doc = await _download_single_miami_dade_assessor_report(
            driver,
            folio,
            report_type,
            document_type,
            report_slug,
        )
        if doc:
            documents.append(doc)

    return documents
