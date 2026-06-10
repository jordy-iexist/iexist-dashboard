from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_

from app.core.dependencies import get_request_user_id
from app.db.models import Blog, BlogPublication, WordPressSite
from app.db.session import SessionLocal
from app.features.blogs.mappers import to_publication_item
from app.features.blogs.schemas import PublicationItem


def _row_to_dict(obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}  # type: ignore[union-attr]


def dedupe_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def ensure_active_sites(site_ids: list[str]) -> dict[str, dict]:
    with SessionLocal() as db:
        query = db.query(WordPressSite).filter(WordPressSite.id.in_(site_ids))
        user_id = get_request_user_id()
        if user_id:
            query = query.filter(WordPressSite.created_by == user_id)
        site_rows = [_row_to_dict(row) for row in query.all()]

    sites_by_id = {str(site["id"]): site for site in site_rows}

    missing_site_ids = [site_id for site_id in site_ids if site_id not in sites_by_id]
    if missing_site_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Onbekende WordPress site ids: {', '.join(missing_site_ids)}",
        )

    inactive_site_ids = [
        site_id
        for site_id, site in sites_by_id.items()
        if not bool(site.get("is_active", True))
    ]
    if inactive_site_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Geselecteerde WordPress sites zijn gedeactiveerd: {', '.join(inactive_site_ids)}",
        )

    return sites_by_id


def ensure_blogs_exist(blog_ids: list[str], user_id: str | None = None) -> None:
    user_id = user_id or get_request_user_id()
    with SessionLocal() as db:
        query = db.query(Blog).filter(Blog.id.in_(blog_ids))
        if user_id:
            query = query.filter(Blog.created_by == user_id)
        blog_rows = [_row_to_dict(row) for row in query.all()]

    found_ids = {str(blog["id"]) for blog in blog_rows}
    missing_ids = [blog_id for blog_id in blog_ids if blog_id not in found_ids]
    if missing_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Onbekende blog ids: {', '.join(missing_ids)}",
        )


def ensure_blog_exists(blog_id: str, user_id: str | None = None) -> None:
    """Eigenaarscheck: 404 wanneer de blog niet bestaat of niet van de gebruiker is."""
    user_id = user_id or get_request_user_id()
    with SessionLocal() as db:
        query = db.query(Blog).filter(Blog.id == blog_id)
        if user_id:
            query = query.filter(Blog.created_by == user_id)
        blog = query.first()

    if not blog:
        raise HTTPException(status_code=404, detail="Blog niet gevonden.")


def ensure_blog_readable(blog_id: str, user_id: str | None = None) -> None:
    """Leescheck: eigenaar óf blog die via is_public met het team gedeeld is."""
    user_id = user_id or get_request_user_id()
    with SessionLocal() as db:
        query = db.query(Blog).filter(Blog.id == blog_id)
        if user_id:
            query = query.filter(
                or_(Blog.created_by == user_id, Blog.is_public.is_(True))
            )
        blog = query.first()

    if not blog:
        raise HTTPException(status_code=404, detail="Blog niet gevonden.")


def fetch_publication_items(publication_ids: list[str]) -> list[PublicationItem]:
    if not publication_ids:
        return []

    with SessionLocal() as db:
        query = db.query(BlogPublication).filter(
            BlogPublication.id.in_(publication_ids)
        )
        user_id = get_request_user_id()
        if user_id:
            query = query.filter(BlogPublication.requested_by == user_id)
        raw_publications = [_row_to_dict(row) for row in query.all()]

    by_id = {str(publication["id"]): publication for publication in raw_publications}
    ordered = [
        by_id[publication_id]
        for publication_id in publication_ids
        if publication_id in by_id
    ]
    return [to_publication_item(publication) for publication in ordered]
