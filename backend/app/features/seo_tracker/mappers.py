from app.features.seo_tracker.schemas import (
    CustomerWebsiteItem,
    SerpScanItem,
    WebsiteKeywordItem,
)
from app.features.seo_tracker.services import (
    is_scan_canceled_error_message,
    strip_scan_canceled_error_marker,
)


def to_customer_website_item(record: dict) -> CustomerWebsiteItem:
    return CustomerWebsiteItem(
        id=str(record["id"]),
        name=str(record["name"]),
        base_url=str(record["base_url"]),
        domain=str(record["domain"]),
        is_active=bool(record.get("is_active", True)),
        created_by=str(record["created_by"]),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def to_website_keyword_item(record: dict) -> WebsiteKeywordItem:
    return WebsiteKeywordItem(
        id=str(record["id"]),
        website_id=str(record["website_id"]),
        keyword=str(record["keyword"]),
        is_active=bool(record.get("is_active", True)),
        created_by=str(record["created_by"]),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def to_serp_scan_item(record: dict) -> SerpScanItem:
    status = str(record.get("status") or "pending")
    total_keywords = int(record.get("total_keywords") or 0)
    processed_keywords = int(record.get("processed_keywords") or 0)
    failed_keywords = int(record.get("failed_keywords") or 0)
    error_message = strip_scan_canceled_error_marker(record.get("error_message"))

    if status == "failed" and is_scan_canceled_error_message(record.get("error_message")):
        status = "canceled"
    if status not in {"pending", "processing", "completed", "failed", "canceled"}:
        status = "pending"

    return SerpScanItem(
        id=str(record["id"]),
        website_id=str(record["website_id"]),
        status=status,
        requested_by=str(record["requested_by"]),
        market=str(record.get("market") or "google_nl_desktop"),
        total_keywords=total_keywords,
        processed_keywords=processed_keywords,
        failed_keywords=failed_keywords,
        max_requests_per_scan=int(record.get("max_requests_per_scan") or 1),
        skipped_due_to_limit=int(record.get("skipped_due_to_limit") or 0),
        truncated_by_limit=bool(record.get("truncated_by_limit", False)),
        error_message=error_message,
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )
