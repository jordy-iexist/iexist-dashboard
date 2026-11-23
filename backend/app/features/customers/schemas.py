from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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


class CustomerContentGap(BaseModel):
    keyword: str
    volume: int


class CustomerRankingsResponse(BaseModel):
    state: Literal["ok", "not_configured", "not_tracked", "error"]
    message: str | None = None
    fetched_at: str | None = None
    keywords: int = 0
    ranked: int = 0
    avg_position: float | None = None
    # Positief = verbeterd t.o.v. een maand geleden.
    avg_position_delta: float | None = None
    top3: int = 0
    top3_delta: int | None = None
    # Gevolgd zonder positie in de top 100, met zoekvolume: maximaal 5, hoogste volume eerst.
    content_gaps: list[CustomerContentGap] = Field(default_factory=list)
    # Totaal aantal contentkansen, vóór het afkappen.
    content_gaps_total: int = 0


class CustomerQuickWinRow(BaseModel):
    keyword: str
    position: int
    # Positief = gestegen t.o.v. 30 dagen geleden; leeg als het zoekwoord toen niet rankte.
    delta: int | None = None
    volume: int | None = None
    kd: int | None = None
    url: str | None = None
    kans: Literal["hoog", "middel", "laag"]
    # Herkomst: alleen ProRankTracker, alleen Ahrefs, of beide (PRT bepaalt dan positie/delta/url).
    source: Literal["prt", "ahrefs", "both"]


class CustomerQuickWinsResponse(BaseModel):
    state: Literal["ok", "not_configured", "error"]
    message: str | None = None
    fetched_at: str | None = None
    limit: int
    # True als er `limit` rijen zijn (er kunnen er meer zijn).
    capped: bool = False
    rows: list[CustomerQuickWinRow] = Field(default_factory=list)
