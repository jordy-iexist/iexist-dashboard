"""Ontbrekende JSON-LD voor één pagina ("Maak schema").

`generate_schema_markup` haalt de pagina opnieuw op (de opgeslagen JSON-LD is
ingekort en ruwe HTML wordt niet bewaard), bepaalt welke verwachte schema-types
ontbreken (`target_types`) en laat de schema-agent alleen die schrijven. Het
resultaat wordt gevalideerd en opgeslagen bij de pagina; een collega kopieert
het blok en plakt het zelf. Er wordt niets op de klantsite geschreven.

Per pagina kan een collega zelf de schema-types kiezen (`LaunchScanPage.schema_target_types`);
zonder keuze volgen ze uit het paginatype. Het voorstel bewaart ook de bestaande JSON-LD van de
pagina, zodat de response de complete markup na plaatsen kan tonen (`page_graph_of`).
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
               "alinea), image (hoofdafbeelding), url, mainEntityOfPage (verwijzing naar de WebPage), brand, "
               "sku/gtin/mpn als ze op de pagina staan, en in offers: price, priceCurrency, availability en url",
    "Brand": "name van het merk zoals op de pagina; koppel het via brand aan het Product; logo en url als bekend",
    "ItemList": "itemListElement met ListItem (position, url, name) voor de items op de pagina; numberOfItems",
    "BlogPosting": "headline (hooguit 110 tekens), description (meta description of eerste alinea), image "
                   "(og:image, uitgelichte afbeelding of hoofdafbeelding), datePublished en dateModified "
                   "(uit article:published_time/article:modified_time, WordPress of <time datetime>), author "
                   "(Person met name en url, uit meta author, Rank Math of WordPress; of een verwijzing naar een "
                   "bestaande Person die niet vervalt), publisher (verwijzing naar de organisatie), "
                   "mainEntityOfPage (verwijzing naar de WebPage), inLanguage en articleSection als bekend",
    "Article": "headline (hooguit 110 tekens), description (meta description of eerste alinea), image "
               "(og:image, uitgelichte afbeelding of hoofdafbeelding), datePublished en dateModified (uit "
               "article:published_time/article:modified_time, WordPress of <time datetime>), author (Person met "
               "name en url, of een verwijzing naar een bestaande Person die niet vervalt), publisher "
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


def is_stale(suggestion: Any, choice: Any) -> bool:
    """Er is een voorstel, maar de typekeuze van de pagina is sindsdien gewijzigd.

    Voorstellen van vóór de eigen keuze zijn automatisch gemaakt.
    """
    if not isinstance(suggestion, dict) or not suggestion.get("jsonld"):
        return False
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


def home_organization(db: Session, page: LaunchScanPage) -> dict[str, str] | None:
    """De Organization van de homepage in dezelfde scan, of None.

    Eerst de hoofdpagina (pad "/") van hetzelfde domein als de pagina, ook als die een ander paginatype
    kreeg (bijv. "landing"); daarna rijen met paginatype "home". Een scan kan meerdere subdomeinen
    bevatten, en de home-rij van een ander subdomein heeft de organisatie vaak niet.
    """
    host = urlparse(page.final_url or page.url or "").netloc.lower()
    rows = (
        db.query(LaunchScanPage)
        .filter(LaunchScanPage.scan_id == page.scan_id,
                or_(LaunchScanPage.page_type == "home", LaunchScanPage.path == "/"))
        .limit(20)
        .all()
    )
    rows.sort(key=lambda r: 0 if r.path == "/" and urlparse(r.final_url or r.url or "").netloc.lower() == host else 1)
    for row in rows:
        org = organization_of(row.jsonld)
        if org:
            return org
    return None


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
    organization: dict[str, str] | None = None,
    lapse_ids: Any = None,
) -> str:
    """Alle feiten van één pagina als tekstblok voor de schema-agent.

    `wordpress`: publicatiegegevens uit de gekoppelde WordPress-site; `organization`: de Organization
    van de homepage als de pagina zelf er geen heeft; `lapse_ids`: @id's van het standaardschema van
    Rank Math dat bij plaatsen vervalt.
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
    if organization:
        lines.append("Organisatie van de site (van de homepage; staat NIET op deze pagina):")
        lines.extend(f"- {key}: {organization[key]}" for key in ("type", "@id", "name", "url", "logo")
                     if organization.get(key))
        lines.append("  Neem deze organisatie beknopt op als eigen node in de @graph (met precies deze @id, "
                     "name, url en logo) en verwijs ernaar als publisher of provider, omdat ze op deze pagina "
                     "niet gedefinieerd is.")

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
    )


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
    if not regenerate and isinstance(page.schema_suggestion, dict) and page.schema_suggestion_at:
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
    site_org = home_organization(db, page)
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
    has_org = any(is_org_type(t) for t in facts.existing_types)
    brief = page_brief(facts, page_type=page_type, targets=targets, customer=customer, open_graph=open_graph,
                       source=source, wordpress=wordpress, organization=None if has_org else site_org,
                       lapse_ids=rank_math.default_ids)

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
