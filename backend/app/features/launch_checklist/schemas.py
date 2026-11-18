from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ScanStatus = Literal[
    "pending", "discovering", "inventory", "vitals", "analyzing",
    "fetching", "linking", "checking",
    "completed", "failed", "canceled",
]
IssueStatus = Literal["open", "doorgezet", "opgelost", "genegeerd"]
ACTIVE_STATUSES = {"pending", "discovering", "inventory", "vitals", "analyzing", "fetching", "linking", "checking"}
ManualStatus = Literal["open", "afgerond", "nvt"]


class LaunchScanCreateRequest(BaseModel):
    customer_website_id: str = Field(..., min_length=1)
    max_pages: int = Field(default=500, ge=1, le=2000)
    vitals_max_pages: int = Field(default=100, ge=0, le=500)


class LaunchScanItem(BaseModel):
    id: str
    customer_website_id: str
    phase: int
    source_scan_id: str | None = None
    status: ScanStatus
    base_url: str
    discovery_source: str | None = None
    total_urls: int
    inventoried_urls: int
    failed_urls: int
    max_pages: int
    vitals_max_pages: int
    vitals_total: int
    vitals_measured: int
    # Fase 4: ronde (kwartaal), bijv. "2026-Q4".
    period: str | None = None
    summary_stats: Any = None
    warnings: Any = None
    error_message: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class LaunchScanDetail(LaunchScanItem):
    ai_checks: Any = None
    # Ahrefs-snapshot: {target, country, fetched_at, reused_from, units, domain, errors, ...}
    ahrefs: Any = None
    # ProRankTracker-snapshot (fase 1, 2 en 4): {state, message, fetched_at, url_id, url,
    # totals, platforms, prompts, errors}; None voor scans van vóór de koppeling.
    proranktracker: Any = None
    ai_summary: str | None = None
    agent_trace: Any = None


# --- ProRankTracker: promptdetail (live) ----------------------------------------------

PrtPlatform = Literal["aio", "aim", "chatgpt", "gemini", "copilot", "perplexity"]


class PrtMentionItem(BaseModel):
    brand: str
    sentence: str


class PrtMentions(BaseModel):
    rank: int | None = None
    total: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    items: list[PrtMentionItem] = Field(default_factory=list)


class PrtLinkItem(BaseModel):
    url: str
    title: str | None = None
    rank: int | None = None
    kind: Literal["link", "citation"] | None = None
    checked_at: str | None = None
    is_own: bool = False


class PrtLinks(BaseModel):
    rank: int | None = None
    total: int = 0
    items: list[PrtLinkItem] = Field(default_factory=list)


class PrtPlatformDetail(BaseModel):
    platform: PrtPlatform
    label: str
    tracked: bool
    mentions: PrtMentions
    links: PrtLinks
    answer_text: str | None = None


class PrtPromptDetail(BaseModel):
    prompt_id: int
    prompt: str
    url: str | None = None
    fetched_at: str
    platforms: list[PrtPlatformDetail]


class LaunchScanListResponse(BaseModel):
    items: list[LaunchScanItem]
    total: int


class LaunchCustomerItem(BaseModel):
    id: str
    name: str
    base_url: str
    domain: str
    category_name: str | None = None
    latest_scan: LaunchScanItem | None = None
    latest_geo_scan: LaunchScanItem | None = None
    checklist_progress: "ChecklistProgress | None" = None
    latest_content_scan: LaunchScanItem | None = None
    content_progress: "ChecklistProgress | None" = None
    # Fase 2/3 gebaseerd op een oudere nulmeting dan de nieuwste (ook lopende) fase-1-scan.
    geo_outdated: bool = False
    content_outdated: bool = False
    # Fase 4: laatste scan, en de voortgang van de ronde van die scan.
    latest_quarterly_scan: LaunchScanItem | None = None
    quarterly_progress: "ChecklistProgress | None" = None
    quarterly_period: str | None = None
    # Livegang (fase 5): laatste scan en de voortgang van de livegangchecklist
    # (None = nog niet gescand en niets afgevinkt).
    latest_golive_scan: LaunchScanItem | None = None
    golive_progress: "ChecklistProgress | None" = None
    # Sitemap-monitor (phase = 6): open actiepunten in de monitor-scan en de laatste
    # keer dat de sitemap veranderde (None = nog nooit een wijziging gezien).
    monitor_open_issues: int = 0
    monitor_changed_at: datetime | None = None


class LaunchCustomerListResponse(BaseModel):
    customers: list[LaunchCustomerItem]


class LaunchScanPageItem(BaseModel):
    id: str
    url: str
    path: str
    in_sitemap: bool
    status_code: int | None = None
    final_url: str | None = None
    redirect_chain: Any = None
    response_time_ms: int | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    http_version: str | None = None
    indexable: bool | None = None
    indexability_reason: str | None = None
    meta_robots: str | None = None
    title: str | None = None
    title_length: int | None = None
    meta_description: str | None = None
    meta_description_length: int | None = None
    h1: Any = None
    h1_count: int | None = None
    h2: Any = None
    canonical: str | None = None
    word_count: int | None = None
    # Woorden buiten nav/header/footer/aside; None = geen paginastructuur herkend.
    main_word_count: int | None = None
    lang: str | None = None
    hreflang: Any = None
    internal_links: int | None = None
    external_links: int | None = None
    broken_links: Any = None
    images_total: int | None = None
    images_missing_alt: int | None = None
    schema_types: Any = None
    open_graph: Any = None
    cwv: Any = None
    cwv_status: str | None = None
    error: str | None = None
    page_type: str | None = None
    page_type_source: str | None = None
    click_depth: int | None = None
    inlinks: int | None = None
    schema_all: list[str] | None = None
    # Ahrefs: organisch verkeer per maand, verwijzende domeinen en details (topzoekwoord, bron).
    org_traffic: int | None = None
    refdomains: int | None = None
    ahrefs: Any = None
    # Wanneer er met "Maak schema" JSON-LD is gegenereerd; de inhoud zelf zit niet in de lijst.
    schema_suggestion_at: datetime | None = None
    # Wanneer het schema in Rank Math op de klantsite is gezet ("Plaats in Rank Math").
    schema_placed_at: datetime | None = None
    # Beoordeling van het huidige voorstel; None = geen geldige beoordeling (of geen voorstel).
    schema_review_status: Literal["approved", "rejected"] | None = None
    # Eigen keuze van schema-types voor "Maak schema"; None = automatisch op paginatype.
    schema_target_types: list[str] | None = None
    issue_count: int = 0


class LaunchScanPageListResponse(BaseModel):
    pages: list[LaunchScanPageItem]
    total: int


class LaunchScanIssueItem(BaseModel):
    id: str
    scan_id: str
    page_id: str | None = None
    issue_type: str
    issue_label: str | None = None
    category: str
    severity: str
    title: str
    description: str
    recommendation: str | None = None
    url: str | None = None
    details: Any = None
    status: IssueStatus
    external_provider: str | None = None
    external_item_id: str | None = None
    external_url: str | None = None
    pushed_at: datetime | None = None
    # Wanneer er een "Maak prompt"-opdracht is gegenereerd; de tekst zelf zit niet in de lijst.
    fix_prompt_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class IssueGroup(BaseModel):
    issue_type: str
    label: str
    category: str
    severity: str
    count: int
    open: int
    # Hoofditem van dit onderwerp in Monday (fase 1, 3, 4 en de monitor); None = nog niet doorgezet.
    monday_url: str | None = None


class LaunchScanIssueListResponse(BaseModel):
    issues: list[LaunchScanIssueItem]
    total: int
    groups: list[IssueGroup]


class IssueStatusUpdate(BaseModel):
    status: IssueStatus


class IssueBulkStatusUpdate(BaseModel):
    issue_ids: list[str] = Field(..., min_length=1, max_length=2000)
    status: IssueStatus


# --- fase 2: GEO/SEO-checklist ---------------------------------------------

class ChecklistProgress(BaseModel):
    done: int
    total: int
    percent: int


class ChecklistItemOut(BaseModel):
    key: str
    label: str
    description: str | None = None
    mode: str
    applies_to: str
    priority: str
    auto: Any = None
    manual_status: ManualStatus | None = None
    note: str | None = None
    updated_at: datetime | None = None
    external_url: str | None = None
    pushed_at: datetime | None = None
    effective: Literal["done", "open", "nvt"]
    f1_issue_types: list[str] = []


class ChecklistSectionOut(BaseModel):
    key: str
    label: str
    items: list[ChecklistItemOut]
    done: int
    total: int


class ChecklistResponse(BaseModel):
    customer_id: str
    customer_name: str
    base_url: str
    scan: LaunchScanItem | None = None
    source_scan_id: str | None = None
    is_webshop: bool
    webshop_detected: bool | None = None
    webshop_override: bool | None = None
    webshop_reasons: list[str] = []
    page_types: dict[str, int] = {}
    generated_at: str | None = None
    sections: list[ChecklistSectionOut]
    done: int
    total: int
    percent: int


class ChecklistStateUpdate(BaseModel):
    manual_status: ManualStatus | None = None
    note: str | None = Field(default=None, max_length=5000)


class WebshopUpdate(BaseModel):
    is_webshop: bool | None = None


class PageTypeUpdate(BaseModel):
    page_type: str = Field(..., min_length=1, max_length=40)


class GeoScanCreateRequest(BaseModel):
    source_scan_id: str | None = None


# --- Fase 3: content & onpage ------------------------------------------------

SuggestionStatus = Literal["open", "overgenomen", "afgewezen"]


class ContentChecklistResponse(BaseModel):
    customer_id: str
    customer_name: str
    base_url: str
    scan: LaunchScanItem | None = None
    source_scan_id: str | None = None
    page_types: dict[str, int] = {}
    generated_at: str | None = None
    gap_analyzed_at: str | None = None
    summary: Any = None
    max_pages_per_analysis: int
    sections: list[ChecklistSectionOut]
    done: int
    total: int
    percent: int


class ContentSuggestionItem(BaseModel):
    id: str
    scan_id: str
    content_page_id: str | None = None
    page_url: str | None = None
    item_key: str
    item_label: str
    agent: str
    title: str | None = None
    current_value: str | None = None
    proposed_value: str
    rationale: str | None = None
    details: Any = None
    status: SuggestionStatus
    created_at: datetime
    updated_at: datetime


class ContentSuggestionListResponse(BaseModel):
    items: list[ContentSuggestionItem]
    total: int


class ContentPageItem(BaseModel):
    id: str
    url: str
    path: str
    page_type: str | None = None
    title: str | None = None
    meta_description: str | None = None
    word_count: int | None = None
    # Woorden zonder site-brede blokken (reviews, projecten); None = nog niet berekend.
    own_word_count: int | None = None
    problem_count: int
    # item_key → {status, message, details}
    checks: dict[str, Any] = {}
    analysis_status: str
    analysis_error: str | None = None
    focus_keyword: str | None = None
    intent: str | None = None
    keyword_source: str | None = None
    # Ahrefs: het zoekwoord waarop de pagina nu het meeste verkeer krijgt.
    ahrefs_keyword: dict[str, Any] | None = None
    analyzed_at: datetime | None = None
    suggestions_open: int = 0
    suggestions_total: int = 0
    # Checklistpunten waarvoor deze pagina open AI-voorstellen heeft.
    suggestion_items: list[str] = []


class ContentPageDetail(ContentPageItem):
    headings: Any = None
    first_paragraph: str | None = None
    readability: str | None = None
    images_total: int = 0
    links_total: int = 0
    suggestions: list[ContentSuggestionItem] = []


class ContentPageListResponse(BaseModel):
    items: list[ContentPageItem]
    total: int
    page_types: dict[str, int] = {}


class ContentAnalysisRequest(BaseModel):
    # Leeg mag als alleen de contentgap-analyse moet draaien.
    page_ids: list[str] = Field(default_factory=list, max_length=200)
    # Ook de contentgap-analyse (nieuwe content) opnieuw draaien.
    run_gap: bool = True


class ContentKeywordUpdate(BaseModel):
    """Handmatig focuszoekwoord; leeg = weer door de AI laten bepalen."""
    focus_keyword: str | None = Field(default=None, max_length=200)
    intent: Literal["informatief", "commercieel", "transactioneel", "navigatie", "lokaal"] | None = None


class SuggestionStatusUpdate(BaseModel):
    status: SuggestionStatus


# --- Fase 4: kwartaal GEO-werkzaamheden -----------------------------------------

class QuarterlyPeriodOption(BaseModel):
    period: str
    label: str
    scanned: bool


class QuarterlyChecklistResponse(BaseModel):
    customer_id: str
    customer_name: str
    base_url: str
    # De getoonde ronde en de huidige ronde (kwartaal van vandaag).
    period: str
    period_label: str
    current_period: str
    periods: list[QuarterlyPeriodOption]
    scan: LaunchScanItem | None = None
    generated_at: str | None = None
    # Vergelijking met de vorige ronde of de nulmeting (zie quarterly_compare).
    comparison: Any = None
    sources: Any = None
    summary: Any = None
    sections: list[ChecklistSectionOut]
    done: int
    total: int
    percent: int


# --- Livegang (fase 5): oplevering van een nieuwe website ------------------------

class GoLiveScanCreateRequest(BaseModel):
    max_pages: int = Field(default=500, ge=1, le=2000)


class GoLiveChecklistResponse(BaseModel):
    customer_id: str
    customer_name: str
    base_url: str
    # Laatste voltooide livegangscan; None = nog niet gescand (alleen handmatig afvinken).
    scan: LaunchScanItem | None = None
    generated_at: str | None = None
    summary: Any = None
    sections: list[ChecklistSectionOut]
    done: int
    total: int
    percent: int


# --- Monday ----------------------------------------------------------------

class MondaySettingsResponse(BaseModel):
    token_configured: bool
    folder_name: str
    board_id: str | None = None
    board_url: str | None = None
    board_name: str | None = None
    # Melding als het gekoppelde bord niet (meer) bereikbaar is.
    board_error: str | None = None


class MondayBoardLink(BaseModel):
    """Bestaand bord koppelen (id of bord-URL); None ontkoppelt."""
    board: str | None = Field(default=None, max_length=500)


class MondayPushIssuesRequest(BaseModel):
    issue_ids: list[str] = Field(..., min_length=1, max_length=25)


class MondayPushChecklistRequest(BaseModel):
    item_keys: list[str] = Field(..., min_length=1, max_length=25)


class MondayPushOutcome(BaseModel):
    ref: str
    status: Literal["pushed", "skipped", "failed"]
    message: str | None = None
    external_url: str | None = None


class MondayPushResponse(BaseModel):
    board_url: str | None = None
    pushed: int
    skipped: int
    failed: int
    outcomes: list[MondayPushOutcome]


class SearchConsoleProperty(BaseModel):
    site_url: str
    permission: str


class SearchConsoleSettingsResponse(BaseModel):
    # Of GSC_CLIENT_ID, GSC_CLIENT_SECRET en GSC_REFRESH_TOKEN zijn gezet.
    configured: bool
    # De property die de fase 4-scan gebruikt, en of die gekozen of automatisch gevonden is.
    property: str | None = None
    property_source: Literal["manual", "auto"] | None = None
    # Properties die bij het domein van de klant passen, beste eerst.
    candidates: list[str] = Field(default_factory=list)
    # Alle properties waar het Google-account bij kan.
    properties: list[SearchConsoleProperty] = Field(default_factory=list)
    # Melding als de properties niet opgehaald konden worden of de gekozen property ontbreekt.
    error: str | None = None


class SearchConsolePropertyUpdate(BaseModel):
    """Property kiezen (bijv. "sc-domain:example.nl"); None = weer automatisch op domein."""
    property: str | None = Field(default=None, max_length=500)


class BingWebmasterSettingsResponse(BaseModel):
    # Of er een API-key of OAuth-client (BING_CLIENT_ID, BING_CLIENT_SECRET,
    # BING_WEBMASTER_REDIRECT_URI) is ingesteld.
    configured: bool
    # "api_key" (lokaal testen) wint van "oauth"; None als er niets is ingesteld.
    mode: Literal["api_key", "oauth"] | None = None
    # Of de koppelknop kan werken (OAuth-client ingesteld).
    oauth_available: bool = False
    # Of er een werkende koppeling is. Eén koppeling geldt voor alle klanten.
    connected: bool = False
    connected_at: datetime | None = None
    # De site van deze klant in het Bing-account, en of hij daar (geverifieerd) staat.
    site: str | None = None
    site_state: Literal["linked", "not_linked", "not_verified"] | None = None
    # Aantal geverifieerde sites in het Bing-account.
    sites_total: int | None = None
    # Melding als de koppeling verlopen is of de sites niet opgehaald konden worden.
    error: str | None = None


class BingWebmasterAuthorizeUrl(BaseModel):
    url: str


class BingWebmasterExchangeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=4000)


class BingWebmasterConnectionResponse(BaseModel):
    connected: bool


# --- sitemap-monitor (phase = 6) -----------------------------------------------------

class SitemapChangeItem(BaseModel):
    kind: Literal["new", "changed", "removed"]
    url: str
    lastmod: str | None = None
    detected_at: datetime


class SitemapMonitorStatus(BaseModel):
    customer_id: str
    # Schakelaar per klant (dagelijkse run); `global_enabled` is de noodrem SITEMAP_MONITOR_ENABLED.
    enabled: bool
    global_enabled: bool
    # Voltooide nulmeting aanwezig: zonder die slaat de dagelijkse run de klant over en
    # weigert "Nu controleren" (400).
    has_nulmeting: bool
    # De doorlopende monitor-scan; None tot de eerste run met nieuwe/gewijzigde pagina's.
    scan_id: str | None = None
    scan_status: ScanStatus | None = None
    # De monitor-scan verwerkt nu pagina's (status in ACTIVE_STATUSES).
    running: bool = False
    checked_at: datetime | None = None
    changed_at: datetime | None = None
    last_error: str | None = None
    # Aantal URL's in de laatst bekende sitemap-stand (0 = nog geen uitgangssituatie).
    total_urls: int = 0
    has_lastmod: bool = False
    # Nieuwste eerst, hooguit 300.
    recent_changes: list[SitemapChangeItem] = []
    open_issues: int = 0


class SitemapMonitorUpdate(BaseModel):
    enabled: bool


LaunchCustomerItem.model_rebuild()
