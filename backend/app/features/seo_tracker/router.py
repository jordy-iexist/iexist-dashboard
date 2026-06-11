from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import require_user_id, utc_now_iso
from app.db.models import CustomerWebsite, SerpScan, SerpScanResult, WebsiteKeyword, WebsiteMetaRun
from app.db.session import get_db
from app.features.seo_tracker.mappers import (
    to_customer_website_item,
    to_serp_scan_item,
    to_website_keyword_item,
)
from app.features.seo_tracker.schemas import (
    CustomerWebsiteCreateRequest,
    CustomerWebsiteItem,
    CustomerWebsitesResponse,
    CustomerWebsiteUpdateRequest,
    SerpScanItem,
    SerpScansResponse,
    StartWebsiteScanResponse,
    WebsiteKeywordCreateRequest,
    WebsiteKeywordItem,
    WebsiteKeywordsResponse,
    WebsiteKeywordUpdateRequest,
    WebsiteRankingItem,
    WebsiteRankingsResponse,
)
from app.features.seo_tracker.services import (
    apply_scan_limit,
    build_scan_canceled_error_message,
    clamp_max_requests,
    normalize_keyword,
    normalize_website_url,
)
from app.worker.tasks import scan_website_keywords_task

router = APIRouter(tags=["seo"])


def _row_to_dict(obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}  # type: ignore[union-attr]


@router.post("/api/seo/websites", response_model=CustomerWebsiteItem)
async def create_customer_website(
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
            detail="Er bestaat al een website met dit domein.",
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


@router.get("/api/seo/websites", response_model=CustomerWebsitesResponse)
async def list_customer_websites(
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    websites = (
        db.query(CustomerWebsite)
        .order_by(CustomerWebsite.created_at.desc())
        .all()
    )
    return CustomerWebsitesResponse(
        websites=[to_customer_website_item(_row_to_dict(w)) for w in websites]
    )


@router.patch("/api/seo/websites/{website_id}", response_model=CustomerWebsiteItem)
async def update_customer_website(
    website_id: str,
    payload: CustomerWebsiteUpdateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    website = (
        db.query(CustomerWebsite)
        .filter(
            CustomerWebsite.id == website_id,
        )
        .first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Website niet gevonden.")

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
                CustomerWebsite.id != website_id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail="Er bestaat al een website met dit domein.",
            )
        updates["base_url"] = next_base_url
        updates["domain"] = next_domain

    if payload.is_active is not None:
        updates["is_active"] = payload.is_active

    if len(updates) == 1:
        raise HTTPException(status_code=400, detail="Geen wijzigingen ontvangen.")

    db.query(CustomerWebsite).filter(
        CustomerWebsite.id == website_id,
    ).update(updates)  # type: ignore
    db.commit()

    updated_website = (
        db.query(CustomerWebsite)
        .filter(
            CustomerWebsite.id == website_id,
        )
        .first()
    )
    if not updated_website:
        raise HTTPException(status_code=500, detail="Kon website niet bijwerken.")
    return to_customer_website_item(_row_to_dict(updated_website))


@router.delete("/api/seo/websites/{website_id}")
async def delete_customer_website(
    website_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    website = (
        db.query(CustomerWebsite)
        .filter(
            CustomerWebsite.id == website_id,
        )
        .first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Website niet gevonden.")

    running_scan = (
        db.query(SerpScan)
        .filter(
            SerpScan.website_id == website_id,
            SerpScan.status.in_(["pending", "processing"]),
        )
        .first()
    )
    if running_scan:
        raise HTTPException(
            status_code=409,
            detail="Er draait nog een scan voor deze website. Annuleer de scan eerst.",
        )

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
            detail="Er draait nog een meta run voor deze website.",
        )

    db.query(CustomerWebsite).filter(
        CustomerWebsite.id == website_id,
    ).delete()
    db.commit()
    return {
        "status": "deleted",
        "website_id": website_id,
    }


@router.post(
    "/api/seo/websites/{website_id}/keywords", response_model=WebsiteKeywordItem
)
async def create_website_keyword(
    website_id: str,
    payload: WebsiteKeywordCreateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    website = (
        db.query(CustomerWebsite)
        .filter(
            CustomerWebsite.id == website_id,
        )
        .first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Website niet gevonden.")

    try:
        keyword = normalize_keyword(payload.keyword)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing_keywords = (
        db.query(WebsiteKeyword)
        .filter(
            WebsiteKeyword.website_id == website_id,
        )
        .all()
    )
    for existing in existing_keywords:
        existing_keyword = str(existing.keyword or "").strip().lower()
        if existing_keyword == keyword.lower():
            raise HTTPException(
                status_code=409,
                detail="Dit keyword bestaat al voor deze website.",
            )

    keyword_id = str(uuid.uuid4())
    now = utc_now_iso()
    keyword_obj = WebsiteKeyword(
        id=keyword_id,
        website_id=website_id,
        keyword=keyword,
        is_active=True,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(keyword_obj)
    db.commit()
    db.refresh(keyword_obj)
    return to_website_keyword_item(_row_to_dict(keyword_obj))


@router.get(
    "/api/seo/websites/{website_id}/keywords", response_model=WebsiteKeywordsResponse
)
async def list_website_keywords(
    website_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    website = (
        db.query(CustomerWebsite)
        .filter(
            CustomerWebsite.id == website_id,
        )
        .first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Website niet gevonden.")

    keywords = (
        db.query(WebsiteKeyword)
        .filter(
            WebsiteKeyword.website_id == website_id,
        )
        .order_by(WebsiteKeyword.created_at.asc())
        .all()
    )
    return WebsiteKeywordsResponse(
        keywords=[to_website_keyword_item(_row_to_dict(kw)) for kw in keywords]
    )


@router.patch("/api/seo/keywords/{keyword_id}", response_model=WebsiteKeywordItem)
async def update_website_keyword(
    keyword_id: str,
    payload: WebsiteKeywordUpdateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    keyword_record = (
        db.query(WebsiteKeyword)
        .filter(
            WebsiteKeyword.id == keyword_id,
        )
        .first()
    )
    if not keyword_record:
        raise HTTPException(status_code=404, detail="Keyword niet gevonden.")

    updates: dict[str, Any] = {"updated_at": utc_now_iso()}

    if isinstance(payload.keyword, str):
        try:
            next_keyword = normalize_keyword(payload.keyword)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        existing_keywords = (
            db.query(WebsiteKeyword)
            .filter(
                WebsiteKeyword.website_id == keyword_record.website_id,
            )
            .all()
        )
        for existing in existing_keywords:
            if str(existing.id) == keyword_id:
                continue
            existing_keyword = str(existing.keyword or "").strip().lower()
            if existing_keyword == next_keyword.lower():
                raise HTTPException(
                    status_code=409,
                    detail="Dit keyword bestaat al voor deze website.",
                )
        updates["keyword"] = next_keyword

    if payload.is_active is not None:
        updates["is_active"] = payload.is_active

    if len(updates) == 1:
        raise HTTPException(status_code=400, detail="Geen wijzigingen ontvangen.")

    db.query(WebsiteKeyword).filter(
        WebsiteKeyword.id == keyword_id,
    ).update(updates)  # type: ignore
    db.commit()

    updated_keyword = (
        db.query(WebsiteKeyword)
        .filter(
            WebsiteKeyword.id == keyword_id,
        )
        .first()
    )
    if not updated_keyword:
        raise HTTPException(status_code=500, detail="Kon keyword niet bijwerken.")
    return to_website_keyword_item(_row_to_dict(updated_keyword))


@router.delete("/api/seo/keywords/{keyword_id}")
async def delete_website_keyword(
    keyword_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    keyword = (
        db.query(WebsiteKeyword)
        .filter(
            WebsiteKeyword.id == keyword_id,
        )
        .first()
    )
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword niet gevonden.")

    website_id = str(keyword.website_id or "").strip()
    if not website_id:
        raise HTTPException(status_code=500, detail="Keyword mist website_id.")

    running_scan = (
        db.query(SerpScan)
        .filter(
            SerpScan.website_id == website_id,
            SerpScan.status.in_(["pending", "processing"]),
        )
        .first()
    )
    if running_scan:
        raise HTTPException(
            status_code=409,
            detail="Er draait nog een scan voor deze website. Annuleer de scan eerst.",
        )

    db.query(WebsiteKeyword).filter(
        WebsiteKeyword.id == keyword_id,
    ).delete()
    db.commit()
    return {
        "status": "deleted",
        "keyword_id": keyword_id,
    }


@router.post(
    "/api/seo/websites/{website_id}/scan", response_model=StartWebsiteScanResponse
)
async def start_website_scan(
    website_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    if not settings.serpapi_api_key.strip():
        raise HTTPException(
            status_code=400,
            detail="SERPAPI_API_KEY ontbreekt in backend configuratie.",
        )

    website = (
        db.query(CustomerWebsite)
        .filter(
            CustomerWebsite.id == website_id,
        )
        .first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Website niet gevonden.")
    if not bool(website.is_active):
        raise HTTPException(status_code=400, detail="Website is gedeactiveerd.")

    active_keywords = (
        db.query(WebsiteKeyword)
        .filter(
            WebsiteKeyword.website_id == website_id,
            WebsiteKeyword.is_active == True,  # noqa: E712
        )
        .order_by(WebsiteKeyword.created_at.asc())
        .all()
    )
    if not active_keywords:
        raise HTTPException(
            status_code=400,
            detail="Voeg eerst minimaal één actief keyword toe.",
        )

    active_keywords_dicts = [_row_to_dict(kw) for kw in active_keywords]
    max_requests_per_scan = clamp_max_requests(settings.serpapi_max_requests_per_scan)
    _, skipped_due_to_limit, truncated_by_limit = apply_scan_limit(
        active_keywords_dicts,
        max_requests_per_scan,
    )

    scan_id = str(uuid.uuid4())
    now = utc_now_iso()
    scan = SerpScan(
        id=scan_id,
        website_id=website_id,
        status="pending",
        requested_by=user_id,
        market="google_nl_desktop",
        total_keywords=len(active_keywords),
        processed_keywords=0,
        failed_keywords=0,
        max_requests_per_scan=max_requests_per_scan,
        skipped_due_to_limit=skipped_due_to_limit,
        truncated_by_limit=truncated_by_limit,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    scan_website_keywords_task.delay(scan_id)  # type: ignore[attr-defined]
    return StartWebsiteScanResponse(
        scan_id=scan_id,
        status="pending",
        total_keywords=int(scan.total_keywords or 0),
        max_requests_per_scan=int(scan.max_requests_per_scan or 1),
        skipped_due_to_limit=int(scan.skipped_due_to_limit or 0),
        truncated_by_limit=bool(scan.truncated_by_limit),
    )


@router.get("/api/seo/scans/{scan_id}", response_model=SerpScanItem)
async def get_website_scan(
    scan_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    scan = (
        db.query(SerpScan)
        .filter(
            SerpScan.id == scan_id,
        )
        .first()
    )
    if not scan:
        raise HTTPException(status_code=404, detail="Scan niet gevonden.")
    return to_serp_scan_item(_row_to_dict(scan))


@router.post("/api/seo/scans/{scan_id}/cancel", response_model=SerpScanItem)
async def cancel_website_scan(
    scan_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    scan = (
        db.query(SerpScan)
        .filter(
            SerpScan.id == scan_id,
        )
        .first()
    )
    if not scan:
        raise HTTPException(status_code=404, detail="Scan niet gevonden.")

    current_status = str(scan.status or "pending").strip().lower()
    if current_status in {"completed", "failed", "canceled"}:
        return to_serp_scan_item(_row_to_dict(scan))

    canceled_error_message = build_scan_canceled_error_message()
    db.query(SerpScan).filter(
        SerpScan.id == scan_id,
    ).update(
        {
            "status": "canceled",
            "error_message": canceled_error_message,
            "updated_at": utc_now_iso(),
        }
    )
    db.commit()

    updated_scan = (
        db.query(SerpScan)
        .filter(
            SerpScan.id == scan_id,
        )
        .first()
    )
    if not updated_scan:
        raise HTTPException(status_code=500, detail="Kon scan niet annuleren.")
    return to_serp_scan_item(_row_to_dict(updated_scan))


@router.get("/api/seo/websites/{website_id}/scans", response_model=SerpScansResponse)
async def list_website_scans(
    website_id: str,
    limit: int = Query(default=25, ge=1, le=200),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    website = (
        db.query(CustomerWebsite)
        .filter(
            CustomerWebsite.id == website_id,
        )
        .first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Website niet gevonden.")

    scans = (
        db.query(SerpScan)
        .filter(
            SerpScan.website_id == website_id,
        )
        .order_by(SerpScan.created_at.desc())
        .limit(limit)
        .all()
    )
    return SerpScansResponse(scans=[to_serp_scan_item(_row_to_dict(s)) for s in scans])


@router.get(
    "/api/seo/websites/{website_id}/rankings", response_model=WebsiteRankingsResponse
)
async def get_website_rankings(
    website_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    website = (
        db.query(CustomerWebsite)
        .filter(
            CustomerWebsite.id == website_id,
        )
        .first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Website niet gevonden.")

    keyword_rows = (
        db.query(WebsiteKeyword)
        .filter(
            WebsiteKeyword.website_id == website_id,
        )
        .order_by(WebsiteKeyword.created_at.asc())
        .all()
    )
    keyword_dicts = [_row_to_dict(kw) for kw in keyword_rows]

    fetch_limit = min(max(len(keyword_dicts) * 10, 200), 5000)
    result_rows = (
        db.query(SerpScanResult)
        .filter(SerpScanResult.website_id == website_id)
        .order_by(SerpScanResult.created_at.desc())
        .limit(fetch_limit)
        .all()
    )
    result_dicts = [_row_to_dict(r) for r in result_rows]

    latest_two_by_keyword: dict[str, list[dict[str, Any]]] = {}
    for row in result_dicts:
        keyword_id = str(row.get("keyword_id", "") or "")
        if not keyword_id:
            continue
        bucket = latest_two_by_keyword.setdefault(keyword_id, [])
        if len(bucket) >= 2:
            continue
        bucket.append(row)

    rankings: list[WebsiteRankingItem] = []
    for keyword_row in keyword_dicts:
        keyword_id = str(keyword_row.get("id", "") or "")
        keyword = str(keyword_row.get("keyword", "") or "")
        is_active = bool(keyword_row.get("is_active", True))
        latest_rows = latest_two_by_keyword.get(keyword_id, [])
        current_row = latest_rows[0] if len(latest_rows) >= 1 else None
        previous_row = latest_rows[1] if len(latest_rows) >= 2 else None

        current_position: int | None = None
        if current_row and current_row.get("position") is not None:
            try:
                parsed_current_position = int(current_row["position"])
                if parsed_current_position > 0:
                    current_position = parsed_current_position
            except (TypeError, ValueError):
                current_position = None

        previous_position: int | None = None
        if previous_row and previous_row.get("position") is not None:
            try:
                parsed_previous_position = int(previous_row["position"])
                if parsed_previous_position > 0:
                    previous_position = parsed_previous_position
            except (TypeError, ValueError):
                previous_position = None

        delta: int | None = None
        if current_position is not None and previous_position is not None:
            delta = previous_position - current_position

        rankings.append(
            WebsiteRankingItem(
                keyword_id=keyword_id,
                keyword=keyword,
                is_active=is_active,
                current_position=current_position,
                previous_position=previous_position,
                delta=delta,
                current_result_url=(
                    str(current_row["result_url"])
                    if current_row and current_row.get("result_url") not in {None, ""}
                    else None
                ),
                current_matched_host=(
                    str(current_row["matched_host"])
                    if current_row and current_row.get("matched_host") not in {None, ""}
                    else None
                ),
                last_scanned_at=(
                    current_row.get("created_at")
                    if current_row and current_row.get("created_at") is not None
                    else None
                ),
                latest_scan_id=(
                    str(current_row["scan_id"])
                    if current_row and current_row.get("scan_id") not in {None, ""}
                    else None
                ),
            )
        )

    rankings.sort(key=lambda row: (not row.is_active, row.keyword.lower()))
    return WebsiteRankingsResponse(
        website_id=website_id,
        rankings=rankings,
    )
