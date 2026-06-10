import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from app.core.config import settings
from app.storage import storage_client

BlogImageSource = Literal["auto_generated", "manual_upload"]

ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _utc_date_path() -> str:
    return datetime.now(timezone.utc).strftime("%Y/%m/%d")


def detect_mime_type(filename: str, content_type: str | None) -> str:
    normalized = (content_type or "").strip().lower()
    if normalized in ALLOWED_IMAGE_MIME_TYPES:
        return normalized

    suffix = os.path.splitext(filename.lower())[1]
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"

    raise ValueError("Alleen JPG, PNG of WEBP afbeeldingen zijn toegestaan.")


def _matches_magic_bytes(mime_type: str, content: bytes) -> bool:
    if mime_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/webp":
        return content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return False


def validate_image_upload(
    filename: str, content_type: str | None, content: bytes
) -> str:
    if not filename.strip():
        raise ValueError("Bestandsnaam ontbreekt.")
    if not content:
        raise ValueError("Afbeelding is leeg.")

    size_bytes = len(content)
    if size_bytes > settings.blog_image_max_size_bytes:
        max_mb = settings.blog_image_max_size_bytes / (1024 * 1024)
        raise ValueError(f"Afbeelding is te groot. Maximaal {max_mb:.1f} MB.")

    mime_type = detect_mime_type(filename, content_type)
    if not _matches_magic_bytes(mime_type, content):
        raise ValueError("Bestandsinhoud is geen geldige JPG, PNG of WEBP afbeelding.")
    return mime_type


def build_storage_path(blog_id: str, source: BlogImageSource, mime_type: str) -> str:
    extension = ALLOWED_IMAGE_MIME_TYPES[mime_type]
    random_part = uuid.uuid4().hex
    return f"{blog_id}/{source}/{_utc_date_path()}/{random_part}{extension}"


def ensure_blog_images_bucket() -> None:
    bucket_id = settings.blog_images_bucket

    buckets = storage_client.list_buckets()
    bucket_ids: set[str] = set()
    for bucket in buckets:
        if isinstance(bucket, dict):
            raw_id = bucket.get("id") or bucket.get("name")
        else:
            raw_id = getattr(bucket, "id", None) or getattr(bucket, "name", None)

        normalized = str(raw_id or "").strip()
        if normalized:
            bucket_ids.add(normalized)

    if bucket_id in bucket_ids:
        return

    try:
        storage_client.create_bucket(
            bucket_id,
            options={
                "public": False,
                "file_size_limit": settings.blog_image_max_size_bytes,
                "allowed_mime_types": sorted(ALLOWED_IMAGE_MIME_TYPES.keys()),
            },
        )
    except Exception as exc:
        message = str(exc).lower()
        # Storage can return 400 if the bucket already exists; treat that as success.
        if "already exists" in message or "duplicate key value" in message:
            return
        raise


def upload_image_to_storage(path: str, content: bytes, mime_type: str) -> None:
    ensure_blog_images_bucket()
    storage_client.from_(settings.blog_images_bucket).upload(
        path,
        content,
        file_options={
            "content-type": mime_type,
            "upsert": "true",
        },
    )


def download_image_from_storage(path: str) -> bytes:
    ensure_blog_images_bucket()
    return storage_client.from_(settings.blog_images_bucket).download(path)


def create_signed_image_url(path: str) -> str:
    ensure_blog_images_bucket()
    response = storage_client.from_(settings.blog_images_bucket).create_signed_url(
        path,
        settings.blog_image_signed_url_ttl_seconds,
    )

    signed_path = response.get("signedURL") or response.get("signedUrl")
    if not isinstance(signed_path, str) or not signed_path.strip():
        raise ValueError("Kon geen signed URL maken voor afbeelding.")

    if signed_path.startswith("http://") or signed_path.startswith("https://"):
        return signed_path

    if signed_path.startswith("/"):
        return f"{settings.backend_public_url.rstrip('/')}{signed_path}"
    return f"{settings.backend_public_url.rstrip('/')}/{signed_path.lstrip('/')}"


def build_auto_image_prompt(title: str, content: str) -> str:
    normalized_title = title.strip() or "Zakelijke blog"
    normalized_content = " ".join(content.split())
    summary = normalized_content[:900].strip()

    return (
        "Maak een professionele, realistische header afbeelding zonder tekst of logo's. "
        "Stijl: modern, editorial, clean, hoge kwaliteit, neutrale kleuren. "
        f"Thema/titel: {normalized_title}. "
        f"Context uit de blog: {summary}"
    )
