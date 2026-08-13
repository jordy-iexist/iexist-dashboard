from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id, utc_now_iso
from app.db.models import Blog, CustomerCategory, CustomerWebsite, SerpScan, WebsiteMetaRun
from app.db.session import get_db
from app.features.customers.services import delete_customer_website_cascade
from app.features.seo_tracker.mappers import to_customer_website_item
from app.features.seo_tracker.schemas import (
    CustomerCategoriesResponse,
    CustomerCategoryCreateRequest,
    CustomerCategoryItem,
    CustomerCategoryUpdateRequest,
    CustomerWebsiteCreateRequest,
    CustomerWebsiteDetailResponse,
    CustomerWebsiteItem,
    CustomerWebsiteListItem,
    CustomerWebsitesListResponse,
    CustomerWebsiteUpdateRequest,
)
from app.features.seo_tracker.services import normalize_website_url

router = APIRouter(tags=["customers"])


def _row_to_dict(obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}  # type: ignore[union-attr]


def _category_name_map(
    db: Session, category_ids: list[str | None]
) -> dict[str, str]:
    ids = {cid for cid in category_ids if cid}
    if not ids:
        return {}
    categories = (
        db.query(CustomerCategory).filter(CustomerCategory.id.in_(ids)).all()
    )
    return {str(c.id): c.name for c in categories}


def _customer_counts_by_category(db: Session) -> dict[str, int]:
    rows = (
        db.query(CustomerWebsite.category_id, func.count(CustomerWebsite.id))
        .filter(CustomerWebsite.category_id.isnot(None))
        .group_by(CustomerWebsite.category_id)
        .all()
    )
    return {str(category_id): int(count) for category_id, count in rows}


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


def _placed_counts_by_customer(
    db: Session, customer_ids: list[str] | None = None
) -> dict[str, int]:
    month_start, next_month_start = _current_month_bounds()
    query = db.query(Blog.customer_website_id, func.count(Blog.id)).filter(
        Blog.customer_website_id.isnot(None),
        Blog.published_at.isnot(None),
        Blog.published_at >= month_start,
        Blog.published_at < next_month_start,
    )
    if customer_ids is not None:
        query = query.filter(Blog.customer_website_id.in_(customer_ids))
    return {
        str(customer_id): int(count)
        for customer_id, count in query.group_by(Blog.customer_website_id).all()
    }


@router.get("/api/customers", response_model=CustomerWebsitesListResponse)
async def list_customers(
    category_id: str | None = Query(default=None),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    query = db.query(CustomerWebsite)
    if category_id == "none":
        query = query.filter(CustomerWebsite.category_id.is_(None))
    elif category_id:
        query = query.filter(CustomerWebsite.category_id == category_id)
    websites = query.order_by(CustomerWebsite.name.asc()).all()
    placed_counts = _placed_counts_by_customer(db, [str(w.id) for w in websites])
    category_names = _category_name_map(db, [w.category_id for w in websites])
    return CustomerWebsitesListResponse(
        websites=[
            CustomerWebsiteListItem(
                **to_customer_website_item(
                    {
                        **_row_to_dict(w),
                        "category_name": category_names.get(str(w.category_id))
                        if w.category_id
                        else None,
                    }
                ).model_dump(),
                placed_this_month=placed_counts.get(str(w.id), 0),
            )
            for w in websites
        ]
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

    placed_this_month = _placed_counts_by_customer(db, [customer_id]).get(
        customer_id, 0
    )

    category_names = _category_name_map(db, [website.category_id])
    base = to_customer_website_item(
        {
            **_row_to_dict(website),
            "category_name": category_names.get(str(website.category_id))
            if website.category_id
            else None,
        }
    )
    return CustomerWebsiteDetailResponse(
        **base.model_dump(),
        placed_this_month=placed_this_month,
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

    category_id = payload.category_id or None
    if category_id:
        category = (
            db.query(CustomerCategory)
            .filter(CustomerCategory.id == category_id)
            .first()
        )
        if not category:
            raise HTTPException(status_code=400, detail="Categorie niet gevonden.")

    website_id = str(uuid.uuid4())
    now = utc_now_iso()
    website = CustomerWebsite(
        id=website_id,
        name=name,
        base_url=normalized_base_url,
        domain=root_domain,
        seo_customer_since=payload.seo_customer_since,
        seo_goals=(payload.seo_goals.strip() or None)
        if isinstance(payload.seo_goals, str)
        else None,
        category_id=category_id,
        target_blogs_per_month=payload.target_blogs_per_month,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(website)
    db.commit()
    db.refresh(website)
    category_names = _category_name_map(db, [website.category_id])
    return to_customer_website_item(
        {
            **_row_to_dict(website),
            "category_name": category_names.get(str(website.category_id))
            if website.category_id
            else None,
        }
    )


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

    provided = payload.model_fields_set
    if "seo_customer_since" in provided:
        updates["seo_customer_since"] = payload.seo_customer_since
    if "seo_goals" in provided:
        updates["seo_goals"] = (
            payload.seo_goals.strip() or None
            if isinstance(payload.seo_goals, str)
            else None
        )
    if "category_id" in provided:
        next_category_id = payload.category_id or None
        if next_category_id:
            category = (
                db.query(CustomerCategory)
                .filter(CustomerCategory.id == next_category_id)
                .first()
            )
            if not category:
                raise HTTPException(
                    status_code=400, detail="Categorie niet gevonden."
                )
        updates["category_id"] = next_category_id
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
    category_names = _category_name_map(db, [updated_website.category_id])
    return to_customer_website_item(
        {
            **_row_to_dict(updated_website),
            "category_name": category_names.get(str(updated_website.category_id))
            if updated_website.category_id
            else None,
        }
    )


@router.delete("/api/customers/{customer_id}")
async def delete_customer(
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

    running_scan = (
        db.query(SerpScan)
        .filter(
            SerpScan.website_id == customer_id,
            SerpScan.status.in_(["pending", "processing"]),
        )
        .first()
    )
    if running_scan:
        raise HTTPException(
            status_code=409,
            detail="Er draait nog een scan voor deze klant. Annuleer de scan eerst.",
        )

    running_meta = (
        db.query(WebsiteMetaRun)
        .filter(
            WebsiteMetaRun.website_id == customer_id,
            WebsiteMetaRun.status.in_(["pending", "processing"]),
        )
        .first()
    )
    if running_meta:
        raise HTTPException(
            status_code=409,
            detail="Er draait nog een meta run voor deze klant.",
        )

    delete_customer_website_cascade(db, customer_id)
    db.commit()
    return {"success": True}


@router.get("/api/customer-categories", response_model=CustomerCategoriesResponse)
async def list_customer_categories(
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    categories = db.query(CustomerCategory).order_by(CustomerCategory.name.asc()).all()
    counts = _customer_counts_by_category(db)
    return CustomerCategoriesResponse(
        categories=[
            CustomerCategoryItem(
                id=str(c.id),
                name=c.name,
                customer_count=counts.get(str(c.id), 0),
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in categories
        ]
    )


@router.post("/api/customer-categories", response_model=CustomerCategoryItem)
async def create_customer_category(
    payload: CustomerCategoryCreateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    name = str(payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Naam is verplicht.")

    duplicate = (
        db.query(CustomerCategory)
        .filter(func.lower(CustomerCategory.name) == name.lower())
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Deze categorie bestaat al.")

    now = utc_now_iso()
    category = CustomerCategory(
        id=str(uuid.uuid4()),
        name=name,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return CustomerCategoryItem(
        id=str(category.id),
        name=category.name,
        customer_count=0,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )


@router.patch(
    "/api/customer-categories/{category_id}", response_model=CustomerCategoryItem
)
async def update_customer_category(
    category_id: str,
    payload: CustomerCategoryUpdateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    category = (
        db.query(CustomerCategory).filter(CustomerCategory.id == category_id).first()
    )
    if not category:
        raise HTTPException(status_code=404, detail="Categorie niet gevonden.")

    name = str(payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Naam mag niet leeg zijn.")

    duplicate = (
        db.query(CustomerCategory)
        .filter(
            func.lower(CustomerCategory.name) == name.lower(),
            CustomerCategory.id != category_id,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Deze categorie bestaat al.")

    category.name = name
    category.updated_at = utc_now_iso()
    db.commit()
    db.refresh(category)
    counts = _customer_counts_by_category(db)
    return CustomerCategoryItem(
        id=str(category.id),
        name=category.name,
        customer_count=counts.get(str(category.id), 0),
        created_at=category.created_at,
        updated_at=category.updated_at,
    )


@router.delete("/api/customer-categories/{category_id}")
async def delete_customer_category(
    category_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    category = (
        db.query(CustomerCategory).filter(CustomerCategory.id == category_id).first()
    )
    if not category:
        raise HTTPException(status_code=404, detail="Categorie niet gevonden.")

    db.query(CustomerWebsite).filter(
        CustomerWebsite.category_id == category_id
    ).update({"category_id": None})
    db.delete(category)
    db.commit()
    return {"success": True}
