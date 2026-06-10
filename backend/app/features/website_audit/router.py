import uuid
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id, utc_now_iso
from app.core.url_guard import UnsafeURLError, validate_external_url
from app.db.models import AuditIssue, AuditPage, WebsiteAudit
from app.db.session import get_db
from app.features.website_audit.mappers import (
    to_audit_issue_item,
    to_audit_item,
    to_audit_page_item,
)
from app.features.website_audit.schemas import (
    AuditCreateRequest,
    AuditIssueListResponse,
    AuditItem,
    AuditListResponse,
    AuditPageListResponse,
    StartAuditResponse,
)

router = APIRouter(tags=["audit"])


def _row_to_dict(obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}  # type: ignore[union-attr]


def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower() or url
    except Exception:
        return url


@router.post("/api/audit", response_model=StartAuditResponse)
async def start_audit(
    payload: AuditCreateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    # Import here to avoid circular import at module load time
    from app.worker.tasks import run_website_audit_task  # type: ignore[attr-defined]

    url = payload.url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    try:
        validate_external_url(url)
    except UnsafeURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    domain = _extract_domain(url)
    now = utc_now_iso()
    audit_id = str(uuid.uuid4())

    audit = WebsiteAudit(
        id=audit_id,
        url=url,
        domain=domain,
        status="pending",
        total_pages=0,
        scanned_pages=0,
        failed_pages=0,
        max_pages=payload.max_pages,
        crawl_source=None,
        summary=None,
        error_message=None,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    run_website_audit_task.delay(audit_id)

    return StartAuditResponse(audit_id=audit_id, status="pending", url=url)


@router.get("/api/audit", response_model=AuditListResponse)
async def list_audits(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    query = (
        db.query(WebsiteAudit)
        .filter(WebsiteAudit.created_by == user_id)
        .order_by(WebsiteAudit.created_at.desc())
    )
    total = query.count()
    audits = query.offset(offset).limit(limit).all()

    return AuditListResponse(
        items=[to_audit_item(_row_to_dict(a)) for a in audits],
        total=total,
    )


@router.get("/api/audit/{audit_id}", response_model=AuditItem)
async def get_audit(
    audit_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    audit = (
        db.query(WebsiteAudit)
        .filter(WebsiteAudit.id == audit_id, WebsiteAudit.created_by == user_id)
        .first()
    )
    if not audit:
        raise HTTPException(status_code=404, detail="Audit niet gevonden.")
    return to_audit_item(_row_to_dict(audit))


@router.get("/api/audit/{audit_id}/pages", response_model=AuditPageListResponse)
async def list_audit_pages(
    audit_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    audit = (
        db.query(WebsiteAudit)
        .filter(WebsiteAudit.id == audit_id, WebsiteAudit.created_by == user_id)
        .first()
    )
    if not audit:
        raise HTTPException(status_code=404, detail="Audit niet gevonden.")

    pages_query = (
        db.query(AuditPage)
        .filter(AuditPage.audit_id == audit_id)
        .order_by(AuditPage.path.asc(), AuditPage.created_at.asc())
    )
    total = pages_query.count()
    pages = pages_query.offset(offset).limit(limit).all()

    return AuditPageListResponse(
        pages=[to_audit_page_item(_row_to_dict(p)) for p in pages],
        total=total,
    )


@router.get("/api/audit/{audit_id}/issues", response_model=AuditIssueListResponse)
async def list_audit_issues(
    audit_id: str,
    category: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    audit = (
        db.query(WebsiteAudit)
        .filter(WebsiteAudit.id == audit_id, WebsiteAudit.created_by == user_id)
        .first()
    )
    if not audit:
        raise HTTPException(status_code=404, detail="Audit niet gevonden.")

    issues_query = (
        db.query(AuditIssue)
        .filter(AuditIssue.audit_id == audit_id)
        .order_by(AuditIssue.created_at.asc())
    )

    valid_categories = {
        "typography", "performance", "accessibility", "links",
        "responsive", "seo", "console_error", "functionality",
    }
    valid_severities = {"critical", "warning", "info"}

    if category and category in valid_categories:
        issues_query = issues_query.filter(AuditIssue.category == category)
    if severity and severity in valid_severities:
        issues_query = issues_query.filter(AuditIssue.severity == severity)

    total = issues_query.count()
    issues = issues_query.offset(offset).limit(limit).all()

    return AuditIssueListResponse(
        issues=[to_audit_issue_item(_row_to_dict(i)) for i in issues],
        total=total,
    )


@router.post("/api/audit/{audit_id}/cancel")
async def cancel_audit(
    audit_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    audit = (
        db.query(WebsiteAudit)
        .filter(WebsiteAudit.id == audit_id, WebsiteAudit.created_by == user_id)
        .first()
    )
    if not audit:
        raise HTTPException(status_code=404, detail="Audit niet gevonden.")

    current_status = str(audit.status or "").strip().lower()
    if current_status not in {"pending", "crawling", "scanning"}:
        raise HTTPException(
            status_code=400,
            detail=f"Audit kan niet worden geannuleerd (status: {current_status}).",
        )

    db.query(WebsiteAudit).filter(WebsiteAudit.id == audit_id).update(
        {"status": "canceled", "updated_at": utc_now_iso()}
    )
    db.commit()
    return {"ok": True, "audit_id": audit_id}


@router.delete("/api/audit/{audit_id}")
async def delete_audit(
    audit_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    audit = (
        db.query(WebsiteAudit)
        .filter(WebsiteAudit.id == audit_id, WebsiteAudit.created_by == user_id)
        .first()
    )
    if not audit:
        raise HTTPException(status_code=404, detail="Audit niet gevonden.")

    current_status = str(audit.status or "").strip().lower()
    if current_status in {"crawling", "scanning"}:
        # Cancel first, then delete
        db.query(WebsiteAudit).filter(WebsiteAudit.id == audit_id).update(
            {"status": "canceled", "updated_at": utc_now_iso()}
        )
        db.commit()

    db.query(AuditIssue).filter(AuditIssue.audit_id == audit_id).delete()
    db.query(AuditPage).filter(AuditPage.audit_id == audit_id).delete()
    db.query(WebsiteAudit).filter(WebsiteAudit.id == audit_id).delete()
    db.commit()
    return {"ok": True, "audit_id": audit_id}
