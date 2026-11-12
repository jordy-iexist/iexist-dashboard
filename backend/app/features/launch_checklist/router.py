"""Livegang checklist — fase 1 (Nulmeting & AI scan), fase 2 (GEO/SEO-checklist),
fase 3 (Contentcreatie & Onpage optimalisatie) en fase 4 (Kwartaal GEO-werkzaamheden)."""
from __future__ import annotations

import csv
import io
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id
from app.core.url_guard import UnsafeURLError, validate_external_url
from app.db.models import (
    CustomerCategory,
    CustomerWebsite,
    LaunchChecklistState,
    LaunchContentPage,
    LaunchContentSuggestion,
    LaunchPageTypeOverride,
    LaunchScan,
    LaunchScanIssue,
    LaunchScanPage,
)
from app.db.session import get_db
from app.features.launch_checklist.mappers import (
    content_page_fields,
    to_suggestion_item,
    to_issue_item,
    to_page_item,
    to_scan_detail,
    to_scan_item,
)
from app.features.launch_checklist.schemas import (
    ACTIVE_STATUSES,
    ChecklistItemOut,
    ChecklistProgress,
    ChecklistResponse,
    ChecklistStateUpdate,
    ContentAnalysisRequest,
    ContentChecklistResponse,
    ContentKeywordUpdate,
    ContentPageDetail,
    ContentPageItem,
    ContentPageListResponse,
    ContentSuggestionItem,
    ContentSuggestionListResponse,
    SuggestionStatusUpdate,
    GeoScanCreateRequest,
    MondayBoardLink,
    MondayPushChecklistRequest,
    MondayPushIssuesRequest,
    MondayPushOutcome,
    MondayPushResponse,
    MondaySettingsResponse,
    SearchConsoleProperty,
    SearchConsolePropertyUpdate,
    SearchConsoleSettingsResponse,
    PageTypeUpdate,
    QuarterlyChecklistResponse,
    QuarterlyPeriodOption,
    WebshopUpdate,
    IssueBulkStatusUpdate,
    IssueGroup,
    IssueStatusUpdate,
    LaunchCustomerItem,
    LaunchCustomerListResponse,
    LaunchScanCreateRequest,
    LaunchScanDetail,
    LaunchScanIssueItem,
    LaunchScanIssueListResponse,
    LaunchScanListResponse,
    LaunchScanPageListResponse,
)
from app.core.config import settings
from app.features.launch_checklist.services import ahrefs_enrich, gsc_enrich, monday_push
from app.features.launch_checklist.services.checklist_view import (
    latest_completed_geo as _latest_completed_geo,
    latest_completed_scan,
    latest_content_scan as _latest_content_scan,
    latest_quarterly_scan,
    merged_checklist,
    merged_content_checklist,
    merged_quarterly_checklist,
    quarterly_periods,
    resolve_is_webshop as _is_webshop,
)
from app.features.launch_checklist.services.quarterly_checklist import (
    ITEMS as QUARTERLY_ITEMS,
    is_period,
    merge_quarterly_checklist,
    period_label,
    period_of,
)
from app.features.launch_checklist.services.geo_checklist import (
    ITEMS as CHECKLIST_ITEMS,
    SECTION_LABELS,
    merge_checklist,
)
from app.services.monday import client as monday_client
from app.services.monday.client import MondayServiceError
from app.services.search_console import client as gsc_client
from app.services.search_console.client import SearchConsoleServiceError
from app.features.launch_checklist.services.content_checklist import (
    ITEMS as CONTENT_ITEMS,
    merge_content_checklist,
)
from app.features.launch_checklist.services.content_rebuild import (
    rebuild_content_checklist,
    recover_stale_analysis,
    reset_unfinished_analysis,
)
from app.features.launch_checklist.services.geo_rebuild import rebuild_checklist
from app.features.launch_checklist.services.issues import ISSUE_TYPES
from app.features.launch_checklist.services.page_types import PAGE_TYPES

router = APIRouter(prefix="/api/launch-checklist", tags=["launch-checklist"])

_SEVERITY_ORDER = {"hoog": 0, "middel": 1, "laag": 2}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_scan(db: Session, scan_id: str) -> LaunchScan:
    scan = db.get(LaunchScan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan niet gevonden.")
    return scan


def _normalize_base_url(raw: str) -> str:
    url = str(raw or "").strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


# --- klanten ---------------------------------------------------------------

def _latest_scans(db: Session, *, phase: int, completed_only: bool = False) -> dict[str, LaunchScan]:
    """Laatste scan per klant voor een fase."""
    base = db.query(LaunchScan).filter(LaunchScan.phase == phase)
    if completed_only:
        base = base.filter(LaunchScan.status == "completed")
    latest: dict[str, LaunchScan] = {}
    for row in base.order_by(LaunchScan.created_at.asc()).all():
        latest[row.customer_website_id] = row
    return latest


def _states_for(db: Session, customer_id: str | None = None) -> dict[str, dict[str, LaunchChecklistState]]:
    """Handmatige status van fase 2 en 3 (zonder ronde) per klant."""
    query = db.query(LaunchChecklistState).filter(LaunchChecklistState.period == "")
    if customer_id:
        query = query.filter(LaunchChecklistState.customer_website_id == customer_id)
    out: dict[str, dict[str, LaunchChecklistState]] = {}
    for state in query.all():
        out.setdefault(state.customer_website_id, {})[state.item_key] = state
    return out


@router.get("/customers", response_model=LaunchCustomerListResponse)
async def list_launch_customers(
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    customers = db.query(CustomerWebsite).order_by(CustomerWebsite.name.asc()).all()
    categories = {c.id: c.name for c in db.query(CustomerCategory).all()}
    latest = _latest_scans(db, phase=1)
    # Nieuwste nulmeting die niet mislukt/geannuleerd is (ook als die nog loopt).
    newest_p1: dict[str, LaunchScan] = {}
    for row in (
        db.query(LaunchScan)
        .filter(LaunchScan.phase == 1, LaunchScan.status.notin_(("failed", "canceled")))
        .order_by(LaunchScan.created_at.asc())
        .all()
    ):
        newest_p1[row.customer_website_id] = row
    latest_geo = _latest_scans(db, phase=2)
    completed_geo = _latest_scans(db, phase=2, completed_only=True)
    latest_content = _latest_scans(db, phase=3)
    states = _states_for(db)
    latest_quarterly = _latest_scans(db, phase=4)
    completed_quarterly = _latest_scans(db, phase=4, completed_only=True)
    # Fase 4: handmatige status per (klant, ronde).
    quarterly_states: dict[tuple[str, str], dict[str, LaunchChecklistState]] = {}
    for state in db.query(LaunchChecklistState).filter(LaunchChecklistState.period != "").all():
        quarterly_states.setdefault((state.customer_website_id, state.period), {})[state.item_key] = state

    items: list[LaunchCustomerItem] = []
    for c in customers:
        progress = None
        geo = completed_geo.get(c.id)
        if geo is not None or c.id in states:
            payload = (geo.checklist if geo else None) or {}
            merged = merge_checklist(payload.get("items"), states.get(c.id, {}), is_webshop=_is_webshop(c, payload))
            progress = ChecklistProgress(done=merged["done"], total=merged["total"], percent=merged["percent"])
        content_progress = None
        content = latest_content.get(c.id)
        if content is not None and isinstance(content.checklist, dict):
            merged = merge_content_checklist(content.checklist.get("items"), states.get(c.id, {}))
            content_progress = ChecklistProgress(
                done=merged["done"], total=merged["total"], percent=merged["percent"])
        # Verouderd: gebaseerd op een oudere nulmeting dan de nieuwste (ook lopende).
        p1 = newest_p1.get(c.id)
        geo_outdated = geo is not None and p1 is not None and geo.source_scan_id != p1.id
        content_outdated = (
            content is not None
            and content.status in ("completed", "analyzing")
            and p1 is not None
            and content.source_scan_id != p1.id
        )
        quarterly_progress = None
        quarterly = completed_quarterly.get(c.id)
        if quarterly is not None and isinstance(quarterly.checklist, dict):
            merged = merge_quarterly_checklist(
                quarterly.checklist.get("items"), quarterly_states.get((c.id, quarterly.period or ""), {}))
            quarterly_progress = ChecklistProgress(
                done=merged["done"], total=merged["total"], percent=merged["percent"])
        items.append(LaunchCustomerItem(
            id=c.id,
            name=c.name,
            base_url=c.base_url,
            domain=c.domain,
            category_name=categories.get(c.category_id) if c.category_id else None,
            latest_scan=to_scan_item(latest[c.id]) if c.id in latest else None,
            latest_geo_scan=to_scan_item(latest_geo[c.id]) if c.id in latest_geo else None,
            checklist_progress=progress,
            latest_content_scan=to_scan_item(content) if content is not None else None,
            content_progress=content_progress,
            geo_outdated=geo_outdated,
            content_outdated=content_outdated,
            latest_quarterly_scan=to_scan_item(latest_quarterly[c.id]) if c.id in latest_quarterly else None,
            quarterly_progress=quarterly_progress,
            quarterly_period=quarterly.period if quarterly is not None else None,
        ))
    return LaunchCustomerListResponse(customers=items)


# --- scans -----------------------------------------------------------------

@router.post("/scans", response_model=LaunchScanDetail)
async def start_launch_scan(
    payload: LaunchScanCreateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    from app.worker.tasks import run_launch_scan_task  # voorkom circulaire import

    customer = db.get(CustomerWebsite, payload.customer_website_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Klant niet gevonden.")
    if not customer.base_url:
        raise HTTPException(status_code=400, detail="Deze klant heeft geen website-URL.")

    running = (
        db.query(LaunchScan)
        .filter(
            LaunchScan.customer_website_id == customer.id,
            LaunchScan.status.in_(ACTIVE_STATUSES),
        )
        .first()
    )
    if running:
        raise HTTPException(status_code=409, detail="Er loopt al een scan voor deze klant.")

    base_url = _normalize_base_url(customer.base_url)
    try:
        validate_external_url(base_url)
    except UnsafeURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = _now()
    scan = LaunchScan(
        id=str(uuid.uuid4()),
        customer_website_id=customer.id,
        phase=1,
        status="pending",
        base_url=base_url,
        total_urls=0,
        inventoried_urls=0,
        failed_urls=0,
        max_pages=payload.max_pages,
        vitals_max_pages=payload.vitals_max_pages,
        vitals_total=0,
        vitals_measured=0,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    run_launch_scan_task.delay(scan.id)
    return to_scan_detail(scan)


@router.get("/scans", response_model=LaunchScanListResponse)
async def list_launch_scans(
    customer_website_id: str | None = Query(default=None),
    phase: int | None = Query(default=None, ge=1, le=4),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    query = db.query(LaunchScan)
    if customer_website_id:
        query = query.filter(LaunchScan.customer_website_id == customer_website_id)
    if phase:
        query = query.filter(LaunchScan.phase == phase)
    total = query.count()
    rows = query.order_by(LaunchScan.created_at.desc()).offset(offset).limit(limit).all()
    return LaunchScanListResponse(items=[to_scan_item(r) for r in rows], total=total)


@router.get("/scans/{scan_id}", response_model=LaunchScanDetail)
async def get_launch_scan(
    scan_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    scan = _get_scan(db, scan_id)
    # De UI pollt deze endpoint tijdens een analyse: hier herstellen we een vastgelopen analyse.
    recover_stale_analysis(db, scan)
    return to_scan_detail(scan)


@router.post("/scans/{scan_id}/cancel")
async def cancel_launch_scan(
    scan_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    scan = _get_scan(db, scan_id)
    if scan.status not in ACTIVE_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"Scan kan niet worden geannuleerd (status: {scan.status})."
        )
    if scan.phase == 3 and scan.status == "analyzing":
        # Alleen de AI-analyse stopt; de scan zelf en afgeronde pagina's blijven staan.
        scan.status = "completed"
        reset_unfinished_analysis(db, scan_id, ("queued",))
    else:
        scan.status = "canceled"
    scan.updated_at = _now()
    db.commit()
    return {"ok": True, "scan_id": scan_id}


@router.delete("/scans/{scan_id}")
async def delete_launch_scan(
    scan_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    _get_scan(db, scan_id)
    db.query(LaunchScanIssue).filter(LaunchScanIssue.scan_id == scan_id).delete()
    db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == scan_id).delete()
    db.query(LaunchScan).filter(LaunchScan.id == scan_id).delete()
    db.commit()
    return {"ok": True, "scan_id": scan_id}


# --- inventaris -----------------------------------------------------------

_PAGE_FILTERS = {
    "errors": lambda q: q.filter((LaunchScanPage.status_code.is_(None)) | (LaunchScanPage.status_code >= 400)),
    "redirects": lambda q: q.filter(LaunchScanPage.status_code >= 300, LaunchScanPage.status_code < 400),
    "non_indexable": lambda q: q.filter(LaunchScanPage.indexable.is_(False)),
    "indexable": lambda q: q.filter(LaunchScanPage.indexable.is_(True)),
    "missing_title": lambda q: q.filter(LaunchScanPage.indexable.is_(True), (LaunchScanPage.title.is_(None)) | (LaunchScanPage.title == "")),
    "missing_meta": lambda q: q.filter(LaunchScanPage.indexable.is_(True), (LaunchScanPage.meta_description.is_(None)) | (LaunchScanPage.meta_description == "")),
    "missing_h1": lambda q: q.filter(LaunchScanPage.indexable.is_(True), LaunchScanPage.h1_count == 0),
    "multiple_h1": lambda q: q.filter(LaunchScanPage.h1_count > 1),
    "cwv_measured": lambda q: q.filter(LaunchScanPage.cwv_status.isnot(None)),
    "cwv_poor": lambda q: q.filter(LaunchScanPage.cwv_status == "poor"),
    "classified": lambda q: q.filter(LaunchScanPage.page_type.isnot(None)),
    # Ahrefs: pagina's met organisch verkeer of verwijzende domeinen.
    "value": lambda q: q.filter((LaunchScanPage.org_traffic > 0) | (LaunchScanPage.refdomains > 0)),
}
# Ahrefs-filters op JSON-inhoud (eindstatus, bron): in Python op de kleine set pagina's met waarde.
_VALUE_PAGE_FILTERS = {
    "value_lost": ahrefs_enrich.is_lost,
    "ahrefs_only": lambda p: (p.ahrefs or {}).get("source") == "ahrefs",
}


@router.get("/scans/{scan_id}/pages", response_model=LaunchScanPageListResponse)
async def list_launch_scan_pages(
    scan_id: str,
    filter: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    page_type: str | None = Query(default=None, max_length=40),
    sort: str = Query(default="path"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    _get_scan(db, scan_id)
    query = db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == scan_id)
    if filter and filter in _PAGE_FILTERS:
        query = _PAGE_FILTERS[filter](query)
    elif filter in _VALUE_PAGE_FILTERS:
        predicate = _VALUE_PAGE_FILTERS[filter]
        ids = [p.id for p in _PAGE_FILTERS["value"](query).all() if predicate(p)]
        query = query.filter(LaunchScanPage.id.in_(ids or [""]))
    if search:
        like = f"%{search.strip()}%"
        query = query.filter((LaunchScanPage.url.ilike(like)) | (LaunchScanPage.title.ilike(like)))
    if page_type:
        query = query.filter(LaunchScanPage.page_type == page_type)

    sort_columns = {
        "path": LaunchScanPage.path.asc(),
        "status": LaunchScanPage.status_code.desc(),
        "response_time": LaunchScanPage.response_time_ms.desc().nullslast(),
        "words": LaunchScanPage.word_count.asc().nullslast(),
        "depth": LaunchScanPage.click_depth.desc().nullsfirst(),
        "inlinks": LaunchScanPage.inlinks.asc().nullsfirst(),
        "traffic": LaunchScanPage.org_traffic.desc().nullslast(),
        "refdomains": LaunchScanPage.refdomains.desc().nullslast(),
    }
    total = query.count()
    rows = query.order_by(sort_columns.get(sort, LaunchScanPage.path.asc())).offset(offset).limit(limit).all()

    counts = dict(
        db.query(LaunchScanIssue.page_id, func.count(LaunchScanIssue.id))
        .filter(LaunchScanIssue.page_id.in_([r.id for r in rows]))
        .group_by(LaunchScanIssue.page_id)
        .all()
    ) if rows else {}
    return LaunchScanPageListResponse(
        pages=[to_page_item(r, counts.get(r.id, 0)) for r in rows], total=total
    )


# --- actiepunten ----------------------------------------------------------

@router.get("/scans/{scan_id}/issues", response_model=LaunchScanIssueListResponse)
async def list_launch_scan_issues(
    scan_id: str,
    category: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    status: str | None = Query(default=None),
    issue_type: str | None = Query(default=None),
    page_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    _get_scan(db, scan_id)
    base = db.query(LaunchScanIssue).filter(LaunchScanIssue.scan_id == scan_id)

    # Groepen over alle issues van de scan (los van filters), voor de zijbalk.
    group_counter: dict[str, dict[str, Any]] = {}
    for issue_type_, category_, severity_, status_ in base.with_entities(
        LaunchScanIssue.issue_type, LaunchScanIssue.category,
        LaunchScanIssue.severity, LaunchScanIssue.status,
    ).all():
        g = group_counter.setdefault(issue_type_, {
            "category": category_, "severities": Counter(), "count": 0, "open": 0,
        })
        g["count"] += 1
        g["severities"][severity_] += 1
        if status_ == "open":
            g["open"] += 1
    groups = [
        IssueGroup(
            issue_type=t,
            label=ISSUE_TYPES.get(t, {}).get("label", t),
            category=g["category"],
            severity=min(g["severities"], key=lambda s: _SEVERITY_ORDER.get(s, 9)),
            count=g["count"],
            open=g["open"],
        )
        for t, g in group_counter.items()
    ]
    groups.sort(key=lambda g: (_SEVERITY_ORDER.get(g.severity, 9), -g.count))

    query = base
    if category:
        query = query.filter(LaunchScanIssue.category == category)
    if severity:
        query = query.filter(LaunchScanIssue.severity == severity)
    if status:
        query = query.filter(LaunchScanIssue.status == status)
    if issue_type:
        query = query.filter(LaunchScanIssue.issue_type == issue_type)
    if page_id:
        query = query.filter(LaunchScanIssue.page_id == page_id)

    total = query.count()
    rows = query.all()
    rows.sort(key=lambda i: (_SEVERITY_ORDER.get(i.severity, 9), i.issue_type, i.url or ""))
    rows = rows[offset: offset + limit]
    return LaunchScanIssueListResponse(
        issues=[to_issue_item(r) for r in rows], total=total, groups=groups
    )


@router.patch("/issues/bulk")
async def bulk_update_issue_status(
    payload: IssueBulkStatusUpdate,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    updated = (
        db.query(LaunchScanIssue)
        .filter(LaunchScanIssue.id.in_(payload.issue_ids))
        .update({"status": payload.status, "updated_at": _now()}, synchronize_session=False)
    )
    db.commit()
    return {"ok": True, "updated": updated}


@router.patch("/issues/{issue_id}", response_model=LaunchScanIssueItem)
async def update_issue_status(
    issue_id: str,
    payload: IssueStatusUpdate,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    issue = db.get(LaunchScanIssue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Actiepunt niet gevonden.")
    issue.status = payload.status
    issue.updated_at = _now()
    db.commit()
    db.refresh(issue)
    return to_issue_item(issue)


# --- fase 2: GEO/SEO-checklist ---------------------------------------------

def _get_customer(db: Session, customer_id: str) -> CustomerWebsite:
    customer = db.get(CustomerWebsite, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Klant niet gevonden.")
    return customer


def _build_checklist(
    db: Session, customer: CustomerWebsite, geo: LaunchScan | None = None
) -> ChecklistResponse:
    """Checklist voor `geo`; zonder scan de laatste voltooide fase-2 scan."""
    if geo is None:
        geo = _latest_completed_geo(db, customer.id)
    payload = (geo.checklist if geo else None) or {}
    merged = merged_checklist(db, customer, geo)
    is_webshop = merged["is_webshop"]
    return ChecklistResponse(
        customer_id=customer.id,
        customer_name=customer.name,
        base_url=customer.base_url,
        scan=to_scan_item(geo) if geo else None,
        source_scan_id=geo.source_scan_id if geo else None,
        is_webshop=is_webshop,
        webshop_detected=payload.get("webshop_detected") if geo else None,
        webshop_override=customer.launch_is_webshop,
        webshop_reasons=payload.get("webshop_reasons") or [],
        page_types=payload.get("page_types") or {},
        generated_at=payload.get("generated_at"),
        sections=merged["sections"],
        done=merged["done"],
        total=merged["total"],
        percent=merged["percent"],
    )


@router.post("/customers/{customer_id}/geo-scans", response_model=LaunchScanDetail)
async def start_geo_scan(
    customer_id: str,
    payload: GeoScanCreateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    from app.worker.tasks import run_geo_scan_task  # voorkom circulaire import

    customer = _get_customer(db, customer_id)
    query = db.query(LaunchScan).filter(
        LaunchScan.customer_website_id == customer.id, LaunchScan.phase == 1,
        LaunchScan.status == "completed",
    )
    if payload.source_scan_id:
        query = query.filter(LaunchScan.id == payload.source_scan_id)
    source = query.order_by(LaunchScan.created_at.desc()).first()
    if source is None:
        raise HTTPException(status_code=400, detail="Voer eerst een voltooide fase-1 scan (nulmeting) uit.")

    running = (
        db.query(LaunchScan)
        .filter(LaunchScan.customer_website_id == customer.id, LaunchScan.status.in_(ACTIVE_STATUSES))
        .first()
    )
    if running:
        raise HTTPException(status_code=409, detail="Er loopt al een scan voor deze klant.")

    now = _now()
    scan = LaunchScan(
        id=str(uuid.uuid4()),
        customer_website_id=customer.id,
        phase=2,
        source_scan_id=source.id,
        status="pending",
        base_url=source.base_url,
        discovery_source=source.discovery_source,
        total_urls=0,
        inventoried_urls=0,
        failed_urls=0,
        max_pages=source.max_pages,
        vitals_max_pages=0,
        vitals_total=0,
        vitals_measured=0,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    run_geo_scan_task.delay(scan.id)
    return to_scan_detail(scan)


@router.get("/customers/{customer_id}/checklist", response_model=ChecklistResponse)
async def get_checklist(
    customer_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    return _build_checklist(db, _get_customer(db, customer_id))


@router.patch("/customers/{customer_id}/checklist/{item_key}", response_model=ChecklistItemOut)
async def update_checklist_item(
    customer_id: str,
    item_key: str,
    payload: ChecklistStateUpdate,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    customer = _get_customer(db, customer_id)
    if item_key not in CHECKLIST_ITEMS:
        raise HTTPException(status_code=404, detail="Onbekend checklistpunt.")
    state = (
        db.query(LaunchChecklistState)
        .filter(LaunchChecklistState.customer_website_id == customer.id,
                LaunchChecklistState.item_key == item_key)
        .first()
    )
    if state is None:
        state = LaunchChecklistState(id=str(uuid.uuid4()), customer_website_id=customer.id, item_key=item_key)
        db.add(state)
    fields = payload.model_fields_set
    if "manual_status" in fields:
        state.manual_status = payload.manual_status
    if "note" in fields:
        state.note = (payload.note or "").strip() or None
    state.updated_by = user_id
    state.updated_at = _now()
    db.commit()

    response = _build_checklist(db, customer)
    for section in response.sections:
        for item in section.items:
            if item.key == item_key:
                return item
    raise HTTPException(status_code=500, detail="Checklistpunt niet gevonden na opslaan.")


@router.patch("/customers/{customer_id}/webshop", response_model=ChecklistResponse)
async def update_webshop(
    customer_id: str,
    payload: WebshopUpdate,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    customer = _get_customer(db, customer_id)
    customer.launch_is_webshop = payload.is_webshop
    db.flush()
    geo = _latest_completed_geo(db, customer.id)
    if geo is not None:
        rebuild_checklist(db, geo)
    db.commit()
    return _build_checklist(db, customer)


# --- Monday ----------------------------------------------------------------
# Gewone `def`: de Monday-calls zijn synchroon en horen in de threadpool,
# niet op de event loop.

_MONDAY_STATUS = {
    "not_configured": 400,
    "folder_not_found": 400,
    "board_not_found": 409,
    "unauthorized": 502,
    "rate_limited": 503,
    "timeout": 504,
    "connection_error": 502,
}


def _monday_http_error(exc: MondayServiceError) -> HTTPException:
    return HTTPException(status_code=_MONDAY_STATUS.get(exc.code, 502), detail=str(exc))


def _monday_settings(customer: CustomerWebsite, *, check_board: bool) -> MondaySettingsResponse:
    response = MondaySettingsResponse(
        token_configured=monday_client.is_configured(),
        folder_name=settings.monday_folder_name,
        board_id=customer.monday_board_id,
        board_url=customer.monday_board_url,
    )
    if check_board and response.token_configured and customer.monday_board_id:
        try:
            response.board_name = monday_client.get_board(customer.monday_board_id).name
        except MondayServiceError as exc:
            response.board_error = str(exc)
    return response


def _push_response(result: monday_push.PushResult) -> MondayPushResponse:
    return MondayPushResponse(
        board_url=result.board_url,
        pushed=result.count("pushed"),
        skipped=result.count("skipped"),
        failed=result.count("failed"),
        outcomes=[MondayPushOutcome(**vars(o)) for o in result.outcomes],
    )


@router.get("/customers/{customer_id}/monday", response_model=MondaySettingsResponse)
def get_monday_settings(
    customer_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    return _monday_settings(_get_customer(db, customer_id), check_board=True)


@router.post("/customers/{customer_id}/monday/board", response_model=MondaySettingsResponse)
def create_monday_board(
    customer_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Maak het klantbord aan in de Monday-map (of bevestig het bestaande)."""
    customer = _get_customer(db, customer_id)
    try:
        board = monday_push.ensure_customer_board(db, customer)
    except MondayServiceError as exc:
        raise _monday_http_error(exc) from exc
    response = _monday_settings(customer, check_board=False)
    response.board_name = board.name
    return response


@router.patch("/customers/{customer_id}/monday", response_model=MondaySettingsResponse)
def link_monday_board(
    customer_id: str,
    payload: MondayBoardLink,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Koppel een bestaand bord (id of URL) of ontkoppel met `board: null`."""
    customer = _get_customer(db, customer_id)
    if not (payload.board or "").strip():
        monday_push.unlink_board(db, customer)
        return _monday_settings(customer, check_board=False)
    board_id = monday_client.parse_board_id(payload.board or "")
    if board_id is None:
        raise HTTPException(status_code=400, detail="Vul een bord-id of een Monday-bord-URL in.")
    try:
        board = monday_client.get_board(board_id)
        monday_push.link_board(db, customer, board)
    except MondayServiceError as exc:
        raise _monday_http_error(exc) from exc
    response = _monday_settings(customer, check_board=False)
    response.board_name = board.name
    return response


@router.post("/customers/{customer_id}/monday/sync")
def sync_monday_links(
    customer_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Ruim koppelingen op naar items die in Monday verwijderd zijn."""
    customer = _get_customer(db, customer_id)
    if not monday_client.is_configured() or not customer.monday_board_id:
        return {"cleared": 0}
    try:
        return {"cleared": monday_push.sync_links(db, customer)}
    except MondayServiceError as exc:
        raise _monday_http_error(exc) from exc


@router.post("/issues/push-monday", response_model=MondayPushResponse)
def push_issues_to_monday(
    payload: MondayPushIssuesRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    try:
        result = monday_push.push_issues(db, payload.issue_ids, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MondayServiceError as exc:
        raise _monday_http_error(exc) from exc
    return _push_response(result)


@router.post("/customers/{customer_id}/checklist/push-monday", response_model=MondayPushResponse)
def push_checklist_to_monday(
    customer_id: str,
    payload: MondayPushChecklistRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    customer = _get_customer(db, customer_id)
    try:
        result = monday_push.push_checklist_items(db, customer, payload.item_keys, user_id)
    except MondayServiceError as exc:
        raise _monday_http_error(exc) from exc
    return _push_response(result)


# --- Search Console (fase 4) ---------------------------------------------------

_GSC_SITES_TTL_SECONDS = 600.0
# (tijdstip, properties) van de laatste sites.list; het account is voor alle klanten hetzelfde.
_gsc_sites_cache: tuple[float, list[dict[str, str]]] | None = None


def _gsc_sites(*, refresh: bool = False) -> list[dict[str, str]]:
    global _gsc_sites_cache
    cached = _gsc_sites_cache
    if not refresh and cached is not None and time.monotonic() - cached[0] < _GSC_SITES_TTL_SECONDS:
        return cached[1]
    sites = gsc_client.list_sites()
    _gsc_sites_cache = (time.monotonic(), sites)
    return sites


def _search_console_settings(customer: CustomerWebsite, *, refresh: bool = False) -> SearchConsoleSettingsResponse:
    response = SearchConsoleSettingsResponse(configured=gsc_client.is_configured())
    manual = (customer.gsc_property or "").strip() or None
    if manual:
        response.property, response.property_source = manual, "manual"
    if not response.configured:
        return response
    try:
        sites = _gsc_sites(refresh=refresh)
    except SearchConsoleServiceError as exc:
        response.error = str(exc)
        return response
    response.properties = [SearchConsoleProperty(**site) for site in sites]
    response.candidates = gsc_enrich.match_properties(customer.base_url, sites)
    if manual:
        if manual not in {site["site_url"] for site in sites}:
            response.error = "Het Google-account heeft geen toegang (meer) tot de gekozen property."
    else:
        response.property, source = gsc_enrich.resolve_property(None, customer.base_url, sites)
        response.property_source = "auto" if source else None
    return response


@router.get("/customers/{customer_id}/search-console", response_model=SearchConsoleSettingsResponse)
def get_search_console_settings(
    customer_id: str,
    refresh: bool = Query(default=False),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Welke Search Console-property de fase 4-scan voor deze klant gebruikt."""
    return _search_console_settings(_get_customer(db, customer_id), refresh=refresh)


@router.patch("/customers/{customer_id}/search-console", response_model=SearchConsoleSettingsResponse)
def set_search_console_property(
    customer_id: str,
    payload: SearchConsolePropertyUpdate,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Kies de property van de klant, of zet hem met `property: null` terug op automatisch."""
    customer = _get_customer(db, customer_id)
    chosen = (payload.property or "").strip() or None
    if chosen is not None:
        try:
            sites = _gsc_sites(refresh=True)
        except SearchConsoleServiceError as exc:
            status = 400 if exc.code == "not_configured" else 502
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        if chosen not in {site["site_url"] for site in sites}:
            raise HTTPException(
                status_code=400,
                detail="Het Google-account heeft geen toegang tot deze property. Kies er een uit de lijst.",
            )
    customer.gsc_property = chosen
    customer.updated_at = _now()
    db.commit()
    return _search_console_settings(customer)


@router.patch("/scans/{scan_id}/pages/{page_id}/page-type")
async def update_page_type(
    scan_id: str,
    page_id: str,
    payload: PageTypeUpdate,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """scan_id mag de fase-1 scan of een fase-2 scan zijn."""
    if payload.page_type not in PAGE_TYPES:
        raise HTTPException(status_code=400, detail="Onbekend paginatype.")
    scan = _get_scan(db, scan_id)
    source_id = scan.source_scan_id if scan.phase == 2 else scan.id
    page = db.get(LaunchScanPage, page_id)
    if page is None or page.scan_id != source_id:
        raise HTTPException(status_code=404, detail="Pagina niet gevonden.")

    override = (
        db.query(LaunchPageTypeOverride)
        .filter(LaunchPageTypeOverride.customer_website_id == scan.customer_website_id,
                LaunchPageTypeOverride.path == page.path)
        .first()
    )
    if override is None:
        override = LaunchPageTypeOverride(id=str(uuid.uuid4()), customer_website_id=scan.customer_website_id,
                                          path=page.path, page_type=payload.page_type)
        db.add(override)
    override.page_type = payload.page_type
    override.updated_at = _now()
    page.page_type = payload.page_type
    page.page_type_source = "manual"
    db.flush()

    geo = (
        db.query(LaunchScan)
        .filter(LaunchScan.source_scan_id == source_id, LaunchScan.phase == 2, LaunchScan.status == "completed")
        .order_by(LaunchScan.created_at.desc())
        .first()
    )
    if geo is not None:
        rebuild_checklist(db, geo)
    db.commit()
    return {"ok": True, "page_id": page.id, "page_type": page.page_type}


@router.get("/page-types")
async def list_page_types(_user_id: str = Depends(require_user_id)):
    return {"page_types": [{"key": k, "label": v} for k, v in PAGE_TYPES.items()]}


# --- fase 3: content & onpage ----------------------------------------------

def _build_content_checklist(
    db: Session, customer: CustomerWebsite, scan: LaunchScan | None = None
) -> ContentChecklistResponse:
    """Fase-3 checklist voor `scan`; zonder scan de laatste fase-3 scan met resultaat."""
    if scan is None:
        scan = _latest_content_scan(db, customer.id)
    payload = (scan.checklist if scan else None) or {}
    merged = merged_content_checklist(db, customer.id, scan)
    return ContentChecklistResponse(
        customer_id=customer.id,
        customer_name=customer.name,
        base_url=customer.base_url,
        scan=to_scan_item(scan) if scan else None,
        source_scan_id=scan.source_scan_id if scan else None,
        page_types=payload.get("page_types") or {},
        generated_at=payload.get("generated_at"),
        gap_analyzed_at=payload.get("gap_analyzed_at"),
        summary=payload.get("summary"),
        max_pages_per_analysis=settings.launch_content_max_pages_per_analysis,
        sections=merged["sections"],
        done=merged["done"],
        total=merged["total"],
        percent=merged["percent"],
    )


def _get_content_scan(db: Session, scan_id: str) -> LaunchScan:
    scan = _get_scan(db, scan_id)
    if scan.phase != 3:
        raise HTTPException(status_code=400, detail="Dit is geen fase-3 scan.")
    return scan


def _suggestion_counts(db: Session, scan_id: str) -> dict[str | None, tuple[int, int]]:
    """content_page_id → (open voorstellen, alle voorstellen)."""
    rows = (
        db.query(
            LaunchContentSuggestion.content_page_id,
            LaunchContentSuggestion.status,
            func.count(LaunchContentSuggestion.id),
        )
        .filter(LaunchContentSuggestion.scan_id == scan_id)
        .group_by(LaunchContentSuggestion.content_page_id, LaunchContentSuggestion.status)
        .all()
    )
    out: dict[str | None, tuple[int, int]] = {}
    for page_id, status, count in rows:
        open_count, total = out.get(page_id, (0, 0))
        out[page_id] = (open_count + (count if status == "open" else 0), total + count)
    return out


@router.post("/customers/{customer_id}/content-scans", response_model=LaunchScanDetail)
async def start_content_scan(
    customer_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    from app.worker.tasks import run_content_scan_task  # voorkom circulaire import

    customer = _get_customer(db, customer_id)
    geo = _latest_completed_geo(db, customer.id)
    source = db.get(LaunchScan, geo.source_scan_id) if geo and geo.source_scan_id else None
    if geo is None or source is None:
        raise HTTPException(
            status_code=400, detail="Voer eerst een voltooide fase-2 scan (GEO/SEO-checklist) uit.")

    running = (
        db.query(LaunchScan)
        .filter(LaunchScan.customer_website_id == customer.id, LaunchScan.status.in_(ACTIVE_STATUSES))
        .first()
    )
    if running:
        raise HTTPException(status_code=409, detail="Er loopt al een scan voor deze klant.")

    now = _now()
    scan = LaunchScan(
        id=str(uuid.uuid4()),
        customer_website_id=customer.id,
        phase=3,
        source_scan_id=source.id,
        status="pending",
        base_url=source.base_url,
        discovery_source=source.discovery_source,
        total_urls=0,
        inventoried_urls=0,
        failed_urls=0,
        max_pages=source.max_pages,
        vitals_max_pages=0,
        vitals_total=0,
        vitals_measured=0,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    run_content_scan_task.delay(scan.id)
    return to_scan_detail(scan)


@router.get("/customers/{customer_id}/content-checklist", response_model=ContentChecklistResponse)
async def get_content_checklist(
    customer_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    return _build_content_checklist(db, _get_customer(db, customer_id))


@router.patch("/customers/{customer_id}/content-checklist/{item_key}", response_model=ChecklistItemOut)
async def update_content_checklist_item(
    customer_id: str,
    item_key: str,
    payload: ChecklistStateUpdate,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    customer = _get_customer(db, customer_id)
    if item_key not in CONTENT_ITEMS:
        raise HTTPException(status_code=404, detail="Onbekend checklistpunt.")
    state = (
        db.query(LaunchChecklistState)
        .filter(LaunchChecklistState.customer_website_id == customer.id,
                LaunchChecklistState.item_key == item_key)
        .first()
    )
    if state is None:
        state = LaunchChecklistState(id=str(uuid.uuid4()), customer_website_id=customer.id, item_key=item_key)
        db.add(state)
    fields = payload.model_fields_set
    if "manual_status" in fields:
        state.manual_status = payload.manual_status
    if "note" in fields:
        state.note = (payload.note or "").strip() or None
    state.updated_by = user_id
    state.updated_at = _now()
    db.commit()

    response = _build_content_checklist(db, customer)
    for section in response.sections:
        for item in section.items:
            if item.key == item_key:
                return item
    raise HTTPException(status_code=500, detail="Checklistpunt niet gevonden na opslaan.")


@router.post("/customers/{customer_id}/content-checklist/push-monday", response_model=MondayPushResponse)
def push_content_checklist_to_monday(
    customer_id: str,
    payload: MondayPushChecklistRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    customer = _get_customer(db, customer_id)
    try:
        result = monday_push.push_checklist_items(db, customer, payload.item_keys, user_id, phase=3)
    except MondayServiceError as exc:
        raise _monday_http_error(exc) from exc
    return _push_response(result)


_CONTENT_PAGE_FILTERS = {
    "problems": lambda q: q.filter(LaunchContentPage.problem_count > 0),
    "analysed": lambda q: q.filter(LaunchContentPage.analysis_status == "done"),
    "not_analysed": lambda q: q.filter(LaunchContentPage.analysis_status.in_(("none", "failed"))),
}


@router.get("/scans/{scan_id}/content-pages", response_model=ContentPageListResponse)
async def list_content_pages(
    scan_id: str,
    page_type: str | None = Query(default=None, max_length=40),
    filter: str | None = Query(default=None, pattern="^(problems|analysed|not_analysed)$"),
    search: str | None = Query(default=None, max_length=200),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    scan = _get_content_scan(db, scan_id)
    base = db.query(LaunchContentPage).filter(LaunchContentPage.scan_id == scan.id)
    page_types = dict(Counter(
        row[0] or "overig"
        for row in db.query(LaunchContentPage.page_type).filter(LaunchContentPage.scan_id == scan.id)
    ))
    if page_type:
        base = base.filter(func.coalesce(LaunchContentPage.page_type, "overig") == page_type)
    if filter:
        base = _CONTENT_PAGE_FILTERS[filter](base)
    if search and search.strip():
        needle = f"%{search.strip()}%"
        base = base.filter(LaunchContentPage.url.ilike(needle) | LaunchContentPage.title.ilike(needle))
    rows = base.order_by(LaunchContentPage.problem_count.desc(), LaunchContentPage.path.asc()).all()
    counts = _suggestion_counts(db, scan.id)
    open_items: dict[str, set[str]] = {}
    for page_id, key in (
        db.query(LaunchContentSuggestion.content_page_id, LaunchContentSuggestion.item_key)
        .filter(LaunchContentSuggestion.scan_id == scan.id, LaunchContentSuggestion.status == "open",
                LaunchContentSuggestion.content_page_id.isnot(None))
        .distinct()
    ):
        open_items.setdefault(page_id, set()).add(key)
    items = []
    for row in rows:
        fields = content_page_fields(row, counts.get(row.id, (0, 0)))
        fields["suggestion_items"] = sorted(open_items.get(row.id, ()))
        # In de lijst alleen status + melding per punt; details staan in de pagina-detail.
        fields["checks"] = {
            key: {"status": check.get("status"), "message": check.get("message")}
            for key, check in (row.checks or {}).items()
        }
        items.append(ContentPageItem(**fields))
    return ContentPageListResponse(items=items, total=len(items), page_types=page_types)


def _content_page_detail(db: Session, page: LaunchContentPage) -> ContentPageDetail:
    suggestions = (
        db.query(LaunchContentSuggestion)
        .filter(LaunchContentSuggestion.content_page_id == page.id)
        .order_by(LaunchContentSuggestion.item_key, LaunchContentSuggestion.created_at)
        .all()
    )
    open_count = sum(1 for s in suggestions if s.status == "open")
    return ContentPageDetail(
        **content_page_fields(page, (open_count, len(suggestions))),
        suggestion_items=sorted({s.item_key for s in suggestions if s.status == "open"}),
        headings=page.headings,
        first_paragraph=page.first_paragraph,
        readability=(page.signals or {}).get("readability"),
        images_total=len(page.images or []),
        links_total=len(page.links or []),
        suggestions=[to_suggestion_item(s, page.url) for s in suggestions],
    )


def _get_content_page(db: Session, scan_id: str, page_id: str) -> LaunchContentPage:
    scan = _get_content_scan(db, scan_id)
    page = db.get(LaunchContentPage, page_id)
    if page is None or page.scan_id != scan.id:
        raise HTTPException(status_code=404, detail="Pagina niet gevonden.")
    return page


@router.get("/scans/{scan_id}/content-pages/{page_id}", response_model=ContentPageDetail)
async def get_content_page(
    scan_id: str,
    page_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    return _content_page_detail(db, _get_content_page(db, scan_id, page_id))


@router.patch("/scans/{scan_id}/content-pages/{page_id}/keyword", response_model=ContentPageDetail)
async def update_content_page_keyword(
    scan_id: str,
    page_id: str,
    payload: ContentKeywordUpdate,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Focuszoekwoord handmatig vastleggen. De agents gebruiken het bij de volgende
    analyse; bestaande voorstellen wijzigen niet. Leeg = weer automatisch: het zoekwoord
    waarop de pagina nu rankt (Ahrefs) of anders door de AI laten bepalen."""
    page = _get_content_page(db, scan_id, page_id)
    keyword = " ".join((payload.focus_keyword or "").split())
    hint = (page.signals or {}).get("ahrefs") or None
    if keyword:
        page.focus_keyword = keyword
        page.keyword_source = "manual"
        if "intent" in payload.model_fields_set:
            page.intent = payload.intent
    elif ahrefs_enrich.is_fixed_keyword(hint):
        page.focus_keyword = hint["keyword"]
        page.keyword_source = "ahrefs"
        page.intent = None
    else:
        page.focus_keyword = None
        page.intent = None
        page.keyword_source = None
    db.commit()
    return _content_page_detail(db, page)


@router.post("/scans/{scan_id}/content-analysis", response_model=LaunchScanDetail)
async def start_content_analysis(
    scan_id: str,
    payload: ContentAnalysisRequest,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Start de AI-analyse voor de geselecteerde pagina's van een voltooide fase-3 scan."""
    from app.worker.tasks import run_content_analysis_task  # voorkom circulaire import

    scan = _get_content_scan(db, scan_id)
    if scan.status != "completed":
        raise HTTPException(status_code=409, detail=f"De scan is niet klaar voor analyse (status: {scan.status}).")
    page_ids = list(dict.fromkeys(payload.page_ids))
    if not page_ids and not payload.run_gap:
        raise HTTPException(status_code=400, detail="Selecteer minstens één pagina.")
    limit = settings.launch_content_max_pages_per_analysis
    if len(page_ids) > limit:
        raise HTTPException(status_code=400, detail=f"Selecteer maximaal {limit} pagina's per analyse.")
    running = (
        db.query(LaunchScan)
        .filter(LaunchScan.customer_website_id == scan.customer_website_id,
                LaunchScan.status.in_(ACTIVE_STATUSES))
        .first()
    )
    if running:
        raise HTTPException(status_code=409, detail="Er loopt al een scan voor deze klant.")
    pages = (
        db.query(LaunchContentPage)
        .filter(LaunchContentPage.scan_id == scan.id, LaunchContentPage.id.in_(page_ids))
        .all()
    )
    if len(pages) != len(page_ids):
        raise HTTPException(status_code=400, detail="Een of meer pagina's horen niet bij deze scan.")

    for page in pages:
        page.analysis_status = "queued"
        page.analysis_error = None
    scan.status = "analyzing"
    scan.vitals_total = len(page_ids)
    scan.vitals_measured = 0
    scan.updated_at = _now()
    db.commit()
    db.refresh(scan)

    run_content_analysis_task.delay(scan.id, page_ids, payload.run_gap)
    return to_scan_detail(scan)


@router.get("/scans/{scan_id}/suggestions", response_model=ContentSuggestionListResponse)
async def list_content_suggestions(
    scan_id: str,
    scope: str = Query(default="new", pattern="^(pages|new|all)$"),
    item_key: str | None = Query(default=None, max_length=60),
    status: str | None = Query(default=None, pattern="^(open|overgenomen|afgewezen)$"),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    scan = _get_content_scan(db, scan_id)
    query = db.query(LaunchContentSuggestion).filter(LaunchContentSuggestion.scan_id == scan.id)
    if scope == "new":
        query = query.filter(LaunchContentSuggestion.content_page_id.is_(None))
    elif scope == "pages":
        query = query.filter(LaunchContentSuggestion.content_page_id.isnot(None))
    if item_key:
        query = query.filter(LaunchContentSuggestion.item_key == item_key)
    if status:
        query = query.filter(LaunchContentSuggestion.status == status)
    rows = query.order_by(LaunchContentSuggestion.item_key, LaunchContentSuggestion.created_at).all()
    urls = {
        p.id: p.url
        for p in db.query(LaunchContentPage.id, LaunchContentPage.url)
        .filter(LaunchContentPage.scan_id == scan.id)
    } if scope != "new" else {}
    return ContentSuggestionListResponse(
        items=[to_suggestion_item(r, urls.get(r.content_page_id)) for r in rows], total=len(rows))


@router.patch("/suggestions/{suggestion_id}", response_model=ContentSuggestionItem)
async def update_content_suggestion(
    suggestion_id: str,
    payload: SuggestionStatusUpdate,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    row = db.get(LaunchContentSuggestion, suggestion_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Voorstel niet gevonden.")
    row.status = payload.status
    row.updated_by = user_id
    row.updated_at = _now()
    db.flush()
    scan = db.get(LaunchScan, row.scan_id)
    # Afgehandelde voorstellen tellen niet meer mee in de checklist.
    if scan is not None and scan.status == "completed":
        rebuild_content_checklist(db, scan)
    db.commit()
    page = db.get(LaunchContentPage, row.content_page_id) if row.content_page_id else None
    return to_suggestion_item(row, page.url if page else None)


# --- fase 4: kwartaal GEO-werkzaamheden --------------------------------------

def _period_param(period: str | None) -> str:
    """Ronde uit de query; leeg = de huidige ronde (kwartaal van vandaag)."""
    if not period:
        return period_of()
    if not is_period(period):
        raise HTTPException(status_code=400, detail="Ongeldige ronde (verwacht bijv. 2026-Q4).")
    return period


def _build_quarterly_checklist(
    db: Session, customer: CustomerWebsite, period: str, scan: LaunchScan | None = None
) -> QuarterlyChecklistResponse:
    """Fase-4 checklist van één ronde; zonder scan de laatste voltooide scan van die ronde."""
    if scan is None:
        scan = latest_quarterly_scan(db, customer.id, period)
    payload = (scan.checklist if scan else None) or {}
    merged = merged_quarterly_checklist(db, customer.id, scan, period)
    current = period_of()
    known = quarterly_periods(db, customer.id)
    options = {p: scanned for p, scanned in known.items()}
    options.setdefault(current, False)
    options.setdefault(period, scan is not None)
    return QuarterlyChecklistResponse(
        customer_id=customer.id,
        customer_name=customer.name,
        base_url=customer.base_url,
        period=period,
        period_label=period_label(period),
        current_period=current,
        periods=[
            QuarterlyPeriodOption(period=p, label=period_label(p), scanned=options[p])
            for p in sorted(options, reverse=True)
        ],
        scan=to_scan_item(scan) if scan else None,
        generated_at=payload.get("generated_at"),
        comparison=payload.get("comparison"),
        sources=payload.get("sources"),
        summary=payload.get("summary"),
        sections=merged["sections"],
        done=merged["done"],
        total=merged["total"],
        percent=merged["percent"],
    )


@router.post("/customers/{customer_id}/quarterly-scans", response_model=LaunchScanDetail)
async def start_quarterly_scan(
    customer_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    from app.worker.tasks import run_quarterly_scan_task  # voorkom circulaire import

    customer = _get_customer(db, customer_id)
    if _latest_content_scan(db, customer.id) is None:
        raise HTTPException(
            status_code=400, detail="Voer eerst een voltooide fase-3 scan (content & onpage) uit.")
    nulmeting = latest_completed_scan(db, customer.id, 1)
    if nulmeting is None:
        raise HTTPException(status_code=400, detail="Voer eerst een voltooide fase-1 scan (nulmeting) uit.")

    running = (
        db.query(LaunchScan)
        .filter(LaunchScan.customer_website_id == customer.id, LaunchScan.status.in_(ACTIVE_STATUSES))
        .first()
    )
    if running:
        raise HTTPException(status_code=409, detail="Er loopt al een scan voor deze klant.")

    base_url = _normalize_base_url(customer.base_url or nulmeting.base_url)
    try:
        validate_external_url(base_url)
    except UnsafeURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = _now()
    scan = LaunchScan(
        id=str(uuid.uuid4()),
        customer_website_id=customer.id,
        phase=4,
        period=period_of(now),
        status="pending",
        base_url=base_url,
        total_urls=0,
        inventoried_urls=0,
        failed_urls=0,
        max_pages=nulmeting.max_pages,
        vitals_max_pages=0,
        vitals_total=0,
        vitals_measured=0,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    run_quarterly_scan_task.delay(scan.id)
    return to_scan_detail(scan)


@router.get("/customers/{customer_id}/quarterly-checklist", response_model=QuarterlyChecklistResponse)
async def get_quarterly_checklist(
    customer_id: str,
    period: str | None = Query(default=None, max_length=10),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    return _build_quarterly_checklist(db, _get_customer(db, customer_id), _period_param(period))


@router.patch("/customers/{customer_id}/quarterly-checklist/{item_key}", response_model=ChecklistItemOut)
async def update_quarterly_checklist_item(
    customer_id: str,
    item_key: str,
    payload: ChecklistStateUpdate,
    period: str | None = Query(default=None, max_length=10),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    customer = _get_customer(db, customer_id)
    if item_key not in QUARTERLY_ITEMS:
        raise HTTPException(status_code=404, detail="Onbekend checklistpunt.")
    round_ = _period_param(period)
    state = (
        db.query(LaunchChecklistState)
        .filter(LaunchChecklistState.customer_website_id == customer.id,
                LaunchChecklistState.item_key == item_key,
                LaunchChecklistState.period == round_)
        .first()
    )
    if state is None:
        state = LaunchChecklistState(
            id=str(uuid.uuid4()), customer_website_id=customer.id, item_key=item_key, period=round_)
        db.add(state)
    fields = payload.model_fields_set
    if "manual_status" in fields:
        state.manual_status = payload.manual_status
    if "note" in fields:
        state.note = (payload.note or "").strip() or None
    state.updated_by = user_id
    state.updated_at = _now()
    db.commit()

    response = _build_quarterly_checklist(db, customer, round_)
    for section in response.sections:
        for item in section.items:
            if item.key == item_key:
                return item
    raise HTTPException(status_code=500, detail="Checklistpunt niet gevonden na opslaan.")


@router.post("/customers/{customer_id}/quarterly-checklist/push-monday", response_model=MondayPushResponse)
def push_quarterly_checklist_to_monday(
    customer_id: str,
    payload: MondayPushChecklistRequest,
    period: str | None = Query(default=None, max_length=10),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    customer = _get_customer(db, customer_id)
    try:
        result = monday_push.push_checklist_items(
            db, customer, payload.item_keys, user_id, phase=4, period=_period_param(period))
    except MondayServiceError as exc:
        raise _monday_http_error(exc) from exc
    return _push_response(result)


# --- export ---------------------------------------------------------------

def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "ja" if value else "nee"
    if isinstance(value, list):
        return " | ".join(str(v.get("url", v)) if isinstance(v, dict) else str(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}={v}" for k, v in value.items())
    return str(value)


@router.get("/scans/{scan_id}/export")
async def export_launch_scan(
    scan_id: str,
    kind: str = Query(default="inventory", pattern="^(inventory|issues|checklist|suggestions)$"),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    scan = _get_scan(db, scan_id)
    buffer = io.StringIO()
    buffer.write("﻿")  # BOM zodat Excel UTF-8 herkent
    writer = csv.writer(buffer, delimiter=";")

    if kind == "suggestions":
        urls = {
            p.id: p.url
            for p in db.query(LaunchContentPage).filter(LaunchContentPage.scan_id == scan_id).all()
        }
        writer.writerow(["Pagina", "Checklistpunt", "Onderdeel", "Huidig", "Voorstel", "Toelichting",
                         "Verwijzing", "Agent", "Status"])
        rows = (
            db.query(LaunchContentSuggestion)
            .filter(LaunchContentSuggestion.scan_id == scan_id)
            .order_by(LaunchContentSuggestion.content_page_id, LaunchContentSuggestion.item_key,
                      LaunchContentSuggestion.created_at)
            .all()
        )
        for row in rows:
            item = CONTENT_ITEMS.get(row.item_key)
            writer.writerow([
                urls.get(row.content_page_id, "Nieuwe content"), item.label if item else row.item_key,
                row.title or "", row.current_value or "", row.proposed_value, row.rationale or "",
                (row.details or {}).get("ref", "") if isinstance(row.details, dict) else "",
                row.agent, row.status,
            ])
    elif kind == "checklist" and scan.phase in (3, 4):
        customer = _get_customer(db, scan.customer_website_id)
        if scan.phase == 4:
            checklist = _build_quarterly_checklist(
                db, customer, scan.period or period_of(scan.created_at),
                scan if scan.status == "completed" else None,
            )
        else:
            checklist = _build_content_checklist(db, customer, scan if scan.checklist else None)
        status_labels = {"done": "Afgerond", "open": "Open", "nvt": "N.v.t."}
        writer.writerow(["Hoofditem", "Subitem", "Type", "Prioriteit", "Auto-status", "Melding",
                         "Handmatige status", "Notitie", "Eindstatus", "Evidence"])
        for section in checklist.sections:
            for item in section.items:
                auto = item.auto or {}
                writer.writerow([
                    section.label, item.label, item.mode, item.priority,
                    auto.get("status", ""), auto.get("message", ""), item.manual_status or "",
                    item.note or "", status_labels.get(item.effective, item.effective),
                    _fmt([str(e) for e in (auto.get("evidence") or [])[:10]]),
                ])
    elif kind == "checklist":
        customer = _get_customer(db, scan.customer_website_id)
        # De gevraagde fase-2 scan; bij een fase-1 scan de laatste checklist.
        geo = scan if scan.phase == 2 and scan.status == "completed" else None
        checklist = _build_checklist(db, customer, geo)
        status_labels = {"done": "Afgerond", "open": "Open", "nvt": "N.v.t."}
        writer.writerow(["Sectie", "Punt", "Type", "Prioriteit", "Auto-status", "Melding",
                         "Handmatige status", "Notitie", "Eindstatus", "Evidence"])
        for section in checklist.sections:
            for item in section.items:
                auto = item.auto or {}
                writer.writerow([
                    SECTION_LABELS.get(section.key, section.key), item.label, item.mode, item.priority,
                    auto.get("status", ""), auto.get("message", ""), item.manual_status or "",
                    item.note or "", status_labels.get(item.effective, item.effective),
                    _fmt([str(e) for e in (auto.get("evidence") or [])[:10]]),
                ])
    elif kind == "issues":
        writer.writerow(["Ernst", "Categorie", "Type", "Titel", "URL", "Beschrijving", "Aanbeveling", "Status"])
        rows = db.query(LaunchScanIssue).filter(LaunchScanIssue.scan_id == scan_id).all()
        rows.sort(key=lambda i: (_SEVERITY_ORDER.get(i.severity, 9), i.issue_type))
        for i in rows:
            writer.writerow([
                i.severity, i.category, ISSUE_TYPES.get(i.issue_type, {}).get("label", i.issue_type),
                i.title, i.url or "", i.description, i.recommendation or "", i.status,
            ])
    else:
        writer.writerow([
            "URL", "In sitemap", "Statuscode", "Eind-URL", "Redirects", "Responstijd (ms)", "Content-type",
            "Grootte (bytes)", "HTTP-versie", "Indexeerbaar", "Reden niet indexeerbaar", "Meta robots",
            "Title", "Title lengte", "Meta description", "Meta description lengte", "H1 aantal", "H1",
            "H2", "Canonical", "Woorden", "Lang", "Hreflang", "Interne links", "Externe links",
            "Kapotte links", "Afbeeldingen", "Zonder alt", "Schema types", "Open Graph",
            "CWV status", "CWV bron", "Performance score", "LCP (ms)", "CLS", "TBT (ms)", "FCP (ms)",
            "Veld LCP", "Veld INP", "Veld CLS", "Fout",
            "Organisch verkeer (Ahrefs)", "Verwijzende domeinen (Ahrefs)", "Topzoekwoord", "Positie topzoekwoord",
            "Volume topzoekwoord", "Niet in crawl (alleen Ahrefs)",
        ])
        pages = (
            db.query(LaunchScanPage)
            .filter(LaunchScanPage.scan_id == scan_id)
            .order_by(LaunchScanPage.path.asc())
            .all()
        )
        for p in pages:
            cwv = p.cwv or {}
            lab = cwv.get("lab") or {}
            field = cwv.get("field") or {}
            ahrefs = p.ahrefs or {}

            def fv(name: str) -> str:
                metric = field.get(name)
                return _fmt(metric.get("value")) if isinstance(metric, dict) else ""

            hops = [h for h in (p.redirect_chain or []) if not h.get("final")]
            writer.writerow([
                p.url, _fmt(p.in_sitemap), _fmt(p.status_code), _fmt(p.final_url), len(hops),
                _fmt(p.response_time_ms), _fmt(p.content_type), _fmt(p.size_bytes), _fmt(p.http_version),
                _fmt(p.indexable), _fmt(p.indexability_reason), _fmt(p.meta_robots),
                _fmt(p.title), _fmt(p.title_length), _fmt(p.meta_description), _fmt(p.meta_description_length),
                _fmt(p.h1_count), _fmt(p.h1), _fmt((p.h2 or [])[:10]), _fmt(p.canonical), _fmt(p.word_count),
                _fmt(p.lang), _fmt([h.get("lang") for h in (p.hreflang or [])]), _fmt(p.internal_links),
                _fmt(p.external_links), _fmt(p.broken_links), _fmt(p.images_total), _fmt(p.images_missing_alt),
                _fmt(p.schema_types), _fmt(p.open_graph), _fmt(p.cwv_status), _fmt(cwv.get("source")),
                _fmt(lab.get("performance_score")), _fmt(lab.get("lcp")), _fmt(lab.get("cls")),
                _fmt(lab.get("tbt")), _fmt(lab.get("fcp")), fv("lcp"), fv("inp"), fv("cls"),
                _fmt(p.error or cwv.get("error")),
                _fmt(p.org_traffic), _fmt(p.refdomains), _fmt(ahrefs.get("top_keyword")),
                _fmt(ahrefs.get("top_keyword_position")), _fmt(ahrefs.get("top_keyword_volume")),
                _fmt(ahrefs.get("source") == "ahrefs") if ahrefs else "",
            ])

    customer = db.get(CustomerWebsite, scan.customer_website_id)
    slug = (customer.domain if customer else "scan").replace("/", "-")
    prefix = {
        2: "geo-seo-checklist", 3: "content-onpage", 4: f"kwartaal-geo-{scan.period or ''}".rstrip("-"),
    }.get(scan.phase, "nulmeting")
    filename = f"{prefix}-{slug}-{kind}-{scan.created_at:%Y%m%d}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
