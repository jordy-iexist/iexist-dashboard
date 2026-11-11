"""Definitie van de fase-3 checklist: Contentcreatie & Onpage optimalisatie.

Hoofditems en subitems komen uit het Monday-sjabloon "AI website optimalisaties
– Fase 3". Keys hebben de prefix `c3_`, omdat de handmatige status per klant en
item_key wordt opgeslagen (zonder fase-kolom).

`agent`: welke fase-3 agent voorstellen levert voor dit punt (None = geen).
"""
from __future__ import annotations

from typing import Any

from app.features.launch_checklist.services.geo_checklist import (
    ChecklistItem,
    merge_checklist,
)

PHASE = 3
KEY_PREFIX = "c3_"

SECTIONS: list[tuple[str, str]] = [
    ("technisch", "Technische bevindingen uit fase 1 en 2 verwerken"),
    ("bestaand", "Bestaande content optimalisatie"),
    ("nieuw", "Nieuwe content"),
]
SECTION_LABELS = dict(SECTIONS)
SECTION_ISSUE_CATEGORY = {
    "technisch": "techniek",
    "bestaand": "content",
    "nieuw": "content",
}

_ITEMS: list[ChecklistItem] = [
    # --- Technische bevindingen ---------------------------------------------
    ChecklistItem("c3_meta_fixed", "technisch", "Titels en meta descriptions gecorrigeerd op basis van de scan",
                  priority="hoog",
                  description="Hercontrole van de titel- en meta-problemen uit fase 1: ontbrekend, dubbel, te kort of te lang."),
    ChecklistItem("c3_redirects_404", "technisch", "Redirects en 404's op de inhoudspagina's verwerkt",
                  priority="hoog",
                  description="Hercontrole van interne links op de inhoudspagina's: geen links meer naar 404's of redirects."),
    # --- Bestaande content ---------------------------------------------------
    ChecklistItem("c3_keywords", "bestaand", "Teksten analyseren op zoekwoorden, intentie en leesbaarheid",
                  mode="hybrid", priority="hoog"),
    ChecklistItem("c3_headings", "bestaand", "Duidelijkere koppen en opheldering in 2-3 zinnen toevoegen",
                  mode="hybrid", priority="hoog"),
    ChecklistItem("c3_scannable", "bestaand", "Scanbare elementen toevoegen (lijsten, tabellen, kernpunten)",
                  mode="hybrid"),
    ChecklistItem("c3_answer_first", "bestaand", "Antwoord-eerst: direct antwoord in de eerste alinea van elke pagina",
                  mode="hybrid"),
    ChecklistItem("c3_faq", "bestaand", "FAQ toevoegen of optimaliseren (alleen met echte vragen van klanten)",
                  mode="hybrid",
                  description="AI-voorstellen voor vragen zijn kandidaten: altijd verifiëren bij de klant."),
    ChecklistItem("c3_eeat", "bestaand", "EEAT: foto's, projecten en reviews toevoegen", mode="hybrid", priority="hoog"),
    ChecklistItem("c3_conversion", "bestaand", "Conversiepaden website controleren en verbeteren", mode="hybrid"),
    ChecklistItem("c3_meta_title", "bestaand", "Meta titel per pagina: maximaal 60 tekens en 580 pixels"),
    ChecklistItem("c3_meta_description", "bestaand", "Meta description per pagina: maximaal 160 tekens en 920 pixels"),
    ChecklistItem("c3_internal_links", "bestaand",
                  "Interne links toegevoegd naar en vanaf dienst- en blogpagina's, met beschrijvende linktekst",
                  mode="hybrid"),
    ChecklistItem("c3_images", "bestaand", "Afbeeldingen voorzien van alt-tekst en beschrijvende bestandsnamen",
                  mode="hybrid"),
    ChecklistItem("c3_local", "bestaand",
                  "Lokale signalen toegevoegd op locatiepagina's: plaatsnamen, regio en werkgebied", mode="hybrid"),
    # --- Nieuwe content -------------------------------------------------------
    ChecklistItem("c3_landing_pages", "nieuw", "Landingspagina's per dienst en locatie", mode="hybrid", priority="hoog"),
    ChecklistItem("c3_blogs", "nieuw", "Blogs", mode="hybrid", priority="hoog"),
    ChecklistItem("c3_other_content", "nieuw", "Overige content: FAQ-pagina, cases en over-ons",
                  mode="hybrid", priority="hoog"),
    ChecklistItem("c3_unique_expert", "nieuw",
                  "Content is uniek, aantoonbaar en geschreven door de klant of een expert (E-E-A-T)", mode="manual"),
]

ITEMS: dict[str, ChecklistItem] = {i.key: i for i in _ITEMS}

# Welke agent levert voorstellen per checklistpunt.
ITEM_AGENT: dict[str, str] = {
    "c3_meta_title": "content_meta",
    "c3_meta_description": "content_meta",
    "c3_keywords": "content_text",
    "c3_headings": "content_text",
    "c3_scannable": "content_text",
    "c3_answer_first": "content_text",
    "c3_faq": "content_text",
    "c3_eeat": "content_trust",
    "c3_conversion": "content_trust",
    "c3_local": "content_trust",
    "c3_internal_links": "content_links",
    "c3_images": "content_links",
    "c3_landing_pages": "content_gap",
    "c3_blogs": "content_gap",
    "c3_other_content": "content_gap",
}
AGENT_ITEMS: dict[str, list[str]] = {}
for _key, _agent in ITEM_AGENT.items():
    AGENT_ITEMS.setdefault(_agent, []).append(_key)

# Punten die per pagina beoordeeld worden (de rest is siteniveau of handmatig).
PAGE_ITEM_KEYS: list[str] = [i.key for i in _ITEMS if i.section == "bestaand"]
GAP_ITEM_KEYS: list[str] = AGENT_ITEMS["content_gap"]


def merge_content_checklist(auto_items: dict[str, Any] | None, states: dict[str, Any]) -> dict[str, Any]:
    return merge_checklist(auto_items, states, is_webshop=False, sections=SECTIONS, items=_ITEMS)
