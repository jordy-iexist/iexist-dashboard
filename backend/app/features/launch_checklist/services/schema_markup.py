"""Ontbrekende JSON-LD voor één pagina ("Maak schema").

`generate_schema_markup` haalt de pagina opnieuw op (de opgeslagen JSON-LD is
ingekort en ruwe HTML wordt niet bewaard), bepaalt welke verwachte schema-types
ontbreken (`target_types`) en laat de schema-agent alleen die schrijven. Het
resultaat wordt gevalideerd en opgeslagen bij de pagina; een collega kopieert
het blok en plakt het zelf. Er wordt niets op de klantsite geschreven.

Per pagina kan een collega zelf de schema-types kiezen (`LaunchScanPage.schema_target_types`);
zonder keuze volgen ze uit het paginatype. Het voorstel bewaart ook de bestaande JSON-LD van de
pagina, zodat de response de complete markup na plaatsen kan tonen (`page_graph_of`).

Een collega kan het voorstel met de hand bewerken (`edit_schema_markup`, alleen database). Zo'n voorstel
wordt nooit vanzelf opnieuw gemaakt; alleen `regenerate` overschrijft het (en wist de bewerkt-markering).
De brief geeft de bedrijfsgegevens van de site (pagina plus homepage) apart en volledig mee
(`business_facts`), omdat de bestaande JSON-LD in de brief begrensd is.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.agents import AGENTS, run_agent
from app.core.url_guard import is_safe_external_url
from app.db.models import CustomerWebsite, LaunchScan, LaunchScanPage
from app.features.launch_checklist.services.content_extract import ContentExtract, extract_content
from app.features.launch_checklist.services.discovery import clean_url, root_domain_of, url_key
from app.features.launch_checklist.services.geo_checks import ARTICLE_TYPES, PRODUCT_TYPES, is_org_type
from app.features.launch_checklist.services.geo_extract import all_types, extract_geo, flatten_jsonld, types_of
from app.features.launch_checklist.services.golive_probes import new_client
from app.features.launch_checklist.services.html_extract import extract_page
from app.features.launch_checklist.services.inventory import MAX_BODY_BYTES
from app.features.launch_checklist.services.page_types import EXPECTED_SCHEMA, PAGE_TYPES
from app.features.launch_checklist.services.schema_validate import (
    RECOMMENDED,
    REQUIRED,
    describe_problem,
    extract_jsonld_blocks,
    validate_blocks,
)
from app.features.settings.services import MissingUserOpenAIKeyError

logger = logging.getLogger(__name__)

# Begrenzing van de invoer, zodat één pagina de prompt niet opblaast.
MAX_HOPS = 5
MAX_BODY_TEXT_CHARS = 8_000
MAX_BLOCK_CHARS = 6_000
MAX_JSONLD_CHARS = 12_000
MAX_HEADINGS = 40
MAX_ENTITIES = 30
MAX_IMAGES = 8
MAX_CRUMBS = 6
MAX_TEXT_CHARS = 300
# Bestaande JSON-LD in het voorstel (voor de complete markup na plaatsen), samen begrensd.
MAX_EXISTING_JSONLD_BYTES = 60_000
MAX_OMITTED = 40

# Eigen keuze van schema-types per pagina.
TYPE_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]{1,60}$")
MAX_TARGET_TYPES = 8
SOURCE_MANUAL = "manual"
SOURCE_AUTO = "auto"
_OMITTED_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(\.[A-Za-z@][A-Za-z0-9]*)+$")
# Labels van Rank Math (twitter:labelN) waarvan twitter:dataN de auteur is.
_AUTHOR_LABELS = {"geschreven door", "written by", "auteur", "author"}

# Een tekst tussen rechte haken in de JSON-LD is een plaatshouder ("[naam van de auteur]").
_PLACEHOLDER_RE = re.compile(r"\[[^\[\]\n]{2,200}\]")

# Korte vakkennis per type, bovenop de verplichte eigenschappen uit `schema_validate`.
# Bewust hier en niet in `RECOMMENDED`: die lijst bepaalt ook de waarschuwingen van de scan.
# De hints noemen alles wat een entiteit volledig maakt; de agent laat weg wat niet in de invoer staat.
_TYPE_HINTS: dict[str, str] = {
    "Organization": "name, url, logo (URL of ImageObject), description, email, telephone, contactPoint, "
                    "address (PostalAddress) en sameAs (profielen), vatID en identifier (KvK) — elk alleen "
                    "als het in de invoer staat",
    "WebSite": "url van de homepage, name, description, inLanguage, publisher als verwijzing naar de organisatie; "
               "potentialAction (SearchAction) alleen als een zoekfunctie met URL in de invoer staat",
    "Service": "name (de dienst zoals in de H1 of title); serviceType (de dienst zonder plaatsnaam, "
               "bv. \"Website laten maken\"); description uit de meta description of de eerste alinea; "
               "url van deze pagina; provider als verwijzing naar de bestaande organisatie; "
               "mainEntityOfPage als verwijzing naar de @id van de bestaande WebPage; "
               "image als er een hoofdafbeelding is (primaryImageOfPage, og:image of een afbeelding in de "
               "inhoud), bij voorkeur als verwijzing naar een bestaande ImageObject-@id; "
               "areaServed als City met name alleen als de plaats op de pagina staat; "
               "offers alleen als er een prijs op de pagina staat; hasOfferCatalog alleen als de pagina "
               "pakketten, varianten of onderdelen van déze dienst noemt, niet voor andere diensten van "
               "het bedrijf die ook op de pagina staan",
    "BreadcrumbList": "itemListElement met ListItem (position, name, item) van homepage tot deze pagina",
    "Product": "staat er geen prijs op de pagina, zet dan offers met een plaatshouder voor de prijs; "
               "nooit review of aggregateRating verzinnen; ook description (meta description of eerste "
               "alinea), image (hoofdafbeelding), url, mainEntityOfPage (verwijzing naar de WebPage), brand "
               "(verwijzing naar de Brand-entiteit als Brand ook gevraagd is), sku/gtin/mpn als ze op de pagina staan, en in offers: price, priceCurrency, availability en url",
    "Brand": "name van het merk zoals op de pagina; logo en url als bekend; eigen entiteit met @id op het "
             "hoogste niveau, waar het Product via brand naar verwijst ({\"@id\": …}), niet genest in het Product",
    "ItemList": "itemListElement met ListItem (position, url, name) voor de items op de pagina; numberOfItems",
    "BlogPosting": "headline (hooguit 110 tekens), description (meta description of eerste alinea), image "
                   "(og:image, uitgelichte afbeelding of hoofdafbeelding), datePublished en dateModified "
                   "(uit article:published_time/article:modified_time, WordPress of <time datetime>), author "
                   "(Person met name en url, uit meta author, Rank Math of WordPress; is Person ook gevraagd, dan "
                   "als eigen entiteit waar author naar verwijst; of een verwijzing naar een bestaande Person "
                   "die niet vervalt), publisher (verwijzing naar de organisatie), "
                   "mainEntityOfPage (verwijzing naar de WebPage), inLanguage en articleSection als bekend",
    "Article": "headline (hooguit 110 tekens), description (meta description of eerste alinea), image "
               "(og:image, uitgelichte afbeelding of hoofdafbeelding), datePublished en dateModified (uit "
               "article:published_time/article:modified_time, WordPress of <time datetime>), author (Person met "
               "name en url, als eigen entiteit als Person ook gevraagd is, of een verwijzing naar een "
               "bestaande Person die niet vervalt), publisher "
               "(verwijzing naar de organisatie), mainEntityOfPage (verwijzing naar de WebPage), inLanguage",
    "Person": "name zoals op de pagina; jobTitle en worksFor (verwijzing naar de organisatie) als bekend; "
              "ook description, image (foto van de persoon), url (bv. de auteurspagina) en sameAs als ze in "
              "de invoer staan",
    "JobPosting": "title, description, datePosted, hiringOrganization (verwijzing), jobLocation met address; "
                  "ook url van deze pagina, mainEntityOfPage (verwijzing naar de WebPage), validThrough, "
                  "employmentType en baseSalary (MonetaryAmount) als dat op de pagina staat",
    "FAQPage": "mainEntity met Question (name) en acceptedAnswer (Answer met text), alleen vragen van de pagina",
    "LocalBusiness": "name, address (PostalAddress met streetAddress, postalCode, addressLocality, "
                     "addressCountry), telephone, email, url, image of logo, sameAs; openingHoursSpecification, "
                     "geo (GeoCoordinates), priceRange en areaServed alleen als ze in de invoer staan; gebruik "
                     "het meest specifieke subtype als dat gevraagd is",
    "HowTo": "name, description, image; step als HowToStep (name, text, url met #anker als er een anker is) "
             "in de volgorde van de pagina; totalTime (ISO 8601-duur), supply, tool en estimatedCost alleen "
             "als ze op de pagina staan",
    "Event": "name, startDate en endDate (ISO 8601 met tijdzone), location (Place met name en address, of "
             "VirtualLocation met url), description, image, eventStatus, eventAttendanceMode, organizer "
             "(verwijzing naar de organisatie); offers (price, priceCurrency, availability, url, validFrom) en "
             "performer alleen als ze op de pagina staan",
    "VideoObject": "alleen voor een video die echt op de pagina staat: name, description, thumbnailUrl, "
                   "uploadDate, en contentUrl of embedUrl; duration (ISO 8601) als bekend",
    "Review": "itemReviewed (verwijzing of naam), author (Person of Organization met name), reviewRating "
              "(Rating met ratingValue en bestRating) en reviewBody alleen letterlijk van de pagina, "
              "datePublished als bekend",
    "Course": "name, description, provider (verwijzing naar de organisatie), url; offers (price, priceCurrency, "
              "category) en hasCourseInstance (courseMode, courseWorkload of courseSchedule) alleen als ze op "
              "de pagina staan; inLanguage",
    "SoftwareApplication": "name, applicationCategory, operatingSystem, url, description, image; offers (price, "
                           "priceCurrency; 0 alleen als 'gratis' op de pagina staat); aggregateRating of review "
                           "alleen als ze op de pagina staan",
    "Recipe": "name, image, description, author, datePublished, recipeIngredient, recipeInstructions "
              "(HowToStep), prepTime/cookTime/totalTime (ISO 8601), recipeYield, recipeCategory, recipeCuisine, "
              "keywords en nutrition.calories — elk alleen als het op de pagina staat",
}


class SchemaMarkupError(RuntimeError):
    """Het schema kon niet worden gemaakt (pagina niet op te halen, modelfout, ongeldig of afgekapt antwoord)."""


class SchemaMarkupPageGoneError(LookupError):
    """De pagina is tijdens de modelaanroep verwijderd (bv. door een nieuwe scan)."""


@dataclass
class SchemaMarkupResult:
    script: str
    types: list[str]
    placeholders: list[str]
    notes: str
    problems: list[str]
    generated_at: datetime
    cached: bool
    nothing_missing: bool
    # Types die al op de pagina stonden en dus niet in het blok zijn herhaald.
    existing_types: list[str] = field(default_factory=list)
    # Types waarvoor het voorstel is gemaakt, en of dat een eigen keuze ("manual") was.
    target_types: list[str] = field(default_factory=list)
    target_types_source: str = SOURCE_AUTO
    # Er is een voorstel, maar de typekeuze van de pagina is daarna gewijzigd.
    stale: bool = False
    # Aanbevolen eigenschappen die niet in te vullen waren ("Type.eigenschap").
    omitted: list[str] = field(default_factory=list)
    # Eén regel per top-level entiteit van de pagina na plaatsen (zie `page_graph_of`).
    page_graph: list[dict[str, Any]] = field(default_factory=list)
    # Bestaande nodes (zonder wat vervalt) plus de nieuwe als één <script>-blok; "" als onbekend.
    full_script: str = ""
    # Het voorstel is daarna met de hand bewerkt (`edit_schema_markup`); wanneer.
    edited: bool = False
    edited_at: datetime | None = None


class SchemaMarkupEditError(ValueError):
    """De bewerkte JSON-LD is niet bruikbaar; de tekst is de (Nederlandse) reden."""


class SchemaMarkupNoSuggestionError(LookupError):
    """Er is (nog) geen voorstel om te bewerken."""


@dataclass
class PageFacts:
    """Wat er uit de vers opgehaalde HTML van één pagina komt."""

    url: str
    blocks: list[str] = field(default_factory=list)
    existing_types: set[str] = field(default_factory=set)
    # (@id, types, name) van bestaande entiteiten, om naar te verwijzen.
    entities: list[tuple[str, list[str], str | None]] = field(default_factory=list)
    content: ContentExtract = field(default_factory=ContentExtract)
    signals: dict[str, Any] = field(default_factory=dict)
    # Geparste JSON-LD-blokken (zonder door ons geplaatste nodes), ongekort.
    parsed: list[Any] = field(default_factory=list)
    # Publicatiegegevens uit de HTML als (label, waarde); alleen wat gevonden is.
    publication: list[tuple[str, str]] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clip(text: Any, limit: int = MAX_TEXT_CHARS) -> str:
    value = str(text)
    return value if len(value) <= limit else value[:limit] + "…(ingekort)"


# --- ophalen en analyseren -----------------------------------------------------

def fetch_page_html(url: str) -> tuple[str, str]:
    """(html, eind-URL). Volgt redirects stap voor stap, elke stap langs de SSRF-bescherming.

    Gooit `SchemaMarkupError` als de pagina niet als HTML met status 200 op te halen is.
    """
    current = url
    with new_client() as client:
        for _ in range(MAX_HOPS + 1):
            if not is_safe_external_url(current):
                raise SchemaMarkupError("De pagina-URL wijst niet naar een toegestane externe website.")
            try:
                response = client.get(current)
            except httpx.HTTPError as exc:
                raise SchemaMarkupError(
                    f"De pagina kon niet worden opgehaald ({type(exc).__name__}). Probeer het later opnieuw."
                ) from exc
            if response.is_redirect:
                target = clean_url(response.headers.get("location", ""), current)
                if not target:
                    raise SchemaMarkupError("De pagina stuurt door naar een ongeldige URL.")
                current = target
                continue
            if response.status_code != 200:
                raise SchemaMarkupError(f"De pagina kon niet worden opgehaald (status {response.status_code}).")
            if "html" not in response.headers.get("content-type", "").lower():
                raise SchemaMarkupError("De pagina is geen HTML-pagina.")
            html = response.content[:MAX_BODY_BYTES].decode(response.encoding or "utf-8", errors="replace")
            return html, str(response.url)
    raise SchemaMarkupError("De pagina stuurt te vaak door; ophalen gestopt.")


def _parsed_blocks(blocks: list[str]) -> list[Any]:
    parsed: list[Any] = []
    for raw in blocks:
        try:
            parsed.append(json.loads(raw.strip()))
        except (ValueError, TypeError):
            continue
    return parsed


def _entities(parsed: list[Any]) -> list[tuple[str, list[str], str | None]]:
    """Bestaande entiteiten met een @id en @type (ook genest), uniek op @id."""
    found: dict[str, tuple[str, list[str], str | None]] = {}

    def walk(value: Any, depth: int) -> None:
        if depth > 8 or len(found) >= MAX_ENTITIES:
            return
        if isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
        elif isinstance(value, dict):
            node_id, node_types = value.get("@id"), types_of(value)
            if isinstance(node_id, str) and node_id.strip() and node_types and node_id not in found:
                name = value.get("name")
                found[node_id] = (node_id, node_types, _clip(name, 120) if isinstance(name, str) else None)
            for item in value.values():
                if isinstance(item, (dict, list)):
                    walk(item, depth + 1)

    walk(parsed, 0)
    return list(found.values())


def analyze_page(html: str, url: str, root_domain: str, placement: dict[str, Any] | None = None) -> PageFacts:
    """Feiten van de pagina. Met `placement` tellen de door ons in Rank Math geplaatste nodes
    niet mee, zodat opnieuw genereren weer het volledige voorstel oplevert."""
    blocks = extract_jsonld_blocks(html)
    parsed = _parsed_blocks(blocks)
    if placement:
        parsed = strip_placed(parsed, placement)
        blocks = [json.dumps(block, ensure_ascii=False) for block in parsed]
    return PageFacts(
        url=url,
        blocks=blocks,
        existing_types=all_types(parsed),
        entities=_entities(parsed),
        content=extract_content(html, url, root_domain),
        signals=extract_geo(html, url, root_domain).signals,
        parsed=parsed,
        publication=publication_facts(html),
    )


def publication_facts(html: str) -> list[tuple[str, str]]:
    """Datums, auteur en hoofdafbeelding uit de <meta>-tags en <time datetime> van de pagina."""
    page = extract_page(html)
    meta = page.meta_facts
    out: list[tuple[str, str]] = []
    if meta.get("article:published_time"):
        out.append(("Gepubliceerd (article:published_time)", meta["article:published_time"]))
    if meta.get("article:modified_time"):
        out.append(("Gewijzigd (article:modified_time)", meta["article:modified_time"]))
    if page.open_graph.get("og:image"):
        out.append(("Hoofdafbeelding (og:image)", page.open_graph["og:image"]))
    if meta.get("author"):
        out.append(("Auteur (meta author)", meta["author"]))
    for n in range(1, 5):
        label, data = meta.get(f"twitter:label{n}", ""), meta.get(f"twitter:data{n}", "")
        if data and label.strip().lower() in _AUTHOR_LABELS:
            out.append((f"Auteur (twitter:data{n}, \"{label.strip()}\")", data))
    if page.time_datetimes:
        out.append(("Datums in <time datetime>", ", ".join(page.time_datetimes)))
    return [(label, _clip(value)) for label, value in out]


# --- Rank Math op de pagina ---------------------------------------------------------

_SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
_LDJSON_ATTR_RE = re.compile(r"\btype\s*=\s*[\"']?application/ld\+json", re.IGNORECASE)
_RANK_MATH_ATTR_RE = re.compile(r"\bclass\s*=\s*(?:\"[^\"]*|'[^']*|)\brank-math-schema", re.IGNORECASE)
# Pagina-types die Rank Math als WebPage-node van de graph gebruikt.
WEBPAGE_TYPES = {"WebPage", "CollectionPage", "ProfilePage", "AboutPage", "ContactPage", "SearchResultsPage",
                 "ItemPage", "CheckoutPage"}


@dataclass
class RankMathFacts:
    """Wat er over Rank Math in de HTML van één pagina staat."""

    detected: bool
    # Types van het standaardschema (`@id` op `#richSnippet`, plus de bijbehorende Person).
    default_types: list[str] = field(default_factory=list)
    # De pagina heeft de graph van Rank Math (een WebPage-node).
    had_graph: bool = False
    # Alle types op de pagina zonder het standaardschema (en zonder door ons geplaatste nodes).
    kept_types: set[str] = field(default_factory=set)
    # @id's van de nodes van het standaardschema (vervallen bij plaatsen).
    default_ids: list[str] = field(default_factory=list)


def _node_id(node: Any) -> str:
    value = node.get("@id") if isinstance(node, dict) else None
    return value.strip() if isinstance(value, str) else ""


def placed_matcher(placement: dict[str, Any] | None):
    """Herkent een top-level node die door ons via Rank Math is geplaatst (op `@id`)."""
    meta_ids: set[str] = set()
    node_ids: set[str] = set()
    for item in (placement or {}).get("items") or []:
        if isinstance(item, dict):
            if item.get("meta_id") is not None:
                meta_ids.add(str(item["meta_id"]))
            if item.get("node_id"):
                node_ids.add(str(item["node_id"]))

    def matches(node: Any) -> bool:
        node_id = _node_id(node)
        if not node_id:
            return False
        if node_id in node_ids:
            return True
        _, sep, suffix = node_id.rpartition("#schema-")
        return bool(sep) and suffix in meta_ids

    return matches


def _is_webpage(node: dict[str, Any]) -> bool:
    return bool(set(types_of(node)) & WEBPAGE_TYPES) or _node_id(node).endswith("#webpage")


def strip_placed(parsed: list[Any], placement: dict[str, Any] | None) -> list[Any]:
    """Geparste JSON-LD-blokken zonder de door ons geplaatste nodes.

    Een geplaatste FAQPage voegt Rank Math samen met de WebPage (type FAQPage erbij, plus
    `mainEntity`); dat wordt bij die WebPage teruggedraaid.
    """
    if not placement:
        return parsed
    placed = placed_matcher(placement)
    faq_placed = any(isinstance(i, dict) and i.get("type") == "FAQPage" for i in placement.get("items") or [])

    def clean_node(node: dict[str, Any]) -> dict[str, Any]:
        types = types_of(node)
        rest = [t for t in types if t != "FAQPage"]
        if faq_placed and "FAQPage" in types and (set(rest) & WEBPAGE_TYPES or _node_id(node).endswith("#webpage")):
            node = {k: v for k, v in node.items() if k != "mainEntity"}
            node["@type"] = rest[0] if len(rest) == 1 else rest
        return node

    def clean(value: Any) -> Any:
        if isinstance(value, list):
            return [clean(v) for v in value if not (isinstance(v, dict) and placed(v))]
        if isinstance(value, dict):
            if isinstance(value.get("@graph"), list):
                value = {**value, "@graph": clean(value["@graph"])}
            return clean_node(value)
        return value

    return [clean(block) for block in parsed if not (isinstance(block, dict) and placed(block))]


def _referenced_ids(value: Any, depth: int = 0) -> set[str]:
    found: set[str] = set()
    if depth > 8:
        return found
    if isinstance(value, dict):
        node_id = _node_id(value)
        if node_id and depth > 0:
            found.add(node_id)
        for item in value.values():
            found |= _referenced_ids(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            found |= _referenced_ids(item, depth + 1)
    return found


def rank_math_blocks(html: str) -> list[str]:
    """JSON-LD-blokken die Rank Math schrijft (`rank-math-schema` in de class)."""
    return [m.group(2) for m in _SCRIPT_RE.finditer(html or "")
            if _LDJSON_ATTR_RE.search(m.group(1)) and _RANK_MATH_ATTR_RE.search(m.group(1))]


def rank_math_facts(html: str, placement: dict[str, Any] | None = None) -> RankMathFacts:
    raw_blocks = rank_math_blocks(html)
    rm_nodes = flatten_jsonld(strip_placed(_parsed_blocks(raw_blocks), placement))
    default_nodes = [n for n in rm_nodes if _node_id(n).endswith("#richSnippet")]
    refs = set().union(*(_referenced_ids(n) for n in default_nodes)) if default_nodes else set()
    default_nodes += [n for n in rm_nodes if "Person" in types_of(n) and _node_id(n) in refs]
    default_ids = {_node_id(n) for n in default_nodes}
    all_nodes = flatten_jsonld(strip_placed(_parsed_blocks(extract_jsonld_blocks(html)), placement))
    return RankMathFacts(
        detected=bool(raw_blocks),
        default_types=_unique([t for n in default_nodes for t in types_of(n)]),
        had_graph=any(_is_webpage(n) for n in rm_nodes),
        kept_types=all_types([n for n in all_nodes if not (_node_id(n) and _node_id(n) in default_ids)]),
        default_ids=sorted(i for i in default_ids if i),
    )


def _is_present(expected: str, existing: set[str]) -> bool:
    """Staat (één van) het verwachte type al op de pagina? Subtypes tellen mee."""
    for alternative in expected.split("|"):
        if alternative in existing:
            return True
        if alternative == "Organization" and any(is_org_type(t) for t in existing):
            return True
        if alternative in ARTICLE_TYPES and existing & ARTICLE_TYPES:
            return True
        if alternative in PRODUCT_TYPES and existing & PRODUCT_TYPES:
            return True
    return False


def normalize_choice(value: Any) -> list[str] | None:
    """Eigen keuze van schema-types als lijst (uniek, volgorde behouden), of None (automatisch)."""
    if not isinstance(value, list):
        return None
    return _unique([str(t).strip() for t in value if isinstance(t, str)]) or None


def requested_types(page_type: str | None, choice: Any, signals: dict[str, Any] | None = None) -> list[str]:
    """Wat er gevraagd wordt vóór aftrek van wat al op de pagina staat (zonder de pagina op te halen):
    de eigen keuze, of de verwachte types van het paginatype (plus FAQPage als het FAQ-signaal bekend is)."""
    manual = normalize_choice(choice)
    if manual:
        return manual
    types = [expected.split("|")[0] for expected in EXPECTED_SCHEMA.get(page_type or "", [])]
    if (signals or {}).get("faq") and "FAQPage" not in types:
        types.append("FAQPage")
    return types


def plan_targets(page_type: str | None, existing_types: set[str], signals: dict[str, Any] | None,
                 choice: Any = None) -> tuple[list[str], list[str], str]:
    """(te schrijven types, overgeslagen omdat ze er al staan, bron "manual"/"auto").

    Met een eigen keuze: die types min wat er al staat. Anders: verwacht voor het paginatype min wat
    er al staat, plus FAQPage bij een FAQ. Bij "A|B" wordt het eerste alternatief gevraagd.
    """
    manual = normalize_choice(choice)
    if manual is not None:
        targets = [t for t in manual if not _is_present(t, existing_types)]
        return targets, [t for t in manual if t not in targets], SOURCE_MANUAL
    targets = [
        expected.split("|")[0]
        for expected in EXPECTED_SCHEMA.get(page_type or "", [])
        if not _is_present(expected, existing_types)
    ]
    if (signals or {}).get("faq") and "FAQPage" not in existing_types:
        targets.append("FAQPage")
    return targets, [], SOURCE_AUTO


def target_types(page_type: str | None, existing_types: set[str], signals: dict[str, Any] | None,
                 choice: Any = None) -> list[str]:
    """Te schrijven types (zie `plan_targets`)."""
    return plan_targets(page_type, existing_types, signals, choice)[0]


def nested_targets(suggestion: Any) -> bool:
    """Bevat een opgeslagen voorstel nog gevraagde types die genest staan (van vóór het splitsen)?

    Gevraagd = de opgeslagen `target_types`; zonder die lijst is dat onbekend (False).
    """
    if not isinstance(suggestion, dict) or not suggestion.get("jsonld"):
        return False
    targets = suggestion.get("target_types")
    if not isinstance(targets, list):
        return False
    return has_nested_targets(suggestion["jsonld"], [str(t) for t in targets])


def outdated_format(suggestion: Any) -> bool:
    """Voorstel in een verouderde vorm: van vóór de rijkere generator (zonder bewaarde paginamarkup, dus
    zonder volledige weergave), of met gevraagde types die nog in een andere entiteit genest staan (dan
    komen ze niet als eigen schema in Rank Math; zie `split_target_entities`).

    Zo'n voorstel wordt bij openen vanzelf opnieuw gemaakt, tenzij het al beoordeeld of geplaatst is:
    dan zou opnieuw maken die beoordeling of de koppeling met de site ongemerkt ongeldig maken. Een met
    de hand bewerkt voorstel ook nooit: dat gaat alleen weg met een expliciete `regenerate`.
    """
    if not isinstance(suggestion, dict) or not suggestion.get("jsonld"):
        return False
    if suggestion.get("placement") or suggestion.get("review") or suggestion.get("edited"):
        return False
    return "existing_nodes" not in suggestion or nested_targets(suggestion)


def is_stale(suggestion: Any, choice: Any) -> bool:
    """Er is een voorstel, maar het moet opnieuw gemaakt worden.

    Omdat de typekeuze van de pagina sindsdien is gewijzigd (voorstellen van vóór de eigen keuze zijn
    automatisch gemaakt), omdat het voorstel nog van vóór de rijkere generator is, of omdat er nog
    gevraagde types genest in staan (ook als het al beoordeeld of geplaatst is: dan wordt het niet
    vanzelf opnieuw gemaakt, maar meldt het scherm dat opnieuw genereren nodig is).
    """
    if not isinstance(suggestion, dict) or not suggestion.get("jsonld"):
        return False
    if outdated_format(suggestion) or nested_targets(suggestion):
        return True
    made_with = normalize_choice(suggestion.get("target_choice"))
    current = normalize_choice(choice)
    return (sorted(made_with) if made_with else None) != (sorted(current) if current else None)


# --- organisatie van de site ----------------------------------------------------------------

def _logo_url(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("url", "contentUrl", "@id"):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()
    return None


def organization_of(jsonld: Any) -> dict[str, str] | None:
    """@id, name, url en logo van de eerste Organization-achtige node, of None."""
    for node in flatten_jsonld(jsonld or []):
        if not any(is_org_type(t) for t in types_of(node)):
            continue
        org: dict[str, str] = {"type": types_of(node)[0]}
        if _node_id(node):
            org["@id"] = _node_id(node)
        for key in ("name", "url"):
            if isinstance(node.get(key), str) and node[key].strip():
                org[key] = _clip(node[key].strip(), 200)
        logo = _logo_url(node.get("logo"))
        if logo:
            org["logo"] = logo
        if org.get("@id") or org.get("name"):
            return org
    return None


def _home_rows(db: Session, page: LaunchScanPage) -> list[LaunchScanPage]:
    """Kandidaat-homepages in dezelfde scan, de beste eerst (zie `home_organization`)."""
    host = urlparse(page.final_url or page.url or "").netloc.lower()
    rows = (
        db.query(LaunchScanPage)
        .filter(LaunchScanPage.scan_id == page.scan_id,
                or_(LaunchScanPage.page_type == "home", LaunchScanPage.path == "/"))
        .limit(20)
        .all()
    )
    rows.sort(key=lambda r: 0 if r.path == "/" and urlparse(r.final_url or r.url or "").netloc.lower() == host else 1)
    return rows


def home_organization(db: Session, page: LaunchScanPage) -> dict[str, str] | None:
    """De Organization van de homepage in dezelfde scan, of None.

    Eerst de hoofdpagina (pad "/") van hetzelfde domein als de pagina, ook als die een ander paginatype
    kreeg (bijv. "landing"); daarna rijen met paginatype "home". Een scan kan meerdere subdomeinen
    bevatten, en de home-rij van een ander subdomein heeft de organisatie vaak niet.
    """
    for row in _home_rows(db, page):
        org = organization_of(row.jsonld)
        if org:
            return org
    return None


def home_jsonld(db: Session, page: LaunchScanPage) -> Any:
    """De opgeslagen JSON-LD van de homepage-rij die `home_organization` kiest, of None.

    `LaunchScanPage.jsonld` kort lange teksten in, maar adressen, telefoon en dergelijke blijven heel.
    """
    for row in _home_rows(db, page):
        if organization_of(row.jsonld):
            return row.jsonld
    return None


# --- bedrijfsgegevens van de site ------------------------------------------------------------

SOURCE_THIS_PAGE = "deze pagina"
SOURCE_HOMEPAGE = "homepage"
# Volgorde in de brief: wat het vaakst ontbreekt (adres) staat vooraan.
_BUSINESS_KEYS = ("type", "@id", "name", "url", "address", "telephone", "email", "logo", "geo",
                  "openingHoursSpecification", "openingHours", "sameAs")
MAX_BUSINESS_CHARS = 5_000
MAX_BUSINESS_VALUE_CHARS = 800
# Een adres wordt nooit afgekapt tenzij het absurd lang is (meerdere vestigingen).
MAX_BUSINESS_ADDRESS_CHARS = 3_000
MAX_SAME_AS = 12
_REF_DEPTH = 4


def _id_index(value: Any) -> dict[str, dict[str, Any]]:
    """Alle entiteiten met een @id (ook genest), per @id de uitgebreidste (meeste eigenschappen)."""
    index: dict[str, dict[str, Any]] = {}

    def walk(item: Any, depth: int) -> None:
        if depth > 10:
            return
        if isinstance(item, list):
            for v in item:
                walk(v, depth + 1)
        elif isinstance(item, dict):
            node_id = _node_id(item)
            if node_id and len(item) > 1 and len(item) > len(index.get(node_id, {})):
                index[node_id] = item
            for v in item.values():
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)

    walk(value, 0)
    return index


def _is_ref(value: Any) -> bool:
    return isinstance(value, dict) and bool(_node_id(value)) and set(value) <= {"@id"}


def _resolve_refs(value: Any, index: dict[str, dict[str, Any]], depth: int = 0) -> Any:
    """Waarde met verwijzingen ({"@id": …}) vervangen door de entiteit zelf (begrensd, zonder @context)."""
    if depth > _REF_DEPTH:
        return value
    if _is_ref(value) and _node_id(value) in index:
        value = index[_node_id(value)]
    if isinstance(value, dict):
        return {k: _resolve_refs(v, index, depth + 1) for k, v in value.items() if k != "@context"}
    if isinstance(value, list):
        return [_resolve_refs(v, index, depth + 1) for v in value]
    return value


def _filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value) and not _is_ref(value)
    return True


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value] if value is not None else []


def _org_candidates(parsed: Any, index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Organization-achtige entiteiten (ook genest) met @id of name: eerst die op het hoogste niveau,
    daarbinnen die met een adres eerst."""
    top = flatten_jsonld(parsed or [])
    found: list[tuple[int, dict[str, Any]]] = [(0, n) for n in top]
    seen = {id(n) for _, n in found}

    def walk(item: Any, depth: int) -> None:
        if depth > 8:
            return
        if isinstance(item, list):
            for v in item:
                walk(v, depth + 1)
        elif isinstance(item, dict):
            if id(item) not in seen and item.get("@type"):
                seen.add(id(item))
                found.append((1, item))
            for v in item.values():
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)

    for node in top:
        for v in node.values():
            walk(v, 1)
    orgs = [(level, n) for level, n in found
            if any(is_org_type(t) for t in types_of(n))
            and (_node_id(n) or (isinstance(n.get("name"), str) and n["name"].strip()))]
    ranked = sorted(enumerate(orgs), key=lambda item: (item[1][0], 0 if _business_values(item[1][1], index)
                                                       .get("address") else 1, item[0]))
    return [n for _, (_, n) in ranked]


def _business_values(node: dict[str, Any], index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Bedrijfsgegevens van één organisatie-entiteit; adres, coördinaten, telefoon en openingstijden
    ook van een Place waarnaar ze via `location` verwijst, telefoon en e-mail ook uit `contactPoint`."""
    places = [p for p in (_resolve_refs(loc, index) for loc in _as_list(node.get("location"))) if isinstance(p, dict)]
    contacts = [c for c in (_resolve_refs(cp, index) for cp in _as_list(node.get("contactPoint")))
                if isinstance(c, dict)]

    def pick(key: str, *, extra: list[dict[str, Any]] | None = None) -> Any:
        for source in [node, *places, *(extra or [])]:
            value = _resolve_refs(source.get(key), index)
            if _filled(value):
                return value
        return None

    values: dict[str, Any] = {"type": ", ".join(types_of(node))}
    if _node_id(node):
        values["@id"] = _node_id(node)
    for key in ("name", "url"):
        if isinstance(node.get(key), str) and node[key].strip():
            values[key] = node[key].strip()
    logo = _logo_url(_resolve_refs(node.get("logo"), index))
    if logo:
        values["logo"] = logo
    for key in ("address", "geo", "openingHoursSpecification", "openingHours"):
        value = pick(key)
        if value is not None:
            values[key] = value
    for key in ("telephone", "email"):
        value = pick(key, extra=contacts)
        if value is not None:
            values[key] = value
    same_as = [s.strip() for s in _as_list(node.get("sameAs")) if isinstance(s, str) and s.strip()]
    if same_as:
        values["sameAs"] = _unique(same_as)[:MAX_SAME_AS]
    return values


def business_of(jsonld: Any) -> dict[str, Any] | None:
    """Bedrijfsgegevens van de belangrijkste organisatie in de JSON-LD, of None."""
    index = _id_index(jsonld)
    candidates = _org_candidates(jsonld, index)
    return _business_values(candidates[0], index) if candidates else None


def _same_org(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("@id") and b.get("@id") and a["@id"] == b["@id"]:
        return True
    name_a, name_b = str(a.get("name") or "").strip().lower(), str(b.get("name") or "").strip().lower()
    return bool(name_a) and name_a == name_b


def business_facts(page_jsonld: Any, home: Any) -> tuple[list[tuple[str, Any, str]], bool]:
    """([(eigenschap, waarde, bron)], organisatie alleen op de homepage).

    Eerst de gegevens van de pagina zelf, aangevuld met die van de homepage als het dezelfde organisatie
    is (zelfde @id of naam) of de pagina er zelf geen heeft. Bron: `SOURCE_THIS_PAGE` of `SOURCE_HOMEPAGE`.
    """
    own = business_of(page_jsonld)
    site = business_of(home) if home else None
    if own and site and not _same_org(own, site):
        site = None
    rows: list[tuple[str, Any, str]] = []
    for key in _BUSINESS_KEYS:
        if own and key in own:
            rows.append((key, own[key], SOURCE_THIS_PAGE))
        elif site and key in site:
            rows.append((key, site[key], SOURCE_HOMEPAGE))
    return rows, own is None and site is not None


def _business_value(key: str, value: Any) -> str:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        text = ", ".join(value)
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value).strip()
    return _clip(text, MAX_BUSINESS_ADDRESS_CHARS if key == "address" else MAX_BUSINESS_VALUE_CHARS)


def _business_section(page_jsonld: Any, home: Any) -> list[str]:
    """Sectie "Bedrijfsgegevens van de site" voor de brief, of [] als er geen organisatie bekend is."""
    rows, home_only = business_facts(page_jsonld, home)
    if not rows:
        return []
    lines = ["Bedrijfsgegevens van de site (volledig uit de bestaande JSON-LD, niet ingekort; bron per gegeven):"]
    if home_only:
        lines.append("Organisatie van de site (van de homepage; staat NIET op deze pagina):")
    budget = MAX_BUSINESS_CHARS
    for index, (key, value, source) in enumerate(rows):
        line = f"- {key}: {_business_value(key, value)} (bron: {source})"
        if len(line) > budget:
            lines.append(f"- … nog {len(rows) - index} gegeven(s) weggelaten (te lang)")
            break
        lines.append(line)
        budget -= len(line)
    has_address = any(key == "address" for key, _, _ in rows)
    lines.append("  Gebruik deze gegevens voor Organization, LocalBusiness (en subtypes), provider en publisher, "
                 "ook als ze niet in de tekst van de pagina staan.")
    if has_address:
        lines.append("  Schrijf het adres als volledige PostalAddress (streetAddress, postalCode, addressLocality, "
                     "addressCountry, en addressRegion als die er staat) met precies deze waarden.")
    else:
        lines.append("  Er staat geen adres bij de organisatie: verzin er geen (bij een verplicht adres geldt de "
                     "regel voor plaatshouders).")
    if home_only:
        lines.append("  Neem deze organisatie beknopt op als eigen node in de @graph (met precies deze @id, "
                     "name, url en logo) en verwijs ernaar als publisher of provider, omdat ze op deze pagina "
                     "niet gedefinieerd is; schrijf je zelf een Organization of LocalBusiness, gebruik dan alle "
                     "gegevens hierboven.")
    return lines


# --- brief voor de agent ---------------------------------------------------------

_GOOGLE_RULES = ("geen vaste regels in het dashboard: gebruik de door Google gedocumenteerde verplichte en "
                 "aanbevolen eigenschappen van dit type (eigen kennis), elk alleen met een waarde uit de invoer")


def _hint(type_name: str) -> str | None:
    """Hint van het type zelf, of van het algemenere type (LocalBusiness-subtype, artikel)."""
    if type_name in _TYPE_HINTS:
        return _TYPE_HINTS[type_name]
    if type_name != "LocalBusiness" and REQUIRED.get(type_name) == REQUIRED["LocalBusiness"]:
        return _TYPE_HINTS["LocalBusiness"]
    if type_name in ARTICLE_TYPES:
        return _TYPE_HINTS["Article"]
    return None


def _requirements(type_name: str) -> str:
    required = REQUIRED.get(type_name)
    hint = _hint(type_name)
    if required:
        parts = ["verplicht: " + ", ".join(" of ".join(alternatives) for alternatives in required)]
    elif hint:
        parts = ["verplicht: name (geen vaste regels)"]
    else:
        parts = [_GOOGLE_RULES]
    recommended = RECOMMENDED.get(type_name)
    if recommended:
        parts.append("aanbevolen: " + ", ".join(" of ".join(alternatives) for alternatives in recommended))
    if hint:
        parts.append(hint)
    elif required:
        parts.append("vul aan met de door Google gedocumenteerde aanbevolen eigenschappen van dit type")
    return "; ".join(parts)


def _compact(raw: str) -> str:
    try:
        return json.dumps(json.loads(raw.strip()), ensure_ascii=False, separators=(",", ":"))
    except (ValueError, TypeError):
        return raw.strip()


def _jsonld_block(blocks: list[str]) -> list[str]:
    lines: list[str] = []
    budget = MAX_JSONLD_CHARS
    texts = [t for t in (_compact(b) for b in blocks) if t]
    for index, text in enumerate(texts):
        if budget <= 0:
            lines.append(f"… en nog {len(texts) - index} blok(ken), weggelaten")
            break
        clipped = _clip(text, min(MAX_BLOCK_CHARS, budget))
        lines.append(f"Blok {index + 1}: {clipped}")
        budget -= len(clipped)
    return lines


def _crumbs(url: str, content: ContentExtract) -> list[str]:
    """Kruimelpad-URL's van homepage tot deze pagina, met een linktekst van de pagina als naam."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return []
    names: dict[str, str] = {}
    for link in content.links:
        text = str(link.get("text") or "").strip()
        if text:
            names.setdefault(url_key(str(link.get("url") or "")), text)
    segments = [s for s in parsed.path.split("/") if s]
    slash = "/" if parsed.path.endswith("/") else ""
    urls = [f"{parsed.scheme}://{parsed.netloc}/"]
    for depth in range(1, len(segments) + 1):
        urls.append(f"{parsed.scheme}://{parsed.netloc}/" + "/".join(segments[:depth]) + slash)
    if len(urls) > MAX_CRUMBS:
        urls = urls[:1] + urls[-(MAX_CRUMBS - 1):]
    lines: list[str] = []
    for crumb in urls:
        name = names.get(url_key(crumb))
        lines.append(f"- {crumb}" + (f" (linktekst op de pagina: {_clip(name, 120)})" if name else ""))
    return lines


def page_brief(
    facts: PageFacts,
    *,
    page_type: str | None,
    targets: list[str],
    customer: dict[str, str | None] | None,
    open_graph: Any = None,
    source: str = SOURCE_AUTO,
    wordpress: list[tuple[str, str]] | None = None,
    home: Any = None,
    lapse_ids: Any = None,
) -> str:
    """Alle feiten van één pagina als tekstblok voor de schema-agent.

    `wordpress`: publicatiegegevens uit de gekoppelde WordPress-site; `home`: de opgeslagen JSON-LD van
    de homepage (`home_jsonld`), waarmee de bedrijfsgegevens van de pagina worden aangevuld;
    `lapse_ids`: @id's van het standaardschema van Rank Math dat bij plaatsen vervalt.

    De bestaande JSON-LD wordt begrensd meegegeven; de bedrijfsgegevens (adres, telefoon, …) staan
    daarom apart en volledig in "Bedrijfsgegevens van de site" (`business_facts`).
    """
    content, signals = facts.content, facts.signals
    lapsing = {str(i) for i in lapse_ids or []}
    lines: list[str] = []
    if customer:
        lines.append(f"Klant: {customer.get('name')}")
        lines.append(f"Website: {customer.get('base_url')} (domein: {customer.get('domain')})")
    lines.append(f"Pagina: {facts.url}")
    lines.append(f"Paginatype: {PAGE_TYPES.get(page_type or '', page_type or 'onbekend')}")

    lines.append("")
    lines.append("Te schrijven types (alleen deze; gekozen door de collega):" if source == SOURCE_MANUAL
                 else "Te schrijven types (alleen deze):")
    lines.extend(f"- {t}: {_requirements(t)}" for t in targets)

    lines.append("")
    if facts.entities:
        lines.append("Bestaande entiteiten op de pagina (verwijs via @id, niet opnieuw definiëren):")
        lines.extend(
            f"- {entity_id} ({', '.join(types)})" + (f": {name}" if name else "")
            + (" [standaardschema van Rank Math; vervalt als dit voorstel in Rank Math wordt geplaatst: "
               "niet naar verwijzen, gegevens eruit mag je overnemen]" if entity_id in lapsing else "")
            for entity_id, types, name in facts.entities
        )
    else:
        lines.append("Bestaande entiteiten met @id: geen.")
    if facts.blocks:
        lines.append(f"Bestaande JSON-LD ({len(facts.blocks)} blok(ken), types: "
                     f"{', '.join(sorted(facts.existing_types)) or 'geen'}):")
        lines.extend(_jsonld_block(facts.blocks))
    else:
        lines.append("Bestaande JSON-LD: geen.")

    lines.append("")
    lines.append("Paginagegevens:")
    facts_list: list[tuple[str, Any]] = [
        ("Title", content.title),
        ("Meta description", content.meta_description),
        ("Eerste alinea", content.first_paragraph),
    ]
    if isinstance(open_graph, dict):
        for key, value in list(open_graph.items())[:12]:
            if isinstance(value, (str, int, float)) and str(value).strip():
                facts_list.append((f"Open Graph {key}", value))
    lines.extend(f"- {label}: {_clip(value)}" for label, value in facts_list if value not in (None, ""))
    contact: list[tuple[str, Any]] = [
        ("Telefoon", signals.get("phones")),
        ("E-mail", signals.get("emails")),
        ("Adres", signals.get("addresses")),
        ("KvK", signals.get("kvk")),
        ("BTW", signals.get("btw")),
        ("Profielen (sameAs)", [u for urls in (signals.get("profiles") or {}).values() for u in urls]),
    ]
    lines.extend(f"- {label}: {', '.join(str(v) for v in values[:5])}" for label, values in contact
                 if isinstance(values, list) and values)
    lines.append(f"- FAQ-blok herkend: {'ja' if signals.get('faq') else 'nee'}")
    if facts.publication:
        lines.append("Publicatiegegevens uit de HTML:")
        lines.extend(f"- {label}: {value}" for label, value in facts.publication)
    if wordpress:
        lines.append("Publicatiegegevens uit WordPress (gekoppelde site):")
        lines.extend(f"- {label}: {_clip(value)}" for label, value in wordpress)
    business = _business_section(facts.parsed, home)
    if business:
        lines.append("")
        lines.extend(business)

    images = [i for i in content.images if i.get("in_content")][:MAX_IMAGES]
    if images:
        lines.append("Afbeeldingen in de inhoud:")
        lines.extend(f"- {i['src']}" + (f" (alt: {_clip(i['alt'], 120)})" if i.get("alt") else "") for i in images)

    crumbs = _crumbs(facts.url, content)
    if crumbs and any(t == "BreadcrumbList" for t in targets):
        lines.append("Kruimelpad-URL's (homepage → deze pagina):")
        lines.extend(crumbs)

    headings = content.headings[:MAX_HEADINGS]
    if headings:
        lines.append("")
        lines.append("Koppenstructuur:")
        lines.extend(
            f"{'  ' * max(int(h.get('level') or 1) - 1, 0)}H{h.get('level')}: {_clip(h.get('text'), 200)}"
            for h in headings
        )
    if content.body_text:
        lines.append("")
        lines.append("Tekst van de pagina (hoofdinhoud):")
        lines.append(_clip(content.body_text, MAX_BODY_TEXT_CHARS))
    return "\n".join(lines)


# --- resultaat -----------------------------------------------------------------------

def build_script(jsonld: Any) -> str:
    """Volledig <script>-blok. `</` en `<!--` worden ge-escaped, zodat een waarde het element niet afsluit."""
    text = json.dumps(jsonld, indent=2, ensure_ascii=False)
    text = text.replace("</", "<\\/").replace("<!--", "\\u003c!--")
    return f'<script type="application/ld+json">\n{text}\n</script>'


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


def _written_types(jsonld: Any) -> list[str]:
    return _unique([t for node in flatten_jsonld(jsonld) for t in types_of(node)])


# --- gevraagde types als eigen entiteit -----------------------------------------------------

DEFAULT_CONTEXT = "https://schema.org"
# Hoe diep er in de JSON-LD naar geneste entiteiten wordt gezocht.
_SPLIT_MAX_DEPTH = 16


def _requested_set(target_types: Any) -> set[str]:
    """Gevraagde types; bij "A|B" telt elk alternatief."""
    return {alt.strip() for t in target_types or [] for alt in str(t).split("|") if alt.strip()}


def _graph_parts(jsonld: Any) -> tuple[Any, list[Any], dict[str, Any]]:
    """(@context, entiteiten op het hoogste niveau, overige sleutels van het buitenste object)."""
    if isinstance(jsonld, dict) and isinstance(jsonld.get("@graph"), list):
        outer = {k: v for k, v in jsonld.items() if k not in ("@context", "@graph")}
        return jsonld.get("@context") or DEFAULT_CONTEXT, list(jsonld["@graph"]), outer
    if isinstance(jsonld, dict):
        return jsonld.get("@context") or DEFAULT_CONTEXT, [_without_context(jsonld)], {}
    if isinstance(jsonld, list):
        context = next((n["@context"] for n in jsonld if isinstance(n, dict) and n.get("@context")), DEFAULT_CONTEXT)
        return context, [_without_context(n) if isinstance(n, dict) else n for n in jsonld], {}
    return DEFAULT_CONTEXT, [], {}


def _is_requested(value: Any, requested: set[str]) -> bool:
    return isinstance(value, dict) and bool(set(types_of(value)) & requested)


def _all_ids(value: Any, depth: int = 0) -> set[str]:
    found: set[str] = set()
    if depth > _SPLIT_MAX_DEPTH:
        return found
    if isinstance(value, dict):
        if _node_id(value):
            found.add(_node_id(value))
        for item in value.values():
            found |= _all_ids(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            found |= _all_ids(item, depth + 1)
    return found


def has_nested_targets(jsonld: Any, target_types: Any) -> bool:
    """Staat er een gevraagd type genest in een andere entiteit (en dus niet op het hoogste niveau)?"""
    requested = _requested_set(target_types)
    if not requested:
        return False

    def walk(value: Any, depth: int) -> bool:
        if depth > _SPLIT_MAX_DEPTH:
            return False
        if isinstance(value, list):
            return any(walk(item, depth + 1) for item in value)
        if isinstance(value, dict):
            return _is_requested(value, requested) or any(walk(item, depth + 1) for item in value.values())
        return False

    return any(isinstance(node, dict) and any(walk(v, 1) for v in node.values())
               for node in _graph_parts(jsonld)[1])


def split_target_entities(jsonld: Any, target_types: Any, page_url: str) -> dict[str, Any]:
    """Elk gevraagd type als eigen entiteit op het hoogste niveau van `@graph`.

    Rank Math krijgt één schema per entiteit op het hoogste niveau (`rankmath_schema.to_rankmath_schemas`);
    een gevraagd type dat genest staat (Brand als `brand` van een Product) zou anders geen eigen schema
    worden. Een geneste entiteit met een gevraagd type verhuist naar het hoogste niveau (achter de
    bestaande, in de volgorde waarin ze gevonden zijn) en op de oude plek komt `{"@id": …}`. Zonder
    eigen @id krijgt hij `<pagina-URL>#<type in kleine letters>`, uniek gemaakt met -2, -3. Staat er al
    een entiteit met die @id (op het hoogste niveau of eerder verhuisd), dan worden alleen de
    ontbrekende eigenschappen aangevuld. Pure verwijzingen, niet-gevraagde types (Offer, PostalAddress,
    ListItem, …) en entiteiten op het hoogste niveau blijven zoals ze zijn.

    Vast en zonder model; idempotent. Het resultaat is altijd één object met @context en @graph.
    """
    requested = _requested_set(target_types)
    context, nodes, outer = _graph_parts(jsonld)
    base = str(page_url or "").split("#", 1)[0]
    used_ids = _all_ids(nodes)
    top_index: dict[str, int] = {}
    for index, node in enumerate(nodes):
        if isinstance(node, dict) and _node_id(node):
            top_index.setdefault(_node_id(node), index)
    moved: list[dict[str, Any]] = []
    moved_index: dict[str, int] = {}
    merges: list[tuple[str, dict[str, Any]]] = []

    def new_id(node: dict[str, Any]) -> str:
        name = next(t for t in types_of(node) if t in requested).lower()
        candidate, n = f"{base}#{name}", 2
        while candidate in used_ids:
            candidate, n = f"{base}#{name}-{n}", n + 1
        used_ids.add(candidate)
        return candidate

    def visit(value: Any, depth: int) -> Any:
        if depth > _SPLIT_MAX_DEPTH:
            return value
        if isinstance(value, list):
            return [visit(item, depth + 1) for item in value]
        if not isinstance(value, dict):
            return value
        if not _is_requested(value, requested):
            return {k: visit(v, depth + 1) for k, v in value.items()}
        node_id = _node_id(value) or new_id(value)
        if node_id in top_index or node_id in moved_index:
            merges.append((node_id, {k: visit(v, depth + 1) for k, v in value.items() if k != "@id"}))
            return {"@id": node_id}
        # Eerst de plek vastleggen: zo blijft de volgorde die van het vinden (ook bij dieper geneste).
        moved_index[node_id] = len(moved)
        moved.append({})
        entity: dict[str, Any] = {}
        for k, v in value.items():
            if k == "@id":
                entity["@id"] = node_id
                continue
            entity[k] = visit(v, depth + 1)
            if k == "@type" and "@id" not in value:
                entity["@id"] = node_id
        moved[moved_index[node_id]] = entity
        return {"@id": node_id}

    top = [{k: visit(v, 1) for k, v in node.items()} if isinstance(node, dict) else node for node in nodes]
    graph = top + moved
    for node_id, props in merges:
        target = graph[top_index[node_id]] if node_id in top_index else moved[moved_index[node_id]]
        for k, v in props.items():
            target.setdefault(k, v)
    return {"@context": context, **outer, "@graph": graph}


def _placeholders(jsonld: Any, reported: Any) -> list[str]:
    """Plaatshouders die echt in de JSON-LD staan: eerst die van het model, dan wat er verder in staat."""
    text = json.dumps(jsonld, ensure_ascii=False)
    from_model = [str(p).strip() for p in reported if str(p).strip() in text] if isinstance(reported, list) else []
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            found.extend(_PLACEHOLDER_RE.findall(value))

    walk(jsonld)
    return _unique(from_model + found)


def _without_context(node: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in node.items() if k != "@context"}


def _graph_row(node: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "types": types_of(node),
        "id": _node_id(node) or None,
        "status": status,
        "properties": [str(k) for k in node if not str(k).startswith("@")],
    }


def capped_nodes(parsed: Any, limit: int = MAX_EXISTING_JSONLD_BYTES) -> tuple[list[dict[str, Any]], int]:
    """Top-level nodes van de bestaande JSON-LD, samen hooguit `limit` bytes (als JSON).

    Bij overschrijding vallen de grootste nodes weg. Geeft (nodes, aantal weggelaten).
    """
    nodes = flatten_jsonld(parsed)
    sizes = [len(json.dumps(node, ensure_ascii=False).encode("utf-8")) for node in nodes]
    total, dropped = sum(sizes), set()
    for index in sorted(range(len(nodes)), key=lambda i: -sizes[i]):
        if total <= limit:
            break
        dropped.add(index)
        total -= sizes[index]
    return [node for index, node in enumerate(nodes) if index not in dropped], len(dropped)


def page_graph_of(stored: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """(page_graph, full_script) van een opgeslagen voorstel.

    Bestaande nodes krijgen "existing", of "lapses" als ze bij het standaardschema van Rank Math
    horen dat bij plaatsen vervalt; nodes uit het voorstel "new". Zonder bewaarde bestaande markup
    (voorstel van vóór deze functie) alleen de nieuwe nodes en geen full_script.
    """
    jsonld = stored.get("jsonld")
    new_nodes = flatten_jsonld(jsonld) if jsonld else []
    existing = stored.get("existing_nodes")
    if not isinstance(existing, list):
        return [_graph_row(node, "new") for node in new_nodes], ""
    lapse_ids = {str(i) for i in stored.get("lapse_ids") or []}
    rows: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for node in existing:
        if not isinstance(node, dict):
            continue
        lapses = bool(_node_id(node)) and _node_id(node) in lapse_ids
        rows.append(_graph_row(node, "lapses" if lapses else "existing"))
        if not lapses:
            kept.append(_without_context(node))
    rows.extend(_graph_row(node, "new") for node in new_nodes)
    if not new_nodes:
        return rows, ""
    graph = kept + [_without_context(node) for node in new_nodes]
    return rows, build_script({"@context": "https://schema.org", "@graph": graph})


def _from_stored(stored: dict[str, Any], generated_at: datetime, *, cached: bool,
                 choice: Any = None) -> SchemaMarkupResult:
    """Resultaat van een opgeslagen voorstel; `choice` is de huidige typekeuze van de pagina."""
    jsonld = stored.get("jsonld")
    targets = stored.get("target_types")
    if not isinstance(targets, list):  # voorstel van vóór de typekeuze: de geschreven top-level types
        targets = _unique([t for node in flatten_jsonld(jsonld or []) for t in types_of(node)])
    source = stored.get("target_types_source")
    page_graph, full_script = page_graph_of(stored)
    edited = stored.get("edited") if isinstance(stored.get("edited"), dict) else None
    return SchemaMarkupResult(
        script=build_script(jsonld) if jsonld else "",
        types=[str(t) for t in stored.get("types") or []],
        placeholders=[str(p) for p in stored.get("placeholders") or []],
        notes=str(stored.get("notes") or ""),
        problems=[str(p) for p in stored.get("problems") or []],
        generated_at=generated_at,
        cached=cached,
        nothing_missing=False,
        # Ontbreekt bij schema's die vóór dit veld zijn opgeslagen.
        existing_types=[str(t) for t in stored.get("existing_types") or []],
        target_types=[str(t) for t in targets],
        target_types_source=source if source in (SOURCE_MANUAL, SOURCE_AUTO) else SOURCE_AUTO,
        stale=is_stale(stored, choice),
        omitted=[str(o) for o in stored.get("omitted") or []],
        page_graph=page_graph,
        full_script=full_script,
        edited=edited is not None,
        edited_at=_parse_time(edited.get("edited_at")) if edited else None,
    )


def _parse_time(raw: Any) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def stored_result(page: LaunchScanPage) -> SchemaMarkupResult | None:
    """Het opgeslagen voorstel als resultaat (zonder ophalen of modelaanroep), of None."""
    if not isinstance(page.schema_suggestion, dict) or not page.schema_suggestion_at:
        return None
    return _from_stored(page.schema_suggestion, page.schema_suggestion_at, cached=True,
                        choice=page.schema_target_types)


def _nothing_missing(page_type: str | None, facts: PageFacts, *, choice: Any = None,
                     skipped: list[str] | None = None) -> SchemaMarkupResult:
    existing_types = facts.existing_types
    manual = normalize_choice(choice)
    expected = EXPECTED_SCHEMA.get(page_type or "")
    if manual:
        notes = f"De gekozen schema-types staan al op de pagina ({', '.join(skipped or manual)})."
    elif expected:
        notes = (f"Het verwachte schema voor dit paginatype staat al op de pagina "
                 f"({', '.join(e.replace('|', ' of ') for e in expected)}).")
    else:
        notes = "Voor dit paginatype wordt geen schema verwacht en er is geen FAQ-blok herkend."
    nodes, _ = capped_nodes(facts.parsed)
    return SchemaMarkupResult(script="", types=[], placeholders=[], notes=notes, problems=[],
                              generated_at=_now(), cached=False, nothing_missing=True,
                              existing_types=sorted(existing_types),
                              target_types=requested_types(page_type, manual, facts.signals),
                              target_types_source=SOURCE_MANUAL if manual else SOURCE_AUTO,
                              page_graph=[_graph_row(node, "existing") for node in nodes])


def _omitted(reported: Any) -> list[str]:
    """Door de agent gemelde weggelaten eigenschappen in de vorm "Type.eigenschap"."""
    if not isinstance(reported, list):
        return []
    values = [str(v).strip() for v in reported if isinstance(v, str)]
    return _unique([v for v in values if len(v) <= 120 and _OMITTED_RE.match(v)])[:MAX_OMITTED]


def _parse_output(output: Any) -> tuple[Any, dict[str, Any]]:
    """(jsonld-object, ruwe agentuitvoer). Gooit `SchemaMarkupError` bij ongeldige JSON."""
    try:
        data = output.parsed()
    except ValueError as exc:
        raise SchemaMarkupError("Het AI-model gaf geen geldig antwoord. Probeer het opnieuw.") from exc
    raw = str(data.get("jsonld") or "").strip()
    if raw.lower().startswith("<script"):
        blocks = extract_jsonld_blocks(raw)
        raw = blocks[0].strip() if blocks else raw
    if not raw:
        raise SchemaMarkupError("Het AI-model gaf geen JSON-LD terug. Probeer het opnieuw.")
    try:
        jsonld = json.loads(raw)
    except ValueError as exc:
        raise SchemaMarkupError("Het AI-model gaf ongeldige JSON-LD terug (geen geldige JSON). "
                                "Probeer het opnieuw.") from exc
    if not isinstance(jsonld, dict):
        raise SchemaMarkupError("Het AI-model gaf geen JSON-LD-object terug. Probeer het opnieuw.")
    return jsonld, data


def generate_schema_markup(
    db: Session, page: LaunchScanPage, *, user_id: str, regenerate: bool = False
) -> SchemaMarkupResult:
    """Geeft het opgeslagen schema terug tenzij `regenerate`; anders ophalen, bepalen en genereren.

    Gooit `MissingUserOpenAIKeyError` als er geen OpenAI-key is, `SchemaMarkupError`
    als de pagina niet op te halen is of de modelaanroep mislukt, niets oplevert, afgekapt
    is of geen geldige JSON geeft, en `SchemaMarkupPageGoneError` als de pagina tijdens
    de aanroep is verdwenen. Ontbreekt er niets, dan volgt een resultaat met
    `nothing_missing` zonder modelaanroep en zonder iets op te slaan.

    Ophalen en de modelaanroep kunnen lang duren. Daarom wordt de sessie daarvoor gesloten
    (transactie dicht, verbinding terug naar de pool; `page` is daarna losgekoppeld) en de
    pagina pas daarna opnieuw opgehaald om het resultaat op te slaan.
    """
    # Een voorstel in een verouderde vorm (van vóór de rijkere generator, of met geneste gevraagde types)
    # telt niet als opgeslagen versie: opnieuw maken.
    if (not regenerate and isinstance(page.schema_suggestion, dict) and page.schema_suggestion_at
            and not outdated_format(page.schema_suggestion)):
        return _from_stored(page.schema_suggestion, page.schema_suggestion_at, cached=True,
                            choice=page.schema_target_types)
    from app.features.launch_checklist.services import rankmath_schema  # wederzijdse import

    previous = page.schema_suggestion if isinstance(page.schema_suggestion, dict) else {}
    placement = previous.get("placement") if isinstance(previous.get("placement"), dict) else None
    page_id = page.id
    page_type = page.page_type
    fetch_url = page.final_url or page.url
    open_graph = page.open_graph
    choice = normalize_choice(page.schema_target_types)
    scan = db.get(LaunchScan, page.scan_id)
    customer_row = db.get(CustomerWebsite, scan.customer_website_id) if scan is not None else None
    customer = (
        {"name": customer_row.name, "base_url": customer_row.base_url, "domain": customer_row.domain}
        if customer_row is not None else None
    )
    home = home_jsonld(db, page)
    # Extra feiten uit de gekoppelde WordPress-site; zonder (bruikbare) koppeling gewoon zonder.
    try:
        wp = rankmath_schema.connect_quietly(rankmath_schema.site_for_customer(db, customer_row, user_id))
    except Exception:  # noqa: BLE001 - alleen voor extra feiten; nooit fataal
        logger.info("WordPress-koppeling voor pagina %s niet op te zoeken", page_id, exc_info=True)
        wp = None
    db.close()

    html, final_url = fetch_page_html(fetch_url)
    root_domain = root_domain_of(final_url) or urlparse(final_url).netloc
    # Na een plaatsing tellen de geplaatste nodes niet als "al aanwezig", anders zou een nieuw
    # voorstel ze missen en zou opnieuw plaatsen ze verwijderen.
    facts = analyze_page(html, final_url, root_domain, placement=placement)
    rank_math = rank_math_facts(html, placement)
    # Bij een eigen keuze telt het standaardschema van Rank Math (`#richSnippet`) niet als aanwezig:
    # dat vervalt zodra het gekozen schema wordt geplaatst, en de keuze is juist om het te vervangen.
    manual = normalize_choice(choice) is not None
    present = rank_math.kept_types if manual and rank_math.detected else facts.existing_types
    targets, skipped, source = plan_targets(page_type, present, facts.signals, choice)
    if not targets:
        return _nothing_missing(page_type, facts, choice=choice, skipped=skipped)
    wordpress = rankmath_schema.wordpress_post_facts(wp, final_url) if wp is not None else []
    brief = page_brief(facts, page_type=page_type, targets=targets, customer=customer, open_graph=open_graph,
                       source=source, wordpress=wordpress, home=home, lapse_ids=rank_math.default_ids)

    try:
        result = run_agent(AGENTS["schema_markup"](), user_id=user_id, input=brief, context=None)
    except MissingUserOpenAIKeyError:
        raise
    except Exception as exc:
        logger.exception("Schema voor pagina %s genereren mislukt", page_id)
        raise SchemaMarkupError(f"Het AI-model gaf een fout: {exc}") from exc
    if result.incomplete_reason is not None:
        logger.warning("Schema voor pagina %s afgekapt (%s)", page_id, result.incomplete_reason)
        raise SchemaMarkupError(
            "Het AI-model heeft het schema niet afgemaakt "
            f"({_INCOMPLETE_REASONS.get(result.incomplete_reason, result.incomplete_reason)}). "
            "Probeer het opnieuw."
        )
    jsonld, data = _parse_output(result)
    # Elk gevraagd type als eigen entiteit (dus als eigen schema in Rank Math), vóór validatie en opslag.
    jsonld = split_target_entities(jsonld, targets, final_url)

    validation = validate_blocks([json.dumps(jsonld, ensure_ascii=False)])
    notes = str(data.get("notes") or "").strip()
    if skipped:
        notes = " ".join(filter(None, [notes, f"Overgeslagen omdat ze al op de pagina staan: {', '.join(skipped)}."]))
    existing_nodes, dropped = capped_nodes(facts.parsed)
    suggestion = {
        "jsonld": jsonld,
        "types": _written_types(jsonld) or _unique([str(t) for t in data.get("types") or []]),
        "placeholders": _placeholders(jsonld, data.get("placeholders")),
        "notes": notes,
        "problems": [describe_problem(p) for p in validation["problems"]],
        # Wat er al op de pagina stond (niet herhaald); de dialog toont het naast het blok.
        "existing_types": sorted(facts.existing_types),
        # Waarvoor het voorstel is gemaakt; `target_choice` is de eigen keuze op dat moment (None =
        # automatisch) en bepaalt `stale`.
        "target_types": targets,
        "target_types_source": source,
        "target_choice": choice,
        "omitted": _omitted(data.get("omitted")),
        # Volledige bestaande JSON-LD (zonder door ons geplaatste nodes) voor de complete markup na
        # plaatsen, plus de @id's van het standaardschema van Rank Math dat dan vervalt.
        "existing_nodes": existing_nodes,
        "existing_nodes_dropped": dropped,
        "lapse_ids": rank_math.default_ids,
        # Voor "Plaats in Rank Math". Na een plaatsing is het standaardschema van Rank Math al
        # van de pagina verdwenen; dan gelden de waarden van vóór het plaatsen.
        "rank_math_detected": rank_math.detected,
        "default_types": list(placement.get("default_types") or []) if placement else rank_math.default_types,
        "had_graph": bool(placement.get("had_graph")) if placement else rank_math.had_graph,
        "kept_types": sorted(rank_math.kept_types),
    }

    stored = db.get(LaunchScanPage, page_id)
    if stored is None:
        raise SchemaMarkupPageGoneError(page_id)
    # Een plaatsing op de klantsite blijft bestaan bij opnieuw genereren. De beoordeling ook, maar die
    # geldt alleen zolang de JSON-LD gelijk is (hash, zie `rankmath_schema.review_view`).
    for key in ("placement", "review"):
        if isinstance(stored.schema_suggestion, dict) and isinstance(stored.schema_suggestion.get(key), dict):
            suggestion[key] = stored.schema_suggestion[key]
    now = _now()
    stored.schema_suggestion = suggestion
    stored.schema_suggestion_at = now
    try:
        db.commit()
    except StaleDataError as exc:  # net tussen ophalen en opslaan verwijderd
        db.rollback()
        raise SchemaMarkupPageGoneError(page_id) from exc
    return _from_stored(suggestion, now, cached=False, choice=stored.schema_target_types)


_INCOMPLETE_REASONS = {
    "max_output_tokens": "maximale lengte bereikt",
    "content_filter": "geblokkeerd door het inhoudsfilter",
}


# --- met de hand bewerken -------------------------------------------------------------------

MAX_EDIT_BYTES = 100_000
_SCRIPT_OPEN_RE = re.compile(r"^\s*<script\b([^>]*)>", re.IGNORECASE)
_SCRIPT_CLOSE_RE = re.compile(r"</script\s*>\s*$", re.IGNORECASE)
# Meldingen van `json` in het Nederlands (begin van de Engelse melding → Nederlandse tekst).
_JSON_ERRORS = (
    ("Expecting ',' delimiter", "komma verwacht"),
    ("Expecting ':' delimiter", "dubbele punt verwacht"),
    ("Expecting property name enclosed in double quotes", "eigenschapsnaam tussen dubbele aanhalingstekens "
                                                          "verwacht (of een komma te veel)"),
    ("Expecting value", "waarde verwacht"),
    ("Unterminated string", "tekst zonder afsluitend aanhalingsteken"),
    ("Extra data", "extra tekst na het einde van de JSON"),
    ("Invalid control character", "ongeldig teken (bijv. een regeleinde of tab) binnen een tekst"),
    ("Invalid \\escape", "ongeldige escape met \\"),
    ("Invalid \\uXXXX escape", "ongeldige \\u-escape"),
)


def _json_error(exc: json.JSONDecodeError, text: str, offset: int) -> str:
    """Nederlandse melding met regel en kolom in de tekst zoals de gebruiker die stuurde."""
    reason = next((dutch for english, dutch in _JSON_ERRORS if exc.msg.startswith(english)), exc.msg)
    pos = offset + exc.pos
    line = text.count("\n", 0, pos) + 1
    column = pos - (text.rfind("\n", 0, pos) + 1) + 1
    return f"De JSON-LD is geen geldige JSON: {reason} (regel {line}, kolom {column})."


def _reject_constant(name: str) -> Any:
    raise SchemaMarkupEditError(f"De JSON-LD is geen geldige JSON: {name} is geen geldige waarde.")


def parse_edited_jsonld(text: str) -> dict[str, Any]:
    """Bewerkte JSON-LD (kale JSON of één `<script type="application/ld+json">`-blok) als één object.

    Gooit `SchemaMarkupEditError` met een Nederlandse reden: te groot, leeg, ongeldige JSON (met regel en
    kolom), geen object, of geen entiteit met @type. Het resultaat heeft altijd @context.
    """
    if not isinstance(text, str):
        raise SchemaMarkupEditError("De JSON-LD ontbreekt.")
    size = len(text.encode("utf-8"))
    if size > MAX_EDIT_BYTES:
        raise SchemaMarkupEditError(f"De JSON-LD is te groot ({size // 1000} kB); maximaal "
                                    f"{MAX_EDIT_BYTES // 1000} kB.")
    start, end = 0, len(text)
    opening = _SCRIPT_OPEN_RE.match(text)
    if opening:
        if not _LDJSON_ATTR_RE.search(opening.group(1)):
            raise SchemaMarkupEditError('Alleen een <script type="application/ld+json">-blok of kale JSON '
                                        "is toegestaan.")
        closing = _SCRIPT_CLOSE_RE.search(text, opening.end())
        if not closing:
            raise SchemaMarkupEditError("Het <script>-blok is niet afgesloten met </script>.")
        start, end = opening.end(), closing.start()
        if re.search(r"</script\s*>", text[start:end], re.IGNORECASE):
            raise SchemaMarkupEditError("Plak één JSON-LD-blok, niet meerdere <script>-blokken.")
    body = text[start:end]
    if not body.strip():
        raise SchemaMarkupEditError("De JSON-LD is leeg.")
    try:
        data = json.loads(body, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise SchemaMarkupEditError(_json_error(exc, text, start)) from exc
    except RecursionError as exc:
        raise SchemaMarkupEditError("De JSON-LD is te diep genest.") from exc
    if not isinstance(data, dict):
        raise SchemaMarkupEditError("De JSON-LD moet één object zijn ({ … }) met @type of @graph; zet "
                                    "meerdere entiteiten in een @graph.")
    graph = data.get("@graph")
    if graph is None:
        if not types_of(data):
            raise SchemaMarkupEditError("Het object heeft geen @type en geen @graph; geef elke entiteit een "
                                        "@type (bijv. \"LocalBusiness\") of zet de entiteiten in een @graph.")
    else:
        if isinstance(graph, dict):
            graph = [graph]
        if not isinstance(graph, list):
            raise SchemaMarkupEditError("@graph moet een lijst met entiteiten zijn.")
        if not any(isinstance(node, dict) and types_of(node) for node in graph):
            raise SchemaMarkupEditError("De @graph bevat geen entiteiten met een @type.")
        data = {**data, "@graph": graph}
    if not data.get("@context"):
        data = {"@context": DEFAULT_CONTEXT, **{k: v for k, v in data.items() if k != "@context"}}
    return data


def _path_filled(node: Any, path: list[str]) -> bool:
    if not path:  # een verwijzing ({"@id": …}) telt hier wel als ingevuld
        return bool(node.strip()) if isinstance(node, str) else node not in (None, [], {})
    if isinstance(node, list):
        return any(_path_filled(item, path) for item in node)
    return isinstance(node, dict) and _path_filled(node.get(path[0]), path[1:])


def still_omitted(omitted: Any, jsonld: Any) -> list[str]:
    """Regels "Type.eigenschap" van `omitted` waarvan de eigenschap nog nergens is ingevuld.

    Ingevuld = bij een entiteit (ook genest) met dat type staat een niet-lege waarde; een
    plaatshouder telt ook als ingevuld (die staat al in `placeholders`).
    """
    if not isinstance(omitted, list):
        return []
    nodes: list[dict[str, Any]] = []

    def walk(value: Any, depth: int) -> None:
        if depth > _SPLIT_MAX_DEPTH:
            return
        if isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
        elif isinstance(value, dict):
            if value.get("@type"):
                nodes.append(value)
            for item in value.values():
                walk(item, depth + 1)

    walk(jsonld, 0)
    keep: list[str] = []
    for rule in (str(o) for o in omitted):
        type_name, _, rest = rule.partition(".")
        path = rest.split(".") if rest else []
        if not path or not any(type_name in types_of(n) and _path_filled(n, path) for n in nodes):
            keep.append(rule)
    return keep


def edit_schema_markup(db: Session, page: LaunchScanPage, text: str, *, user_id: str) -> SchemaMarkupResult:
    """Slaat een met de hand bewerkt voorstel op (alleen database: geen modelaanroep, geen HTTP).

    De JSON-LD wordt genormaliseerd (één object met @context en @graph), elk type waarvoor het voorstel is
    gemaakt wordt een eigen entiteit (`split_target_entities`), en types, plaatshouders, problemen en
    `omitted` worden opnieuw bepaald. De rest van het voorstel (bewaarde paginamarkup, typekeuze,
    plaatsing, beoordeling) blijft staan; beoordeling en `placement.current` volgen de hash van de
    JSON-LD en worden dus vanzelf "pending"/false als die verandert.

    Gooit `SchemaMarkupNoSuggestionError` zonder voorstel, `SchemaMarkupEditError` bij onbruikbare
    JSON-LD en `SchemaMarkupPageGoneError` als de pagina intussen is verwijderd.
    """
    suggestion = page.schema_suggestion if isinstance(page.schema_suggestion, dict) else None
    if not suggestion or not suggestion.get("jsonld") or not page.schema_suggestion_at:
        raise SchemaMarkupNoSuggestionError(page.id)
    jsonld = parse_edited_jsonld(text)
    targets = suggestion.get("target_types")
    if not isinstance(targets, list):  # voorstel van vóór de typekeuze (zie `_from_stored`)
        targets = _written_types(suggestion["jsonld"])
    jsonld = split_target_entities(jsonld, targets, page.final_url or page.url)
    validation = validate_blocks([json.dumps(jsonld, ensure_ascii=False)])
    now = _now()
    updated = {
        **suggestion,
        "jsonld": jsonld,
        "types": _written_types(jsonld),
        "placeholders": _placeholders(jsonld, None),
        "problems": [describe_problem(p) for p in validation["problems"]],
        "omitted": still_omitted(suggestion.get("omitted"), jsonld),
        "edited": {"user_id": user_id, "edited_at": now.isoformat()},
    }
    page_id, generated_at, choice = page.id, page.schema_suggestion_at, page.schema_target_types
    page.schema_suggestion = updated
    try:
        db.commit()
    except StaleDataError as exc:
        db.rollback()
        raise SchemaMarkupPageGoneError(page_id) from exc
    return _from_stored(updated, generated_at, cached=True, choice=choice)
