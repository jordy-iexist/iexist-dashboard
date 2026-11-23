"""Contract van de concurrentieanalyse per klant.

Drie lagen in één bestand, zodat de worker (schrijver) en de router (lezer) dezelfde vorm
gebruiken:
1. Literal-types en constanten voor statussen, modules en toestanden.
2. De vorm van elke JSON-kolom in de tabellen `competitor_analyses`, `..._keywords`,
   `..._pages` en `..._actions`. Schrijven: `Model(...).model_dump(mode="json")`;
   lezen: `Model.model_validate(waarde)` (een lege kolom is `None`).
3. De request/response-modellen van `/api/competitor-analyses`.

Eenheden en conventies:
- Tijden van pagina's in milliseconden (`lcp_ms`); duur van een analyse in seconden.
- Ahrefs-verbruik in API-units (gehele getallen).
- Claude: werkelijk verbruik (`AiUsage.cost_usd`) in US-dollar, zoals Anthropic factureert;
  de schatting voor de gebruiker (`Estimate.ai_cost_eur`) in euro. `Rates` geeft beide.
- Posities zijn 1-gebaseerd; `None` = niet gevonden of onbekend.
- `country` is een ISO 3166-1 alpha-2-code in kleine letters ("nl"), zoals Ahrefs hem kent.
- `domain_rating` is een geheel getal 0–100 (Ahrefs-DR afgerond).
- Tijdstippen zijn timezone-aware (UTC); `serp_date` is de ISO-tekst zoals Ahrefs hem geeft.
- Medianen worden niet opgeslagen maar bij het lezen berekend (`MedianRow`).
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# --- Statussen en constanten -----------------------------------------------------------------

AnalysisStatus = Literal[
    "pending", "serp", "fetching", "analyzing",
    "completed", "failed", "canceled",
]
ACTIVE_STATUSES = {"pending", "serp", "fetching", "analyzing"}
FINAL_STATUSES = {"completed", "failed", "canceled"}

# Per zoekwoord: `pending` zolang de run ermee bezig is; `failed` als alleen dit zoekwoord
# mislukte (bijv. een Ahrefs-fout), de rest van de analyse loopt door.
KeywordStatus = Literal["pending", "completed", "failed"]

# De zes vinkjes onder "Wat analyseren?" in de wizard.
Module = Literal["serp", "onpage", "topics", "authority", "tech", "eeat"]
ALL_MODULES: tuple[Module, ...] = ("serp", "onpage", "topics", "authority", "tech", "eeat")
MODULE_LABELS: dict[str, str] = {
    "serp": "Zoekintentie & SERP-features",
    "onpage": "On-page & structuur",
    "topics": "Onderwerpdekking (AI)",
    "authority": "Autoriteit & backlinks",
    "tech": "Techniek",
    "eeat": "E-E-A-T-signalen",
}

# Toestand van een databron (ook van de Google-poging per zoekwoord).
SourceState = Literal["ok", "not_configured", "error", "blocked", "skipped", "empty"]
SourceKey = Literal["ahrefs", "prt", "pagespeed", "claude", "google"]
SOURCE_KEYS: tuple[SourceKey, ...] = ("ahrefs", "prt", "pagespeed", "claude", "google")

# Toestand van de AI-stap per zoekwoord.
AiState = Literal["ok", "not_configured", "error", "skipped"]

# Uitkomst van het ophalen van één pagina; `None` in de kolom = nog niet opgehaald.
FetchStatus = Literal["ok", "blocked", "not_html", "error"]

# Eigen paginatype-indeling (aanroep A); `ahrefs_page_type` bewaart de ruwe Ahrefs-waarde.
PageType = Literal["dienst", "product", "categorie", "blog", "vergelijker", "homepage", "overig"]

# Waarom een pagina niet meetelt in de medianen.
ExcludeReason = Literal["aggregator", "own_site"]

Level = Literal["hoog", "middel", "laag"]

# Herkomst van de eigen positie.
PositionSource = Literal["prt", "ahrefs"]

TopN = Literal[3, 5, 10, 20]
TOP_N_OPTIONS: tuple[int, ...] = (3, 5, 10, 20)

CwvSource = Literal["lab", "field"]
MissingTopicKind = Literal["topic", "question"]

# Metrieken in de vergelijkingstabel waarop de eigen pagina een rode vlag kan krijgen.
FlagMetric = Literal["words", "h2_count", "faq", "schema", "refdomains", "domain_rating", "lcp_ms"]
FLAG_METRICS: tuple[FlagMetric, ...] = (
    "words", "h2_count", "faq", "schema", "refdomains", "domain_rating", "lcp_ms",
)

MAX_HEADINGS = 60


# --- Vorm van de JSON-kolommen ---------------------------------------------------------------


class Heading(BaseModel):
    """Eén kop van een pagina (H1–H6) in documentvolgorde."""

    level: int = Field(..., ge=1, le=6)
    text: str


class OnPage(BaseModel):
    """`competitor_analysis_pages.onpage`: uitgelezen on-page-kenmerken (uit `extract_content`)."""

    title: str | None = None
    meta_description: str | None = None
    h1: str | None = None
    h2_count: int = 0
    h3_count: int = 0
    # Hooguit MAX_HEADINGS; langere lijsten worden afgekapt in plaats van geweigerd.
    headings: list[Heading] = Field(default_factory=list)
    word_count: int = 0
    internal_links: int = 0
    images: int = 0
    has_faq: bool = False
    schema_types: list[str] = Field(default_factory=list)

    @field_validator("headings", mode="before")
    @classmethod
    def _cap_headings(cls, value: object) -> object:
        if isinstance(value, list):
            return value[:MAX_HEADINGS]
        return value


class Eeat(BaseModel):
    """`competitor_analysis_pages.eeat`: E-E-A-T-signalen op een pagina volgens aanroep B."""

    team: bool = False
    cases: bool = False
    reviews: bool = False
    certifications: bool = False
    note: str | None = None


class Cwv(BaseModel):
    """`competitor_analysis_pages.cwv`: LCP-meting (mobiel); `error` bijv. "niet op tijd gemeten"."""

    lcp_ms: int | None = None
    source: CwvSource | None = None
    error: str | None = None


class Paa(BaseModel):
    """`competitor_analysis_keywords.paa`: "Mensen vragen ook" uit de Google-poging."""

    state: SourceState
    questions: list[str] = Field(default_factory=list)


class AiOverviewSource(BaseModel):
    """Eén bron die in de AI Overview wordt genoemd."""

    domain: str
    url: str | None = None


class AiOverview(BaseModel):
    """`competitor_analysis_keywords.ai_overview`: AI Overview-bronnen; `own_cited` None = onbekend."""

    state: SourceState
    sources: list[AiOverviewSource] = Field(default_factory=list)
    own_cited: bool | None = None


class MissingTopic(BaseModel):
    """Element van `competitor_analysis_keywords.missing_topics`: onderwerp dat de eigen pagina mist.

    `covered` = aantal meegetelde concurrenten dat het behandelt, `total` = aantal meegetelde
    concurrenten (geteld door de code, niet door het model).
    """

    topic: str
    kind: MissingTopicKind = "topic"
    covered: int = 0
    total: int = 0


class SourceStatus(BaseModel):
    """Toestand van één databron met een korte toelichting voor de gebruiker."""

    state: SourceState
    message: str | None = None


def _skipped() -> SourceStatus:
    return SourceStatus(state="skipped")


class Sources(BaseModel):
    """`competitor_analyses.sources` en `ProposalResponse.sources`: toestand per databron."""

    ahrefs: SourceStatus = Field(default_factory=_skipped)
    prt: SourceStatus = Field(default_factory=_skipped)
    pagespeed: SourceStatus = Field(default_factory=_skipped)
    claude: SourceStatus = Field(default_factory=_skipped)
    google: SourceStatus = Field(default_factory=_skipped)


class Estimate(BaseModel):
    """`competitor_analyses.estimate`: schatting vooraf (pagina's, seconden, units, euro)."""

    pages: int = 0
    seconds: int = 0
    ahrefs_units: int = 0
    ai_cost_eur: float = 0.0


class AiUsage(BaseModel):
    """`competitor_analyses.ai_usage`: werkelijk Claude-verbruik van de run (kosten in USD)."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


# --- Voorstel voor de wizard -----------------------------------------------------------------


class ProposalKeyword(BaseModel):
    """Voorgesteld zoekwoord met de rankende URL en positie van de klant."""

    keyword: str
    url: str | None = None
    position: int | None = None
    volume: int | None = None
    source: PositionSource


class ProposalDefaults(BaseModel):
    """Beginwaarden van de wizard."""

    country: str
    top_n: TopN = 10
    exclude_aggregators: bool = True
    modules: list[Module] = Field(default_factory=lambda: list(ALL_MODULES))


class Rates(BaseModel):
    """Tarieven voor de schatting in de wizard (uit `services/estimate.py`)."""

    # Ahrefs-units voor het SERP-overzicht: per opgevraagde positie. Ahrefs telt SERP-blokken
    # (AI Overview, vragen, sitelinks) mee als positie, dus er worden `top_n + serp_extra_positions`
    # posities opgevraagd: units = (top_n + serp_extra_positions) * ahrefs_units_per_serp_position.
    ahrefs_units_per_serp_position: float
    serp_extra_positions: int
    # Ahrefs-units per zoekwoord (volume/KD/intentie) en per URL (DR/RD van de eigen doelpagina).
    ahrefs_units_per_keyword: int
    ahrefs_units_per_url: int
    # Ahrefs rekent minimaal dit aantal units per aanvraag. Zoekwoordgegevens en URL-metrics gaan
    # elk in één aanvraag per analyse: units = max(minimum, aantal * tarief), 0 bij aantal 0.
    ahrefs_min_units_per_request: int
    # Claude per geanalyseerde pagina en per zoekwoord, in USD en in EUR.
    claude_usd_per_page: float
    claude_eur_per_page: float
    claude_usd_per_keyword: float
    claude_eur_per_keyword: float
    # Doorlooptijd per pagina (ophalen, uitlezen, meten) en vaste tijd per zoekwoord
    # (SERP, Google-poging, aanroep B).
    seconds_per_page: float
    seconds_per_keyword: float


class ProposalResponse(BaseModel):
    """`GET /customers/{cid}/proposal`: alles wat de wizard nodig heeft, zonder betaalde aanroep."""

    sources: Sources
    keywords: list[ProposalKeyword]
    # Unieke rankende URL's van de klant voor de keuzelijst "doelpagina".
    pages: list[str]
    defaults: ProposalDefaults
    rates: Rates
    max_keywords: int


# --- Starten ---------------------------------------------------------------------------------


class KeywordInput(BaseModel):
    """Eén zoekwoord uit de wizard; `target_url` None = er komt een nieuwe pagina."""

    keyword: str = Field(..., min_length=1, max_length=200)
    target_url: str | None = None

    @field_validator("keyword")
    @classmethod
    def _strip_keyword(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Zoekwoord is leeg.")
        return value

    @field_validator("target_url")
    @classmethod
    def _blank_url_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class AnalysisCreateRequest(BaseModel):
    """`POST /customers/{cid}/analyses`.

    Het maximum aantal zoekwoorden en het klantdomein van de doel-URL's controleert de router
    (400 met een leesbare melding), niet dit model.
    """

    keywords: list[KeywordInput] = Field(..., min_length=1)
    country: str = Field(..., min_length=2, max_length=2)
    top_n: TopN = 10
    exclude_aggregators: bool = True
    modules: list[Module] = Field(default_factory=lambda: list(ALL_MODULES), min_length=1)

    @field_validator("country")
    @classmethod
    def _lower_country(cls, value: str) -> str:
        value = value.strip().lower()
        if not value.isalpha():
            raise ValueError("Land moet een landcode van twee letters zijn.")
        return value

    @field_validator("modules")
    @classmethod
    def _unique_modules(cls, value: list[str]) -> list[str]:
        # Ontdubbelen in de vaste volgorde van ALL_MODULES.
        return [module for module in ALL_MODULES if module in value]


# --- Lijst -----------------------------------------------------------------------------------


class AnalysisListItem(BaseModel):
    """Eén analyse in de lijst en op de kaart "Recente analyses"."""

    id: str
    status: AnalysisStatus
    created_at: datetime
    completed_at: datetime | None = None
    top_n: int
    # Zoekwoorden in de volgorde van de wizard.
    keywords: list[str]
    total_keywords: int


class AnalysisListResponse(BaseModel):
    """`GET /customers/{cid}/analyses`: nieuwste eerst."""

    items: list[AnalysisListItem]


# --- Detail van een run ----------------------------------------------------------------------


class KeywordSummary(BaseModel):
    """Zoekwoord in de zoekwoordkiezer bovenaan het resultaat."""

    id: str
    keyword: str
    target_url: str | None = None
    status: KeywordStatus
    error_message: str | None = None
    own_position: int | None = None
    volume: int | None = None
    kd: int | None = None
    ai_state: AiState | None = None


class AnalysisDetail(BaseModel):
    """`GET /analyses/{id}`, ook het antwoord op starten en annuleren: status, tellers, instellingen."""

    id: str
    customer_website_id: str
    status: AnalysisStatus
    error_message: str | None = None
    warnings: list[str] = Field(default_factory=list)
    # Instellingen
    country: str
    top_n: int
    exclude_aggregators: bool
    modules: list[Module]
    # Voortgang
    total_keywords: int
    done_keywords: int
    total_pages: int
    fetched_pages: int
    failed_pages: int
    vitals_total: int
    vitals_measured: int
    # Bronnen, schatting en werkelijk verbruik
    sources: Sources
    estimate: Estimate | None = None
    ahrefs_units: int
    ai_usage: AiUsage | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    keywords: list[KeywordSummary]


# --- Resultaat per zoekwoord -----------------------------------------------------------------


class PageRow(BaseModel):
    """Eén rij in de tabel "Jij vs. de top X"."""

    id: str
    position: int | None = None
    url: str
    domain: str | None = None
    serp_title: str | None = None
    page_type: PageType | None = None
    is_excluded: bool = False
    exclude_reason: ExcludeReason | None = None
    fetch_status: FetchStatus | None = None
    fetch_error: str | None = None
    # Woorden op de pagina (`OnPage.word_count`); None als de pagina niet is uitgelezen.
    words: int | None = None
    h2_count: int | None = None
    has_faq: bool | None = None
    schema_types: list[str] = Field(default_factory=list)
    refdomains: int | None = None
    domain_rating: int | None = None
    lcp_ms: int | None = None
    # Waarom er geen LCP is (bijv. "niet op tijd gemeten"), uit `Cwv.error`.
    lcp_error: str | None = None
    eeat: Eeat | None = None
    # Minder dan 50 woorden: "mogelijk niet leesbaar", telt niet mee in de medianen.
    unreadable: bool = False


class OwnPageRow(PageRow):
    """De eigen doelpagina, met per metriek of hij duidelijk onder de mediaan zit (rood)."""

    flags: dict[FlagMetric, bool] = Field(default_factory=dict)


class MedianRow(BaseModel):
    """Mediaanrij over de meegetelde concurrenten; None = te weinig waarden ("—")."""

    words: float | None = None
    h2_count: float | None = None
    refdomains: float | None = None
    domain_rating: float | None = None
    lcp_ms: float | None = None
    # Aantal meegetelde concurrenten met FAQ en met schema, en het meest voorkomende schema-type.
    faq_count: int = 0
    schema_count: int = 0
    schema_top: str | None = None
    # Aantal meegetelde concurrenten (niet uitgesloten, opgehaald en leesbaar).
    total: int = 0


class ActionItem(BaseModel):
    """Verbeterpunt; ook het antwoord op `PATCH /actions/{action_id}`."""

    id: str
    title: str
    description: str | None = None
    impact: Level | None = None
    effort: Level | None = None
    category: Module | None = None
    done: bool = False
    done_by_name: str | None = None
    done_at: datetime | None = None


class KeywordDetail(BaseModel):
    """`GET /analyses/{id}/keywords/{kid}`: volledig resultaat van één zoekwoord."""

    id: str
    analysis_id: str
    keyword: str
    target_url: str | None = None
    status: KeywordStatus
    error_message: str | None = None
    own_position: int | None = None
    own_position_source: PositionSource | None = None
    volume: int | None = None
    kd: int | None = None
    # Namen van de actieve Ahrefs-intenties (bijv. "commercial") en SERP-featuretypes.
    intents: list[str] = Field(default_factory=list)
    serp_features: list[str] = Field(default_factory=list)
    serp_date: str | None = None
    serp_summary: str | None = None
    search_intent: str | None = None
    ai_state: AiState | None = None
    ai_error: str | None = None
    # Concurrenten in SERP-volgorde (zonder de eigen pagina).
    pages: list[PageRow]
    # None als er geen doelpagina is (nieuwe pagina).
    own: OwnPageRow | None = None
    median: MedianRow
    actions: list[ActionItem]
    missing_topics: list[MissingTopic]
    paa: Paa | None = None
    ai_overview: AiOverview | None = None


class ActionUpdate(BaseModel):
    """`PATCH /actions/{action_id}`: verbeterpunt afvinken of weer openzetten."""

    done: bool


__all__ = [
    "ACTIVE_STATUSES",
    "ALL_MODULES",
    "FINAL_STATUSES",
    "FLAG_METRICS",
    "MAX_HEADINGS",
    "MODULE_LABELS",
    "SOURCE_KEYS",
    "TOP_N_OPTIONS",
    "ActionItem",
    "ActionUpdate",
    "AiOverview",
    "AiOverviewSource",
    "AiState",
    "AiUsage",
    "AnalysisCreateRequest",
    "AnalysisDetail",
    "AnalysisListItem",
    "AnalysisListResponse",
    "AnalysisStatus",
    "Cwv",
    "CwvSource",
    "Eeat",
    "Estimate",
    "ExcludeReason",
    "FetchStatus",
    "FlagMetric",
    "Heading",
    "KeywordDetail",
    "KeywordInput",
    "KeywordStatus",
    "KeywordSummary",
    "Level",
    "MedianRow",
    "MissingTopic",
    "MissingTopicKind",
    "Module",
    "OnPage",
    "OwnPageRow",
    "PageRow",
    "PageType",
    "Paa",
    "PositionSource",
    "ProposalDefaults",
    "ProposalKeyword",
    "ProposalResponse",
    "Rates",
    "SourceKey",
    "SourceState",
    "SourceStatus",
    "Sources",
    "TopN",
]
