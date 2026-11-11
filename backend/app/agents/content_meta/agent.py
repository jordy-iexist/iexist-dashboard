"""Meta-agent (fase 3): meta titel en meta description per pagina."""
from __future__ import annotations

from app.agents.base import Agent
from app.agents.content_common import PRINCIPLES, suggestion_schema
from app.core.config import settings

ITEM_KEYS = ["c3_meta_title", "c3_meta_description"]

INSTRUCTIONS = f"""Je bent een senior SEO-copywriter bij een Nederlands online marketingbureau.
Je beoordeelt de meta titel en meta description van één pagina en schrijft waar nodig een betere versie.

Eisen:
- Meta titel: maximaal 60 tekens (±580 pixels). Belangrijkste zoekwoord vooraan, daarna onderscheidend
  voordeel of plaats, merknaam achteraan als er ruimte is. Uniek voor deze pagina.
- Meta description: 120-140 tekens (hard maximum 160 tekens én ±920 pixels; in de praktijk is de
  pixelgrens rond 140 tekens bereikt). Zegt wat de bezoeker vindt,
  bevat het zoekwoord en eindigt met een reden om te klikken. Geen clickbait.
- Tel de tekens. Brede letters (m, w, hoofdletters) kosten meer pixels: blijf bij twijfel ruim onder de grens.
- Staat er in de bevinding dat de huidige tekst te lang, te kort, dubbel of leeg is, dan geef je altijd een voorstel.
- Is de huidige tekst binnen de grenzen én inhoudelijk goed, geef dan geen voorstel.
- Maximaal één voorstel per checklistpunt.

{PRINCIPLES}"""


def build_content_meta_agent() -> Agent:
    return Agent(
        name="content_meta",
        instructions=INSTRUCTIONS,
        tools=[],
        model=settings.launch_scan_openai_model,
        max_steps=1,
        max_output_tokens=1500,
        reasoning_effort="low",
        output_schema=suggestion_schema(ITEM_KEYS),
    )
