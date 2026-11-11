"""Gedeelde fase-2 stappen voor worker én router (herberekenen zonder refetch)."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.db.models import CustomerWebsite, LaunchPageTypeOverride, LaunchScan, LaunchScanPage
from app.features.launch_checklist.services.bot_access import test_bot_access
from app.features.launch_checklist.services.geo_checks import (
    check_html_sitemap,
    check_sitemap_index,
    detect_webshop,
    evaluate_checklist,
    find_home,
    page_type_counts,
)
from app.features.launch_checklist.services.issues import _is_indexable_html, _is_ok_html
from app.features.launch_checklist.services.page_types import (
    PAGE_TYPES,
    classify_by_rules,
    classify_with_llm,
)


def _origin(base_url: str) -> str:
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def load_overrides(db: Session, customer_id: str) -> dict[str, str]:
    return {
        o.path: o.page_type
        for o in db.query(LaunchPageTypeOverride)
        .filter(LaunchPageTypeOverride.customer_website_id == customer_id)
        .all()
    }


def apply_page_types(
    db: Session,
    pages: list[LaunchScanPage],
    *,
    customer_id: str,
    base_url: str,
    user_id: str | None,
    use_llm: bool = True,
) -> None:
    """Zet page_type/page_type_source op de pagina's (commit doet de aanroeper)."""
    overrides = load_overrides(db, customer_id)
    home = find_home(pages)
    unresolved: list[LaunchScanPage] = []
    for p in pages:
        if not _is_ok_html(p):
            p.page_type, p.page_type_source = None, None
            continue
        if p.path in overrides and overrides[p.path] in PAGE_TYPES:
            p.page_type, p.page_type_source = overrides[p.path], "manual"
            continue
        rule = classify_by_rules(p.url, is_home=home is not None and p.id == home.id, signals=p.signals, jsonld=p.jsonld)
        if rule:
            p.page_type, p.page_type_source = rule, "rule"
        elif p.page_type_source == "ai" and p.page_type:
            continue  # eerder door AI bepaald: niet opnieuw betalen
        else:
            p.page_type, p.page_type_source = "overig", "rule"
            if p.indexable is True:
                unresolved.append(p)

    if use_llm and unresolved and user_id:
        items = [
            {"id": i, "url": p.url, "title": p.title, "h1": (p.h1 or [""])[0] if p.h1 else ""}
            for i, p in enumerate(unresolved[:600])
        ]
        labels = classify_with_llm(items, user_id=user_id)
        for i, p in enumerate(unresolved[:600]):
            label = labels.get(str(i))
            if label:
                p.page_type, p.page_type_source = label, "ai"


def collect_extras(base_url: str, pages: list[LaunchScanPage]) -> dict[str, Any]:
    origin = _origin(base_url)
    linked_sitemap = next(
        ((p.signals or {}).get("links", {}).get("sitemap") for p in pages if (p.signals or {}).get("links", {}).get("sitemap")),
        None,
    )
    home = find_home(pages)
    candidates = [p for p in pages if _is_indexable_html(p) and (home is None or p.id != home.id)]
    candidates.sort(key=lambda p: (p.path.count("/"), len(p.path)))
    home_url = (home.final_url or home.url) if home is not None else origin + "/"
    bot_urls = [home_url] + [p.final_url or p.url for p in candidates][:3]
    return {
        "sitemap_index": check_sitemap_index(origin),
        "html_sitemap": check_html_sitemap(origin, linked_sitemap),
        "bot_access": test_bot_access(bot_urls),
        "webshop": detect_webshop(pages),
    }


def build_checklist_payload(
    db: Session, scan: LaunchScan, pages: list[LaunchScanPage], extras: dict[str, Any]
) -> dict[str, Any]:
    source = db.get(LaunchScan, scan.source_scan_id) if scan.source_scan_id else None
    customer = db.get(CustomerWebsite, scan.customer_website_id)
    detection = extras.get("webshop") or detect_webshop(pages)
    override = customer.launch_is_webshop if customer else None
    is_webshop = override if override is not None else bool(detection.get("detected"))
    items = evaluate_checklist(
        base_url=scan.base_url,
        pages=pages,
        ai_checks=(source.ai_checks if source else None),
        extras=extras,
        is_webshop=is_webshop,
        discovery_source=(source.discovery_source if source else None),
    )
    counts = page_type_counts(pages)
    return {
        "items": items,
        "extras": extras,
        "is_webshop": is_webshop,
        "webshop_detected": bool(detection.get("detected")),
        "webshop_reasons": detection.get("reasons") or [],
        "page_types": counts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "auto_status": dict(Counter(r.get("status") for r in items.values())),
            "page_types": counts,
            "pages_fetched": len([p for p in pages if p.signals is not None]),
            "is_webshop": is_webshop,
        },
    }


def rebuild_checklist(db: Session, scan: LaunchScan, *, reclassify: bool = False) -> None:
    """Herbereken de checklist van een fase-2 scan uit opgeslagen data."""
    if scan.phase != 2 or not scan.source_scan_id:
        return
    pages = db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == scan.source_scan_id).all()
    if reclassify:
        apply_page_types(db, pages, customer_id=scan.customer_website_id, base_url=scan.base_url,
                         user_id=None, use_llm=False)
    extras = (scan.checklist or {}).get("extras") or {}
    payload = build_checklist_payload(db, scan, pages, extras)
    scan.checklist = payload
    scan.summary_stats = payload["summary"]
    scan.updated_at = datetime.now(timezone.utc)
