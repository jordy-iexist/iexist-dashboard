"""Bronnen voor de aanpassingen per pagina (alleen lezen, geen nieuwe AI-aanroepen).

1. AI-voorstellen per pagina uit de laatste voltooide fase 3-scan.
2. Actiepunten met een URL uit de laatste voltooide scan van fase 1, 3 en 4 en de monitor-scan;
   bij dezelfde (issue_type, url_key) in meer scans wint de nieuwste.
3. Schema: een samenvatting van `LaunchScanPage.schema_suggestion` per pagina.

Pagina's worden samengevoegd op `url_key()`.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from sqlalchemy.orm import Session, load_only

from app.db.models import (
    LaunchContentPage,
    LaunchContentSuggestion,
    LaunchScan,
    LaunchScanIssue,
    LaunchScanPage,
    SiteChange,
)
from app.features.launch_checklist.services.checklist_view import latest_completed_scan
from app.features.launch_checklist.services.content_checklist import ITEMS as CONTENT_ITEMS
from app.features.launch_checklist.services.discovery import url_key
from app.features.launch_checklist.services.geo_extract import all_types
from app.features.launch_checklist.services.issues import ISSUE_TYPES
from app.features.launch_checklist.services.rankmath_schema import (
    REVIEW_APPROVED,
    REVIEW_REJECTED,
    placement_view,
    review_view,
)
from app.features.launch_checklist.services.sitemap_monitor import monitor_scan
from app.features.site_changes.services.changes import (
    KIND_ISSUE,
    KIND_SUGGESTION,
    Entry,
    issue_source_key,
    merge_entries,
    suggestion_key,
    suggestion_needs_proposal,
    topic_for,
)

ISSUE_PHASES = (1, 3, 4)
SEVERITIES = {"laag", "middel", "hoog"}


@dataclass
class SourceItem:
    """Eén voorstel of actiepunt uit de bron, in de vorm van de weergave."""

    key: str
    source_kind: str
    type_key: str  # item_key (voorstel) of issue_type (actiepunt)
    topic: str
    page_url: str
    url_key: str
    title: str
    description: str | None
    current_value: str | None
    proposed_value: str | None
    rationale: str | None
    ref: str | None
    severity: str | None
    item_label: str | None
    status: str  # status in de bron
    source_ref: dict[str, str]
    updated_by: str | None = None
    updated_at: datetime | None = None
    details: Any = None
    suggestion: LaunchContentSuggestion | None = None
    # Alle issue-rijen met deze sleutel in de bronscans, nieuwste eerst.
    issues: list[LaunchScanIssue] = field(default_factory=list)


@dataclass
class PageInfo:
    url: str
    path: str
    title: str | None = None


@dataclass
class Sources:
    items: dict[str, SourceItem]
    pages: dict[str, PageInfo]
    content_scan: LaunchScan | None
    has_sources: bool


def path_of(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    return f"{path}?{parsed.query}" if parsed.query else path


def absolute_url(url: str, base_url: str) -> str:
    """Fase 4 kan een pad opslaan in plaats van een volledige URL."""
    if url.startswith(("http://", "https://")):
        return url
    return urljoin(base_url, url)


def issue_scans(db: Session, customer_id: str) -> list[LaunchScan]:
    """Laatste voltooide scan per fase 1, 3, 4 plus de monitor-scan; nieuwste eerst."""
    scans = [latest_completed_scan(db, customer_id, phase) for phase in ISSUE_PHASES]
    scans.append(monitor_scan(db, customer_id))
    unique = {scan.id: scan for scan in scans if scan is not None}
    return sorted(unique.values(), key=lambda s: s.created_at, reverse=True)


def has_completed_scan(db: Session, customer_id: str) -> bool:
    return (
        db.query(LaunchScan.id)
        .filter(LaunchScan.customer_website_id == customer_id, LaunchScan.status == "completed")
        .first()
        is not None
    )


def _severity(value: str | None) -> str | None:
    return value if value in SEVERITIES else None


def _suggestion_items(
    db: Session, scan: LaunchScan, only_key: str | None, pages: dict[str, PageInfo],
) -> dict[str, SourceItem]:
    content_pages = {
        p.id: p
        for p in db.query(LaunchContentPage)
        .options(load_only(LaunchContentPage.id, LaunchContentPage.url, LaunchContentPage.path,
                           LaunchContentPage.title))
        .filter(LaunchContentPage.scan_id == scan.id)
    }
    rows = (
        db.query(LaunchContentSuggestion)
        .filter(LaunchContentSuggestion.scan_id == scan.id, LaunchContentSuggestion.content_page_id.isnot(None))
        .order_by(LaunchContentSuggestion.created_at, LaunchContentSuggestion.id)
        .all()
    )
    for page in content_pages.values():
        ukey = url_key(page.url)
        if only_key is None or ukey == only_key:
            info = pages.setdefault(ukey, PageInfo(url=page.url, path=page.path or path_of(page.url)))
            info.title = info.title or page.title

    # Basissleutels tellen: dezelfde basis op dezelfde pagina en hetzelfde punt -> voorstel meenemen.
    prepared: list[tuple[LaunchContentSuggestion, LaunchContentPage, str, str, str | None]] = []
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        page = content_pages.get(row.content_page_id)
        if page is None:
            continue
        ukey = url_key(page.url)
        if only_key is not None and ukey != only_key:
            continue
        ref = (row.details or {}).get("ref") if isinstance(row.details, dict) else None
        topic = topic_for(row.item_key)
        base = suggestion_key(topic, ukey, row.item_key, row.current_value, ref)
        counts[base] += 1
        prepared.append((row, page, ukey, base, ref))

    items: dict[str, SourceItem] = {}
    for row, page, ukey, base, ref in prepared:
        topic = topic_for(row.item_key)
        key = base
        if counts[base] > 1 or suggestion_needs_proposal(row.current_value, ref):
            key = suggestion_key(topic, ukey, row.item_key, row.current_value, ref, row.proposed_value)
        if key in items:
            continue  # letterlijk hetzelfde voorstel twee keer
        item = CONTENT_ITEMS.get(row.item_key)
        items[key] = SourceItem(
            key=key, source_kind=KIND_SUGGESTION, type_key=row.item_key, topic=topic,
            page_url=page.url, url_key=ukey,
            title=row.title or (item.label if item else row.item_key),
            description=None, current_value=row.current_value, proposed_value=row.proposed_value,
            rationale=row.rationale, ref=ref, severity=None,
            item_label=item.label if item else row.item_key,
            status=row.status, source_ref={"suggestion_id": row.id},
            updated_by=row.updated_by, updated_at=row.updated_at, details=row.details, suggestion=row,
        )
    return items


def _issue_items(
    db: Session, scans: list[LaunchScan], only_key: str | None, pages: dict[str, PageInfo],
) -> dict[str, SourceItem]:
    if not scans:
        return {}
    order = {scan.id: index for index, scan in enumerate(scans)}
    base_urls = {scan.id: scan.base_url for scan in scans}
    rows = (
        db.query(LaunchScanIssue)
        .filter(LaunchScanIssue.scan_id.in_(list(order)), LaunchScanIssue.url.isnot(None),
                LaunchScanIssue.url != "")
        .all()
    )
    # Nieuwste scan eerst; binnen een scan de nieuwste rij eerst.
    rows.sort(key=lambda r: (order[r.scan_id], -(r.created_at.timestamp() if r.created_at else 0)))
    items: dict[str, SourceItem] = {}
    for row in rows:
        url = absolute_url(row.url, base_urls[row.scan_id])
        ukey = url_key(url)
        if only_key is not None and ukey != only_key:
            continue
        key = issue_source_key(row.issue_type, ukey)
        existing = items.get(key)
        if existing is not None:
            existing.issues.append(row)
            continue
        pages.setdefault(ukey, PageInfo(url=url, path=path_of(url)))
        label = ISSUE_TYPES.get(row.issue_type, {}).get("label", row.issue_type)
        items[key] = SourceItem(
            key=key, source_kind=KIND_ISSUE, type_key=row.issue_type, topic=topic_for(row.issue_type),
            page_url=url, url_key=ukey, title=row.title, description=row.description,
            current_value=None, proposed_value=None, rationale=row.recommendation, ref=None,
            severity=_severity(row.severity), item_label=label, status=row.status,
            source_ref={"issue_id": row.id}, updated_at=row.updated_at, details=row.details,
            issues=[row],
        )
    return items


def _page_titles(db: Session, scans: list[LaunchScan], pages: dict[str, PageInfo]) -> None:
    """Titels aanvullen uit de paginarijen van de bronscans (fase 1/4/monitor)."""
    missing = {k for k, p in pages.items() if not p.title}
    if not missing or not scans:
        return
    for row in (
        db.query(LaunchScanPage)
        .options(load_only(LaunchScanPage.url, LaunchScanPage.title))
        .filter(LaunchScanPage.scan_id.in_([s.id for s in scans]), LaunchScanPage.title.isnot(None))
    ):
        ukey = url_key(row.url)
        if ukey in missing and row.title:
            pages[ukey].title = row.title
            missing.discard(ukey)


def collect_sources(db: Session, customer_id: str, only_key: str | None = None) -> Sources:
    """Alle voorstellen en actiepunten met een URL (optioneel alleen voor één url_key)."""
    pages: dict[str, PageInfo] = {}
    content_scan = latest_completed_scan(db, customer_id, 3)
    items: dict[str, SourceItem] = {}
    if content_scan is not None:
        items.update(_suggestion_items(db, content_scan, only_key, pages))
    scans = issue_scans(db, customer_id)
    items.update(_issue_items(db, scans, only_key, pages))
    _page_titles(db, scans, pages)
    return Sources(items=items, pages=pages, content_scan=content_scan,
                   has_sources=has_completed_scan(db, customer_id))


def change_rows(db: Session, customer_id: str, only_key: str | None = None) -> list[SiteChange]:
    query = db.query(SiteChange).filter(SiteChange.customer_website_id == customer_id)
    if only_key is not None:
        query = query.filter(SiteChange.url_key == only_key)
    return query.all()


def collect_entries(db: Session, customer_id: str, only_key: str | None = None) -> tuple[Sources, list[Entry]]:
    sources = collect_sources(db, customer_id, only_key)
    rows = change_rows(db, customer_id, only_key)
    for row in rows:
        # Rijen waarvan de bron weg is: pagina blijft vindbaar.
        sources.pages.setdefault(row.url_key, PageInfo(url=row.page_url, path=path_of(row.page_url)))
    entries = merge_entries(sources.items, rows)
    return sources, entries


# --- schema -----------------------------------------------------------------------

def schema_summary(db: Session, customer_id: str, ukey: str) -> dict[str, Any] | None:
    """Status-regel van het schema-voorstel van deze pagina (laatste voltooide fase 1/2-scan).

    None als de pagina in die scans niet voorkomt.
    """
    scans = [latest_completed_scan(db, customer_id, phase) for phase in (1, 2)]
    scans = sorted((s for s in scans if s is not None), key=lambda s: s.created_at, reverse=True)
    found: LaunchScanPage | None = None
    for scan in scans:
        for row in (
            db.query(LaunchScanPage)
            .options(load_only(LaunchScanPage.id, LaunchScanPage.url, LaunchScanPage.schema_suggestion))
            .filter(LaunchScanPage.scan_id == scan.id)
        ):
            if url_key(row.url) != ukey:
                continue
            if found is None:
                found = row
            if isinstance(row.schema_suggestion, dict) and row.schema_suggestion.get("jsonld"):
                return _schema_view(row.schema_suggestion)
    if found is None:
        return None
    return _schema_view(found.schema_suggestion if isinstance(found.schema_suggestion, dict) else None)


def _schema_view(suggestion: dict[str, Any] | None) -> dict[str, Any]:
    if not suggestion or not suggestion.get("jsonld"):
        return {"status": "none", "types": [], "placed_at": None, "verified": None}
    types = [str(t) for t in suggestion.get("types") or []] or sorted(all_types(suggestion.get("jsonld")))
    placement = placement_view(suggestion)
    if placement is not None:
        return {"status": "placed", "types": types, "placed_at": placement["placed_at"],
                "verified": placement["verified"]}
    review_status, _ = review_view(suggestion)
    status = {REVIEW_APPROVED: "approved", REVIEW_REJECTED: "rejected"}.get(review_status, "suggested")
    return {"status": status, "types": types, "placed_at": None, "verified": None}
