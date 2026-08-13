from datetime import datetime

from pydantic import BaseModel


class CustomerSheetColumnItem(BaseModel):
    id: str
    label: str
    position: int


class CustomerSheetColumnCreateRequest(BaseModel):
    label: str


class CustomerSheetColumnUpdateRequest(BaseModel):
    label: str | None = None
    position: int | None = None


class CustomerSheetRowItem(BaseModel):
    id: str
    title: str
    created_at: datetime
    published_at: datetime | None = None
    is_owner: bool = True
    words: str | None = None
    anchor_1: str | None = None
    anchor_1_url: str | None = None
    anchor_2: str | None = None
    anchor_2_url: str | None = None
    placement_url: str | None = None
    cells: dict[str, str | None] = {}


class CustomerSheetResponse(BaseModel):
    columns: list[CustomerSheetColumnItem]
    rows: list[CustomerSheetRowItem]


class CustomerSheetCellUpsertRequest(BaseModel):
    blog_id: str
    column_id: str
    value: str | None = None


class CustomerSheetCellItem(BaseModel):
    column_id: str
    blog_id: str
    value: str | None = None
