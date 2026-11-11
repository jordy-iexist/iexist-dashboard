from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ScanStatus = Literal[
    "pending", "discovering", "inventory", "vitals", "analyzing",
    "completed", "failed", "canceled",
]
IssueStatus = Literal["open", "doorgezet", "opgelost", "genegeerd"]
ACTIVE_STATUSES = {"pending", "discovering", "inventory", "vitals", "analyzing"}


class LaunchScanCreateRequest(BaseModel):
    customer_website_id: str = Field(..., min_length=1)
    max_pages: int = Field(default=500, ge=1, le=2000)
    vitals_max_pages: int = Field(default=100, ge=0, le=500)


class LaunchScanItem(BaseModel):
    id: str
    customer_website_id: str
    phase: int
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
