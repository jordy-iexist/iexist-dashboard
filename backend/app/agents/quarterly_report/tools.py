"""Tools voor de kwartaalrapport-agent (fase 4): alleen-lezen toegang tot één fase 4-scan."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.agents.tools import tool
from app.db.models import LaunchScan, LaunchScanIssue
from app.features.launch_checklist.services.checklist_view import merged_quarterly_checklist
from app.features.launch_checklist.services.issues import ISSUE_TYPES

MAX_ROWS = 25


@dataclass
class QuarterlyContext:
    db: Session
    scan_id: str
    customer_name: str
    period: str


def _payload(ctx: QuarterlyContext) -> dict[str, Any]:
    scan = ctx.db.get(LaunchScan, ctx.scan_id)
    return (scan.checklist if scan else None) or {}


def _comparison(ctx: QuarterlyContext) -> dict[str, Any]:
    return _payload(ctx).get("comparison") or {}


@tool(
    "get_overview",
    "Overzicht van de ronde: vergelijkingsbasis, AI-score voor/na, aantallen actiepunten en pagina's voor/na, "
    "Ahrefs-domeincijfers voor/na en welke databronnen beschikbaar zijn. Begin hiermee.",
)
def get_overview(ctx: QuarterlyContext) -> dict[str, Any]:
    comparison = _comparison(ctx)
    ai = comparison.get("ai") or {}
    issues = comparison.get("issues") or {}
    return {
        "customer": ctx.customer_name,
        "period": ctx.period,
        "base": comparison.get("base"),
        "ai_score": {"before": ai.get("before"), "after": ai.get("after"),
                     "improved": ai.get("improved"), "worsened": ai.get("worsened")},
        "issues_total": {"before": issues.get("before"), "after": issues.get("after")},
        "pages": comparison.get("pages"),
        "ahrefs": comparison.get("ahrefs"),
        "sources": _payload(ctx).get("sources"),
    }


@tool(
    "get_checklist",
    "De fase 4-checklist van deze ronde: per punt de auto-status (ok/warning/error/info/unknown), "
    "handmatige status, notitie en melding.",
)
def get_checklist(ctx: QuarterlyContext) -> dict[str, Any]:
    scan = ctx.db.get(LaunchScan, ctx.scan_id)
    if scan is None:
        return {}
    merged = merged_quarterly_checklist(ctx.db, scan.customer_website_id, scan, ctx.period)
    return {
        "progress": {"done": merged["done"], "total": merged["total"], "percent": merged["percent"]},
        "items": [
            {
                "key": i["key"],
                "label": i["label"],
                "mode": i["mode"],
                "auto_status": (i["auto"] or {}).get("status"),
                "message": (i["auto"] or {}).get("message"),
                "manual_status": i["manual_status"],
                "note": i["note"],
            }
            for s in merged["sections"]
            for i in s["items"]
        ],
    }


@tool(
    "get_ai_checks",
    "AI-vindbaarheid per check: status voor en na (ok/warning/error) en de huidige melding.",
)
def get_ai_checks(ctx: QuarterlyContext) -> dict[str, Any]:
    return {"checks": (_comparison(ctx).get("ai") or {}).get("checks") or []}


@tool(
    "get_issue_changes",
    "Actiepunten per type: aantal voor en na en het verschil, gesorteerd op grootste verandering.",
)
def get_issue_changes(ctx: QuarterlyContext) -> dict[str, Any]:
    issues = _comparison(ctx).get("issues") or {}
    return {"rows": (issues.get("rows") or [])[:MAX_ROWS]}


@tool(
    "get_rankings",
    "Posities uit de SEO-tracker: per zoekwoord de positie rond de basisdatum en nu (null = niet in de top 100), "
    "plus aantallen gestegen/gedaald en in de top 3/10. Leeg als er geen zoekwoorden worden gevolgd.",
)
def get_rankings(ctx: QuarterlyContext) -> dict[str, Any]:
    rankings = _comparison(ctx).get("rankings")
    if not rankings:
        return {"available": False}
    rows = rankings.get("rows") or []
    movers = sorted([r for r in rows if r.get("delta")], key=lambda r: -abs(r["delta"]))
    return {
        "available": True,
        **{k: v for k, v in rankings.items() if k != "rows"},
        "biggest_changes": movers[:15],
        "top_positions": [r for r in rows if r.get("after") is not None][:15],
    }


@tool(
    "get_search_console",
    "Google Search Console: klikken, vertoningen, CTR en gemiddelde positie in de meetperiode, de periode ervoor "
    "en dezelfde periode vorig jaar; zoekopdrachten en pagina's met de meeste klikken en de grootste stijgers en "
    "dalers; ingediende sitemaps; en geïnspecteerde URL's die Google niet heeft geïndexeerd. "
    "available=false als Search Console niet is gekoppeld.",
)
def get_search_console(ctx: QuarterlyContext) -> dict[str, Any]:
    gsc = _comparison(ctx).get("search_console")
    if not gsc:
        return {"available": False}

    def movers(block: dict[str, Any] | None) -> dict[str, Any]:
        block = block or {}
        return {
            "total": block.get("total", 0),
            "top": (block.get("top") or [])[:10],
            "risers": (block.get("risers") or [])[:10],
            "fallers": (block.get("fallers") or [])[:10],
        }

    sitemaps = gsc.get("sitemaps")
    inspection = gsc.get("inspection")
    return {
        "available": True,
        "property": gsc.get("property"),
        "period": gsc.get("period"),
        "previous_period": gsc.get("previous"),
        "last_year_period": gsc.get("last_year"),
        # before = periode ervoor, after = meetperiode. Bij positie is lager beter.
        "metrics": gsc.get("metrics") if gsc.get("has_performance") else None,
        "queries": movers(gsc.get("queries")),
        "pages": movers(gsc.get("pages")),
        "sitemaps": None if sitemaps is None else {
            "total": sitemaps.get("total"),
            "with_errors": sitemaps.get("with_errors"),
            "with_warnings": sitemaps.get("with_warnings"),
            "problems": [
                s for s in sitemaps.get("rows") or [] if s.get("errors") or s.get("warnings")
            ][:MAX_ROWS],
        },
        "url_inspection": None if not inspection else {
            "checked": inspection.get("checked"),
            "indexed": inspection.get("indexed"),
            "not_indexed": (inspection.get("not_indexed") or [])[:MAX_ROWS],
        },
    }


@tool(
    "get_new_pages",
    "Nieuwe pagina's sinds de basis (met problemen zoals 404, noindex, canonical, niet in sitemap), pagina's die "
    "eerder werkten en nu een fout geven, en het aantal verdwenen pagina's.",
)
def get_new_pages(ctx: QuarterlyContext) -> dict[str, Any]:
    details = ((_payload(ctx).get("items") or {}).get("c4_new_pages") or {}).get("details") or {}
    return {
        "new_total": details.get("new_total", 0),
        "new": (details.get("new") or [])[:MAX_ROWS],
        "broken_total": details.get("broken_total", 0),
        "broken": (details.get("broken") or [])[:MAX_ROWS],
        "removed_total": details.get("removed_total", 0),
        "removed_examples": (details.get("removed") or [])[:10],
    }


@tool(
    "get_schema_problems",
    "Resultaat van de schema-validatie: aantal gecontroleerde pagina's en per pagina de fouten (ongeldige JSON, "
    "ontbrekende verplichte eigenschappen, verdwenen schema-types).",
)
def get_schema_problems(ctx: QuarterlyContext) -> dict[str, Any]:
    details = ((_payload(ctx).get("items") or {}).get("c4_schema_validation") or {}).get("details") or {}
    return {k: (v[:MAX_ROWS] if isinstance(v, list) else v) for k, v in details.items()}


@tool(
    "query_issues",
    "Actiepunten van deze scan, optioneel gefilterd op ernst. Geeft type, titel en URL.",
    {"severity": {"type": "string", "enum": ["hoog", "middel", "laag"]}},
)
def query_issues(ctx: QuarterlyContext, severity: str | None = None) -> dict[str, Any]:
    query = ctx.db.query(LaunchScanIssue).filter(LaunchScanIssue.scan_id == ctx.scan_id)
    if severity:
        query = query.filter(LaunchScanIssue.severity == severity)
    rows = query.limit(200).all()
    return {
        "total": len(rows),
        "issues": [
            {
                "type": ISSUE_TYPES.get(r.issue_type, {}).get("label", r.issue_type),
                "severity": r.severity,
                "title": r.title,
                "url": r.url,
            }
            for r in rows[:MAX_ROWS]
        ],
    }


QUARTERLY_REPORT_TOOLS = [
    get_overview,
    get_checklist,
    get_ai_checks,
    get_issue_changes,
    get_rankings,
    get_search_console,
    get_new_pages,
    get_schema_problems,
    query_issues,
]
