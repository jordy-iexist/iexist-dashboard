from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

WorkStatus = Literal["todo", "doing", "review", "done"]
WorkSource = Literal["scan", "analysis", "search_console", "site_changes", "manual"]
WorkKind = Literal["ctr", "techniek", "content", "links", "update", "rapport"]
WorkSeverity = Literal["hoog", "middel", "laag"]


class Card(BaseModel):
    id: str
    customer_id: str
    customer_name: str
    source: WorkSource
    kind: WorkKind
    # Zonder aantal; de frontend zet `item_count` en `unit` erachter.
    title: str
    item_count: int
    # Enkelvoud of meervoud bij `item_count`; null bij een eigen taak.
    unit: str | None = None
    severity: WorkSeverity
    status: WorkStatus
    position: float
    assignee_id: str | None = None
    assignee_name: str | None = None
    has_note: bool
    resolved_by_source: bool
    done_at: datetime | None = None
    created_at: datetime


class CardItem(BaseModel):
    key: str
    title: str
    url: str | None = None
    path: str | None = None
    severity: str | None = None


class ScanLink(BaseModel):
    source: Literal["scan"] = "scan"
    customer_id: str
    phase: int
    issue_type: str


class AnalysisLink(BaseModel):
    source: Literal["analysis"] = "analysis"
    customer_id: str
    analysis_id: str
    keyword_id: str


class SearchConsoleLink(BaseModel):
    source: Literal["search_console"] = "search_console"
    customer_id: str


class SiteChangesLink(BaseModel):
    source: Literal["site_changes"] = "site_changes"
    customer_id: str
    url: str


SourceLink = Annotated[
    Union[ScanLink, AnalysisLink, SearchConsoleLink, SiteChangesLink],
    Field(discriminator="source"),
]


class CardDetail(Card):
    note: str | None = None
    items: list[CardItem] = Field(default_factory=list)
    # Waar de bron staat; null bij een eigen taak.
    source_link: SourceLink | None = None
    done_by_name: str | None = None
    created_by_name: str | None = None


class BoardColumn(BaseModel):
    status: WorkStatus
    label: str
    count: int
    cards: list[Card]


class BoardTotals(BaseModel):
    todo: int
    doing: int
    review: int
    done: int
    # Open kaarten zonder medewerker (binnen de filters).
    unassigned: int


class BoardCustomer(BaseModel):
    id: str
    name: str
    open_count: int


class BoardUser(BaseModel):
    id: str
    name: str
    email: str
    open_count: int


class BoardResponse(BaseModel):
    week_start: datetime
    columns: list[BoardColumn]
    totals: BoardTotals
    customers: list[BoardCustomer]
    users: list[BoardUser]


class UserOption(BaseModel):
    id: str
    name: str
    email: str


# --- verzoeken ----------------------------------------------------------------------
# Bewust ruime types: de router controleert soort, status en titel zelf, zodat een fout een
# platte Nederlandse zin geeft in plaats van de standaard validatielijst.


class CardCreate(BaseModel):
    title: Any = None
    customer_id: Any = None
    kind: Any = None
    status: Any = None
    assignee_id: Any = None
    note: Any = None


class CardUpdate(BaseModel):
    """Alleen meegestuurde velden tellen (`model_fields_set`): `assignee_id: null` en
    `note: null` wissen de waarde, weggelaten velden blijven ongemoeid."""

    status: Any = None
    after_id: str | None = None
    before_id: str | None = None
    assignee_id: str | None = None
    note: str | None = None
    title: Any = None
    kind: Any = None


class OkResponse(BaseModel):
    ok: bool = True
