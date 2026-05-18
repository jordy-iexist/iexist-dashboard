from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


AuditStatus = Literal["pending", "crawling", "scanning", "completed", "failed", "canceled"]
AuditSeverity = Literal["critical", "warning", "info"]
AuditCategory = Literal[
    "typography", "performance", "accessibility", "links",
    "responsive", "seo", "console_error", "functionality"
]


class AuditCreateRequest(BaseModel):
    url: str = Field(..., min_length=1)
    max_pages: int = Field(default=50, ge=1, le=200)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = f"https://{v}"
        return v


class AuditSummary(BaseModel):
    total_issues: int = 0
    critical: int = 0
    warnings: int = 0
    info: int = 0
    categories: dict[str, int] = Field(default_factory=dict)
    score: int = 100  # 0-100


class AuditItem(BaseModel):
    id: str
    url: str
    domain: str
    status: AuditStatus
    total_pages: int
    scanned_pages: int
    failed_pages: int
    max_pages: int
    crawl_source: str | None = None
    summary: AuditSummary | None = None
    error_message: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class AuditListResponse(BaseModel):
    items: list[AuditItem]
    total: int


class AuditPageItem(BaseModel):
    id: str
    audit_id: str
    url: str
    path: str
    status: str
    typography_data: Any = None
    performance_data: Any = None
    accessibility_data: Any = None
    console_errors: Any = None
    meta_data: Any = None
    links_data: Any = None
    responsive_data: Any = None
    screenshots: Any = None
    issue_count: int = 0
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class AuditPageListResponse(BaseModel):
    pages: list[AuditPageItem]
    total: int


class AuditIssueItem(BaseModel):
    id: str
    audit_id: str
    page_id: str | None = None
    category: AuditCategory
    severity: AuditSeverity
    title: str
    description: str
    selector: str | None = None
    page_url: str | None = None
    issue_metadata: Any = None
    created_at: datetime


class AuditIssueListResponse(BaseModel):
    issues: list[AuditIssueItem]
    total: int


class StartAuditResponse(BaseModel):
    audit_id: str
    status: AuditStatus
    url: str
