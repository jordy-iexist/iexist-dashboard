import re
import uuid

from celery.utils.log import get_task_logger

from app.db.models import Job, LandingPage, LandingPageGenerationSettings, LandingPageRow, LandingPageUpload
from app.db.session import SessionLocal
from app.features.landing_pages.services.generation.csv import build_landing_page_prompt
from app.features.landing_pages.services.generation.openai import (
    DEFAULT_LANDING_PAGE_MAX_OUTPUT_TOKENS,
    DEFAULT_LANDING_PAGE_REASONING_EFFORT,
    LandingPageOutputValidationError,
    generate_landing_page,
    validate_landing_page_output,
)
from app.features.settings.services import MissingUserOpenAIKeyError
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


def _parse_requested_length(row_data: dict) -> int | None:
    raw_length = str(row_data.get("lengte", "") or "").strip()
    if not raw_length:
        return None
    match = re.search(r"\d[\d.,]*", raw_length)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(0))
    return int(digits) if digits else None


@celery_app.task(
    bind=True,
    name="app.worker.tasks.generate_landing_page_task",
    autoretry_for=(Exception,),
    dont_autoretry_for=(MissingUserOpenAIKeyError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 3},
)
def generate_landing_page_task(self, job_id: str):
    """Generate a landing page for a specific job."""
    upload_id = ""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} niet gevonden.")

        if str(job.status or "").lower() == "canceled":
            logger.info("Job %s was canceled before start, skipping.", job_id)
            return

        landing_page_row = (
            db.query(LandingPageRow)
            .filter(LandingPageRow.id == job.landing_page_row_id)
            .first()
            if job.landing_page_row_id
            else None
        )
        if not landing_page_row:
            raise ValueError(f"Landingspagina rij voor job {job_id} niet gevonden.")

        row_data = landing_page_row.data
        if not isinstance(row_data, dict):
            raise ValueError(f"Landingspagina data voor job {job_id} is ongeldig.")

        upload_id = str(landing_page_row.upload_id or "").strip()
        if not upload_id:
            raise ValueError(f"Upload id ontbreekt voor job {job_id}.")

        created_by = str(job.created_by or "").strip() or None
        if not created_by:
            upload = db.query(LandingPageUpload).filter(LandingPageUpload.id == upload_id).first()
            created_by = str(getattr(upload, "created_by", "") or "").strip() or None
        if not created_by:
            raise ValueError(f"Gebruiker ontbreekt voor landingspagina generatie job {job_id}.")

        job.status = "processing"
        db.commit()

        user_gen_settings: LandingPageGenerationSettings | None = (
            db.query(LandingPageGenerationSettings)
            .filter(LandingPageGenerationSettings.user_id == created_by)
            .first()
            if created_by
            else None
        )

        prompt = build_landing_page_prompt(row_data)
        effective_model = user_gen_settings.model if user_gen_settings else None
        effective_reasoning_effort = (
            user_gen_settings.reasoning_effort
            if user_gen_settings and user_gen_settings.reasoning_effort
            else DEFAULT_LANDING_PAGE_REASONING_EFFORT
        )
        effective_max_output_tokens = (
            user_gen_settings.max_output_tokens
            if user_gen_settings and user_gen_settings.max_output_tokens is not None
            else DEFAULT_LANDING_PAGE_MAX_OUTPUT_TOKENS
        )
        requested_length = _parse_requested_length(row_data)
        db.refresh(job)
        if str(job.status or "").lower() == "canceled":
            logger.info("Job %s was canceled before OpenAI call, skipping.", job_id)
            return
        logger.info(
            "Generating landing page for job %s with model=%s reasoning_effort=%s max_output_tokens=%s",
            job_id,
            effective_model or "default",
            effective_reasoning_effort,
            effective_max_output_tokens,
        )
        raw_content = generate_landing_page(
            prompt,
            user_id=created_by,
            system_prompt=user_gen_settings.system_prompt if user_gen_settings else None,
            model=effective_model,
            reasoning_effort=effective_reasoning_effort,
            max_output_tokens=effective_max_output_tokens,
        )
        try:
            meta_title, meta_description, slug, body_markdown = validate_landing_page_output(
                raw_content,
                requested_length=requested_length,
            )
        except LandingPageOutputValidationError as exc:
            logger.error(
                "Landing page validation failed for job %s: %s chars=%s words=%s",
                job_id,
                exc,
                len(raw_content),
                len(raw_content.split()),
            )
            raise
        logger.info(
            "Validated landing page output for job %s: chars=%s words=%s",
            job_id,
            len(raw_content),
            len(body_markdown.split()),
        )

        landing_page_id = str(uuid.uuid4())
        new_landing_page = LandingPage(
            id=landing_page_id,
            job_id=job_id,
            content=body_markdown,
            meta_title=meta_title,
            meta_description=meta_description,
            slug=slug,
            created_by=created_by,
        )
        db.add(new_landing_page)
        db.commit()

        job.status = "completed"
        db.commit()

        logger.info("Successfully generated landing page for job %s", job_id)
    except Exception as exc:
        logger.error("Failed to generate landing page for job %s: %s", job_id, exc)
        retries = int(getattr(self.request, "retries", 0) or 0)
        max_retries = int(getattr(self, "max_retries", 0) or 0)
        will_retry = retries < max_retries
        try:
            job_err = db.query(Job).filter(Job.id == job_id).first()
            if job_err and str(job_err.status or "").lower() != "canceled":
                job_err.status = "pending" if will_retry else "failed"
                job_err.error = str(exc)
                db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()
