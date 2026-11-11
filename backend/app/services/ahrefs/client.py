"""Ahrefs API v3-client (sync httpx), gedeeld door features.

Elke functie geeft naast de data ook het aantal verbruikte API-units terug
(header `x-api-units-cost-total-actual`), zodat een scan zijn verbruik kan tonen.
Fouten worden vertaald naar `AhrefsServiceError` met een `code`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

from app.core.config import settings

API_URL = "https://api.ahrefs.com/v3"
MAX_ATTEMPTS = 3
MAX_RETRY_WAIT_SECONDS = 15.0

# Kolommen per rapport. De unit-kosten per rij staan in de Ahrefs-reference:
# top-pages 24 (sum_traffic en top_keyword_volume kosten 10), pages-by-backlinks 8
# (refdomains_target kost 5), broken-backlinks 5.
TOP_PAGES_FIELDS = (
    "url", "sum_traffic", "keywords", "top_keyword",
    "top_keyword_best_position", "top_keyword_volume",
)
BACKLINK_PAGES_FIELDS = ("url_to", "refdomains_target", "dofollow_to_target", "http_code_target")
BROKEN_BACKLINKS_FIELDS = ("url_from", "url_to", "domain_rating_source", "anchor", "http_code_target")
DOMAIN_FIELDS = (
    "domain_rating", "refdomains", "backlinks",
    "org_traffic", "org_keywords", "org_keywords_1_3", "org_cost",
)


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


def limits_and_usage(*, client: httpx.Client | None = None) -> dict[str, Any]:
    """Abonnement, maandlimiet en verbruik. Dit endpoint kost geen units."""
    payload, _ = _request("GET", "/subscription-info/limits-and-usage", client=client)
    data = payload.get("limits_and_usage")
    return data if isinstance(data, dict) else {}
