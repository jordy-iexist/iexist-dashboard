import uuid
from datetime import datetime, timezone

from celery.utils.log import get_task_logger

from app.core.config import settings
from app.db.models import CustomerWebsite, SerpScan, SerpScanResult, WebsiteKeyword
from app.db.session import SessionLocal
from app.features.seo_tracker.services import (
    apply_scan_limit,
    build_scan_canceled_error_message,
    find_first_domain_match,
    is_scan_canceled_error_message,
    search_google_nl_desktop,
)
from app.worker._common import utc_now_iso
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)
CANCELED_SCAN_ERROR_MESSAGE = build_scan_canceled_error_message()


def _mark_scan_canceled(
    scan_id: str,
    *,
    processed_keywords: int,
    failed_keywords: int,
) -> None:
    db = SessionLocal()
    try:
        scan = db.query(SerpScan).filter(SerpScan.id == scan_id).first()
        if not scan:
            return
        scan.processed_keywords = processed_keywords
        scan.failed_keywords = failed_keywords
        scan.error_message = CANCELED_SCAN_ERROR_MESSAGE
        scan.updated_at = datetime.now(timezone.utc)  # type: ignore[assignment]
        try:
            scan.status = "canceled"
            db.commit()
            return
        except Exception as exc:
            logger.warning(
                "Kon scan %s niet als canceled opslaan (%s). Fallback naar failed.",
                scan_id,
                exc,
            )
            db.rollback()
        scan.status = "failed"
        db.commit()
    finally:
        db.close()


@celery_app.task(bind=True, name="app.worker.tasks.scan_website_keywords_task")
def scan_website_keywords_task(self, scan_id: str):
    """Run one manual SERP scan for a website and store keyword positions."""
    processed_keywords = 0
    failed_keywords = 0
    first_failure_reason: str | None = None

    def _current_scan_status() -> str:
        _db = SessionLocal()
        try:
            row = _db.query(SerpScan).filter(SerpScan.id == scan_id).first()
            if not row:
                return "deleted"
            if is_scan_canceled_error_message(row.error_message):
                return "canceled"
            return str(row.status or "").strip().lower()
        except Exception:
            return ""
        finally:
            _db.close()

    db = SessionLocal()
    try:
        scan = db.query(SerpScan).filter(SerpScan.id == scan_id).first()
        if not scan:
            logger.info("SEO scan %s niet gevonden (mogelijk al verwijderd).", scan_id)
            return
        if str(scan.status or "").strip().lower() == "canceled":
            logger.info(
                "SEO scan %s is al geannuleerd voordat worker startte.", scan_id
            )
            return

        website_id = str(scan.website_id or "").strip()
        if not website_id:
            raise ValueError("Website id ontbreekt voor scan.")

        website = (
            db.query(CustomerWebsite).filter(CustomerWebsite.id == website_id).first()
        )
        if not website:
            raise ValueError("Website niet gevonden.")

        domain = str(website.domain or "").strip().lower()
        if not domain:
            raise ValueError("Website domein ontbreekt.")

        all_keywords = (
            db.query(WebsiteKeyword)
            .filter(
                WebsiteKeyword.website_id == website_id,
                WebsiteKeyword.is_active == True,
            )
            .order_by(WebsiteKeyword.created_at.asc())
            .all()
        )
        # Convert to dicts for apply_scan_limit compatibility
        all_keywords_dicts = [
            {c.key: getattr(kw, c.key) for c in kw.__table__.columns}
            for kw in all_keywords
        ]
        total_keywords = len(all_keywords_dicts)

        max_requests_per_scan = int(
            scan.max_requests_per_scan or settings.serpapi_max_requests_per_scan
        )
        keywords_to_scan, skipped_due_to_limit, truncated_by_limit = apply_scan_limit(
            all_keywords_dicts,
            max_requests_per_scan,
        )

        try:
            db.query(SerpScan).filter(
                SerpScan.id == scan_id,
                SerpScan.status != "canceled",
            ).update(
                {
                    "status": "processing",
                    "total_keywords": total_keywords,
                    "processed_keywords": 0,
                    "failed_keywords": 0,
                    "skipped_due_to_limit": skipped_due_to_limit,
                    "truncated_by_limit": truncated_by_limit,
                    "error_message": None,
                    "updated_at": utc_now_iso(),
                }
            )
            db.commit()
        except Exception:
            if _current_scan_status() in {"canceled", "deleted"}:
                logger.info(
                    "SEO scan %s is geannuleerd voordat verwerking begon.",
                    scan_id,
                )
                return
            raise

        if _current_scan_status() in {"canceled", "deleted"}:
            logger.info(
                "SEO scan %s is geannuleerd voordat verwerking begon.",
                scan_id,
            )
            return

        configured_serp_depth = int(settings.serpapi_results_depth)

        for keyword_row in keywords_to_scan:
            current_status = _current_scan_status()
            if current_status == "deleted":
                logger.info(
                    "SEO scan %s verwijderd tijdens verwerking; worker stopt.",
                    scan_id,
                )
                return
            if current_status == "canceled":
                _mark_scan_canceled(
                    scan_id,
                    processed_keywords=processed_keywords,
                    failed_keywords=failed_keywords,
                )
                logger.info(
                    "SEO scan %s geannuleerd na %s/%s keywords.",
                    scan_id,
                    processed_keywords,
                    total_keywords,
                )
                return

            keyword_id = str(keyword_row["id"])
            keyword = str(keyword_row.get("keyword", "") or "").strip()
            if not keyword:
                failed_keywords += 1
                if first_failure_reason is None:
                    first_failure_reason = "Keyword is leeg."
                result = SerpScanResult(
                    id=str(uuid.uuid4()),
                    scan_id=scan_id,
                    website_id=website_id,
                    keyword_id=keyword_id,
                    keyword="",
                    position=None,
                    result_url=None,
                    matched_host=None,
                    serp_checked_depth=configured_serp_depth,
                    error_message="Keyword is leeg.",
                    created_at=utc_now_iso(),
                )
                db.add(result)
                db.commit()
                processed_keywords += 1
                db.query(SerpScan).filter(SerpScan.id == scan_id).update(
                    {
                        "processed_keywords": processed_keywords,
                        "failed_keywords": failed_keywords,
                        "updated_at": utc_now_iso(),
                    }
                )
                db.commit()
                continue

            error_message: str | None = None
            position: int | None = None
            result_url: str | None = None
            matched_host: str | None = None
            serp_checked_depth = configured_serp_depth

            try:
                serp_payload = search_google_nl_desktop(
                    keyword,
                    target_domain=domain,
                )
                organic_results = serp_payload.get("organic_results")
                if isinstance(organic_results, list):
                    serp_checked_depth = max(
                        len([row for row in organic_results if isinstance(row, dict)]),
                        1,
                    )
                match = find_first_domain_match(serp_payload, domain)
                position = match.position
                result_url = match.result_url
                matched_host = match.matched_host
            except Exception as exc:
                failed_keywords += 1
                error_message = str(exc)
                if first_failure_reason is None:
                    first_failure_reason = error_message

            result = SerpScanResult(
                id=str(uuid.uuid4()),
                scan_id=scan_id,
                website_id=website_id,
                keyword_id=keyword_id,
                keyword=keyword,
                position=position,
                result_url=result_url,
                matched_host=matched_host,
                serp_checked_depth=serp_checked_depth,
                error_message=error_message,
                created_at=utc_now_iso(),
            )
            db.add(result)
            db.commit()

            processed_keywords += 1
            db.query(SerpScan).filter(SerpScan.id == scan_id).update(
                {
                    "processed_keywords": processed_keywords,
                    "failed_keywords": failed_keywords,
                    "updated_at": utc_now_iso(),
                }
            )
            db.commit()

        current_status = _current_scan_status()
        if current_status in {"canceled", "deleted"}:
            logger.info(
                "SEO scan %s bleef geannuleerd en is niet naar completed gezet.",
                scan_id,
            )
            return
        final_status = "completed" if failed_keywords == 0 else "failed"
        final_error_message = None
        if failed_keywords > 0:
            detail_suffix = (
                f" Eerste fout: {first_failure_reason}" if first_failure_reason else ""
            )
            final_error_message = (
                f"Scan afgerond met fouten: {failed_keywords}/{processed_keywords} "
                f"keyword(s) zonder geldige SerpApi response.{detail_suffix}"
            )
        db.query(SerpScan).filter(SerpScan.id == scan_id).update(
            {
                "status": final_status,
                "processed_keywords": processed_keywords,
                "failed_keywords": failed_keywords,
                "error_message": final_error_message,
                "updated_at": utc_now_iso(),
            }
        )
        db.commit()
        if final_status == "completed":
            logger.info("Successfully processed SEO scan %s", scan_id)
        else:
            logger.warning(
                "SEO scan %s afgerond met fouten: %s failed keyword(s).",
                scan_id,
                failed_keywords,
            )
    except Exception as exc:
        current_status = _current_scan_status()
        if current_status == "deleted":
            logger.info("SEO scan %s verwijderd tijdens verwerking.", scan_id)
            return
        if current_status == "canceled":
            _mark_scan_canceled(
                scan_id,
                processed_keywords=processed_keywords,
                failed_keywords=failed_keywords,
            )
            logger.info("SEO scan %s geannuleerd tijdens verwerking.", scan_id)
            return
        logger.error("Failed SEO scan %s: %s", scan_id, exc)
        try:
            db.query(SerpScan).filter(SerpScan.id == scan_id).update(
                {
                    "status": "failed",
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
