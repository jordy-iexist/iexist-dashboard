from app.features.blogs.schemas import BlogImageItem, PublicationItem, WordPressSiteItem
from app.features.blogs.services.image_service import create_signed_image_url


def to_wordpress_site_item(record: dict) -> WordPressSiteItem:
    return WordPressSiteItem(
        id=str(record["id"]),
        name=str(record["name"]),
        base_url=str(record["base_url"]),
        wp_login=str(record["wp_login"]),
        is_active=bool(record.get("is_active", True)),
        created_by=str(record["created_by"]),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def to_publication_item(record: dict) -> PublicationItem:
    status = str(record.get("status") or "pending")
    if status not in {"pending", "processing", "succeeded", "failed", "blocked_duplicate"}:
        status = "pending"
    wp_status = str(record.get("wp_status") or "draft")
    if wp_status not in {"draft", "publish"}:
        wp_status = "draft"

    return PublicationItem(
        id=str(record["id"]),
        blog_id=str(record["blog_id"]),
        wordpress_site_id=str(record["wordpress_site_id"]),
        status=status,
        requested_by=str(record["requested_by"]),
        wp_post_id=(
            str(record["wp_post_id"])
            if record.get("wp_post_id") not in {None, ""}
            else None
        ),
        wp_post_url=(
            str(record["wp_post_url"])
            if record.get("wp_post_url") not in {None, ""}
            else None
        ),
        wp_media_id=(
            str(record["wp_media_id"])
            if record.get("wp_media_id") not in {None, ""}
            else None
        ),
        blog_image_id=(
            str(record["blog_image_id"])
            if record.get("blog_image_id") not in {None, ""}
            else None
        ),
        wp_status=wp_status,
        error_code=(
            str(record["error_code"])
            if record.get("error_code") not in {None, ""}
            else None
        ),
        error_message=(
            str(record["error_message"])
            if record.get("error_message") not in {None, ""}
            else None
        ),
        warning_code=(
            str(record["warning_code"])
            if record.get("warning_code") not in {None, ""}
            else None
        ),
        warning_message=(
            str(record["warning_message"])
            if record.get("warning_message") not in {None, ""}
            else None
        ),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def to_blog_image_item(record: dict) -> BlogImageItem:
    signed_url: str | None
    try:
        signed_url = create_signed_image_url(str(record["storage_path"]))
    except Exception:
        signed_url = None

    source = str(record.get("source") or "manual_upload")
    if source not in {"auto_generated", "manual_upload"}:
        source = "manual_upload"

    return BlogImageItem(
        id=str(record["id"]),
        blog_id=str(record["blog_id"]),
        source=source,
        storage_path=str(record["storage_path"]),
        signed_url=signed_url,
        mime_type=str(record["mime_type"]),
        file_size_bytes=int(record.get("file_size_bytes") or 0),
        width=(
            int(record["width"])
            if isinstance(record.get("width"), int)
            else None
        ),
        height=(
            int(record["height"])
            if isinstance(record.get("height"), int)
            else None
        ),
        is_primary=bool(record.get("is_primary", False)),
        generation_prompt=(
            str(record["generation_prompt"])
            if record.get("generation_prompt") not in {None, ""}
            else None
        ),
        created_by=(
            str(record["created_by"])
            if record.get("created_by") not in {None, ""}
            else None
        ),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )
