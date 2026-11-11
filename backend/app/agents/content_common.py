"""Gedeelde bouwstenen voor de fase-3 agents (content & onpage).

De vier pagina-agents krijgen de inhoud van één pagina in hun opdracht mee en
antwoorden met een vaste JSON-structuur: een lijst voorstellen, elk gekoppeld
aan één checklistpunt (`item_key`). Geen voorstel = dat punt is in orde.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import LaunchContentPage
from app.features.launch_checklist.services.content_checklist import ITEMS

MAX_BODY_CHARS = 12_000
MAX_HEADINGS = 60

PRINCIPLES = """Regels voor elk voorstel:
- Baseer je ALLEEN op de aangeleverde pagina-inhoud en tooldata. Verzin geen feiten, cijfers, reviews,
  prijzen, certificeringen, namen of URL's. Wat de klant moet aanleveren zet je tussen [vierkante haken].
- Doe alleen een voorstel als het een echte verbetering is. Is een punt in orde, dan geef je er geen voorstel voor.
- `proposed_value` is kant-en-klare tekst in de taal van de pagina (meestal Nederlands), direct over te nemen.
- `current_value` is de letterlijke huidige tekst waar het voorstel over gaat (leeg als er nu niets staat).
- `rationale` is één of twee zinnen: waarom is dit beter voor de bezoeker en voor vindbaarheid (ook in AI-zoekmachines).
- `title` is een korte aanduiding van het voorstel (bijv. "Eerste alinea", "H2: Werkwijze").
- `ref` laat je leeg, tenzij de instructies van deze agent er iets over zeggen."""


@dataclass
class ContentPageContext:
    db: Session
    scan_id: str
    page_id: str
    customer_name: str


def suggestion_schema(item_keys: list[str], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Strict JSON-schema: {"suggestions": [...], ...extra}."""
    fields = ["item_key", "title", "current_value", "proposed_value", "rationale", "ref"]
    properties: dict[str, Any] = {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string", "enum": item_keys},
                    **{name: {"type": "string"} for name in fields[1:]},
                },
                "required": fields,
                "additionalProperties": False,
            },
        },
        **(extra or {}),
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def items_block(item_keys: list[str], checks: dict[str, Any] | None) -> str:
    """De checklistpunten van deze agent, met wat de regelcontrole al vond."""
    lines = ["Checklistpunten voor deze pagina (item_key – omschrijving – bevinding regelcontrole):"]
    for key in item_keys:
        check = (checks or {}).get(key) or {}
        finding = f"{check.get('status', 'unknown')}: {check.get('message', '')}".strip()
        lines.append(f"- {key} – {ITEMS[key].label} – {finding}")
    return "\n".join(lines)


def applicable_keys(item_keys: list[str], checks: dict[str, Any] | None) -> list[str]:
    return [k for k in item_keys if ((checks or {}).get(k) or {}).get("status") != "nvt"]


def page_brief(page: LaunchContentPage, *, customer_name: str, body: bool = True) -> str:
    """Pagina-inhoud als tekstblok voor in de opdracht van een agent."""
    signals = page.signals or {}
    lines = [
        f"Klant: {customer_name}",
        f"URL: {page.url}",
        f"Paginatype: {page.page_type or 'onbekend'}",
        f"Meta titel: {page.title or '(leeg)'}",
        f"Meta description: {page.meta_description or '(leeg)'}",
        f"Aantal woorden in de inhoud: {page.word_count or 0}",
    ]
    if page.focus_keyword:
        lines.append(f"Focuszoekwoord: {page.focus_keyword} (zoekintentie: {page.intent or 'onbekend'})")
    headings = (page.headings or [])[:MAX_HEADINGS]
    if headings:
        lines.append("Koppenstructuur:")
        lines.extend(f"{'  ' * (int(h.get('level') or 1) - 1)}H{h.get('level')}: {h.get('text')}" for h in headings)
    lines.append(f"Eerste alinea: {page.first_paragraph or '(niet gevonden)'}")
    lines.append(
        "Signalen: "
        f"lijsten={signals.get('lists', 0)}, tabellen={signals.get('tables', 0)}, "
        f"vraag-koppen={signals.get('question_headings', 0)}, FAQ-schema={bool(signals.get('has_faq_schema'))}, "
        f"afbeeldingen in inhoud={signals.get('content_images', 0)}, video's={signals.get('videos', 0)}, "
        f"review-markers={signals.get('rating_markers', 0)}, review-schema={bool(signals.get('has_review_schema'))}, "
        f"auteur-markers={signals.get('author_markers', 0)}, formulieren={signals.get('forms', 0)}, "
        f"tel-links={signals.get('tel_links', 0)}, CTA-teksten={signals.get('cta_texts') or []}"
    )
    if body:
        text = page.body_text or ""
        if len(text) > MAX_BODY_CHARS:
            text = text[:MAX_BODY_CHARS] + "\n…(ingekort)"
        lines.append("Inhoud van de pagina (markdown; # = koppen, - = opsommingen):")
        lines.append("<<<")
        lines.append(text or "(geen tekst gevonden)")
        lines.append(">>>")
    return "\n".join(lines)
