from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ScanStatus = Literal[
    "pending", "discovering", "inventory", "vitals", "analyzing",
    "fetching", "linking", "checking",
    "completed", "failed", "canceled",
]
IssueStatus = Literal["open", "doorgezet", "opgelost", "genegeerd"]
ACTIVE_STATUSES = {"pending", "discovering", "inventory", "vitals", "analyzing", "fetching", "linking", "checking"}
ManualStatus = Literal["open", "afgerond", "nvt"]


class LaunchScanCreateRequest(BaseModel):
    customer_website_id: str = Field(..., min_length=1)
    max_pages: int = Field(default=500, ge=1, le=2000)
    vitals_max_pages: int = Field(default=100, ge=0, le=500)


class LaunchScanItem(BaseModel):
    id: str
    customer_website_id: str
    phase: int
    source_scan_id: str | None = None
    status: ScanStatus
    base_url: str
    discovery_source: str | None = None
    total_urls: int
    inventoried_urls: int
    failed_urls: int
    max_pages: int
    vitals_max_pages: int
    vitals_total: int
    vitals_measured: int
    summary_stats: Any = None
    warnings: Any = None
    error_message: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class LaunchScanDetail(LaunchScanItem):
    ai_checks: Any = None
    # Ahrefs-snapshot: {target, country, fetched_at, reused_from, units, domain, errors, ...}
    ahrefs: Any = None
    ai_summary: str | None = None
    agent_trace: Any = None


class LaunchScanListResponse(BaseModel):
    items: list[LaunchScanItem]
    total: int


class LaunchCustomerItem(BaseModel):
    id: str
    name: str
    base_url: str
    domain: str
    category_name: str | None = None
    latest_scan: LaunchScanItem | None = None
    latest_geo_scan: LaunchScanItem | None = None
    checklist_progress: "ChecklistProgress | None" = None
    latest_content_scan: LaunchScanItem | None = None
    content_progress: "ChecklistProgress | None" = None
    # Fase 2/3 gebaseerd op een oudere nulmeting dan de nieuwste (ook lopende) fase-1-scan.
    geo_outdated: bool = False
    content_outdated: bool = False


class LaunchCustomerListResponse(BaseModel):
    customers: list[LaunchCustomerItem]


class LaunchScanPageItem(BaseModel):
    id: str
    url: str
    path: str
    in_sitemap: bool
    status_code: int | None = None
    final_url: str | None = None
    redirect_chain: Any = None
    response_time_ms: int | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    http_version: str | None = None
    indexable: bool | None = None
    indexability_reason: str | None = None
    meta_robots: str | None = None
    title: str | None = None
    title_length: int | None = None
    meta_description: str | None = None
    meta_description_length: int | None = None
    h1: Any = None
    h1_count: int | None = None
    h2: Any = None
    canonical: str | None = None
    word_count: int | None = None
    lang: str | None = None
    hreflang: Any = None
    internal_links: int | None = None
    external_links: int | None = None
    broken_links: Any = None
    images_total: int | None = None
    images_missing_alt: int | None = None
    schema_types: Any = None
    open_graph: Any = None
    cwv: Any = None
    cwv_status: str | None = None
    error: str | None = None
    page_type: str | None = None
    page_type_source: str | None = None
    click_depth: int | None = None
    inlinks: int | None = None
    schema_all: list[str] | None = None
    # Ahrefs: organisch verkeer per maand, verwijzende domeinen en details (topzoekwoord, bron).
    org_traffic: int | None = None
    refdomains: int | None = None
    ahrefs: Any = None
    issue_count: int = 0


class LaunchScanPageListResponse(BaseModel):
    pages: list[LaunchScanPageItem]
    total: int


class LaunchScanIssueItem(BaseModel):
    id: str
    scan_id: str
    page_id: str | None = None
    issue_type: str
    issue_label: str | None = None
    category: str
    severity: str
    title: str
    description: str
    recommendation: str | None = None
    url: str | None = None
    details: Any = None
    status: IssueStatus
    external_provider: str | None = None
    external_item_id: str | None = None
    external_url: str | None = None
    pushed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class IssueGroup(BaseModel):
    issue_type: str
    label: str
    category: str
    severity: str
    count: int
    open: int


class LaunchScanIssueListResponse(BaseModel):
    issues: list[LaunchScanIssueItem]
    total: int
    groups: list[IssueGroup]


class IssueStatusUpdate(BaseModel):
    status: IssueStatus


class IssueBulkStatusUpdate(BaseModel):
    issue_ids: list[str] = Field(..., min_length=1, max_length=2000)
    status: IssueStatus


# --- fase 2: GEO/SEO-checklist ---------------------------------------------

class ChecklistProgress(BaseModel):
    done: int
    total: int
    percent: int


class ChecklistItemOut(BaseModel):
    key: str
    label: str
    description: str | None = None
    mode: str
    applies_to: str
    priority: str
    auto: Any = None
    manual_status: ManualStatus | None = None
    note: str | None = None
    updated_at: datetime | None = None
    external_url: str | None = None
    pushed_at: datetime | None = None
    effective: Literal["done", "open", "nvt"]
    f1_issue_types: list[str] = []


class ChecklistSectionOut(BaseModel):
    key: str
    label: str
    items: list[ChecklistItemOut]
    done: int
    total: int


class ChecklistResponse(BaseModel):
    customer_id: str
    customer_name: str
    base_url: str
    scan: LaunchScanItem | None = None
    source_scan_id: str | None = None
    is_webshop: bool
    webshop_detected: bool | None = None
    webshop_override: bool | None = None
    webshop_reasons: list[str] = []
    page_types: dict[str, int] = {}
    generated_at: str | None = None
    sections: list[ChecklistSectionOut]
    done: int
    total: int
    percent: int


class ChecklistStateUpdate(BaseModel):
    manual_status: ManualStatus | None = None
    note: str | None = Field(default=None, max_length=5000)


class WebshopUpdate(BaseModel):
    is_webshop: bool | None = None


class PageTypeUpdate(BaseModel):
    page_type: str = Field(..., min_length=1, max_length=40)


class GeoScanCreateRequest(BaseModel):
    source_scan_id: str | None = None


# --- Fase 3: content & onpage ------------------------------------------------

SuggestionStatus = Literal["open", "overgenomen", "afgewezen"]


class ContentChecklistResponse(BaseModel):
    customer_id: str
    customer_name: str
    base_url: str
    scan: LaunchScanItem | None = None
    source_scan_id: str | None = None
    page_types: dict[str, int] = {}
    generated_at: str | None = None
    gap_analyzed_at: str | None = None
    summary: Any = None
    max_pages_per_analysis: int
    sections: list[ChecklistSectionOut]
    done: int
    total: int
    percent: int


class ContentSuggestionItem(BaseModel):
    id: str
    scan_id: str
    content_page_id: str | None = None
    page_url: str | None = None
    item_key: str
    item_label: str
    agent: str
    title: str | None = None
    current_value: str | None = None
    proposed_value: str
    rationale: str | None = None
    details: Any = None
    status: SuggestionStatus
    created_at: datetime
    updated_at: datetime


class ContentSuggestionListResponse(BaseModel):
    items: list[ContentSuggestionItem]
    total: int


class ContentPageItem(BaseModel):
    id: str
    url: str
    path: str
    page_type: str | None = None
    title: str | None = None
    meta_description: str | None = None
    word_count: int | None = None
    problem_count: int
    # item_key → {status, message, details}
    checks: dict[str, Any] = {}
    analysis_status: str
    analysis_error: str | None = None
    focus_keyword: str | None = None
    intent: str | None = None
    keyword_source: str | None = None
    # Ahrefs: het zoekwoord waarop de pagina nu het meeste verkeer krijgt.
    ahrefs_keyword: dict[str, Any] | None = None
    analyzed_at: datetime | None = None
    suggestions_open: int = 0
    suggestions_total: int = 0
    # Checklistpunten waarvoor deze pagina open AI-voorstellen heeft.
    suggestion_items: list[str] = []


class ContentPageDetail(ContentPageItem):
    headings: Any = None
    first_paragraph: str | None = None
    readability: str | None = None
    images_total: int = 0
    links_total: int = 0
    suggestions: list[ContentSuggestionItem] = []


class ContentPageListResponse(BaseModel):
    items: list[ContentPageItem]
    total: int
    page_types: dict[str, int] = {}


class ContentAnalysisRequest(BaseModel):
    # Leeg mag als alleen de contentgap-analyse moet draaien.
    page_ids: list[str] = Field(default_factory=list, max_length=200)
    # Ook de contentgap-analyse (nieuwe content) opnieuw draaien.
    run_gap: bool = True


class ContentKeywordUpdate(BaseModel):
    """Handmatig focuszoekwoord; leeg = weer door de AI laten bepalen."""
    focus_keyword: str | None = Field(default=None, max_length=200)
    intent: Literal["informatief", "commercieel", "transactioneel", "navigatie", "lokaal"] | None = None


class SuggestionStatusUpdate(BaseModel):
    status: SuggestionStatus


# --- Monday ----------------------------------------------------------------

class MondaySettingsResponse(BaseModel):
    token_configured: bool
    folder_name: str
    board_id: str | None = None
    board_url: str | None = None
    board_name: str | None = None
    # Melding als het gekoppelde bord niet (meer) bereikbaar is.
    board_error: str | None = None


class MondayBoardLink(BaseModel):
    """Bestaand bord koppelen (id of bord-URL); None ontkoppelt."""
    board: str | None = Field(default=None, max_length=500)


class MondayPushIssuesRequest(BaseModel):
    issue_ids: list[str] = Field(..., min_length=1, max_length=25)


class MondayPushChecklistRequest(BaseModel):
    item_keys: list[str] = Field(..., min_length=1, max_length=25)


class MondayPushOutcome(BaseModel):
    ref: str
    status: Literal["pushed", "skipped", "failed"]
    message: str | None = None
    external_url: str | None = None


class MondayPushResponse(BaseModel):
    board_url: str | None = None
    pushed: int
    skipped: int
    failed: int
    outcomes: list[MondayPushOutcome]


LaunchCustomerItem.model_rebuild()
