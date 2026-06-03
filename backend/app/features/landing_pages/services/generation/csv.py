from typing import Any

from app.features.blogs.services.generation.csv import (  # noqa: F401 — re-exported for callers
    build_blog_prompt,
    extract_template_placeholders,
    get_missing_prompt_values,
    map_row_to_prompt_fields,
    normalize_mapping,
    parse_csv,
    validate_mapping,
)

REQUIRED_COLUMNS = [
    "website",
    "onderwerp",
    "lengte",
    "primaire_zoekwoorden",
    "secundaire_zoekwoorden",
]

LANDING_PAGE_PROMPT_TEMPLATE = (
    "Opdracht: Schrijf een informatieve SEO-geoptimaliseerde landingspagina van minimaal {lengte} woorden voor de website {website}.\n"
    "\n"
    "Het onderwerp van de landingspagina is: {onderwerp}.\n"
    "\n"
    "Doel van de landingspagina: bezoekers informeren en aanzetten tot het doen van een offerte aanvraag. Benoem duidelijk hoe {website} de bezoeker kan helpen.\n"
    "\n"
    "Stijl:\n"
    "\n"
    "Gebruik duidelijke, korte zinnen.\n"
    "\n"
    "Gebruik actieve taal (geen \"er wordt gekeken naar…\" maar \"de bank kijkt naar…\").\n"
    "\n"
    "Gebruik H2- en H3-tussenkoppen met zoekwoorden erin verwerkt. Verwerk de H2 en H3 tussenkoppen met opmaak, dus niet als H2: en H3:.\n"
    "\n"
    "Gebruik maximaal 1 opsomming in de pagina.\n"
    "\n"
    "Sluit af met een korte samenvatting en een call-to-action naar {website}.\n"
    "\n"
    "SEO-richtlijnen:\n"
    "\n"
    "Gebruik de primaire zoekwoorden elk minimaal 2–3 keer, verspreid over de tekst en in minstens één tussenkop:\n"
    "\n"
    "{primaire_zoekwoorden}\n"
    "\n"
    "Gebruik de secundaire zoekwoorden minimaal één keer, verspreid over de tekst:\n"
    "\n"
    "{secundaire_zoekwoorden}\n"
    "\n"
    "Structuur van de pagina:\n"
    "\n"
    "Titel met hoofdzoekwoord.\n"
    "\n"
    "Introductie: kort, pakkend, en met het hoofdzoekwoord in de eerste alinea.\n"
    "\n"
    "Informatieve hoofdsecties (H2's):\n"
    "\n"
    "Beantwoord de belangrijkste vragen van de doelgroep over het onderwerp.\n"
    "\n"
    "Conclusie + samenvatting + CTA: vat de kern samen en voeg een duidelijke oproep toe.\n"
    "\n"
    "FAQ-sectie:\n"
    "\n"
    "Voeg 6 relevante veelgestelde vragen en antwoorden toe.\n"
    "\n"
    "Antwoorden zijn kort (50–100 woorden) en informatief.\n"
    "\n"
    "FAQ's moeten aansluiten bij het onderwerp en long-tail zoektermen bevatten."
)

DEFAULT_LANDING_PAGE_PROMPT_TEMPLATE = LANDING_PAGE_PROMPT_TEMPLATE


def normalize_landing_page_prompt_template(template: str | None) -> str:
    normalized = str(template or "").strip()
    return normalized if normalized else DEFAULT_LANDING_PAGE_PROMPT_TEMPLATE


def validate_landing_page_mapping(
    mapping: dict[str, Any],
    headers: list[str],
    required_fields: list[str] | None = None,
) -> dict[str, str]:
    fields = required_fields if required_fields is not None else REQUIRED_COLUMNS
    normalized = normalize_mapping(mapping, fields)
    validate_mapping(normalized, headers, fields)
    return normalized


def map_row_to_landing_page_fields(
    row: dict[str, Any],
    mapping: dict[str, str],
    required_fields: list[str] | None = None,
) -> dict[str, str]:
    fields = required_fields if required_fields is not None else REQUIRED_COLUMNS
    return map_row_to_prompt_fields(row, mapping, fields)


def build_landing_page_prompt(
    row: dict[str, Any], template: str | None = None
) -> str:
    prompt_template = normalize_landing_page_prompt_template(template)
    if template is not None or prompt_template != LANDING_PAGE_PROMPT_TEMPLATE:
        return build_blog_prompt(prompt_template, row)

    fields: dict[str, str] = {}
    for column in REQUIRED_COLUMNS:
        value = str(row.get(column, "") or "").strip()
        if not value:
            raise ValueError(f"Waarde ontbreekt voor veld: '{column}'.")
        fields[column] = value

    return LANDING_PAGE_PROMPT_TEMPLATE.format(**fields)
