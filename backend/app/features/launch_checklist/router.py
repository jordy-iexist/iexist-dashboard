"""Livegang checklist — fase 1 (Nulmeting & AI scan) endpoints."""
from __future__ import annotations

import csv
import io
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
    LaunchScan,
    LaunchScanIssue,
    LaunchScanPage,
)
from app.db.session import get_db
from app.features.launch_checklist.mappers import (
    to_issue_item,
    to_page_item,
    to_scan_detail,
    to_scan_item,
)
from app.features.launch_checklist.schemas import (
    ACTIVE_STATUSES,
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
from app.features.launch_checklist.services.issues import ISSUE_TYPES

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

@router.get("/customers", response_model=LaunchCustomerListResponse)
async def list_launch_customers(
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    customers = db.query(CustomerWebsite).order_by(CustomerWebsite.name.asc()).all()
    categories = {c.id: c.name for c in db.query(CustomerCategory).all()}

    latest_sub = (
        db.query(
            LaunchScan.customer_website_id,
            func.max(LaunchScan.created_at).label("max_created"),
        )
        .group_by(LaunchScan.customer_website_id)
        .subquery()
    )
    latest_rows = (
        db.query(LaunchScan)
        .join(
            latest_sub,
            (LaunchScan.customer_website_id == latest_sub.c.customer_website_id)
            & (LaunchScan.created_at == latest_sub.c.max_created),
        )
        .all()
    )
    latest = {row.customer_website_id: row for row in latest_rows}

    return LaunchCustomerListResponse(
        customers=[
            LaunchCustomerItem(
                id=c.id,
                name=c.name,
                base_url=c.base_url,
                domain=c.domain,
                category_name=categories.get(c.category_id) if c.category_id else None,
                latest_scan=to_scan_item(latest[c.id]) if c.id in latest else None,
            )
            for c in customers
        ]
    )


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
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    query = db.query(LaunchScan)
    if customer_website_id:
        query = query.filter(LaunchScan.customer_website_id == customer_website_id)
    total = query.count()
    rows = query.order_by(LaunchScan.created_at.desc()).offset(offset).limit(limit).all()
    return LaunchScanListResponse(items=[to_scan_item(r) for r in rows], total=total)


@router.get("/scans/{scan_id}", response_model=LaunchScanDetail)
async def get_launch_scan(
    scan_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    return to_scan_detail(_get_scan(db, scan_id))


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
}


@router.get("/scans/{scan_id}/pages", response_model=LaunchScanPageListResponse)
async def list_launch_scan_pages(
    scan_id: str,
    filter: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
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
    if search:
        like = f"%{search.strip()}%"
        query = query.filter((LaunchScanPage.url.ilike(like)) | (LaunchScanPage.title.ilike(like)))

    sort_columns = {
        "path": LaunchScanPage.path.asc(),
        "status": LaunchScanPage.status_code.desc(),
        "response_time": LaunchScanPage.response_time_ms.desc().nullslast(),
        "words": LaunchScanPage.word_count.asc().nullslast(),
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
    kind: str = Query(default="inventory", pattern="^(inventory|issues)$"),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    scan = _get_scan(db, scan_id)
    buffer = io.StringIO()
    buffer.write("﻿")  # BOM zodat Excel UTF-8 herkent
    writer = csv.writer(buffer, delimiter=";")

    if kind == "issues":
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
            ])

    customer = db.get(CustomerWebsite, scan.customer_website_id)
    slug = (customer.domain if customer else "scan").replace("/", "-")
    filename = f"nulmeting-{slug}-{kind}-{scan.created_at:%Y%m%d}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
