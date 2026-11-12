"""Definitie van de fase-4 checklist: Kwartaal GEO-werkzaamheden.

Punten komen uit het Monday-sjabloon "AI website optimalisaties – Fase 4". Anders
dan fase 2 en 3 is fase 4 terugkerend: elke ronde (kwartaal) heeft een eigen
handmatige status. Keys hebben de prefix `c4_`; de handmatige status wordt per
klant, item_key en ronde (`period`) opgeslagen.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.features.launch_checklist.services.geo_checklist import (
    ChecklistItem,
    merge_checklist,
)

PHASE = 4
KEY_PREFIX = "c4_"

SECTIONS: list[tuple[str, str]] = [
    ("meting", "Meting & vergelijking"),
    ("rapportage", "Rapportage"),
    ("controle", "Controle & onderhoud"),
]
SECTION_LABELS = dict(SECTIONS)

_ITEMS: list[ChecklistItem] = [
    # --- Meting ---------------------------------------------------------------
    ChecklistItem("c4_ai_scan", "meting", "Nieuwe AI scan uitvoeren en vergelijken",
                  priority="hoog",
                  description="De fase 4-scan herhaalt de nulmeting en vergelijkt AI-vindbaarheid, actiepunten, "
                              "pagina's en backlinks met de vorige ronde (of met de nulmeting)."),
    ChecklistItem("c4_proranktracker", "meting", "ProRankTracker AI overzicht", mode="manual",
                  description="Bekijk in ProRankTracker de AI-zichtbaarheid (AI Overviews, AI Mode, ChatGPT, "
                              "Gemini, Perplexity, Copilot) en noteer de belangrijkste veranderingen."),
    # --- Rapportage -----------------------------------------------------------
    ChecklistItem("c4_monthly_report", "rapportage",
                  "Maandrapportage opstellen: Search Console, GA4, posities, AI-zichtbaarheid en backlinks",
                  mode="hybrid",
                  description="Het dashboard schrijft een conceptrapport uit de scan, posities (SEO-tracker), "
                              "backlinks (Ahrefs) en, als de koppeling er is, Search Console. Cijfers uit GA4 "
                              "(en Search Console zonder koppeling) vul je zelf aan."),
    # --- Controle -------------------------------------------------------------
    ChecklistItem("c4_search_console", "controle",
                  "Search Console en Bing Webmaster controleren op fouten en nieuwe indexatieproblemen",
                  mode="hybrid", priority="hoog",
                  description="Met de Search Console-koppeling controleert de scan de klikken t.o.v. de vorige "
                              "periode, de ingediende sitemaps en de indexstatus van nieuwe pagina's. Het rapport "
                              "Pagina-indexering, Verbeteringen en Bing Webmaster (Crawlfouten) controleer je zelf; "
                              "vink het punt daarna af."),
    ChecklistItem("c4_new_pages", "controle", "Indexatie en 404's controleren op nieuwe pagina's",
                  priority="hoog",
                  description="Nieuwe pagina's sinds de vorige ronde moeten bereikbaar en indexeerbaar zijn (geen "
                              "noindex, eigen canonical, in de sitemap). Pagina's die eerder werkten mogen geen 404 "
                              "geven. Of Google ze echt heeft opgenomen staat bij het Search Console-punt."),
    ChecklistItem("c4_schema_validation", "controle", "Schema-validatie na elke wijziging",
                  description="Alle JSON-LD op de site moet geldig zijn en de verplichte eigenschappen per type "
                              "bevatten. Scan opnieuw na een wijziging; de afvinkstatus van de ronde blijft staan."),
]

ITEMS: dict[str, ChecklistItem] = {i.key: i for i in _ITEMS}

# Categorie van de actiepunten per checklistpunt.
ITEM_ISSUE_CATEGORY: dict[str, str] = {
    "c4_ai_scan": "ai",
    "c4_new_pages": "techniek",
    "c4_search_console": "techniek",
    "c4_schema_validation": "schema",
}


def merge_quarterly_checklist(auto_items: dict[str, Any] | None, states: dict[str, Any]) -> dict[str, Any]:
    return merge_checklist(auto_items, states, is_webshop=False, sections=SECTIONS, items=_ITEMS)


# --- rondes ------------------------------------------------------------------

try:
    _TZ: Any = ZoneInfo("Europe/Amsterdam")
except ZoneInfoNotFoundError:  # image zonder tz-database: kwartaalgrenzen in UTC
    _TZ = timezone.utc

_PERIOD_RE = re.compile(r"^(\d{4})-Q([1-4])$")


def period_of(moment: datetime | None = None) -> str:
    """Ronde (kwartaal) van een moment, bijv. "2026-Q4"."""
    local = (moment or datetime.now(timezone.utc)).astimezone(_TZ)
    return f"{local.year}-Q{(local.month - 1) // 3 + 1}"


def is_period(value: str | None) -> bool:
    return bool(value and _PERIOD_RE.match(value))


def period_label(period: str | None) -> str:
    match = _PERIOD_RE.match(period or "")
    if not match:
        return period or ""
    return f"Q{match.group(2)} {match.group(1)}"
