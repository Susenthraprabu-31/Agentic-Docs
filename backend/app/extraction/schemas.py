from datetime import date, datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class QueryType(str, Enum):
    OWNER = "owner"
    PARCEL = "parcel"
    ADDRESS = "address"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceType(str, Enum):
    NETRONLINE = "netronline"
    ASSESSOR = "assessor"
    RECORDER = "recorder"
    TREASURER = "treasurer"
    TAX_RECORD = "tax_record"
    GIS = "gis"


class SourceStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class SearchRequest(BaseModel):
    state: str = "AZ"
    county: str = "gila"
    query_type: QueryType
    query_value: str = Field(min_length=1)


class SearchResponse(BaseModel):
    run_id: str


class CountySources(BaseModel):
    assessor_url: Optional[str] = None
    recorder_url: Optional[str] = None
    treasurer_url: Optional[str] = None
    gis_url: Optional[str] = None
    phones: dict[str, str] = Field(default_factory=dict)


class ParcelRecord(BaseModel):
    apn: Optional[str] = None
    owner_name: Optional[str] = None
    legal_desc: Optional[str] = None
    assessed_value: Optional[float] = None
    property_address: Optional[str] = None
    source: str = "assessor"
    raw_json: dict[str, Any] = Field(default_factory=dict)


class RecordedDocument(BaseModel):
    document_type: Optional[str] = None
    recording_date: Optional[date] = None
    book_page: Optional[str] = None
    instrument_number: Optional[str] = None
    grantor: Optional[str] = None
    grantee: Optional[str] = None
    source_url: Optional[str] = None
    screenshot_path: Optional[str] = None
    ocr_json: dict[str, Any] = Field(default_factory=dict)


class TaxRecord(BaseModel):
    apn: Optional[str] = None
    tax_account: Optional[str] = None
    owner_name: Optional[str] = None
    tax_year: Optional[str] = None
    bill_number: Optional[str] = None
    amount_due: Optional[float] = None
    property_address: Optional[str] = None
    mailing_address: Optional[str] = None
    source_url: Optional[str] = None
    raw_json: dict[str, Any] = Field(default_factory=dict)


class RunEventPayload(BaseModel):
    message: Optional[str] = None
    url: Optional[str] = None
    records_found: int = 0
    duration_ms: Optional[int] = None
    reason: Optional[str] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class RunEvent(BaseModel):
    id: Optional[str] = None
    run_id: str
    event_type: str
    source: Optional[SourceType] = None
    payload: RunEventPayload | dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class RunRecord(BaseModel):
    id: str
    state: str
    county: str
    query_type: QueryType
    query_value: str
    status: RunStatus
    plan_json: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class RunDetailResponse(BaseModel):
    run: RunRecord
    events: list[RunEvent] = Field(default_factory=list)
    records_count: int = 0
    documents_count: int = 0
    records: list[dict[str, Any]] = Field(default_factory=list)
    documents: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)


class ReportSummary(BaseModel):
    id: str
    run_id: str
    report_json: dict[str, Any]
    pdf_path: Optional[str] = None
    pdf_url: Optional[str] = None
    created_at: Optional[datetime] = None


class SourceProgress(BaseModel):
    source: SourceType
    status: SourceStatus = SourceStatus.PENDING
    records_found: int = 0
    message: Optional[str] = None
