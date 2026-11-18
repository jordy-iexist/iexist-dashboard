"""Het schema-voorstel van één pagina in Rank Math zetten ("Plaats in Rank Math").

Via de interne REST-routes van Rank Math op de WordPress-klantsite, met de login en het
Application Password van de gekoppelde `WordPressSite` (zoals de blog-publicatie):

- toevoegen en bijwerken: `POST rankmath/v1/updateSchemas` met sleutels `new-…` (antwoord:
  `{"new-…": meta_id}`) of `schema-<meta_id>` (antwoord `[]`). Met `metadata.type == "custom"`
  zet Rank Math het schema precies zo op de pagina, inclusief een eigen `@id`.
- verwijderen: `POST rankmath/v1/updateMeta` met `rank_math_delete_schema-<meta_id>`. Dat zet
  `rank_math_rich_snippet` op "off"; blijven er geen schema's over, dan verdwijnt de hele graph.
  Had de pagina die graph, dan wordt hij hersteld door `rank_math_rich_snippet` leeg te maken.

Een opgeslagen schema laat het standaardschema van Rank Math (`#richSnippet`) vervallen. Plaatsen
wordt geweigerd als daardoor een voor het paginatype verwacht type verdwijnt.

De plaatsing staat in `LaunchScanPage.schema_suggestion["placement"]` (geen migratie).
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlparse

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.db.models import CustomerWebsite, LaunchScan, LaunchScanPage, WordPressSite
from app.features.blogs.services.crypto_service import decrypt_secret
from app.features.blogs.services.wordpress_service import (
    WordPressServiceError,
    _build_basic_auth_header,
    _extract_error_message,
    _request_with_auth_redirect,
    _wordpress_rest_url,
    normalize_wordpress_url,
)
from app.features.launch_checklist.services import schema_markup
from app.features.launch_checklist.services.discovery import url_key
from app.features.launch_checklist.services.geo_extract import all_types, types_of
from app.features.launch_checklist.services.page_types import EXPECTED_SCHEMA
from app.services.site_matching import normalize_host as _host, site_for_customer  # noqa: F401

logger = logging.getLogger(__name__)

OBJECT_TYPE = "post"
# Queryparameter om bij de controle na het plaatsen een paginacache te omzeilen.
CACHE_BUSTER = "iexist_schema_check"
# Berichttypes die geen losse pagina zijn; worden bij het opzoeken van het ID overgeslagen.
_SKIP_POST_TYPES = {"post", "page", "attachment", "nav_menu_item", "elementor_library"}
MAX_EXTRA_POST_TYPES = 15

NO_SUGGESTION = "Er is nog geen schema-voorstel voor deze pagina; maak eerst een schema."
NOTHING_MISSING = "Het verwachte schema staat al op de pagina; er is niets om te plaatsen."
NO_SITE = ("Koppel de site bij Instellingen > WordPress (login met Application Password) "
           "om het schema direct in Rank Math te plaatsen.")
NO_RANK_MATH = "Rank Math is niet op deze pagina herkend; plaatsen kan alleen op sites met Rank Math."
# Velden in het voorstel die bij het genereren uit de pagina komen (zie `schema_markup.rank_math_facts`).
_RANK_MATH_KEYS = ("rank_math_detected", "default_types", "had_graph", "kept_types")

# Beoordeling van het voorstel door een collega (`schema_suggestion["review"]`).
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"
REVIEW_STATUSES = (REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED)
NOT_APPROVED = ("Het schema-voorstel is nog niet goedgekeurd; controleer het en keur het goed voordat het "
                "in Rank Math wordt geplaatst.")


class RankMathSchemaError(RuntimeError):
    """De klantsite gaf een fout of een onverwacht antwoord (de melding van WordPress zit erin)."""


class RankMathPlacementBlocked(ValueError):
    """Plaatsen is niet toegestaan of niet mogelijk; de tekst is de reden (één zin, Nederlands)."""


class RankMathPlacementNotFound(LookupError):
    """Er is geen plaatsing om te verwijderen."""


@dataclass
class PlacementState:
    """Wat de response over plaatsen (en de beoordeling van het voorstel) meegeeft."""

    can_place: bool
    reason: str
    replaces_default_types: list[str] = field(default_factory=list)
    # Response-vorm van de plaatsing, of None.
    placement: dict[str, Any] | None = None
    # Beoordeling van het huidige voorstel (zie `review_view`).
    review_status: str = REVIEW_PENDING
    reviewed_at: datetime | None = None


@dataclass
class _WordPress:
    site_id: str
    name: str
    base_url: str
    headers: dict[str, str]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def jsonld_hash(jsonld: Any) -> str:
    return hashlib.sha256(json.dumps(jsonld, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# --- gekoppelde site ---------------------------------------------------------------------

# `_host` en `site_for_customer` staan in `app.services.site_matching` (ook gebruikt door blogs).

def _placement_site(db: Session, placement: dict[str, Any], user_id: str) -> WordPressSite | None:
    site = db.get(WordPressSite, str(placement.get("site_id") or ""))
    if site is None or not site.is_active or site.created_by != user_id:
        return None
    return site


def _customer_of(db: Session, page: LaunchScanPage) -> CustomerWebsite | None:
    scan = db.get(LaunchScan, page.scan_id)
    return db.get(CustomerWebsite, scan.customer_website_id) if scan is not None else None


def _site_for_page(db: Session, page: LaunchScanPage, user_id: str,
                   placement: dict[str, Any] | None) -> tuple[WordPressSite | None, str]:
    """(site, reden). Na een plaatsing geldt de koppeling waarmee geplaatst is."""
    if placement:
        site = _placement_site(db, placement, user_id)
        if site is None:
            return None, ("Het schema is geplaatst via een WordPress-koppeling die niet (meer) van jou of "
                          "niet actief is; controleer Instellingen > WordPress.")
        return site, ""
    site = site_for_customer(db, _customer_of(db, page), user_id)
    return (site, "") if site is not None else (None, NO_SITE)


def _connect(site: WordPressSite) -> _WordPress:
    try:
        base_url = normalize_wordpress_url(site.base_url)
        password = decrypt_secret(str(site.app_password_encrypted or ""))
    except (WordPressServiceError, ValueError) as exc:
        raise RankMathSchemaError(f"De WordPress-koppeling is niet bruikbaar: {exc}") from exc
    return _WordPress(site_id=site.id, name=site.name, base_url=base_url,
                      headers=_build_basic_auth_header(site.wp_login, password))


# --- regels ---------------------------------------------------------------------------------

def _placeholders(suggestion: dict[str, Any]) -> list[str]:
    return [str(p) for p in suggestion.get("placeholders") or [] if str(p).strip()]


def default_loss(page_type: str | None, default_types: list[str], kept_types: set[str],
                 placed_types: set[str]) -> tuple[list[str], list[str]]:
    """(verwachte types die verdwijnen, standaardtypes die vervallen) als het standaardschema wegvalt."""
    before = kept_types | set(default_types)
    after = kept_types | placed_types
    lost = [
        expected.replace("|", " of ")
        for expected in EXPECTED_SCHEMA.get(page_type or "", [])
        if schema_markup._is_present(expected, before) and not schema_markup._is_present(expected, after)
    ]
    return lost, [t for t in default_types if t not in after]


def placement_check(suggestion: dict[str, Any] | None, page_type: str | None,
                    *, site_problem: str = "") -> tuple[str, list[str]]:
    """(reden, vervallen standaardtypes). Lege reden = plaatsen mag.

    Ontbreken de Rank Math-velden (voorstel van vóór deze functie), dan is dat onbekend en
    beslist het plaats-endpoint op de vers opgehaalde pagina.
    """
    if not isinstance(suggestion, dict) or not suggestion.get("jsonld"):
        return NO_SUGGESTION, []
    placeholders = _placeholders(suggestion)
    if placeholders:
        shown = ", ".join(placeholders[:3]) + (" …" if len(placeholders) > 3 else "")
        return (f"Het voorstel bevat nog plaatshouders ({shown}); kopieer het blok en vul ze zelf in, "
                "of genereer het schema opnieuw."), []
    if site_problem:
        return site_problem, []
    if suggestion.get("rank_math_detected") is False:
        return NO_RANK_MATH, []
    default_types, kept_types = suggestion.get("default_types"), suggestion.get("kept_types")
    if not isinstance(default_types, list) or not isinstance(kept_types, list):
        return "", []
    lost, replaces = default_loss(page_type, [str(t) for t in default_types], {str(t) for t in kept_types},
                                  all_types(suggestion["jsonld"]))
    if lost:
        return (f"Plaatsen laat het standaardschema van Rank Math vervallen en daarmee {', '.join(lost)}, "
                "dat voor dit paginatype verwacht wordt; kopieer het blok en plaats het zelf."), []
    return "", replaces


def placement_view(suggestion: dict[str, Any] | None) -> dict[str, Any] | None:
    placement = suggestion.get("placement") if isinstance(suggestion, dict) else None
    if not isinstance(placement, dict):
        return None
    return {
        "placed_at": placed_at_of(suggestion),
        "verified": bool(placement.get("verified")),
        "current": placement.get("jsonld_hash") == jsonld_hash(suggestion.get("jsonld")),
        "site_name": str(placement.get("site_name") or ""),
        "post_id": int(placement.get("post_id") or 0),
    }


def placed_at_of(suggestion: Any) -> datetime | None:
    placement = suggestion.get("placement") if isinstance(suggestion, dict) else None
    raw = placement.get("placed_at") if isinstance(placement, dict) else None
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def placement_state(db: Session, page: LaunchScanPage, user_id: str, *, nothing_missing: bool = False) -> PlacementState:
    """Mag er geplaatst worden (alleen database, geen HTTP)? Plus de bestaande plaatsing."""
    suggestion = page.schema_suggestion if isinstance(page.schema_suggestion, dict) else None
    view = placement_view(suggestion)
    if nothing_missing:
        return PlacementState(False, NOTHING_MISSING, [], view)
    review_status, reviewed_at = review_view(suggestion)
    placement = suggestion.get("placement") if suggestion and isinstance(suggestion.get("placement"), dict) else None
    _, site_problem = _site_for_page(db, page, user_id, placement)
    reason, replaces = placement_check(suggestion, page.page_type, site_problem=site_problem)
    return PlacementState(not reason, reason, replaces if not reason else [], view,
                          review_status=review_status, reviewed_at=reviewed_at)


# --- beoordeling ----------------------------------------------------------------------------

def review_view(suggestion: Any) -> tuple[str, datetime | None]:
    """(status, tijdstip) van de beoordeling van het huidige voorstel.

    Een goed- of afkeuring geldt alleen voor de JSON-LD waarop ze is gegeven (`jsonld_hash`, zoals
    `placement.current`); na opnieuw genereren met andere JSON-LD is de status weer "pending".
    """
    review = suggestion.get("review") if isinstance(suggestion, dict) else None
    if not isinstance(review, dict) or not suggestion.get("jsonld"):
        return REVIEW_PENDING, None
    status = review.get("status")
    if status not in (REVIEW_APPROVED, REVIEW_REJECTED) or review.get("jsonld_hash") != jsonld_hash(suggestion["jsonld"]):
        return REVIEW_PENDING, None
    raw = review.get("reviewed_at")
    try:
        reviewed_at = datetime.fromisoformat(str(raw)) if raw else None
    except ValueError:
        reviewed_at = None
    if reviewed_at is not None and reviewed_at.tzinfo is None:
        reviewed_at = reviewed_at.replace(tzinfo=timezone.utc)
    return str(status), reviewed_at


def review_schema(db: Session, page: LaunchScanPage, *, status: str, user_id: str) -> None:
    """Legt de beoordeling van het huidige voorstel vast (alleen database, geen HTTP of modelaanroep).

    Gooit `ValueError` bij een onbekende status, `RankMathPlacementBlocked` als goedkeuren niet
    mag (plaatsen kan niet; de tekst is de reden) en `SchemaMarkupPageGoneError` als de pagina
    intussen is verwijderd. Afkeuren en terugzetten naar "pending" mag altijd.
    """
    if status not in REVIEW_STATUSES:
        raise ValueError(status)
    suggestion = page.schema_suggestion if isinstance(page.schema_suggestion, dict) else None
    if not suggestion or not suggestion.get("jsonld"):
        raise RankMathPlacementBlocked(NO_SUGGESTION)
    if status == REVIEW_APPROVED:
        state = placement_state(db, page, user_id)
        if not state.can_place:
            raise RankMathPlacementBlocked(state.reason)
    page.schema_suggestion = {**suggestion, "review": {
        "status": status,
        "jsonld_hash": jsonld_hash(suggestion["jsonld"]),
        "user_id": user_id,
        "reviewed_at": _now().isoformat(),
    }}
    try:
        db.commit()
    except StaleDataError as exc:
        db.rollback()
        raise schema_markup.SchemaMarkupPageGoneError(page.id) from exc


# --- omzetting ------------------------------------------------------------------------------

def to_rankmath_schemas(jsonld: Any) -> list[tuple[str, str, dict[str, Any]]]:
    """(sleutel, titel, schema) per top-level item uit `@graph`.

    Titel = het (eerste) @type; de sleutel koppelt bij opnieuw plaatsen een item aan zijn eerdere
    plaatsing (`Service`, bij hetzelfde type nogmaals `Service 2`). `@id`'s blijven staan: met
    `metadata.type == "custom"` neemt Rank Math ze over, en verwijzingen naar bestaande entiteiten ook.
    """
    if isinstance(jsonld, dict) and isinstance(jsonld.get("@graph"), list):
        nodes = jsonld["@graph"]
    elif isinstance(jsonld, list):
        nodes = jsonld
    else:
        nodes = [jsonld]
    out: list[tuple[str, str, dict[str, Any]]] = []
    seen: dict[str, int] = {}
    for node in nodes:
        types = types_of(node)
        if not types:
            continue
        title = types[0]
        seen[title] = seen.get(title, 0) + 1
        key = title if seen[title] == 1 else f"{title} {seen[title]}"
        schema = {k: v for k, v in node.items() if k not in {"@context", "metadata"}}
        schema["metadata"] = {"title": title, "type": "custom", "isPrimary": False}
        out.append((key, title, schema))
    return out


# --- WordPress ------------------------------------------------------------------------------

def _call(wp: _WordPress, method: str, route: str, *, action: str, payload: dict[str, Any] | None = None) -> Any:
    headers = dict(wp.headers)
    if payload is not None:
        headers["Content-Type"] = "application/json"
    try:
        response = _request_with_auth_redirect(method, _wordpress_rest_url(wp.base_url, route),
                                               headers=headers, json_payload=payload)
    except WordPressServiceError as exc:
        raise RankMathSchemaError(f"{action}: {exc}") from exc
    if response.status_code in {401, 403}:
        raise RankMathSchemaError(
            f"{action}: WordPress weigert de toegang ({_extract_error_message(response)}). "
            "Controleer de koppeling bij Instellingen > WordPress."
        )
    if response.status_code >= 400:
        raise RankMathSchemaError(
            f"{action}: WordPress gaf een fout (status {response.status_code}): {_extract_error_message(response)}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise RankMathSchemaError(f"{action}: WordPress gaf geen geldig antwoord (geen JSON).") from exc


def _comparable(url: str) -> str:
    key = url_key(url)
    host, sep, rest = key.partition("/")
    host = host[4:] if host.startswith("www.") else host
    return unquote(host + sep + rest).lower()


def _match_item(items: Any, page_url: str) -> dict[str, Any] | None:
    """Het item uit een WordPress-lijst waarvan `link` deze pagina is (met een geldig ID)."""
    target = _comparable(page_url)
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("id") and _comparable(str(item.get("link") or "")) == target:
            try:
                int(item["id"])
            except (TypeError, ValueError):
                continue
            return item
    return None


def _match_id(items: Any, page_url: str) -> int | None:
    item = _match_item(items, page_url)
    return int(item["id"]) if item is not None else None


def _extra_routes(wp: _WordPress) -> list[str]:
    try:
        data = _call(wp, "GET", "wp/v2/types", action="Berichttypes opvragen mislukt")
    except RankMathSchemaError as exc:
        logger.info("Berichttypes van %s niet op te vragen: %s", wp.base_url, exc)
        return []
    routes: list[str] = []
    for slug, info in (data.items() if isinstance(data, dict) else []):
        if slug in _SKIP_POST_TYPES or str(slug).startswith("wp_") or not isinstance(info, dict):
            continue
        rest_base = str(info.get("rest_base") or "").strip("/")
        namespace = str(info.get("rest_namespace") or "wp/v2").strip("/")
        if rest_base:
            routes.append(f"{namespace}/{rest_base}")
    return routes[:MAX_EXTRA_POST_TYPES]


# Relaties die `find_post(..., embed=True)` meeneemt (auteur en uitgelichte afbeelding).
_EMBED = "author,wp:featuredmedia"


def find_post(wp: _WordPress, page_url: str, *, embed: bool = False) -> dict[str, Any]:
    """Het WordPress-item van de pagina: homepage via `page_on_front`, anders op slug en `link`.

    Zonder `embed` alleen `id` en `link`; met `embed` het volledige item inclusief `_embedded`
    (auteur, uitgelichte afbeelding). Gooit `RankMathPlacementBlocked` als de pagina niet als
    bericht of pagina te vinden is en `RankMathSchemaError` bij een fout van de klantsite.
    """
    action = "Pagina opzoeken in WordPress mislukt"
    if _comparable(page_url) == _comparable(wp.base_url):
        settings = _call(wp, "GET", "wp/v2/settings", action=action)
        front = settings.get("page_on_front") if isinstance(settings, dict) else None
        try:
            front_id = int(front or 0)
        except (TypeError, ValueError):
            front_id = 0
        if not front_id:
            raise RankMathPlacementBlocked(
                "De homepage is geen vaste WordPress-pagina (Instellingen > Lezen), dus Rank Math kan er "
                "geen schema bij opslaan; kopieer het blok en plaats het zelf."
            )
        if not embed:
            return {"id": front_id}
        item = _call(wp, "GET", f"wp/v2/pages/{front_id}?{urlencode({'_embed': _EMBED})}", action=action)
        return item if isinstance(item, dict) else {"id": front_id}

    segments = [s for s in urlparse(page_url).path.split("/") if s]
    slug = unquote(segments[-1]) if segments else ""
    if slug:
        params: dict[str, Any] = {"slug": slug, "per_page": 20}
        params.update({"_embed": _EMBED} if embed else {"_fields": "id,link"})
        query = urlencode(params)
        for route in ("wp/v2/pages", "wp/v2/posts"):
            found = _match_item(_call(wp, "GET", f"{route}?{query}", action=action), page_url)
            if found:
                return found
        for route in _extra_routes(wp):
            try:
                found = _match_item(_call(wp, "GET", f"{route}?{query}", action=action), page_url)
            except RankMathSchemaError as exc:  # niet elk berichttype is openbaar op te vragen
                logger.info("Opzoeken in %s mislukt: %s", route, exc)
                continue
            if found:
                return found
    raise RankMathPlacementBlocked(
        "De pagina is niet als bericht of pagina op de gekoppelde WordPress-site gevonden; "
        "kopieer het blok en plaats het zelf."
    )


def resolve_post_id(wp: _WordPress, page_url: str) -> int:
    """WordPress-ID van de pagina (zie `find_post`).

    Gooit `RankMathPlacementBlocked` als de pagina niet als bericht of pagina te vinden is.
    """
    return int(find_post(wp, page_url)["id"])


def _gmt(item: dict[str, Any], key: str) -> str:
    """ISO-datum uit WordPress: `<key>_gmt` met +00:00, anders de lokale tijd zoals WordPress hem geeft."""
    gmt = str(item.get(f"{key}_gmt") or "").strip()
    if gmt and not gmt.startswith("0000"):
        return gmt if gmt.endswith(("Z", "+00:00")) else f"{gmt}+00:00"
    local = str(item.get(key) or "").strip()
    return "" if local.startswith("0000") else local


def connect_quietly(site: WordPressSite | None) -> _WordPress | None:
    """Verbinding met de gekoppelde site, of None (geen site of onbruikbare koppeling)."""
    if site is None:
        return None
    try:
        return _connect(site)
    except Exception as exc:  # noqa: BLE001 - alleen voor extra feiten; nooit fataal
        logger.info("WordPress-koppeling %s niet bruikbaar voor publicatiegegevens: %s", site.id, exc)
        return None


def wordpress_post_facts(wp: _WordPress, page_url: str) -> list[tuple[str, str]]:
    """Publicatiegegevens van de pagina uit WordPress: (label, waarde), alleen wat gevonden is.

    Faalt nooit: bij elke fout (klantsite, pagina niet gevonden, onverwacht antwoord) een lege lijst.
    """
    try:
        item = find_post(wp, page_url, embed=True)
        facts: list[tuple[str, str]] = []
        for key, label in (("date", "Publicatiedatum"), ("modified", "Wijzigingsdatum")):
            value = _gmt(item, key)
            if value:
                facts.append((label, value))
        embedded = item.get("_embedded") if isinstance(item.get("_embedded"), dict) else {}
        authors = embedded.get("author") if isinstance(embedded.get("author"), list) else []
        author = next((a for a in authors if isinstance(a, dict) and str(a.get("name") or "").strip()), None)
        if author is not None:
            name = str(author["name"]).strip()
            url = str(author.get("link") or author.get("url") or "").strip()
            facts.append(("Auteur", f"{name} ({url})" if url else name))
        media = embedded.get("wp:featuredmedia") if isinstance(embedded.get("wp:featuredmedia"), list) else []
        image = next((m for m in media if isinstance(m, dict) and str(m.get("source_url") or "").strip()), None)
        if image is not None:
            details = image.get("media_details") if isinstance(image.get("media_details"), dict) else {}
            size = (f" ({details['width']}x{details['height']})"
                    if details.get("width") and details.get("height") else "")
            facts.append(("Uitgelichte afbeelding", f"{str(image['source_url']).strip()}{size}"))
        return facts
    except Exception as exc:  # noqa: BLE001 - genereren mag hier nooit op mislukken
        logger.info("Publicatiegegevens uit WordPress voor %s niet op te halen: %s", page_url, exc)
        return []


def _update_schemas(wp: _WordPress, post_id: int, schemas: dict[str, Any]) -> Any:
    return _call(wp, "POST", "rankmath/v1/updateSchemas", action="Schema plaatsen in Rank Math mislukt",
                 payload={"objectType": OBJECT_TYPE, "objectID": post_id, "schemas": schemas})


def _delete_schemas(wp: _WordPress, post_id: int, meta_ids: list[int], *, had_graph: bool) -> bool:
    """Verwijdert de schema's; herstelt de graph als er niets overblijft en die er eerst was.

    Geeft True terug als `rank_math_rich_snippet` is hersteld.
    """
    if not meta_ids:
        return False
    result = _call(
        wp, "POST", "rankmath/v1/updateMeta", action="Schema verwijderen uit Rank Math mislukt",
        payload={"objectType": OBJECT_TYPE, "objectID": post_id,
                 "meta": {f"rank_math_delete_schema-{meta_id}": "" for meta_id in meta_ids}},
    )
    remaining = result.get("schemas") if isinstance(result, dict) else None
    if remaining is None:
        logger.warning("Onverwacht antwoord van updateMeta voor post %s: %r", post_id, result)
        return False
    if remaining or not had_graph:
        return False
    # Verwijderen zet rank_math_rich_snippet op "off"; zonder schema's toont de pagina dan alleen nog
    # het kruimelpad. Leegmaken brengt de graph en het standaardschema terug.
    _call(wp, "POST", "rankmath/v1/updateMeta", action="Standaardschema van Rank Math herstellen mislukt",
          payload={"objectType": OBJECT_TYPE, "objectID": post_id, "meta": {"rank_math_rich_snippet": ""}})
    return True


def _with_cache_buster(url: str) -> str:
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != CACHE_BUSTER]
    query.append((CACHE_BUSTER, uuid.uuid4().hex[:10]))
    return parsed._replace(query=urlencode(query)).geturl()


def _verify(url: str, placed_types: list[str]) -> bool:
    """Staan alle geplaatste types in de JSON-LD van de pagina? (FAQPage zit dan in de WebPage.)"""
    try:
        html, _ = schema_markup.fetch_page_html(_with_cache_buster(url))
    except schema_markup.SchemaMarkupError as exc:
        logger.info("Controle na plaatsen van %s mislukt: %s", url, exc)
        return False
    blocks = schema_markup.extract_jsonld_blocks(html)
    present = all_types(schema_markup._parsed_blocks(blocks))
    return all(t in present for t in placed_types)


# --- plaatsen en verwijderen ----------------------------------------------------------------

def place_schema(db: Session, page: LaunchScanPage, *, user_id: str, require_approved: bool = False) -> None:
    """Zet het opgeslagen voorstel in Rank Math (of werkt een eerdere plaatsing bij).

    Gooit `RankMathPlacementBlocked` (niet toegestaan, niets geschreven), `RankMathSchemaError`
    (fout van de klantsite), `SchemaMarkupError` (pagina niet op te halen) en
    `SchemaMarkupPageGoneError` (pagina tijdens het plaatsen verwijderd).

    Met `require_approved` (bulkroute) wordt alleen geplaatst als precies dit voorstel is
    goedgekeurd; dat wordt gecontroleerd vóór elke HTTP-aanroep, en daarna wordt alleen deze
    (goedgekeurde) JSON-LD gebruikt.

    De sessie wordt tijdens de HTTP-aanroepen gesloten, zoals bij het genereren.
    """
    suggestion = page.schema_suggestion if isinstance(page.schema_suggestion, dict) else None
    if require_approved and review_view(suggestion)[0] != REVIEW_APPROVED:
        raise RankMathPlacementBlocked(NOT_APPROVED)
    # Eerst alleen voorstel en plaatshouders; Rank Math en het standaardschema hieronder op de verse pagina.
    reason, _ = placement_check(
        {k: v for k, v in suggestion.items() if k not in _RANK_MATH_KEYS} if suggestion else None, page.page_type
    )
    if reason:
        raise RankMathPlacementBlocked(reason)
    assert suggestion is not None
    placement = suggestion.get("placement") if isinstance(suggestion.get("placement"), dict) else None
    site, site_problem = _site_for_page(db, page, user_id, placement)
    if site is None:
        raise RankMathPlacementBlocked(site_problem)
    wp = _connect(site)
    page_id, page_type = page.id, page.page_type
    fetch_url = page.final_url or page.url
    jsonld = suggestion["jsonld"]
    db.close()

    # Opnieuw beslissen op de vers opgehaalde pagina.
    html, final_url = schema_markup.fetch_page_html(fetch_url)
    facts = schema_markup.rank_math_facts(html, placement)
    default_types = list(placement.get("default_types") or []) if placement else facts.default_types
    had_graph = bool(placement.get("had_graph")) if placement else facts.had_graph
    fresh = {**suggestion, "rank_math_detected": facts.detected, "default_types": default_types,
             "had_graph": had_graph, "kept_types": sorted(facts.kept_types)}
    reason, _ = placement_check(fresh, page_type)
    if reason:
        raise RankMathPlacementBlocked(reason)
    schemas = to_rankmath_schemas(jsonld)
    if not schemas:
        raise RankMathPlacementBlocked("Het voorstel bevat geen schema om te plaatsen.")

    post_id = int(placement["post_id"]) if placement else resolve_post_id(wp, final_url)

    # Eerder geplaatste items op sleutel; wat na het koppelen overblijft is vervallen.
    stale = {str(i["key"]): i for i in (placement or {}).get("items") or [] if isinstance(i, dict) and "key" in i}
    payload: dict[str, Any] = {}
    planned: list[tuple[str, str, dict[str, Any], int | None, str | None]] = []
    for key, title, schema in schemas:
        old = stale.pop(key, None)
        if old is not None:
            payload[f"schema-{old['meta_id']}"] = schema
            planned.append((key, title, schema, int(old["meta_id"]), None))
        else:
            temp = f"new-{uuid.uuid4().hex[:12]}"
            payload[temp] = schema
            planned.append((key, title, schema, None, temp))
    result = _update_schemas(wp, post_id, payload)
    new_ids = result if isinstance(result, dict) else {}

    items: list[dict[str, Any]] = []
    missing: list[str] = []
    for key, title, schema, meta_id, temp in planned:
        if temp is not None:
            try:
                meta_id = int(new_ids.get(temp))
            except (TypeError, ValueError):
                missing.append(title)
                continue
        node_id = schema.get("@id") if isinstance(schema.get("@id"), str) else None
        items.append({"key": key, "type": title, "meta_id": meta_id, "node_id": node_id})

    def placement_with(entries: list[dict[str, Any]], verified: bool) -> dict[str, Any]:
        return {
            "site_id": wp.site_id,
            "site_name": wp.name,
            "base_url": wp.base_url,
            "object_type": OBJECT_TYPE,
            "post_id": post_id,
            "page_url": final_url,
            "items": entries,
            "placed_at": _now().isoformat(),
            "verified": verified,
            "jsonld_hash": jsonld_hash(jsonld),
            # Nodig voor het herstel bij verwijderen en voor de regels bij opnieuw plaatsen.
            "had_graph": had_graph,
            "default_types": default_types,
        }

    # Wat al op de site staat altijd vastleggen, zodat opnieuw plaatsen of verwijderen geen
    # dubbele of verweesde schema's achterlaat.
    if missing:
        _save(db, page_id, placement_with(items + list(stale.values()), False), facts=fresh, placed_jsonld=jsonld)
        raise RankMathSchemaError(
            f"Schema plaatsen in Rank Math mislukt: Rank Math gaf geen ID terug voor {', '.join(missing)}."
        )
    # Types die niet meer in het voorstel staan.
    try:
        _delete_schemas(wp, post_id, [int(i["meta_id"]) for i in stale.values()], had_graph=had_graph)
    except RankMathSchemaError:
        _save(db, page_id, placement_with(items + list(stale.values()), False), facts=fresh, placed_jsonld=jsonld)
        raise

    verified = _verify(final_url, [item["type"] for item in items])
    _save(db, page_id, placement_with(items, verified), facts=fresh, placed_jsonld=jsonld)


def remove_schema(db: Session, page: LaunchScanPage, *, user_id: str) -> None:
    """Haalt de geplaatste schema's weg uit Rank Math en vergeet de plaatsing.

    Gooit `RankMathPlacementNotFound` als er geen plaatsing is, `RankMathPlacementBlocked` als de
    koppeling niet (meer) bruikbaar is en `RankMathSchemaError` bij een fout van de klantsite.
    """
    suggestion = page.schema_suggestion if isinstance(page.schema_suggestion, dict) else None
    placement = suggestion.get("placement") if suggestion else None
    if not isinstance(placement, dict):
        raise RankMathPlacementNotFound(page.id)
    site, site_problem = _site_for_page(db, page, user_id, placement)
    if site is None:
        raise RankMathPlacementBlocked(site_problem)
    wp = _connect(site)
    page_id = page.id
    db.close()

    meta_ids = [int(i["meta_id"]) for i in placement.get("items") or [] if isinstance(i, dict) and "meta_id" in i]
    _delete_schemas(wp, int(placement["post_id"]), meta_ids, had_graph=bool(placement.get("had_graph")))
    _save(db, page_id, None)


def _save(db: Session, page_id: str, placement: dict[str, Any] | None, *,
          facts: dict[str, Any] | None = None, placed_jsonld: Any = None) -> None:
    stored = db.get(LaunchScanPage, page_id)
    if stored is None:
        logger.error("Pagina %s verdwenen na wijziging in Rank Math; plaatsing niet opgeslagen: %r", page_id, placement)
        raise schema_markup.SchemaMarkupPageGoneError(page_id)
    suggestion = dict(stored.schema_suggestion) if isinstance(stored.schema_suggestion, dict) else {}
    if placement is None:
        suggestion.pop("placement", None)
    else:
        suggestion["placement"] = placement
        # De vers bepaalde Rank Math-gegevens horen bij dit voorstel, tenzij het intussen opnieuw is gemaakt.
        if facts is not None and jsonld_hash(suggestion.get("jsonld")) == jsonld_hash(placed_jsonld):
            for key in _RANK_MATH_KEYS:
                suggestion[key] = facts[key]
    stored.schema_suggestion = suggestion
    try:
        db.commit()
    except StaleDataError as exc:
        db.rollback()
        logger.error("Pagina %s verdwenen na wijziging in Rank Math; plaatsing niet opgeslagen: %r", page_id, placement)
        raise schema_markup.SchemaMarkupPageGoneError(page_id) from exc
