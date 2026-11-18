"""Klant (`CustomerWebsite`) en WordPress-koppeling (`WordPressSite`) bij elkaar zoeken.

Er is geen vaste relatie tussen beide tabellen; ze horen bij elkaar als de hostnaam gelijk is
(kleine letters, leidende `www.` genegeerd). Een ander subdomein telt niet als match.
"""
from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.db.models import CustomerWebsite, WordPressSite


def normalize_host(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    host = urlparse(raw).hostname or ""
    return host[4:] if host.startswith("www.") else host


def site_for_customer(db: Session, customer: CustomerWebsite | None, user_id: str) -> WordPressSite | None:
    """Actieve WordPress-koppeling van deze gebruiker met hetzelfde domein als de klant (www. genegeerd)."""
    if customer is None:
        return None
    hosts = {h for h in (normalize_host(customer.domain), normalize_host(customer.base_url)) if h}
    if not hosts:
        return None
    rows = (
        db.query(WordPressSite)
        .filter(WordPressSite.created_by == user_id, WordPressSite.is_active.is_(True))
        .order_by(WordPressSite.updated_at.desc())
        .all()
    )
    return next((row for row in rows if normalize_host(row.base_url) in hosts), None)


def match_customer_ids(
    sites: Iterable[tuple[str, str | None]],
    customers: Iterable[tuple[str, str | None, str | None]],
) -> dict[str, list[str]]:
    """Per site-id de klant-id's met dezelfde hostnaam.

    `sites` zijn `(id, base_url)`, `customers` zijn `(id, domain, base_url)`. Sites zonder match
    krijgen een lege lijst.
    """
    by_host: dict[str, list[str]] = {}
    for customer_id, domain, base_url in customers:
        for host in {normalize_host(domain), normalize_host(base_url)}:
            if not host:
                continue
            ids = by_host.setdefault(host, [])
            if str(customer_id) not in ids:
                ids.append(str(customer_id))
    result: dict[str, list[str]] = {}
    for site_id, base_url in sites:
        host = normalize_host(base_url)
        result[str(site_id)] = list(by_host.get(host, [])) if host else []
    return result


def customer_ids_by_site(db: Session, sites: Iterable[WordPressSite]) -> dict[str, list[str]]:
    """Klant-id's per WordPress-site (key = site-id). Klanten zijn niet per gebruiker afgeschermd."""
    customers = db.query(CustomerWebsite.id, CustomerWebsite.domain, CustomerWebsite.base_url).all()
    return match_customer_ids(((site.id, site.base_url) for site in sites), customers)
