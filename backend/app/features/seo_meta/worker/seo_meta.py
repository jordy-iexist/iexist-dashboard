import uuid

from celery.utils.log import get_task_logger

from app.core.config import settings
from app.db.models import CustomerWebsite, WebsiteMetaPage, WebsiteMetaRun
from app.db.session import SessionLocal
from app.features.seo_meta.services import (
    discover_website_pages,
    fetch_page_snapshot,
    generate_meta_suggestion,
)
from app.features.settings.services import MissingUserOpenAIKeyError
from app.worker._common import utc_now_iso
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.worker.tasks.run_website_meta_optimization_task",
    dont_autoretry_for=(MissingUserOpenAIKeyError,),
)
def run_website_meta_optimization_task(self, run_id: str):
    """Discover website pages and generate meta title/description suggestions."""
    processed_pages = 0
    failed_pages = 0

    def _current_run_status() -> str:
        _db = SessionLocal()
        try:
            row = _db.query(WebsiteMetaRun).filter(WebsiteMetaRun.id == run_id).first()
            if not row:
                return "deleted"
            return str(row.status or "").strip().lower()
        finally:
            _db.close()

    db = SessionLocal()
    try:
        run = db.query(WebsiteMetaRun).filter(WebsiteMetaRun.id == run_id).first()
        if not run:
            logger.info("Meta run %s niet gevonden.", run_id)
            return

        if str(run.status or "").strip().lower() == "canceled":
            logger.info("Meta run %s is al geannuleerd.", run_id)
            return

        website_id = str(run.website_id or "").strip()
        if not website_id:
            raise ValueError("Meta run mist website_id.")

        website = (
            db.query(CustomerWebsite).filter(CustomerWebsite.id == website_id).first()
        )
        if not website:
            raise ValueError("Website niet gevonden voor meta run.")
        if not bool(website.is_active):
            raise ValueError("Website is gedeactiveerd.")
        requested_by = str(run.requested_by or "").strip()
        if not requested_by:
            raise ValueError("Meta run mist gebruiker.")

        base_url = str(website.base_url or "").strip()
        if not base_url:
            raise ValueError("Website base_url ontbreekt.")

        max_pages_per_run = int(
            run.max_pages_per_run or settings.seo_meta_max_pages_per_run
        )
        if max_pages_per_run < 1:
            max_pages_per_run = settings.seo_meta_max_pages_per_run

        include_paths = run.include_paths
        exclude_paths = run.exclude_paths

        db.query(WebsiteMetaRun).filter(
            WebsiteMetaRun.id == run_id,
            WebsiteMetaRun.status == "pending",
        ).update(
            {
                "status": "processing",
                "processed_pages": 0,
                "failed_pages": 0,
                "error_message": None,
                "updated_at": utc_now_iso(),
            }
        )
        db.commit()

        if _current_run_status() == "deleted":
            return

        discovery = discover_website_pages(
            base_url=base_url,
            max_pages=max_pages_per_run,
            include_paths=include_paths if isinstance(include_paths, list) else [],
            exclude_paths=exclude_paths if isinstance(exclude_paths, list) else [],
            timeout_seconds=settings.seo_meta_http_timeout_seconds,
            crawl_max_depth=settings.seo_meta_crawl_max_depth,
            crawl_max_pages=settings.seo_meta_crawl_max_pages,
        )
        page_urls = discovery.urls
        total_pages = len(page_urls)

        db.query(WebsiteMetaRun).filter(WebsiteMetaRun.id == run_id).update(
            {
                "source": discovery.source,
                "total_pages": total_pages,
                "skipped_due_to_limit": discovery.skipped_due_to_limit,
                "updated_at": utc_now_iso(),
            }
        )
        db.commit()

        for page_url in page_urls:
            status = _current_run_status()
            if status in {"canceled", "deleted"}:
                logger.info("Meta run %s vroegtijdig gestopt (%s).", run_id, status)
                return

            generation_error: str | None = None
            current_title: str | None = None
            current_description: str | None = None
            suggested_title: str | None = None
            suggested_description: str | None = None
            page_path = "/"

            try:
                snapshot = fetch_page_snapshot(
                    page_url,
                    timeout_seconds=settings.seo_meta_http_timeout_seconds,
                )
                page_path = snapshot.path
                current_title = snapshot.title
                current_description = snapshot.description

                suggestion = generate_meta_suggestion(
                    user_id=requested_by,
                    model=settings.seo_meta_openai_model,
                    title_max_chars=settings.seo_meta_title_max_chars,
                    description_max_chars=settings.seo_meta_description_max_chars,
                    page_url=snapshot.url,
                    path=snapshot.path,
                    current_title=snapshot.title,
                    current_description=snapshot.description,
                    h1=snapshot.h1,
                    content_excerpt=snapshot.content_excerpt,
                )
                suggested_title = suggestion.title
                suggested_description = suggestion.description
            except Exception as exc:
                generation_error = str(exc)
                failed_pages += 1

            try:
                new_page = WebsiteMetaPage(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    website_id=website_id,
                    url=page_url,
                    path=page_path,
                    current_title=current_title,
                    current_description=current_description,
                    suggested_title=suggested_title,
                    suggested_description=suggested_description,
                    approved_title=None,
                    approved_description=None,
                    review_status="pending_review",
                    generation_error=generation_error,
                    reviewed_by=None,
                    reviewed_at=None,
                    created_at=utc_now_iso(),
                    updated_at=utc_now_iso(),
                )
                db.add(new_page)
                db.commit()
            except Exception as insert_exc:
                db.rollback()
                failed_pages += 1
                logger.warning(
                    "Meta page insert mislukt voor run %s (%s): %s",
                    run_id,
                    page_url,
                    insert_exc,
                )

            processed_pages += 1
            db.query(WebsiteMetaRun).filter(WebsiteMetaRun.id == run_id).update(
                {
                    "processed_pages": processed_pages,
                    "failed_pages": failed_pages,
                    "updated_at": utc_now_iso(),
                }
            )
            db.commit()

        final_status = _current_run_status()
        if final_status in {"canceled", "deleted"}:
            logger.info(
                "Meta run %s niet afgerond wegens status %s.", run_id, final_status
            )
            return

        db.query(WebsiteMetaRun).filter(WebsiteMetaRun.id == run_id).update(
            {
                "status": "completed",
                "processed_pages": processed_pages,
                "failed_pages": failed_pages,
                "updated_at": utc_now_iso(),
            }
        )
        db.commit()
        logger.info("Meta run %s succesvol afgerond.", run_id)
    except Exception as exc:
        logger.error("Meta run %s mislukt: %s", run_id, exc)
        try:
            db.query(WebsiteMetaRun).filter(WebsiteMetaRun.id == run_id).update(
                {
                    "status": "failed",
                    "processed_pages": processed_pages,
                    "failed_pages": failed_pages
                    if failed_pages > 0
                    else processed_pages,
                    "error_message": str(exc),
                    "updated_at": utc_now_iso(),
                }
            )
            db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()
