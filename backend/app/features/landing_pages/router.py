import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.core.dependencies import require_user_id, utc_now_iso
from app.db.models import (
    CustomerWebsite,
    Job,
    LandingPage,
    LandingPageGenerationSettings,
    LandingPageRow,
    LandingPageUpload,
)
from app.db.session import get_db
from app.features.landing_pages.mappers import extract_landing_page_context
from app.features.blogs.dependencies import dedupe_ids
from app.features.customers.services import (
    CUSTOMER_WEBSITE_META_FIELD,
    build_customer_domain_index,
    match_customer_id_by_website,
    resolve_customer_website_id,
)
from app.features.landing_pages.schemas import (
    DeleteBatchRequest,
    DeleteBatchResponse,
    LandingPageDetailResponse,
    LandingPageGenerationSettingsResponse,
    LandingPageGenerationSettingsUpdateRequest,
    LandingPageListItem,
    LandingPageListResponse,
    LandingPageManualUploadRequest,
    LandingPageRecentUploadItem,
    LandingPageRecentUploadsResponse,
    LandingPageUpdateRequest,
    LandingPageUploadResponse,
    LandingPageUploadStatusResponse,
)
from app.features.landing_pages.services.generation.csv import (
    build_landing_page_prompt,
    extract_template_placeholders,
    get_missing_prompt_values,
    map_row_to_landing_page_fields,
    normalize_landing_page_prompt_template,
    parse_csv,
    validate_landing_page_mapping,
)
from app.features.landing_pages.services.generation.openai import (
    DEFAULT_LANDING_PAGE_MAX_OUTPUT_TOKENS,
    DEFAULT_LANDING_PAGE_REASONING_EFFORT,
    SYSTEM_PROMPT as DEFAULT_SYSTEM_PROMPT,
)
from app.features.settings.services import (
    MissingUserOpenAIKeyError,
    require_personal_openai_api_key,
)
from app.worker.tasks import generate_landing_page_task

router = APIRouter(tags=["landing-pages"])


def _customer_names(db: Session, customer_ids: list[str | None]) -> dict[str, str]:
    ids = [str(cid) for cid in customer_ids if cid]
    if not ids:
        return {}
    rows = (
        db.query(CustomerWebsite.id, CustomerWebsite.name)
        .filter(CustomerWebsite.id.in_(ids))
        .all()
    )
    return {str(cid): str(name) for cid, name in rows}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@router.post("/api/landing-pages/upload", response_model=LandingPageUploadResponse)
async def upload_landing_page_csv(
    file: UploadFile = File(...),
    mapping: str = Form(...),
    template: str = Form(""),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Upload a CSV with column mapping and queue landing page generation jobs."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Bestand moet een CSV zijn.")

    try:
        require_personal_openai_api_key(user_id, db)
    except MissingUserOpenAIKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        mapping_payload = json.loads(mapping)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Ongeldige kolom-mapping.") from exc

    if not isinstance(mapping_payload, dict):
        raise HTTPException(status_code=400, detail="Ongeldige kolom-mapping.")

    prompt_template = normalize_landing_page_prompt_template(template)
    try:
        required_fields = extract_template_placeholders(prompt_template)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content = await file.read()
    try:
        headers, rows = parse_csv(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        normalized_mapping = validate_landing_page_mapping(
            mapping_payload, headers, required_fields
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    customer_domain_index = build_customer_domain_index(db)
    valid_rows: list[dict[str, Any]] = []
    skipped_count = 0

    for row in rows:
        row_dict = map_row_to_landing_page_fields(
            row, normalized_mapping, required_fields
        )

        if get_missing_prompt_values(row_dict, required_fields):
            skipped_count += 1
            continue

        try:
            build_landing_page_prompt(row_dict, prompt_template)
        except ValueError:
            skipped_count += 1
            continue

        matched_customer_id = match_customer_id_by_website(
            customer_domain_index, row_dict.get("website")
        )
        if matched_customer_id:
            row_dict[CUSTOMER_WEBSITE_META_FIELD] = matched_customer_id

        valid_rows.append(row_dict)

    if not valid_rows:
        raise HTTPException(
            status_code=400,
            detail="Geen verwerkbare rijen gevonden. Controleer of alle verplichte kolommen zijn ingevuld.",
        )

    upload_id = str(uuid.uuid4())
    upload = LandingPageUpload(
        id=upload_id,
        filename=str(file.filename),
        template=prompt_template,
        skipped_rows=skipped_count,
        created_by=user_id,
    )
    db.add(upload)
    db.commit()

    jobs_queued = 0
    for row_dict in valid_rows:
        row_id = str(uuid.uuid4())
        lp_row = LandingPageRow(id=row_id, upload_id=upload_id, data=row_dict)
        db.add(lp_row)

        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            job_type="landing_page_generation",
            landing_page_row_id=row_id,
            status="pending",
            created_by=user_id,
        )
        db.add(job)
        db.commit()

        generate_landing_page_task.delay(job_id)  # type: ignore[attr-defined]
        jobs_queued += 1

    return LandingPageUploadResponse(
        upload_id=upload_id,
        rows_count=len(valid_rows),
        jobs_queued=jobs_queued,
        skipped_rows=skipped_count,
        status="processing",
    )


@router.post("/api/landing-pages/manual", response_model=LandingPageUploadResponse)
async def manual_landing_page_upload(
    payload: LandingPageManualUploadRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Accept pre-filled rows (no CSV file) and queue landing page generation jobs."""
    try:
        require_personal_openai_api_key(user_id, db)
    except MissingUserOpenAIKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not payload.rows:
        raise HTTPException(status_code=400, detail="Voeg minimaal één rij toe.")

    prompt_template = normalize_landing_page_prompt_template(payload.template)
    try:
        required_fields = extract_template_placeholders(prompt_template)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    customer_domain_index = build_customer_domain_index(db)
    valid_rows: list[dict[str, Any]] = []
    skipped_count = 0

    for raw_row in payload.rows:
        row_dict: dict[str, Any] = {
            field: str(raw_row.get(field, "") or "").strip()
            for field in required_fields
        }

        if get_missing_prompt_values(row_dict, required_fields):
            skipped_count += 1
            continue

        try:
            build_landing_page_prompt(row_dict, prompt_template)
        except ValueError:
            skipped_count += 1
            continue

        customer_id = resolve_customer_website_id(
            db, raw_row.get(CUSTOMER_WEBSITE_META_FIELD)
        ) or match_customer_id_by_website(
            customer_domain_index, row_dict.get("website")
        )
        if customer_id:
            row_dict[CUSTOMER_WEBSITE_META_FIELD] = customer_id

        valid_rows.append(row_dict)

    if not valid_rows:
        raise HTTPException(
            status_code=400,
            detail="Geen verwerkbare rijen gevonden. Controleer of alle verplichte velden zijn ingevuld.",
        )

    upload_id = str(uuid.uuid4())
    upload = LandingPageUpload(
        id=upload_id,
        filename="Handmatige invoer",
        template=prompt_template,
        skipped_rows=skipped_count,
        created_by=user_id,
    )
    db.add(upload)
    db.commit()

    jobs_queued = 0
    for row_dict in valid_rows:
        row_id = str(uuid.uuid4())
        lp_row = LandingPageRow(id=row_id, upload_id=upload_id, data=row_dict)
        db.add(lp_row)

        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            job_type="landing_page_generation",
            landing_page_row_id=row_id,
            status="pending",
            created_by=user_id,
        )
        db.add(job)
        db.commit()

        generate_landing_page_task.delay(job_id)  # type: ignore[attr-defined]
        jobs_queued += 1

    return LandingPageUploadResponse(
        upload_id=upload_id,
        rows_count=len(valid_rows),
        jobs_queued=jobs_queued,
        skipped_rows=skipped_count,
        status="processing",
    )


# ---------------------------------------------------------------------------
# Uploads list
# ---------------------------------------------------------------------------

@router.get("/api/landing-pages/uploads", response_model=LandingPageRecentUploadsResponse)
async def list_recent_landing_page_uploads(
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """List the 10 most recent non-dismissed landing page uploads for the current user."""
    uploads: list[LandingPageUpload] = (
        db.query(LandingPageUpload)
        .filter(
            LandingPageUpload.created_by == user_id,
            LandingPageUpload.dismissed_at.is_(None),
        )
        .order_by(LandingPageUpload.created_at.desc())
        .limit(10)
        .all()  # type: ignore[assignment]
    )

    if not uploads:
        return LandingPageRecentUploadsResponse(uploads=[])

    upload_ids = [u.id for u in uploads]

    job_rows = (
        db.query(Job.status, LandingPageRow.upload_id)
        .join(LandingPageRow, Job.landing_page_row_id == LandingPageRow.id)
        .filter(LandingPageRow.upload_id.in_(upload_ids))
        .all()
    )

    counts: dict[str, dict[str, int]] = {
        uid: {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "canceled": 0}
        for uid in upload_ids
    }
    for job_status, upload_id in job_rows:
        bucket = str(job_status or "").strip()
        if bucket in counts[upload_id]:
            counts[upload_id][bucket] += 1

    items: list[LandingPageRecentUploadItem] = []
    for upload in uploads:
        c = counts[upload.id]
        total = sum(c.values())
        processed = c["completed"] + c["failed"] + c["canceled"]
        is_done = processed >= total
        final_status: Any = (
            "canceled"
            if is_done and c["canceled"] > 0 and c["failed"] == 0
            else "completed_with_errors"
            if is_done and c["failed"] > 0
            else "completed"
            if is_done
            else "processing"
        )
        items.append(
            LandingPageRecentUploadItem(
                upload_id=upload.id,
                filename=upload.filename,
                created_at=upload.created_at,
                total_jobs=total,
                completed=c["completed"],
                failed=c["failed"],
                canceled=c["canceled"],
                processed=processed,
                is_done=is_done,
                final_status=final_status,
            )
        )

    return LandingPageRecentUploadsResponse(uploads=items)


# ---------------------------------------------------------------------------
# Upload status
# ---------------------------------------------------------------------------

@router.get(
    "/api/landing-pages/uploads/{upload_id}/status",
    response_model=LandingPageUploadStatusResponse,
)
async def get_landing_page_upload_status(
    upload_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    upload: LandingPageUpload | None = (
        db.query(LandingPageUpload)
        .filter(
            LandingPageUpload.id == upload_id,
            LandingPageUpload.created_by == user_id,
        )
        .first()  # type: ignore[assignment]
    )
    if not upload:
        raise HTTPException(status_code=404, detail="Upload niet gevonden.")

    jobs: list[Job] = (
        db.query(Job)
        .join(LandingPageRow, Job.landing_page_row_id == LandingPageRow.id)
        .filter(LandingPageRow.upload_id == upload_id)
        .all()  # type: ignore[assignment]
    )

    status_counts: dict[str, int] = {
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "canceled": 0,
    }
    for job in jobs:
        raw = str(job.status or "").strip()
        if raw in status_counts:
            status_counts[raw] += 1

    total = len(jobs)
    completed = status_counts["completed"]
    failed = status_counts["failed"]
    processing = status_counts["processing"]
    pending = status_counts["pending"]
    canceled = status_counts["canceled"]
    processed = completed + failed + canceled
    remaining = max(total - processed, 0)
    is_done = processed >= total
    final_status: Any = (
        "canceled"
        if is_done and canceled > 0 and failed == 0
        else "completed_with_errors"
        if is_done and failed > 0
        else "completed"
        if is_done
        else "processing"
    )
    skipped_rows_count = (
        upload.skipped_rows if isinstance(upload.skipped_rows, int) else 0
    )

    return LandingPageUploadStatusResponse(
        upload_id=upload_id,
        filename=upload.filename,
        total_jobs=total,
        completed=completed,
        failed=failed,
        processing=processing,
        pending=pending,
        canceled=canceled,
        processed=processed,
        remaining=remaining,
        skipped_rows=skipped_rows_count,
        is_done=is_done,
        final_status=final_status,
    )


# ---------------------------------------------------------------------------
# Dismiss upload
# ---------------------------------------------------------------------------

@router.post(
    "/api/landing-pages/uploads/{upload_id}/dismiss",
    status_code=204,
)
async def dismiss_landing_page_upload(
    upload_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
) -> Response:
    upload: LandingPageUpload | None = (
        db.query(LandingPageUpload)
        .filter(
            LandingPageUpload.id == upload_id,
            LandingPageUpload.created_by == user_id,
        )
        .first()
    )
    if not upload:
        raise HTTPException(status_code=404, detail="Upload niet gevonden.")

    upload.dismissed_at = utc_now_iso()
    db.commit()
    return Response(status_code=204)


@router.post("/api/landing-pages/uploads/{upload_id}/cancel")
async def cancel_landing_page_upload(
    upload_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    upload: LandingPageUpload | None = (
        db.query(LandingPageUpload)
        .filter(LandingPageUpload.id == upload_id, LandingPageUpload.created_by == user_id)
        .first()
    )
    if not upload:
        raise HTTPException(status_code=404, detail="Upload niet gevonden.")

    all_jobs: list[Job] = (
        db.query(Job)
        .join(LandingPageRow, Job.landing_page_row_id == LandingPageRow.id)
        .filter(LandingPageRow.upload_id == upload_id)
        .all()  # type: ignore[assignment]
    )

    active_count = sum(
        1 for j in all_jobs if str(j.status or "").strip() in {"pending", "processing"}
    )
    if active_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Er zijn geen actieve jobs om te annuleren.",
        )

    (
        db.query(Job)
        .filter(
            Job.landing_page_row_id.in_(
                db.query(LandingPageRow.id).filter(LandingPageRow.upload_id == upload_id)
            ),
            Job.status.in_(["pending", "processing"]),
        )
        .update({"status": "canceled"}, synchronize_session="fetch")
    )
    db.commit()

    return {"ok": True, "upload_id": upload_id}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.get("/api/landing-pages/settings", response_model=LandingPageGenerationSettingsResponse)
async def get_landing_page_generation_settings(
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    user_settings: LandingPageGenerationSettings | None = (
        db.query(LandingPageGenerationSettings)
        .filter(LandingPageGenerationSettings.user_id == user_id)
        .first()  # type: ignore[assignment]
    )
    return LandingPageGenerationSettingsResponse(
        system_prompt=user_settings.system_prompt if user_settings else None,
        reasoning_effort=user_settings.reasoning_effort if user_settings else None,
        model=user_settings.model if user_settings else None,
        max_output_tokens=user_settings.max_output_tokens if user_settings else None,
        effective_system_prompt=(
            user_settings.system_prompt
            if user_settings and user_settings.system_prompt
            else DEFAULT_SYSTEM_PROMPT.strip()
        ),
        effective_reasoning_effort=(
            user_settings.reasoning_effort
            if user_settings and user_settings.reasoning_effort
            else DEFAULT_LANDING_PAGE_REASONING_EFFORT
        ),
        effective_model=(
            user_settings.model
            if user_settings and user_settings.model
            else app_settings.openai_blog_model
        ),
        effective_max_output_tokens=(
            user_settings.max_output_tokens
            if user_settings and user_settings.max_output_tokens is not None
            else DEFAULT_LANDING_PAGE_MAX_OUTPUT_TOKENS
        ),
    )


@router.put("/api/landing-pages/settings", response_model=LandingPageGenerationSettingsResponse)
async def update_landing_page_generation_settings(
    payload: LandingPageGenerationSettingsUpdateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    user_settings: LandingPageGenerationSettings | None = (
        db.query(LandingPageGenerationSettings)
        .filter(LandingPageGenerationSettings.user_id == user_id)
        .first()  # type: ignore[assignment]
    )
    now = utc_now_iso()
    if user_settings:
        user_settings.system_prompt = payload.system_prompt
        user_settings.reasoning_effort = payload.reasoning_effort
        user_settings.model = payload.model
        user_settings.max_output_tokens = payload.max_output_tokens
        user_settings.updated_at = now
    else:
        user_settings = LandingPageGenerationSettings(
            id=str(uuid.uuid4()),
            user_id=user_id,
            system_prompt=payload.system_prompt,
            reasoning_effort=payload.reasoning_effort,
            model=payload.model,
            max_output_tokens=payload.max_output_tokens,
            updated_at=now,
        )
        db.add(user_settings)
    db.commit()
    db.refresh(user_settings)

    return LandingPageGenerationSettingsResponse(
        system_prompt=user_settings.system_prompt,
        reasoning_effort=user_settings.reasoning_effort,
        model=user_settings.model,
        max_output_tokens=user_settings.max_output_tokens,
        effective_system_prompt=(
            user_settings.system_prompt
            if user_settings.system_prompt
            else DEFAULT_SYSTEM_PROMPT.strip()
        ),
        effective_reasoning_effort=(
            user_settings.reasoning_effort
            if user_settings.reasoning_effort
            else DEFAULT_LANDING_PAGE_REASONING_EFFORT
        ),
        effective_model=(
            user_settings.model
            if user_settings.model
            else app_settings.openai_blog_model
        ),
        effective_max_output_tokens=(
            user_settings.max_output_tokens
            if user_settings.max_output_tokens is not None
            else DEFAULT_LANDING_PAGE_MAX_OUTPUT_TOKENS
        ),
    )


# ---------------------------------------------------------------------------
# Landing page list
# ---------------------------------------------------------------------------

@router.get("/api/landing-pages", response_model=LandingPageListResponse)
async def list_landing_pages(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=100),
    scope: str = Query(default="all", pattern="^(mine|shared|all)$"),
    customer_website_id: str | None = Query(default=None),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    start = (page - 1) * page_size
    if scope == "mine":
        visibility = LandingPage.created_by == user_id
    elif scope == "shared":
        visibility = (LandingPage.is_public.is_(True)) & (
            LandingPage.created_by != user_id
        )
    else:
        visibility = or_(
            LandingPage.created_by == user_id, LandingPage.is_public.is_(True)
        )

    customer_filter = str(customer_website_id or "").strip()
    base_query = db.query(LandingPage).filter(visibility)
    if customer_filter == "none":
        base_query = base_query.filter(LandingPage.customer_website_id.is_(None))
    elif customer_filter:
        base_query = base_query.filter(
            LandingPage.customer_website_id == customer_filter
        )

    total: int = base_query.count()
    lp_rows: list[LandingPage] = (
        base_query
        .order_by(LandingPage.created_at.desc())
        .offset(start)
        .limit(page_size)
        .all()  # type: ignore[assignment]
    )
    customer_name_map = _customer_names(
        db, [lp.customer_website_id for lp in lp_rows]
    )

    items: list[LandingPageListItem] = []
    for lp in lp_rows:
        job: Job | None = (
            db.query(Job).filter(Job.id == lp.job_id).first()  # type: ignore[assignment]
            if lp.job_id
            else None
        )
        lp_row: LandingPageRow | None = (
            db.query(LandingPageRow)
            .filter(LandingPageRow.id == job.landing_page_row_id)
            .first()  # type: ignore[assignment]
            if job and job.landing_page_row_id
            else None
        )
        upload: LandingPageUpload | None = (
            db.query(LandingPageUpload)
            .filter(LandingPageUpload.id == lp_row.upload_id)
            .first()  # type: ignore[assignment]
            if lp_row
            else None
        )
        row_data = lp_row.data if lp_row else None
        onderwerp, filename, status = extract_landing_page_context(
            row_data if isinstance(row_data, dict) else None,
            upload.filename if upload else None,
            job.status if job else None,
        )
        items.append(
            LandingPageListItem(
                id=str(lp.id),
                meta_title=lp.meta_title,
                onderwerp=onderwerp,
                filename=filename,
                status=status,
                created_at=lp.created_at,
                is_public=bool(lp.is_public),
                is_owner=str(lp.created_by or "") == user_id,
                customer_website_id=lp.customer_website_id,
                customer_name=customer_name_map.get(
                    str(lp.customer_website_id or "")
                ),
            )
        )

    return LandingPageListResponse(
        landing_pages=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Landing page detail
# ---------------------------------------------------------------------------

@router.get("/api/landing-pages/{landing_page_id}", response_model=LandingPageDetailResponse)
async def get_landing_page(
    landing_page_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    lp: LandingPage | None = (
        db.query(LandingPage)
        .filter(
            LandingPage.id == landing_page_id,
            or_(
                LandingPage.created_by == user_id,
                LandingPage.is_public.is_(True),
            ),
        )
        .first()  # type: ignore[assignment]
    )
    if not lp:
        raise HTTPException(status_code=404, detail="Landingspagina niet gevonden.")

    job: Job | None = (
        db.query(Job).filter(Job.id == lp.job_id).first()  # type: ignore[assignment]
        if lp.job_id
        else None
    )
    lp_row: LandingPageRow | None = (
        db.query(LandingPageRow)
        .filter(LandingPageRow.id == job.landing_page_row_id)
        .first()  # type: ignore[assignment]
        if job and job.landing_page_row_id
        else None
    )
    upload: LandingPageUpload | None = (
        db.query(LandingPageUpload)
        .filter(LandingPageUpload.id == lp_row.upload_id)
        .first()  # type: ignore[assignment]
        if lp_row
        else None
    )
    row_data = lp_row.data if lp_row else None
    onderwerp, filename, status = extract_landing_page_context(
        row_data if isinstance(row_data, dict) else None,
        upload.filename if upload else None,
        job.status if job else None,
    )
    return LandingPageDetailResponse(
        id=str(lp.id),
        content=lp.content,
        meta_title=lp.meta_title,
        meta_description=lp.meta_description,
        slug=lp.slug,
        share_token=str(lp.share_token),
        status=status,
        onderwerp=onderwerp,
        filename=filename,
        created_at=lp.created_at,
        is_public=bool(lp.is_public),
        is_owner=str(lp.created_by or "") == user_id,
        customer_website_id=lp.customer_website_id,
        customer_name=_customer_names(db, [lp.customer_website_id]).get(
            str(lp.customer_website_id or "")
        ),
    )


# ---------------------------------------------------------------------------
# Landing page update
# ---------------------------------------------------------------------------

@router.patch("/api/landing-pages/{landing_page_id}", response_model=LandingPageDetailResponse)
async def update_landing_page(
    landing_page_id: str,
    payload: LandingPageUpdateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    if (
        all(
            v is None
            for v in (
                payload.content,
                payload.meta_title,
                payload.meta_description,
                payload.slug,
                payload.is_public,
            )
        )
        and "customer_website_id" not in payload.model_fields_set
    ):
        raise HTTPException(
            status_code=400,
            detail="Minimaal één veld moet worden meegegeven.",
        )

    lp: LandingPage | None = (
        db.query(LandingPage)
        .filter(LandingPage.id == landing_page_id, LandingPage.created_by == user_id)
        .first()  # type: ignore[assignment]
    )
    if not lp:
        raise HTTPException(status_code=404, detail="Landingspagina niet gevonden.")

    updates: dict[str, Any] = {}
    if payload.content is not None:
        stripped_content = payload.content.strip()
        if not stripped_content:
            raise HTTPException(status_code=400, detail="Inhoud mag niet leeg zijn.")
        updates["content"] = stripped_content
    if payload.meta_title is not None:
        updates["meta_title"] = payload.meta_title
    if payload.meta_description is not None:
        updates["meta_description"] = payload.meta_description
    if payload.slug is not None:
        updates["slug"] = payload.slug
    if payload.is_public is not None:
        updates["is_public"] = bool(payload.is_public)
    # null betekent hier expliciet ontkoppelen, dus afwezig vs. null onderscheiden.
    if "customer_website_id" in payload.model_fields_set:
        if payload.customer_website_id:
            resolved = resolve_customer_website_id(db, payload.customer_website_id)
            if not resolved:
                raise HTTPException(status_code=400, detail="Klant niet gevonden.")
            updates["customer_website_id"] = resolved
        else:
            updates["customer_website_id"] = None

    db.query(LandingPage).filter(
        LandingPage.id == landing_page_id, LandingPage.created_by == user_id
    ).update(updates)
    db.commit()

    # Re-fetch for response
    lp = (
        db.query(LandingPage)
        .filter(LandingPage.id == landing_page_id, LandingPage.created_by == user_id)
        .first()  # type: ignore[assignment]
    )
    if not lp:
        raise HTTPException(status_code=500, detail="Kon landingspagina niet opslaan.")

    job: Job | None = (
        db.query(Job).filter(Job.id == lp.job_id).first()  # type: ignore[assignment]
        if lp.job_id
        else None
    )
    lp_row: LandingPageRow | None = (
        db.query(LandingPageRow)
        .filter(LandingPageRow.id == job.landing_page_row_id)
        .first()  # type: ignore[assignment]
        if job and job.landing_page_row_id
        else None
    )
    upload: LandingPageUpload | None = (
        db.query(LandingPageUpload)
        .filter(LandingPageUpload.id == lp_row.upload_id)
        .first()  # type: ignore[assignment]
        if lp_row
        else None
    )
    row_data = lp_row.data if lp_row else None
    onderwerp, filename, status = extract_landing_page_context(
        row_data if isinstance(row_data, dict) else None,
        upload.filename if upload else None,
        job.status if job else None,
    )
    return LandingPageDetailResponse(
        id=str(lp.id),
        content=lp.content,
        meta_title=lp.meta_title,
        meta_description=lp.meta_description,
        slug=lp.slug,
        share_token=str(lp.share_token),
        status=status,
        onderwerp=onderwerp,
        filename=filename,
        created_at=lp.created_at,
        is_public=bool(lp.is_public),
        is_owner=True,
        customer_website_id=lp.customer_website_id,
        customer_name=_customer_names(db, [lp.customer_website_id]).get(
            str(lp.customer_website_id or "")
        ),
    )


# ---------------------------------------------------------------------------
# Landing page batch delete
# ---------------------------------------------------------------------------

@router.post("/api/landing-pages/delete/batch", response_model=DeleteBatchResponse)
async def delete_landing_pages_batch(
    payload: DeleteBatchRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
) -> DeleteBatchResponse:
    landing_page_ids = dedupe_ids(payload.landing_page_ids)
    if not landing_page_ids:
        raise HTTPException(status_code=400, detail="Minimaal één landingspagina is verplicht.")

    owned_rows = (
        db.query(LandingPage.id, LandingPage.job_id)
        .filter(LandingPage.id.in_(landing_page_ids), LandingPage.created_by == user_id)
        .all()
    )
    owned_ids = [str(row.id) for row in owned_rows]
    owned_job_ids = [str(row.job_id) for row in owned_rows if row.job_id]
    missing = [lp_id for lp_id in landing_page_ids if lp_id not in owned_ids]

    if owned_ids:
        related_row_ids: list[str] = []
        if owned_job_ids:
            related_row_ids = [
                str(row.landing_page_row_id)
                for row in db.query(Job.landing_page_row_id)
                    .filter(Job.id.in_(owned_job_ids))
                    .all()
                if row.landing_page_row_id
            ]

        db.query(LandingPage).filter(LandingPage.id.in_(owned_ids)).delete(synchronize_session=False)
        if owned_job_ids:
            db.query(Job).filter(Job.id.in_(owned_job_ids)).delete(synchronize_session=False)
        if related_row_ids:
            db.query(LandingPageRow).filter(LandingPageRow.id.in_(related_row_ids)).delete(synchronize_session=False)
        db.commit()

    return DeleteBatchResponse(requested=len(landing_page_ids), deleted=len(owned_ids), missing=missing)


# ---------------------------------------------------------------------------
# Landing page delete
# ---------------------------------------------------------------------------

@router.delete("/api/landing-pages/{landing_page_id}", status_code=204)
async def delete_landing_page(
    landing_page_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
) -> Response:
    lp: LandingPage | None = (
        db.query(LandingPage)
        .filter(LandingPage.id == landing_page_id, LandingPage.created_by == user_id)
        .first()  # type: ignore[assignment]
    )
    if not lp:
        raise HTTPException(status_code=404, detail="Landingspagina niet gevonden.")

    job = db.query(Job).filter(Job.id == lp.job_id).first() if lp.job_id else None
    row_id = job.landing_page_row_id if job else None

    db.query(LandingPage).filter(LandingPage.id == landing_page_id).delete()
    if job:
        db.query(Job).filter(Job.id == job.id).delete()
    if row_id:
        db.query(LandingPageRow).filter(LandingPageRow.id == row_id).delete()
    db.commit()

    return Response(status_code=204)
