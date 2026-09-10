import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.agents.county_resolver import CountyResolver
from app.agents.extraction_normalizer import ExtractionNormalizer
from app.agents.run_logger import RunLogger
from app.db.repositories.documents_repository import DocumentsRepository
from app.db.repositories.records_repository import RecordsRepository
from app.db.repositories.runs_repository import RunsRepository
from app.config.florida_portals import resolve_florida_recorder_url, resolve_florida_tax_url, supports_florida_tax_record
from app.drivers.assessor.gila_assessor_driver import GilaAssessorDriver
from app.drivers.base.base_driver import BaseDriver
from app.drivers.gis.gila_gis_driver import GilaGisDriver
from app.drivers.netronline.netronline_driver import NetronlineDriver
from app.drivers.recorder.gila_recorder_driver import GilaRecorderDriver
from app.drivers.tax.florida_tax_driver import FloridaTaxDriver
from app.extraction.document_ocr import DocumentOcrService
from app.extraction.schemas import CountySources, QueryType, RunStatus, SourceType

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCREENSHOTS_DIR = BACKEND_ROOT / "screenshots"


class Orchestrator:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.runs_repo = RunsRepository()
        self.records_repo = RecordsRepository()
        self.documents_repo = DocumentsRepository()
        self.run_logger = RunLogger(run_id)
        self.normalizer = ExtractionNormalizer()
        self.ocr = DocumentOcrService()
        self.sources: Optional[CountySources] = None

    async def execute(
        self,
        state: str,
        county: str,
        query_type: QueryType,
        query_value: str,
    ) -> dict[str, Any]:
        self.runs_repo.update_run(
            self.run_id,
            status=RunStatus.RUNNING.value,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        total_records = 0
        plan: dict[str, Any] = {
            "steps": [
                "open_netronline_directory",
                "search_assessor",
                "search_tax_record",
                "capture_gis_screenshot",
                "search_recorder",
            ],
            "state": state,
            "county": county,
            "query_type": query_type.value,
            "query_value": query_value,
        }
        self.runs_repo.update_run(self.run_id, plan_json=plan)

        driver = NetronlineDriver(screenshot_dir=SCREENSHOTS_DIR)
        try:
            async def _status(msg: str) -> None:
                await self.run_logger.log("human_action_required", message=msg)

            driver.status_callback = _status
            await driver.start()
            resolver = CountyResolver(driver)

            # Step 1: NETR Online
            t0 = time.monotonic()
            await self.run_logger.source_started(SourceType.NETRONLINE, "https://publicrecords.netronline.com/")
            self.sources = await resolver.resolve(state, county)
            duration = int((time.monotonic() - t0) * 1000)
            links_found = sum(
                1
                for u in [
                    self.sources.assessor_url,
                    self.sources.recorder_url,
                    self.sources.treasurer_url,
                    self.sources.gis_url,
                ]
                if u
            )
            await self.run_logger.source_completed(
                SourceType.NETRONLINE,
                records_found=links_found,
                duration_ms=duration,
            )

            # Step 2: Assessor (reuse browser context via new page in same context)
            if self.sources.assessor_url:
                total_records += await self._search_assessor(
                    driver, self.sources.assessor_url, query_type, query_value, state, county
                )
            else:
                await self.run_logger.source_skipped(SourceType.ASSESSOR, "No Assessor URL resolved from NETR")

            parcel = query_value if query_type == QueryType.PARCEL else None
            records = self.records_repo.list_by_run(self.run_id)
            assessor_record = next((r for r in records if r.get("source") == "assessor"), records[0] if records else None)
            if not parcel and assessor_record:
                parcel = assessor_record.get("apn")
            owner_name = assessor_record.get("owner_name") if assessor_record else None

            # Step 3: Tax Record — click through from floridapa parcel details
            if supports_florida_tax_record(state, county) and parcel:
                total_records += await self._search_tax_record(
                    driver, state, county, parcel, owner_name
                )
            elif supports_florida_tax_record(state, county):
                await self.run_logger.source_skipped(
                    SourceType.TAX_RECORD, "No parcel ID resolved for tax record lookup"
                )
            else:
                await self.run_logger.source_skipped(
                    SourceType.TAX_RECORD, "Tax record lookup not configured for this county"
                )

            # Step 4: GIS — capture while parcel details may still be open
            gis_captured = False
            if self.sources.gis_url and parcel:
                gis_captured = await self._capture_gis(
                    driver, self.sources.gis_url, parcel, query_type, query_value
                )
            elif self.sources.gis_url:
                await self.run_logger.source_skipped(SourceType.GIS, "No parcel ID resolved for GIS map")
            else:
                await self.run_logger.source_skipped(SourceType.GIS, "No GIS URL resolved from NETR")

            # Step 5: Recorder
            if self.sources.recorder_url:
                total_records += await self._search_recorder(
                    driver, self.sources.recorder_url, query_type, query_value, state, county
                )
            else:
                await self.run_logger.source_skipped(SourceType.RECORDER, "No Recorder URL resolved from NETR")

            if self.sources.gis_url and parcel and not gis_captured:
                await self._capture_gis(
                    driver, self.sources.gis_url, parcel, query_type, query_value
                )

            self.runs_repo.update_run(
                self.run_id,
                status=RunStatus.COMPLETED.value,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.run_logger.run_completed(total_records=total_records)
            return {"run_id": self.run_id, "total_records": total_records, "sources": self.sources.model_dump()}

        except Exception as exc:
            logger.exception("Run %s failed", self.run_id)
            self.runs_repo.update_run(
                self.run_id,
                status=RunStatus.FAILED.value,
                error_message=str(exc),
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.run_logger.log("run_failed", message=str(exc))
            raise
        finally:
            await driver.stop()

    def _persist_assessor_chain_of_title(self, parcel: Any) -> int:
        chain = (parcel.raw_json or {}).get("chain_of_title") or []
        source_url = (parcel.raw_json or {}).get("source_url")
        saved = 0
        for entry in chain:
            if not isinstance(entry, dict):
                continue
            grantor = entry.get("grantor")
            grantee = entry.get("grantee")
            doc_type = entry.get("document_type") or "Sale"
            recording_date = entry.get("recording_date")
            sale_price = entry.get("sale_price")
            instrument_number = entry.get("instrument_number")
            if not any([grantor, grantee, recording_date, sale_price, instrument_number]):
                continue
            self.documents_repo.insert(
                self.run_id,
                {
                    "document_type": doc_type,
                    "recording_date": recording_date,
                    "grantor": grantor,
                    "grantee": grantee,
                    "book_page": entry.get("book_page"),
                    "instrument_number": entry.get("instrument_number"),
                    "source_url": source_url,
                    "ocr_json": {
                        "sale_price": sale_price,
                        "source": "assessor_sales",
                        "section": "sales_information",
                    },
                },
            )
            saved += 1
        return saved

    async def _search_assessor(
        self,
        base: BaseDriver,
        url: str,
        query_type: QueryType,
        query_value: str,
        state: str,
        county: str,
    ) -> int:
        t0 = time.monotonic()
        assessor = GilaAssessorDriver()
        assessor._page = base.page
        assessor._context = base.context
        assessor._browser = base._browser
        assessor._playwright = base._playwright
        assessor.screenshot_dir = base.screenshot_dir
        assessor.status_callback = base.status_callback

        try:
            await self.run_logger.source_started(SourceType.ASSESSOR, url)
            parcels = await assessor.search(url, query_type, query_value, state=state, county=county)
            count = 0
            for parcel in parcels:
                html_snippet = json.dumps(parcel.raw_json) if parcel.raw_json else ""
                normalized = await self.normalizer.normalize("assessor", html_snippet, parcel)
                self.records_repo.insert(
                    self.run_id,
                    {
                        "source": "assessor",
                        "apn": normalized.apn,
                        "owner_name": normalized.owner_name,
                        "legal_desc": normalized.legal_desc,
                        "assessed_value": normalized.assessed_value,
                        "property_address": normalized.property_address,
                        "raw_json": normalized.raw_json,
                    },
                )
                chain_saved = self._persist_assessor_chain_of_title(normalized)
                if chain_saved:
                    await self.run_logger.log(
                        "record_found",
                        source=SourceType.ASSESSOR,
                        message=f"Saved {chain_saved} chain-of-title entry(ies) from assessor sales data.",
                        records_found=chain_saved,
                    )
                await self.run_logger.record_found(SourceType.ASSESSOR, apn=normalized.apn, owner=normalized.owner_name)
                count += 1
            duration = int((time.monotonic() - t0) * 1000)
            await self.run_logger.source_completed(SourceType.ASSESSOR, records_found=count, duration_ms=duration)
            return count
        except Exception as exc:
            await self.run_logger.source_failed(SourceType.ASSESSOR, str(exc))
            await assessor.screenshot_on_failure("assessor_error")
            return 0

    async def _search_recorder(
        self,
        base: BaseDriver,
        url: str,
        query_type: QueryType,
        query_value: str,
        state: str,
        county: str,
    ) -> int:
        t0 = time.monotonic()
        recorder = GilaRecorderDriver()
        recorder._page = base.page
        recorder._context = base.context
        recorder._browser = base._browser
        recorder._playwright = base._playwright
        recorder.screenshot_dir = base.screenshot_dir
        recorder.status_callback = base.status_callback

        search_url = url
        if state.upper() == "FL":
            search_url = resolve_florida_recorder_url(url, county)

        try:
            await self.run_logger.source_started(SourceType.RECORDER, search_url)
            documents = await recorder.search(search_url, query_type, query_value)
            count = 0
            for doc in documents:
                if doc.screenshot_path:
                    doc = await self.ocr.extract_document(doc.screenshot_path, doc.document_type)
                normalized = await self.normalizer.normalize(
                    "recorder",
                    json.dumps(doc.ocr_json) if doc.ocr_json else query_value,
                    doc,
                )
                self.documents_repo.insert(
                    self.run_id,
                    {
                        "document_type": normalized.document_type,
                        "recording_date": normalized.recording_date.isoformat() if normalized.recording_date else None,
                        "book_page": normalized.book_page,
                        "instrument_number": normalized.instrument_number,
                        "grantor": normalized.grantor,
                        "grantee": normalized.grantee,
                        "source_url": normalized.source_url or url,
                        "screenshot_path": normalized.screenshot_path,
                        "ocr_json": normalized.ocr_json,
                    },
                )
                count += 1
            duration = int((time.monotonic() - t0) * 1000)
            await self.run_logger.source_completed(SourceType.RECORDER, records_found=count, duration_ms=duration)
            return count
        except Exception as exc:
            await self.run_logger.source_failed(SourceType.RECORDER, str(exc))
            await recorder.screenshot_on_failure("recorder_error")
            return 0

    async def _search_tax_record(
        self,
        base: BaseDriver,
        state: str,
        county: str,
        apn: str,
        owner_name: Optional[str],
    ) -> int:
        t0 = time.monotonic()
        tax = FloridaTaxDriver(screenshot_dir=base.screenshot_dir)
        tax._page = base.page
        tax._context = base.context
        tax._browser = base._browser
        tax._playwright = base._playwright
        tax.status_callback = base.status_callback

        tax_url = resolve_florida_tax_url(county, apn)
        try:
            await self.run_logger.source_started(SourceType.TAX_RECORD, tax_url)
            record = await tax.fetch_tax_record(county, apn, owner_name)
            if not record:
                await self.run_logger.source_failed(
                    SourceType.TAX_RECORD, "Could not capture tax bill details from county tax site."
                )
                return 0

            self.records_repo.insert(
                self.run_id,
                {
                    "source": "tax_record",
                    "apn": apn,
                    "owner_name": record.owner_name or owner_name,
                    "property_address": record.property_address,
                    "assessed_value": record.amount_due,
                    "raw_json": record.raw_json,
                },
            )
            await self.run_logger.record_found(
                SourceType.TAX_RECORD,
                apn=apn,
                tax_account=record.tax_account,
                tax_year=record.tax_year,
            )
            duration = int((time.monotonic() - t0) * 1000)
            await self.run_logger.source_completed(
                SourceType.TAX_RECORD, records_found=1, duration_ms=duration
            )
            return 1
        except Exception as exc:
            await self.run_logger.source_failed(SourceType.TAX_RECORD, str(exc))
            await tax.screenshot_on_failure("tax_record_error")
            return 0

    async def _capture_gis(
        self,
        base: BaseDriver,
        url: str,
        parcel: str,
        query_type: QueryType,
        query_value: str,
    ) -> bool:
        t0 = time.monotonic()
        gis = GilaGisDriver(screenshot_dir=base.screenshot_dir)
        gis._page = base.page
        gis._context = base.context
        gis._browser = base._browser
        gis._playwright = base._playwright
        gis.status_callback = base.status_callback
        try:
            await self.run_logger.source_started(SourceType.GIS, url)
            path = await gis.capture_parcel_map(url, parcel, query_type, query_value)
            duration = int((time.monotonic() - t0) * 1000)
            await self.run_logger.source_completed(
                SourceType.GIS, records_found=1 if path else 0, duration_ms=duration, screenshot_path=path
            )
            return bool(path)
        except Exception as exc:
            await self.run_logger.source_failed(SourceType.GIS, str(exc))
            return False
