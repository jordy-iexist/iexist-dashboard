from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import require_user_id, utc_now_iso
from app.db.models import CustomerWebsite, WebsiteMetaPage, WebsiteMetaRun
from app.db.session import get_db
from app.features.seo_meta.mappers import to_meta_page_item, to_meta_run_item
from app.features.seo_meta.schemas import (
    MetaPageItem,
    MetaPageUpdateRequest,
    MetaRunCreateRequest,
    MetaRunItem,
    MetaRunPagesResponse,
    StartMetaRunResponse,
    WebsiteMetaLatestResponse,
)
from app.features.seo_meta.services import clamp_meta_page_limit, normalize_path_filters
from app.features.settings.services import (
    MissingUserOpenAIKeyError,
    resolve_openai_api_key,
)
from app.worker.tasks import run_website_meta_optimization_task

router = APIRouter(tags=["seo"])


def _row_to_dict(obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}  # type: ignore[union-attr]


@router.post(
    "/api/seo/websites/{website_id}/meta-runs",
    response_model=StartMetaRunResponse,
)
async def start_website_meta_run(
    website_id: str,
    payload: MetaRunCreateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    website = (
        db.query(CustomerWebsite)
        .filter(
            CustomerWebsite.id == website_id,
            CustomerWebsite.created_by == user_id,
        )
        .first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Website niet gevonden.")
    if not bool(website.is_active):
        raise HTTPException(status_code=400, detail="Website is gedeactiveerd.")
    try:
        resolve_openai_api_key(user_id, db)
    except MissingUserOpenAIKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    running_meta = (
        db.query(WebsiteMetaRun)
        .filter(
            WebsiteMetaRun.website_id == website_id,
            WebsiteMetaRun.status.in_(["pending", "processing"]),
        )
        .first()
    )
    if running_meta:
        raise HTTPException(
            status_code=409,
            detail="Er draait al een meta run voor deze website.",
        )

    max_pages = clamp_meta_page_limit(
        payload.page_limit,
        settings.seo_meta_max_pages_per_run,
    )
    include_paths = normalize_path_filters(payload.include_paths)
    exclude_paths = normalize_path_filters(payload.exclude_paths)

    run_id = str(uuid.uuid4())
    now = utc_now_iso()
    meta_run = WebsiteMetaRun(
        id=run_id,
        website_id=website_id,
        status="pending",
        requested_by=user_id,
        source="sitemap_first",
        total_pages=0,
        processed_pages=0,
        failed_pages=0,
        max_pages_per_run=max_pages,
        skipped_due_to_limit=0,
        include_paths=include_paths,
        exclude_paths=exclude_paths,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    db.add(meta_run)
    db.commit()
    db.refresh(meta_run)

    run_website_meta_optimization_task.delay(run_id)  # type: ignore[attr-defined]
    return StartMetaRunResponse(
        run_id=run_id,
        status="pending",
        total_pages=0,
        max_pages_per_run=int(meta_run.max_pages_per_run or max_pages),
        skipped_due_to_limit=0,
    )


@router.get("/api/seo/meta-runs/{run_id}", response_model=MetaRunItem)
async def get_meta_run(
    run_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    run = (
        db.query(WebsiteMetaRun)
        .filter(
            WebsiteMetaRun.id == run_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Meta run niet gevonden.")
    return to_meta_run_item(_row_to_dict(run))


@router.get("/api/seo/meta-runs/{run_id}/pages", response_model=MetaRunPagesResponse)
async def list_meta_run_pages(
    run_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    review_status: str | None = Query(default=None),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    run = (
        db.query(WebsiteMetaRun)
        .filter(
            WebsiteMetaRun.id == run_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Meta run niet gevonden.")

    normalized_review_status = str(review_status or "").strip().lower() or None
    if normalized_review_status and normalized_review_status not in {
        "pending_review",
        "approved",
        "rejected",
    }:
        raise HTTPException(status_code=400, detail="Ongeldige review_status filter.")

    pages_query = (
        db.query(WebsiteMetaPage)
        .filter(WebsiteMetaPage.run_id == run_id)
        .order_by(WebsiteMetaPage.path.asc(), WebsiteMetaPage.created_at.asc())
    )
    total_query = db.query(WebsiteMetaPage).filter(WebsiteMetaPage.run_id == run_id)

    if normalized_review_status:
        pages_query = pages_query.filter(
            WebsiteMetaPage.review_status == normalized_review_status
        )
        total_query = total_query.filter(
            WebsiteMetaPage.review_status == normalized_review_status
        )

    pages = pages_query.offset(offset).limit(limit).all()
    total = total_query.count()

    return MetaRunPagesResponse(
        pages=[to_meta_page_item(_row_to_dict(p)) for p in pages],
        total=total,
    )


@router.get(
    "/api/seo/websites/{website_id}/meta-latest",
    response_model=WebsiteMetaLatestResponse,
)
async def get_website_meta_latest(
    website_id: str,
    pages_limit: int = Query(default=200, ge=1, le=500),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    website = (
        db.query(CustomerWebsite)
        .filter(
            CustomerWebsite.id == website_id,
            CustomerWebsite.created_by == user_id,
        )
        .first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Website niet gevonden.")

    latest_run = (
        db.query(WebsiteMetaRun)
        .filter(
            WebsiteMetaRun.website_id == website_id,
        )
        .order_by(WebsiteMetaRun.created_at.desc())
        .first()
    )
    if not latest_run:
        return WebsiteMetaLatestResponse(run=None, pages=[])

    run_id = str(latest_run.id)
    pages = (
        db.query(WebsiteMetaPage)
        .filter(WebsiteMetaPage.run_id == run_id)
        .order_by(WebsiteMetaPage.path.asc(), WebsiteMetaPage.created_at.asc())
        .limit(pages_limit)
        .all()
    )
    return WebsiteMetaLatestResponse(
        run=to_meta_run_item(_row_to_dict(latest_run)),
        pages=[to_meta_page_item(_row_to_dict(p)) for p in pages],
    )


@router.patch("/api/seo/meta-pages/{page_id}", response_model=MetaPageItem)
async def update_meta_page(
    page_id: str,
    payload: MetaPageUpdateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    page = db.query(WebsiteMetaPage).filter(WebsiteMetaPage.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Meta pagina niet gevonden.")

    run_owner = (
        db.query(WebsiteMetaRun)
        .filter(
            WebsiteMetaRun.id == page.run_id,
        )
        .first()
    )
    if not run_owner:
        raise HTTPException(status_code=404, detail="Meta pagina niet gevonden.")

    page_dict = _row_to_dict(page)
    now = utc_now_iso()
    updates: dict[str, Any] = {"updated_at": now}

    current_review_status = str(page_dict.get("review_status") or "pending_review")
    next_review_status = payload.review_status or current_review_status
    if next_review_status not in {"pending_review", "approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Ongeldige review_status.")

    approved_title_input = (
        payload.approved_title.strip()
        if isinstance(payload.approved_title, str)
        else None
    )
    approved_description_input = (
        payload.approved_description.strip()
        if isinstance(payload.approved_description, str)
        else None
    )

    if next_review_status == "approved":
        next_title = (
            approved_title_input
            if approved_title_input is not None
            else str(page_dict.get("approved_title") or "").strip()
            or str(page_dict.get("suggested_title") or "").strip()
        )
        next_description = (
            approved_description_input
            if approved_description_input is not None
            else str(page_dict.get("approved_description") or "").strip()
            or str(page_dict.get("suggested_description") or "").strip()
        )

        if not next_title:
            raise HTTPException(status_code=400, detail="Approved title is verplicht.")
        if not next_description:
            raise HTTPException(
                status_code=400,
                detail="Approved description is verplicht.",
            )
        if len(next_title) > settings.seo_meta_title_max_chars:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Approved title is te lang "
                    f"(max {settings.seo_meta_title_max_chars} tekens)."
                ),
            )
        if len(next_description) > settings.seo_meta_description_max_chars:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Approved description is te lang "
                    f"(max {settings.seo_meta_description_max_chars} tekens)."
                ),
            )

        updates.update(
            {
                "review_status": "approved",
                "approved_title": next_title,
                "approved_description": next_description,
                "reviewed_by": user_id,
                "reviewed_at": now,
            }
        )
    elif next_review_status == "rejected":
        updates.update(
            {
                "review_status": "rejected",
                "reviewed_by": user_id,
                "reviewed_at": now,
            }
        )
    else:
        updates.update(
            {
                "review_status": "pending_review",
                "reviewed_by": None,
                "reviewed_at": None,
            }
        )
        if approved_title_input is not None:
            updates["approved_title"] = approved_title_input or None
        if approved_description_input is not None:
            updates["approved_description"] = approved_description_input or None

    if len(updates) == 1:
        raise HTTPException(status_code=400, detail="Geen wijzigingen ontvangen.")

    db.query(WebsiteMetaPage).filter(WebsiteMetaPage.id == page_id).update(updates)  # type: ignore
    db.commit()

    updated_page = (
        db.query(WebsiteMetaPage).filter(WebsiteMetaPage.id == page_id).first()
    )
    if not updated_page:
        raise HTTPException(status_code=500, detail="Kon meta pagina niet bijwerken.")
    return to_meta_page_item(_row_to_dict(updated_page))
