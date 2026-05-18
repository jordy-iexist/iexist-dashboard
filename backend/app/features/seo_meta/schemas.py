from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


MetaRunStatus = Literal["pending", "processing", "completed", "failed", "canceled"]
MetaReviewStatus = Literal["pending_review", "approved", "rejected"]


class MetaRunCreateRequest(BaseModel):
    page_limit: int | None = Field(default=None, ge=1, le=500)
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)


class MetaRunItem(BaseModel):
    id: str
    website_id: str
    status: MetaRunStatus
    requested_by: str
    source: str
    total_pages: int
    processed_pages: int
    failed_pages: int
    max_pages_per_run: int
    skipped_due_to_limit: int
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class StartMetaRunResponse(BaseModel):
    run_id: str
    status: MetaRunStatus
    total_pages: int
    max_pages_per_run: int
    skipped_due_to_limit: int


class MetaRunsResponse(BaseModel):
    runs: list[MetaRunItem]


class MetaPageItem(BaseModel):
    id: str
    run_id: str
    website_id: str
    url: str
    path: str
    current_title: str | None = None
    current_description: str | None = None
    suggested_title: str | None = None
    suggested_description: str | None = None
    approved_title: str | None = None
    approved_description: str | None = None
    review_status: MetaReviewStatus
    generation_error: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MetaRunPagesResponse(BaseModel):
    pages: list[MetaPageItem]
    total: int


class WebsiteMetaLatestResponse(BaseModel):
    run: MetaRunItem | None = None
    pages: list[MetaPageItem] = Field(default_factory=list)


class MetaPageUpdateRequest(BaseModel):
    review_status: MetaReviewStatus | None = None
    approved_title: str | None = None
    approved_description: str | None = None
