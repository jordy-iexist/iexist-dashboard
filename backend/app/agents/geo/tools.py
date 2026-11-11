"""Tools voor de GEO-agent (fase 2): alleen-lezen toegang tot één fase-2 scan."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.agents.tools import tool
from app.db.models import LaunchChecklistState, LaunchScan, LaunchScanPage
from app.features.launch_checklist.services.geo_checklist import ITEMS, merge_checklist
from app.features.launch_checklist.services.geo_extract import all_types
from app.features.launch_checklist.services.page_types import PAGE_TYPES


@dataclass
class GeoContext:
    db: Session
    scan_id: str
    source_scan_id: str
    customer_name: str


def _scan(ctx: GeoContext) -> LaunchScan | None:
    return ctx.db.get(LaunchScan, ctx.scan_id)


def _merged(ctx: GeoContext) -> dict[str, Any]:
    scan = _scan(ctx)
    if scan is None:
        return {}
    payload = scan.checklist or {}
    states = {
        s.item_key: s
        for s in ctx.db.query(LaunchChecklistState)
        .filter(LaunchChecklistState.customer_website_id == scan.customer_website_id)
        .all()
    }
    return merge_checklist(
        payload.get("items"), states, is_webshop=bool(payload.get("is_webshop"))
    )


@tool(
    "get_checklist",
    "Overzicht van de hele GEO/SEO-checklist: per sectie de voortgang en per punt de auto-status (ok/warning/error/nvt/unknown/info), handmatige status en korte melding. Begin hiermee.",
)
def get_checklist(ctx: GeoContext) -> dict[str, Any]:
    merged = _merged(ctx)
    scan = _scan(ctx)
    payload = (scan.checklist if scan else None) or {}
    return {
        "customer": ctx.customer_name,
        "base_url": scan.base_url if scan else None,
        "is_webshop": payload.get("is_webshop"),
        "page_types": payload.get("page_types"),
        "progress": {
            "done": merged.get("done"),
            "total": merged.get("total"),
            "percent": merged.get("percent"),
        },
        "sections": [
            {
                "section": s["label"],
                "done": s["done"],
                "total": s["total"],
                "items": [
                    {
                        "key": i["key"],
                        "label": i["label"],
                        "mode": i["mode"],
                        "priority": i["priority"],
                        "auto_status": (i["auto"] or {}).get("status"),
                        "message": (i["auto"] or {}).get("message"),
                        "manual_status": i["manual_status"],
                        "effective": i["effective"],
                    }
                    for i in s["items"]
                ],
            }
            for s in merged.get("sections", [])
        ],
    }


@tool(
    "get_item_details",
    "Volledige details van één checklistpunt: melding, evidence (voorbeeld-URL's, gevonden waarden) en ruwe details.",
    {"key": {"type": "string", "enum": sorted(ITEMS.keys())}},
    ["key"],
)
def get_item_details(ctx: GeoContext, key: str) -> Any:
    scan = _scan(ctx)
    items = ((scan.checklist if scan else None) or {}).get("items") or {}
    item = ITEMS.get(key)
    result = dict(items.get(key) or {})
    if isinstance(result.get("details"), dict):
        result["details"] = {
            k: v for k, v in result["details"].items() if k not in {"tried", "baseline"}
        }
    return {"key": key, "label": item.label if item else key, **result}


@tool(
    "get_schema_matrix",
    "Per paginatype: aantal pagina's en welke schema-types daar voorkomen (aantal pagina's per type).",
)
def get_schema_matrix(ctx: GeoContext) -> dict[str, Any]:
    pages = (
        ctx.db.query(LaunchScanPage)
        .filter(
            LaunchScanPage.scan_id == ctx.source_scan_id,
            LaunchScanPage.indexable.is_(True),
        )
        .all()
    )
    matrix: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"pages": 0, "types": defaultdict(int)}
    )
    for p in pages:
        if p.page_type is None:
            continue
        row = matrix[p.page_type]
        row["pages"] += 1
        for t in all_types(p.jsonld or []):
            row["types"][t] += 1
    return {
        PAGE_TYPES.get(k, k): {
            "pages": v["pages"],
            "types": dict(sorted(v["types"].items(), key=lambda kv: -kv[1])[:12]),
        }
        for k, v in matrix.items()
    }


@tool(
    "get_entity_signals",
    "Wat de site toont over het bedrijf: NAP-gegevens (telefoon, adres, KvK, BTW), sameAs-links en profielen waar de site naar linkt.",
)
def get_entity_signals(ctx: GeoContext) -> dict[str, Any]:
    scan = _scan(ctx)
    items = ((scan.checklist if scan else None) or {}).get("items") or {}
    nap = ((items.get("nap_linkedin") or {}).get("details") or {}).get("site_nap")
    org = (items.get("schema_org_nap") or {}).get("details")
    same_as = {
        k.removeprefix("sameas_"): v.get("evidence")
        for k, v in items.items()
        if k.startswith("sameas_")
    }
    return {"site_nap": nap, "organization_markup": org, "same_as_or_profiles": same_as}


@tool(
    "query_pages",
    "Pagina's met paginatype, klikdiepte, inkomende interne links, woorden en schema-types. Filter optioneel op paginatype of probleem.",
    {
        "page_type": {"type": "string", "enum": sorted(PAGE_TYPES.keys())},
        "problem": {"type": "string", "enum": ["deep", "orphan", "no_schema", "thin"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    },
)
def query_pages(
    ctx: GeoContext,
    page_type: str | None = None,
    problem: str | None = None,
    limit: int = 15,
) -> dict[str, Any]:
    pages = (
        ctx.db.query(LaunchScanPage)
        .filter(
            LaunchScanPage.scan_id == ctx.source_scan_id,
            LaunchScanPage.indexable.is_(True),
        )
        .all()
    )
    if page_type:
        pages = [p for p in pages if p.page_type == page_type]
    predicates = {
        "deep": lambda p: p.click_depth is None or p.click_depth > 3,
        "orphan": lambda p: p.in_sitemap and (p.inlinks or 0) == 0,
        "no_schema": lambda p: not (p.jsonld or []),
        "thin": lambda p: (p.word_count or 0) < 300,
    }
    if problem in predicates:
        pages = [p for p in pages if predicates[problem](p)]
    limit = max(1, min(int(limit or 15), 50))
    return {
        "total_matches": len(pages),
        "pages": [
            {
                "url": p.url,
                "type": p.page_type,
                "depth": p.click_depth,
                "inlinks": p.inlinks,
                "words": p.word_count,
                "schema": sorted(all_types(p.jsonld or []))[:10],
            }
            for p in pages[:limit]
        ],
    }


GEO_TOOLS = [
    get_checklist,
    get_item_details,
    get_schema_matrix,
    get_entity_signals,
    query_pages,
]
