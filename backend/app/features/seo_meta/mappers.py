from app.features.seo_meta.schemas import MetaPageItem, MetaRunItem


def _coerce_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        candidate = str(item or "").strip()
        if candidate:
            normalized.append(candidate)
    return normalized


def to_meta_run_item(record: dict) -> MetaRunItem:
    status = str(record.get("status") or "pending")
    if status not in {"pending", "processing", "completed", "failed", "canceled"}:
        status = "pending"

    return MetaRunItem(
        id=str(record["id"]),
        website_id=str(record["website_id"]),
        status=status,
        requested_by=str(record["requested_by"]),
        source=str(record.get("source") or "sitemap_first"),
        total_pages=int(record.get("total_pages") or 0),
        processed_pages=int(record.get("processed_pages") or 0),
        failed_pages=int(record.get("failed_pages") or 0),
        max_pages_per_run=int(record.get("max_pages_per_run") or 1),
        skipped_due_to_limit=int(record.get("skipped_due_to_limit") or 0),
        include_paths=_coerce_string_list(record.get("include_paths")),
        exclude_paths=_coerce_string_list(record.get("exclude_paths")),
        error_message=(
            str(record["error_message"])
            if record.get("error_message") not in {None, ""}
            else None
        ),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def to_meta_page_item(record: dict) -> MetaPageItem:
    review_status = str(record.get("review_status") or "pending_review")
    if review_status not in {"pending_review", "approved", "rejected"}:
        review_status = "pending_review"

    return MetaPageItem(
        id=str(record["id"]),
        run_id=str(record["run_id"]),
        website_id=str(record["website_id"]),
        url=str(record["url"]),
        path=str(record.get("path") or "/"),
        current_title=(
            str(record["current_title"])
            if record.get("current_title") not in {None, ""}
            else None
        ),
        current_description=(
            str(record["current_description"])
            if record.get("current_description") not in {None, ""}
            else None
        ),
        suggested_title=(
            str(record["suggested_title"])
            if record.get("suggested_title") not in {None, ""}
            else None
        ),
        suggested_description=(
            str(record["suggested_description"])
            if record.get("suggested_description") not in {None, ""}
            else None
        ),
        approved_title=(
            str(record["approved_title"])
            if record.get("approved_title") not in {None, ""}
            else None
        ),
        approved_description=(
            str(record["approved_description"])
            if record.get("approved_description") not in {None, ""}
            else None
        ),
        review_status=review_status,
        generation_error=(
            str(record["generation_error"])
            if record.get("generation_error") not in {None, ""}
            else None
        ),
        reviewed_by=(
            str(record["reviewed_by"])
            if record.get("reviewed_by") not in {None, ""}
            else None
        ),
        reviewed_at=record.get("reviewed_at"),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )
