"""Tools voor de Nulmeting-agent: alleen-lezen toegang tot één scan."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.agents.tools import tool
from app.db.models import LaunchScan, LaunchScanIssue, LaunchScanPage


@dataclass
class NulmetingContext:
    db: Session
    scan_id: str
    customer_name: str


def _page_brief(p: LaunchScanPage) -> dict[str, Any]:
    return {
        "url": p.url,
        "status": p.status_code,
        "indexable": p.indexable,
        "reason": p.indexability_reason,
        "title": p.title,
        "meta_len": p.meta_description_length,
        "h1": (p.h1 or [])[:3],
        "words": p.word_count,
        "ms": p.response_time_ms,
        "cwv": p.cwv_status,
    }


@tool(
    "get_scan_overview",
    "Algemene info over de scan: klant, URL, discovery-bron, samenvattende cijfers (statuscodes, indexeerbaarheid, ontbrekende titles/meta/H1, CWV-verdeling, issues per ernst/categorie/type) en waarschuwingen.",
)
def get_scan_overview(ctx: NulmetingContext) -> dict[str, Any]:
    scan = ctx.db.get(LaunchScan, ctx.scan_id)
    if scan is None:
        return {"error": "Scan niet gevonden"}
    return {
        "customer": ctx.customer_name,
        "base_url": scan.base_url,
        "discovery_source": scan.discovery_source,
        "total_urls": scan.total_urls,
        "vitals_measured": scan.vitals_measured,
        "stats": scan.summary_stats,
        "warnings": scan.warnings,
    }


@tool(
    "get_issue_groups",
    "Actiepunten gegroepeerd per issue_type met aantal, ernst, categorie en maximaal 5 voorbeeld-URL's. Gebruik dit om te prioriteren.",
    {
        "category": {
            "type": "string",
            "enum": ["techniek", "on-page", "content", "performance", "ai"],
            "description": "Optioneel filter op categorie.",
        },
    },
)
def get_issue_groups(ctx: NulmetingContext, category: str | None = None) -> list[dict[str, Any]]:
    query = ctx.db.query(LaunchScanIssue).filter(LaunchScanIssue.scan_id == ctx.scan_id)
    if category:
        query = query.filter(LaunchScanIssue.category == category)
    groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "examples": [], "severity": set()})
    for issue in query.all():
        g = groups[issue.issue_type]
        g["count"] += 1
        g["category"] = issue.category
        g["severity"].add(issue.severity)
        if len(g["examples"]) < 5:
            g["examples"].append(issue.url or issue.title)
    order = {"hoog": 0, "middel": 1, "laag": 2}
    out = [
        {
            "issue_type": t,
            "count": g["count"],
            "category": g["category"],
            "severity": sorted(g["severity"], key=lambda s: order.get(s, 9)),
            "examples": g["examples"],
        }
        for t, g in groups.items()
    ]
    out.sort(key=lambda g: (order.get(g["severity"][0], 9), -g["count"]))
    return out


@tool(
    "query_pages",
    "Zoek pagina's uit de inventaris op een filter. Geeft compacte pagina-info terug.",
    {
        "filter": {
            "type": "string",
            "enum": [
                "all", "errors", "redirects", "non_indexable", "missing_title",
                "missing_meta", "missing_h1", "multiple_h1", "thin_content", "slow", "cwv_poor",
            ],
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    },
    ["filter"],
)
def query_pages(ctx: NulmetingContext, filter: str = "all", limit: int = 15) -> dict[str, Any]:
    pages = ctx.db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == ctx.scan_id).all()
    predicates = {
        "all": lambda p: True,
        "errors": lambda p: p.status_code is None or (p.status_code or 0) >= 400,
        "redirects": lambda p: bool(p.redirect_chain),
        "non_indexable": lambda p: p.indexable is False,
        "missing_title": lambda p: p.indexable and not p.title,
        "missing_meta": lambda p: p.indexable and not p.meta_description,
        "missing_h1": lambda p: p.indexable and not (p.h1_count or 0),
        "multiple_h1": lambda p: p.indexable and (p.h1_count or 0) > 1,
        "thin_content": lambda p: p.indexable and (p.word_count or 0) < 300,
        "slow": lambda p: (p.response_time_ms or 0) > 2000,
        "cwv_poor": lambda p: p.cwv_status == "poor",
    }
    pred = predicates.get(filter, predicates["all"])
    matches = [p for p in pages if pred(p)]
    limit = max(1, min(int(limit or 15), 50))
    return {"total_matches": len(matches), "pages": [_page_brief(p) for p in matches[:limit]]}


@tool(
    "get_worst_vitals",
    "De pagina's met de slechtste Core Web Vitals (mobiel), gesorteerd op performance-score.",
    {"limit": {"type": "integer", "minimum": 1, "maximum": 25}},
)
def get_worst_vitals(ctx: NulmetingContext, limit: int = 10) -> list[dict[str, Any]]:
    pages = (
        ctx.db.query(LaunchScanPage)
        .filter(LaunchScanPage.scan_id == ctx.scan_id, LaunchScanPage.cwv.isnot(None))
        .all()
    )

    def score(p: LaunchScanPage) -> float:
        value = ((p.cwv or {}).get("lab") or {}).get("performance_score")
        return value if isinstance(value, (int, float)) else 101

    pages.sort(key=score)
    limit = max(1, min(int(limit or 10), 25))
    out = []
    for p in pages[:limit]:
        cwv = p.cwv or {}
        lab = cwv.get("lab") or {}
        out.append({
            "url": p.url,
            "status": cwv.get("status"),
            "source": cwv.get("source"),
            "performance_score": lab.get("performance_score"),
            "lcp_ms": lab.get("lcp"),
            "cls": lab.get("cls"),
            "tbt_ms": lab.get("tbt"),
            "field": cwv.get("field"),
        })
    return out


@tool(
    "get_ai_checks",
    "Resultaten van de AI-vindbaarheidschecks: robots.txt per AI-bot, llms.txt, sitemap, structured data, SSR.",
)
def get_ai_checks(ctx: NulmetingContext) -> Any:
    scan = ctx.db.get(LaunchScan, ctx.scan_id)
    return scan.ai_checks if scan else None


NULMETING_TOOLS = [get_scan_overview, get_issue_groups, query_pages, get_worst_vitals, get_ai_checks]
