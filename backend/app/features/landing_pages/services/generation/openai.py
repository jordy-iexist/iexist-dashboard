import re

from app.core.config import settings
from app.services.openai import create_response

SYSTEM_PROMPT = (
"""
Je bent een ervaren SEO-copywriter die Nederlandstalige landingspagina's schrijft. Je schrijft voor zowel zoekmachines als menselijke lezers — conversie en ranking gaan hand in hand.

## Structuur
- **H1**: bevat het primaire zoekwoord, max 70 tekens, prikkelend maar niet clickbait.
- **Intro (50–100 woorden)**: benoem het probleem, beloof de oplossing, primair zoekwoord in de eerste zin. Directe aanspreekvorm (jij/je).
- **H2/H3 hiërarchie**: logisch en scanbaar. Zoekwoorden verwerken waar dat natuurlijk valt.
- **Body**: informatief, gericht op de lezer. Gebruik concrete details en voorbeelden.
- **FAQ**: 6 vragen, antwoorden van 50–100 woorden, long-tail zoektermen verwerkt.
- **CTA**: elke sectie sluit af met een subtiele richting naar de website. Einde: expliciete call-to-action.

## SEO-principes
- **Keyword density**: primair keyword ~1–2%. Forceer niets.
- **Semantische dekking**: behandel gerelateerde subtopics en entities.
- **E-E-A-T**: laat expertise en autoriteit zien via concrete voorbeelden en specifieke nuances.

## Schrijfstijl
- Helder, direct Nederlands. Actieve zinnen. Tweede persoon (je/jij).
- Geen fluff, geen AI-tells ("duik in", "ontgrendel", "in het rijk van").
- Concreet boven abstract.

## Uitvoerformaat
Lever de output in dit exacte formaat — begin altijd met de YAML frontmatter:

---
meta_title: [maximaal 60 tekens, hoofdzoekwoord aan het begin]
meta_description: [120–155 tekens, aantrekkelijk, met CTA]
slug: [korte URL, alleen lowercase en koppeltekens, bijv. glad-stucwerk]
---

[De volledige landingspagina in Markdown hieronder]

## Wat je niet doet
- Geen verzonnen statistieken of bronnen.
- Geen zoekwoord-herhaling in elke kop.
- Geen emoji's.
- Geen meta-commentaar.
"""
)

_FRONTMATTER_REGEX = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def generate_landing_page(
    prompt: str,
    *,
    user_id: str,
    system_prompt: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    max_output_tokens: int | None = None,
) -> str:
    response = create_response(
        user_id=user_id,
        model=model or settings.openai_blog_model,
        instructions=system_prompt or SYSTEM_PROMPT,
        input=prompt,
        max_output_tokens=max_output_tokens if max_output_tokens is not None else 4000,
        reasoning={"effort": reasoning_effort or settings.openai_blog_reasoning_effort},
    )
    return str(getattr(response, "output_text", "") or "").strip()


def parse_landing_page_output(raw: str) -> tuple[str, str, str, str]:
    match = _FRONTMATTER_REGEX.match(raw.strip())
    if not match:
        return ("", "", "", raw.strip())

    frontmatter_block = match.group(1)
    body_markdown = match.group(2).strip()

    meta_title = ""
    meta_description = ""
    slug = ""

    for line in frontmatter_block.splitlines():
        stripped = line.strip()
        if stripped.startswith("meta_title:"):
            meta_title = stripped[len("meta_title:"):].strip()
        elif stripped.startswith("meta_description:"):
            meta_description = stripped[len("meta_description:"):].strip()
        elif stripped.startswith("slug:"):
            slug = stripped[len("slug:"):].strip()

    if not meta_title or not meta_description or not slug:
        return ("", "", "", raw.strip())

    return (meta_title, meta_description, slug, body_markdown)
