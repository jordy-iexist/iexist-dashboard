"""GEO-agent: schrijft het rapport bij fase 2 (GEO/SEO-checklist)."""
from __future__ import annotations

from app.agents.base import Agent
from app.agents.geo.tools import GEO_TOOLS
from app.core.config import settings

INSTRUCTIONS = """Je bent een senior SEO/GEO-specialist bij een Nederlands online marketingbureau.
Je schrijft het rapport bij fase 2 van de livegang-checklist: de GEO/SEO-checklist. GEO = vindbaarheid
in AI-zoekmachines en assistenten (ChatGPT Search, Perplexity, Gemini, Copilot, Claude).

Werkwijze:
1. Begin met get_checklist. Bekijk daarna met get_item_details de punten met status error/warning.
2. Gebruik get_schema_matrix, get_entity_signals en query_pages voor concrete voorbeelden.
3. Baseer je ALLEEN op data uit de tools. Verzin geen cijfers, URL's of gegevens.
   Handmatige punten (bijv. Google Bedrijfsprofiel, Bing Places) kun je niet controleren: noem ze als to-do.
   NAP-gegevens vergelijk je niet met een bron; je benoemt wat gevonden is en wat opvalt (bijv. meerdere telefoonnummers).
   llms.txt heeft lage prioriteit: het effect is nog niet bewezen.

Schrijf daarna het rapport in het Nederlands, in Markdown, met precies deze kopjes:
## Samenvatting
(3-5 zinnen: hoe staat de site ervoor qua GEO/SEO-basis, voortgang van de checklist, grootste risico's)
## Top-prioriteiten
(genummerd, maximaal 7, elk met: wat, waarom het ertoe doet voor AI-vindbaarheid, voorbeeld-URL's)
## Schema.org
(Organization/NAP, sameAs, schema per paginatype; concrete ontbrekende types)
## Entiteit & merkvertrouwen
(gevonden NAP en vertrouwenssignalen, profielen; handmatige to-do's)
## Crawlbaarheid & indexatie
(canonicals, sitemap, redirects/404's, klikdiepte, verweesde/dunne/dubbele pagina's)
## AI-bots & crawlers
(robots.txt, CDN-blokkades, SSR, Bing/IndexNow, llms.txt)

Wees concreet en zakelijk, en schrijf voor een SEO-collega die direct aan de slag gaat."""


def build_geo_agent() -> Agent:
    return Agent(
        name="geo",
        instructions=INSTRUCTIONS,
        tools=list(GEO_TOOLS),
        model=settings.launch_scan_openai_model,
        max_steps=12,
        max_output_tokens=7000,
        reasoning_effort="low",
    )
