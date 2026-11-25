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


# --- Search Console-inzichten -------------------------------------------------------------

class SearchConsolePeriod(BaseModel):
    start: str
    end: str
    days: int


class SearchConsoleTotals(BaseModel):
    clicks: int
    impressions: int
    # 0–1
    ctr: float
    # Leeg als er geen vertoningen waren.
    position: float | None = None


class SearchConsoleOpportunityRow(BaseModel):
    query: str
    page: str
    impressions: int
    clicks: int
    ctr: float
    expected_ctr: float
    position: float
    # Vertoningen × verwachte CTR − klikken.
    missed_clicks: int
    # Andere pagina's die op deze zoekterm vertoond werden.
    other_pages: int
    advice_code: Literal["improve_snippet_top", "improve_snippet", "improve_position", "check_intent"]
    advice: str


class SearchConsoleOpportunities(BaseModel):
    state: Literal["ok", "unavailable"]
    message: str | None = None
    rows: list[SearchConsoleOpportunityRow] = Field(default_factory=list)
    # Aantal kansen vóór het afkappen op 100.
    total: int = 0
    # Som van de gemiste klikken omgerekend naar 30 dagen, afgerond; leeg onder 5.
    potential_clicks_per_month: int | None = None
    # Merkzoektermen die aan de regels voldeden maar zijn weggelaten.
    brand_excluded: int = 0
    # True als Google meer rijen had dan opgehaald (de kansen kunnen onvolledig zijn).
    truncated: bool = False
    min_impressions: int


class SearchConsoleUntrackedRow(BaseModel):
    query: str
    impressions: int
    clicks: int
    position: float


class SearchConsoleUntracked(BaseModel):
    state: Literal["ok", "prt_not_tracked", "prt_not_configured", "prt_error", "unavailable"]
    message: str | None = None
    rows: list[SearchConsoleUntrackedRow] = Field(default_factory=list)
    total: int = 0
    # Aantal verschillende zoekwoorden in ProRankTracker (alleen bij state ok).
    tracked_keywords: int = 0


class SearchConsoleDecliningRow(BaseModel):
    page: str
    clicks: int
    clicks_prev: int
    # Negatief: klikken nu − klikken vorige periode.
    delta: int
    # In procenten, negatief (bijv. -35.2).
    pct: float
    impressions: int
    impressions_prev: int
    ctr: float
    ctr_prev: float | None = None
    position: float | None = None
    position_prev: float | None = None
    cause_code: Literal["no_impressions", "position_drop", "less_demand", "lower_ctr"]
    cause: str


class SearchConsoleDeclining(BaseModel):
    state: Literal["ok", "unavailable"]
    message: str | None = None
    rows: list[SearchConsoleDecliningRow] = Field(default_factory=list)
    total: int = 0


class CustomerSearchConsoleInsightsResponse(BaseModel):
    state: Literal["ok", "not_configured", "token_expired", "no_property", "property_inaccessible", "error"]
    message: str | None = None
    days: int
    property: str | None = None
    property_source: Literal["manual", "auto"] | None = None
    fetched_at: str | None = None
    period: SearchConsolePeriod
    previous: SearchConsolePeriod
    # Alleen bij state ok; `totals_previous` is ook leeg als de vorige periode niet opgehaald kon worden.
    totals: SearchConsoleTotals | None = None
    totals_previous: SearchConsoleTotals | None = None
    opportunities: SearchConsoleOpportunities | None = None
    untracked: SearchConsoleUntracked | None = None
    declining: SearchConsoleDeclining | None = None
