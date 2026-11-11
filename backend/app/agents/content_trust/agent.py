"""Vertrouwen & conversie-agent (fase 3): EEAT, conversiepaden, lokale signalen."""
from __future__ import annotations

from app.agents.base import Agent
from app.agents.content_common import PRINCIPLES, suggestion_schema
from app.core.config import settings

ITEM_KEYS = ["c3_eeat", "c3_conversion", "c3_local"]

INSTRUCTIONS = f"""Je bent een senior CRO- en SEO-specialist bij een Nederlands online marketingbureau.
Je beoordeelt één pagina op vertrouwen (E-E-A-T), conversie en lokale vindbaarheid, en doet concrete voorstellen.

Beoordeel alleen de checklistpunten die in de opdracht staan:
- c3_eeat (ervaring, expertise, autoriteit, vertrouwen): welke bewijzen ontbreken op deze pagina? Denk aan
  eigen foto's van werk/team, uitgewerkte projecten of cases, reviews met naam, auteur met functie, keurmerken.
  Je kunt die bewijzen niet verzinnen. Voorstel: wat er moet komen, waar op de pagina, en de tekst eromheen met
  [plaatshouders] voor wat de klant aanlevert (bijv. "[foto van opgeleverd project in <plaats>]").
- c3_conversion: is direct duidelijk wat de bezoeker moet doen? Staat er een call-to-action boven de vouw en
  na de belangrijkste secties? Past de CTA bij de zoekintentie? Zijn er drempels (alleen een formulier, geen
  telefoonnummer, vage knoptekst)? Voorstel: plek + knoptekst + ondersteunende zin.
- c3_local (alleen locatiepagina's): komen plaats, regio en werkgebied natuurlijk terug in H1, eerste alinea en
  tekst? Voorstel: herschreven zinnen/alinea met plaatsnaam, omliggende plaatsen als [plaatshouder] wanneer ze
  niet op de site staan, en lokale aanknopingspunten.

Maximaal 3 voorstellen per checklistpunt; kies de voorstellen met de meeste impact.

{PRINCIPLES}"""


def build_content_trust_agent(item_keys: list[str] | None = None) -> Agent:
    return Agent(
        name="content_trust",
        instructions=INSTRUCTIONS,
        tools=[],
        model=settings.launch_scan_openai_model,
        max_steps=1,
        max_output_tokens=4000,
        reasoning_effort="low",
        output_schema=suggestion_schema(item_keys or ITEM_KEYS),
    )
