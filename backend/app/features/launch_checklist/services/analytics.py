"""Analytics over livegang-scans: trend per klant, scan A tegen B en klanten onderling.

Alleen fase 1 (nulmeting) en fase 4 (kwartaal) leveren cijfers die op een
tijdlijn passen. Eén extractor (`extract_metrics`) is de bron voor alle drie de
weergaven. Regels die de cijfers eerlijk houden:

- None = niet gemeten, nooit 0 (fase 4 meet geen Core Web Vitals).
- Actiepunten tellen uit `summary_stats["issues"]["by_type"]` zonder `c4_`- en
  `cwv_`-punten (zelfde regel als de fase 4-vergelijking), niet uit `issues.total`.
- Types die nieuwer zijn dan de laagste regelset in de vergeleken set tellen in
  `issues_new_checks`, niet in `issues_comparable`.
- Procenten zijn 0-100 (GSC slaat de CTR op als fractie).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import LaunchScan, LaunchScanPage
from app.features.launch_checklist.services.issues import ISSUE_TYPES, issue_type_since
from app.features.launch_checklist.services.prt_enrich import DETAIL_ORDER as PRT_PLATFORMS
from app.features.launch_checklist.services.prt_enrich import PLATFORM_LABELS as PRT_PLATFORM_LABELS
from app.features.launch_checklist.services.quarterly_checklist import _TZ, period_label, period_of
from app.features.launch_checklist.services.quarterly_compare import (
    compare_ahrefs,
    compare_ai,
    compare_issues,
    compare_pages,
    count_issues_by_type,
    scan_ruleset,
)

TREND_PHASES = (1, 4)
NEW_PAGES_IN_COMPARISON = 50  # zelfde aantal voorbeelden als de opgeslagen fase 4-vergelijking

GROUP_LABELS: dict[str, str] = {
    "issues": "Actiepunten",
    "issues_category": "Actiepunten per categorie",
    "tech": "Techniek",
    "cwv": "Core Web Vitals",
    "ai": "AI-vindbaarheid",
    "ahrefs": "Ahrefs",
    "gsc": "Search Console",
    "bing": "Bing",
    "prt": "AI-zichtbaarheid (ProRankTracker)",
    "checklist": "Checklist-voortgang",
}

CATEGORY_LABELS: dict[str, str] = {
    "techniek": "Techniek",
    "performance": "Performance",
    "on-page": "On-page",
    "content": "Content",
    "ai": "AI-vindbaarheid",
    "schema": "Schema.org",
    "entiteit": "Entiteit & merkvertrouwen",
}
# Categorieën in de volgorde waarin ze in ISSUE_TYPES voorkomen.
ISSUE_CATEGORIES: list[str] = list(dict.fromkeys(meta["category"] for meta in ISSUE_TYPES.values()))

_MONTHS = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


# --- snapshot -------------------------------------------------------------------

@dataclass
class ScanSnapshot:
    """Wat analytics van een scan nodig heeft; nooit `checklist`, `agent_trace` of `ai_summary`."""

    id: str
    customer_id: str
    phase: int
    status: str
    period: str | None
    created_at: datetime
    completed_at: datetime | None
    summary_stats: dict[str, Any] | None
    # {"score", "checks"} of None
    ai_checks: dict[str, Any] | None
    # {"domain", "reused_from", "fetched_at", "errors", "lost_value_urls"} of None
    ahrefs: dict[str, Any] | None
    # {"property", "fetched_at", "period", "totals", "errors", "inspection": {checked, indexed, eligible}} of None
    search_console: dict[str, Any] | None
    # {"state", "period", "totals", "in_index"} of None
    bing_webmaster: dict[str, Any] | None
    # {"state", "totals", "platforms"} of None (scans van vóór de ProRankTracker-koppeling)
    proranktracker: dict[str, Any] | None = None


# Projectie: JSON-subpaden in plaats van hele kolommen (GSC-queries/pagina's en
# inspectierijen kunnen groot zijn). Werkt op Postgres (`->`/`#>`) en SQLite (JSON_EXTRACT).
SNAPSHOT_COLUMNS = (
    LaunchScan.id,
    LaunchScan.customer_website_id,
    LaunchScan.phase,
    LaunchScan.status,
    LaunchScan.period,
    LaunchScan.created_at,
    LaunchScan.completed_at,
    LaunchScan.summary_stats,
    LaunchScan.ai_checks["score"].label("ai_score"),
    LaunchScan.ai_checks["checks"].label("ai_checks_list"),
    LaunchScan.ahrefs["domain"].label("ahrefs_domain"),
    LaunchScan.ahrefs["reused_from"].label("ahrefs_reused_from"),
    LaunchScan.ahrefs["fetched_at"].label("ahrefs_fetched_at"),
    LaunchScan.ahrefs["errors"].label("ahrefs_errors"),
    LaunchScan.ahrefs["lost_value_urls"].label("ahrefs_lost_value_urls"),
    LaunchScan.search_console["property"].label("gsc_property"),
    LaunchScan.search_console["fetched_at"].label("gsc_fetched_at"),
    LaunchScan.search_console["period"].label("gsc_period"),
    LaunchScan.search_console["totals"].label("gsc_totals"),
    LaunchScan.search_console["errors"].label("gsc_errors"),
    LaunchScan.search_console[("inspection", "checked")].label("gsc_inspection_checked"),
    LaunchScan.search_console[("inspection", "indexed")].label("gsc_inspection_indexed"),
    LaunchScan.search_console[("inspection", "eligible")].label("gsc_inspection_eligible"),
    LaunchScan.bing_webmaster["state"].label("bing_state"),
    LaunchScan.bing_webmaster["period"].label("bing_period"),
    LaunchScan.bing_webmaster["totals"].label("bing_totals"),
    LaunchScan.bing_webmaster[("crawl", "in_index")].label("bing_in_index"),
    # Niet de promptlijst: alleen de cijfers die op een tijdlijn passen.
    LaunchScan.proranktracker["state"].label("prt_state"),
    LaunchScan.proranktracker["totals"].label("prt_totals"),
    LaunchScan.proranktracker["platforms"].label("prt_platforms"),
)


def _dict_or_none(**values: Any) -> dict[str, Any] | None:
    return values if any(v is not None for v in values.values()) else None


def snapshot_from_row(row: Any) -> ScanSnapshot:
    ai = None
    if row.ai_score is not None or row.ai_checks_list is not None:
        ai = {"score": row.ai_score, "checks": row.ai_checks_list or []}
    ahrefs = _dict_or_none(
        domain=row.ahrefs_domain,
        reused_from=row.ahrefs_reused_from,
        fetched_at=row.ahrefs_fetched_at,
        errors=row.ahrefs_errors,
        lost_value_urls=row.ahrefs_lost_value_urls,
    )
    inspection = _dict_or_none(
        checked=row.gsc_inspection_checked,
        indexed=row.gsc_inspection_indexed,
        eligible=row.gsc_inspection_eligible,
    )
    search_console = _dict_or_none(
        property=row.gsc_property,
        fetched_at=row.gsc_fetched_at,
        period=row.gsc_period,
        totals=row.gsc_totals,
        errors=row.gsc_errors,
        inspection=inspection,
    )
    bing = None
    if row.bing_state is not None:
        bing = {
            "state": row.bing_state,
            "period": row.bing_period,
            "totals": row.bing_totals,
            "in_index": row.bing_in_index,
        }
    prt = None
    if row.prt_state is not None:
        prt = {"state": row.prt_state, "totals": row.prt_totals, "platforms": row.prt_platforms}
    return ScanSnapshot(
        id=row.id,
        customer_id=row.customer_website_id,
        phase=row.phase,
        status=row.status,
        period=row.period,
        created_at=row.created_at,
        completed_at=row.completed_at,
        summary_stats=row.summary_stats if isinstance(row.summary_stats, dict) else None,
        ai_checks=ai,
        ahrefs=ahrefs,
        search_console=search_console,
        bing_webmaster=bing,
        proranktracker=prt,
    )


def load_snapshots(db: Session, *criteria: Any) -> list[ScanSnapshot]:
    rows = db.query(*SNAPSHOT_COLUMNS).filter(*criteria).order_by(LaunchScan.created_at.asc()).all()
    return [snapshot_from_row(row) for row in rows]


def load_customer_snapshots(db: Session, customer_id: str) -> list[ScanSnapshot]:
    """Voltooide fase 1- en fase 4-scans van één klant, oudste eerst."""
    return load_snapshots(
        db,
        LaunchScan.customer_website_id == customer_id,
        LaunchScan.phase.in_(TREND_PHASES),
        LaunchScan.status == "completed",
    )


def load_latest_snapshots(db: Session) -> dict[str, ScanSnapshot]:
    """Laatste voltooide fase 1/4-scan per klant, in één query (row_number)."""
    ranked = (
        select(
            LaunchScan.id.label("scan_id"),
            func.row_number()
            .over(partition_by=LaunchScan.customer_website_id, order_by=LaunchScan.created_at.desc())
            .label("rn"),
        )
        .where(LaunchScan.phase.in_(TREND_PHASES), LaunchScan.status == "completed")
        .subquery()
    )
    rows = (
        db.query(*SNAPSHOT_COLUMNS)
        .join(ranked, ranked.c.scan_id == LaunchScan.id)
        .filter(ranked.c.rn == 1)
        .all()
    )
    return {row.customer_website_id: snapshot_from_row(row) for row in rows}


def load_page_rows(db: Session, scan_id: str) -> list[SimpleNamespace]:
    """Alleen wat `compare_pages` gebruikt (`page_key`, `is_crawled`, `is_broken`, `is_working`)."""
    rows = (
        db.query(
            LaunchScanPage.url,
            LaunchScanPage.status_code,
            LaunchScanPage.redirect_chain,
            LaunchScanPage.error,
            LaunchScanPage.ahrefs["source"].label("ahrefs_source"),
        )
        .filter(LaunchScanPage.scan_id == scan_id)
        .all()
    )
    return [
        SimpleNamespace(
            url=row.url,
            status_code=row.status_code,
            redirect_chain=row.redirect_chain,
            error=row.error,
            ahrefs={"source": row.ahrefs_source} if row.ahrefs_source is not None else None,
        )
        for row in rows
    ]


# --- scan-metadata ----------------------------------------------------------------

def aware(moment: datetime) -> datetime:
    """SQLite geeft tijden zonder tijdzone terug; die zijn UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def scan_moment(snapshot: ScanSnapshot) -> datetime:
    return aware(snapshot.completed_at or snapshot.created_at)


def scan_local_date(snapshot: ScanSnapshot) -> date:
    return scan_moment(snapshot).astimezone(_TZ).date()


def scan_period(snapshot: ScanSnapshot) -> str:
    """Ronde van de scan; voor de nulmeting het kwartaal waarin hij gestart is."""
    if snapshot.phase == 4 and snapshot.period:
        return snapshot.period
    return period_of(aware(snapshot.created_at))


def scan_label(snapshot: ScanSnapshot) -> str:
    if snapshot.phase == 4:
        return period_label(scan_period(snapshot))
    local = aware(snapshot.created_at).astimezone(_TZ)
    return f"Nulmeting {_MONTHS[local.month - 1]} {local.year}"


def scan_ref(snapshot: ScanSnapshot) -> dict[str, Any]:
    return {
        "scan_id": snapshot.id,
        "phase": snapshot.phase,
        "period": scan_period(snapshot),
        "label": scan_label(snapshot),
        "date": scan_moment(snapshot).isoformat(),
    }


def primary_scan_ids(snapshots: Iterable[ScanSnapshot]) -> set[str]:
    """Per fase en ronde de laatst gestarte voltooide scan: één punt per ronde."""
    latest: dict[tuple[int, str], ScanSnapshot] = {}
    for snapshot in snapshots:
        if snapshot.status != "completed":
            continue
        key = (snapshot.phase, scan_period(snapshot))
        current = latest.get(key)
        if current is None or aware(snapshot.created_at) >= aware(current.created_at):
            latest[key] = snapshot
    return {s.id for s in latest.values()}


def ruleset_floor(snapshots: Iterable[ScanSnapshot]) -> int | None:
    """Laagste regelset in de set (None voor een lege set)."""
    return min((scan_ruleset(s) for s in snapshots), default=None)


# --- bronnen -------------------------------------------------------------------

_BING_NOT_CONNECTED = {"not_configured", "not_connected", "site_not_linked", "site_not_verified"}
_PRT_NOT_CONNECTED = {"not_configured", "not_tracked"}


def scan_sources(snapshot: ScanSnapshot) -> dict[str, str]:
    """Per bron: "ok" | "reused" | "not_measured" | "not_connected" | "error"."""
    ahrefs = snapshot.ahrefs
    if ahrefs is None:
        ahrefs_state = "not_connected"  # AHREFS_API_KEY ontbrak: de scan bewaart dan niets
    elif ahrefs.get("domain"):
        ahrefs_state = "reused" if ahrefs.get("reused_from") else "ok"
    else:
        ahrefs_state = "error"

    gsc = snapshot.search_console
    if snapshot.phase != 4:
        gsc_state = "not_measured"
    elif gsc is None:
        gsc_state = "not_connected"  # geen koppeling, geen property of geen data
    elif gsc.get("totals") is not None:
        gsc_state = "ok"
    else:
        gsc_state = "error"

    bing = snapshot.bing_webmaster
    if snapshot.phase != 4 or bing is None:
        bing_state = "not_measured"
    elif bing.get("state") == "ok":
        bing_state = "ok"
    elif bing.get("state") in _BING_NOT_CONNECTED:
        bing_state = "not_connected"
    else:
        bing_state = "error"

    prt = snapshot.proranktracker
    if prt is None:
        prt_state = "not_measured"  # scan van vóór de koppeling
    elif prt.get("state") == "ok":
        prt_state = "ok"
    elif prt.get("state") in _PRT_NOT_CONNECTED:
        prt_state = "not_connected"
    else:
        prt_state = "error"

    cwv = (snapshot.summary_stats or {}).get("cwv") or {}
    cwv_state = "ok" if (cwv.get("measured") or 0) > 0 else "not_measured"
    return {
        "ahrefs": ahrefs_state,
        "search_console": gsc_state,
        "bing": bing_state,
        "proranktracker": prt_state,
        "cwv": cwv_state,
    }


# --- metrics --------------------------------------------------------------------

Getter = Callable[[ScanSnapshot], "float | int | None"]


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    group: str
    unit: str  # "count" | "percent" | "score" | "ms" | "position"
    higher_is_better: bool | None
    phases: tuple[int, ...]
    getter: Getter | None = None  # None: berekend in extract_metrics (actiepunten) of buiten de scan

    @property
    def group_label(self) -> str:
        return GROUP_LABELS[self.group]

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "group": self.group,
            "group_label": self.group_label,
            "unit": self.unit,
            "higher_is_better": self.higher_is_better,
            "phases": list(self.phases),
        }


def _num(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(part: Any, whole: Any) -> float | None:
    p, w = _num(part), _num(whole)
    if p is None or not w:
        return None
    return round(100 * p / w, 1)


def _stats(key: str) -> Getter:
    return lambda s: _num((s.summary_stats or {}).get(key))


def _cwv(s: ScanSnapshot) -> dict[str, Any] | None:
    """CWV-cijfers alleen als er gemeten is (fase 4 zet `measured` op 0)."""
    cwv = (s.summary_stats or {}).get("cwv")
    if not isinstance(cwv, dict) or not (_num(cwv.get("measured")) or 0) > 0:
        return None
    return cwv


def _ai_count(status: str) -> Getter:
    def get(s: ScanSnapshot) -> int | None:
        if s.ai_checks is None:
            return None
        return len([c for c in s.ai_checks.get("checks") or [] if isinstance(c, dict) and c.get("status") == status])
    return get


def _ahrefs(key: str) -> Getter:
    return lambda s: _num(((s.ahrefs or {}).get("domain") or {}).get(key))


def _gsc_totals(s: ScanSnapshot) -> dict[str, Any] | None:
    if s.phase != 4:
        return None
    totals = (s.search_console or {}).get("totals")
    return totals if isinstance(totals, dict) else None


def _gsc_ctr(s: ScanSnapshot) -> float | None:
    ctr = _num((_gsc_totals(s) or {}).get("ctr"))
    return round(100 * ctr, 2) if ctr is not None else None  # GSC: fractie -> procent


def _gsc_indexed_pct(s: ScanSnapshot) -> float | None:
    if s.phase != 4:
        return None
    inspection = (s.search_console or {}).get("inspection") or {}
    return _pct(inspection.get("indexed"), inspection.get("checked"))


def _bing(s: ScanSnapshot) -> dict[str, Any] | None:
    bing = s.bing_webmaster
    return bing if s.phase == 4 and bing is not None and bing.get("state") == "ok" else None


def _bing_total(key: str) -> Getter:
    return lambda s: _num(((_bing(s) or {}).get("totals") or {}).get(key))


def _prt(s: ScanSnapshot) -> dict[str, Any] | None:
    prt = s.proranktracker
    return prt if prt is not None and prt.get("state") == "ok" else None


def _prt_total(key: str) -> Getter:
    return lambda s: _num(((_prt(s) or {}).get("totals") or {}).get(key))


def _prt_platform_visibility(platform: str) -> Getter:
    return lambda s: _num((((_prt(s) or {}).get("platforms") or {}).get(platform) or {}).get("visibility"))


_P14 = (1, 4)


def _metric_list() -> list[MetricDef]:
    out = [
        MetricDef("issues_comparable", "Actiepunten (vergelijkbaar)", "issues", "count", False, _P14),
        MetricDef("issues_new_checks", "Actiepunten uit nieuwe controles", "issues", "count", False, _P14),
    ]
    out += [
        MetricDef(f"issues_cat_{cat}", f"Actiepunten {CATEGORY_LABELS.get(cat, cat)}", "issues_category",
                  "count", False, _P14)
        for cat in ISSUE_CATEGORIES
    ]
    out += [
        MetricDef("pages_total", "Gevonden URL's", "tech", "count", None, _P14, _stats("total_urls")),
        MetricDef("indexable_pct", "Indexeerbare HTML-pagina's", "tech", "percent", True, _P14,
                  lambda s: _pct((s.summary_stats or {}).get("indexable"), (s.summary_stats or {}).get("html_pages"))),
        MetricDef("missing_title", "Title ontbreekt", "tech", "count", False, _P14, _stats("missing_title")),
        MetricDef("missing_meta", "Meta description ontbreekt", "tech", "count", False, _P14, _stats("missing_meta")),
        MetricDef("missing_h1", "H1 ontbreekt", "tech", "count", False, _P14, _stats("missing_h1")),
        MetricDef("broken_link_pages", "Pagina's met kapotte links", "tech", "count", False, _P14,
                  _stats("broken_link_pages")),
        MetricDef("final_4xx", "Pagina's met 4xx-fout", "tech", "count", False, _P14, _stats("final_4xx")),
        MetricDef("redirects", "Redirects", "tech", "count", False, _P14, _stats("redirects")),
        MetricDef("images_missing_alt", "Afbeeldingen zonder alt-tekst", "tech", "count", False, _P14,
                  _stats("images_missing_alt")),
        MetricDef("avg_response_ms", "Gemiddelde responstijd", "tech", "ms", False, _P14, _stats("avg_response_ms")),
        MetricDef("cwv_good_pct", "Pagina's met goede Core Web Vitals", "cwv", "percent", True, (1,),
                  lambda s: _pct((_cwv(s) or {}).get("good"), (_cwv(s) or {}).get("measured"))),
        MetricDef("cwv_poor", "Pagina's met slechte Core Web Vitals", "cwv", "count", False, (1,),
                  lambda s: _num((_cwv(s) or {}).get("poor"))),
        MetricDef("cwv_performance_score", "Gemiddelde performancescore", "cwv", "score", True, (1,),
                  lambda s: _num((_cwv(s) or {}).get("avg_performance_score"))),
        MetricDef("ai_score", "AI-score", "ai", "score", True, _P14,
                  lambda s: _num((s.ai_checks or {}).get("score"))),
        MetricDef("ai_checks_ok", "AI-checks in orde", "ai", "count", True, _P14, _ai_count("ok")),
        MetricDef("ai_checks_warning", "AI-checks met waarschuwing", "ai", "count", False, _P14, _ai_count("warning")),
        MetricDef("ai_checks_error", "AI-checks met fout", "ai", "count", False, _P14, _ai_count("error")),
        MetricDef("domain_rating", "Domain Rating", "ahrefs", "score", True, _P14, _ahrefs("domain_rating")),
        MetricDef("refdomains", "Verwijzende domeinen", "ahrefs", "count", True, _P14, _ahrefs("refdomains")),
        MetricDef("backlinks", "Backlinks", "ahrefs", "count", True, _P14, _ahrefs("backlinks")),
        MetricDef("org_traffic", "Organisch verkeer / maand", "ahrefs", "count", True, _P14, _ahrefs("org_traffic")),
        MetricDef("org_keywords", "Organische zoekwoorden", "ahrefs", "count", True, _P14, _ahrefs("org_keywords")),
        MetricDef("org_keywords_1_3", "Zoekwoorden in top 3", "ahrefs", "count", True, _P14,
                  _ahrefs("org_keywords_1_3")),
        MetricDef("gsc_clicks", "Klikken (Google)", "gsc", "count", True, (4,),
                  lambda s: _num((_gsc_totals(s) or {}).get("clicks"))),
        MetricDef("gsc_impressions", "Vertoningen (Google)", "gsc", "count", True, (4,),
                  lambda s: _num((_gsc_totals(s) or {}).get("impressions"))),
        MetricDef("gsc_ctr", "CTR (Google)", "gsc", "percent", True, (4,), _gsc_ctr),
        MetricDef("gsc_position", "Gemiddelde positie (Google)", "gsc", "position", False, (4,),
                  lambda s: _num((_gsc_totals(s) or {}).get("position"))),
        MetricDef("gsc_indexed_pct", "Geïndexeerd van geïnspecteerde pagina's", "gsc", "percent", True, (4,),
                  _gsc_indexed_pct),
        MetricDef("bing_clicks", "Klikken (Bing)", "bing", "count", True, (4,), _bing_total("clicks")),
        MetricDef("bing_impressions", "Vertoningen (Bing)", "bing", "count", True, (4,), _bing_total("impressions")),
        MetricDef("bing_in_index", "Pagina's in Bing-index", "bing", "count", True, (4,),
                  lambda s: _num((_bing(s) or {}).get("in_index"))),
        MetricDef("prt_visibility", "AI-zichtbaarheid", "prt", "score", True, _P14, _prt_total("visibility")),
        MetricDef("prt_appearances", "Verschijningen in AI-antwoorden", "prt", "count", True, _P14,
                  _prt_total("appearances")),
        MetricDef("prt_mentions", "Merkvermeldingen in AI-antwoorden", "prt", "count", True, _P14,
                  _prt_total("mentions")),
        MetricDef("prt_links", "Links in AI-antwoorden", "prt", "count", True, _P14, _prt_total("links")),
        MetricDef("prt_prompts", "Getrackte prompts", "prt", "count", None, _P14, _prt_total("prompts")),
    ]
    out += [
        MetricDef(f"prt_visibility_{platform}", f"AI-zichtbaarheid {PRT_PLATFORM_LABELS[platform]}", "prt",
                  "score", True, _P14, _prt_platform_visibility(platform))
        for platform in PRT_PLATFORMS
    ]
    out += [
        MetricDef("checklist_geo_pct", "GEO/SEO-checklist (fase 2) afgerond", "checklist", "percent", True, (2,)),
        MetricDef("checklist_content_pct", "Contentchecklist (fase 3) afgerond", "checklist", "percent", True, (3,)),
        MetricDef("checklist_golive_pct", "Livegangchecklist (fase 5) afgerond", "checklist", "percent", True, (5,)),
    ]
    return out


METRICS: dict[str, MetricDef] = {m.key: m for m in _metric_list()}
SCAN_METRIC_KEYS: list[str] = [k for k, m in METRICS.items() if m.group != "checklist"]
CHECKLIST_METRIC_KEYS: list[str] = [k for k, m in METRICS.items() if m.group == "checklist"]


def metric_defs(*, include_checklist: bool) -> list[dict[str, Any]]:
    return [m.as_dict() for m in METRICS.values() if include_checklist or m.group != "checklist"]


def _issue_metrics(snapshot: ScanSnapshot, floor: int | None) -> dict[str, int | None]:
    keys = ["issues_comparable", "issues_new_checks"] + [f"issues_cat_{cat}" for cat in ISSUE_CATEGORIES]
    by_type = ((snapshot.summary_stats or {}).get("issues") or {}).get("by_type")
    if not isinstance(by_type, dict):
        return {key: None for key in keys}  # oude scan zonder telling per type
    counts = count_issues_by_type(by_type)
    out: dict[str, int | None] = {key: 0 for key in keys}
    for issue_type, count in counts.items():
        if floor is not None and issue_type_since(issue_type) > floor:
            out["issues_new_checks"] += count
            continue
        out["issues_comparable"] += count
        category = ISSUE_TYPES.get(issue_type, {}).get("category", "techniek")
        out[f"issues_cat_{category}"] = (out.get(f"issues_cat_{category}") or 0) + count
    return out


def extract_metrics(snapshot: ScanSnapshot, ruleset_floor: int | None = None) -> dict[str, float | int | None]:
    """Alle scan-metrics (geen checklist-voortgang). None = niet gemeten.

    Met `ruleset_floor` tellen actiepunttypes die pas in een latere regelset
    bestaan in `issues_new_checks`; de categorieën tellen alleen vergelijkbare types.
    """
    values: dict[str, float | int | None] = {}
    issue_values = _issue_metrics(snapshot, ruleset_floor)
    for key in SCAN_METRIC_KEYS:
        metric = METRICS[key]
        if key in issue_values:
            values[key] = issue_values[key]
        elif snapshot.phase not in metric.phases or metric.getter is None:
            values[key] = None
        else:
            values[key] = metric.getter(snapshot)
    return values


# --- trend ----------------------------------------------------------------------

def build_trend(
    snapshots: list[ScanSnapshot], *, start: date | None = None, end: date | None = None
) -> dict[str, Any]:
    """Punten (oplopend op datum), regelset-breuken en metric-definities."""
    primary = primary_scan_ids(snapshots)  # over alle scans: een datumfilter verandert dit niet
    selected = [
        s for s in snapshots
        if s.status == "completed" and s.phase in TREND_PHASES
        and (start is None or scan_local_date(s) >= start)
        and (end is None or scan_local_date(s) <= end)
    ]
    selected.sort(key=lambda s: (scan_moment(s), aware(s.created_at)))
    floor = ruleset_floor(selected)
    points = [
        {
            **scan_ref(s),
            "ruleset": scan_ruleset(s),
            "is_primary": s.id in primary,
            "sources": scan_sources(s),
            "values": extract_metrics(s, floor),
        }
        for s in selected
    ]
    breaks = [
        {"after_scan_id": prev["scan_id"], "from": prev["ruleset"], "to": cur["ruleset"]}
        for prev, cur in zip(points, points[1:])
        if prev["ruleset"] != cur["ruleset"]
    ]
    return {"metrics": metric_defs(include_checklist=False), "points": points, "breaks": breaks}


# --- scan A tegen B ---------------------------------------------------------------

def order_pair(a: ScanSnapshot, b: ScanSnapshot) -> tuple[ScanSnapshot, ScanSnapshot]:
    """Oudste eerst."""
    key = lambda s: (scan_moment(s), aware(s.created_at))  # noqa: E731
    return (a, b) if key(a) <= key(b) else (b, a)


def _delta_row(metric: MetricDef, before: Any, after: Any) -> dict[str, Any]:
    delta = after - before if before is not None and after is not None else None
    if isinstance(delta, float):
        delta = round(delta, 2)
    return {
        "key": metric.key,
        "label": metric.label,
        "group": metric.group,
        "group_label": metric.group_label,
        "unit": metric.unit,
        "higher_is_better": metric.higher_is_better,
        "before": before,
        "after": after,
        "delta": delta,
        "pct": round(100 * (after - before) / before, 1) if delta is not None and before else None,
    }


def _span_overlap(a: Any, b: Any) -> bool:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    try:
        return date.fromisoformat(str(a["end"])) >= date.fromisoformat(str(b["start"])) and \
            date.fromisoformat(str(b["end"])) >= date.fromisoformat(str(a["start"]))
    except (KeyError, ValueError):
        return False


def _span_text(span: dict[str, Any]) -> str:
    return f"{span.get('start')} t/m {span.get('end')}"


def compare_notes(a: ScanSnapshot, b: ScanSnapshot, issues: dict[str, Any] | None) -> list[str]:
    notes: list[str] = []
    if a.phase == 4 and b.phase == 4 and scan_period(a) == scan_period(b):
        notes.append(f"A en B horen bij dezelfde ronde ({period_label(scan_period(a))}).")
    for label, snapshot in (("A", a), ("B", b)):
        if snapshot.phase == 1:
            notes.append(
                f"{label} is een nulmeting: Search Console en Bing worden daar niet gemeten, "
                "dus voor die cijfers is er geen vergelijking."
            )
    if 4 in (a.phase, b.phase):
        notes.append(
            "Core Web Vitals worden alleen in de nulmeting gemeten: een kwartaalscan heeft die cijfers niet."
        )
    gsc_a, gsc_b = (a.search_console or {}).get("period"), (b.search_console or {}).get("period")
    if a.phase == 4 and b.phase == 4 and _span_overlap(gsc_a, gsc_b):
        notes.append(
            f"De Search Console-meetperiodes overlappen (A: {_span_text(gsc_a)}, B: {_span_text(gsc_b)}): "
            "klikken en vertoningen uit de overlap tellen in beide scans mee."
        )
    bing_a, bing_b = (a.bing_webmaster or {}).get("period"), (b.bing_webmaster or {}).get("period")
    if a.phase == 4 and b.phase == 4 and _span_overlap(bing_a, bing_b):
        notes.append(
            f"De Bing-meetperiodes overlappen (A: {_span_text(bing_a)}, B: {_span_text(bing_b)})."
        )
    ahrefs_a, ahrefs_b = a.ahrefs or {}, b.ahrefs or {}
    if ahrefs_b.get("reused_from") and (
        ahrefs_b.get("reused_from") == a.id
        or (ahrefs_a.get("fetched_at") and ahrefs_a.get("fetched_at") == ahrefs_b.get("fetched_at"))
    ):
        notes.append("B gebruikt dezelfde Ahrefs-meting als A (hergebruikt binnen de bewaartermijn): "
                     "de Ahrefs-cijfers kunnen niet veranderd zijn.")
    elif ahrefs_b.get("reused_from"):
        notes.append("De Ahrefs-cijfers van B zijn hergebruikt van een eerdere scan.")
    rs_a, rs_b = scan_ruleset(a), scan_ruleset(b)
    if rs_a != rs_b:
        extra = issues.get("not_compared") if issues else None
        notes.append(
            f"A is gemaakt met regelset {rs_a} en B met regelset {rs_b}: actiepunten uit nieuwere "
            "controles tellen niet mee in de vergelijking"
            + (f" ({extra} in B)." if extra else ".")
        )
    if issues is None:
        notes.append("Van minstens één scan ontbreekt de telling per actiepunttype: geen vergelijking van actiepunten.")
    return notes


def build_compare(
    a: ScanSnapshot,
    b: ScanSnapshot,
    *,
    pages_a: list[Any],
    pages_b: list[Any],
    rankings: dict[str, Any] | None,
) -> dict[str, Any]:
    """A en B moeten al chronologisch staan (`order_pair`)."""
    floor = min(scan_ruleset(a), scan_ruleset(b))
    before, after = extract_metrics(a, floor), extract_metrics(b, floor)
    metrics = [_delta_row(METRICS[key], before[key], after[key]) for key in SCAN_METRIC_KEYS]

    by_type_a = ((a.summary_stats or {}).get("issues") or {}).get("by_type")
    by_type_b = ((b.summary_stats or {}).get("issues") or {}).get("by_type")
    issues = None
    if isinstance(by_type_a, dict) and isinstance(by_type_b, dict):
        issues = compare_issues(
            count_issues_by_type(by_type_a), count_issues_by_type(by_type_b), base_ruleset=scan_ruleset(a)
        )

    pages_diff = compare_pages(pages_a, pages_b)
    return {
        "a": scan_ref(a),
        "b": scan_ref(b),
        "metrics": metrics,
        "ai": compare_ai(a.ai_checks, b.ai_checks) if (a.ai_checks or b.ai_checks) else None,
        "issues": issues,
        "pages": {
            "before": pages_diff["before"],
            "after": pages_diff["after"],
            "new": len(pages_diff["new"]),
            "removed": len(pages_diff["removed"]),
            "broken": len(pages_diff["broken"]),
            "new_examples": [p.url for p in pages_diff["new"]][:NEW_PAGES_IN_COMPARISON],
        },
        "ahrefs": compare_ahrefs(a.ahrefs, b.ahrefs),
        "rankings": rankings,
        "notes": compare_notes(a, b, issues),
    }


# --- klanten onderling --------------------------------------------------------------

def _quantile(sorted_values: list[float], q: float) -> float:
    """Lineaire interpolatie (zoals numpy.percentile standaard)."""
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    value = sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)
    return round(value, 2)


def summarize(values: Iterable[float | int | None]) -> dict[str, Any]:
    present = sorted(v for v in values if v is not None)
    if not present:
        return {"median": None, "p25": None, "p75": None, "min": None, "max": None, "n": 0}
    return {
        "median": _quantile(present, 0.5),
        "p25": _quantile(present, 0.25),
        "p75": _quantile(present, 0.75),
        "min": present[0],
        "max": present[-1],
        "n": len(present),
    }


def build_benchmark(
    customers: list[Any],
    latest: dict[str, ScanSnapshot],
    checklist_values: dict[str, dict[str, float | int | None]],
    *,
    max_age_days: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Eén rij per klant: laatste voltooide fase 1/4-scan plus checklist-voortgang.

    Met `max_age_days` telt een oudere scan niet mee (scan = None, scan-metrics None);
    de klant blijft in de rijen voor de checklist-voortgang.
    """
    now = now or datetime.now(timezone.utc)
    usable: dict[str, ScanSnapshot] = {}
    for customer_id, snapshot in latest.items():
        if max_age_days is not None and (now - scan_moment(snapshot)).days > max_age_days:
            continue
        usable[customer_id] = snapshot
    floor = ruleset_floor(usable.values())
    empty = {key: None for key in SCAN_METRIC_KEYS}
    rows = []
    for customer in customers:
        snapshot = usable.get(customer.id)
        values = extract_metrics(snapshot, floor) if snapshot is not None else dict(empty)
        values.update(checklist_values.get(customer.id) or {key: None for key in CHECKLIST_METRIC_KEYS})
        rows.append({
            "customer": {"id": customer.id, "name": customer.name, "domain": customer.domain},
            "scan": scan_ref(snapshot) if snapshot is not None else None,
            "values": values,
        })
    summary = {key: summarize(row["values"].get(key) for row in rows) for key in METRICS}
    return {"metrics": metric_defs(include_checklist=True), "rows": rows, "summary": summary}
