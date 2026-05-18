import asyncio
import uuid
from urllib.parse import urlparse

from celery.utils.log import get_task_logger

from app.db.models import AuditIssue, AuditPage, WebsiteAudit
from app.db.session import SessionLocal
from app.features.website_audit.services.analyzer import analyze_page
from app.features.website_audit.services.reporter import generate_audit_summary, generate_cross_page_issues
from app.services.crawler import crawl_website_pages
from app.storage import storage_client
from app.worker._common import utc_now_iso
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


def _normalize_path(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower() or url


def _current_audit_status(audit_id: str) -> str:
    db = SessionLocal()
    try:
        row = db.query(WebsiteAudit).filter(WebsiteAudit.id == audit_id).first()
        if not row:
            return "deleted"
        return str(row.status or "").strip().lower()
    finally:
        db.close()


@celery_app.task(bind=True, name="app.worker.tasks.run_website_audit_task")
def run_website_audit_task(self, audit_id: str) -> None:
    """Crawl a website and analyse each page using Playwright."""
    scanned_pages = 0
    failed_pages = 0

    db = SessionLocal()
    try:
        audit = db.query(WebsiteAudit).filter(WebsiteAudit.id == audit_id).first()
        if not audit:
            logger.info("Audit %s niet gevonden.", audit_id)
            return

        if str(audit.status or "").strip().lower() == "canceled":
            logger.info("Audit %s is al geannuleerd.", audit_id)
            return

        url = str(audit.url or "").strip()
        max_pages = int(audit.max_pages or 50)

        # Phase 1: crawling
        db.query(WebsiteAudit).filter(
            WebsiteAudit.id == audit_id,
            WebsiteAudit.status == "pending",
        ).update({"status": "crawling", "updated_at": utc_now_iso()})
        db.commit()

        if _current_audit_status(audit_id) in {"canceled", "deleted"}:
            return

        try:
            crawl_result = crawl_website_pages(
                base_url=url,
                max_pages=max_pages,
                timeout_seconds=15.0,
                crawl_max_depth=2,
                crawl_max_pages=300,
            )
        except Exception as crawl_err:
            raise ValueError(f"Crawlen mislukt: {crawl_err}") from crawl_err

        page_urls = crawl_result.urls
        total_pages = len(page_urls)

        db.query(WebsiteAudit).filter(WebsiteAudit.id == audit_id).update(
            {
                "total_pages": total_pages,
                "crawl_source": crawl_result.source,
                "status": "scanning",
                "updated_at": utc_now_iso(),
            }
        )
        db.commit()

        # Phase 2: scanning each page
        pages_analysis_data: list[dict] = []

        for page_url in page_urls:
            current_status = _current_audit_status(audit_id)
            if current_status in {"canceled", "deleted"}:
                logger.info("Audit %s vroegtijdig gestopt (%s).", audit_id, current_status)
                return

            page_id = str(uuid.uuid4())
            page_path = _normalize_path(page_url)
            now = utc_now_iso()

            # Insert page record as "scanning"
            new_page = AuditPage(
                id=page_id,
                audit_id=audit_id,
                url=page_url,
                path=page_path,
                status="scanning",
                issue_count=0,
                created_at=now,
                updated_at=now,
            )
            try:
                db.add(new_page)
                db.commit()
            except Exception:
                db.rollback()
                failed_pages += 1
                scanned_pages += 1
                continue

            # Run Playwright analysis
            try:
                analysis = asyncio.run(analyze_page(page_url))
                page_error = analysis.error
            except Exception as exc:
                page_error = str(exc)[:500]
                analysis = None

            page_issues = analysis.issues if analysis else []
            issue_count = len(page_issues)

            # Store screenshots if available
            screenshot_urls: dict[str, str] = {}
            if analysis and analysis.screenshots:
                bucket = storage_client.from_("audit-screenshots")
                for viewport_name, img_bytes in analysis.screenshots.items():
                    path = f"{audit_id}/{page_id}/{viewport_name}.jpg"
                    try:
                        bucket.upload(path, img_bytes)
                        signed = bucket.create_signed_url(path, 7 * 24 * 3600)
                        screenshot_urls[viewport_name] = signed["signedURL"]
                    except Exception:
                        pass

            # Update page with results
            update_vals = {
                "status": "failed" if page_error else "completed",
                "issue_count": issue_count,
                "error_message": page_error,
                "updated_at": utc_now_iso(),
            }
            if analysis:
                update_vals.update({
                    "typography_data": analysis.typography_data,
                    "performance_data": analysis.performance_data,
                    "accessibility_data": analysis.accessibility_data,
                    "console_errors": analysis.console_errors,
                    "meta_data": analysis.meta_data,
                    "links_data": analysis.links_data,
                    "responsive_data": analysis.responsive_data,
                    "screenshots": screenshot_urls if screenshot_urls else None,
                })

            db.query(AuditPage).filter(AuditPage.id == page_id).update(update_vals)
            db.commit()

            # Insert issues
            for issue_data in page_issues:
                try:
                    issue = AuditIssue(
                        id=str(uuid.uuid4()),
                        audit_id=audit_id,
                        page_id=page_id,
                        category=issue_data.get("category", "functionality"),
                        severity=issue_data.get("severity", "info"),
                        title=str(issue_data.get("title") or "")[:500],
                        description=str(issue_data.get("description") or ""),
                        selector=str(issue_data["selector"])[:500] if issue_data.get("selector") else None,
                        page_url=page_url,
                        issue_metadata=issue_data.get("issue_metadata"),
                        created_at=utc_now_iso(),
                    )
                    db.add(issue)
                except Exception:
                    pass
            try:
                db.commit()
            except Exception:
                db.rollback()

            if page_error:
                failed_pages += 1
            scanned_pages += 1

            # Track data for cross-page summary
            page_summary_entry = {
                "url": page_url,
                "issues": page_issues,
                "typography_data": analysis.typography_data if analysis else {},
                "meta_data": analysis.meta_data if analysis else {},
            }
            pages_analysis_data.append(page_summary_entry)

            db.query(WebsiteAudit).filter(WebsiteAudit.id == audit_id).update(
                {
                    "scanned_pages": scanned_pages,
                    "failed_pages": failed_pages,
                    "updated_at": utc_now_iso(),
                }
            )
            db.commit()

        # Phase 3: cross-page issues + summary
        final_status = _current_audit_status(audit_id)
        if final_status in {"canceled", "deleted"}:
            return

        cross_page_issues = generate_cross_page_issues(pages_analysis_data)
        for issue_data in cross_page_issues:
            try:
                issue = AuditIssue(
                    id=str(uuid.uuid4()),
                    audit_id=audit_id,
                    page_id=None,
                    category=issue_data.get("category", "typography"),
                    severity=issue_data.get("severity", "info"),
                    title=str(issue_data.get("title") or "")[:500],
                    description=str(issue_data.get("description") or ""),
                    selector=None,
                    page_url=issue_data.get("page_url"),
                    issue_metadata=issue_data.get("issue_metadata"),
                    created_at=utc_now_iso(),
                )
                db.add(issue)
            except Exception:
                pass
        try:
            db.commit()
        except Exception:
            db.rollback()

        summary = generate_audit_summary(pages_analysis_data)

        # Add cross-page issues to summary totals and recompute score
        for issue_data in cross_page_issues:
            sev = issue_data.get("severity", "info")
            cat = issue_data.get("category", "typography")
            summary["total_issues"] += 1
            if sev == "critical":
                summary["critical"] += 1
            elif sev == "warning":
                summary["warnings"] += 1
            else:
                summary["info"] += 1
            summary["categories"][cat] = summary["categories"].get(cat, 0) + 1

        score = 100
        score -= summary["critical"] * 10
        score -= summary["warnings"] * 3
        score -= summary["info"] * 1
        summary["score"] = max(0, min(100, score))

        db.query(WebsiteAudit).filter(WebsiteAudit.id == audit_id).update(
            {
                "status": "completed",
                "scanned_pages": scanned_pages,
                "failed_pages": failed_pages,
                "summary": summary,
                "updated_at": utc_now_iso(),
            }
        )
        db.commit()
        logger.info("Audit %s succesvol afgerond (%d pagina's).", audit_id, scanned_pages)

    except Exception as exc:
        logger.error("Audit %s mislukt: %s", audit_id, exc)
        try:
            db.query(WebsiteAudit).filter(WebsiteAudit.id == audit_id).update(
                {
                    "status": "failed",
                    "scanned_pages": scanned_pages,
                    "failed_pages": failed_pages,
                    "error_message": str(exc)[:500],
                    "updated_at": utc_now_iso(),
                }
            )
            db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()
