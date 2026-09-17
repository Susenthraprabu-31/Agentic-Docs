from datetime import date, datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class QueryType(str, Enum):
    OWNER = "owner"
    PARCEL = "parcel"
    ADDRESS = "address"
    BOOK_PAGE = "book_page"


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


class NodeOverride(BaseModel):
    """Per-node inputs from the pipeline editor UI."""

    node_id: str = Field(description="Node key, e.g. assessor, recorder, gis, ai_agent")
    url: Optional[str] = None
    playwright_notes: Optional[str] = None
    enabled: bool = True
    # OpenAI Agent node fields (API key always from backend .env)
    agent_name: Optional[str] = None
    instructions: Optional[str] = None
    user_prompt: Optional[str] = None
    model: Optional[str] = "gpt-4o"
    agent_type: Optional[str] = "orchestrator"
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1000


class PipelineGraphNode(BaseModel):
    id: str
    node_id: str
    type: str = "pipelineNode"
    enabled: bool = True
    data: dict[str, Any] = Field(default_factory=dict)


class PipelineGraphEdge(BaseModel):
    source: str
    target: str


class PipelineGraph(BaseModel):
    nodes: list[PipelineGraphNode] = Field(default_factory=list)
    edges: list[PipelineGraphEdge] = Field(default_factory=list)


class SearchRequest(BaseModel):
    state: str = "AZ"
    county: str = "gila"
    query_type: QueryType
    query_value: str = Field(default="")
    address: Optional[str] = None
    owner_name: Optional[str] = None
    parcel_number: Optional[str] = None
    book_number: Optional[str] = None
    page_number: Optional[str] = None
    pipeline_graph: Optional[PipelineGraph] = None
    node_overrides: list[NodeOverride] = Field(default_factory=list)


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
    legal_description: Optional[str] = None
    assessed_value: Optional[float] = None
    property_address: Optional[str] = None
    source: str = "assessor"
    raw_json: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.legal_desc and not self.legal_description:
            self.legal_description = self.legal_desc
        elif self.legal_description and not self.legal_desc:
            self.legal_desc = self.legal_description


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


class GenerateInstructionsRequest(BaseModel):
    node_id: str = Field(description="assessor, recorder, gis, tax, or netr")
    state: str = "AZ"
    county: str = "gila"
    query_type: QueryType = QueryType.OWNER
    url: Optional[str] = None
    query_value: Optional[str] = ""
    playwright_notes: Optional[str] = None


class GenerateInstructionsResponse(BaseModel):
    instructions: str
    layout_type: str
    confidence: str
    reasoning: str
    resolved_url: str

