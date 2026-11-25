"""Contract van het maandrapport per klant.

Eén bestand voor de schrijver (worker), de agent en de lezer (router), zodat ze dezelfde vorm
gebruiken:
1. Literal-types en constanten voor statussen en toestanden per cijfer.
2. De vorm van de JSON-kolommen van `monthly_reports`: `data` (`ReportData`, momentopname van
   cijfers en werk), `report` (`ReportText`, uitvoer van de agent na naverwerking) en `manual`
   (`Manual`, handmatige cijfers). Schrijven: `Model(...).model_dump(mode="json")`; lezen:
   `Model.model_validate(waarde)` (een lege kolom is `None`).
3. De request/response-modellen van `/api/monthly-reports`.

Conventies:
- `month` is "YYYY-MM"; datums zijn ISO-tekst ("2026-11-01"), tijdstippen timezone-aware (UTC).
- `data` en `report` worden samen weggeschreven als een run slaagt; `manual` schrijft alleen de
  router. De tegel "Aanvragen" op het scherm komt uit `MonthlyReport.leads` (berekend uit
  `manual`), niet uit `data`; `data.metrics.leads` is wat de agent bij het schrijven kreeg.
- Id's in `work` beginnen met "W", in `upcoming` met "N"; de agent verwijst ernaar in `refs`.
- Claude-verbruik in US-dollar (`AiUsage.cost_usd`).
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.features.competitor_analysis.schemas import AiUsage

# --- Statussen en constanten -----------------------------------------------------------------

# draft = rij die alleen handmatige cijfers draagt (er is nog geen run gestart).
ReportStatus = Literal["draft", "pending", "collecting", "writing", "completed", "failed"]
ACTIVE_REPORT_STATUSES: frozenset[str] = frozenset({"pending", "collecting", "writing"})

# De tegels en hun volgorde op het rapportvel; enige plek waar dit vastligt.
MetricKey = Literal["clicks", "top10", "leads", "ai_mentions"]
METRIC_ORDER: tuple[str, ...] = ("clicks", "top10", "leads", "ai_mentions")

# clicks:               ok | not_configured | token_expired | no_property | property_inaccessible
#                       | no_data | error
# top10, ai_mentions:   ok | not_configured | not_tracked | out_of_window | error
# leads:                manual | not_connected
MetricState = Literal[
    "ok",
    "manual",
    "not_connected",
    "not_configured",
    "token_expired",
    "no_property",
    "property_inaccessible",
    "not_tracked",
    "out_of_window",
    "no_data",
    "error",
]
# Toestanden waarbij het cijfer naar de agent gaat en op het vel als getal staat.
USABLE_METRIC_STATES: frozenset[str] = frozenset({"ok", "manual"})

LEADS_MAX = 1_000_000

# --- data: momentopname ----------------------------------------------------------------------


class Period(BaseModel):
    """Periode waarover de Search Console-cijfers gaan (bij een lopende maand korter)."""

    start: str
    end: str
    days: int
    # False = de maand is nog niet (helemaal) beschikbaar in Search Console.
    complete: bool = True


class Metric(BaseModel):
    """Eén cijfertegel. Velden die bij een tegel niet horen blijven `None`."""

    state: MetricState
    message: str | None = None
    value: int | None = None
    previous: int | None = None
    delta: int | None = None
    # Alleen clicks; None als de vorige periode 0 was.
    delta_pct: float | None = None
    # top10: aantal gevolgde zoekwoorden; ai_mentions: aantal prompts.
    total: int | None = None
    # Alleen clicks.
    impressions: int | None = None
    property: str | None = None
    property_source: Literal["manual", "auto"] | None = None
    # top10 en ai_mentions: moment waarop ProRankTracker is uitgelezen.
    captured_at: datetime | None = None
    # Alleen leads: waar `previous` vandaan komt.
    previous_source: Literal["manual", "previous_report"] | None = None


class Metrics(BaseModel):
    clicks: Metric
    top10: Metric
    leads: Metric
    ai_mentions: Metric


class WorkExample(BaseModel):
    title: str
    path: str | None = None


class WorkGroup(BaseModel):
    """Aanpassingen van één onderwerp (bijv. alle meta descriptions) samengenomen."""

    id: str
    topic: str
    label: str
    count: int
    pages: int
    # Aantal dat live is teruggezien; None bij openstaand werk.
    verified: int | None = None
    examples: list[WorkExample] = Field(default_factory=list)


class WorkBlog(BaseModel):
    id: str
    title: str
    published_at: str
    url: str | None = None


class WorkBrief(BaseModel):
    id: str
    keyword: str
    # True = de brief is voor een pagina die nog niet bestaat.
    new_page: bool = False


class QuickWin(BaseModel):
    id: str
    keyword: str
    position: int | None = None
    volume: int | None = None


class Work(BaseModel):
    """Wat er in de maand is gedaan (id's W1, W2, ...)."""

    changes: list[WorkGroup] = Field(default_factory=list)
    blogs: list[WorkBlog] = Field(default_factory=list)
    briefs: list[WorkBrief] = Field(default_factory=list)


class Upcoming(BaseModel):
    """Openstaand werk waaruit de agent "Volgende maand" kiest (id's N1, N2, ...)."""

    approved_changes: list[WorkGroup] = Field(default_factory=list)
    briefs: list[WorkBrief] = Field(default_factory=list)
    quick_wins: list[QuickWin] = Field(default_factory=list)


class ReportData(BaseModel):
    """`monthly_reports.data`."""

    version: int = 1
    month: str
    collected_at: datetime
    # None als Search Console voor deze maand nog niets heeft.
    period: Period | None = None
    previous: Period | None = None
    metrics: Metrics
    work: Work = Field(default_factory=Work)
    upcoming: Upcoming = Field(default_factory=Upcoming)


# --- report: tekst van de agent --------------------------------------------------------------


class ReportItem(BaseModel):
    text: str
    refs: list[str] = Field(default_factory=list)


class ReviewNote(BaseModel):
    """Opmerking voor de specialist. `agent` = door Claude gemeld, `check` = controle in code."""

    text: str
    source: Literal["agent", "check"] = "agent"


class ReportText(BaseModel):
    """`monthly_reports.report`. `version` telt op bij elke nieuwe tekst."""

    version: int = 1
    summary: list[str] = Field(default_factory=list)
    work_done: list[ReportItem] = Field(default_factory=list)
    next_month: list[ReportItem] = Field(default_factory=list)
    review_notes: list[ReviewNote] = Field(default_factory=list)


# --- manual: handmatige cijfers --------------------------------------------------------------


class Manual(BaseModel):
    """`monthly_reports.manual`. Alleen de router schrijft deze kolom."""

    leads: int | None = None
    leads_previous: int | None = None
    updated_by: str | None = None
    updated_at: datetime | None = None


class ManualUpdate(BaseModel):
    """Body van `PATCH .../manual`. `None` wist het cijfer."""

    leads: int | None = Field(default=None, ge=0, le=LEADS_MAX)
    leads_previous: int | None = Field(default=None, ge=0, le=LEADS_MAX)


class Leads(BaseModel):
    """Aanvragen zoals het scherm ze toont; bij elk lezen berekend uit `manual`.

    `previous` is `manual.leads_previous`; is dat leeg, dan `manual.leads` van het rapport van
    de vorige maand (`previous_source = "previous_report"`); anders `None`.
    """

    value: int | None = None
    previous: int | None = None
    previous_source: Literal["manual", "previous_report"] | None = None
    updated_at: datetime | None = None


# --- API -------------------------------------------------------------------------------------


class MonthlyReport(BaseModel):
    """Antwoord van alle endpoints. Zonder rij: `id = None` en `status = "draft"`."""

    id: str | None = None
    customer_website_id: str
    month: str
    status: ReportStatus = "draft"
    error_message: str | None = None
    model: str | None = None
    ai_usage: AiUsage = Field(default_factory=AiUsage)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    leads: Leads = Field(default_factory=Leads)
    # True = de aanvragen zijn gewijzigd nadat de tekst is geschreven.
    text_outdated: bool = False
    data: ReportData | None = None
    report: ReportText | None = None
