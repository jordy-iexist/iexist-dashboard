"""Ahrefs-verrijking van de nulmeting: verkeer, backlinks en topzoekwoord per URL.

Eén snapshot per scan (vier API-calls, circa 7.000 units). Een herscan binnen
`AHREFS_SNAPSHOT_TTL_DAYS` neemt de data van de vorige scan over en kost niets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Protocol
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import LaunchScan, LaunchScanPage
from app.features.launch_checklist.services.discovery import is_internal, root_domain_of, url_key
from app.services.ahrefs import client as ahrefs
from app.services.ahrefs.client import AhrefsServiceError

MAX_EXTRA_URLS = 300
MAX_BROKEN_BACKLINKS_PER_PAGE = 10
# Na deze fouten hebben verdere calls geen zin.
_FATAL_CODES = {"not_configured", "unauthorized", "forbidden"}


class _Page(Protocol):
    """Zowel een `PageRecord` (tijdens de scan) als een `LaunchScanPage`-rij."""

    url: str
    final_url: str | None
    status_code: int | None
    redirect_chain: Any
    error: str | None
    org_traffic: int | None
    refdomains: int | None
    ahrefs: Any


@dataclass
class Snapshot:
    target: str
    country: str
    fetched_at: str
    reused_from: str | None = None
    units: int = 0
    domain: dict[str, Any] = field(default_factory=dict)
    # match_key -> {"url", "org_traffic", "refdomains", "keywords", "top_keyword", ...}
    pages: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def match_key(url: str) -> str:
    """`url_key` zonder `www.`: Ahrefs en de crawl schrijven de host niet altijd gelijk."""
    key = url_key(url)
    return key[4:] if key.startswith("www.") else key


def target_of(base_url: str) -> str:
    host = (urlparse(base_url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _entry(pages: dict[str, dict[str, Any]], url: str) -> dict[str, Any]:
    key = match_key(url)
    entry = pages.get(key)
    if entry is None:
        entry = pages[key] = {"url": url}
    elif url.startswith("https://") and not str(entry["url"]).startswith("https://"):
        entry["url"] = url
    return entry


def _add_top_pages(pages: dict[str, dict[str, Any]], rows: Iterable[dict[str, Any]], root: str) -> None:
    for row in rows:
        url = str(row.get("url") or "")
        if not url or not is_internal(url, root):
            continue
        traffic = _int(row.get("sum_traffic")) or 0
        entry = _entry(pages, url)
        # http- en https-varianten van dezelfde URL ranken apart: verkeer optellen,
        # het topzoekwoord komt van de variant met het meeste verkeer.
        if traffic >= (entry.get("_best_traffic") or -1):
            entry["_best_traffic"] = traffic
            entry["keywords"] = _int(row.get("keywords"))
            entry["top_keyword"] = str(row.get("top_keyword") or "").strip() or None
            entry["top_keyword_position"] = _int(row.get("top_keyword_best_position"))
            entry["top_keyword_volume"] = _int(row.get("top_keyword_volume"))
        entry["org_traffic"] = (entry.get("org_traffic") or 0) + traffic


def _add_backlink_pages(pages: dict[str, dict[str, Any]], rows: Iterable[dict[str, Any]], root: str) -> None:
    for row in rows:
        url = str(row.get("url_to") or "")
        if not url or not is_internal(url, root):
            continue
        entry = _entry(pages, url)
        entry["refdomains"] = max(entry.get("refdomains") or 0, _int(row.get("refdomains_target")) or 0)
        entry["dofollow_backlinks"] = max(
            entry.get("dofollow_backlinks") or 0, _int(row.get("dofollow_to_target")) or 0
        )


def _add_broken_backlinks(pages: dict[str, dict[str, Any]], rows: Iterable[dict[str, Any]], root: str) -> None:
    for row in rows:
        url = str(row.get("url_to") or "")
        if not url or not is_internal(url, root):
            continue
        entry = _entry(pages, url)
        links = entry.setdefault("broken_backlinks", [])
        if len(links) < MAX_BROKEN_BACKLINKS_PER_PAGE:
            links.append({
                "url_from": str(row.get("url_from") or ""),
                "dr": row.get("domain_rating_source"),
                "anchor": str(row.get("anchor") or "")[:120],
            })
        entry["_broken_domains"] = (entry.get("_broken_domains") or 0) + 1
    for entry in pages.values():
        # Eén rij per verwijzend domein: dat is de ondergrens voor het aantal domeinen.
        broken = entry.pop("_broken_domains", 0)
        if broken:
            entry["refdomains"] = max(entry.get("refdomains") or 0, broken)


def fetch_snapshot(base_url: str, *, client: httpx.Client | None = None) -> Snapshot:
    """Haal de Ahrefs-data van het domein op. Elke call faalt los van de andere."""
    snapshot = Snapshot(
        target=target_of(base_url),
        country=settings.ahrefs_country.strip().lower(),
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    root = root_domain_of(base_url) or snapshot.target
    country = snapshot.country or None

    def domain() -> None:
        result = ahrefs.domain_overview(snapshot.target, country=country, client=client)
        snapshot.units += result.units
        snapshot.domain = result.data

    def top() -> None:
        result = ahrefs.top_pages(
            snapshot.target, country=country, limit=settings.ahrefs_top_pages_limit, client=client
        )
        snapshot.units += result.units
        _add_top_pages(snapshot.pages, result.rows, root)

    def backlinks() -> None:
        result = ahrefs.pages_by_backlinks(
            snapshot.target, limit=settings.ahrefs_backlink_pages_limit, client=client
        )
        snapshot.units += result.units
        _add_backlink_pages(snapshot.pages, result.rows, root)

    def broken() -> None:
        result = ahrefs.broken_backlinks(
            snapshot.target, limit=settings.ahrefs_broken_backlinks_limit, client=client
        )
        snapshot.units += result.units
        _add_broken_backlinks(snapshot.pages, result.rows, root)

    calls = [
        ("domeincijfers", domain, True),
        ("verkeer per pagina", top, settings.ahrefs_top_pages_limit > 0),
        ("backlinks per pagina", backlinks, settings.ahrefs_backlink_pages_limit > 0),
        ("kapotte backlinks", broken, settings.ahrefs_broken_backlinks_limit > 0),
    ]
    for label, call, enabled in calls:
        if not enabled:
            continue
        try:
            call()
        except AhrefsServiceError as exc:
            snapshot.errors.append(f"{label} niet opgehaald: {exc}")
            if exc.code in _FATAL_CODES:
                break
    for entry in snapshot.pages.values():
        entry.pop("_best_traffic", None)
    return snapshot


def _page_entry(page: _Page) -> dict[str, Any]:
    data = dict(page.ahrefs or {})
    data.pop("source", None)
    return {"url": page.url, "org_traffic": page.org_traffic, "refdomains": page.refdomains, **data}


def reuse_snapshot(db: Session, scan: LaunchScan) -> Snapshot | None:
    """Recente, volledige snapshot van een eerdere nulmeting of fase 4-scan van dezelfde klant."""
    ttl_days = settings.ahrefs_snapshot_ttl_days
    if ttl_days <= 0:
        return None
    # Alleen de laatste voltooide scan met eigen pagina's (fase 1 of 4) telt: heeft
    # die geen bruikbare snapshot, dan halen we de data opnieuw op.
    previous = (
        db.query(LaunchScan)
        .filter(
            LaunchScan.customer_website_id == scan.customer_website_id,
            LaunchScan.phase.in_((1, 4)),
            LaunchScan.id != scan.id,
            LaunchScan.status == "completed",
        )
        .order_by(LaunchScan.created_at.desc())
        .first()
    )
    meta = previous.ahrefs if previous is not None else None
    if not isinstance(meta, dict) or meta.get("errors") or meta.get("target") != target_of(scan.base_url):
        return None
    try:
        fetched_at = datetime.fromisoformat(str(meta.get("fetched_at")))
    except ValueError:
        return None
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - fetched_at > timedelta(days=ttl_days):
        return None

    # Een lege JSON-kolom is JSON-null (geen SQL NULL), dus in Python filteren.
    rows = [
        row
        for row in db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == previous.id)
        if isinstance(row.ahrefs, dict)
    ]
    return Snapshot(
        target=str(meta.get("target")),
        country=str(meta.get("country") or ""),
        fetched_at=fetched_at.isoformat(),
        reused_from=previous.id,
        units=0,
        domain=dict(meta.get("domain") or {}),
        pages={match_key(row.url): _page_entry(row) for row in rows},
    )


def load_snapshot(db: Session, scan: LaunchScan, *, client: httpx.Client | None = None) -> Snapshot:
    return reuse_snapshot(db, scan) or fetch_snapshot(scan.base_url, client=client)


def _apply(page: _Page, entry: dict[str, Any], *, source: str) -> None:
    page.org_traffic = _int(entry.get("org_traffic"))
    page.refdomains = _int(entry.get("refdomains"))
    details = {k: v for k, v in entry.items() if k not in {"url", "org_traffic", "refdomains"} and v is not None}
    page.ahrefs = {"source": source, **details}


def has_value(page: _Page) -> bool:
    return (page.org_traffic or 0) > 0 or (page.refdomains or 0) > 0


def merge_into_records(records: list[Any], snapshot: Snapshot) -> list[str]:
    """Zet de Ahrefs-data op de gecrawlde pagina's.

    Geeft de URL's terug die Ahrefs kent (met verkeer of backlinks) maar die niet
    in de crawl zitten: die moeten apart worden opgehaald.
    """
    by_url: dict[str, Any] = {}
    by_final: dict[str, Any] = {}
    for rec in records:
        by_url.setdefault(match_key(rec.url), rec)
        if rec.final_url:
            by_final.setdefault(match_key(rec.final_url), rec)

    unknown: list[tuple[int, str]] = []
    for key, entry in snapshot.pages.items():
        # Een exacte URL gaat voor; anders de pagina die naar deze URL doorstuurt.
        rec = by_url.get(key) or by_final.get(key)
        if rec is not None:
            if rec.ahrefs is None:
                _apply(rec, entry, source="crawl")
            continue
        weight = (_int(entry.get("org_traffic")) or 0) + (_int(entry.get("refdomains")) or 0)
        if weight > 0:
            unknown.append((weight, str(entry["url"])))
    unknown.sort(key=lambda item: -item[0])
    return [url for _, url in unknown[:MAX_EXTRA_URLS]]


def mark_extra_records(extra: list[Any], snapshot: Snapshot) -> None:
    """Records van URL's die alleen Ahrefs kende."""
    for rec in extra:
        entry = snapshot.pages.get(match_key(rec.url))
        if entry is not None:
            _apply(rec, entry, source="ahrefs")


def _final_status(page: _Page) -> int | None:
    chain = page.redirect_chain or []
    if chain and isinstance(chain[-1], dict) and chain[-1].get("final"):
        return chain[-1].get("status")
    return page.status_code


def is_lost(page: _Page) -> bool:
    """Pagina met verkeer of backlinks die niet (meer) werkt."""
    if not has_value(page):
        return False
    status = _final_status(page)
    if status is None:
        return bool(page.error)
    return status >= 400 and status not in {401, 403, 429, 503}


def scan_summary(snapshot: Snapshot, records: list[Any]) -> dict[str, Any]:
    """Wat op de scan zelf wordt bewaard (`LaunchScan.ahrefs`)."""
    return {
        "target": snapshot.target,
        "country": snapshot.country,
        "fetched_at": snapshot.fetched_at,
        "reused_from": snapshot.reused_from,
        "units": snapshot.units,
        "domain": snapshot.domain,
        "errors": snapshot.errors,
        "pages_with_traffic": len([r for r in records if (r.org_traffic or 0) > 0]),
        "pages_with_backlinks": len([r for r in records if (r.refdomains or 0) > 0]),
        "extra_urls": len([r for r in records if (r.ahrefs or {}).get("source") == "ahrefs"]),
        "lost_value_urls": len([r for r in records if is_lost(r)]),
    }


# --- fase 3: focuszoekwoord ----------------------------------------------------

def keyword_hint(page: _Page) -> dict[str, Any] | None:
    """Het zoekwoord waarop de pagina volgens Ahrefs het meeste verkeer krijgt."""
    data = page.ahrefs if isinstance(page.ahrefs, dict) else {}
    keyword = " ".join(str(data.get("top_keyword") or "").split())[:200]
    if not keyword:
        return None
    return {
        "keyword": keyword,
        "position": _int(data.get("top_keyword_position")),
        "volume": _int(data.get("top_keyword_volume")),
        "traffic": _int(page.org_traffic),
        # Wordt gezet door `mark_fixed_keywords`: dit zoekwoord ligt vast als focuszoekwoord.
        "fixed": False,
    }


def is_ranking_keyword(hint: dict[str, Any] | None) -> bool:
    """Rankt de pagina echt op dit zoekwoord?

    Een pagina op positie 80 voor een toevallig woord telt niet, en een pagina die
    er geen verkeer uit haalt ook niet (vaak de merknaam, waar elke pagina op staat).
    """
    position = _int((hint or {}).get("position"))
    traffic = _int((hint or {}).get("traffic")) or 0
    return position is not None and position <= settings.ahrefs_keyword_max_position and traffic > 0


def mark_fixed_keywords(hints: Iterable[dict[str, Any] | None]) -> None:
    """Bepaal per zoekwoord welke pagina het als vast focuszoekwoord krijgt.

    Eén zoekwoord hoort bij één pagina: die met het meeste verkeer. De andere
    pagina's houden het alleen als hint voor de AI.
    """
    best: dict[str, dict[str, Any]] = {}
    for hint in hints:
        if not hint or not is_ranking_keyword(hint):
            continue
        key = hint["keyword"].lower()
        if key not in best or (hint.get("traffic") or 0) > (best[key].get("traffic") or 0):
            best[key] = hint
    for hint in best.values():
        hint["fixed"] = True


def is_fixed_keyword(hint: dict[str, Any] | None) -> bool:
    return bool(hint and hint.get("fixed"))


def choose_keyword(carried: dict[str, Any] | None, hint: dict[str, Any] | None) -> dict[str, Any]:
    """Velden `focus_keyword`, `intent`, `keyword_source` voor een nieuwe contentpagina.

    Volgorde: handmatig vastgelegd > Ahrefs (pagina rankt nu) > eerder overgenomen Ahrefs.
    `carried` is het vastgelegde zoekwoord uit de vorige fase 3-scan.
    """
    if carried and carried.get("keyword_source") != "ahrefs":
        return carried
    if is_fixed_keyword(hint):
        same = bool(carried) and carried.get("focus_keyword") == hint["keyword"]
        return {
            "focus_keyword": hint["keyword"],
            "intent": carried.get("intent") if same and carried else None,
            "keyword_source": "ahrefs",
        }
    return carried or {}
