"""Het bureau-overzicht: KPI's, signalen ("Vraagt aandacht") en de tabel met klanten.

`build_overview` leest de klanten, de positie-momentopnames, de open kaarten van de werkvoorraad,
de nieuwste scan per (klant, fase), de sitemap-monitor en de maandrapporten van de vorige maand.
Search Console wordt één keer opgevraagd (`cached_sites`, tien minuten bewaard) en daarna per
klant opgezocht met `resolve_property`. De signalen zelf staan in `signals.py`.

Vóór het tellen van de open taken wordt het bord gesynchroniseerd (`sync_board`), zodat de
tellers gelijk zijn aan de werkvoorraad. Die synchronisatie commit; een fout daarin wordt gelogd
en teruggedraaid, en het overzicht gaat door met de opgeslagen kaarten.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session, load_only

from app.db.models import (
    CustomerRankSnapshot,
    CustomerWebsite,
    LaunchScan,
    LaunchSitemapSnapshot,
    MonthlyReport,
    WorkItem,
)
from app.features.agency_overview.services import signals as sig
from app.features.agency_overview.services.rank_snapshots import is_token_error
from app.features.customers.rankings import STATE_MESSAGES as PRT_STATE_MESSAGES
from app.features.launch_checklist.services.checklist_view import latest_scans_by_customer
from app.features.launch_checklist.services.golive_checklist import MONITOR_PHASE
from app.features.launch_checklist.services.gsc_enrich import resolve_property
from app.features.launch_checklist.services.scan_recovery import as_utc
from app.features.monthly_report.services.periods import month_of, previous_month
from app.features.work_queue.services.board import sync_board
from app.features.work_queue.services.types import (
    ACTIVE_STATUSES,
    SEVERITY_HIGH,
    STATUS_REVIEW,
    STATUS_TODO,
)
from app.services.proranktracker import client as prt
from app.services.search_console import client as gsc
from app.services.search_console.client import SearchConsoleServiceError
from app.services.search_console.sites import cached_sites

logger = logging.getLogger(__name__)

try:
    _TZ: Any = ZoneInfo("Europe/Amsterdam")
except ZoneInfoNotFoundError:  # image zonder tz-database
    _TZ = timezone.utc

# Fases van de scan die een signaal "Storing" geven als de nieuwste scan mislukt is.
SCAN_PHASES: tuple[int, ...] = tuple(range(1, MONITOR_PHASE + 1))
# Fouten van `cached_sites` die voor het hele bureau gelden (geen token, token verlopen, geen
# toegang tot de API). Een andere fout (timeout, verbinding) slaat Search Console deze keer over.
GSC_BUREAU_CODES: frozenset[str] = frozenset({"not_configured", "token_expired", "forbidden"})

GSC_NOT_CONFIGURED = ("Search Console is niet gekoppeld: GSC_CLIENT_ID, GSC_CLIENT_SECRET of "
                      "GSC_REFRESH_TOKEN ontbreekt in de backend-configuratie")
PRT_TOKEN_REFUSED = "ProRankTracker weigert het API-token (ongeldig of verlopen)"

_SCAN_COLUMNS = (
    LaunchScan.id, LaunchScan.customer_website_id, LaunchScan.phase, LaunchScan.status,
    LaunchScan.created_at, LaunchScan.updated_at, LaunchScan.completed_at,
)


def _clock(today: date | datetime | None) -> tuple[datetime, date]:
    """(nu in UTC, datum in Amsterdam). Een datum zonder tijd geldt als 12:00 Amsterdamse tijd."""
    if today is None:
        now = datetime.now(timezone.utc)
    elif isinstance(today, datetime):
        now = as_utc(today)
    else:
        now = datetime.combine(today, time(12, 0), tzinfo=_TZ).astimezone(timezone.utc)
    return now, now.astimezone(_TZ).date()


def _local_date(value: datetime | None) -> date | None:
    value = as_utc(value)
    return value.astimezone(_TZ).date() if value is not None else None


def _iso(value: datetime | None) -> str | None:
    value = as_utc(value)
    return value.isoformat() if value is not None else None


# --- Search Console en ProRankTracker ----------------------------------------------------

def _search_console(
    customers: list[CustomerWebsite],
) -> tuple[sig.Signal | None, dict[str, sig.Problem]]:
    """(bureaubreed signaal of None, probleem per klant-id)."""
    if not gsc.is_configured():
        return sig.bureau_signal(sig.BUREAU_SEARCH_CONSOLE, GSC_NOT_CONFIGURED), {}
    try:
        sites = cached_sites()
    except SearchConsoleServiceError as exc:
        if exc.code in GSC_BUREAU_CODES:
            return sig.bureau_signal(sig.BUREAU_SEARCH_CONSOLE, str(exc).rstrip(".")), {}
        logger.warning("Bureau-overzicht: Search Console-properties niet opgehaald (%s): %s", exc.code, exc)
        return None, {}
    site_urls = {site.get("site_url") for site in sites}
    problems: dict[str, sig.Problem] = {}
    for customer in customers:
        prop, source = resolve_property(customer.gsc_property, str(customer.base_url or ""), sites)
        if not prop:
            problems[customer.id] = sig.Problem(sig.GSC_NO_PROPERTY, sig.LINK_CUSTOMER_PROFILE)
        elif source == "manual" and prop not in site_urls:
            problems[customer.id] = sig.Problem(sig.GSC_PROPERTY_INACCESSIBLE, sig.LINK_CUSTOMER_PROFILE)
    return None, problems


def _proranktracker(
    snapshots: dict[str, CustomerRankSnapshot],
) -> tuple[sig.Signal | None, dict[str, sig.Problem]]:
    """(bureaubreed signaal of None, probleem per klant-id) uit de momentopnames."""
    if not prt.is_configured():
        message = PRT_STATE_MESSAGES["not_configured"].rstrip(".")
        return sig.bureau_signal(sig.BUREAU_PRORANKTRACKER, message), {}
    errors = {cid: snap for cid, snap in snapshots.items() if snap.state == "error"}
    if any(is_token_error(snap.message) for snap in errors.values()):
        return sig.bureau_signal(sig.BUREAU_PRORANKTRACKER, PRT_TOKEN_REFUSED), {}
    return None, {cid: sig.Problem(sig.PRT_ERROR, sig.LINK_CUSTOMER_HOME) for cid in errors}


# --- scans en sitemap-monitor -------------------------------------------------------------

def _scan_problems(db: Session, customer_ids: set[str]) -> dict[str, list[sig.Problem]]:
    """Per klant de mislukte scans (nieuwste scan per fase staat op `failed`) en de
    sitemap-monitor die aan staat maar een fout gaf, in die volgorde."""
    problems: dict[str, list[sig.Problem]] = {}
    for phase in SCAN_PHASES:
        latest = latest_scans_by_customer(db, phase=phase, options=(load_only(*_SCAN_COLUMNS),))
        for customer_id, scan in latest.items():
            if scan.status != "failed" or customer_id not in customer_ids:
                continue
            day = _local_date(scan.updated_at or scan.completed_at or scan.created_at)
            problems.setdefault(customer_id, []).append(
                sig.Problem(sig.scan_failed_text(phase, day), sig.LINK_SEO_GEO))

    monitor_rows = (
        db.query(LaunchSitemapSnapshot.customer_website_id, LaunchSitemapSnapshot.checked_at)
        .join(CustomerWebsite, CustomerWebsite.id == LaunchSitemapSnapshot.customer_website_id)
        .filter(
            CustomerWebsite.sitemap_monitor_enabled.is_(True),
            LaunchSitemapSnapshot.last_error.isnot(None),
            LaunchSitemapSnapshot.last_error != "",
        )
        .all()
    )
    for customer_id, checked_at in monitor_rows:
        if customer_id in customer_ids:
            problems.setdefault(customer_id, []).append(
                sig.Problem(sig.monitor_failed_text(_local_date(checked_at)), sig.LINK_SEO_GEO))
    return problems


# --- werkvoorraad -------------------------------------------------------------------------

def _work(db: Session, now: datetime) -> tuple[Counter, Counter, Counter, Counter]:
    """(open kaarten per klant, waarvan ernst hoog, vastgelopen in Review, vastgelopen in Te doen)."""
    open_tasks: Counter = Counter()
    open_high: Counter = Counter()
    review_stale: Counter = Counter()
    todo_stale: Counter = Counter()
    review_limit = now - timedelta(days=sig.REVIEW_STALE_DAYS)
    todo_limit = now - timedelta(days=sig.TODO_HIGH_STALE_DAYS)
    rows = (
        db.query(WorkItem.customer_website_id, WorkItem.status, WorkItem.severity,
                 WorkItem.created_at, WorkItem.updated_at)
        .filter(WorkItem.status.in_(ACTIVE_STATUSES))
        .all()
    )
    for customer_id, status, severity, created_at, updated_at in rows:
        open_tasks[customer_id] += 1
        if severity == SEVERITY_HIGH:
            open_high[customer_id] += 1
        if status == STATUS_REVIEW and updated_at is not None and as_utc(updated_at) < review_limit:
            review_stale[customer_id] += 1
        elif (status == STATUS_TODO and severity == SEVERITY_HIGH and created_at is not None
              and as_utc(created_at) < todo_limit):
            todo_stale[customer_id] += 1
    return open_tasks, open_high, review_stale, todo_stale


# --- overzicht ----------------------------------------------------------------------------

def _customer_row(customer: CustomerWebsite, snapshot: CustomerRankSnapshot | None,
                  open_tasks: int, signal_count: int) -> dict[str, Any]:
    keywords = top10 = top10_delta = None
    state = snapshot.state if snapshot is not None else "missing"
    if snapshot is not None and state == "ok":
        keywords, top10 = snapshot.keywords, snapshot.top10
        if top10 is not None and snapshot.top10_month_ago is not None:
            top10_delta = top10 - snapshot.top10_month_ago
    return {
        "id": customer.id,
        "name": customer.name or "",
        "rank_state": state,
        "keywords": keywords,
        "top10": top10,
        "top10_delta": top10_delta,
        "open_tasks": open_tasks,
        "signal_count": signal_count,
    }


def build_overview(db: Session, today: date | datetime | None = None) -> dict[str, Any]:
    """Het antwoord van `GET /api/agency-overview/overview` als dict (zie `schemas.py`).

    `today` maakt de datumregels testbaar: een datum (geldt als 12:00 in Amsterdam) of een
    tijdstip (naïef = UTC). Zonder: nu.
    """
    now, local_today = _clock(today)

    # Eerst synchroniseren: dat commit (of draait terug) en laat de sessie daarna leeg achter.
    sync_board(db, now)

    def _existed_before(customer: Any, day: date) -> bool:
        """Klant bestond al vóór `day` (Amsterdam); een klant van deze maand heeft geen rapport over de vorige."""
        created = getattr(customer, "created_at", None)
        if not isinstance(created, datetime):
            return True
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return created.astimezone(_TZ).date() < day

    customers = (
        db.query(CustomerWebsite)
        .options(load_only(CustomerWebsite.id, CustomerWebsite.name, CustomerWebsite.base_url,
                           CustomerWebsite.gsc_property, CustomerWebsite.sitemap_monitor_enabled,
                           CustomerWebsite.created_at))
        .all()
    )
    customer_ids = {c.id for c in customers}
    snapshots = {s.customer_website_id: s for s in db.query(CustomerRankSnapshot).all()}
    open_tasks, open_high, review_stale, todo_stale = _work(db, now)
    scan_problems = _scan_problems(db, customer_ids)
    report_month = previous_month(month_of(local_today))
    report_status = dict(
        db.query(MonthlyReport.customer_website_id, MonthlyReport.status)
        .filter(MonthlyReport.month == report_month)
        .all()
    )
    gsc_bureau, gsc_problems = _search_console(customers)
    prt_bureau, prt_problems = _proranktracker(snapshots)

    signals: list[sig.Signal] = [s for s in (prt_bureau, gsc_bureau) if s is not None]
    for customer in customers:
        cid, name = customer.id, customer.name or ""
        snapshot = snapshots.get(cid)
        problems = list(scan_problems.get(cid, []))
        problems.extend(p for p in (prt_problems.get(cid), gsc_problems.get(cid)) if p is not None)
        candidates = (
            sig.drop_signal(cid, name, snapshot.drops) if snapshot is not None and snapshot.state == "ok" else None,
            sig.failure_signal(cid, name, problems),
            sig.work_signal(cid, name, review_stale[cid], todo_stale[cid]),
            sig.report_signal(cid, name, month=report_month, status=report_status.get(cid), today=local_today)
            if _existed_before(customer, local_today.replace(day=1)) else None,
        )
        signals.extend(s for s in candidates if s is not None)
    signals = sig.sort_signals(signals)

    per_customer = Counter(s.customer_id for s in signals if s.customer_id)
    rows = [
        _customer_row(c, snapshots.get(c.id), open_tasks[c.id], per_customer[c.id]) for c in customers
    ]
    rows.sort(key=lambda r: (-r["signal_count"], -r["open_tasks"], r["name"].casefold(), r["id"]))

    fetched = [as_utc(s.fetched_at) for s in snapshots.values()
               if s.state == "ok" and s.fetched_at is not None and s.customer_website_id in customer_ids]
    return {
        "generated_at": _iso(now),
        "week": local_today.isocalendar()[1],
        "rankings_fetched_at": _iso(min(fetched)) if fetched else None,
        "kpis": {
            "customers": len(customers),
            "customers_attention": sum(1 for r in rows if r["signal_count"] > 0),
            "open_tasks": sum(open_tasks[c.id] for c in customers),
            "open_tasks_high": sum(open_high[c.id] for c in customers),
        },
        "signals": [s.as_dict() for s in signals],
        "customers": rows,
    }


__all__ = ["build_overview"]
