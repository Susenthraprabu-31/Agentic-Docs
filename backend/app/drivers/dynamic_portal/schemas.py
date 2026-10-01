"""Data models and schemas for Dynamic County Portal Intelligence."""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class BlockingType(str, Enum):
    NORMAL = "NORMAL"
    CLOUDFLARE_CHALLENGE = "CLOUDFLARE_CHALLENGE"
    CAPTCHA = "CAPTCHA"
    ACCESS_DENIED = "ACCESS_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN_BLOCK = "UNKNOWN_BLOCK"


class RunErrorStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NO_RESULTS = "NO_RESULTS"
    MULTIPLE_RESULTS = "MULTIPLE_RESULTS"
    MISMATCH = "MISMATCH"
    NAVIGATION_FAILED = "NAVIGATION_FAILED"
    NAVIGATION_LIMIT_REACHED = "NAVIGATION_LIMIT_REACHED"
    PORTAL_CHANGED = "PORTAL_CHANGED"
    CLOUDFLARE_CHALLENGE = "CLOUDFLARE_CHALLENGE"
    CAPTCHA_DETECTED = "CAPTCHA_DETECTED"
    ACCESS_DENIED = "ACCESS_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    NETWORK_ERROR = "NETWORK_ERROR"
    AI_ANALYSIS_FAILED = "AI_ANALYSIS_FAILED"
    ACTION_VALIDATION_FAILED = "ACTION_VALIDATION_FAILED"
    DOCUMENT_DOWNLOAD_FAILED = "DOCUMENT_DOWNLOAD_FAILED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class PropertySearchInput(BaseModel):
    """Canonical property model across all county variations."""
    address: Optional[str] = None
    parcelNumber: Optional[str] = None
    ownerName: Optional[str] = None
    accountNumber: Optional[str] = None
    folioNumber: Optional[str] = None
    county: str
    state: str

    def get_effective_parcel(self) -> Optional[str]:
        """Returns the primary parcel/APN/folio identifier if available."""
        return self.parcelNumber or self.folioNumber or self.accountNumber


class DetectionResult(BaseModel):
    blocked: bool = False
    type: BlockingType = BlockingType.NORMAL
    confidence: float = 1.0
    recommendedAction: str = "CONTINUE"  # CONTINUE, STOP_AND_RECOVER, MANUAL_REVIEW_REQUIRED, RETRY_TRANSIENT
    details: Dict[str, Any] = Field(default_factory=dict)


class CompactElement(BaseModel):
    tag: str
    text: str = ""
    selector: str
    name: Optional[str] = None
    id: Optional[str] = None
    type: Optional[str] = None
    placeholder: Optional[str] = None
    role: Optional[str] = None
    aria_label: Optional[str] = None
    label_text: Optional[str] = None
    href: Optional[str] = None
    value: Optional[str] = None
    is_visible: bool = True
    is_enabled: bool = True


class CompactIframe(BaseModel):
    selector: str
    src: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    title: Optional[str] = None


class CompactBrowserState(BaseModel):
    """Compact representation of current page state to avoid sending full HTML."""
    url: str
    title: str = ""
    visible_text: str = ""
    inputs: List[CompactElement] = Field(default_factory=list)
    buttons: List[CompactElement] = Field(default_factory=list)
    links: List[CompactElement] = Field(default_factory=list)
    selects: List[CompactElement] = Field(default_factory=list)
    iframes: List[CompactIframe] = Field(default_factory=list)
    dialogs: List[str] = Field(default_factory=list)
    has_captcha_indicators: bool = False
    has_cloudflare_indicators: bool = False
    has_login_indicators: bool = False


class SearchFieldMapping(BaseModel):
    field_type: str  # parcel, address, owner, account, folio
    selector: str
    confidence: float = 1.0
    label: Optional[str] = None
    input_type: Optional[str] = None


class PortalAnalysis(BaseModel):
    page_type: str  # search_form, landing_page, results_page, detail_page, blocked, login_required
    is_search_page: bool = False
    search_fields: Dict[str, SearchFieldMapping] = Field(default_factory=dict)
    submit_button_selector: Optional[str] = None
    tab_selectors: Dict[str, str] = Field(default_factory=dict)  # e.g. {"address": "...", "parcel": "..."}
    dropdown_selectors: Dict[str, str] = Field(default_factory=dict)
    iframe_selector: Optional[str] = None
    reasoning: str = ""
    confidence: float = 1.0


AllowedActionType = Literal[
    "fill", "click", "select", "wait", "navigate", "scroll", "switch_frame", "open_tab"
]


class BrowserAction(BaseModel):
    action: AllowedActionType
    selector: Optional[str] = None
    value: Optional[str] = None
    timeout_ms: Optional[int] = 10000
    description: Optional[str] = None


class SearchPlan(BaseModel):
    status: str = "ready"  # ready, cannot_search, blocked, needs_navigation
    strategy: Optional[str] = None  # parcel, address, owner, account
    actions: List[BrowserAction] = Field(default_factory=list)
    reasoning: str = ""


class ActionResult(BaseModel):
    success: bool
    action: BrowserAction
    error_message: Optional[str] = None
    duration_ms: int = 0


class SearchResultItem(BaseModel):
    parcelNumber: Optional[str] = None
    address: Optional[str] = None
    ownerName: Optional[str] = None
    legalDescription: Optional[str] = None
    propertyUrl: Optional[str] = None
    raw_data: Dict[str, Any] = Field(default_factory=dict)


class SearchResultAnalysis(BaseModel):
    status: RunErrorStatus
    results_count: int = 0
    records: List[SearchResultItem] = Field(default_factory=list)
    best_match: Optional[SearchResultItem] = None
    requires_disambiguation: bool = False
    disambiguation_candidates: List[SearchResultItem] = Field(default_factory=list)
    message: str = ""


class DocumentItem(BaseModel):
    title: str
    document_type: str  # Deed, Mortgage, Release, Assignment, Lien, Tax Document, Instrument
    link_selector: Optional[str] = None
    download_url: Optional[str] = None
    file_path: Optional[str] = None
    file_size_bytes: int = 0
    is_valid_pdf: bool = False
    sha256_hash: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PortalFingerprint(BaseModel):
    domain: str
    url_pattern: str
    page_title_pattern: str
    form_signature: str
    stable_identifiers: List[str] = Field(default_factory=list)


class PortalMapping(BaseModel):
    county: str
    state: str
    domain: str
    portal_type: str = "assessor"  # assessor, recorder, tax, gis
    search_page_url: str
    navigation_path: List[str] = Field(default_factory=list)
    search_fields: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    submit_selector: Optional[str] = None
    tab_selectors: Dict[str, str] = Field(default_factory=dict)
    iframe_selector: Optional[str] = None
    fingerprint: Optional[PortalFingerprint] = None
    last_verified: str = ""
    analysis_version: str = "1.0"
