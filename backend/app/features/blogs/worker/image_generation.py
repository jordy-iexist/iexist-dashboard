import uuid

from celery.utils.log import get_task_logger

from app.db.models import Blog, BlogImage, CsvRow, Job
from app.db.session import SessionLocal
from app.features.blogs.services.image_service import (
    build_auto_image_prompt,
    build_storage_path,
    upload_image_to_storage,
)
from app.features.blogs.services.generation import (
    generate_blog_image,
    should_generate_image_from_row_data,
)
from app.features.settings.services import MissingUserOpenAIKeyError
from app.worker._common import build_title, utc_now_iso
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


def _row_to_dict(obj):
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}


def _create_image_generation_job(blog_id: str) -> str:
    row_id: str | None = None
    created_by: str | None = None
    db = SessionLocal()
    try:
        blog = db.query(Blog).filter(Blog.id == blog_id).first()
        if blog:
            created_by = str(blog.created_by or "").strip() or None
            blog_job_id = str(blog.job_id or "").strip()
            if blog_job_id:
                parent_job = db.query(Job).filter(Job.id == blog_job_id).first()
                if parent_job:
                    parent_row_id = str(parent_job.row_id or "").strip()
                    row_id = parent_row_id or None
                    if not created_by:
                        created_by = str(parent_job.created_by or "").strip() or None
    except Exception as lookup_exc:
        logger.warning(
            "Kon parent row_id niet ophalen voor blog %s: %s",
            blog_id,
            lookup_exc,
        )

    job_id = str(uuid.uuid4())
    now = utc_now_iso()
    try:
        new_job = Job(
            id=job_id,
            row_id=row_id,
            status="pending",
            error=None,
            job_type="image_generation",
            blog_id=blog_id,
            created_by=created_by,
            created_at=now,
        )
        db.add(new_job)
        db.commit()
    except Exception as exc:
        lowered = str(exc).lower()
        if "row_id" in lowered and ("not-null" in lowered or "null value" in lowered):
            raise ValueError(
                "Database schema blokkeert image jobs omdat jobs.row_id op NOT NULL staat. "
                "Voer migratie uit: 2026-02-10-add-image-generation-job-tracking.sql"
            ) from exc
        if "job_type" in lowered or "blog_id" in lowered:
            raise ValueError(
                "Database migratie ontbreekt. Voer uit: "
                "2026-02-10-add-image-generation-job-tracking.sql"
            ) from exc
        raise
    finally:
        db.close()

    return job_id


def _set_image_generation_job_status(
    job_id: str,
    *,
    status: str,
    error: str | None = None,
) -> None:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = status
            job.error = error
            db.commit()
    finally:
        db.close()


def _all_blog_jobs_finished_for_upload(upload_id: str) -> bool:
    db = SessionLocal()
    try:
        jobs = (
            db.query(Job)
            .join(CsvRow, Job.row_id == CsvRow.id)
            .filter(CsvRow.upload_id == upload_id)
            .all()
        )
        for job in jobs:
            if job.job_type == "image_generation":
                continue
            if job.status in {"pending", "processing"}:
                return False
        return True
    finally:
        db.close()


def _dispatch_pending_image_jobs_for_upload(upload_id: str) -> int:
    db = SessionLocal()
    try:
        pending_jobs = (
            db.query(Job)
            .join(CsvRow, Job.row_id == CsvRow.id)
            .filter(
                CsvRow.upload_id == upload_id,
                Job.job_type == "image_generation",
                Job.status == "pending",
            )
            .all()
        )
        dispatched = 0

        for job in pending_jobs:
            image_job_id = str(job.id or "").strip()
            blog_id = str(job.blog_id or "").strip()
            if not image_job_id:
                continue
            if not blog_id:
                job.status = "failed"
                job.error = "Image job mist blog_id."
                db.commit()
                continue

            try:
                # claim the job (optimistic: update only if still pending)
                updated = (
                    db.query(Job)
                    .filter(Job.id == image_job_id, Job.status == "pending")
                    .update({"status": "queued", "error": None})
                )
                db.commit()
                if not updated:
                    continue

                try:
                    generate_blog_image_task.delay(blog_id, image_job_id)
                    dispatched += 1
                except Exception as queue_exc:
                    job_to_reset = db.query(Job).filter(Job.id == image_job_id).first()
                    if job_to_reset:
                        job_to_reset.status = "pending"
                        job_to_reset.error = f"Kon image taak niet starten: {queue_exc}"
                        db.commit()
            except Exception as dispatch_exc:
                logger.warning(
                    "Kon pending image job %s niet dispatchen voor upload %s: %s",
                    image_job_id,
                    upload_id,
                    dispatch_exc,
                )

        return dispatched
    finally:
        db.close()


def _maybe_start_upload_image_jobs(upload_id: str) -> None:
    normalized_upload_id = str(upload_id or "").strip()
    if not normalized_upload_id:
        return

    if not _all_blog_jobs_finished_for_upload(normalized_upload_id):
        return

    dispatched = _dispatch_pending_image_jobs_for_upload(normalized_upload_id)
    if dispatched > 0:
        logger.info(
            "Started %s image generation job(s) for upload %s after all blogs finished.",
            dispatched,
            normalized_upload_id,
        )


def enqueue_blog_image_generation(blog_id: str) -> str:
    job_id = _create_image_generation_job(blog_id)
    generate_blog_image_task.delay(blog_id, job_id)
    return job_id


@celery_app.task(
    bind=True,
    name="app.worker.tasks.generate_blog_image_task",
    autoretry_for=(Exception,),
    dont_autoretry_for=(MissingUserOpenAIKeyError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 2},
)
def generate_blog_image_task(self, blog_id: str, image_job_id: str | None = None):
    """Generate a default image for one blog and store it in local storage."""
    db = SessionLocal()
    try:
        image_job_id = str(image_job_id or "").strip() or None

        if not image_job_id:
            try:
                image_job_id = _create_image_generation_job(blog_id)
            except Exception as job_exc:
                logger.warning(
                    "Kon image generatie job tracking niet aanmaken voor blog %s: %s",
                    blog_id,
                    job_exc,
                )
                image_job_id = None

        if image_job_id:
            image_job = db.query(Job).filter(Job.id == image_job_id).first()
            if image_job and str(image_job.status or "").lower() == "canceled":
                logger.info("Image job %s was canceled, skipping.", image_job_id)
                return

        if image_job_id:
            _set_image_generation_job_status(
                image_job_id,
                status="processing",
                error=None,
            )

        blog = db.query(Blog).filter(Blog.id == blog_id).first()
        if not blog:
            raise ValueError(f"Blog {blog_id} niet gevonden.")

        content = str(blog.content or "").strip()
        if not content:
            raise ValueError(f"Blog inhoud ontbreekt voor blog {blog_id}.")
        user_id = str(blog.created_by or "").strip()
        if not user_id:
            raise ValueError(
                f"Gebruiker ontbreekt voor afbeelding generatie van blog {blog_id}."
            )

        job = (
            db.query(Job).filter(Job.id == blog.job_id).first() if blog.job_id else None
        )
        csv_row = (
            db.query(CsvRow).filter(CsvRow.id == job.row_id).first()
            if job and job.row_id
            else None
        )
        row_data = csv_row.data if csv_row and isinstance(csv_row.data, dict) else {}

        title = build_title(row_data)
        image_prompt = build_auto_image_prompt(title=title, content=content)
        image_bytes, mime_type, revised_prompt = generate_blog_image(
            image_prompt,
            user_id=user_id,
        )
        storage_path = build_storage_path(blog_id, "auto_generated", mime_type)
        upload_image_to_storage(storage_path, image_bytes, mime_type)

        has_manual_primary = (
            db.query(BlogImage)
            .filter(
                BlogImage.blog_id == blog_id,
                BlogImage.source == "manual_upload",
                BlogImage.is_primary == True,
            )
            .first()
            is not None
        )
        is_primary = not has_manual_primary

        image_id = str(uuid.uuid4())
        now = utc_now_iso()
        if is_primary:
            db.query(BlogImage).filter(
                BlogImage.blog_id == blog_id,
                BlogImage.is_primary == True,
            ).update({"is_primary": False, "updated_at": now})

        new_image = BlogImage(
            id=image_id,
            blog_id=blog_id,
            source="auto_generated",
            storage_path=storage_path,
            mime_type=mime_type,
            file_size_bytes=len(image_bytes),
            width=None,
            height=None,
            is_primary=is_primary,
            generation_prompt=(revised_prompt or image_prompt),
            created_by=blog.created_by,
            created_at=now,
            updated_at=now,
        )
        db.add(new_image)
        db.commit()

        if image_job_id:
            _set_image_generation_job_status(
                image_job_id,
                status="completed",
                error=None,
            )
        logger.info("Successfully generated image for blog %s", blog_id)
    except Exception as exc:
        if image_job_id:
            retries = int(getattr(self.request, "retries", 0) or 0)
            max_retries = int(getattr(self, "max_retries", 0) or 0)
            will_retry = retries < max_retries
            try:
                current_job = db.query(Job).filter(Job.id == image_job_id).first()
                if not current_job or str(current_job.status or "").lower() != "canceled":
                    _set_image_generation_job_status(
                        image_job_id,
                        status="pending" if will_retry else "failed",
                        error=str(exc),
                    )
            except Exception as status_exc:
                logger.warning(
                    "Kon image generatie job status niet updaten voor job %s: %s",
                    image_job_id,
                    status_exc,
                )
        logger.error("Failed to generate image for blog %s: %s", blog_id, exc)
        raise
    finally:
        db.close()
