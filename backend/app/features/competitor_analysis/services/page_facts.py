"""On-page-kenmerken van één opgehaalde pagina, uit `extract_content`.

`onpage_from_extract` vult het `OnPage`-schema (de JSON-kolom `competitor_analysis_pages.onpage`);
`is_unreadable` zegt of een pagina zo weinig tekst heeft dat hij waarschijnlijk met JavaScript
wordt opgebouwd. Zo'n pagina telt niet mee in de medianen en gaat niet mee naar Claude.
"""
from __future__ import annotations

from typing import Any

from app.features.competitor_analysis.schemas import MAX_HEADINGS, Heading, OnPage
from app.features.launch_checklist.services.content_extract import ContentExtract
from app.features.launch_checklist.services.geo_extract import _FAQ_TEXT_RE

# Onder dit aantal woorden is de pagina "mogelijk niet leesbaar".
MIN_READABLE_WORDS = 50

# Zelfde drempels als het FAQ-signaal in `launch_checklist/services/geo_extract.py`.
FAQ_MIN_DETAILS = 2
FAQ_MIN_QUESTION_HEADINGS = 3


def has_faq(extract: ContentExtract) -> bool:
    """Heeft de pagina een FAQ-blok?

    Zelfde regel als `geo_extract` (signaal `faq`): minstens twee uitklapblokken, minstens drie
    koppen die een vraag zijn, of het woord "veelgestelde vragen"/"FAQ" met minstens één
    vraagkop. Een FAQPage-schema telt ook als FAQ.
    """
    signals = extract.signals or {}
    details = int(signals.get("details_count") or 0)
    questions = int(signals.get("question_headings") or 0)
    if signals.get("has_faq_schema"):
        return True
    if details >= FAQ_MIN_DETAILS or questions >= FAQ_MIN_QUESTION_HEADINGS:
        return True
    return bool(questions >= 1 and _FAQ_TEXT_RE.search(extract.body_text or ""))


def _first_h1(extract: ContentExtract) -> str | None:
    for heading in extract.headings:
        if heading.get("level") == 1 and str(heading.get("text") or "").strip():
            return str(heading["text"]).strip()
    # Een H1 buiten de hoofdinhoud (bijv. in een hero die als chrome geldt).
    for text in (extract.signals or {}).get("h1") or []:
        if str(text).strip():
            return str(text).strip()
    return None


def onpage_from_extract(extract: ContentExtract) -> OnPage:
    """Zet een `ContentExtract` om naar het `OnPage`-schema.

    - `headings`: de koppen H1–H4 in documentvolgorde, hooguit `MAX_HEADINGS`.
    - `internal_links`: aantal unieke interne URL's waarnaar de pagina linkt (menu en footer
      inbegrepen; `extract_content` houdt dezelfde link op verschillende plekken apart).
    - `images`: aantal afbeeldingen (zonder trackingpixels en data-URL's).
    """
    headings = [
        Heading(level=int(h["level"]), text=str(h.get("text") or "").strip())
        for h in extract.headings
        if isinstance(h.get("level"), int) and 1 <= h["level"] <= 6 and str(h.get("text") or "").strip()
    ]
    signals = extract.signals or {}
    return OnPage(
        title=extract.title or None,
        meta_description=extract.meta_description or None,
        h1=_first_h1(extract),
        h2_count=sum(1 for h in headings if h.level == 2),
        h3_count=sum(1 for h in headings if h.level == 3),
        headings=headings[:MAX_HEADINGS],
        word_count=int(extract.word_count or 0),
        internal_links=len({link.get("url") for link in extract.links if link.get("url")}),
        images=len(extract.images),
        has_faq=has_faq(extract),
        schema_types=list(signals.get("schema_types") or []),
    )


def as_onpage(value: Any) -> OnPage | None:
    """`OnPage` uit een model of uit de JSON-kolom (dict); `None` als er niets is uitgelezen."""
    if value is None:
        return None
    if isinstance(value, OnPage):
        return value
    if isinstance(value, dict):
        return OnPage.model_validate(value)
    return None


def is_unreadable(onpage: OnPage | dict | None) -> bool:
    """Minder dan `MIN_READABLE_WORDS` woorden: waarschijnlijk met JavaScript opgebouwd.

    Alleen zinvol voor een opgehaalde pagina; zonder on-page-gegevens is het antwoord False
    (die pagina is niet uitgelezen, niet "onleesbaar").
    """
    page = as_onpage(onpage)
    if page is None:
        return False
    return page.word_count < MIN_READABLE_WORDS
