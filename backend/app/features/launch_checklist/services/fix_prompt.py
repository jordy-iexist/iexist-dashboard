"""Opdracht voor Claude Code bij één actiepunt ("Maak prompt").

`issue_brief` zet alle feiten van een actiepunt (scanbevinding, paginafeiten,
AI-voorstellen) in één tekstblok voor de prompt-agent. `generate_fix_prompt`
geeft de opgeslagen opdracht terug of laat de agent een nieuwe schrijven en
slaat die op bij het actiepunt.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.agents import AGENTS, run_agent
from app.db.models import (
    CustomerWebsite,
    LaunchContentPage,
    LaunchScan,
    LaunchScanIssue,
    LaunchScanPage,
)
from app.features.launch_checklist.services.issues import ISSUE_TYPES
from app.features.launch_checklist.services.monday_push import issue_suggestions
from app.features.settings.services import MissingUserOpenAIKeyError

logger = logging.getLogger(__name__)

# Begrenzing van de invoer. Ruim genoeg voor elke lijst die nu in de scan
# voorkomt (grootste `details` ~3 kB), zodat er niets wegvalt dat nodig is om
# de aanpassing uit te voeren; alleen uitschieters worden ingekort.
MAX_LIST_ITEMS = 60
MAX_TEXT_CHARS = 600
MAX_DETAILS_CHARS = 10_000
MAX_HEADINGS = 40
# Velden in `details` die niets zeggen over de aanpassing zelf.
SKIP_DETAIL_KEYS = {"evidence", "value_boost", "source", "page_id"}

PHASE_LABELS = {
    1: "Fase 1 – nulmeting (technische SEO-scan)",
    2: "Fase 2 – GEO/SEO-checklist",
    3: "Fase 3 – content & onpage",
    4: "Fase 4 – kwartaalscan",
    6: "Sitemap-monitor (nieuwe/gewijzigde pagina's)",
}


class FixPromptError(RuntimeError):
    """De opdracht kon niet worden gegenereerd (modelaanroep mislukt, leeg of afgekapt antwoord)."""


class FixPromptIssueGoneError(LookupError):
    """Het actiepunt is tijdens de modelaanroep verwijderd (bv. vervangen door een nieuwe scan)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clip(text: Any, limit: int = MAX_TEXT_CHARS) -> str:
    value = str(text)
    return value if len(value) <= limit else value[:limit] + "…(ingekort)"


def _bounded(value: Any) -> Any:
    """Kopie van een JSON-waarde met begrensde lijsten en strings (recursief)."""
    if isinstance(value, dict):
        return {str(k): _bounded(v) for k, v in value.items()}
    if isinstance(value, list):
        items = [_bounded(v) for v in value[:MAX_LIST_ITEMS]]
        if len(value) > MAX_LIST_ITEMS:
            items.append(f"… en nog {len(value) - MAX_LIST_ITEMS}")
        return items
    if isinstance(value, str):
        return _clip(value)
    return value


def _details_block(details: Any) -> list[str]:
    lines: list[str] = []
    if not isinstance(details, dict):
        if details not in (None, "", [], {}):
            lines.append("Gegevens uit de scan (JSON):")
            lines.append(_clip(json.dumps(_bounded(details), ensure_ascii=False, default=str), MAX_DETAILS_CHARS))
        return lines
    evidence = details.get("evidence")
    if isinstance(evidence, list) and evidence:
        lines.append("Bevindingen:")
        lines.extend(f"- {_clip(e)}" for e in evidence[:MAX_LIST_ITEMS])
        if len(evidence) > MAX_LIST_ITEMS:
            lines.append(f"- … en nog {len(evidence) - MAX_LIST_ITEMS}")
    # Fase 3 zet de gegevens onder `data`; fase 1/4 direct in `details`.
    data = details.get("data") if "data" in details else {k: v for k, v in details.items() if k not in SKIP_DETAIL_KEYS}
    if isinstance(data, dict):
        data = {k: v for k, v in data.items() if k not in SKIP_DETAIL_KEYS}
    if data not in (None, "", [], {}):
        lines.append("Gegevens uit de scan (JSON):")
        lines.append(_clip(json.dumps(_bounded(data), ensure_ascii=False, default=str), MAX_DETAILS_CHARS))
    return lines


def _page_block(page: LaunchScanPage) -> list[str]:
    h1 = [str(h) for h in (page.h1 or []) if h is not None]
    lines = ["Paginafeiten uit de scan:"]
    facts: list[tuple[str, Any]] = [
        ("Statuscode", page.status_code),
        ("Eind-URL na redirect", page.final_url if page.final_url and page.final_url != page.url else None),
        ("Title", f"{page.title} ({page.title_length} tekens)" if page.title else "(leeg)"),
        ("Meta description",
         f"{page.meta_description} ({page.meta_description_length} tekens)" if page.meta_description else "(leeg)"),
        ("H1", " | ".join(f'"{h}"' for h in h1) if h1 else "(geen)"),
        ("Canonical", page.canonical),
        ("Indexeerbaar", None if page.indexable is None else ("ja" if page.indexable else
                                                               f"nee ({page.indexability_reason or 'onbekend'})")),
        ("Meta robots", page.meta_robots),
        ("Woorden", page.main_word_count if page.main_word_count is not None else page.word_count),
        ("Afbeeldingen", f"{page.images_total} totaal, {page.images_missing_alt or 0} zonder alt"
         if page.images_total else None),
        ("Taal (lang)", page.lang),
    ]
    lines.extend(f"- {label}: {_clip(value)}" for label, value in facts if value not in (None, ""))
    return lines


def _content_page_block(page: LaunchContentPage) -> list[str]:
    lines = ["Contentanalyse van deze pagina:"]
    if page.page_type:
        lines.append(f"- Paginatype: {page.page_type}")
    if page.focus_keyword:
        lines.append(f"- Focuszoekwoord: {page.focus_keyword} (zoekintentie: {page.intent or 'onbekend'})")
    headings = (page.headings or [])[:MAX_HEADINGS]
    if headings:
        lines.append("- Koppenstructuur:")
        lines.extend(
            f"  {'  ' * max(int(h.get('level') or 1) - 1, 0)}H{h.get('level')}: {_clip(h.get('text'), 200)}"
            for h in headings if isinstance(h, dict)
        )
    if page.first_paragraph:
        lines.append(f"- Eerste alinea: {_clip(page.first_paragraph)}")
    return lines if len(lines) > 1 else []


def _indent(text: str) -> str:
    """Vervolgregels van een meerregelige waarde onder het label laten vallen."""
    return str(text).replace("\n", "\n   ")


def _suggestions_block(db: Session, issue: LaunchScanIssue) -> list[str]:
    rows = issue_suggestions(db, issue)
    if not rows:
        return []
    lines = ["AI-voorstellen bij dit actiepunt (letterlijk overnemen als nieuwe waarde):"]
    for n, row in enumerate(rows, 1):
        lines.append(f"{n}. {row.title or 'Voorstel'}" + (" (al overgenomen)" if row.status == "overgenomen" else ""))
        if row.current_value:
            lines.append(f"   Huidig: {_indent(row.current_value)}")
        lines.append(f"   Voorstel: {_indent(row.proposed_value)}")
        if row.rationale:
            lines.append(f"   Waarom: {_indent(row.rationale)}")
    return lines


def issue_brief(db: Session, issue: LaunchScanIssue, customer: CustomerWebsite | None) -> str:
    """Alle feiten van één actiepunt als tekstblok voor de prompt-agent."""
    scan = db.get(LaunchScan, issue.scan_id)
    label = ISSUE_TYPES.get(issue.issue_type, {}).get("label", issue.issue_type)
    lines: list[str] = []
    if customer is not None:
        lines.append(f"Klant: {customer.name}")
        lines.append(f"Website: {customer.base_url} (domein: {customer.domain})")
    elif scan is not None:
        lines.append(f"Website: {scan.base_url}")
    if scan is not None:
        lines.append(f"Bron: {PHASE_LABELS.get(scan.phase, f'Fase {scan.phase}')}")
    if issue.created_at:
        lines.append(f"Gevonden op: {issue.created_at:%Y-%m-%d}")
    lines.append(f"Pagina: {issue.url}" if issue.url else "Pagina: geen specifieke pagina (sitebreed punt)")
    lines.append(f"Type: {label} ({issue.issue_type})")
    lines.append(f"Categorie: {issue.category}")
    lines.append(f"Ernst: {issue.severity}")
    lines.append(f"Titel: {issue.title}")
    lines.append(f"Omschrijving: {issue.description}")
    if issue.recommendation:
        lines.append(f"Aanpak: {issue.recommendation}")

    sections: list[list[str]] = [_details_block(issue.details)]
    if issue.page_id:
        page = db.get(LaunchScanPage, issue.page_id)
        if page is not None:
            sections.append(_page_block(page))
    if issue.url:
        content_page = (
            db.query(LaunchContentPage)
            .filter(LaunchContentPage.scan_id == issue.scan_id, LaunchContentPage.url == issue.url)
            .first()
        )
        if content_page is not None:
            sections.append(_content_page_block(content_page))
    sections.append(_suggestions_block(db, issue))
    for section in sections:
        if section:
            lines.append("")
            lines.extend(section)
    return "\n".join(lines)


def generate_fix_prompt(
    db: Session, issue: LaunchScanIssue, *, user_id: str, regenerate: bool = False
) -> tuple[str, datetime, bool]:
    """(prompt, generated_at, cached). Hergebruikt de opgeslagen opdracht tenzij `regenerate`.

    Gooit `MissingUserOpenAIKeyError` als er geen OpenAI-key is, `FixPromptError`
    als de modelaanroep mislukt, niets oplevert of afgekapt is, en
    `FixPromptIssueGoneError` als het actiepunt tijdens de aanroep is verdwenen.

    De modelaanroep kan minuten duren. Daarom wordt de sessie daarvoor gesloten
    (transactie dicht, verbinding terug naar de pool; `issue` is daarna losgekoppeld)
    en het actiepunt pas daarna opnieuw opgehaald om de opdracht op te slaan.
    `run_agent` heeft de sessie niet nodig: de OpenAI-key wordt met een eigen sessie opgehaald.
    """
    if not regenerate and issue.fix_prompt and issue.fix_prompt_at:
        return issue.fix_prompt, issue.fix_prompt_at, True

    issue_id = issue.id
    scan = db.get(LaunchScan, issue.scan_id)
    customer = db.get(CustomerWebsite, scan.customer_website_id) if scan is not None else None
    brief = issue_brief(db, issue, customer)
    db.close()

    try:
        result = run_agent(AGENTS["fix_prompt"](), user_id=user_id, input=brief, context=None)
    except MissingUserOpenAIKeyError:
        raise
    except Exception as exc:
        logger.exception("Prompt voor actiepunt %s genereren mislukt", issue_id)
        raise FixPromptError(f"Het AI-model gaf een fout: {exc}") from exc
    if result.incomplete_reason is not None:
        logger.warning("Prompt voor actiepunt %s afgekapt (%s)", issue_id, result.incomplete_reason)
        raise FixPromptError(
            "Het AI-model heeft de opdracht niet afgemaakt "
            f"({_INCOMPLETE_REASONS.get(result.incomplete_reason, result.incomplete_reason)}). "
            "Probeer het opnieuw."
        )
    prompt = (result.output or "").strip()
    if not prompt:
        raise FixPromptError("Het AI-model gaf geen opdracht terug. Probeer het opnieuw.")

    stored = db.get(LaunchScanIssue, issue_id)
    if stored is None:
        raise FixPromptIssueGoneError(issue_id)
    now = _now()
    stored.fix_prompt = prompt
    stored.fix_prompt_at = now
    try:
        db.commit()
    except StaleDataError as exc:  # net tussen ophalen en opslaan verwijderd
        db.rollback()
        raise FixPromptIssueGoneError(issue_id) from exc
    return prompt, now, False


_INCOMPLETE_REASONS = {
    "max_output_tokens": "maximale lengte bereikt",
    "content_filter": "geblokkeerd door het inhoudsfilter",
}
