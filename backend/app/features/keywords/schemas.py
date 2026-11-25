"""Contract van het scherm Zoekwoorden › Concurrenten (per klant).

Eén bestand voor de ophaler (`services/collect.py`), de rekenregels (`services/compute.py`),
Claude (`services/ai.py`), de worker en de router, zodat ze dezelfde vorm gebruiken:
1. Literal-types en constanten.
2. De vorm van de JSON-kolommen van `customer_competitor_overviews`: `raw` (`Raw`, ruwe
   Ahrefs- en PRT-gegevens, voor hergebruik), `data` (`Snapshot`, de berekende momentopname)
   en `overrides` (`Overrides`, handmatige keuzes). Schrijven: `Model(...).model_dump(mode="json")`;
   lezen: `Model.model_validate(waarde)` (een lege kolom is `None`).
3. De tussenvormen tussen de stappen (`Candidate`, `DomainClass`, `TopicAssignment`).
4. De request/response-modellen van `/api/keywords`.
5. Onderaan: de afgesproken functies per module (wie roept wat aan).

Conventies:
- Een domein is altijd een kale host in kleine letters zonder `www.` (`rankings.host_of`).
- Zoekwoorden worden vergeleken met `rankings.keyword_key`; de getoonde tekst is de eerste
  schrijfwijze die binnenkwam.
- Percentages zijn 0–100 (`overlap_pct` met één decimaal, celpercentages hele getallen).
- Tijdstippen zijn timezone-aware (UTC). Ahrefs in units, Claude-verbruik in USD.
- `overrides` schrijft alleen de router; de worker schrijft `raw`, `data` en de statusvelden.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.features.competitor_analysis.schemas import AiUsage

# --- Statussen en constanten -----------------------------------------------------------------

# idle = nog nooit opgehaald (geen rij, of een rij die alleen handmatige keuzes draagt).
OverviewStatus = Literal[
    "idle", "pending", "collecting", "classifying", "summarizing", "completed", "failed"
]
ACTIVE_OVERVIEW_STATUSES: frozenset[str] = frozenset(
    {"pending", "collecting", "classifying", "summarizing"}
)

CompetitorType = Literal["landelijk", "regio", "lokaal"]
# ahrefs = organische concurrenten; tracked = gevonden via de gevolgde zoekwoorden; manual = toegevoegd.
CompetitorOrigin = Literal["ahrefs", "tracked", "manual"]
# Waar Gedeeld en Overlap op gebaseerd zijn; één basis per momentopname.
OverlapBasis = Literal["ahrefs", "tracked"]
RefreshMode = Literal["full", "reuse"]

# Waarom ophalen niet kan (POST refresh geeft dan 400).
BlockedReason = Literal["ahrefs_not_configured", "no_website"]

# ahrefs:  ok | not_configured | error
# prt:     ok | not_configured | not_tracked | error
# claude:  ok | not_configured | error
# profile: ok | empty
SourceState = Literal["ok", "not_configured", "not_tracked", "empty", "error"]
# competitors: ok | empty | not_configured | error
# heatmap:     ok | no_profile | no_keywords | not_configured | error
# summary:     ok | not_configured | error | skipped (geen concurrenten om over te schrijven)
SectionState = Literal[
    "ok", "empty", "no_profile", "no_keywords", "not_configured", "skipped", "error"
]

COUNTRY = "nl"
TOP_COMPETITORS = 5  # "de vijf": kolommen van de heatmap en basis van de KPI's
MAX_MANUAL_COMPETITORS = 10
MAX_EXCLUDED_SHOWN = 5
CANDIDATE_LIMIT = 20  # rijen uit organic-competitors
MIN_SHARED_KEYWORDS = 5  # daaronder telt een Ahrefs-kandidaat niet als bruikbaar
TRACKED_SAMPLE_MAX = 10  # SERP's voor de aanvulling via gevolgde zoekwoorden
TRACKED_SAMPLE_MIN = 3
TRACKED_CANDIDATES_MAX = 15
TRACKED_KEYWORDS_MAX = 150  # gevolgde zoekwoorden in de verzameling van de heatmap
UNIVERSE_MAX = 600
MIN_TOPIC_KEYWORDS = 5  # daaronder toont een onderwerp "te weinig zoekwoorden"
LOCAL_TOPIC = "Lokaal"
SUMMARY_POINTS = 3
# Ondergrenzen van de vier tinten (level 0..3): 0–9, 10–24, 25–49, ≥50 procent.
HEAT_LEVEL_MIN: tuple[int, ...] = (0, 10, 25, 50)

# Gemeten op het gratis testdomein ahrefs.com (25-11-2026), units per rij:
# organic-competitors 6 (zes velden zonder traffic), organic-keywords 2 met alleen
# keyword+best_position en ZONDER order_by (standaardvolgorde is dan op verkeer; een order_by
# op volume of sum_traffic maakt het 12), batch-analysis 14 met org_traffic, metrics-history 11.
# Elke aanvraag kost minimaal 50 units.
UNITS_MIN_PER_REQUEST = 50
UNITS_PER_COMPETITOR_ROW = 6
UNITS_PER_KEYWORD_ROW = 2
UNITS_PER_METRICS_ROW = 14
UNITS_PER_HISTORY_ROW = 11
UNITS_PER_SERP_ROW = 5  # schatting voor de smalle selectie; de werkelijke kosten staan in de header

# --- overrides: handmatige keuzes ------------------------------------------------------------


class ManualDomain(BaseModel):
    domain: str
    added_by: str
    added_at: datetime


class DomainChoice(BaseModel):
    """Keuze van de gebruiker voor één domein; `None` = het oordeel van Claude volgen."""

    type: CompetitorType | None = None
    excluded: bool | None = None


class Overrides(BaseModel):
    manual: list[ManualDomain] = Field(default_factory=list)
    domains: dict[str, DomainChoice] = Field(default_factory=dict)


# --- raw: ruwe gegevens ----------------------------------------------------------------------


class TrackedKeyword(BaseModel):
    """Gevolgd zoekwoord uit ProRankTracker; `rank` is None buiten de top 100."""

    keyword: str
    rank: int | None = None
    volume: int | None = None


class RawPrt(BaseModel):
    state: SourceState = "not_configured"
    message: str | None = None
    rows: list[TrackedKeyword] = Field(default_factory=list)


class RawCompetitor(BaseModel):
    """Rij uit Ahrefs organic-competitors; `share` is een percentage (bijv. 8.4)."""

    domain: str
    domain_rating: float | None = None
    keywords_common: int = 0
    keywords_competitor: int = 0
    keywords_target: int = 0
    share: float = 0.0


class SerpHit(BaseModel):
    """Organisch resultaat in de top 10 van één steekproef-SERP."""

    domain: str
    position: int
    title: str | None = None


class RawMetrics(BaseModel):
    """Rij uit Ahrefs batch-analysis voor één domein."""

    domain_rating: float | None = None
    org_keywords: int | None = None
    org_keywords_1_3: int | None = None
    org_keywords_4_10: int | None = None
    org_traffic: int | None = None


class TrafficPoint(BaseModel):
    date: str  # "2026-10-01"
    org_traffic: int


class RawTop10(BaseModel):
    """Zoekwoorden waarop een domein volgens Ahrefs in de top 10 staat.

    `truncated`: de lijst haalde de rijlimiet, er zijn er dus meer. `checked`: zoekwoorden die
    daarna los zijn nagevraagd (de nacontrole); wat daarvan in de top 10 staat is aan
    `keywords` toegevoegd. Een afgekapt domein telt in de heatmap alleen als volledig voor
    zoekwoorden uit `keywords` of `checked`.
    """

    keywords: list[str] = Field(default_factory=list)
    truncated: bool = False
    checked: list[str] = Field(default_factory=list)


class Raw(BaseModel):
    """Alles wat een verversing ophaalt; onderdelen die ontbreken zijn (nog) niet opgehaald."""

    fetched_at: datetime | None = None
    prt: RawPrt | None = None
    competitors: list[RawCompetitor] | None = None  # stap A + A2
    # stap B: zoekwoord -> organische top 10; None = de aanvulling heeft niet gedraaid.
    serps: dict[str, list[SerpHit]] | None = None
    metrics: dict[str, RawMetrics] = Field(default_factory=dict)  # stap D, per domein
    traffic_history: list[TrafficPoint] | None = None  # stap E, oplopend op datum
    top10: dict[str, RawTop10] = Field(default_factory=dict)  # stap F + nacontrole, per domein


# --- tussenvormen ----------------------------------------------------------------------------


class Candidate(BaseModel):
    """Kandidaat-concurrent vóór de indeling door Claude en vóór de cijfers per domein."""

    domain: str
    origin: CompetitorOrigin
    domain_rating: float | None = None
    shared: int = 0
    overlap_pct: float = 0.0
    titles: list[str] = Field(default_factory=list)  # paginatitels uit de steekproef-SERP's


class DomainClass(BaseModel):
    """Oordeel van Claude over één domein."""

    type: CompetitorType
    is_aggregator: bool = False
    reason: str = ""


class TopicAssignment(BaseModel):
    """Indeling van zoekwoorden door Claude; sleutels zijn onderwerpnamen (dienstnamen).

    Een zoekwoord staat bij hoogstens één dienst; `local` staat daar los van. Zoekwoorden die
    nergens bij passen ontbreken.
    """

    services: dict[str, list[str]] = Field(default_factory=dict)
    local: list[str] = Field(default_factory=list)


# --- data: momentopname ----------------------------------------------------------------------


class SourceInfo(BaseModel):
    state: SourceState
    message: str | None = None


class Sources(BaseModel):
    ahrefs: SourceInfo
    prt: SourceInfo
    claude: SourceInfo
    profile: SourceInfo


class SnapshotCompetitor(BaseModel):
    """Concurrent in de momentopname, met het oordeel van Claude (nog zonder handmatige keuzes).

    `in_top5` is berekend mét de keuzes die golden toen de run startte.
    """

    domain: str
    origin: CompetitorOrigin
    ai_type: CompetitorType | None = None  # None = Claude gaf geen oordeel
    ai_is_aggregator: bool = False
    ai_reason: str | None = None
    in_top5: bool = False
    domain_rating: float | None = None
    organic_keywords: int | None = None
    top10_keywords: int | None = None
    traffic: int | None = None
    shared: int = 0
    overlap_pct: float = 0.0


class KeywordKpi(BaseModel):
    value: int | None = None
    top10: int | None = None


class TrafficKpi(BaseModel):
    value: int | None = None
    change_pct: float | None = None  # t.o.v. de vorige maand; None = onbekend


class DomainRatingKpi(BaseModel):
    value: float | None = None
    competitor_median: float | None = None


class OverlapKpi(BaseModel):
    pct: float | None = None  # gemiddelde overlap met de vijf
    shared_avg: int | None = None


class Kpis(BaseModel):
    organic_keywords: KeywordKpi
    organic_traffic: TrafficKpi
    domain_rating: DomainRatingKpi
    top5_overlap: OverlapKpi


class HeatmapColumn(BaseModel):
    domain: str
    is_customer: bool = False
    truncated: bool = False  # lijst afgekapt: het aandeel kan hoger zijn


class HeatmapCell(BaseModel):
    pct: int
    level: int  # 0..3, zie HEAT_LEVEL_MIN


class HeatmapRow(BaseModel):
    """`cells` loopt gelijk met `Heatmap.columns`; leeg bij minder dan MIN_TOPIC_KEYWORDS."""

    topic: str
    kind: Literal["service", "local"]
    keywords: int
    cells: list[HeatmapCell] = Field(default_factory=list)


class HeatmapUniverse(BaseModel):
    total: int = 0  # zoekwoorden die naar Claude gingen
    tracked: int = 0  # waarvan gevolgd in ProRankTracker
    assigned: int = 0  # door Claude bij een onderwerp ingedeeld


class Heatmap(BaseModel):
    state: SectionState
    message: str | None = None
    columns: list[HeatmapColumn] = Field(default_factory=list)
    rows: list[HeatmapRow] = Field(default_factory=list)
    universe: HeatmapUniverse = Field(default_factory=HeatmapUniverse)


class Summary(BaseModel):
    state: SectionState
    message: str | None = None
    paragraph: str | None = None
    points: list[str] = Field(default_factory=list)  # precies SUMMARY_POINTS bij state ok


class Snapshot(BaseModel):
    overlap_basis: OverlapBasis = "ahrefs"
    tracked_sample: int = 0  # aantal steekproef-SERP's bij basis "tracked"
    warnings: list[str] = Field(default_factory=list)
    sources: Sources
    kpis: Kpis | None = None
    competitors_state: SectionState = "ok"
    competitors_message: str | None = None
    competitors: list[SnapshotCompetitor] = Field(default_factory=list)
    heatmap: Heatmap
    summary: Summary


# --- API: /api/keywords ----------------------------------------------------------------------


class RefreshRequest(BaseModel):
    mode: RefreshMode = "full"


class DomainRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=255)


class ChoiceRequest(BaseModel):
    """`None` = terug naar het oordeel van Claude. Beide velden worden altijd overschreven."""

    domain: str = Field(min_length=1, max_length=255)
    type: CompetitorType | None = None
    excluded: bool | None = None


class CompetitorRow(BaseModel):
    """Rij in de tabel, met de handmatige keuzes toegepast."""

    domain: str
    origin: CompetitorOrigin
    type: CompetitorType | None = None
    type_source: Literal["ai", "manual"] | None = None
    excluded: bool = False
    excluded_source: Literal["ai", "manual"] | None = None
    exclude_reason: str | None = None  # bijv. "vergelijkingssite" of "handmatig uitgesloten"
    in_top5: bool = False
    # Handmatig toegevoegd na de laatste run: nog geen cijfers, eerst "Bijwerken".
    pending: bool = False
    domain_rating: float | None = None
    organic_keywords: int | None = None
    top10_keywords: int | None = None
    traffic: int | None = None
    shared: int = 0
    overlap_pct: float = 0.0


class CompetitorsSection(BaseModel):
    state: SectionState
    message: str | None = None
    # Meetellende concurrenten op overlap aflopend, daarna de uitgesloten.
    rows: list[CompetitorRow] = Field(default_factory=list)


class CompetitorOverview(BaseModel):
    """Antwoord van alle endpoints. Zonder momentopname zijn `kpis` None en de secties leeg."""

    status: OverviewStatus
    error_message: str | None = None
    customer_id: str
    domain: str | None = None
    country: str = COUNTRY
    fetched_at: datetime | None = None
    expires_at: datetime | None = None
    units: int = 0  # Ahrefs-units van de laatste run
    unit_cap: int = 0
    unit_estimate: int = 0  # schatting voor een volledige verversing (voor de knop)
    # Er zijn keuzes gemaakt sinds de laatste run die de vijf raken: toon "Bijwerken".
    dirty: bool = False
    blocked_reason: BlockedReason | None = None
    blocked_message: str | None = None
    warnings: list[str] = Field(default_factory=list)
    overlap_basis: OverlapBasis = "ahrefs"
    tracked_sample: int = 0
    sources: Sources | None = None
    kpis: Kpis | None = None
    competitors: CompetitorsSection
    heatmap: Heatmap
    summary: Summary
    ai_usage: AiUsage | None = None
    model: str | None = None


# --- Afgesproken functies per module ---------------------------------------------------------
#
# services/collect.py (ophalen; elke Ahrefs-aanroep loopt via het budget)
#   class UnitBudget:
#       def __init__(self, cap: int): ...
#       spent: int                      # werkelijk verbruikte units
#       skipped: list[str]              # Nederlandse omschrijving van elke overgeslagen stap
#       def allows(self, estimate: int) -> bool
#       def add(self, units: int) -> None
#   def collect_candidates(*, base_url: str, country: str, manual_domains: list[str],
#                          previous: Raw | None, budget: UnitBudget) -> Raw
#       Stap 0 (PRT), A, A2 en zo nodig B. `previous` is alleen gevuld bij mode "reuse" en dan
#       al jong genoeg: neem over wat erin staat en haal alleen op wat ontbreekt. Gooit
#       `AhrefsServiceError` als stap A zelf mislukt; PRT-fouten komen in `Raw.prt.state`.
#   def collect_metrics(raw: Raw, *, base_url: str, country: str, domains: list[str],
#                       keyword_domains: list[str], budget: UnitBudget) -> Raw
#       Stap D voor klant + `domains`, stap E voor de klant, stap F voor klant +
#       `keyword_domains` (leeg = stap F overslaan). Slaat over wat al in `raw` staat.
#   def collect_keyword_checks(raw: Raw, *, base_url: str, country: str, keywords: list[str],
#                              budget: UnitBudget) -> Raw
#       Nacontrole: voor elk afgekapt domein in `raw.top10` de `keywords` navragen die nog niet
#       in zijn lijst of `checked` staan.
#
# services/compute.py (puur, geen I/O)
#   def candidates(raw: Raw, *, customer_domain: str, manual_domains: list[str]) -> list[Candidate]
#   def overlap_basis(raw: Raw) -> OverlapBasis
#   def select_top5(items: list[Candidate], classes: dict[str, DomainClass],
#                   overrides: Overrides) -> list[str]
#   def shown_excluded(items: list[Candidate], classes: dict[str, DomainClass],
#                      overrides: Overrides) -> list[str]         # max MAX_EXCLUDED_SHOWN
#   def keyword_universe(raw: Raw, *, customer_domain: str, top5: list[str]) -> list[str]
#   def build_snapshot(raw: Raw, *, customer_domain: str, items: list[Candidate],
#                      classes: dict[str, DomainClass], top5: list[str], overrides: Overrides,
#                      topics: list[str], assignment: TopicAssignment | None,
#                      heatmap: Heatmap | None, sources: Sources,
#                      warnings: list[str]) -> Snapshot
#       `heatmap` meegeven = die overnemen (no_profile, not_configured, error); None = berekenen
#       uit `topics` + `assignment`. `summary` komt terug als state "skipped"; de worker vult
#       die na de derde Claude-aanroep.
#   def unit_estimate(*, with_heatmap: bool) -> int
#
# services/ai.py (Claude via `app.services.anthropic.parse_structured`)
#   def classify_domains(items: list[Candidate], *, customer_domain: str, company_type: str,
#                        service_area: str) -> tuple[dict[str, DomainClass], dict, str | None]
#   def assign_keywords(keywords: list[str], topics: list[str], *, company_type: str,
#                       service_area: str) -> tuple[TopicAssignment, dict, str | None]
#   def summarize(snapshot: Snapshot, *, customer_name: str) -> tuple[Summary, dict, str | None]
#       Elk geeft (resultaat, usage, model) terug en gooit `AnthropicServiceError`.
