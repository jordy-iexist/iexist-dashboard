from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import (
    Blog,
    CustomerWebsite,
    LandingPage,
    SerpScan,
    SerpScanResult,
    WebsiteKeyword,
    WebsiteMetaPage,
    WebsiteMetaRun,
)
from app.features.seo_tracker.services import to_root_domain

CUSTOMER_WEBSITE_META_FIELD = "__customer_website_id"


def build_customer_name_index(db: Session) -> dict[str, str]:
    rows = db.query(CustomerWebsite.name, CustomerWebsite.id).all()
    return {
        str(name or "").strip().lower(): website_id
        for name, website_id in rows
        if str(name or "").strip()
    }


def build_customer_domain_index(db: Session) -> dict[str, str]:
    rows = db.query(CustomerWebsite.domain, CustomerWebsite.id).all()
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


def delete_customer_website_cascade(db: Session, website_id: str) -> None:
    """Delete a customer website and every row that references it.

    Blogs and landing pages are only unlinked (their customer_website_id FK
    already has ondelete=SET NULL, but we do it explicitly here to keep the
    session consistent within this transaction). Everything else — keywords,
    SERP scans/results, meta runs/pages — is fully removed since it has no
    meaning without the customer. Does not commit; the caller owns the
    transaction.
    """
    scan_ids = [
        scan_id
        for (scan_id,) in db.query(SerpScan.id)
        .filter(SerpScan.website_id == website_id)
        .all()
    ]
    run_ids = [
        run_id
        for (run_id,) in db.query(WebsiteMetaRun.id)
        .filter(WebsiteMetaRun.website_id == website_id)
        .all()
    ]

    scan_result_filters = [SerpScanResult.website_id == website_id]
    if scan_ids:
        scan_result_filters.append(SerpScanResult.scan_id.in_(scan_ids))
    db.query(SerpScanResult).filter(or_(*scan_result_filters)).delete(
        synchronize_session=False
    )
    db.query(SerpScan).filter(SerpScan.website_id == website_id).delete(
        synchronize_session=False
    )
    db.query(WebsiteKeyword).filter(
        WebsiteKeyword.website_id == website_id
    ).delete(synchronize_session=False)

    meta_page_filters = [WebsiteMetaPage.website_id == website_id]
    if run_ids:
        meta_page_filters.append(WebsiteMetaPage.run_id.in_(run_ids))
    db.query(WebsiteMetaPage).filter(or_(*meta_page_filters)).delete(
        synchronize_session=False
    )
    db.query(WebsiteMetaRun).filter(
        WebsiteMetaRun.website_id == website_id
    ).delete(synchronize_session=False)

    db.query(Blog).filter(Blog.customer_website_id == website_id).update(
        {"customer_website_id": None}, synchronize_session=False
    )
    db.query(LandingPage).filter(
        LandingPage.customer_website_id == website_id
    ).update({"customer_website_id": None}, synchronize_session=False)

    db.query(CustomerWebsite).filter(CustomerWebsite.id == website_id).delete(
        synchronize_session=False
    )
