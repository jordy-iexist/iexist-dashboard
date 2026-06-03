from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

LANDING_PAGE_MAX_OUTPUT_TOKENS_MIN = 1000
LANDING_PAGE_MAX_OUTPUT_TOKENS_MAX = 50000


class LandingPageManualUploadRequest(BaseModel):
    template: str = ""
    rows: list[dict[str, str]]


class LandingPageUploadResponse(BaseModel):
    upload_id: str
    rows_count: int
    jobs_queued: int
    skipped_rows: int = 0
    status: str


class LandingPageUploadStatusResponse(BaseModel):
    upload_id: str
    filename: str
    total_jobs: int
    completed: int
    failed: int
    processing: int
    pending: int
    canceled: int = 0
    processed: int
    remaining: int
    skipped_rows: int
    is_done: bool
    final_status: Literal["processing", "completed", "completed_with_errors", "canceled"]


class LandingPageRecentUploadItem(BaseModel):
    upload_id: str
    filename: str
    created_at: datetime
    total_jobs: int
    completed: int
    failed: int
    canceled: int
    processed: int
    is_done: bool
    final_status: Literal["processing", "completed", "completed_with_errors", "canceled"]


class LandingPageRecentUploadsResponse(BaseModel):
    uploads: list[LandingPageRecentUploadItem]


class LandingPageListItem(BaseModel):
    id: str
    meta_title: str | None = None
    onderwerp: str = ""  # from row_data for preview
    filename: str = ""
    status: str
    created_at: datetime


class LandingPageListResponse(BaseModel):
    landing_pages: list[LandingPageListItem]
    total: int
    page: int
    page_size: int


class LandingPageDetailResponse(BaseModel):
    id: str
    content: str
    meta_title: str | None = None
    meta_description: str | None = None
    slug: str | None = None
    share_token: str
    status: str
    onderwerp: str = ""  # from row_data for display
    filename: str = ""
    created_at: datetime


class LandingPageUpdateRequest(BaseModel):
    content: str | None = None
    meta_title: str | None = None
    meta_description: str | None = None
    slug: str | None = None


class LandingPageGenerationSettingsResponse(BaseModel):
    system_prompt: str | None = None
    reasoning_effort: str | None = None
    model: str | None = None
    max_output_tokens: int | None = None
    effective_system_prompt: str
    effective_reasoning_effort: str
    effective_model: str
    effective_max_output_tokens: int


class LandingPageGenerationSettingsUpdateRequest(BaseModel):
    system_prompt: str | None = None
    reasoning_effort: str | None = None
    model: str | None = None
    max_output_tokens: int | None = Field(
        default=None,
        ge=LANDING_PAGE_MAX_OUTPUT_TOKENS_MIN,
        le=LANDING_PAGE_MAX_OUTPUT_TOKENS_MAX,
    )


class DeleteBatchRequest(BaseModel):
    landing_page_ids: list[str] = Field(default_factory=list)


class DeleteBatchResponse(BaseModel):
    requested: int
    deleted: int
    missing: list[str] = Field(default_factory=list)
