import os

import markdown as md
from celery.utils.log import get_task_logger

from app.db.models import Blog, BlogImage, BlogPublication, CsvRow, Job, WordPressSite
from app.db.session import SessionLocal
from app.features.blogs.services.image_service import (
    ALLOWED_IMAGE_MIME_TYPES,
    download_image_from_storage,
)
from app.features.blogs.services.crypto_service import decrypt_secret
from app.features.blogs.services.wordpress_service import (
    WordPressServiceError,
    publish_post_to_wordpress,
    upload_media_to_wordpress,
)
from app.worker._common import build_excerpt, build_title, utc_now_iso
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


def _row_to_dict(obj):
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}


def _select_primary_blog_image(blog_id: str) -> dict | None:
    db = SessionLocal()
    try:
        image = (
            db.query(BlogImage)
            .filter(BlogImage.blog_id == blog_id, BlogImage.is_primary == True)
            .order_by(BlogImage.created_at.desc())
            .first()
        )
        if image:
            return _row_to_dict(image)
        image = (
            db.query(BlogImage)
            .filter(BlogImage.blog_id == blog_id)
            .order_by(BlogImage.created_at.desc())
            .first()
        )
        return _row_to_dict(image) if image else None
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="app.worker.tasks.publish_blog_to_wordpress_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 3},
)
def publish_blog_to_wordpress_task(self, publication_id: str):
    """Publish one generated blog to one WordPress site."""
    db = SessionLocal()
    try:
        publication = (
            db.query(BlogPublication)
            .filter(BlogPublication.id == publication_id)
            .first()
        )
        if not publication:
            raise ValueError(f"Publicatie {publication_id} niet gevonden.")

        publication.status = "processing"
        publication.error_code = None
        publication.error_message = None
        publication.updated_at = utc_now_iso()
        db.commit()

        site = (
            db.query(WordPressSite)
            .filter(WordPressSite.id == publication.wordpress_site_id)
            .first()
        )
        if not site:
            raise ValueError("WordPress site niet gevonden.")
        if not site.is_active:
            raise ValueError("WordPress site is gedeactiveerd.")

        blog = db.query(Blog).filter(Blog.id == publication.blog_id).first()
        if not blog:
            raise ValueError("Blog niet gevonden.")

        job = (
            db.query(Job).filter(Job.id == blog.job_id).first() if blog.job_id else None
        )
        csv_row = (
            db.query(CsvRow).filter(CsvRow.id == job.row_id).first()
            if job and job.row_id
            else None
        )
        row_data = csv_row.data if csv_row and isinstance(csv_row.data, dict) else {}

        content = str(blog.content or "").strip()
        if not content:
            raise ValueError("Blog inhoud is leeg.")

        html_content = md.markdown(content, extensions=["extra"])
        title = build_title(row_data)
        excerpt = build_excerpt(content)
        wp_password = decrypt_secret(str(site.app_password_encrypted or ""))
        featured_media_id: str | None = None
        selected_blog_image_id: str | None = None
        warning_code: str | None = None
        warning_message: str | None = None

        image_record = _select_primary_blog_image(str(blog.id))
        if image_record:
            selected_blog_image_id = str(image_record["id"])
            storage_path = str(image_record.get("storage_path", "") or "").strip()
            mime_type = str(image_record.get("mime_type", "") or "").strip()
            filename = (
                os.path.basename(storage_path)
                or f"blog-image{ALLOWED_IMAGE_MIME_TYPES.get(mime_type, '.png')}"
            )

            try:
                image_bytes = download_image_from_storage(storage_path)
                media_result = upload_media_to_wordpress(
                    base_url=str(site.base_url),
                    username=str(site.wp_login),
                    app_password=wp_password,
                    filename=filename,
                    content=image_bytes,
                    mime_type=mime_type if mime_type else "image/png",
                )
                featured_media_id = media_result.media_id
            except Exception as media_exc:
                warning_code = (
                    media_exc.code
                    if isinstance(media_exc, WordPressServiceError)
                    else "media_upload_failed"
                )
                warning_message = (
                    f"Featured image kon niet worden toegevoegd: {media_exc}"
                )
        else:
            warning_code = "missing_featured_image"
            warning_message = "Geen afbeelding beschikbaar; post is zonder uitgelichte afbeelding gepubliceerd."

        publish_result = publish_post_to_wordpress(
            base_url=str(site.base_url),
            username=str(site.wp_login),
            app_password=wp_password,
            title=title,
            content=html_content,
            excerpt=excerpt,
            post_status=str(publication.wp_status or "draft"),
            featured_media=featured_media_id,
        )

        publication.status = "succeeded"
        publication.wp_post_id = publish_result.post_id
        publication.wp_post_url = publish_result.post_url
        publication.wp_media_id = featured_media_id
        publication.blog_image_id = selected_blog_image_id
        publication.error_code = None
        publication.error_message = None
        publication.warning_code = warning_code
        publication.warning_message = warning_message
        publication.updated_at = utc_now_iso()
        if not blog.published_at:
            blog.published_at = utc_now_iso()
        db.commit()

        logger.info("Successfully published publication %s", publication_id)
    except Exception as exc:
        logger.error("Failed publication %s: %s", publication_id, exc)
        error_code = (
            exc.code if isinstance(exc, WordPressServiceError) else "publish_failed"
        )
        try:
            db.rollback()
            pub_err = (
                db.query(BlogPublication)
                .filter(BlogPublication.id == publication_id)
                .first()
            )
            if pub_err:
                pub_err.status = "failed"
                pub_err.error_code = error_code
                pub_err.error_message = str(exc)[:2000]
                pub_err.warning_code = None
                pub_err.warning_message = None
                pub_err.updated_at = utc_now_iso()
                db.commit()
        except Exception as status_exc:
            logger.error(
                "Kon publicatiestatus niet bijwerken voor %s na fout: %s",
                publication_id,
                status_exc,
            )
        raise
    finally:
        db.close()
