from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class CustomerWebsiteCreateRequest(BaseModel):
    name: str
    base_url: str
    seo_customer_since: date | None = None
    seo_goals: str | None = None
    category_id: str | None = None
    target_blogs_per_month: int | None = None


class CustomerWebsiteUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    seo_customer_since: date | None = None
    seo_goals: str | None = None
    category_id: str | None = None
    target_blogs_per_month: int | None = None


class CustomerWebsiteItem(BaseModel):
    id: str
    name: str
    base_url: str
    domain: str
    seo_customer_since: date | None = None
    seo_goals: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    target_blogs_per_month: int | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class CustomerWebsiteDetailResponse(CustomerWebsiteItem):
    placed_this_month: int = 0
    pending_blogs: int | None = None


class CustomerWebsitesResponse(BaseModel):
    websites: list[CustomerWebsiteItem]


class CustomerWebsiteListItem(CustomerWebsiteItem):
    placed_this_month: int = 0


class CustomerWebsitesListResponse(BaseModel):
    websites: list[CustomerWebsiteListItem]


class CustomerCategoryItem(BaseModel):
    id: str
    name: str
    customer_count: int = 0
    created_at: datetime
    updated_at: datetime


class CustomerCategoriesResponse(BaseModel):
    categories: list[CustomerCategoryItem]


class CustomerCategoryCreateRequest(BaseModel):
    name: str


class CustomerCategoryUpdateRequest(BaseModel):
    name: str


class WebsiteKeywordCreateRequest(BaseModel):
    keyword: str


class WebsiteKeywordUpdateRequest(BaseModel):
    keyword: str | None = None
    is_active: bool | None = None


class WebsiteKeywordItem(BaseModel):
    id: str
    website_id: str
    keyword: str
    is_active: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class WebsiteKeywordsResponse(BaseModel):
    keywords: list[WebsiteKeywordItem]


SerpScanStatus = Literal["pending", "processing", "completed", "failed", "canceled"]


class SerpScanItem(BaseModel):
    id: str
    website_id: str
    status: SerpScanStatus
    requested_by: str
    market: str
    total_keywords: int
    processed_keywords: int
    failed_keywords: int
    max_requests_per_scan: int
    skipped_due_to_limit: int
    truncated_by_limit: bool
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class StartWebsiteScanResponse(BaseModel):
    scan_id: str
    status: SerpScanStatus
    total_keywords: int
    max_requests_per_scan: int
    skipped_due_to_limit: int
    truncated_by_limit: bool


class SerpScansResponse(BaseModel):
    scans: list[SerpScanItem]


class WebsiteRankingItem(BaseModel):
    keyword_id: str
    keyword: str
    is_active: bool
    current_position: int | None = None
    previous_position: int | None = None
    delta: int | None = None
    current_result_url: str | None = None
    current_matched_host: str | None = None
    last_scanned_at: datetime | None = None
    latest_scan_id: str | None = None


class WebsiteRankingsResponse(BaseModel):
    website_id: str
    rankings: list[WebsiteRankingItem]
