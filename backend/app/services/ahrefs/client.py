"""Ahrefs API v3-client (sync httpx), gedeeld door features.

Elke functie geeft naast de data ook het aantal verbruikte API-units terug
(header `x-api-units-cost-total-actual`), zodat een scan zijn verbruik kan tonen.
Fouten worden vertaald naar `AhrefsServiceError` met een `code`.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import httpx

from app.core.config import settings

API_URL = "https://api.ahrefs.com/v3"
MAX_ATTEMPTS = 3
MAX_RETRY_WAIT_SECONDS = 15.0

# Kolommen per rapport. De unit-kosten per rij staan in de Ahrefs-reference:
# top-pages 24 (sum_traffic en top_keyword_volume kosten 10), pages-by-backlinks 8
# (refdomains_target kost 5), broken-backlinks 5, organic-keywords 24 (gemeten op het
# testdomein ahrefs.com met precies deze zes velden; elk extra veld kost meer units).
TOP_PAGES_FIELDS = (
    "url", "sum_traffic", "keywords", "top_keyword",
    "top_keyword_best_position", "top_keyword_volume",
)
BACKLINK_PAGES_FIELDS = ("url_to", "refdomains_target", "dofollow_to_target", "http_code_target")
BROKEN_BACKLINKS_FIELDS = ("url_from", "url_to", "domain_rating_source", "anchor", "http_code_target")
ORGANIC_KEYWORDS_FIELDS = (
    "keyword", "best_position", "best_position_diff", "best_position_url",
    "volume", "keyword_difficulty",
)
DOMAIN_FIELDS = (
    "domain_rating", "refdomains", "backlinks",
    "org_traffic", "org_keywords", "org_keywords_1_3", "org_cost",
)

# Concurrentieanalyse (gemeten 23-11-2026, "seo bureau", land nl). Een gewoon veld kost
# 1 unit per rij; de velden met een eigen prijs staan in de reference.
#
# serp-overview: rijen onder `positions`, `type` is echt een lijst (bv. ["organic"]).
#   `position` is de plek van het SERP-blok, niet de organische rang: features tellen mee
#   en sitelinks delen de positie van hun resultaat. top_positions=10 gaf 21 rijen
#   (posities 1-10) met maar 8 organische resultaten: 1 organic + 2 sitelink, 2 ai_overview
#   + 6 ai_overview_sitelink, 3 vier keer question, 4-10 organic. Haal dus ruimer op
#   (`SERP_EXTRA_POSITIONS`) en gebruik `organic_rows()`. Kosten: 15 units per rij
#   (refdomains 5 + tien velden van 1), dus 315 voor deze aanroep; feature-rijen tellen mee.
#   `traffic` (10 units) laten we weg, we tonen het niet.
#   - ai_overview: één rij zonder url/title.
#   - ai_overview_sitelink: url + title gevuld, metrieken leeg. Dit zijn de bronnen die
#     Google in de AI Overview citeert (`ai_overview_sources()`).
#   - question ("Mensen vragen ook"): vraagtekst in `title`, url leeg (`people_also_ask()`).
#   - Alleen organic-rijen hebben page_type, DR, UR, refdomains, backlinks en keywords.
#     `page_type` is een kommagescheiden string, bv. "/Landing_Page,/Landing_Page/Service_Page".
# keywords-explorer/overview: rijen onder `keywords`, niet in invoervolgorde. 31 units per
#   zoekwoord (volume, difficulty en intents 10, keyword 1); 62 voor twee zoekwoorden.
#   Bundel zoekwoorden in één aanroep (de API rekent vermoedelijk minimaal 50 per request).
#   `intents` is een object met booleans informational/navigational/commercial/
#   transactional/branded/local.
# batch-analysis met mode exact: rijen onder `targets` met `index` (volgorde van de invoer)
#   en `url` zonder protocol ("ahrefs.com/blog/"); koppel dus op `index`. Nominaal 50 units
#   voor twee URL's (minimum per request; per rij 1+1+1+1+5 = 9), op ahrefs.com 0.
SERP_FIELDS = (
    "position", "url", "title", "type", "page_type", "domain_rating", "url_rating",
    "refdomains", "backlinks", "keywords", "update_date",
)
SERP_EXTRA_POSITIONS = 5
KEYWORDS_OVERVIEW_FIELDS = ("keyword", "volume", "difficulty", "intents")
URL_METRICS_FIELDS = ("index", "url", "domain_rating", "url_rating", "refdomains")
BATCH_MAX_TARGETS = 100


class AhrefsServiceError(Exception):
    def __init__(self, message: str, code: str = "ahrefs_error"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AhrefsResult:
    """Antwoord van één request: `rows` voor lijsten, `data` voor één object."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    units: int = 0
    cached: bool = False


def is_configured() -> bool:
    return bool(settings.ahrefs_api_key.strip())


def _retry_wait(response: httpx.Response | None, attempt: int) -> float:
    header = response.headers.get("Retry-After") if response is not None else None
    try:
        wait = float(header) if header else float(2 ** attempt)
    except ValueError:
        wait = float(2 ** attempt)
    return max(0.0, min(wait, MAX_RETRY_WAIT_SECONDS))


def _units(response: httpx.Response) -> int:
    for header in ("x-api-units-cost-total-actual", "x-api-units-cost-total"):
        try:
            return max(0, int(float(response.headers.get(header, ""))))
        except ValueError:
            continue
    return 0


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(payload, dict) and payload.get("error"):
        return str(payload["error"])[:300]
    return f"HTTP {response.status_code}"


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
) -> tuple[dict[str, Any], httpx.Response]:
    """Voer één request uit en geef de JSON-payload plus de response terug.

    `client` is alleen bedoeld voor tests (httpx.MockTransport).
    """
    token = settings.ahrefs_api_key.strip()
    if not token:
        raise AhrefsServiceError(
            "Ahrefs is niet gekoppeld: AHREFS_API_KEY ontbreekt in de backend-configuratie.",
            code="not_configured",
        )
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    owns_client = client is None
    http = client or httpx.Client(timeout=settings.ahrefs_request_timeout_seconds)
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            last_attempt = attempt == MAX_ATTEMPTS
            try:
                response = http.request(
                    method, f"{API_URL}{path}", headers=headers, params=params, json=json
                )
            except httpx.TimeoutException as exc:
                raise AhrefsServiceError("Timeout bij verbinden met Ahrefs.", code="timeout") from exc
            except httpx.HTTPError as exc:
                raise AhrefsServiceError(
                    "Kon geen verbinding maken met Ahrefs.", code="connection_error"
                ) from exc

            if response.status_code == 401:
                raise AhrefsServiceError("Ahrefs weigert de API-key (ongeldig of verlopen).", code="unauthorized")
            if response.status_code == 403:
                # Onvoldoende units, geen API-toegang op dit abonnement of meer rijen dan toegestaan.
                raise AhrefsServiceError(
                    f"Ahrefs staat deze aanvraag niet toe: {_error_message(response)}", code="forbidden"
                )
            if response.status_code == 429 or response.status_code >= 500:
                if last_attempt:
                    code = "rate_limited" if response.status_code == 429 else "ahrefs_error"
                    raise AhrefsServiceError(
                        f"Ahrefs is tijdelijk niet beschikbaar (HTTP {response.status_code}).", code=code
                    )
                time.sleep(_retry_wait(response, attempt))
                continue
            if response.status_code >= 400:
                raise AhrefsServiceError(f"Ahrefs-fout: {_error_message(response)}", code="ahrefs_error")

            try:
                payload = response.json()
            except ValueError as exc:
                raise AhrefsServiceError("Onleesbaar antwoord van Ahrefs.", code="ahrefs_error") from exc
            if not isinstance(payload, dict):
                raise AhrefsServiceError("Onleesbaar antwoord van Ahrefs.", code="ahrefs_error")
            return payload, response
        raise AhrefsServiceError("Ahrefs-request mislukt.", code="ahrefs_error")
    finally:
        if owns_client:
            http.close()


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [row for row in (payload.get(key) or []) if isinstance(row, dict)]


def _result(payload: dict[str, Any], response: httpx.Response, key: str) -> AhrefsResult:
    return AhrefsResult(
        rows=_rows(payload, key),
        units=_units(response),
        cached=response.headers.get("x-api-cache") == "hit",
    )


def _site_explorer(
    report: str, key: str, params: dict[str, Any], client: httpx.Client | None
) -> AhrefsResult:
    payload, response = _request("GET", f"/site-explorer/{report}", params=params, client=client)
    return _result(payload, response, key)


def domain_overview(
    target: str, *, country: str | None = None, client: httpx.Client | None = None
) -> AhrefsResult:
    """Kerncijfers van het domein: DR, verwijzende domeinen, organisch verkeer."""
    body: dict[str, Any] = {
        "select": list(DOMAIN_FIELDS),
        "targets": [{"url": target, "mode": "subdomains", "protocol": "both"}],
    }
    if country:
        body["country"] = country
    payload, response = _request("POST", "/batch-analysis/batch-analysis", json=body, client=client)
    rows = _rows(payload, "targets")
    return AhrefsResult(
        rows=rows,
        data={k: rows[0].get(k) for k in DOMAIN_FIELDS} if rows else {},
        units=_units(response),
        cached=response.headers.get("x-api-cache") == "hit",
    )


def top_pages(
    target: str,
    *,
    country: str | None = None,
    limit: int = 200,
    on_date: date | None = None,
    client: httpx.Client | None = None,
) -> AhrefsResult:
    """Pagina's met het meeste organische verkeer, met hun topzoekwoord."""
    params: dict[str, Any] = {
        "target": target,
        "mode": "subdomains",
        "protocol": "both",
        "date": (on_date or date.today()).isoformat(),
        "select": ",".join(TOP_PAGES_FIELDS),
        "order_by": "sum_traffic:desc",
        "limit": limit,
    }
    if country:
        params["country"] = country
    return _site_explorer("top-pages", "pages", params, client)


def organic_keywords(
    target: str,
    *,
    country: str | None = None,
    position_min: int = 4,
    position_max: int = 20,
    limit: int = 50,
    compare_days: int = 30,
    on_date: date | None = None,
    client: httpx.Client | None = None,
) -> AhrefsResult:
    """Zoekwoorden waarop het domein rankt binnen `position_min`–`position_max`, hoogste volume eerst.

    Met `date_compared` (`compare_days` terug) komt `best_position_diff` mee: huidige positie
    min de positie toen, dus negatief bij een stijging en `None` als het zoekwoord toen niet rankte.
    """
    today = on_date or date.today()
    where = {
        "and": [
            {"field": "best_position", "is": ["gte", position_min]},
            {"field": "best_position", "is": ["lte", position_max]},
        ]
    }
    params: dict[str, Any] = {
        "target": target,
        "mode": "subdomains",
        "protocol": "both",
        "date": today.isoformat(),
        "date_compared": (today - timedelta(days=compare_days)).isoformat(),
        "select": ",".join(ORGANIC_KEYWORDS_FIELDS),
        "where": json.dumps(where, separators=(",", ":")),
        "order_by": "volume:desc",
        "limit": limit,
    }
    if country:
        params["country"] = country
    return _site_explorer("organic-keywords", "keywords", params, client)


def pages_by_backlinks(
    target: str, *, limit: int = 200, client: httpx.Client | None = None
) -> AhrefsResult:
    """Pagina's met de meeste verwijzende domeinen (alleen live backlinks)."""
    params = {
        "target": target,
        "mode": "subdomains",
        "protocol": "both",
        "history": "live",
        "select": ",".join(BACKLINK_PAGES_FIELDS),
        "order_by": "refdomains_target:desc",
        "limit": limit,
    }
    return _site_explorer("pages-by-backlinks", "pages", params, client)


def broken_backlinks(
    target: str, *, limit: int = 100, client: httpx.Client | None = None
) -> AhrefsResult:
    """Backlinks die volgens Ahrefs op een kapotte pagina uitkomen, sterkste domeinen eerst."""
    params = {
        "target": target,
        "mode": "subdomains",
        "protocol": "both",
        "aggregation": "1_per_domain",
        "select": ",".join(BROKEN_BACKLINKS_FIELDS),
        "order_by": "domain_rating_source:desc",
        "limit": limit,
    }
    return _site_explorer("broken-backlinks", "backlinks", params, client)


def serp_overview(
    keyword: str,
    *,
    country: str | None = None,
    top_positions: int = 10,
    client: httpx.Client | None = None,
) -> AhrefsResult:
    """De laatst bekende Google-SERP van een zoekwoord, inclusief SERP-features.

    `top_positions` telt SERP-blokken, geen organische resultaten (zie het commentaar
    bovenin). Voor de top N organische pagina's: vraag `N + SERP_EXTRA_POSITIONS` op en
    filter met `organic_rows()`.
    """
    params: dict[str, Any] = {
        "select": ",".join(SERP_FIELDS),
        "keyword": keyword.strip(),
        "country": country or settings.ahrefs_country,
        "top_positions": top_positions,
    }
    payload, response = _request("GET", "/serp-overview/serp-overview", params=params, client=client)
    return _result(payload, response, "positions")


def keywords_overview(
    keywords: list[str], *, country: str | None = None, client: httpx.Client | None = None
) -> AhrefsResult:
    """Volume, moeilijkheid (`difficulty`) en zoekintentie voor een lijst zoekwoorden.

    Eén aanroep voor alle zoekwoorden; de API scheidt op komma's, dus zoekwoorden met een
    komma vallen af. De rijen komen niet in de volgorde van de invoer terug.
    """
    cleaned = list(dict.fromkeys(k.strip() for k in keywords if k and k.strip() and "," not in k))
    if not cleaned:
        return AhrefsResult()
    params: dict[str, Any] = {
        "select": ",".join(KEYWORDS_OVERVIEW_FIELDS),
        "country": country or settings.ahrefs_country,
        "keywords": ",".join(cleaned),
    }
    payload, response = _request("GET", "/keywords-explorer/overview", params=params, client=client)
    return _result(payload, response, "keywords")


def url_metrics(urls: list[str], *, client: httpx.Client | None = None) -> AhrefsResult:
    """DR, UR en verwijzende domeinen van losse pagina's (batch-analysis, `mode: exact`).

    Per request maximaal `BATCH_MAX_TARGETS` URL's; meer wordt in delen opgehaald. Ahrefs
    geeft `url` zonder protocol terug, dus elke rij krijgt `target` met de URL zoals
    opgegeven (gekoppeld via `index`).
    """
    targets = [u.strip() for u in urls if u and u.strip()]
    rows: list[dict[str, Any]] = []
    units = 0
    cached = bool(targets)
    for start in range(0, len(targets), BATCH_MAX_TARGETS):
        chunk = targets[start:start + BATCH_MAX_TARGETS]
        body = {
            "select": list(URL_METRICS_FIELDS),
            "targets": [{"url": url, "mode": "exact", "protocol": "both"} for url in chunk],
        }
        payload, response = _request("POST", "/batch-analysis/batch-analysis", json=body, client=client)
        for row in _rows(payload, "targets"):
            index = row.get("index")
            target = chunk[index] if isinstance(index, int) and 0 <= index < len(chunk) else None
            rows.append({**row, "target": target})
        units += _units(response)
        cached = cached and response.headers.get("x-api-cache") == "hit"
    return AhrefsResult(rows=rows, units=units, cached=cached)


def _types(row: dict[str, Any]) -> list[str]:
    value = row.get("type")
    if isinstance(value, str):
        return [value]
    return [t for t in (value or []) if isinstance(t, str)]


def _position(row: dict[str, Any]) -> float:
    value = row.get("position")
    return float(value) if isinstance(value, (int, float)) else float("inf")


def organic_rows(result: AhrefsResult, top_n: int) -> list[dict[str, Any]]:
    """De top N organische resultaten uit `serp_overview`, op positie en zonder dubbele URL's.

    Elke rij krijgt `organic_position` (1..N): de rang onder de organische resultaten.
    `position` blijft de SERP-positie van Ahrefs, waarin features meetellen.
    """
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for row in sorted(result.rows, key=_position):
        url = (row.get("url") or "").strip()
        if "organic" not in _types(row) or not url or url in seen:
            continue
        seen.add(url)
        rows.append({**row, "organic_position": len(rows) + 1})
        if len(rows) >= top_n:
            break
    return rows


def serp_features(result: AhrefsResult) -> list[str]:
    """Gesorteerde lijst van de feature-types in de SERP, alles behalve `organic`."""
    return sorted({t for row in result.rows for t in _types(row)} - {"organic"})


def ai_overview_sources(result: AhrefsResult) -> list[dict[str, Any]]:
    """Bronnen die Google in de AI Overview citeert: `url` en `title`, op volgorde, zonder dubbelen."""
    seen: set[str] = set()
    sources: list[dict[str, Any]] = []
    for row in sorted(result.rows, key=_position):
        url = (row.get("url") or "").strip()
        if "ai_overview_sitelink" not in _types(row) or not url or url in seen:
            continue
        seen.add(url)
        sources.append({"url": url, "title": row.get("title")})
    return sources


def people_also_ask(result: AhrefsResult) -> list[str]:
    """Vragen uit "Mensen vragen ook" (rijen van type `question`, vraag in `title`)."""
    seen: set[str] = set()
    questions: list[str] = []
    for row in sorted(result.rows, key=_position):
        title = (row.get("title") or "").strip()
        if "question" not in _types(row) or not title or title in seen:
            continue
        seen.add(title)
        questions.append(title)
    return questions


def limits_and_usage(*, client: httpx.Client | None = None) -> dict[str, Any]:
    """Abonnement, maandlimiet en verbruik. Dit endpoint kost geen units."""
    payload, _ = _request("GET", "/subscription-info/limits-and-usage", client=client)
    data = payload.get("limits_and_usage")
    return data if isinstance(data, dict) else {}
