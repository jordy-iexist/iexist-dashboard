"""Fase 3: checklist opbouwen uit opgeslagen pagina-inhoud en AI-voorstellen.

Gedeeld door de workers (scan + AI-analyse) en de router (na het afhandelen
van een voorstel), zodat de checklist altijd op dezelfde manier wordt berekend.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    LaunchContentPage,
    LaunchContentSuggestion,
    LaunchScan,
    LaunchScanIssue,
)
from app.features.launch_checklist.services.content_checklist import ITEMS
from app.features.launch_checklist.services.content_checks import (
    F1_META_TYPES,
    REDIRECTS_KEY,
    aggregate_items,
    evaluate_pages,
    problem_count,
    recheck_meta,
)
from app.features.launch_checklist.services.issues import content_issue


def content_pages(db: Session, scan_id: str) -> list[LaunchContentPage]:
    return (
        db.query(LaunchContentPage)
        .filter(LaunchContentPage.scan_id == scan_id)
        .order_by(LaunchContentPage.path)
        .all()
    )


def open_suggestion_counts(db: Session, scan_id: str) -> dict[tuple[str | None, str], int]:
    rows = (
        db.query(
            LaunchContentSuggestion.content_page_id,
            LaunchContentSuggestion.item_key,
            func.count(LaunchContentSuggestion.id),
        )
        .filter(LaunchContentSuggestion.scan_id == scan_id, LaunchContentSuggestion.status == "open")
        .group_by(LaunchContentSuggestion.content_page_id, LaunchContentSuggestion.item_key)
        .all()
    )
    return {(page_id, key): int(count) for page_id, key, count in rows}


def f1_meta_issues(db: Session, source_scan_id: str | None) -> list[tuple[str, str | None]]:
    if not source_scan_id:
        return []
    rows = (
        db.query(LaunchScanIssue.issue_type, LaunchScanIssue.url)
        .filter(
            LaunchScanIssue.scan_id == source_scan_id,
            LaunchScanIssue.issue_type.in_(F1_META_TYPES),
            LaunchScanIssue.status != "genegeerd",
        )
        .all()
    )
    return [(row[0], row[1]) for row in rows]


def build_content_payload(
    db: Session,
    scan: LaunchScan,
    pages: list[LaunchContentPage],
    *,
    link_status: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Evalueer alle punten en werk `checks`/`problem_count` per pagina bij.

    `link_status` is alleen bekend direct na de scan; bij herberekenen blijft
    het opgeslagen linkresultaat per pagina staan.
    Geeft (payload voor `scan.checklist`, regelresultaat per pagina) terug.
    """
    page_checks = evaluate_pages(pages, link_status)
    for page in pages:
        checks = page_checks[page.id]
        if link_status is None and isinstance(page.checks, dict) and REDIRECTS_KEY in page.checks:
            checks[REDIRECTS_KEY] = page.checks[REDIRECTS_KEY]
        page.checks = checks
        page.problem_count = problem_count(checks)

    previous = scan.checklist if isinstance(scan.checklist, dict) else {}
    gap_analyzed_at = previous.get("gap_analyzed_at")
    open_counts = open_suggestion_counts(db, scan.id)
    items = aggregate_items(
        pages,
        page_checks,
        open_suggestions=open_counts,
        meta_fixed=recheck_meta(f1_meta_issues(db, scan.source_scan_id), pages),
        gap_analyzed=bool(gap_analyzed_at),
    )
    page_types = dict(Counter((p.page_type or "overig") for p in pages))
    payload = {
        "items": items,
        "page_types": page_types,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gap_analyzed_at": gap_analyzed_at,
        "links_checked": previous.get("links_checked") if link_status is None else len(link_status),
        "summary": {
            "auto_status": dict(Counter(r.get("status") for r in items.values())),
            "page_types": page_types,
            "pages_fetched": len(pages),
            "pages_with_problems": sum(1 for p in pages if p.problem_count),
            "pages_analysed": sum(1 for p in pages if p.analysis_status == "done"),
            "suggestions_open": sum(open_counts.values()),
        },
    }
    return payload, page_checks


def rebuild_content_checklist(db: Session, scan: LaunchScan) -> None:
    """Herbereken de fase-3 checklist uit opgeslagen data (zonder de site op te halen)."""
    if scan.phase != 3:
        return
    pages = content_pages(db, scan.id)
    payload, _ = build_content_payload(db, scan, pages)
    scan.checklist = payload
    scan.summary_stats = payload["summary"]
    scan.updated_at = datetime.now(timezone.utc)


def sync_suggestion_issues(db: Session, scan: LaunchScan, page: LaunchContentPage) -> int:
    """Maak een actiepunt voor elk checklistpunt waar de AI voorstellen voor deed
    maar de regelcontrole niets vond, zodat het ook naar Monday kan."""
    keys = {
        row[0]
        for row in db.query(LaunchContentSuggestion.item_key)
        .filter(
            LaunchContentSuggestion.content_page_id == page.id,
            LaunchContentSuggestion.status == "open",
        )
        .distinct()
    }
    if not keys:
        return 0
    existing = {
        row[0]
        for row in db.query(LaunchScanIssue.issue_type)
        .filter(LaunchScanIssue.scan_id == scan.id, LaunchScanIssue.url == page.url)
    }
    now = datetime.now(timezone.utc)
    created = 0
    for key in sorted(keys - existing):
        if key not in ITEMS:
            continue
        check = {"status": "warning", "message": f"AI-voorstellen: {ITEMS[key].label}"}
        db.add(LaunchScanIssue(
            id=str(uuid.uuid4()), scan_id=scan.id, status="open", created_at=now, updated_at=now,
            **content_issue(key, check, page_id=page.source_page_id, url=page.url, path=page.path, ai=True),
        ))
        created += 1
    return created


def reset_unfinished_analysis(db: Session, scan_id: str, statuses: tuple[str, ...] = ("queued", "running")) -> None:
    """Pagina's die nog in de wachtrij stonden terugzetten: eerder geanalyseerde
    pagina's worden weer 'done', de rest 'none'."""
    base = db.query(LaunchContentPage).filter(
        LaunchContentPage.scan_id == scan_id, LaunchContentPage.analysis_status.in_(statuses)
    )
    base.filter(LaunchContentPage.analyzed_at.isnot(None)).update(
        {"analysis_status": "done"}, synchronize_session=False)
    base.filter(LaunchContentPage.analyzed_at.is_(None)).update(
        {"analysis_status": "none"}, synchronize_session=False)


# Zo lang mag een AI-analyse niets van zich laten horen voordat we hem als afgebroken zien.
# De worker werkt `updated_at` bij na elke pagina en vóór de contentgap- en rapportstap.
STALE_ANALYSIS_AFTER = timedelta(minutes=20)
INTERRUPTED_WARNING = (
    "De AI-analyse is onderbroken (bijvoorbeeld door een herstart van de server). "
    "Afgeronde pagina's zijn bewaard; start de analyse opnieuw voor de rest."
)


def recover_stale_analysis(db: Session, scan: LaunchScan, *, force: bool = False) -> bool:
    """Zet een fase-3 scan die op 'analyzing' is blijven hangen terug op 'completed'.

    Gebeurt als de worker midden in een analyse stopt: zonder dit blijft de
    voortgangsbalk eeuwig staan en kan er geen nieuwe analyse starten.
    """
    if scan.phase != 3 or scan.status != "analyzing":
        return False
    updated = scan.updated_at
    if updated is not None and updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    if not force and updated is not None and datetime.now(timezone.utc) - updated < STALE_ANALYSIS_AFTER:
        return False
    reset_unfinished_analysis(db, scan.id)
    db.flush()
    rebuild_content_checklist(db, scan)
    scan.status = "completed"
    scan.warnings = [*(scan.warnings or []), INTERRUPTED_WARNING][-50:]
    db.commit()
    return True
