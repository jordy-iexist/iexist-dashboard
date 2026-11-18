"""Ontbrekende JSON-LD voor één pagina ("Maak schema").

`generate_schema_markup` haalt de pagina opnieuw op (de opgeslagen JSON-LD is
ingekort en ruwe HTML wordt niet bewaard), bepaalt welke verwachte schema-types
ontbreken (`target_types`) en laat de schema-agent alleen die schrijven. Het
resultaat wordt gevalideerd en opgeslagen bij de pagina; een collega kopieert
het blok en plakt het zelf. Er wordt niets op de klantsite geschreven.
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

# Een tekst tussen rechte haken in de JSON-LD is een plaatshouder ("[naam van de auteur]").
_PLACEHOLDER_RE = re.compile(r"\[[^\[\]\n]{2,200}\]")

# Korte vakkennis per type, bovenop de verplichte eigenschappen uit `schema_validate`.
# Bewust hier en niet in `RECOMMENDED`: die lijst bepaalt ook de waarschuwingen van de scan.
# De hints noemen alles wat een entiteit volledig maakt; de agent laat weg wat niet in de invoer staat.
_TYPE_HINTS: dict[str, str] = {
    "Organization": "url, logo, contactPoint/telephone, address en sameAs alleen als ze in de invoer staan",
    "WebSite": "url van de homepage, name, publisher als verwijzing naar de organisatie",
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
               "alinea), image (hoofdafbeelding), url en mainEntityOfPage (verwijzing naar de WebPage)",
    "Brand": "name van het merk zoals op de pagina; koppel het via brand aan het Product",
    "ItemList": "itemListElement met ListItem (position, url, name) voor de items op de pagina",
    "BlogPosting": "headline, author (Person of verwijzing), datePublished alleen als de datum bekend is, "
                   "mainEntityOfPage als verwijzing naar de WebPage; ook description (meta description of "
                   "eerste alinea), image (hoofdafbeelding) en publisher (verwijzing naar de organisatie)",
    "Article": "headline, author (Person of verwijzing), datePublished alleen als de datum bekend is; ook "
               "description (meta description of eerste alinea), image (hoofdafbeelding), mainEntityOfPage "
               "(verwijzing naar de WebPage) en publisher (verwijzing naar de organisatie)",
    "Person": "name zoals op de pagina; jobTitle en worksFor (verwijzing naar de organisatie) als bekend; "
              "ook description, image (foto van de persoon) en url als ze op de pagina staan",
    "JobPosting": "title, description, datePosted, hiringOrganization (verwijzing), jobLocation met address; "
                  "ook url van deze pagina, mainEntityOfPage (verwijzing naar de WebPage) en "
                  "employmentType als dat op de pagina staat",
    "FAQPage": "mainEntity met Question (name) en acceptedAnswer (Answer met text), alleen vragen van de pagina",
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
    )


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


def target_types(page_type: str | None, existing_types: set[str], signals: dict[str, Any] | None) -> list[str]:
    """Te schrijven types: verwacht voor het paginatype min wat er al staat, plus FAQPage bij een FAQ.

    Bij "A|B" wordt het eerste alternatief gevraagd.
    """
    targets = [
        expected.split("|")[0]
        for expected in EXPECTED_SCHEMA.get(page_type or "", [])
        if not _is_present(expected, existing_types)
    ]
    if (signals or {}).get("faq") and "FAQPage" not in existing_types:
        targets.append("FAQPage")
    return targets


# --- brief voor de agent ---------------------------------------------------------

def _requirements(type_name: str) -> str:
    required = REQUIRED.get(type_name)
    parts = [
        "verplicht: " + ", ".join(" of ".join(alternatives) for alternatives in required)
        if required else "verplicht: name (geen vaste regels)"
    ]
    recommended = RECOMMENDED.get(type_name)
    if recommended:
        parts.append("aanbevolen: " + ", ".join(" of ".join(alternatives) for alternatives in recommended))
    if type_name in _TYPE_HINTS:
        parts.append(_TYPE_HINTS[type_name])
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
) -> str:
    """Alle feiten van één pagina als tekstblok voor de schema-agent."""
    content, signals = facts.content, facts.signals
    lines: list[str] = []
    if customer:
        lines.append(f"Klant: {customer.get('name')}")
        lines.append(f"Website: {customer.get('base_url')} (domein: {customer.get('domain')})")
    lines.append(f"Pagina: {facts.url}")
    lines.append(f"Paginatype: {PAGE_TYPES.get(page_type or '', page_type or 'onbekend')}")

    lines.append("")
    lines.append("Te schrijven types (alleen deze):")
    lines.extend(f"- {t}: {_requirements(t)}" for t in targets)

    lines.append("")
    if facts.entities:
        lines.append("Bestaande entiteiten op de pagina (verwijs via @id, niet opnieuw definiëren):")
        lines.extend(
            f"- {entity_id} ({', '.join(types)})" + (f": {name}" if name else "")
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


def _from_stored(stored: dict[str, Any], generated_at: datetime, *, cached: bool) -> SchemaMarkupResult:
    jsonld = stored.get("jsonld")
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
    )


def stored_result(page: LaunchScanPage) -> SchemaMarkupResult | None:
    """Het opgeslagen voorstel als resultaat (zonder ophalen of modelaanroep), of None."""
    if not isinstance(page.schema_suggestion, dict) or not page.schema_suggestion_at:
        return None
    return _from_stored(page.schema_suggestion, page.schema_suggestion_at, cached=True)


def _nothing_missing(page_type: str | None, existing_types: set[str]) -> SchemaMarkupResult:
    expected = EXPECTED_SCHEMA.get(page_type or "")
    if expected:
        notes = (f"Het verwachte schema voor dit paginatype staat al op de pagina "
                 f"({', '.join(e.replace('|', ' of ') for e in expected)}).")
    else:
        notes = "Voor dit paginatype wordt geen schema verwacht en er is geen FAQ-blok herkend."
    return SchemaMarkupResult(script="", types=[], placeholders=[], notes=notes, problems=[],
                              generated_at=_now(), cached=False, nothing_missing=True,
                              existing_types=sorted(existing_types))


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
        return _from_stored(page.schema_suggestion, page.schema_suggestion_at, cached=True)

    previous = page.schema_suggestion if isinstance(page.schema_suggestion, dict) else {}
    placement = previous.get("placement") if isinstance(previous.get("placement"), dict) else None
    page_id = page.id
    page_type = page.page_type
    fetch_url = page.final_url or page.url
    open_graph = page.open_graph
    scan = db.get(LaunchScan, page.scan_id)
    customer_row = db.get(CustomerWebsite, scan.customer_website_id) if scan is not None else None
    customer = (
        {"name": customer_row.name, "base_url": customer_row.base_url, "domain": customer_row.domain}
        if customer_row is not None else None
    )
    db.close()

    html, final_url = fetch_page_html(fetch_url)
    root_domain = root_domain_of(final_url) or urlparse(final_url).netloc
    # Na een plaatsing tellen de geplaatste nodes niet als "al aanwezig", anders zou een nieuw
    # voorstel ze missen en zou opnieuw plaatsen ze verwijderen.
    facts = analyze_page(html, final_url, root_domain, placement=placement)
    rank_math = rank_math_facts(html, placement)
    targets = target_types(page_type, facts.existing_types, facts.signals)
    if not targets:
        return _nothing_missing(page_type, facts.existing_types)
    brief = page_brief(facts, page_type=page_type, targets=targets, customer=customer, open_graph=open_graph)

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
    suggestion = {
        "jsonld": jsonld,
        "types": _written_types(jsonld) or _unique([str(t) for t in data.get("types") or []]),
        "placeholders": _placeholders(jsonld, data.get("placeholders")),
        "notes": str(data.get("notes") or "").strip(),
        "problems": [describe_problem(p) for p in validation["problems"]],
        # Wat er al op de pagina stond (niet herhaald); de dialog toont het naast het blok.
        "existing_types": sorted(facts.existing_types),
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
    return _from_stored(suggestion, now, cached=False)


_INCOMPLETE_REASONS = {
    "max_output_tokens": "maximale lengte bereikt",
    "content_filter": "geblokkeerd door het inhoudsfilter",
}
