from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id, utc_now_iso
from app.db.models import Blog, CustomerWebsite
from app.db.session import get_db
from app.features.seo_tracker.mappers import to_customer_website_item
from app.features.seo_tracker.schemas import (
    CustomerWebsiteCreateRequest,
    CustomerWebsiteDetailResponse,
    CustomerWebsiteItem,
    CustomerWebsitesResponse,
    CustomerWebsiteUpdateRequest,
)
from app.features.seo_tracker.services import normalize_website_url

router = APIRouter(tags=["customers"])


def _row_to_dict(obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}  # type: ignore[union-attr]


def _current_month_bounds() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    month_start = now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1)
    return month_start, next_month_start


@router.get("/api/customers", response_model=CustomerWebsitesResponse)
async def list_customers(
    active_only: bool = Query(default=False),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    query = db.query(CustomerWebsite)
    if active_only:
        query = query.filter(CustomerWebsite.is_active.is_(True))
    websites = query.order_by(CustomerWebsite.name.asc()).all()
    return CustomerWebsitesResponse(
        websites=[to_customer_website_item(_row_to_dict(w)) for w in websites]
    )


@router.get(
    "/api/customers/{customer_id}", response_model=CustomerWebsiteDetailResponse
)
async def get_customer(
    customer_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    website = (
        db.query(CustomerWebsite)
        .filter(CustomerWebsite.id == customer_id)
        .first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Klant niet gevonden.")

    month_start, next_month_start = _current_month_bounds()
    placed_this_month = (
        db.query(func.count(Blog.id))
        .filter(
            Blog.customer_website_id == customer_id,
            Blog.published_at.isnot(None),
            Blog.published_at >= month_start,
            Blog.published_at < next_month_start,
        )
        .scalar()
        or 0
    )

    base = to_customer_website_item(_row_to_dict(website))
    return CustomerWebsiteDetailResponse(
        **base.model_dump(),
        placed_this_month=int(placed_this_month),
        pending_blogs=None,
    )


@router.post("/api/customers", response_model=CustomerWebsiteItem)
async def create_customer(
    payload: CustomerWebsiteCreateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    name = str(payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Naam is verplicht.")

    try:
        normalized_base_url, root_domain = normalize_website_url(payload.base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    duplicate = (
        db.query(CustomerWebsite).filter(CustomerWebsite.domain == root_domain).first()
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail="Er bestaat al een klant met dit domein.",
        )

    website_id = str(uuid.uuid4())
    now = utc_now_iso()
    website = CustomerWebsite(
        id=website_id,
        name=name,
        base_url=normalized_base_url,
        domain=root_domain,
        is_active=True,
        seo_customer_since=payload.seo_customer_since,
        seo_goals=(payload.seo_goals.strip() or None)
        if isinstance(payload.seo_goals, str)
        else None,
        industry=(payload.industry.strip() or None)
        if isinstance(payload.industry, str)
        else None,
        target_blogs_per_month=payload.target_blogs_per_month,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(website)
    db.commit()
    db.refresh(website)
    return to_customer_website_item(_row_to_dict(website))


@router.patch("/api/customers/{customer_id}", response_model=CustomerWebsiteItem)
async def update_customer(
    customer_id: str,
    payload: CustomerWebsiteUpdateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    website = (
        db.query(CustomerWebsite)
        .filter(CustomerWebsite.id == customer_id)
        .first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Klant niet gevonden.")

    updates: dict[str, Any] = {"updated_at": utc_now_iso()}

    if isinstance(payload.name, str):
        next_name = payload.name.strip()
        if not next_name:
            raise HTTPException(status_code=400, detail="Naam mag niet leeg zijn.")
        updates["name"] = next_name

    if isinstance(payload.base_url, str):
        try:
            next_base_url, next_domain = normalize_website_url(payload.base_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        duplicate = (
            db.query(CustomerWebsite)
            .filter(
                CustomerWebsite.domain == next_domain,
                CustomerWebsite.id != customer_id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail="Er bestaat al een klant met dit domein.",
            )
        updates["base_url"] = next_base_url
        updates["domain"] = next_domain

    if payload.is_active is not None:
        updates["is_active"] = payload.is_active

    provided = payload.model_fields_set
    if "seo_customer_since" in provided:
        updates["seo_customer_since"] = payload.seo_customer_since
    if "seo_goals" in provided:
        updates["seo_goals"] = (
            payload.seo_goals.strip() or None
            if isinstance(payload.seo_goals, str)
            else None
        )
    if "industry" in provided:
        updates["industry"] = (
            payload.industry.strip() or None
            if isinstance(payload.industry, str)
            else None
        )
    if "target_blogs_per_month" in provided:
        updates["target_blogs_per_month"] = payload.target_blogs_per_month

    if len(updates) == 1:
        raise HTTPException(status_code=400, detail="Geen wijzigingen ontvangen.")

    db.query(CustomerWebsite).filter(CustomerWebsite.id == customer_id).update(
        updates  # type: ignore
    )
    db.commit()

    updated_website = (
        db.query(CustomerWebsite)
        .filter(CustomerWebsite.id == customer_id)
        .first()
    )
    if not updated_website:
        raise HTTPException(status_code=500, detail="Kon klant niet bijwerken.")
    return to_customer_website_item(_row_to_dict(updated_website))
