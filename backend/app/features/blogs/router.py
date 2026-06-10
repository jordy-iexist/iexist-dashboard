import json
import uuid
from collections import defaultdict
from json import JSONDecodeError
from typing import Any, cast
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.core.dependencies import require_user_id, utc_now_iso
from app.db.models import Blog, BlogGenerationSettings, BlogImage, BlogPublication, CsvRow, CsvUpload, Job, WordPressSite
from app.db.session import get_db
from app.features.blogs.dependencies import (
    dedupe_ids,
    ensure_active_sites,
    ensure_blog_exists,
    ensure_blog_readable,
    ensure_blogs_exist,
    fetch_publication_items,
)
from app.features.blogs.mappers import (
    to_blog_image_item,
    to_publication_item,
    to_wordpress_site_item,
)
from app.features.blogs.schemas import (
    BlockedPublicationItem,
    BlogDetailResponse,
    BlogShareResponse,
    DeleteBatchRequest,
    DeleteBatchResponse,
    BlogGenerationSettingsResponse,
    BlogGenerationSettingsUpdateRequest,
    BlogImageGenerationState,
    BlogImageGenerationStatusResponse,
    BlogImageItem,
    BlogImagesResponse,
    BlogItem,
    BlogPublicationSummary,
    BlogsListItem,
    BlogsListResponse,
    BlogsResponse,
    BlogUpdateRequest,
    GenerateBlogImageResponse,
    ManualUploadRequest,
    PublicationItem,
    PublicationListResponse,
    PublishActionResponse,
    PublishBatchRequest,
    PublishBlogRequest,
    RecentUploadItem,
    RecentUploadsResponse,
    UploadResponse,
    UploadStatus,
    WordPressSiteCreateRequest,
    WordPressSiteItem,
    WordPressSitesResponse,
    WordPressSiteUpdateRequest,
)
from app.features.blogs.services.crypto_service import decrypt_secret, encrypt_secret
from app.features.blogs.services.generation.openai import SYSTEM_PROMPT as DEFAULT_SYSTEM_PROMPT
from app.features.blogs.services.generation import (
    IMAGE_GENERATION_META_FIELD,
    build_blog_prompt,
    extract_template_placeholders,
    get_missing_prompt_values,
    map_row_to_prompt_fields,
    normalize_mapping,
    normalize_prompt_template,
    parse_csv,
    parse_image_generation_cell,
    should_generate_image_from_row_data,
    validate_mapping,
)
from app.features.blogs.services.image_service import (
    build_storage_path,
    upload_image_to_storage,
    validate_image_upload,
)
from app.features.blogs.services.wordpress_service import (
    WordPressServiceError,
    normalize_wordpress_url,
    validate_wordpress_credentials,
)
from app.features.settings.services import (
    MissingUserOpenAIKeyError,
    require_personal_openai_api_key,
)
from app.worker.tasks import (
    enqueue_blog_image_generation,
    generate_blog_task,
    publish_blog_to_wordpress_task,
)

router = APIRouter(tags=["blogs"])


def _row_to_dict(obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}  # type: ignore[union-attr]


def _extract_blog_context(record: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    job = record.get("jobs")
    csv_row = (job or {}).get("csv_rows")
    upload = (csv_row or {}).get("csv_uploads")
    row_data = (csv_row or {}).get("data")
    filename = str((upload or {}).get("filename") or "Onbekend bestand")
    status = str((job or {}).get("status") or "-")
    return (
        row_data if isinstance(row_data, dict) else {},
        filename,
        status,
    )


def _get_blog_record(
    blog_id: str, user_id: str, db: Session, include_shared: bool = False
) -> dict[str, Any] | None:
    query = db.query(Blog).filter(Blog.id == blog_id)
    if include_shared:
        query = query.filter(
            or_(Blog.created_by == user_id, Blog.is_public.is_(True))
        )
    else:
        query = query.filter(Blog.created_by == user_id)
    blog: Blog | None = query.first()  # type: ignore[assignment]
    if not blog:
        return None
    job: Job | None = (
        db.query(Job).filter(Job.id == blog.job_id).first()  # type: ignore[assignment]
        if blog.job_id
        else None
    )
    csv_row: CsvRow | None = (
        db.query(CsvRow).filter(CsvRow.id == job.row_id).first()  # type: ignore[assignment]
        if job and job.row_id
        else None
    )
    upload: CsvUpload | None = (
        db.query(CsvUpload).filter(CsvUpload.id == csv_row.upload_id).first()  # type: ignore[assignment]
        if csv_row
        else None
    )
    return {
        "id": str(blog.id),
        "content": blog.content,
        "share_token": blog.share_token,
        "created_at": blog.created_at,
        "published_at": blog.published_at,
        "created_by": blog.created_by,
        "is_public": bool(blog.is_public),
        "jobs": {
            "status": job.status if job else None,
            "csv_rows": {
                "data": csv_row.data if csv_row else None,
                "csv_uploads": (
                    {"filename": upload.filename if upload else None}
                    if upload
                    else None
                ),
            }
            if csv_row
            else None,
        }
        if job
        else None,
    }


@router.get("/api/blogs", response_model=BlogsListResponse)
async def list_blogs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=100),
    scope: str = Query(default="all", pattern="^(mine|shared|all)$"),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    start = (page - 1) * page_size
    if scope == "mine":
        visibility = Blog.created_by == user_id
    elif scope == "shared":
        visibility = (Blog.is_public.is_(True)) & (Blog.created_by != user_id)
    else:
        visibility = or_(Blog.created_by == user_id, Blog.is_public.is_(True))
    total: int = db.query(Blog).filter(visibility).count()
    blog_rows: list[Blog] = (
        db.query(Blog)
        .filter(visibility)
        .order_by(Blog.created_at.desc())
        .offset(start)
        .limit(page_size)
        .all()  # type: ignore[assignment]
    )
    blog_ids = [str(blog.id) for blog in blog_rows]

    publication_counts = (
        db.query(
            BlogPublication.blog_id,
            BlogPublication.status,
            func.count(BlogPublication.id).label("count"),
        )
        .filter(BlogPublication.blog_id.in_(blog_ids))
        .group_by(BlogPublication.blog_id, BlogPublication.status)
        .all()
    )

    pub_summary_map: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for blog_id, status, count in publication_counts:
        pub_summary_map[str(blog_id)][status] = count

    blogs = []
    for blog in blog_rows:
        job: Job | None = (
            db.query(Job).filter(Job.id == blog.job_id).first()  # type: ignore[assignment]
            if blog.job_id
            else None
        )
        csv_row: CsvRow | None = (
            db.query(CsvRow).filter(CsvRow.id == job.row_id).first()  # type: ignore[assignment]
            if job and job.row_id
            else None
        )
        upload: CsvUpload | None = (
            db.query(CsvUpload).filter(CsvUpload.id == csv_row.upload_id).first()  # type: ignore[assignment]
            if csv_row
            else None
        )
        record: dict[str, Any] = {
            "id": str(blog.id),
            "content": blog.content,
            "created_at": blog.created_at,
            "created_by": blog.created_by,
            "jobs": {
                "status": job.status if job else None,
                "csv_rows": {
                    "data": csv_row.data if csv_row else None,
                    "csv_uploads": (
                        {"filename": upload.filename if upload else None}
                        if upload
                        else None
                    ),
                }
                if csv_row
                else None,
            }
            if job
            else None,
        }
        row_data, filename, _status = _extract_blog_context(record)

        counts = pub_summary_map.get(str(blog.id), {})
        succeeded = counts.get("succeeded", 0)
        failed = counts.get("failed", 0)
        pending = counts.get("pending", 0)
        processing = counts.get("processing", 0)
        total_pubs = succeeded + failed + pending + processing
        publication = (
            BlogPublicationSummary(
                total=total_pubs,
                succeeded=succeeded,
                failed=failed,
                pending=pending,
                processing=processing,
            )
            if total_pubs > 0
            else None
        )

        blogs.append(
            BlogsListItem(
                id=str(blog.id),
                row_data=row_data,
                content=str(blog.content),
                filename=filename,
                created_at=cast(Any, blog.created_at),
                published_at=cast(Any, blog.published_at),
                publication=publication,
                share_token=str(blog.share_token),
                is_public=bool(blog.is_public),
                is_owner=str(blog.created_by or "") == user_id,
            )
        )

    return BlogsListResponse(
        blogs=blogs,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/api/blogs/settings", response_model=BlogGenerationSettingsResponse)
async def get_blog_generation_settings(
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    user_settings: BlogGenerationSettings | None = (
        db.query(BlogGenerationSettings)
        .filter(BlogGenerationSettings.user_id == user_id)
        .first()  # type: ignore[assignment]
    )
    return BlogGenerationSettingsResponse(
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
            else app_settings.openai_blog_reasoning_effort
        ),
        effective_model=(
            user_settings.model
            if user_settings and user_settings.model
            else app_settings.openai_blog_model
        ),
        effective_max_output_tokens=(
            user_settings.max_output_tokens
            if user_settings and user_settings.max_output_tokens is not None
            else app_settings.openai_blog_max_output_tokens
        ),
    )


@router.put("/api/blogs/settings", response_model=BlogGenerationSettingsResponse)
async def update_blog_generation_settings(
    payload: BlogGenerationSettingsUpdateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    user_settings: BlogGenerationSettings | None = (
        db.query(BlogGenerationSettings)
        .filter(BlogGenerationSettings.user_id == user_id)
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
        user_settings = BlogGenerationSettings(
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

    return BlogGenerationSettingsResponse(
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
            else app_settings.openai_blog_reasoning_effort
        ),
        effective_model=(
            user_settings.model
            if user_settings.model
            else app_settings.openai_blog_model
        ),
        effective_max_output_tokens=(
            user_settings.max_output_tokens
            if user_settings.max_output_tokens is not None
            else app_settings.openai_blog_max_output_tokens
        ),
    )


@router.get("/api/blogs/share/{token}", response_model=BlogShareResponse)
async def get_shared_blog(token: str, db: Session = Depends(get_db)):
    blog: Blog | None = (
        db.query(Blog).filter(Blog.share_token == token).first()  # type: ignore[assignment]
    )
    if not blog:
        raise HTTPException(status_code=404, detail="Blog niet gevonden.")
    images: list[BlogImage] = (
        db.query(BlogImage)
        .filter(BlogImage.blog_id == blog.id)
        .order_by(BlogImage.is_primary.desc(), BlogImage.created_at.desc())
        .all()  # type: ignore[assignment]
    )
    return BlogShareResponse(
        id=str(blog.id),
        content=blog.content,
        created_at=blog.created_at,
        images=[to_blog_image_item(_row_to_dict(image)) for image in images],
    )


@router.get("/api/blogs/{blog_id}", response_model=BlogDetailResponse)
async def get_blog(
    blog_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    blog = _get_blog_record(blog_id, user_id, db, include_shared=True)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog niet gevonden.")
    row_data, filename, status = _extract_blog_context(blog)
    return BlogDetailResponse(
        id=str(blog["id"]),
        row_data=row_data,
        content=str(blog["content"]),
        filename=filename,
        status=status,
        created_at=blog["created_at"],
        published_at=blog.get("published_at"),
        share_token=str(blog["share_token"]),
        is_public=bool(blog.get("is_public")),
        is_owner=str(blog.get("created_by") or "") == user_id,
    )


@router.patch("/api/blogs/{blog_id}", response_model=BlogDetailResponse)
async def update_blog(
    blog_id: str,
    payload: BlogUpdateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    updates: dict[str, Any] = {}
    if payload.content is not None:
        content = str(payload.content or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="Blog inhoud mag niet leeg zijn.")
        updates["content"] = content
    if payload.is_public is not None:
        updates["is_public"] = bool(payload.is_public)
    if not updates:
        raise HTTPException(status_code=400, detail="Minimaal één veld moet worden meegegeven.")

    existing = _get_blog_record(blog_id, user_id, db)
    if not existing:
        raise HTTPException(status_code=404, detail="Blog niet gevonden.")

    db.query(Blog).filter(Blog.id == blog_id, Blog.created_by == user_id).update(updates)
    db.commit()

    refreshed = _get_blog_record(blog_id, user_id, db)
    if not refreshed:
        raise HTTPException(status_code=500, detail="Kon blog niet opslaan.")
    row_data, filename, status = _extract_blog_context(refreshed)
    return BlogDetailResponse(
        id=str(refreshed["id"]),
        row_data=row_data,
        content=str(refreshed["content"]),
        filename=filename,
        status=status,
        created_at=refreshed["created_at"],
        published_at=refreshed.get("published_at"),
        share_token=str(refreshed["share_token"]),
        is_public=bool(refreshed.get("is_public")),
        is_owner=True,
    )


@router.delete("/api/blogs/{blog_id}", status_code=204)
async def delete_blog(
    blog_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
) -> Response:
    record = _get_blog_record(blog_id, user_id, db)
    if not record:
        raise HTTPException(status_code=404, detail="Blog niet gevonden.")

    db.query(BlogPublication).filter(BlogPublication.blog_id == blog_id).delete()
    db.query(BlogImage).filter(BlogImage.blog_id == blog_id).delete()
    db.query(Job).filter(Job.blog_id == blog_id).delete()
    db.query(Blog).filter(Blog.id == blog_id).delete()
    db.commit()

    return Response(status_code=204)


@router.post("/api/blogs/delete/batch", response_model=DeleteBatchResponse)
async def delete_blogs_batch(
    payload: DeleteBatchRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
) -> DeleteBatchResponse:
    blog_ids = dedupe_ids(payload.blog_ids)
    if not blog_ids:
        raise HTTPException(status_code=400, detail="Minimaal één blog is verplicht.")

    owned_rows = (
        db.query(Blog.id)
        .filter(Blog.id.in_(blog_ids), Blog.created_by == user_id)
        .all()
    )
    owned_ids = [str(row.id) for row in owned_rows]
    missing = [bid for bid in blog_ids if bid not in owned_ids]

    if owned_ids:
        db.query(BlogPublication).filter(BlogPublication.blog_id.in_(owned_ids)).delete(synchronize_session=False)
        db.query(BlogImage).filter(BlogImage.blog_id.in_(owned_ids)).delete(synchronize_session=False)
        db.query(Job).filter(Job.blog_id.in_(owned_ids)).delete(synchronize_session=False)
        db.query(Blog).filter(Blog.id.in_(owned_ids)).delete(synchronize_session=False)
        db.commit()

    return DeleteBatchResponse(
        requested=len(blog_ids),
        deleted=len(owned_ids),
        missing=missing,
    )


@router.post("/api/csv/upload", response_model=UploadResponse)
async def upload_csv(
    file: UploadFile = File(...),
    mapping: str = Form(...),
    template: str = Form(""),
    image_generation_column: str = Form(""),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Upload CSV, validate prompt placeholders/mappings, and queue jobs per row."""
    try:
        require_personal_openai_api_key(user_id, db)
    except MissingUserOpenAIKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    if not mapping.strip():
        raise HTTPException(status_code=400, detail="Mapping is required")

    prompt_template = normalize_prompt_template(template)
    try:
        required_fields = extract_template_placeholders(prompt_template)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        mapping_payload = json.loads(mapping)
    except JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="Mapping must be valid JSON"
        ) from exc

    if not isinstance(mapping_payload, dict):
        raise HTTPException(status_code=400, detail="Mapping must be a JSON object")

    content = await file.read()
    try:
        headers, rows = parse_csv(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    try:
        normalized_mapping = normalize_mapping(mapping_payload, required_fields)
        validate_mapping(normalized_mapping, headers, required_fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    normalized_image_generation_column = str(image_generation_column or "").strip()
    if (
        normalized_image_generation_column
        and normalized_image_generation_column not in headers
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Kolom voor afbeeldingsgeneratie bestaat niet in CSV-header: "
                f"{normalized_image_generation_column}"
            ),
        )

    prompt_rows: list[dict[str, Any]] = []
    image_jobs_target = 0
    skipped_rows: list[str] = []
    for row_index, row in enumerate(rows, start=2):
        prompt_row: dict[str, Any] = dict(  # type: ignore[arg-type]
            map_row_to_prompt_fields(row, normalized_mapping, required_fields)
        )
        missing_values = get_missing_prompt_values(prompt_row, required_fields)
        if missing_values:
            skipped_rows.append(f"rij {row_index}: {', '.join(missing_values)}")
            continue

        try:
            build_blog_prompt(prompt_template, prompt_row)
        except ValueError as exc:
            skipped_rows.append(f"rij {row_index}: {exc}")
            continue

        should_generate_image = False
        if normalized_image_generation_column:
            should_generate_image = parse_image_generation_cell(
                row.get(normalized_image_generation_column)
            )
        prompt_row[IMAGE_GENERATION_META_FIELD] = should_generate_image
        if should_generate_image:
            image_jobs_target += 1

        prompt_rows.append(prompt_row)

    if not prompt_rows:
        shown_errors = (
            "; ".join(skipped_rows[:10]) if skipped_rows else "geen geldige rijen"
        )
        suffix = " ..." if len(skipped_rows) > 10 else ""
        raise HTTPException(
            status_code=400,
            detail=f"Geen verwerkbare rijen gevonden. Overgeslagen: {shown_errors}{suffix}",
        )

    upload_id = str(uuid.uuid4())
    csv_upload = CsvUpload(
        id=upload_id,
        filename=file.filename,
        template=prompt_template,
        skipped_rows=len(skipped_rows),
        created_by=user_id,
    )
    db.add(csv_upload)
    db.commit()

    jobs_queued = 0
    for prompt_row in prompt_rows:
        row_id = str(uuid.uuid4())
        csv_row_obj = CsvRow(id=row_id, upload_id=upload_id, data=prompt_row)
        db.add(csv_row_obj)

        job_id = str(uuid.uuid4())
        job_obj = Job(
            id=job_id,
            row_id=row_id,
            job_type="blog_generation",
            blog_id=None,
            status="pending",
            error=None,
            created_by=user_id,
        )
        db.add(job_obj)
        db.commit()

        generate_blog_task.delay(job_id)  # type: ignore[attr-defined]
        jobs_queued += 1

    return UploadResponse(
        upload_id=upload_id,
        rows_count=len(prompt_rows),
        jobs_queued=jobs_queued,
        skipped_rows=len(skipped_rows),
        images_target=image_jobs_target,
        status="processing",
    )


@router.post("/api/csv/manual", response_model=UploadResponse)
async def manual_upload(
    payload: ManualUploadRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Accept pre-filled rows (no CSV file) and queue blog generation jobs."""
    try:
        require_personal_openai_api_key(user_id, db)
    except MissingUserOpenAIKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not payload.rows:
        raise HTTPException(status_code=400, detail="Voeg minimaal één rij toe.")

    prompt_template = normalize_prompt_template(payload.template)
    try:
        required_fields = extract_template_placeholders(prompt_template)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    prompt_rows: list[dict[str, Any]] = []
    image_jobs_target = 0
    skipped_rows: list[str] = []

    for row_index, raw_row in enumerate(payload.rows, start=1):
        prompt_row: dict[str, Any] = {
            field: str(raw_row.get(field, "") or "").strip()
            for field in required_fields
        }
        missing_values = get_missing_prompt_values(prompt_row, required_fields)
        if missing_values:
            skipped_rows.append(f"rij {row_index}: {', '.join(missing_values)}")
            continue

        try:
            build_blog_prompt(prompt_template, prompt_row)
        except ValueError as exc:
            skipped_rows.append(f"rij {row_index}: {exc}")
            continue

        should_generate_image = bool(raw_row.get(IMAGE_GENERATION_META_FIELD, False))
        prompt_row[IMAGE_GENERATION_META_FIELD] = should_generate_image
        if should_generate_image:
            image_jobs_target += 1

        prompt_rows.append(prompt_row)

    if not prompt_rows:
        shown_errors = (
            "; ".join(skipped_rows[:10]) if skipped_rows else "geen geldige rijen"
        )
        suffix = " ..." if len(skipped_rows) > 10 else ""
        raise HTTPException(
            status_code=400,
            detail=f"Geen verwerkbare rijen gevonden. Overgeslagen: {shown_errors}{suffix}",
        )

    upload_id = str(uuid.uuid4())
    csv_upload = CsvUpload(
        id=upload_id,
        filename="Handmatige invoer",
        template=prompt_template,
        skipped_rows=len(skipped_rows),
        created_by=user_id,
    )
    db.add(csv_upload)
    db.commit()

    jobs_queued = 0
    for prompt_row in prompt_rows:
        row_id = str(uuid.uuid4())
        csv_row_obj = CsvRow(id=row_id, upload_id=upload_id, data=prompt_row)
        db.add(csv_row_obj)

        job_id = str(uuid.uuid4())
        job_obj = Job(
            id=job_id,
            row_id=row_id,
            job_type="blog_generation",
            blog_id=None,
            status="pending",
            error=None,
            created_by=user_id,
        )
        db.add(job_obj)
        db.commit()

        generate_blog_task.delay(job_id)  # type: ignore[attr-defined]
        jobs_queued += 1

    return UploadResponse(
        upload_id=upload_id,
        rows_count=len(prompt_rows),
        jobs_queued=jobs_queued,
        skipped_rows=len(skipped_rows),
        images_target=image_jobs_target,
        status="processing",
    )


def _collect_error_messages(
    errors: list[str | None], *, limit: int = 3, max_len: int = 300
) -> list[str]:
    """Dedupliceer foutmeldingen van mislukte jobs voor weergave in de UI."""
    seen: set[str] = set()
    messages: list[str] = []
    for error in errors:
        text = str(error or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        if len(text) > max_len:
            text = text[: max_len - 1].rstrip() + "…"
        messages.append(text)
        if len(messages) >= limit:
            break
    return messages


@router.get("/api/csv/uploads", response_model=RecentUploadsResponse)
async def list_recent_uploads(
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """List the 10 most recent CSV uploads for the current user."""
    uploads: list[CsvUpload] = (
        db.query(CsvUpload)
        .filter(CsvUpload.created_by == user_id, CsvUpload.dismissed_at.is_(None))
        .order_by(CsvUpload.created_at.desc())
        .limit(10)
        .all()  # type: ignore[assignment]
    )

    if not uploads:
        return RecentUploadsResponse(uploads=[])

    upload_ids = [u.id for u in uploads]

    job_rows = (
        db.query(Job.status, Job.error, CsvRow.upload_id)
        .join(CsvRow, Job.row_id == CsvRow.id)
        .filter(CsvRow.upload_id.in_(upload_ids))
        .filter(Job.job_type != "image_generation")
        .all()
    )

    counts: dict[str, dict[str, int]] = {
        uid: {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "canceled": 0}
        for uid in upload_ids
    }
    errors_by_upload: dict[str, list[str | None]] = {uid: [] for uid in upload_ids}
    for job_status, job_error, upload_id in job_rows:
        bucket = str(job_status or "").strip()
        if bucket in counts[upload_id]:
            counts[upload_id][bucket] += 1
        if bucket == "failed":
            errors_by_upload[upload_id].append(job_error)

    items: list[RecentUploadItem] = []
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
            RecentUploadItem(
                upload_id=upload.id,
                filename=upload.filename,
                template=upload.template,
                created_at=upload.created_at,
                total_jobs=total,
                completed=c["completed"],
                failed=c["failed"],
                canceled=c["canceled"],
                processed=processed,
                is_done=is_done,
                final_status=final_status,
                error_messages=_collect_error_messages(errors_by_upload[upload.id]),
            )
        )

    return RecentUploadsResponse(uploads=items)


@router.get("/api/uploads/{upload_id}", response_model=UploadStatus)
async def get_upload_status(
    upload_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Get the status of an upload and its jobs."""
    upload: CsvUpload | None = (
        db.query(CsvUpload)
        .filter(CsvUpload.id == upload_id, CsvUpload.created_by == user_id)
        .first()  # type: ignore[assignment]
    )
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")

    all_jobs: list[Job] = (
        db.query(Job)
        .join(CsvRow, Job.row_id == CsvRow.id)
        .filter(CsvRow.upload_id == upload_id)
        .all()  # type: ignore[assignment]
    )

    blog_jobs: list[Job] = []
    image_jobs: list[Job] = []
    for job in all_jobs:
        raw_job_type = str(job.job_type or "").strip()
        if raw_job_type == "image_generation":
            image_jobs.append(job)
            continue
        blog_jobs.append(job)

    total = len(blog_jobs)
    status_counts: dict[str, int] = {
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "canceled": 0,
    }
    for job in blog_jobs:
        if job.status in status_counts:
            status_counts[job.status] += 1

    images_target = 0
    for job in blog_jobs:
        csv_row: CsvRow | None = (
            db.query(CsvRow).filter(CsvRow.id == job.row_id).first()  # type: ignore[assignment]
            if job.row_id
            else None
        )
        row_data = csv_row.data if csv_row else None
        if should_generate_image_from_row_data(
            row_data if isinstance(row_data, dict) else None,
            default_when_missing=False,
        ):
            images_target += 1

    image_generated = 0
    for job in image_jobs:
        if job.status == "completed":
            image_generated += 1

    if image_generated > images_target:
        image_generated = images_target

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

    return UploadStatus(
        upload_id=upload_id,
        filename=upload.filename,
        template=upload.template,
        total_jobs=total,
        jobs_created=total,
        completed=completed,
        failed=failed,
        processing=processing,
        pending=pending,
        canceled=canceled,
        processed=processed,
        remaining=remaining,
        skipped_rows=skipped_rows_count,
        images_generated=image_generated,
        images_target=images_target,
        is_done=is_done,
        final_status=final_status,
        error_messages=_collect_error_messages(
            [job.error for job in blog_jobs if job.status == "failed"]
        ),
    )


@router.post("/api/csv/uploads/{upload_id}/cancel")
async def cancel_upload(
    upload_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    upload: CsvUpload | None = (
        db.query(CsvUpload)
        .filter(CsvUpload.id == upload_id, CsvUpload.created_by == user_id)
        .first()
    )
    if not upload:
        raise HTTPException(status_code=404, detail="Upload niet gevonden.")

    all_jobs: list[Job] = (
        db.query(Job)
        .join(CsvRow, Job.row_id == CsvRow.id)
        .filter(CsvRow.upload_id == upload_id)
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
            Job.row_id.in_(
                db.query(CsvRow.id).filter(CsvRow.upload_id == upload_id)
            ),
            Job.status.in_(["pending", "processing"]),
        )
        .update({"status": "canceled"}, synchronize_session="fetch")
    )
    db.commit()

    return {"ok": True, "upload_id": upload_id}


@router.post("/api/csv/uploads/{upload_id}/dismiss", status_code=204)
async def dismiss_csv_upload(
    upload_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
) -> Response:
    upload: CsvUpload | None = (
        db.query(CsvUpload)
        .filter(CsvUpload.id == upload_id, CsvUpload.created_by == user_id)
        .first()
    )
    if not upload:
        raise HTTPException(status_code=404, detail="Upload niet gevonden.")

    upload.dismissed_at = utc_now_iso()
    db.commit()
    return Response(status_code=204)


@router.get("/api/uploads/{upload_id}/blogs", response_model=BlogsResponse)
async def get_upload_blogs(
    upload_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Get all generated blogs for an upload."""
    upload: CsvUpload | None = (
        db.query(CsvUpload)
        .filter(CsvUpload.id == upload_id, CsvUpload.created_by == user_id)
        .first()  # type: ignore[assignment]
    )
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")

    blogs_query: list[tuple[Blog, Any]] = (
        db.query(Blog, CsvRow.data)
        .join(Job, Blog.job_id == Job.id)
        .join(CsvRow, Job.row_id == CsvRow.id)
        .filter(CsvRow.upload_id == upload_id, Blog.created_by == user_id)
        .all()  # type: ignore[assignment]
    )
    blogs = [
        BlogItem(
            id=str(blog.id),
            row_data=data if isinstance(data, dict) else {},
            content=blog.content,
            created_at=cast(Any, blog.created_at),
        )
        for blog, data in blogs_query
    ]

    return BlogsResponse(blogs=blogs)


@router.get("/api/blogs/{blog_id}/images", response_model=BlogImagesResponse)
async def get_blog_images(
    blog_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    ensure_blog_readable(blog_id, user_id)
    images: list[BlogImage] = (
        db.query(BlogImage)
        .filter(BlogImage.blog_id == blog_id)
        .order_by(BlogImage.is_primary.desc(), BlogImage.created_at.desc())
        .all()  # type: ignore[assignment]
    )
    return BlogImagesResponse(
        images=[to_blog_image_item(_row_to_dict(image)) for image in images]
    )


@router.get(
    "/api/blogs/{blog_id}/images/generation-status",
    response_model=BlogImageGenerationStatusResponse,
)
async def get_blog_image_generation_status(
    blog_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    ensure_blog_readable(blog_id, user_id)

    primary_image: BlogImage | None = (
        db.query(BlogImage)
        .filter(BlogImage.blog_id == blog_id, BlogImage.is_primary == True)  # noqa: E712
        .order_by(BlogImage.created_at.desc())
        .first()  # type: ignore[assignment]
    )
    has_primary_image = bool(primary_image)

    try:
        latest_job: Job | None = (
            db.query(Job)
            .filter(Job.job_type == "image_generation", Job.blog_id == blog_id)
            .order_by(Job.created_at.desc())
            .first()  # type: ignore[assignment]
        )
    except Exception as exc:
        lowered = str(exc).lower()
        if "job_type" in lowered or "blog_id" in lowered:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Database migratie ontbreekt. Voer uit: "
                    "2026-02-10-add-image-generation-job-tracking.sql"
                ),
            ) from exc
        raise

    if not latest_job:
        if has_primary_image and primary_image is not None:
            return BlogImageGenerationStatusResponse(
                blog_id=blog_id,
                state=cast(BlogImageGenerationState, "completed"),
                progress_percent=100,
                message="Afbeelding beschikbaar.",
                job_id=None,
                error_message=None,
                has_primary_image=True,
                primary_image_id=str(primary_image.id),
                primary_image_created_at=cast(Any, primary_image.created_at),
            )

        return BlogImageGenerationStatusResponse(
            blog_id=blog_id,
            state=cast(BlogImageGenerationState, "idle"),
            progress_percent=0,
            message="Nog geen automatische afbeelding generatie gestart.",
            job_id=None,
            error_message=None,
            has_primary_image=False,
            primary_image_id=None,
            primary_image_created_at=None,
        )

    raw_state = str(latest_job.status or "pending")
    if raw_state not in {"pending", "processing", "completed", "failed"}:
        raw_state = "pending"
    state = cast(BlogImageGenerationState, raw_state)

    progress_map: dict[str, int] = {
        "pending": 25,
        "processing": 70,
        "completed": 100,
        "failed": 100,
    }
    default_message_map: dict[str, str] = {
        "pending": "Afbeelding staat in de wachtrij.",
        "processing": "Afbeelding wordt nu gegenereerd.",
        "completed": "Afbeelding is gegenereerd.",
        "failed": "Afbeelding genereren is mislukt.",
    }
    error_message = (
        str(latest_job.error) if latest_job.error not in {None, ""} else None
    )
    message = (
        error_message
        if raw_state == "failed" and error_message
        else default_message_map[raw_state]
    )

    return BlogImageGenerationStatusResponse(
        blog_id=blog_id,
        state=state,
        progress_percent=progress_map[raw_state],
        message=message,
        job_id=str(latest_job.id),
        error_message=error_message,
        has_primary_image=has_primary_image,
        primary_image_id=str(primary_image.id) if primary_image else None,
        primary_image_created_at=cast(Any, primary_image.created_at)
        if primary_image
        else None,
    )


@router.post("/api/blogs/{blog_id}/images/upload", response_model=BlogImageItem)
async def upload_blog_image(
    blog_id: str,
    file: UploadFile = File(...),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    ensure_blog_exists(blog_id, user_id)

    filename = str(file.filename or "").strip()
    content = await file.read()
    try:
        mime_type = validate_image_upload(filename, file.content_type, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    storage_path = build_storage_path(blog_id, "manual_upload", mime_type)
    try:
        upload_image_to_storage(storage_path, content, mime_type)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Uploaden van afbeelding mislukt: {exc}"
        ) from exc

    image_id = str(uuid.uuid4())
    now = utc_now_iso()

    db.query(BlogImage).filter(
        BlogImage.blog_id == blog_id,
        BlogImage.is_primary == True,  # noqa: E712
    ).update({"is_primary": False, "updated_at": now})
    db.commit()

    image = BlogImage(
        id=image_id,
        blog_id=blog_id,
        source="manual_upload",
        storage_path=storage_path,
        mime_type=mime_type,
        file_size_bytes=len(content),
        width=None,
        height=None,
        is_primary=True,
        generation_prompt=None,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(image)
    db.commit()
    db.refresh(image)

    return to_blog_image_item(_row_to_dict(image))


@router.post(
    "/api/blogs/{blog_id}/images/generate", response_model=GenerateBlogImageResponse
)
async def queue_blog_image_generation(
    blog_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    ensure_blog_exists(blog_id, user_id)
    try:
        require_personal_openai_api_key(user_id, db)
    except MissingUserOpenAIKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        image_job_id = enqueue_blog_image_generation(blog_id)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Kon afbeelding generatie niet starten: {exc}",
        ) from exc

    return GenerateBlogImageResponse(
        status="queued",
        message="Automatische afbeelding staat in de wachtrij.",
        job_id=image_job_id,
    )


# WordPress Site endpoints

@router.post("/api/wordpress/sites", response_model=WordPressSiteItem)
async def create_wordpress_site(
    payload: WordPressSiteCreateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    try:
        base_url = normalize_wordpress_url(payload.base_url)
    except WordPressServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    wp_login = payload.wp_login.strip()
    wp_password = payload.wp_password.strip()
    custom_name = (payload.name or "").strip()

    if not wp_login:
        raise HTTPException(status_code=400, detail="WordPress login is verplicht.")
    if not wp_password:
        raise HTTPException(
            status_code=400, detail="WordPress wachtwoord is verplicht."
        )

    try:
        validation = validate_wordpress_credentials(base_url, wp_login, wp_password)
    except WordPressServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    canonical_base_url = validation.normalized_base_url
    existing_site = (
        db.query(WordPressSite)
        .filter(
            WordPressSite.base_url == canonical_base_url,
            WordPressSite.created_by == user_id,
        )
        .first()
    )
    if existing_site:
        raise HTTPException(
            status_code=409, detail="Deze WordPress site is al toegevoegd."
        )

    hostname = urlparse(canonical_base_url).hostname or canonical_base_url
    site_name = custom_name or validation.site_name or hostname
    site_id = str(uuid.uuid4())
    now = utc_now_iso()

    site = WordPressSite(
        id=site_id,
        name=site_name,
        base_url=canonical_base_url,
        wp_login=wp_login,
        app_password_encrypted=encrypt_secret(wp_password),
        is_active=True,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(site)
    db.commit()
    db.refresh(site)

    return to_wordpress_site_item(_row_to_dict(site))


@router.get("/api/wordpress/sites", response_model=WordPressSitesResponse)
async def list_wordpress_sites(
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    sites = (
        db.query(WordPressSite)
        .filter(WordPressSite.created_by == user_id)
        .order_by(WordPressSite.created_at.desc())
        .all()
    )
    return WordPressSitesResponse(
        sites=[to_wordpress_site_item(_row_to_dict(s)) for s in sites]
    )


@router.patch("/api/wordpress/sites/{site_id}", response_model=WordPressSiteItem)
async def update_wordpress_site(
    site_id: str,
    payload: WordPressSiteUpdateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    site = (
        db.query(WordPressSite)
        .filter(
            WordPressSite.id == site_id,
            WordPressSite.created_by == user_id,
        )
        .first()
    )
    if not site:
        raise HTTPException(status_code=404, detail="WordPress site niet gevonden.")

    site_dict = _row_to_dict(site)
    updates: dict[str, Any] = {"updated_at": utc_now_iso()}

    new_name = payload.name.strip() if isinstance(payload.name, str) else None
    if isinstance(payload.base_url, str):
        try:
            new_base_url = normalize_wordpress_url(payload.base_url)
        except WordPressServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        new_base_url = str(site_dict["base_url"])

    new_wp_login = (
        payload.wp_login.strip()
        if isinstance(payload.wp_login, str)
        else str(site_dict["wp_login"])
    )
    new_wp_password = (
        payload.wp_password.strip() if isinstance(payload.wp_password, str) else None
    )

    if isinstance(payload.name, str):
        if not new_name:
            raise HTTPException(status_code=400, detail="Naam mag niet leeg zijn.")
        updates["name"] = new_name

    if isinstance(payload.base_url, str):
        duplicate_site = (
            db.query(WordPressSite)
            .filter(
                WordPressSite.base_url == new_base_url,
                WordPressSite.created_by == user_id,
                WordPressSite.id != site_id,
            )
            .first()
        )
        if duplicate_site:
            raise HTTPException(
                status_code=409,
                detail="Er bestaat al een koppeling met deze WordPress URL.",
            )
        updates["base_url"] = new_base_url

    if isinstance(payload.wp_login, str):
        if not new_wp_login:
            raise HTTPException(
                status_code=400, detail="WordPress login mag niet leeg zijn."
            )
        updates["wp_login"] = new_wp_login

    if isinstance(payload.wp_password, str):
        if not new_wp_password:
            raise HTTPException(
                status_code=400,
                detail="WordPress wachtwoord mag niet leeg zijn.",
            )
        updates["app_password_encrypted"] = encrypt_secret(new_wp_password)

    if payload.is_active is not None:
        updates["is_active"] = payload.is_active

    needs_validation = (
        isinstance(payload.base_url, str)
        or isinstance(payload.wp_login, str)
        or isinstance(payload.wp_password, str)
    )
    next_is_active = bool(updates.get("is_active", site_dict.get("is_active", True)))
    if needs_validation and next_is_active:
        if isinstance(payload.wp_password, str):
            password_for_validation = new_wp_password or ""
        else:
            try:
                password_for_validation = decrypt_secret(
                    str(site_dict["app_password_encrypted"])
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=500,
                    detail="Kon bestaande WordPress credentials niet lezen.",
                ) from exc

        try:
            validation = validate_wordpress_credentials(
                new_base_url,
                new_wp_login,
                password_for_validation,
            )
        except WordPressServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        canonical_base_url = validation.normalized_base_url
        duplicate_site = (
            db.query(WordPressSite)
            .filter(
                WordPressSite.base_url == canonical_base_url,
                WordPressSite.created_by == user_id,
                WordPressSite.id != site_id,
            )
            .first()
        )
        if duplicate_site:
            raise HTTPException(
                status_code=409,
                detail="Er bestaat al een koppeling met deze WordPress URL.",
            )
        updates["base_url"] = canonical_base_url

    if len(updates) == 1:
        raise HTTPException(status_code=400, detail="Geen wijzigingen ontvangen.")

    (
        db.query(WordPressSite)
        .filter(
            WordPressSite.id == site_id,
            WordPressSite.created_by == user_id,
        )
        .update(updates)
    )
    db.commit()

    updated_site = (
        db.query(WordPressSite)
        .filter(
            WordPressSite.id == site_id,
            WordPressSite.created_by == user_id,
        )
        .first()
    )
    if not updated_site:
        raise HTTPException(status_code=500, detail="Kon WordPress site niet updaten.")
    return to_wordpress_site_item(_row_to_dict(updated_site))


@router.post("/api/blogs/{blog_id}/publish", response_model=PublishActionResponse)
async def publish_single_blog(
    blog_id: str,
    payload: PublishBlogRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    site_ids = dedupe_ids(payload.site_ids)
    if not site_ids:
        raise HTTPException(
            status_code=400, detail="Minimaal één WordPress site is verplicht."
        )

    blog = db.query(Blog).filter(Blog.id == blog_id, Blog.created_by == user_id).first()
    if not blog:
        raise HTTPException(status_code=404, detail="Blog niet gevonden.")

    ensure_active_sites(site_ids)

    existing_pubs = (
        db.query(BlogPublication)
        .filter(
            BlogPublication.blog_id == blog_id,
            BlogPublication.requested_by == user_id,
            BlogPublication.wordpress_site_id.in_(site_ids),
        )
        .all()
    )
    existing_site_ids = {str(pub.wordpress_site_id) for pub in existing_pubs}

    blocked_items = [
        BlockedPublicationItem(blog_id=blog_id, wordpress_site_id=site_id)
        for site_id in site_ids
        if site_id in existing_site_ids
    ]

    now = utc_now_iso()
    queued_ids: list[str] = []
    for site_id in site_ids:
        if site_id in existing_site_ids:
            continue
        pub_id = str(uuid.uuid4())
        queued_ids.append(pub_id)
        pub = BlogPublication(
            id=pub_id,
            blog_id=blog_id,
            wordpress_site_id=site_id,
            status="pending",
            requested_by=user_id,
            wp_status=payload.wp_status,
            created_at=now,
            updated_at=now,
        )
        db.add(pub)

    if queued_ids:
        db.commit()
        for publication_id in queued_ids:
            publish_blog_to_wordpress_task.delay(publication_id)

    publications = fetch_publication_items(queued_ids)
    return PublishActionResponse(
        requested=len(site_ids),
        queued=len(publications),
        blocked_duplicates=len(blocked_items),
        publications=publications,
        blocked=blocked_items,
    )


@router.post("/api/blogs/publish/batch", response_model=PublishActionResponse)
async def publish_blogs_batch(
    payload: PublishBatchRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    blog_ids = dedupe_ids(payload.blog_ids)
    site_ids = dedupe_ids(payload.site_ids)

    if not blog_ids:
        raise HTTPException(status_code=400, detail="Minimaal één blog is verplicht.")
    if not site_ids:
        raise HTTPException(
            status_code=400, detail="Minimaal één WordPress site is verplicht."
        )

    ensure_blogs_exist(blog_ids, user_id)
    ensure_active_sites(site_ids)

    existing_pubs = (
        db.query(BlogPublication)
        .filter(
            BlogPublication.requested_by == user_id,
            BlogPublication.blog_id.in_(blog_ids),
            BlogPublication.wordpress_site_id.in_(site_ids),
        )
        .all()
    )
    existing_pairs = {
        (str(pub.blog_id), str(pub.wordpress_site_id)) for pub in existing_pubs
    }

    blocked_items: list[BlockedPublicationItem] = []
    now = utc_now_iso()
    queued_ids: list[str] = []

    for blog_id in blog_ids:
        for site_id in site_ids:
            if (blog_id, site_id) in existing_pairs:
                blocked_items.append(
                    BlockedPublicationItem(blog_id=blog_id, wordpress_site_id=site_id)
                )
                continue
            pub_id = str(uuid.uuid4())
            queued_ids.append(pub_id)
            pub = BlogPublication(
                id=pub_id,
                blog_id=blog_id,
                wordpress_site_id=site_id,
                status="pending",
                requested_by=user_id,
                wp_status=payload.wp_status,
                created_at=now,
                updated_at=now,
            )
            db.add(pub)

    if queued_ids:
        db.commit()
        for publication_id in queued_ids:
            publish_blog_to_wordpress_task.delay(publication_id)

    publications = fetch_publication_items(queued_ids)
    return PublishActionResponse(
        requested=len(blog_ids) * len(site_ids),
        queued=len(publications),
        blocked_duplicates=len(blocked_items),
        publications=publications,
        blocked=blocked_items,
    )


@router.get("/api/publications/{publication_id}", response_model=PublicationItem)
async def get_publication(
    publication_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    pub = (
        db.query(BlogPublication)
        .filter(
            BlogPublication.id == publication_id,
            BlogPublication.requested_by == user_id,
        )
        .first()
    )
    if not pub:
        raise HTTPException(status_code=404, detail="Publicatie niet gevonden.")
    return to_publication_item(_row_to_dict(pub))


@router.get("/api/publications", response_model=PublicationListResponse)
async def list_publications(
    blog_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    q = db.query(BlogPublication).filter(BlogPublication.requested_by == user_id)
    if blog_id and blog_id.strip():
        q = q.filter(BlogPublication.blog_id == blog_id.strip())
    q = q.order_by(BlogPublication.created_at.desc()).limit(limit)

    pubs = q.all()
    return PublicationListResponse(
        publications=[to_publication_item(_row_to_dict(p)) for p in pubs]
    )
