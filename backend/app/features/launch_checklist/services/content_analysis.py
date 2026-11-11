"""Fase 3: AI-analyse draaien en de voorstellen opslaan.

`analyse_page` draait de vier pagina-agents op één pagina (tekst & structuur
eerst, die bepaalt het focuszoekwoord voor de rest). `run_gap` draait de
contentgap-agent op siteniveau, `run_report` de rapport-agent. Elke functie
opent zijn eigen database-sessie, zodat ze vanuit een threadpool kunnen draaien.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.agents import AGENTS, run_agent
from app.agents.base import Agent, AgentRunResult, image_part, text_part
from app.agents.content_common import (
    ContentPageContext,
    applicable_keys,
    items_block,
    page_brief,
)
from app.agents.content_gap.tools import ContentSiteContext
from app.agents.content_links.agent import build_content_links_agent
from app.agents.content_text.agent import build_content_text_agent
from app.agents.content_trust.agent import build_content_trust_agent
from app.core.config import settings
from app.db.models import LaunchContentPage, LaunchContentSuggestion, LaunchScan
from app.db.session import SessionLocal
from app.features.launch_checklist.services.content_checklist import AGENT_ITEMS, ITEMS
from app.features.launch_checklist.services.content_checks import images_needing_work
from app.features.launch_checklist.services.content_rebuild import sync_suggestion_issues
from app.features.launch_checklist.services.pixel_width import (
    description_width,
    fits_description,
    fits_title,
    title_width,
)

logger = logging.getLogger(__name__)

MAX_VALUE_CHARS = 8000
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Usage:
    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def add(self, result: AgentRunResult) -> None:
        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens
        self.calls += 1

    def merge(self, other: dict[str, int]) -> None:
        self.input_tokens += int(other.get("input_tokens") or 0)
        self.output_tokens += int(other.get("output_tokens") or 0)
        self.calls += int(other.get("calls") or 0)

    def to_dict(self) -> dict[str, int]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "calls": self.calls}


def _clean_suggestions(raw: Any, allowed: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or entry.get("item_key") not in allowed:
            continue
        proposed = str(entry.get("proposed_value") or "").strip()
        if not proposed:
            continue
        out.append({
            "item_key": entry["item_key"],
            "title": str(entry.get("title") or "").strip()[:300],
            "current_value": str(entry.get("current_value") or "").strip()[:MAX_VALUE_CHARS],
            "proposed_value": proposed[:MAX_VALUE_CHARS],
            "rationale": str(entry.get("rationale") or "").strip()[:2000],
            "ref": str(entry.get("ref") or "").strip()[:2000],
        })
    return out


def _store(
    db: Session, scan: LaunchScan, page_id: str | None, agent: str,
    suggestions: list[dict[str, Any]],
) -> None:
    """Vervang de open voorstellen van deze agent; afgehandelde voorstellen blijven staan."""
    query = db.query(LaunchContentSuggestion).filter(
        LaunchContentSuggestion.scan_id == scan.id,
        LaunchContentSuggestion.agent == agent,
        LaunchContentSuggestion.status == "open",
    )
    if page_id is None:
        query = query.filter(LaunchContentSuggestion.content_page_id.is_(None))
    else:
        query = query.filter(LaunchContentSuggestion.content_page_id == page_id)
    query.delete(synchronize_session=False)
    now = _now()
    for s in suggestions:
        details = dict(s.get("details") or {})
        if s.get("ref"):
            details["ref"] = s["ref"]
        db.add(LaunchContentSuggestion(
            id=str(uuid.uuid4()),
            scan_id=scan.id,
            customer_website_id=scan.customer_website_id,
            content_page_id=page_id,
            item_key=s["item_key"],
            agent=agent,
            title=s.get("title") or None,
            current_value=s.get("current_value") or None,
            proposed_value=s["proposed_value"],
            rationale=s.get("rationale") or None,
            details=details or None,
            status="open",
            created_at=now,
            updated_at=now,
        ))


# --- meta: harde lengtecontrole -------------------------------------------------

def _meta_fits(key: str, value: str) -> bool:
    return fits_title(value) if key == "c3_meta_title" else fits_description(value)


def _meta_size(key: str, value: str) -> str:
    width = title_width(value) if key == "c3_meta_title" else description_width(value)
    return f"{len(value)} tekens, ±{width} px"


def _trim_to_fit(key: str, value: str) -> str:
    words = value.split()
    while len(words) > 1 and not _meta_fits(key, " ".join(words)):
        words.pop()
    return " ".join(words).rstrip(" -–|,:;")


def _run_meta(agent: Agent, prompt: str, *, user_id: str, ctx: Any, usage: Usage, keys: list[str]) -> list[dict[str, Any]]:
    result = run_agent(agent, user_id=user_id, input=prompt, context=ctx)
    usage.add(result)
    suggestions = _clean_suggestions(result.parsed().get("suggestions"), keys)
    too_long = [s for s in suggestions if not _meta_fits(s["item_key"], s["proposed_value"])]
    if too_long:
        feedback = "\n".join(
            f"- {s['item_key']}: \"{s['proposed_value']}\" is te lang ({_meta_size(s['item_key'], s['proposed_value'])})."
            for s in too_long
        )
        retry = run_agent(
            agent, user_id=user_id, context=ctx,
            input=f"{prompt}\n\nJe vorige voorstel paste niet binnen de grenzen:\n{feedback}\n"
                  "Geef opnieuw alle voorstellen, nu korter (meta titel hooguit 55 tekens, description hooguit 130).",
        )
        usage.add(retry)
        suggestions = _clean_suggestions(retry.parsed().get("suggestions"), keys)
    for s in suggestions:
        value = s["proposed_value"]
        if not _meta_fits(s["item_key"], value):
            s["proposed_value"] = _trim_to_fit(s["item_key"], value)
            s["details"] = {"trimmed_from": value}
        final = s["proposed_value"]
        s.setdefault("details", {})
        s["details"].update({
            "length": len(final),
            "pixels": title_width(final) if s["item_key"] == "c3_meta_title" else description_width(final),
        })
    return suggestions


# --- links & afbeeldingen ---------------------------------------------------------

def _vision_images(page: LaunchContentPage) -> list[dict[str, Any]]:
    limit = settings.launch_content_max_images_per_page
    images = [
        i for i in images_needing_work(page)
        if str(i.get("filename") or "").lower().endswith(_IMAGE_EXTENSIONS)
    ]
    return images[:limit] if limit else []


def _links_prompt(page: LaunchContentPage, brief: str, keys: list[str], images: list[dict[str, Any]]) -> str:
    parts = [brief, "", items_block(keys, page.checks)]
    content_links = [l for l in (page.links or []) if l.get("in_content")][:60]
    if "c3_internal_links" in keys:
        parts.append("\nHuidige links in de inhoud (linktekst → url):")
        parts.extend(f"- {l.get('text') or '(geen tekst)'} → {l['url']}" for l in content_links)
        if not content_links:
            parts.append("- (geen)")
    if "c3_images" in keys:
        parts.append("\nAfbeeldingen die een voorstel nodig hebben (in deze volgorde meegestuurd):")
        for index, image in enumerate(images, 1):
            alt = "ontbreekt" if image.get("alt") is None else f"\"{image.get('alt')}\""
            parts.append(f"{index}. url: {image['src']} | bestandsnaam: {image['filename']} | alt: {alt}")
    return "\n".join(parts)


def _run_links(
    page: LaunchContentPage, brief: str, keys: list[str], *, user_id: str, ctx: Any, usage: Usage,
    warnings: list[str],
) -> list[dict[str, Any]]:
    images = _vision_images(page) if "c3_images" in keys else []
    if "c3_images" in keys and not images:
        keys = [k for k in keys if k != "c3_images"]
    if not keys:
        return []
    agent = build_content_links_agent(keys)
    prompt = _links_prompt(page, brief, keys, images)
    if images:
        try:
            result = run_agent(
                agent, user_id=user_id, context=ctx,
                input=[text_part(prompt), *[image_part(i["src"]) for i in images]],
            )
            usage.add(result)
            return _clean_suggestions(result.parsed().get("suggestions"), keys)
        except Exception as exc:  # afbeelding niet op te halen door het model: zonder beeld verder
            logger.warning("Vision faalde voor %s: %s", page.url, exc)
            warnings.append(f"{page.path}: afbeeldingen konden niet worden bekeken; alt-teksten op basis van context.")
            prompt += "\n\nLet op: de afbeeldingen konden niet worden meegestuurd. Baseer je op bestandsnaam en context."
    result = run_agent(agent, user_id=user_id, input=prompt, context=ctx)
    usage.add(result)
    return _clean_suggestions(result.parsed().get("suggestions"), keys)


def _ranking_note(hint: dict[str, Any] | None, keyword: str | None) -> str:
    """' (positie 4 in Google, circa 320 zoekopdrachten per maand)' als de Ahrefs-data bij dit zoekwoord hoort."""
    if not hint or not keyword or hint.get("keyword") != keyword:
        return ""
    parts = []
    if hint.get("position") is not None:
        parts.append(f"positie {hint['position']} in Google")
    if hint.get("volume") is not None:
        parts.append(f"circa {hint['volume']} zoekopdrachten per maand")
    return f" ({', '.join(parts)})" if parts else ""


# --- per pagina ---------------------------------------------------------------------

def analyse_page(scan_id: str, page_id: str, *, user_id: str, customer_name: str) -> dict[str, Any]:
    """Draai de pagina-agents op één pagina. Geeft {"ok", "warnings", "usage"} terug."""
    usage = Usage()
    warnings: list[str] = []
    with SessionLocal() as db:
        scan = db.get(LaunchScan, scan_id)
        page = db.get(LaunchContentPage, page_id)
        if scan is None or page is None or page.scan_id != scan_id:
            return {"ok": False, "warnings": ["Pagina niet gevonden."], "usage": usage.to_dict()}
        page.analysis_status = "running"
        page.analysis_error = None
        db.commit()

        ctx = ContentPageContext(db=db, scan_id=scan_id, page_id=page_id, customer_name=customer_name)
        checks = page.checks or {}
        succeeded = 0
        errors: list[str] = []

        def attempt(agent_name: str, fn: Any) -> None:
            nonlocal succeeded
            try:
                suggestions = fn()
            except Exception as exc:
                db.rollback()
                logger.warning("Agent %s faalde voor %s: %s", agent_name, page.url, exc)
                errors.append(f"{agent_name}: {exc}")
                return
            _store(db, scan, page_id, agent_name, suggestions)
            db.commit()
            succeeded += 1

        # 1. Tekst & structuur (bepaalt ook focuszoekwoord en intentie)
        text_keys = applicable_keys(AGENT_ITEMS["content_text"], checks)

        # Een zoekwoord dat niet van de AI komt (handmatig of Ahrefs) ligt vast.
        fixed_keyword = bool(page.focus_keyword) and page.keyword_source not in (None, "ai")
        ahrefs_hint = (page.signals or {}).get("ahrefs") or None

        def run_text() -> list[dict[str, Any]]:
            prompt = (
                f"{page_brief(page, customer_name=customer_name)}\n\n{items_block(text_keys, checks)}"
                if text_keys else
                f"{page_brief(page, customer_name=customer_name)}\n\n"
                "Er zijn geen checklistpunten van toepassing: bepaal alleen focus_keyword, intent en readability."
            )
            if fixed_keyword:
                origin = (
                    f"komt uit Ahrefs{_ranking_note(ahrefs_hint, page.focus_keyword)}"
                    if page.keyword_source == "ahrefs" else "is vastgesteld door de gebruiker"
                )
                prompt += (
                    f"\n\nHet focuszoekwoord {origin}: \"{page.focus_keyword}\". "
                    "Leid zelf geen ander zoekwoord af: geef exact dit zoekwoord terug als focus_keyword en "
                    "baseer alle voorstellen hierop."
                )
            elif ahrefs_hint:
                prompt += (
                    f"\n\nTer info uit Ahrefs: de pagina krijgt nu het meeste organische verkeer via "
                    f"\"{ahrefs_hint.get('keyword')}\"{_ranking_note(ahrefs_hint, ahrefs_hint.get('keyword'))}. "
                    "Weeg dit mee bij het bepalen van het focuszoekwoord, maar kies een ander zoekwoord als "
                    "dat beter bij de inhoud van de pagina past."
                )
            agent = build_content_text_agent(text_keys or AGENT_ITEMS["content_text"])
            result = run_agent(agent, user_id=user_id, input=prompt, context=ctx)
            usage.add(result)
            data = result.parsed()
            keyword = str(data.get("focus_keyword") or "").strip()[:200]
            intent = str(data.get("intent") or "").strip()[:40] or None
            if fixed_keyword:
                # Handmatig of Ahrefs-zoekwoord blijft staan; alleen een lege intentie vullen we aan.
                page.intent = page.intent or intent
            elif keyword:
                page.focus_keyword = keyword
                page.intent = intent
                page.keyword_source = "ai"
            page.signals = {**(page.signals or {}), "readability": str(data.get("readability") or "")[:600]}
            return _clean_suggestions(data.get("suggestions"), text_keys)

        attempt("content_text", run_text)
        brief = page_brief(page, customer_name=customer_name)

        # 2. Meta titel + description
        meta_keys = AGENT_ITEMS["content_meta"]
        attempt("content_meta", lambda: _run_meta(
            AGENTS["content_meta"](), f"{brief}\n\n{items_block(meta_keys, checks)}",
            user_id=user_id, ctx=ctx, usage=usage, keys=meta_keys,
        ))

        # 3. Vertrouwen & conversie
        trust_keys = applicable_keys(AGENT_ITEMS["content_trust"], checks)
        if trust_keys:
            def run_trust() -> list[dict[str, Any]]:
                result = run_agent(
                    build_content_trust_agent(trust_keys), user_id=user_id, context=ctx,
                    input=f"{brief}\n\n{items_block(trust_keys, checks)}",
                )
                usage.add(result)
                return _clean_suggestions(result.parsed().get("suggestions"), trust_keys)

            attempt("content_trust", run_trust)

        # 4. Interne links & afbeeldingen
        link_keys = applicable_keys(AGENT_ITEMS["content_links"], checks)
        if link_keys:
            attempt("content_links", lambda: _run_links(
                page, brief, link_keys, user_id=user_id, ctx=ctx, usage=usage, warnings=warnings,
            ))

        page = db.get(LaunchContentPage, page_id)
        if succeeded == 0:
            page.analysis_status = "failed"
            page.analysis_error = "; ".join(errors)[:1000]
            warnings.append(f"{page.path}: AI-analyse mislukt ({errors[0] if errors else 'onbekende fout'}).")
        else:
            page.analysis_status = "done"
            page.analysis_error = "; ".join(errors)[:1000] or None
            page.analyzed_at = _now()
            if errors:
                warnings.append(f"{page.path}: een deel van de AI-analyse is mislukt ({len(errors)} agent(s)).")
            sync_suggestion_issues(db, scan, page)
        db.commit()
        return {"ok": succeeded > 0, "warnings": warnings, "usage": usage.to_dict()}


# --- siteniveau -----------------------------------------------------------------------

def run_gap(scan_id: str, *, user_id: str, customer_name: str) -> dict[str, int]:
    """Contentgap-agent: voorstellen voor nieuwe content (zonder pagina)."""
    usage = Usage()
    with SessionLocal() as db:
        scan = db.get(LaunchScan, scan_id)
        if scan is None:
            return usage.to_dict()
        keys = AGENT_ITEMS["content_gap"]
        items = (scan.checklist or {}).get("items") or {}
        findings = "\n".join(
            f"- {key} – {ITEMS[key].label} – {(items.get(key) or {}).get('message', '')}" for key in keys
        )
        result = run_agent(
            AGENTS["content_gap"](), user_id=user_id,
            input=f"Bepaal welke nieuwe content ontbreekt voor {customer_name} ({scan.base_url}).\n\n"
                  f"Checklistpunten (item_key – omschrijving – bevinding regelcontrole):\n{findings}",
            context=ContentSiteContext(
                db=db, scan_id=scan_id, source_scan_id=scan.source_scan_id, customer_name=customer_name),
        )
        usage.add(result)
        _store(db, scan, None, "content_gap", _clean_suggestions(result.parsed().get("suggestions"), keys))
        scan.checklist = {**(scan.checklist or {}), "gap_analyzed_at": _now().isoformat()}
        db.commit()
    return usage.to_dict()


def run_report(scan_id: str, *, user_id: str, customer_name: str) -> AgentRunResult:
    with SessionLocal() as db:
        scan = db.get(LaunchScan, scan_id)
        return run_agent(
            AGENTS["content_report"](), user_id=user_id,
            input=f"Schrijf het rapport Contentcreatie & Onpage optimalisatie (fase 3) voor {customer_name} "
                  f"({scan.base_url if scan else ''}).",
            context=ContentSiteContext(
                db=db, scan_id=scan_id, source_scan_id=scan.source_scan_id if scan else None,
                customer_name=customer_name),
        )
