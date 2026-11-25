"""Cijfers en werk van één klant voor één maand verzamelen (`ReportData`).

Gooit nooit fouten van Search Console of ProRankTracker: elk cijfer krijgt een toestand uit
`schemas.MetricState`, en de agent schrijft met wat er is.

- Bezoekers uit Google (`clicks_metric`): klikken in de kalendermaand uit Search Console, tot
  zover Google ze heeft (`periods.gsc_spans`), tegen dezelfde dagen van de maand ervoor.
- Zoekwoorden in top 10 (`top10_metric`) en Genoemd door AI (`ai_metric`): ProRankTracker kent
  alleen "nu", dus alleen binnen `periods.prt_window_open`; anders `out_of_window`. Een eerder
  vastgelegd `ok`-cijfer (`previous_data`) wordt nooit vervangen door een niet-`ok`.
- Aanvragen: alleen handmatig (`manual` en het rapport van de vorige maand).
- Wat we deden (`work_done`, id's W1, W2, ...) en Volgende maand (`upcoming`, id's N1, ...)
  komen alleen uit de database.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Iterator
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    Blog,
    CompetitorAnalysisKeyword,
    ContentBrief,
    CustomerQuickWins,
    CustomerWebsite,
    MonthlyReport as MonthlyReportRow,
    SiteChange,
)
from app.features.competitor_analysis.mappers import _model
from app.features.customers import rankings
from app.features.customers.search_console_insights import STATE_MESSAGES as GSC_MESSAGES
from app.features.customers.search_console_insights import totals_of
from app.features.launch_checklist.services import prt_enrich
from app.features.launch_checklist.services.gsc_enrich import resolve_property
from app.features.launch_checklist.services.scan_recovery import as_utc
from app.features.monthly_report.mappers import leads_from, manual_of
from app.features.monthly_report.schemas import (
    Manual,
    Metric,
    Metrics,
    Period,
    QuickWin,
    ReportData,
    Upcoming,
    Work,
    WorkBlog,
    WorkBrief,
    WorkExample,
    WorkGroup,
)
from app.features.monthly_report.services.periods import (
    gsc_spans,
    month_bounds_utc,
    previous_month,
    prt_window_open,
    today_local,
)
from app.features.site_changes.services.changes import APPROVED, DONE, TOPIC_LABELS, TOPIC_ORDER
from app.services.search_console import client as gsc
from app.services.search_console import sites as gsc_sites
from app.services.search_console.client import SearchConsoleServiceError
from app.worker._common import split_markdown_title

logger = logging.getLogger(__name__)

PRT_TIMEOUT_SECONDS = 15.0
TOP_POSITION = 10
MAX_EXAMPLES = 5
MAX_UPCOMING_BRIEFS = 5
MAX_QUICK_WINS = 5
QUICK_WINS_MAX_AGE = timedelta(days=45)
TITLE_MAX = 120

MESSAGES: dict[str, str] = {
    **GSC_MESSAGES,
    "no_data": "Search Console heeft nog geen cijfers voor deze maand.",
    "out_of_window": "ProRankTracker toont alleen de stand van nu; dit cijfer wordt alleen vastgelegd als het "
                     "rapport in de maand zelf of tot 7 dagen erna wordt gemaakt.",
    "not_connected": "GA4 niet gekoppeld; vul het aantal aanvragen met de hand in.",
    "unexpected": "Onverwachte fout bij het ophalen.",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _delta(value: int | None, previous: int | None) -> int | None:
    return value - previous if value is not None and previous is not None else None


def _period(start: date, end: date, *, complete: bool = True) -> Period:
    return Period(start=start.isoformat(), end=end.isoformat(), days=(end - start).days + 1, complete=complete)


# --- Bezoekers uit Google ------------------------------------------------------------------


def _gsc_failed(exc: SearchConsoleServiceError, **extra: Any) -> Metric:
    if exc.code in ("not_configured", "token_expired"):
        return Metric(state=exc.code, message=MESSAGES[exc.code], **extra)
    return Metric(state="error", message=str(exc)[:500], **extra)


def _clicks(customer: CustomerWebsite, spans: dict[str, Any]) -> Metric:
    """Klikken van de maand; zie `customer_insights` voor de toestanden."""
    base_url = str(customer.base_url or "")
    if not gsc.is_configured():
        return Metric(state="not_configured", message=MESSAGES["not_configured"])
    try:
        sites = gsc_sites.cached_sites()
    except SearchConsoleServiceError as exc:
        return _gsc_failed(exc)
    site_url, source = resolve_property(customer.gsc_property, base_url, sites)
    if not site_url:
        return Metric(state="no_property", message=MESSAGES["no_property"])

    retried = False
    while True:
        prop = {"property": site_url, "property_source": source}
        try:
            current = gsc.search_analytics(site_url, *spans["current"])
            break
        except SearchConsoleServiceError as exc:
            if exc.code not in ("forbidden", "not_found") or retried:
                return _gsc_failed(exc, **prop)
            # Geen toegang of niet gevonden: kijk met een verse lijst of de property er nog is.
            retried = True
            try:
                sites = gsc_sites.cached_sites(refresh=True)
            except SearchConsoleServiceError:
                return _gsc_failed(exc, **prop)
            if source == "manual":
                if site_url not in {site["site_url"] for site in sites}:
                    return Metric(state="property_inaccessible", message=MESSAGES["property_inaccessible"], **prop)
                return _gsc_failed(exc, **prop)
            new_url, new_source = resolve_property(None, base_url, sites)
            if not new_url:
                return Metric(state="no_property", message=MESSAGES["no_property"])
            if new_url == site_url:
                return _gsc_failed(exc, **prop)
            site_url, source = new_url, new_source

    totals = totals_of(current)
    try:
        previous_rows = gsc.search_analytics(site_url, *spans["previous"])
        # Geen rijen = Search Console heeft over die periode niets (bijv. een property die pas
        # daarna is toegevoegd): onbekend, geen 0. Anders staat er "van 0 naar 35" in het rapport.
        previous: int | None = totals_of(previous_rows)["clicks"] if previous_rows else None
    except SearchConsoleServiceError as exc:
        logger.info("Maandrapport: vorige periode niet opgehaald (%s)", exc.code)
        previous = None
    value = totals["clicks"]
    return Metric(
        state="ok",
        value=value,
        previous=previous,
        delta=_delta(value, previous),
        delta_pct=round((value - previous) / previous * 100, 1) if previous else None,
        impressions=totals["impressions"],
        property=site_url,
        property_source=source,
    )


def clicks_metric(
    customer: CustomerWebsite, month: str, today: date
) -> tuple[Metric, Period | None, Period | None]:
    """(tegel, periode, vergelijkingsperiode). Zonder dagen in Search Console: `no_data`."""
    spans = gsc_spans(month, today, settings.gsc_data_lag_days)
    if spans is None:
        return Metric(state="no_data", message=MESSAGES["no_data"]), None, None
    period = _period(*spans["current"], complete=spans["complete"])
    previous = _period(*spans["previous"])
    try:
        metric = _clicks(customer, spans)
    except Exception:  # noqa: BLE001 - een bron mag het rapport nooit laten mislukken
        logger.exception("Maandrapport: Search Console onverwacht mislukt")
        metric = Metric(state="error", message=MESSAGES["unexpected"])
    return metric, period, previous


# --- ProRankTracker ------------------------------------------------------------------------


def top10_metric(base_url: str, *, client: httpx.Client | None = None, now: datetime | None = None) -> Metric:
    """Aantal gevolgde zoekwoorden in de top 10, ontdubbeld per zoekwoord (beste positie)."""
    state, rows, message = rankings.organic_rows(base_url, client=client)
    if state != "ok":
        return Metric(state=state if state in ("not_configured", "not_tracked") else "error",
                      message=message or rankings.STATE_MESSAGES.get(state))
    best: dict[str, int | None] = {}
    best_month: dict[str, int | None] = {}
    for row in rows:
        key = rankings.keyword_key(row.get("name"))
        if not key:
            continue
        for target, raw in ((best, row.get("rank")), (best_month, row.get("monthagorank"))):
            rank = rankings.position(raw)
            if rank is not None and (target.get(key) is None or rank < target[key]):
                target[key] = rank
            else:
                target.setdefault(key, None)
    value = sum(1 for rank in best.values() if rank is not None and rank <= TOP_POSITION)
    previous = None
    if any("monthagorank" in row for row in rows):
        previous = sum(1 for rank in best_month.values() if rank is not None and rank <= TOP_POSITION)
    return Metric(state="ok", value=value, previous=previous, delta=_delta(value, previous), total=len(best),
                  captured_at=now or _now())


def _captured_at(value: Any) -> datetime | None:
    try:
        return as_utc(datetime.fromisoformat(str(value))) if value else None
    except ValueError:
        return None


def ai_metric(
    base_url: str,
    *,
    client: httpx.Client | None = None,
    previous_month_data: ReportData | None = None,
    now: datetime | None = None,
) -> Metric:
    """Prompts met een vermelding van de klant / alle getrackte prompts."""
    snapshot = prt_enrich.collect(base_url, client=client)
    state = snapshot.get("state")
    if state != "ok":
        return Metric(state=state if state in ("not_configured", "not_tracked") else "error",
                      message=snapshot.get("message"))
    prompts = [p for p in snapshot.get("prompts") or [] if isinstance(p, dict)]
    totals = snapshot.get("totals") if isinstance(snapshot.get("totals"), dict) else {}
    value = sum(1 for p in prompts if (p.get("mentions") or 0) > 0)
    previous = None
    if previous_month_data is not None and previous_month_data.metrics.ai_mentions.state == "ok":
        previous = previous_month_data.metrics.ai_mentions.value
    return Metric(
        state="ok",
        value=value,
        previous=previous,
        delta=_delta(value, previous),
        total=int(totals.get("prompts") or len(prompts)),
        captured_at=_captured_at(snapshot.get("fetched_at")) or now or _now(),
    )


def _guarded(name: str, fetch: Any) -> Metric:
    try:
        return fetch()
    except Exception:  # noqa: BLE001 - een bron mag het rapport nooit laten mislukken
        logger.exception("Maandrapport: %s onverwacht mislukt", name)
        return Metric(state="error", message=MESSAGES["unexpected"])


def _keep_ok(new: Metric, old: Metric | None) -> Metric:
    """Een eerder vastgelegd `ok`-cijfer blijft staan als het nieuwe geen `ok` is."""
    return old if old is not None and old.state == "ok" and new.state != "ok" else new


# --- Aanvragen -----------------------------------------------------------------------------


def leads_metric(manual: Manual | None, previous_month_row: MonthlyReportRow | None) -> Metric:
    leads = leads_from(manual, manual_of(previous_month_row))
    if leads.value is None:
        return Metric(state="not_connected", message=MESSAGES["not_connected"], previous=leads.previous,
                      previous_source=leads.previous_source)
    return Metric(state="manual", value=leads.value, previous=leads.previous,
                  delta=_delta(leads.value, leads.previous), previous_source=leads.previous_source)


# --- Wat we deden en Volgende maand ---------------------------------------------------------


def _path(url: str | None) -> str | None:
    if not url:
        return None
    return urlparse(url).path or "/"


def _groups(changes: Iterable[SiteChange], ids: Iterator[str], *, verified: bool) -> list[WorkGroup]:
    """Aanpassingen per onderwerp, in de vaste volgorde van `TOPICS`."""
    by_topic: OrderedDict[str, list[SiteChange]] = OrderedDict()
    for change in changes:
        by_topic.setdefault(change.topic or "other", []).append(change)
    groups = []
    for topic in sorted(by_topic, key=lambda t: (TOPIC_ORDER.get(t, len(TOPIC_ORDER)), t)):
        items = by_topic[topic]
        groups.append(WorkGroup(
            id=next(ids),
            topic=topic,
            label=TOPIC_LABELS.get(topic, topic),
            count=len(items),
            pages=len({item.url_key for item in items}),
            verified=sum(1 for item in items if item.verified is True) if verified else None,
            examples=[WorkExample(title=item.title, path=_path(item.page_url)) for item in items[:MAX_EXAMPLES]],
        ))
    return groups


def _counter(prefix: str) -> Iterator[str]:
    number = 0
    while True:
        number += 1
        yield f"{prefix}{number}"


def _blog_title(content: str | None) -> str:
    title, _body = split_markdown_title(content or "")
    if not title:
        line = next((ln.strip().lstrip("#").strip() for ln in (content or "").splitlines() if ln.strip()), "")
        title = line or "Blog zonder titel"
    return title if len(title) <= TITLE_MAX else title[: TITLE_MAX - 1].rstrip() + "…"


def work_done(db: Session, customer_id: str, month: str) -> Work:
    """Doorgevoerde aanpassingen, gepubliceerde blogs en afgeronde briefs in de maand."""
    start, end = month_bounds_utc(month)
    ids = _counter("W")
    changes = (
        db.query(SiteChange)
        .filter(SiteChange.customer_website_id == customer_id, SiteChange.status == DONE,
                SiteChange.done_at >= start, SiteChange.done_at < end)
        .order_by(SiteChange.done_at.asc(), SiteChange.id.asc())
        .all()
    )
    groups = _groups(changes, ids, verified=True)
    blogs = (
        db.query(Blog)
        .filter(Blog.customer_website_id == customer_id, Blog.published_at >= start, Blog.published_at < end)
        .order_by(Blog.published_at.asc(), Blog.id.asc())
        .all()
    )
    work_blogs = [
        WorkBlog(id=next(ids), title=_blog_title(blog.content),
                 published_at=today_local(as_utc(blog.published_at)).isoformat(), url=blog.placement_url or None)
        for blog in blogs
    ]
    briefs = (
        db.query(ContentBrief, CompetitorAnalysisKeyword)
        .join(CompetitorAnalysisKeyword, CompetitorAnalysisKeyword.id == ContentBrief.keyword_id)
        .filter(ContentBrief.customer_website_id == customer_id, ContentBrief.status == "completed",
                ContentBrief.completed_at >= start, ContentBrief.completed_at < end)
        .order_by(ContentBrief.completed_at.asc(), ContentBrief.id.asc())
        .all()
    )
    work_briefs = [
        WorkBrief(id=next(ids), keyword=keyword.keyword, new_page=not (keyword.target_url or "").strip())
        for _brief, keyword in briefs
    ]
    return Work(changes=groups, blogs=work_blogs, briefs=work_briefs)


def upcoming(db: Session, customer_id: str, month: str, *, now: datetime | None = None) -> Upcoming:
    """Openstaand werk: goedgekeurde aanpassingen, briefs zonder pagina en quick wins.

    Alleen de database: de quick wins komen uit de laatst opgeslagen Ahrefs-stand
    (`CustomerQuickWins.rows`), niet uit `quick_wins.load` (dat kost Ahrefs-units).
    """
    now = now or _now()
    ids = _counter("N")
    approved = (
        db.query(SiteChange)
        .filter(SiteChange.customer_website_id == customer_id, SiteChange.status == APPROVED)
        .order_by(SiteChange.reviewed_at.asc(), SiteChange.id.asc())
        .all()
    )
    groups = _groups(approved, ids, verified=False)

    since, _end = month_bounds_utc(previous_month(month))
    briefs = (
        db.query(ContentBrief, CompetitorAnalysisKeyword)
        .join(CompetitorAnalysisKeyword, CompetitorAnalysisKeyword.id == ContentBrief.keyword_id)
        .filter(ContentBrief.customer_website_id == customer_id, ContentBrief.status == "completed",
                ContentBrief.completed_at >= since)
        .order_by(ContentBrief.completed_at.desc(), ContentBrief.id.asc())
        .all()
    )
    without_page = [keyword for _brief, keyword in briefs if not (keyword.target_url or "").strip()]
    open_briefs = [
        WorkBrief(id=next(ids), keyword=keyword.keyword, new_page=True)
        for keyword in without_page[:MAX_UPCOMING_BRIEFS]
    ]

    wins: list[QuickWin] = []
    record = db.get(CustomerQuickWins, customer_id)
    fetched_at = as_utc(record.fetched_at) if record is not None else None
    if record is not None and fetched_at is not None and now - fetched_at <= QUICK_WINS_MAX_AGE:
        for row in record.rows if isinstance(record.rows, list) else []:
            if not isinstance(row, dict) or row.get("kans") != "hoog" or not row.get("keyword"):
                continue
            wins.append(QuickWin(id=next(ids), keyword=str(row["keyword"]),
                                 position=_int(row.get("position")), volume=_int(row.get("volume"))))
            if len(wins) >= MAX_QUICK_WINS:
                break
    return Upcoming(approved_changes=groups, briefs=open_briefs, quick_wins=wins)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# --- alles samen ---------------------------------------------------------------------------


def collect(
    db: Session,
    customer: CustomerWebsite,
    month: str,
    *,
    today: date | None = None,
    previous_data: Any = None,
    previous_month_row: MonthlyReportRow | None = None,
    manual: Manual | dict[str, Any] | None = None,
) -> ReportData:
    """Momentopname voor het rapport van `month`.

    `previous_data`: `data` van dit rapport (bij opnieuw genereren), voor het vasthouden van
    eerder vastgelegde ProRankTracker-cijfers. `previous_month_row`: het rapport van de maand
    ervoor (aanvragen en AI-vermeldingen). `manual`: de handmatige cijfers van dit rapport.
    """
    today = today or today_local()
    now = _now()
    base_url = str(customer.base_url or "")
    old = previous_data if isinstance(previous_data, ReportData) else _model(ReportData, previous_data)
    previous_month_data = _model(ReportData, previous_month_row.data) if previous_month_row is not None else None
    if isinstance(manual, dict):
        manual = _model(Manual, manual)

    clicks, period, previous_period = clicks_metric(customer, month, today)

    if prt_window_open(month, today):
        with httpx.Client(timeout=PRT_TIMEOUT_SECONDS) as client:
            top10 = _guarded("top 10", lambda: top10_metric(base_url, client=client, now=now))
            ai = _guarded("AI-vermeldingen", lambda: ai_metric(
                base_url, client=client, previous_month_data=previous_month_data, now=now))
    else:
        top10 = Metric(state="out_of_window", message=MESSAGES["out_of_window"])
        ai = Metric(state="out_of_window", message=MESSAGES["out_of_window"])
    if old is not None:
        top10 = _keep_ok(top10, old.metrics.top10)
        ai = _keep_ok(ai, old.metrics.ai_mentions)

    return ReportData(
        month=month,
        collected_at=now,
        period=period,
        previous=previous_period,
        metrics=Metrics(clicks=clicks, top10=top10, leads=leads_metric(manual, previous_month_row),
                        ai_mentions=ai),
        work=work_done(db, customer.id, month),
        upcoming=upcoming(db, customer.id, month, now=now),
    )


__all__ = [
    "MESSAGES",
    "PRT_TIMEOUT_SECONDS",
    "ai_metric",
    "clicks_metric",
    "collect",
    "leads_metric",
    "top10_metric",
    "upcoming",
    "work_done",
]
