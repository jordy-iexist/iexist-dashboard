from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ManualUploadRequest(BaseModel):
    template: str
    rows: list[dict[str, Any]]


class UploadResponse(BaseModel):
    upload_id: str
    rows_count: int
    jobs_queued: int
    skipped_rows: int = 0
    images_target: int = 0
    status: str


class UploadStatus(BaseModel):
    upload_id: str
    filename: str
    template: str
    total_jobs: int
    jobs_created: int
    completed: int
    failed: int
    processing: int
    pending: int
    canceled: int = 0
    processed: int
    remaining: int
    skipped_rows: int
    images_generated: int = 0
    images_target: int = 0
    is_done: bool
    final_status: Literal["processing", "completed", "completed_with_errors", "canceled"]


class RecentUploadItem(BaseModel):
    upload_id: str
    filename: str
    template: str
    created_at: datetime
    total_jobs: int
    completed: int
    failed: int
    canceled: int
    processed: int
    is_done: bool
    final_status: Literal["processing", "completed", "completed_with_errors", "canceled"]


class RecentUploadsResponse(BaseModel):
    uploads: list[RecentUploadItem]


class BlogItem(BaseModel):
    id: str
    row_data: dict[str, Any]
    content: str
    created_at: datetime


class BlogsResponse(BaseModel):
    blogs: list[BlogItem]


class BlogPublicationSummary(BaseModel):
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    pending: int = 0
    processing: int = 0


class BlogsListItem(BaseModel):
    id: str
    row_data: dict[str, Any] = Field(default_factory=dict)
    content: str
    filename: str
    created_at: datetime
    published_at: datetime | None = None
    publication: BlogPublicationSummary | None = None
    share_token: str
    is_public: bool = False
    is_owner: bool = True


class BlogsListResponse(BaseModel):
    blogs: list[BlogsListItem]
    total: int
    page: int
    page_size: int


class BlogDetailResponse(BaseModel):
    id: str
    row_data: dict[str, Any] = Field(default_factory=dict)
    content: str
    filename: str
    status: str
    created_at: datetime
    published_at: datetime | None = None
    share_token: str
    is_public: bool = False
    is_owner: bool = True


class BlogShareResponse(BaseModel):
    id: str
    content: str
    created_at: datetime
    images: list["BlogImageItem"] = Field(default_factory=list)


class BlogUpdateRequest(BaseModel):
    content: str | None = None
    is_public: bool | None = None


BlogImageSource = Literal["auto_generated", "manual_upload"]
BlogImageGenerationState = Literal[
    "idle",
    "pending",
    "processing",
    "completed",
    "failed",
]


class BlogImageItem(BaseModel):
    id: str
    blog_id: str
    source: BlogImageSource
    storage_path: str
    signed_url: str | None = None
    mime_type: str
    file_size_bytes: int
    width: int | None = None
    height: int | None = None
    is_primary: bool
    generation_prompt: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class BlogImagesResponse(BaseModel):
    images: list[BlogImageItem]


class GenerateBlogImageResponse(BaseModel):
    status: Literal["queued"]
    message: str
    job_id: str


class BlogImageGenerationStatusResponse(BaseModel):
    blog_id: str
    state: BlogImageGenerationState
    progress_percent: int = Field(ge=0, le=100)
    message: str
    job_id: str | None = None
    error_message: str | None = None
    has_primary_image: bool
    primary_image_id: str | None = None
    primary_image_created_at: datetime | None = None


# WordPress schemas

PublicationStatus = Literal[
    "pending",
    "processing",
    "succeeded",
    "failed",
    "blocked_duplicate",
]
WordPressPostStatus = Literal["draft", "publish"]


class WordPressSiteCreateRequest(BaseModel):
    name: str | None = None
    base_url: str
    wp_login: str
    wp_password: str


class WordPressSiteUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    wp_login: str | None = None
    wp_password: str | None = None
    is_active: bool | None = None


class WordPressSiteItem(BaseModel):
    id: str
    name: str
    base_url: str
    wp_login: str
    is_active: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class WordPressSitesResponse(BaseModel):
    sites: list[WordPressSiteItem]


class PublishBlogRequest(BaseModel):
    site_ids: list[str] = Field(default_factory=list)
    wp_status: WordPressPostStatus = "draft"


class PublishBatchRequest(BaseModel):
    blog_ids: list[str] = Field(default_factory=list)
    site_ids: list[str] = Field(default_factory=list)
    wp_status: WordPressPostStatus = "draft"


class DeleteBatchRequest(BaseModel):
    blog_ids: list[str] = Field(default_factory=list)


class DeleteBatchResponse(BaseModel):
    requested: int
    deleted: int
    missing: list[str] = Field(default_factory=list)


class PublicationItem(BaseModel):
    id: str
    blog_id: str
    wordpress_site_id: str
    status: PublicationStatus
    requested_by: str
    wp_post_id: str | None = None
    wp_post_url: str | None = None
    wp_media_id: str | None = None
    blog_image_id: str | None = None
    wp_status: WordPressPostStatus
    error_code: str | None = None
    error_message: str | None = None
    warning_code: str | None = None
    warning_message: str | None = None
    created_at: datetime
    updated_at: datetime


class BlockedPublicationItem(BaseModel):
    blog_id: str
    wordpress_site_id: str
    status: Literal["blocked_duplicate"] = "blocked_duplicate"
    reason: str = "Deze blog is al gepubliceerd naar deze WordPress site."


class PublishActionResponse(BaseModel):
    requested: int
    queued: int
    blocked_duplicates: int
    publications: list[PublicationItem]
    blocked: list[BlockedPublicationItem]


class PublicationListResponse(BaseModel):
    publications: list[PublicationItem]


class BlogGenerationSettingsResponse(BaseModel):
    system_prompt: str | None = None
    reasoning_effort: str | None = None
    model: str | None = None
    max_output_tokens: int | None = None
    effective_system_prompt: str
    effective_reasoning_effort: str
    effective_model: str
    effective_max_output_tokens: int


class BlogGenerationSettingsUpdateRequest(BaseModel):
    system_prompt: str | None = None
    reasoning_effort: str | None = None
    model: str | None = None
    max_output_tokens: int | None = None
