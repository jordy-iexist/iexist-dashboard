from app.features.website_audit.schemas import (
    AuditCategory,
    AuditIssueItem,
    AuditItem,
    AuditPageItem,
    AuditSeverity,
    AuditStatus,
    AuditSummary,
)

_VALID_STATUSES = {"pending", "crawling", "scanning", "completed", "failed", "canceled"}
_VALID_SEVERITIES = {"critical", "warning", "info"}
_VALID_CATEGORIES = {
    "typography", "performance", "accessibility", "links",
    "responsive", "seo", "console_error", "functionality",
}


def to_audit_item(record: dict) -> AuditItem:
    status = str(record.get("status") or "pending")
    if status not in _VALID_STATUSES:
        status = "pending"

    summary_raw = record.get("summary")
    summary: AuditSummary | None = None
    if isinstance(summary_raw, dict):
        summary = AuditSummary(
            total_issues=int(summary_raw.get("total_issues") or 0),
            critical=int(summary_raw.get("critical") or 0),
            warnings=int(summary_raw.get("warnings") or 0),
            info=int(summary_raw.get("info") or 0),
            categories=dict(summary_raw.get("categories") or {}),
            score=int(summary_raw.get("score") or 100),
        )

    return AuditItem(
        id=str(record["id"]),
        url=str(record["url"]),
        domain=str(record["domain"]),
        status=status,  # type: ignore[arg-type]
        total_pages=int(record.get("total_pages") or 0),
        scanned_pages=int(record.get("scanned_pages") or 0),
        failed_pages=int(record.get("failed_pages") or 0),
        max_pages=int(record.get("max_pages") or 50),
        crawl_source=str(record["crawl_source"]) if record.get("crawl_source") else None,
        summary=summary,
        error_message=str(record["error_message"]) if record.get("error_message") else None,
        created_by=str(record["created_by"]),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def to_audit_page_item(record: dict) -> AuditPageItem:
    return AuditPageItem(
        id=str(record["id"]),
        audit_id=str(record["audit_id"]),
        url=str(record["url"]),
        path=str(record.get("path") or "/"),
        status=str(record.get("status") or "pending"),
        typography_data=record.get("typography_data"),
        performance_data=record.get("performance_data"),
        accessibility_data=record.get("accessibility_data"),
        console_errors=record.get("console_errors"),
        meta_data=record.get("meta_data"),
        links_data=record.get("links_data"),
        responsive_data=record.get("responsive_data"),
        screenshots=record.get("screenshots"),
        issue_count=int(record.get("issue_count") or 0),
        error_message=str(record["error_message"]) if record.get("error_message") else None,
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def to_audit_issue_item(record: dict) -> AuditIssueItem:
    category = str(record.get("category") or "functionality")
    if category not in _VALID_CATEGORIES:
        category = "functionality"

    severity = str(record.get("severity") or "info")
    if severity not in _VALID_SEVERITIES:
        severity = "info"

    return AuditIssueItem(
        id=str(record["id"]),
        audit_id=str(record["audit_id"]),
        page_id=str(record["page_id"]) if record.get("page_id") else None,
        category=category,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        title=str(record.get("title") or ""),
        description=str(record.get("description") or ""),
        selector=str(record["selector"]) if record.get("selector") else None,
        page_url=str(record["page_url"]) if record.get("page_url") else None,
        issue_metadata=record.get("issue_metadata"),
        created_at=record["created_at"],
    )
