"""Tools voor de contentgap-agent (fase 3): alleen-lezen overzicht van de site."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.agents.tools import tool
from app.db.models import CustomerWebsite, LaunchContentPage, LaunchScan, LaunchScanPage
from app.features.launch_checklist.services.content_checks import detect_place
from app.features.launch_checklist.services.page_types import PAGE_TYPES

MAX_PAGES = 80


@dataclass
class ContentSiteContext:
    db: Session
    scan_id: str
    source_scan_id: str | None
    customer_name: str


def _pages(ctx: ContentSiteContext) -> list[LaunchContentPage]:
    return (
        ctx.db.query(LaunchContentPage)
        .filter(LaunchContentPage.scan_id == ctx.scan_id)
        .order_by(LaunchContentPage.path)
        .all()
    )


def _row(page: LaunchContentPage) -> dict[str, Any]:
    return {
        "url": page.url,
        "title": page.title,
        "h1": ((page.signals or {}).get("h1") or [None])[0],
        "words": page.word_count,
        "focus_keyword": page.focus_keyword,
        "place": detect_place(page),
    }


@tool(
    "get_site_overview",
    "Overzicht van de site: klant, aantal pagina's per paginatype, alle dienstpagina's, gevonden locatiepagina's "
    "met plaatsnaam en de plaatsen/adressen die op de site genoemd worden. Begin hiermee.",
)
def get_site_overview(ctx: ContentSiteContext) -> dict[str, Any]:
    scan = ctx.db.get(LaunchScan, ctx.scan_id)
    customer = ctx.db.get(CustomerWebsite, scan.customer_website_id) if scan else None
    pages = _pages(ctx)
    addresses: Counter[str] = Counter()
    if ctx.source_scan_id:
        rows = (
            ctx.db.query(LaunchScanPage.signals)
            .filter(LaunchScanPage.scan_id == ctx.source_scan_id, LaunchScanPage.signals.isnot(None))
            .limit(400)
        )
        for (signals,) in rows:
            for address in (signals or {}).get("addresses") or []:
                addresses[str(address)] += 1
    services = [p for p in pages if p.page_type in {"dienst", "product", "categorie"}]
    return {
        "customer": ctx.customer_name,
        "base_url": scan.base_url if scan else None,
        "seo_goals": getattr(customer, "seo_goals", None),
        "page_types": dict(Counter((p.page_type or "overig") for p in pages)),
        "services": [_row(p) for p in services[:MAX_PAGES]],
        "location_pages": [_row(p) for p in pages if detect_place(p)][:MAX_PAGES],
        "addresses_on_site": [a for a, _ in addresses.most_common(5)],
    }


@tool(
    "list_pages",
    "Pagina's van één paginatype (url, titel, H1, woorden, focuszoekwoord). Gebruik dit om te zien welke blogs, "
    "cases, FAQ- en over ons-pagina's al bestaan, zodat je geen bestaande content voorstelt.",
    {
        "page_type": {"type": "string", "enum": sorted(PAGE_TYPES)},
        "search": {"type": "string", "description": "Optioneel: filter op tekst in URL of titel. Leeg = alles."},
    },
    ["page_type", "search"],
)
def list_pages(ctx: ContentSiteContext, page_type: str, search: str = "") -> dict[str, Any]:
    needle = (search or "").strip().lower()
    rows = [
        p for p in _pages(ctx)
        if (p.page_type or "overig") == page_type
        and (not needle or needle in p.url.lower() or needle in (p.title or "").lower())
    ]
    return {"total": len(rows), "pages": [_row(p) for p in rows[:MAX_PAGES]]}


CONTENT_GAP_TOOLS = [get_site_overview, list_pages]
