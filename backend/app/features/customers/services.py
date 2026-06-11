from sqlalchemy.orm import Session

from app.db.models import CustomerWebsite
from app.features.seo_tracker.services import to_root_domain

CUSTOMER_WEBSITE_META_FIELD = "__customer_website_id"


def build_customer_name_index(db: Session) -> dict[str, str]:
    rows = (
        db.query(CustomerWebsite.name, CustomerWebsite.id)
        .filter(CustomerWebsite.is_active.is_(True))
        .all()
    )
    return {
        str(name or "").strip().lower(): website_id
        for name, website_id in rows
        if str(name or "").strip()
    }


def build_customer_domain_index(db: Session) -> dict[str, str]:
    rows = (
        db.query(CustomerWebsite.domain, CustomerWebsite.id)
        .filter(CustomerWebsite.is_active.is_(True))
        .all()
    )
    return {
        str(domain or "").strip().lower(): website_id
        for domain, website_id in rows
        if str(domain or "").strip()
    }


def match_customer_id_by_name(
    name_index: dict[str, str], raw_name: object
) -> str | None:
    name = str(raw_name or "").strip().lower()
    if not name:
        return None
    return name_index.get(name)


def match_customer_id_by_website(
    domain_index: dict[str, str], raw_website: object
) -> str | None:
    website = str(raw_website or "").strip()
    if not website:
        return None
    try:
        root_domain = to_root_domain(website)
    except ValueError:
        return None
    return domain_index.get(root_domain)


def resolve_customer_website_id(db: Session, raw_id: object) -> str | None:
    candidate = str(raw_id or "").strip()
    if not candidate:
        return None
    exists = (
        db.query(CustomerWebsite.id)
        .filter(CustomerWebsite.id == candidate)
        .first()
    )
    return candidate if exists else None
