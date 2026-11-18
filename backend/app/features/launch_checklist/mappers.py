from typing import Any

from pydantic import ValidationError

from app.features.launch_checklist.schemas import (
    ACTIVE_STATUSES,
    LaunchScanDetail,
    LaunchScanIssueItem,
    LaunchScanItem,
    LaunchScanPageItem,
    SitemapChangeItem,
    SitemapMonitorStatus,
)
from app.features.launch_checklist.services.geo_extract import all_types
from app.features.launch_checklist.services.issues import ISSUE_TYPES
from app.features.launch_checklist.services.sitemap_monitor import snapshot_summary


def row_to_dict(obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}


def to_scan_item(row: Any) -> LaunchScanItem:
    return LaunchScanItem.model_validate(row_to_dict(row))


def to_scan_detail(row: Any) -> LaunchScanDetail:
    return LaunchScanDetail.model_validate(row_to_dict(row))


def to_page_item(row: Any, issue_count: int = 0) -> LaunchScanPageItem:
    data = row_to_dict(row)
    jsonld = data.pop("jsonld", None)
    data.pop("signals", None)
    data.pop("outlinks", None)
    data["schema_all"] = sorted(all_types(jsonld)) if jsonld is not None else None
    return LaunchScanPageItem.model_validate({**data, "issue_count": issue_count})


def to_issue_item(row: Any) -> LaunchScanIssueItem:
    data = row_to_dict(row)
    # De prompttekst hoort niet in elke lijstrespons; alleen het tijdstip gaat mee.
    data.pop("fix_prompt", None)
    data["fix_prompt_at"] = getattr(row, "fix_prompt_at", None)
    data["issue_label"] = ISSUE_TYPES.get(row.issue_type, {}).get("label", row.issue_type)
    return LaunchScanIssueItem.model_validate(data)


# --- fase 3 ------------------------------------------------------------------

def to_suggestion_item(row: Any, page_url: str | None = None):
    from app.features.launch_checklist.schemas import ContentSuggestionItem
    from app.features.launch_checklist.services.content_checklist import ITEMS as CONTENT_ITEMS

    item = CONTENT_ITEMS.get(row.item_key)
    return ContentSuggestionItem(
        id=row.id,
        scan_id=row.scan_id,
        content_page_id=row.content_page_id,
        page_url=page_url,
        item_key=row.item_key,
        item_label=item.label if item else row.item_key,
        agent=row.agent,
        title=row.title,
        current_value=row.current_value,
        proposed_value=row.proposed_value,
        rationale=row.rationale,
        details=row.details,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def content_page_fields(row: Any, counts: tuple[int, int] = (0, 0)) -> dict[str, Any]:
    """Velden voor ContentPageItem; `counts` = (open voorstellen, alle voorstellen)."""
    return {
        "id": row.id,
        "url": row.url,
        "path": row.path,
        "page_type": row.page_type,
        "title": row.title,
        "meta_description": row.meta_description,
        "word_count": row.word_count,
        "problem_count": row.problem_count or 0,
        "checks": row.checks or {},
        "analysis_status": row.analysis_status,
        "analysis_error": row.analysis_error,
        "focus_keyword": row.focus_keyword,
        "intent": row.intent,
        "keyword_source": row.keyword_source,
        "ahrefs_keyword": (row.signals or {}).get("ahrefs") or None,
        "analyzed_at": row.analyzed_at,
        "suggestions_open": counts[0],
        "suggestions_total": counts[1],
    }


# --- sitemap-monitor ---------------------------------------------------------

def to_sitemap_monitor_status(
    customer: Any,
    snapshot: Any | None,
    scan: Any | None,
    *,
    open_issues: int,
    has_nulmeting: bool,
    global_enabled: bool,
) -> SitemapMonitorStatus:
    """Stand van de sitemap-monitor voor één klant; `snapshot` en `scan` mogen ontbreken."""
    entries = (snapshot.entries if snapshot is not None else None) or {}
    changes: list[SitemapChangeItem] = []
    for raw in (snapshot.recent_changes if snapshot is not None else None) or []:
        try:
            changes.append(SitemapChangeItem.model_validate(raw))
        except ValidationError:
            continue  # een beschadigde regel mag de rest niet blokkeren
    summary = snapshot_summary(entries if isinstance(entries, dict) else {})
    return SitemapMonitorStatus(
        customer_id=customer.id,
        enabled=bool(customer.sitemap_monitor_enabled),
        global_enabled=global_enabled,
        has_nulmeting=has_nulmeting,
        scan_id=scan.id if scan is not None else None,
        scan_status=scan.status if scan is not None else None,
        running=scan is not None and scan.status in ACTIVE_STATUSES,
        checked_at=snapshot.checked_at if snapshot is not None else None,
        changed_at=snapshot.changed_at if snapshot is not None else None,
        last_error=snapshot.last_error if snapshot is not None else None,
        total_urls=summary["total_urls"],
        has_lastmod=summary["has_lastmod"],
        recent_changes=changes,
        open_issues=open_issues,
    )
