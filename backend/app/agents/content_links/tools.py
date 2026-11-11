"""Tools voor de links & afbeeldingen-agent (fase 3)."""
from __future__ import annotations

import re
from typing import Any

from app.agents.content_common import ContentPageContext
from app.agents.tools import tool
from app.db.models import LaunchContentPage
from app.features.launch_checklist.services.discovery import url_key
from app.features.launch_checklist.services.page_types import PAGE_TYPES

_TOKEN_RE = re.compile(r"[\wÀ-ÿ]{3,}", re.UNICODE)
MAX_RESULTS = 15


def _tokens(text: str | None) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


@tool(
    "find_link_targets",
    "Zoek andere pagina's van deze website om naar te linken. Geeft per pagina URL, paginatype, titel, H1 en "
    "focuszoekwoord, en of de huidige pagina er al naar linkt. Zoek op onderwerp (bijv. een dienst of thema).",
    {
        "query": {"type": "string", "description": "Zoekwoorden, bijv. 'dakgoot reinigen'."},
        "page_type": {"type": "string", "enum": [*sorted(PAGE_TYPES), "alle"],
                      "description": "Beperk tot een paginatype, of 'alle'."},
    },
    ["query", "page_type"],
)
def find_link_targets(ctx: ContentPageContext, query: str, page_type: str = "alle") -> dict[str, Any]:
    current = ctx.db.get(LaunchContentPage, ctx.page_id)
    linked = {url_key(l["url"]) for l in ((current.links if current else None) or []) if l.get("in_content")}
    wanted = _tokens(query)
    rows = ctx.db.query(LaunchContentPage).filter(LaunchContentPage.scan_id == ctx.scan_id)
    if page_type and page_type != "alle":
        rows = rows.filter(LaunchContentPage.page_type == page_type)
    scored: list[tuple[int, LaunchContentPage]] = []
    for page in rows.all():
        if page.id == ctx.page_id or (page.page_type or "") in {"juridisch", "archief"}:
            continue
        h1 = " ".join((page.signals or {}).get("h1") or [])
        haystack = _tokens(f"{page.title} {h1} {page.path.replace('-', ' ').replace('/', ' ')} {page.focus_keyword or ''}")
        score = len(wanted & haystack)
        if score or not wanted:
            scored.append((score, page))
    scored.sort(key=lambda item: -item[0])
    return {
        "results": [
            {
                "url": page.url,
                "page_type": page.page_type,
                "title": page.title,
                "h1": ((page.signals or {}).get("h1") or [None])[0],
                "focus_keyword": page.focus_keyword,
                "already_linked": url_key(page.url) in linked,
            }
            for _, page in scored[:MAX_RESULTS]
        ],
        "total_matches": len(scored),
    }


CONTENT_LINKS_TOOLS = [find_link_targets]
