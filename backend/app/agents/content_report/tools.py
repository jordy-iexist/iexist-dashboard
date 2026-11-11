"""Tools voor de rapport-agent (fase 3): alleen-lezen toegang tot één fase-3 scan."""
from __future__ import annotations

from collections import Counter
from typing import Any

from app.agents.content_gap.tools import ContentSiteContext
from app.agents.tools import tool
from app.db.models import LaunchContentPage, LaunchContentSuggestion, LaunchScan
from app.features.launch_checklist.services.checklist_view import merged_content_checklist
from app.features.launch_checklist.services.content_checklist import ITEMS

MAX_ROWS = 25


def _scan(ctx: ContentSiteContext) -> LaunchScan | None:
    return ctx.db.get(LaunchScan, ctx.scan_id)


@tool(
    "get_checklist",
    "De fase-3 checklist: per hoofditem de voortgang en per subitem de status (ok/warning/error/nvt/unknown), "
    "handmatige status en melding, plus hoeveel pagina's door AI zijn geanalyseerd. Begin hiermee.",
)
def get_checklist(ctx: ContentSiteContext) -> dict[str, Any]:
    scan = _scan(ctx)
    if scan is None:
        return {}
    merged = merged_content_checklist(ctx.db, scan.customer_website_id, scan)
    payload = scan.checklist or {}
    return {
        "customer": ctx.customer_name,
        "base_url": scan.base_url,
        "summary": payload.get("summary"),
        "progress": {"done": merged.get("done"), "total": merged.get("total"), "percent": merged.get("percent")},
        "sections": [
            {
                "section": s["label"],
                "done": s["done"],
                "total": s["total"],
                "items": [
                    {
                        "key": i["key"],
                        "label": i["label"],
                        "priority": i["priority"],
                        "status": (i.get("auto") or {}).get("status"),
                        "message": (i.get("auto") or {}).get("message"),
                        "manual_status": i.get("manual_status"),
                        "effective": i["effective"],
                    }
                    for i in s["items"]
                ],
            }
            for s in merged["sections"]
        ],
    }


@tool(
    "get_item_pages",
    "De pagina's met een probleem voor één checklistpunt: URL, paginatype, bevinding van de regelcontrole en het "
    "aantal open AI-voorstellen.",
    {"key": {"type": "string", "enum": sorted(ITEMS)}},
    ["key"],
)
def get_item_pages(ctx: ContentSiteContext, key: str) -> dict[str, Any]:
    pages = ctx.db.query(LaunchContentPage).filter(LaunchContentPage.scan_id == ctx.scan_id).all()
    counts = Counter(
        row[0]
        for row in ctx.db.query(LaunchContentSuggestion.content_page_id).filter(
            LaunchContentSuggestion.scan_id == ctx.scan_id,
            LaunchContentSuggestion.item_key == key,
            LaunchContentSuggestion.status == "open",
        )
    )
    rows = []
    for page in pages:
        check = (page.checks or {}).get(key) or {}
        if check.get("status") in {"error", "warning"} or counts.get(page.id):
            rows.append({
                "url": page.url,
                "page_type": page.page_type,
                "status": check.get("status"),
                "finding": check.get("message"),
                "open_suggestions": counts.get(page.id, 0),
            })
    rows.sort(key=lambda r: (r["status"] != "error", -r["open_suggestions"]))
    return {"item": ITEMS[key].label, "total": len(rows), "pages": rows[:MAX_ROWS]}


@tool(
    "get_suggestions",
    "AI-voorstellen van deze scan. scope='pages' = voorstellen per pagina (bestaande content), scope='new' = "
    "voorstellen voor nieuwe content (contentgap). Geeft per voorstel het checklistpunt, de pagina, titel, het "
    "voorstel (ingekort) en de status.",
    {
        "scope": {"type": "string", "enum": ["pages", "new"]},
        "key": {"type": "string", "enum": [*sorted(ITEMS), "alle"], "description": "Checklistpunt, of 'alle'."},
    },
    ["scope", "key"],
)
def get_suggestions(ctx: ContentSiteContext, scope: str, key: str = "alle") -> dict[str, Any]:
    query = ctx.db.query(LaunchContentSuggestion).filter(LaunchContentSuggestion.scan_id == ctx.scan_id)
    if scope == "new":
        query = query.filter(LaunchContentSuggestion.content_page_id.is_(None))
    else:
        query = query.filter(LaunchContentSuggestion.content_page_id.isnot(None))
    if key and key != "alle":
        query = query.filter(LaunchContentSuggestion.item_key == key)
    rows = query.order_by(LaunchContentSuggestion.created_at).all()
    urls = {
        p.id: p.url
        for p in ctx.db.query(LaunchContentPage).filter(LaunchContentPage.scan_id == ctx.scan_id).all()
    }
    return {
        "total": len(rows),
        "per_item": dict(Counter(r.item_key for r in rows)),
        "suggestions": [
            {
                "item_key": r.item_key,
                "url": urls.get(r.content_page_id),
                "title": r.title,
                "proposal": (r.proposed_value or "")[:300],
                "status": r.status,
            }
            for r in rows[:MAX_ROWS]
        ],
    }


CONTENT_REPORT_TOOLS = [get_checklist, get_item_pages, get_suggestions]
