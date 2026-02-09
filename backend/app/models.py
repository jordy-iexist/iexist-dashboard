from pydantic import BaseModel
from typing import Any
from datetime import datetime


class UploadResponse(BaseModel):
    upload_id: str
    rows_count: int
    jobs_queued: int
    status: str


class UploadStatus(BaseModel):
    upload_id: str
    filename: str
    template: str
    total_jobs: int
    completed: int
    failed: int
    pending: int


class BlogItem(BaseModel):
    id: str
    row_data: dict[str, Any]
    content: str
    created_at: datetime


class BlogsResponse(BaseModel):
    blogs: list[BlogItem]
