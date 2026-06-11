from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id, utc_now_iso
from app.db.models import CustomerWebsite
from app.db.session import get_db
from app.features.seo_tracker.mappers import to_customer_website_item
from app.features.seo_tracker.schemas import (
    CustomerWebsiteCreateRequest,
    CustomerWebsiteItem,
    CustomerWebsitesResponse,
    CustomerWebsiteUpdateRequest,
)
from app.features.seo_tracker.services import normalize_website_url

router = APIRouter(tags=["customers"])


def _row_to_dict(obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}  # type: ignore[union-attr]


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
