"""Celery-taken: dagelijkse sitemap-monitor (livegang, scans met phase = 6).

Celery beat start elke ochtend `run_sitemap_monitor_dispatch_task`; die zet per
ingeschakelde klant met een voltooide nulmeting één `run_sitemap_monitor_task`
op de `audit`-queue. Die vergelijkt de sitemap met de vorige stand
(`LaunchSitemapSnapshot`) en scant alleen nieuwe en gewijzigde pagina's:

- fase-1-regels per pagina (`generate_page_issues`), met signalen en paginatype;
- de vaste fase-3-contentchecks, beoordeeld tegen de content van de laatste
  fase-3-scan (dubbele titels, inkomende interne links); zonder AI-voorstellen.

Alles komt in één doorlopende monitor-scan per klant: pagina's en actiepunten
van een opnieuw gescande URL worden vervangen, met behoud van status en
Monday-koppeling. Het enige AI-gebruik is de goedkope paginatype-classificatie
van `apply_page_types` voor pagina's die de regels niet kunnen plaatsen.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse

from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger
from sqlalchemy.orm import load_only

from app.core.config import settings
from app.db.models import (
    CustomerWebsite,
    LaunchContentPage,
    LaunchScan,
    LaunchScanIssue,
    LaunchScanPage,
    LaunchSitemapSnapshot,
)
from app.db.session import SessionLocal
from app.features.launch_checklist.schemas import ACTIVE_STATUSES
from app.features.launch_checklist.services.checklist_view import (
    latest_completed_scan,
    manual_states_by_customer,
)
from app.features.launch_checklist.services.content_checks import evaluate_pages, problem_count
from app.features.launch_checklist.services.content_rebuild import recover_stale_analysis
from app.features.launch_checklist.services.discovery import discover_from_sitemaps, root_domain_of, url_key
from app.features.launch_checklist.services.geo_rebuild import apply_page_types
from app.features.launch_checklist.services.golive_checklist import MONITOR_PHASE
from app.features.launch_checklist.services.inventory import (
    _INCONCLUSIVE_STATUSES,
    PageRecord,
    _path_of,
    run_inventory,
)
from app.features.launch_checklist.services.issue_state import (
    carried_state_from_rows,
    issue_key,
    with_carried_state,
)
from app.features.launch_checklist.services.issues import (
    _is_ok_html,
    generate_content_issues,
    generate_page_issues,
)
from app.features.launch_checklist.services.scan_recovery import heartbeat, recover_stale_scan
from app.features.launch_checklist.services.sitemap_monitor import (
    MonitorPlan,
    acquire_lock,
    change_items,
    drop_covered_f1_issues,
    merge_recent_changes,
    monitor_scan,
    plan_run,
    release_lock,
    retry_later,
)
from app.features.launch_checklist.worker.content_scan import _check_links, _fetch_content
from app.features.launch_checklist.worker.launch_scan import _record_to_row
from app.features.launch_checklist.worker.quarterly_scan import _copy_page_types, _refetch
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)

STOPPED_STATUSES = {"canceled", "deleted"}
INTERNAL_LINKS_KEY = "c3_internal_links"
SKIPPED_MESSAGE = (
    "Overgeslagen: er liep een andere scan voor deze klant. "
    "De wijzigingen komen bij de volgende run aan bod."
)
MAX_FAILED_IN_MESSAGE = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_stopped(scan_id: str) -> bool:
    with SessionLocal() as db:
        row = db.query(LaunchScan.status).filter(LaunchScan.id == scan_id).first()
        return row is None or str(row[0] or "").lower() in STOPPED_STATUSES


def _update(scan_id: str, **fields: Any) -> None:
    """Werk de scan bij, behalve als hij inmiddels geannuleerd is."""
    fields["updated_at"] = _now()
    with SessionLocal() as db:
        db.query(LaunchScan).filter(
            LaunchScan.id == scan_id, LaunchScan.status != "canceled"
        ).update(fields, synchronize_session=False)
        db.commit()


def _save_snapshot(customer_id: str, **fields: Any) -> None:
    """Snapshot van de klant bijwerken (of aanmaken)."""
    now = _now()
    with SessionLocal() as db:
        snapshot = db.get(LaunchSitemapSnapshot, customer_id)
        if snapshot is None:
            snapshot = LaunchSitemapSnapshot(
                customer_website_id=customer_id, entries={}, recent_changes=[], created_at=now,
            )
            db.add(snapshot)
        for key, value in fields.items():
            setattr(snapshot, key, value)
        snapshot.updated_at = now
        db.commit()


# --- dispatcher --------------------------------------------------------------------

@celery_app.task(name="app.worker.tasks.run_sitemap_monitor_dispatch_task")
def run_sitemap_monitor_dispatch_task() -> list[str]:
    """Zet per ingeschakelde klant met een voltooide nulmeting een monitor-run klaar."""
    if not settings.sitemap_monitor_enabled:
        logger.info("Sitemap-monitor staat uit (SITEMAP_MONITOR_ENABLED=false).")
        return []
    with SessionLocal() as db:
        ids = [
            row[0]
            for row in db.query(CustomerWebsite.id)
            .filter(CustomerWebsite.sitemap_monitor_enabled.is_(True))
            .order_by(CustomerWebsite.name.asc())
            .all()
        ]
        queued = [cid for cid in ids if latest_completed_scan(db, cid, 1) is not None]
    for customer_id in queued:
        run_sitemap_monitor_task.delay(customer_id)
    logger.info("Sitemap-monitor: %d klant(en) ingepland.", len(queued))
    return queued


# --- run per klant -----------------------------------------------------------------

def _prepare_monitor_scan(customer_id: str, base_url: str, user_id: str, total: int) -> str:
    """Monitor-scan van de klant ophalen of aanmaken en op 'inventory' zetten."""
    now = _now()
    with SessionLocal() as db:
        scan = monitor_scan(db, customer_id)
        if scan is None:
            scan = LaunchScan(
                id=str(uuid.uuid4()),
                customer_website_id=customer_id,
                phase=MONITOR_PHASE,
                status="inventory",
                base_url=base_url,
                discovery_source="sitemap",
                total_urls=total,
                inventoried_urls=0,
                failed_urls=0,
                max_pages=settings.sitemap_monitor_max_pages_per_run,
                vitals_max_pages=0,
                vitals_total=0,
                vitals_measured=0,
                created_by=user_id,
                created_at=now,
                updated_at=now,
            )
            db.add(scan)
        else:
            # Direct (niet via _update): een eerder geannuleerde monitor-scan moet weer kunnen lopen.
            scan.status = "inventory"
            scan.base_url = base_url
            scan.total_urls = total
            scan.inventoried_urls = 0
            scan.failed_urls = 0
            scan.error_message = None
            scan.warnings = []
            scan.updated_at = now
        db.commit()
        return scan.id


def _known_page_types(db: Any, scan_id: str, nulmeting_id: str, keys: set[str]) -> list[LaunchScanPage]:
    """Pagina's met een bekend paginatype voor deze URL's: eerst uit de monitor, dan uit de nulmeting."""
    columns = load_only(LaunchScanPage.url, LaunchScanPage.page_type, LaunchScanPage.page_type_source)
    out: list[LaunchScanPage] = []
    for source_id in (nulmeting_id, scan_id):  # monitor als laatste: _copy_page_types laat de laatste winnen
        out.extend(
            p for p in db.query(LaunchScanPage).options(columns).filter(
                LaunchScanPage.scan_id == source_id, LaunchScanPage.page_type.isnot(None))
            if url_key(p.url) in keys
        )
    return out


def _not_scanned_reason(rec: PageRecord) -> str | None:
    """Waarom een doel-URL niet als gescand telt; None = wel gescand.

    Grens: een time-out, verbindingsfout of blokkade/tijdelijke weigering (401, 403, 429,
    503: dezelfde 'onbeslisbare' statussen als de rest van de scan) zegt niets over de
    pagina, dus die probeert de volgende run opnieuw. Een gewone 404, 410, andere 5xx,
    redirectlus of ongeldig adres is wél een bevinding en levert actiepunten op.
    """
    error = rec.error or ""
    if error == "Timeout" or error.startswith("Verbindingsfout"):
        return error
    status = rec.final_status if rec.final_status is not None else rec.status_code
    if status in _INCONCLUSIVE_STATUSES:
        return f"HTTP {status}"
    return None


def _site_path(url: str) -> str:
    """url_key zonder host: www/zonder-www maakt voor de vergelijking met de sitemap niet uit."""
    key = url_key(url)
    slash = key.find("/")
    return key[slash:] if slash >= 0 else "/"


def _content_context(
    db: Any, customer_id: str, scan_id: str, keys: set[str], live_urls: Iterable[str]
) -> tuple[list[LaunchContentPage], bool]:
    """Content van de rest van de site voor de fase-3-checks: (pagina's, fase-3-scan gevonden).

    De laatste fase-3-scan, aangevuld met eerder door de monitor gescande pagina's (die
    winnen bij dezelfde URL). Pagina's die nu opnieuw gescand worden vallen weg, net als
    pagina's die niet meer in de sitemap staan (`live_urls`): een verwijderde pagina telt
    niet mee voor dubbele titels of inkomende links.
    """
    live = {_site_path(url) for url in live_urls}
    phase3 = (
        db.query(LaunchScan)
        .filter(LaunchScan.customer_website_id == customer_id, LaunchScan.phase == 3,
                LaunchScan.checklist.isnot(None))
        .order_by(LaunchScan.created_at.desc())
        .first()
    )
    by_key: dict[str, LaunchContentPage] = {}
    for source_id in ([phase3.id] if phase3 is not None else []) + [scan_id]:
        for page in db.query(LaunchContentPage).filter(LaunchContentPage.scan_id == source_id):
            key = url_key(page.url)
            if key not in keys and _site_path(page.url) in live:
                by_key[key] = page
    return list(by_key.values()), phase3 is not None


def _scan_stats(db: Any, scan_id: str, plan: MonitorPlan, *, scanned: int, issues_found: int,
                now: datetime) -> dict[str, Any]:
    """`summary_stats` van de monitor-scan: de laatste run plus de totale stand."""
    statuses = [row[0] for row in db.query(LaunchScanIssue.status).filter(LaunchScanIssue.scan_id == scan_id)]
    return {
        "run_at": now.isoformat(),
        "new": plan.new_count,
        "changed": plan.changed_count,
        "removed": len(plan.removed),
        "deferred": len(plan.deferred),
        "scanned": scanned,
        "issues_found": issues_found,
        "pages": db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == scan_id).count(),
        "issues": len(statuses),
        "open_issues": sum(1 for s in statuses if s == "open"),
    }


def _resolve_removed(db: Any, scan_id: str, removed_keys: set[str], now: datetime) -> int:
    """Open actiepunten van verwijderde pagina's op 'opgelost'."""
    count = 0
    if not removed_keys:
        return count
    for issue in db.query(LaunchScanIssue).filter(
        LaunchScanIssue.scan_id == scan_id, LaunchScanIssue.status == "open", LaunchScanIssue.url.isnot(None)
    ):
        if url_key(issue.url) in removed_keys:
            issue.status = "opgelost"
            issue.updated_at = now
            count += 1
    return count


def _store_results(
    scan_id: str,
    plan: MonitorPlan,
    rows: list[LaunchScanPage],
    content_rows: list[LaunchContentPage],
    issues: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Pagina's, content en actiepunten van de opnieuw gescande URL's vervangen (één transactie)."""
    target_keys = {t["key"] for t in plan.targets} | {url_key(r.url) for r in rows}
    with SessionLocal() as db:
        old_pages = [
            p for p in db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == scan_id)
            if url_key(p.url) in target_keys
        ]
        old_page_ids = {p.id for p in old_pages}
        old_issues = [
            i for i in db.query(LaunchScanIssue).filter(LaunchScanIssue.scan_id == scan_id)
            if i.page_id in old_page_ids or (i.url and url_key(i.url) in target_keys)
        ]
        carried = carried_state_from_rows(old_issues)

        db.add_all(rows)
        db.flush()

        # Oude punten vervangen. Een punt met Monday-koppeling dat niet meer gevonden wordt,
        # blijft staan als 'opgelost' (anders raakt de koppeling zoek); de rest vervalt.
        found = {issue_key(i["issue_type"], i.get("url")) for i in issues}
        new_page_ids = {url_key(r.url): r.id for r in rows}
        for old in old_issues:
            if old.external_item_id and issue_key(old.issue_type, old.url) not in found:
                if old.status != "genegeerd":
                    old.status = "opgelost"
                old.page_id = new_page_ids.get(url_key(old.url)) if old.url else None
                old.updated_at = now
            else:
                db.delete(old)
        db.flush()

        for page in db.query(LaunchContentPage).filter(LaunchContentPage.scan_id == scan_id):
            if page.source_page_id in old_page_ids or url_key(page.url) in target_keys:
                db.delete(page)
        db.flush()
        for page in old_pages:
            db.delete(page)
        db.flush()

        db.add_all(content_rows)
        db.add_all([
            LaunchScanIssue(id=str(uuid.uuid4()), scan_id=scan_id, created_at=now, updated_at=now,
                            **with_carried_state(issue, carried))
            for issue in issues
        ])
        db.flush()
        _resolve_removed(db, scan_id, {r["key"] for r in plan.removed}, now)
        db.flush()
        stats = _scan_stats(db, scan_id, plan, scanned=len(rows), issues_found=len(issues), now=now)
        db.commit()
    return stats


def _scan_targets(
    scan_id: str,
    customer_id: str,
    nulmeting_id: str,
    base_url: str,
    user_id: str,
    plan: MonitorPlan,
    warnings: list[str],
) -> tuple[
    list[LaunchScanPage], list[LaunchContentPage], list[dict[str, Any]], dict[str, tuple[str, str]]
] | None:
    """Inventaris, signalen, paginatypes, contentchecks en actiepunten van de doel-URL's.

    Geeft (pagina-rijen, content-rijen, actiepunten, niet gescand) terug; alleen voor URL's
    die echt gescand zijn. `niet gescand` is {url_key: (url, reden)}: die URL's blijven
    ongemoeid en komen bij de volgende run opnieuw aan bod.
    Schrijft nog niets weg (behalve voortgang). None als de scan intussen gestopt is.
    """
    concurrency = settings.launch_scan_http_concurrency
    urls = [t["url"] for t in plan.targets]

    # 1. Inventaris van alleen de doel-URL's (geen crawl)
    progress = {"done": 0, "failed": 0}

    def on_batch(batch: list[PageRecord]) -> bool:
        progress["done"] += len(batch)
        progress["failed"] += len([r for r in batch if r.error])
        _update(scan_id, inventoried_urls=progress["done"], failed_urls=progress["failed"])
        return not _is_stopped(scan_id)

    records = asyncio.run(
        run_inventory(
            seed_urls=urls,
            in_sitemap=True,
            follow_links=False,
            max_pages=len(urls),
            concurrency=concurrency,
            on_batch=on_batch,
            on_progress=heartbeat(lambda: _update(scan_id)),
        )
    )
    if _is_stopped(scan_id):
        return None
    now = _now()
    failed: dict[str, tuple[str, str]] = {}
    for rec in records:
        reason = _not_scanned_reason(rec)
        if reason is not None:
            failed[url_key(rec.url)] = (rec.url, reason)
    rows = [_record_to_row(scan_id, rec) for rec in records if url_key(rec.url) not in failed]
    for row in rows:
        row.created_at = now

    # 2. Signalen: JSON-LD, uitgaande links en schema-validatie (zoals fase 4)
    _update(scan_id, status="fetching", total_urls=len(rows), inventoried_urls=0)
    root_domain = root_domain_of(base_url) or urlparse(base_url).netloc
    html_targets = [(r.id, r.final_url or r.url) for r in rows if _is_ok_html(r)]

    def on_fetch(done: int) -> bool:
        _update(scan_id, inventoried_urls=done)
        return not _is_stopped(scan_id)

    fetched = asyncio.run(_refetch(html_targets, root_domain, concurrency, on_fetch))
    if _is_stopped(scan_id):
        return None
    for row in rows:
        data = fetched.get(row.id)
        if data:
            row.jsonld, row.outlinks, row.signals = data["jsonld"], data["outlinks"], data["signals"]
    if len(fetched) < len(html_targets):
        warnings.append(
            f"{len(html_targets) - len(fetched)} van de {len(html_targets)} pagina's konden niet opnieuw "
            "worden opgehaald voor JSON-LD en schema-validatie."
        )

    # 3. Paginatype: eerst bekende types overnemen (niet opnieuw betalen), dan regels/AI
    keys = {url_key(r.url) for r in rows}
    with SessionLocal() as db:
        _copy_page_types(_known_page_types(db, scan_id, nulmeting_id, keys), rows)
        try:
            apply_page_types(db, rows, customer_id=customer_id, base_url=base_url, user_id=user_id)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # paginatype is een verrijking: de run gaat door
            logger.warning("Paginatypes bepalen mislukt (monitor-scan %s): %s", scan_id, exc)
            warnings.append(f"Paginatypes niet (volledig) bepaald: {exc}")

    # 4. Fase-3-inhoud van de nieuwe/gewijzigde pagina's
    content_targets = [
        {"id": r.id, "url": r.final_url or r.url, "page_type": r.page_type}
        for r in rows if _is_ok_html(r) and r.indexable is not False
    ]
    _update(scan_id, total_urls=len(content_targets), inventoried_urls=0)
    content = asyncio.run(_fetch_content(content_targets, root_domain, concurrency, on_fetch))
    if _is_stopped(scan_id):
        return None
    # Inhoud niet opgehaald: zonder contentchecks zouden de punten van deze pagina onterecht
    # verdwijnen of als fase-1-dubbelen terugkomen. Dan telt de pagina als niet gescand.
    for t in content_targets:
        if t["id"] not in content:
            failed[url_key(t["url"])] = (t["url"], "inhoud niet opgehaald")
    rows = [r for r in rows if url_key(r.url) not in failed]
    content_rows = [
        LaunchContentPage(
            id=str(uuid.uuid4()), scan_id=scan_id, source_page_id=t["id"], url=t["url"],
            path=_path_of(t["url"]), page_type=t["page_type"], analysis_status="none",
            created_at=now, **content[t["id"]],
        )
        for t in content_targets if t["id"] in content
    ]

    # 5. Interne links op de nieuwe pagina's (404's en redirects)
    _update(scan_id, status="linking", total_urls=len(rows), inventoried_urls=len(rows))
    known_ok = {url_key(p.url) for p in content_rows}
    link_urls = list(dict.fromkeys(link["url"] for p in content_rows for link in (p.links or [])))
    link_status = asyncio.run(_check_links(link_urls, known_ok, heartbeat(lambda: _update(scan_id))))
    if _is_stopped(scan_id):
        return None

    # 6. Regels: fase 1 per pagina, fase-3-checks tegen de rest van de site
    _update(scan_id, status="checking")
    with SessionLocal() as db:
        context, has_phase3 = _content_context(
            db, customer_id, scan_id, keys | known_ok, (e.get("url") or "" for e in plan.entries.values()))
        all_checks = evaluate_pages([*context, *content_rows], link_status)
        page_checks: dict[str, dict[str, Any]] = {}
        for page in content_rows:
            checks = all_checks[page.id]
            if not has_phase3:
                # Zonder fase-3-scan kent de monitor de inkomende links van de site niet.
                checks.pop(INTERNAL_LINKS_KEY, None)
            page.checks = checks
            page.problem_count = problem_count(checks)
            page_checks[page.id] = checks
        states = {
            key: state.manual_status
            for key, state in manual_states_by_customer(db, customer_id).get(customer_id, {}).items()
        }
    if not has_phase3:
        warnings.append("Geen fase-3-scan gevonden: interne links naar deze pagina's zijn niet beoordeeld.")
    content_issues = generate_content_issues(content_rows, page_checks, {}, states)
    page_issues = drop_covered_f1_issues(generate_page_issues(rows), content_issues)
    return rows, content_rows, page_issues + content_issues, failed


def _not_scanned_message(failed: dict[str, tuple[str, str]]) -> str:
    """Zichtbare melding (scan én monitorkaart) voor pagina's die niet gescand konden worden."""
    shown = [f"{url} ({reason})" for url, reason in list(failed.values())[:MAX_FAILED_IN_MESSAGE]]
    more = f" en {len(failed) - MAX_FAILED_IN_MESSAGE} meer" if len(failed) > MAX_FAILED_IN_MESSAGE else ""
    return (
        f"{len(failed)} pagina('s) niet gescand door een time-out, verbindingsfout of blokkade; "
        f"die komen bij de volgende run opnieuw aan bod: {', '.join(shown)}{more}."
    )


@celery_app.task(
    bind=True,
    name="app.worker.tasks.run_sitemap_monitor_task",
    soft_time_limit=1500,
    time_limit=1800,
)
def run_sitemap_monitor_task(self, customer_id: str, lock_token: str | None = None) -> str:
    """Eén monitor-run voor één klant. Geeft de uitkomst terug (voor logs en tests):
    skipped | locked | error | baseline | unchanged | completed | stopped | failed.

    `lock_token`: de lock die "Nu controleren" al pakte bij het inplannen.
    """
    try:
        token = acquire_lock(customer_id, lock_token)
    except Exception as exc:  # Redis onbereikbaar: liever overslaan dan dubbel draaien
        logger.warning("Sitemap-monitor: lock voor klant %s niet beschikbaar: %s", customer_id, exc)
        return "skipped"
    if token is None:
        # Er loopt (of wacht) al een monitor-run voor deze klant; die werkt zelf
        # checked_at en last_error bij, dus hier niets wegschrijven.
        logger.info("Sitemap-monitor: klant %s overgeslagen, er loopt al een monitor-run.", customer_id)
        return "locked"
    try:
        return _run_monitor(customer_id)
    finally:
        try:
            release_lock(customer_id, token)
        except Exception as exc:  # verloopt vanzelf (LOCK_TTL_SECONDS)
            logger.warning("Sitemap-monitor: lock voor klant %s niet vrijgegeven: %s", customer_id, exc)


def _run_monitor(customer_id: str) -> str:
    with SessionLocal() as db:
        customer = db.get(CustomerWebsite, customer_id)
        if customer is None:
            return "skipped"
        nulmeting = latest_completed_scan(db, customer_id, 1)
        if nulmeting is None:
            logger.info("Sitemap-monitor: klant %s heeft geen voltooide nulmeting.", customer_id)
            return "skipped"
        # Zoals router._recover_stale_scans: een vastgelopen scan mag de monitor niet blokkeren.
        active = (
            db.query(LaunchScan)
            .filter(LaunchScan.customer_website_id == customer_id, LaunchScan.status.in_(ACTIVE_STATUSES))
            .all()
        )
        for scan in active:
            recover_stale_analysis(db, scan) or recover_stale_scan(db, scan)
        running = any(str(scan.status).lower() in ACTIVE_STATUSES for scan in active)
        snapshot = db.get(LaunchSitemapSnapshot, customer_id)
        entries = dict(snapshot.entries or {}) if snapshot is not None else None
        previous_changes = list(snapshot.recent_changes or []) if snapshot is not None else []
        base_url = nulmeting.base_url
        nulmeting_id = nulmeting.id
        user_id = customer.created_by or nulmeting.created_by
    if running:
        # De stand blijft staan: de volgende run pakt de wijzigingen alsnog op. Wel melden,
        # zodat "Nu controleren" niet op een antwoord blijft wachten.
        logger.info("Sitemap-monitor: klant %s overgeslagen, er loopt al een scan.", customer_id)
        _save_snapshot(customer_id, checked_at=_now(), last_error=SKIPPED_MESSAGE)
        return "skipped"

    # Ruim eigen maximum, niet dat van de nulmeting: een afgekapte lijst geeft valse "nieuwe" pagina's.
    try:
        discovery = discover_from_sitemaps(base_url, max_urls=settings.sitemap_monitor_max_urls)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        logger.warning("Sitemap-monitor: sitemap van %s niet opgehaald: %s", customer_id, exc)
        _save_snapshot(customer_id, checked_at=_now(), last_error=f"Sitemap niet opgehaald: {exc}"[:1000])
        return "error"

    plan = plan_run(entries, discovery, max_pages=settings.sitemap_monitor_max_pages_per_run)
    now = _now()
    if plan.kind == "error":
        _save_snapshot(customer_id, checked_at=now, last_error=plan.error)
        return "error"
    if plan.kind in ("baseline", "unchanged"):
        _save_snapshot(customer_id, entries=plan.entries, checked_at=now, last_error=plan.sitemap_problem)
        return plan.kind

    def finish_snapshot(done: MonitorPlan, extra_error: str | None = None) -> None:
        items = change_items(done, now)
        fields: dict[str, Any] = {
            "entries": done.entries,
            "recent_changes": merge_recent_changes(previous_changes, items),
            "checked_at": now,
            "last_error": " ".join(p for p in (done.sitemap_problem, extra_error) if p) or None,
        }
        if items:
            fields["changed_at"] = now
        _save_snapshot(customer_id, **fields)

    if not plan.targets:
        # Alleen verwijderde pagina's: open punten daarvan afsluiten, niets scannen.
        with SessionLocal() as db:
            scan = monitor_scan(db, customer_id)
            if scan is not None:
                _resolve_removed(db, scan.id, {r["key"] for r in plan.removed}, now)
                db.flush()
                scan.summary_stats = _scan_stats(db, scan.id, plan, scanned=0, issues_found=0, now=now)
                scan.updated_at = now
            db.commit()
        finish_snapshot(plan)
        return "completed"

    scan_id = _prepare_monitor_scan(customer_id, base_url, user_id, len(plan.targets))
    warnings = list(plan.warnings)
    _update(scan_id, warnings=warnings)
    try:
        result = _scan_targets(scan_id, customer_id, nulmeting_id, base_url, user_id, plan, warnings)
        if result is None:
            _save_snapshot(
                customer_id, checked_at=_now(),
                last_error="De monitor-run is gestopt; de wijzigingen komen bij de volgende run opnieuw aan bod.",
            )
            return "stopped"
        rows, content_rows, issues, failed = result
        not_scanned = None
        if failed:
            # Niet gescand: pagina, content en punten blijven staan, de stand gaat terug.
            plan = retry_later(plan, entries or {}, set(failed))
            not_scanned = _not_scanned_message(failed)
            warnings.append(not_scanned)
        stats = _store_results(scan_id, plan, rows, content_rows, issues, now)
        stats["not_scanned"] = len(failed)
        finish_snapshot(plan, not_scanned)
        _update(
            scan_id,
            status="completed",
            summary_stats=stats,
            warnings=warnings,
            total_urls=len(rows),
            inventoried_urls=len(rows),
            completed_at=_now(),
        )
        return "completed"
    except SoftTimeLimitExceeded:
        message = "Monitor-run duurde te lang en is afgebroken."
        _update(scan_id, status="failed", error_message=message, warnings=warnings)
        _save_snapshot(customer_id, checked_at=_now(), last_error=message)
        return "failed"
    except Exception as exc:
        logger.exception("Sitemap-monitor voor klant %s mislukt", customer_id)
        _update(scan_id, status="failed", error_message=str(exc)[:1000], warnings=warnings)
        _save_snapshot(customer_id, checked_at=_now(), last_error=f"Monitor-run mislukt: {exc}"[:1000])
        return "failed"
