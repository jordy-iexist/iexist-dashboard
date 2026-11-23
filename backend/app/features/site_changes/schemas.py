from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Topic = Literal[
    "meta_title", "meta_description", "headings", "text", "faq", "image_alt", "internal_links",
    "technical", "performance", "other",
]
SourceKind = Literal["content_suggestion", "scan_issue"]
ChangeStatus = Literal["open", "goedgekeurd", "afgewezen", "doorgevoerd"]
ChangeAction = Literal["approve", "reject", "reopen", "done"]


class SourceRef(BaseModel):
    suggestion_id: str | None = None
    issue_id: str | None = None


class VerifyDetail(BaseModel):
    checked_at: str
    message: str | None = None
    live_value: str | None = None
    missing: list[str] = Field(default_factory=list)


class ChangeItem(BaseModel):
    key: str
    change_id: str | None = None
    source_kind: SourceKind
    source_ref: SourceRef
    topic: Topic
    title: str
    description: str | None = None
    current_value: str | None = None
    proposed_value: str | None = None
    approved_value: str | None = None
    edited: bool = False
    rationale: str | None = None
    ref: str | None = None
    severity: Literal["laag", "middel", "hoog"] | None = None
    item_label: str | None = None
    status: ChangeStatus
    checkable: bool
    verified: bool | None = None
    verify_detail: VerifyDetail | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    done_by: str | None = None
    done_at: datetime | None = None
    note: str | None = None


class PageSummary(BaseModel):
    url: str
    path: str
    title: str | None = None
    open_count: int
    approved_count: int
    done_count: int


class PageTotals(BaseModel):
    open: int
    approved: int
    done: int


class PagesResponse(BaseModel):
    pages: list[PageSummary]
    totals: PageTotals
    has_sources: bool


class SchemaSummary(BaseModel):
    status: Literal["none", "suggested", "approved", "rejected", "placed"]
    types: list[str] = Field(default_factory=list)
    placed_at: datetime | None = None
    verified: bool | None = None


class ChangeGroup(BaseModel):
    topic: Topic
    label: str
    items: list[ChangeItem]


class PageDetail(BaseModel):
    url: str
    path: str
    title: str | None = None
    groups: list[ChangeGroup]
    rejected: list[ChangeItem]
    done: list[ChangeItem]
    schema_: SchemaSummary | None = Field(default=None, alias="schema", serialization_alias="schema")
    last_checked_at: datetime | None = None

    model_config = {"populate_by_name": True}


class ChangeUpdate(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    source_kind: SourceKind
    source_ref: SourceRef = Field(default_factory=SourceRef)
    action: ChangeAction
    value: str | None = Field(default=None, max_length=20_000)
    note: str | None = Field(default=None, max_length=2_000)


class PageCheckRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2_000)


class PageCheckResponse(BaseModel):
    page: PageDetail
    checked: int
    verified: int
    resolved_issues: int
