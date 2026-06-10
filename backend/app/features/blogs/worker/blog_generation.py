import uuid

from celery.utils.log import get_task_logger

from app.db.models import Blog, BlogGenerationSettings, CsvRow, CsvUpload, Job
from app.db.session import SessionLocal
from app.features.blogs.services.generation import (
    build_blog_prompt,
    generate_blog,
    normalize_prompt_template,
    should_generate_image_from_row_data,
)
from app.features.settings.services import MissingUserOpenAIKeyError
from app.worker._common import PermanentTaskError
from app.worker.celery_app import celery_app
from app.features.blogs.worker.image_generation import (
    _create_image_generation_job,
    _maybe_start_upload_image_jobs,
)

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.worker.tasks.generate_blog_task",
    autoretry_for=(Exception,),
    dont_autoretry_for=(MissingUserOpenAIKeyError, PermanentTaskError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 3},
)
def generate_blog_task(self, job_id: str):
    """Generate a blog for a specific job."""
    upload_id = ""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise PermanentTaskError(f"Job {job_id} niet gevonden.")

        if str(job.status or "").lower() == "canceled":
            logger.info("Job %s was canceled before start, skipping.", job_id)
            return

        csv_row = (
            db.query(CsvRow).filter(CsvRow.id == job.row_id).first()
            if job.row_id
            else None
        )
        if not csv_row:
            raise PermanentTaskError(f"CSV rij voor job {job_id} niet gevonden.")

        row_data = csv_row.data
        if not isinstance(row_data, dict):
            raise PermanentTaskError(f"CSV data voor job {job_id} is ongeldig.")

        upload_id = str(csv_row.upload_id or "").strip()
        if not upload_id:
            raise PermanentTaskError(f"Upload id ontbreekt voor job {job_id}.")

        upload = db.query(CsvUpload).filter(CsvUpload.id == upload_id).first()
        template = upload.template if upload else ""
        created_by = (
            str(job.created_by or "").strip()
            or str(getattr(upload, "created_by", "") or "").strip()
            or None
        )
        if not created_by:
            raise PermanentTaskError(f"Gebruiker ontbreekt voor blog generatie job {job_id}.")
        prompt_template = normalize_prompt_template(template)

        job.status = "processing"
        db.commit()

        user_gen_settings: BlogGenerationSettings | None = (
            db.query(BlogGenerationSettings)
            .filter(BlogGenerationSettings.user_id == created_by)
            .first()
            if created_by
            else None
        )

        prompt = build_blog_prompt(prompt_template, row_data)
        db.refresh(job)
        if str(job.status or "").lower() == "canceled":
            logger.info("Job %s was canceled before OpenAI call, skipping.", job_id)
            return
        content = generate_blog(
            prompt,
            user_id=created_by,
            system_prompt=user_gen_settings.system_prompt if user_gen_settings else None,
            model=user_gen_settings.model if user_gen_settings else None,
            reasoning_effort=user_gen_settings.reasoning_effort if user_gen_settings else None,
            max_output_tokens=user_gen_settings.max_output_tokens if user_gen_settings else None,
        )
        # Cancel kan tijdens de (lange) OpenAI-call binnengekomen zijn:
        # niets opslaan als de job inmiddels geannuleerd is.
        db.refresh(job)
        if str(job.status or "").lower() == "canceled":
            logger.info("Job %s was canceled during OpenAI call, discarding result.", job_id)
            return

        blog_id = str(uuid.uuid4())

        new_blog = Blog(
            id=blog_id, job_id=job_id, content=content, created_by=created_by
        )
        db.add(new_blog)
        db.commit()

        if should_generate_image_from_row_data(row_data, default_when_missing=False):
            try:
                _create_image_generation_job(blog_id)
            except Exception as queue_exc:
                logger.warning(
                    "Image generation job kon niet aangemaakt worden voor blog %s: %s",
                    blog_id,
                    queue_exc,
                )

        job.status = "completed"
        db.commit()
        _maybe_start_upload_image_jobs(upload_id)

        logger.info("Successfully generated blog for job %s", job_id)
    except Exception as exc:
        logger.error("Failed to generate blog for job %s: %s", job_id, exc)
        retries = int(getattr(self.request, "retries", 0) or 0)
        max_retries = int(getattr(self, "max_retries", 0) or 0)
        will_retry = retries < max_retries
        try:
            db.rollback()
            job_err = db.query(Job).filter(Job.id == job_id).first()
            if job_err and str(job_err.status or "").lower() != "canceled":
                job_err.status = "pending" if will_retry else "failed"
                job_err.error = str(exc)[:2000]
                db.commit()
        except Exception as status_exc:
            logger.error(
                "Kon jobstatus niet bijwerken voor job %s na fout: %s",
                job_id,
                status_exc,
            )
        if not will_retry:
            _maybe_start_upload_image_jobs(upload_id)
        raise
    finally:
        db.close()
