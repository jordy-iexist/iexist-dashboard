"""Paginatype bepalen: handmatige override → URL-regels → body-class/schema → LLM."""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

from app.core.config import settings
from app.features.launch_checklist.services.geo_extract import all_types

logger = logging.getLogger(__name__)

PAGE_TYPES: dict[str, str] = {
    "home": "Homepage",
    "dienst": "Dienstpagina",
    "product": "Productpagina",
    "categorie": "Categoriepagina",
    "blog": "Blog / artikel",
    "vacature": "Vacature",
    "over_ons": "Over ons / team",
    "contact": "Contact",
    "overzicht": "Overzichtspagina",
    "archief": "Archief (tag/auteur/paginatie)",
    "juridisch": "Juridisch (privacy/voorwaarden)",
    "overig": "Overig",
}

# Volgorde telt: eerste match wint.
_SEGMENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("archief", ("tag", "tags", "author", "auteur", "category", "categorie-blog")),
    ("juridisch", ("privacy", "privacyverklaring", "privacybeleid", "privacy-policy", "cookies",
                   "cookiebeleid", "cookie-policy", "algemene-voorwaarden", "voorwaarden",
                   "disclaimer", "terms", "terms-and-conditions", "leveringsvoorwaarden")),
    ("categorie", ("product-categorie", "product-category", "productcategorie", "collections",
                   "categorieen", "categories", "assortiment")),
    ("product", ("product", "producten", "products", "artikel-detail")),
    ("vacature", ("vacatures", "vacature", "werken-bij", "werkenbij", "jobs", "job", "careers",
                  "carriere", "carriere-bij", "vacancies")),
    ("blog", ("blog", "blogs", "nieuws", "news", "artikelen", "artikel", "kennisbank", "insights",
              "magazine", "tips", "kennis", "updates", "verhalen", "cases", "case")),
    ("dienst", ("diensten", "dienst", "services", "service", "behandelingen", "behandeling",
                "oplossingen", "wat-we-doen", "expertise", "expertises", "specialisaties",
                "werkzaamheden", "aanbod")),
    ("over_ons", ("over-ons", "over", "about", "about-us", "wie-zijn-wij", "ons-team", "team",
                  "over-mij", "het-team", "medewerkers")),
    ("contact", ("contact", "contact-opnemen", "contactgegevens")),
]
# Typen waarvan de sectie-index (bijv. /blog/) een overzicht is.
_INDEX_IS_OVERVIEW = {"product", "vacature", "blog", "dienst", "categorie"}

_BODY_CLASS_RULES: list[tuple[str, str]] = [
    ("single-product", "product"),
    ("tax-product_cat", "categorie"),
    ("post-type-archive-product", "overzicht"),
    ("template-product", "product"),
    ("template-collection", "categorie"),
    ("single-post", "blog"),
    ("single-vacature", "vacature"),
    ("single-vacatures", "vacature"),
    ("single-job_listing", "vacature"),
    ("tag ", "archief"),
    ("author ", "archief"),
    ("category ", "archief"),
    ("paged", "archief"),
]

_SCHEMA_RULES: list[tuple[set[str], str]] = [
    ({"JobPosting"}, "vacature"),
    ({"Product", "ProductGroup"}, "product"),
    # Geen generiek "Article": Rank Math/Yoast zetten dat op elke pagina.
    ({"BlogPosting", "NewsArticle"}, "blog"),
    ({"AboutPage"}, "over_ons"),
    ({"ContactPage"}, "contact"),
    ({"CollectionPage", "ItemList"}, "categorie"),
]

_PAGINATION_RE = re.compile(r"/page/\d+/?$|[?&](page|paged|p)=\d+", re.IGNORECASE)


def is_pagination(url: str) -> bool:
    return bool(_PAGINATION_RE.search(url))


def classify_by_rules(url: str, *, is_home: bool, signals: dict[str, Any] | None, jsonld: Any) -> str | None:
    if is_home:
        return "home"
    if is_pagination(url):
        return "archief"
    segments = [s for s in urlparse(url).path.lower().split("/") if s]
    for page_type, needles in _SEGMENT_RULES:
        for index, seg in enumerate(segments):
            if seg in needles:
                is_index = index == len(segments) - 1
                if page_type in _INDEX_IS_OVERVIEW and is_index:
                    return "overzicht"
                return page_type

    body = f" {(signals or {}).get('body_classes', '')} ".lower()
    for needle, page_type in _BODY_CLASS_RULES:
        if f" {needle}" in body:
            return page_type

    types = all_types(jsonld or [])
    for needles, page_type in _SCHEMA_RULES:
        if types & needles:
            return page_type
    return None


_LLM_INSTRUCTIONS = """Je classificeert pagina's van een Nederlandse bedrijfswebsite.
Kies per pagina precies één type uit: dienst, product, categorie, blog, vacature, over_ons, contact, overzicht, juridisch, overig.
- dienst: pagina over één dienst/behandeling/oplossing die het bedrijf aanbiedt.
- product: pagina over één product dat te koop is.
- categorie: overzicht van producten in een categorie.
- blog: artikel, nieuwsbericht, kennisbankartikel of case.
- vacature: één vacature.
- over_ons: over het bedrijf, team of een teamlid.
- overzicht: overzicht van meerdere diensten/blogs/vacatures.
Antwoord ALLEEN met een JSON-object {"<id>": "<type>", ...}."""

_LLM_ALLOWED = {"dienst", "product", "categorie", "blog", "vacature", "over_ons", "contact", "overzicht", "juridisch", "overig"}


def classify_with_llm(items: list[dict[str, Any]], *, user_id: str) -> dict[str, str]:
    """items: [{id, url, title, h1}] → {id: type}. Faalt stil (lege dict)."""
    if not items:
        return {}
    from app.services.openai.client import create_response, response_output_text

    out: dict[str, str] = {}
    for start in range(0, len(items), 150):
        chunk = items[start: start + 150]
        lines = [
            json.dumps({"id": str(i["id"]), "url": i["url"], "title": (i.get("title") or "")[:120],
                        "h1": (i.get("h1") or "")[:120]}, ensure_ascii=False)
            for i in chunk
        ]
        try:
            response = create_response(
                user_id=user_id,
                model=settings.launch_scan_openai_model,
                instructions=_LLM_INSTRUCTIONS,
                input="\n".join(lines),
                max_output_tokens=4000,
            )
            text = response_output_text(response)
            match = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(match.group(0)) if match else {}
        except Exception as exc:  # geen key / API-fout / kapotte JSON
            logger.warning("Paginatype-classificatie via LLM mislukt: %s", exc)
            continue
        for key, value in (data or {}).items():
            if isinstance(value, str) and value in _LLM_ALLOWED:
                out[str(key)] = value
    return out
