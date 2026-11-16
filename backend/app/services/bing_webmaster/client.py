"""Bing Webmaster Tools-client (sync httpx), gedeeld door features.

Twee manieren van aanmelden, aangereikt als `BingAuth`: een OAuth access-token
(productie, via de koppelknop) of een API-key (lokaal testen). De leesfuncties
weten niet welke van de twee het is. Deze module raakt de database niet; het
bewaren en verversen van tokens zit in `connection.py`.

Bing geeft fouten terug als HTTP 400 met `{"ErrorCode": n, "Message": "..."}`.
Die worden vertaald naar `BingWebmasterServiceError` met een `code`.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings

API_URL = "https://www.bing.com/webmaster/api.svc/json"
AUTHORIZE_URL = "https://www.bing.com/webmasters/oauth/authorize"
TOKEN_URL = "https://www.bing.com/webmasters/oauth/token"
# Alleen lezen: de koppeling kan niets wijzigen in Bing Webmaster.
SCOPE = "webmaster.read"
MAX_ATTEMPTS = 3
MAX_RETRY_WAIT_SECONDS = 15.0

# Bij deze codes heeft doorgaan geen zin: elke volgende call faalt op dezelfde manier.
FATAL_CODES = {"not_configured", "not_connected", "unauthorized", "token_expired", "site_not_found"}

# ErrorCode van Bing → onze code. 14 (NotAuthorized) komt ook terug voor een site
# die niet in het account staat; 3 en 18 zijn een ongeldige API-key of token.
_ERROR_CODES: dict[int, str] = {
    3: "unauthorized",
    4: "rate_limited",
    5: "rate_limited",
    7: "invalid_url",
    14: "site_not_found",
    18: "unauthorized",
}

# UrlWithCrawlIssues.CrawlIssues is een vlaggen-enum.
_CRAWL_ISSUE_FLAGS: list[tuple[int, str, str]] = [
    (1, "code_301", "301-redirect"),
    (2, "code_302", "302-redirect"),
    (4, "code_4xx", "4xx-fout"),
    (8, "code_5xx", "serverfout (5xx)"),
    (16, "blocked_by_robots", "geblokkeerd door robots.txt"),
    (32, "contains_malware", "malware gevonden"),
    (64, "important_blocked_by_robots", "belangrijke URL geblokkeerd door robots.txt"),
    (128, "dns_errors", "DNS-fout"),
    (256, "timeout_errors", "time-out"),
]

_DATE_RE = re.compile(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/")


class BingWebmasterServiceError(Exception):
    def __init__(self, message: str, code: str = "bing_error"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BingAuth:
    """Aanmelding voor één request: precies één van beide is gezet."""

    api_key: str | None = None
    access_token: str | None = None

    @property
    def mode(self) -> str:
        return "api_key" if self.api_key else "oauth"


# --- configuratie -----------------------------------------------------------------

def api_key_auth() -> BingAuth | None:
    key = settings.bing_webmaster_api_key.strip()
    return BingAuth(api_key=key) if key else None


def oauth_configured() -> bool:
    return bool(
        settings.bing_client_id.strip()
        and settings.bing_client_secret.strip()
        and settings.bing_webmaster_redirect_uri.strip()
    )


def is_configured() -> bool:
    return api_key_auth() is not None or oauth_configured()


# --- OAuth -------------------------------------------------------------------------

def _require_oauth() -> None:
    if not oauth_configured():
        raise BingWebmasterServiceError(
            "Bing Webmaster-OAuth is niet geconfigureerd: BING_CLIENT_ID, BING_CLIENT_SECRET en "
            "BING_WEBMASTER_REDIRECT_URI ontbreken in de backend-configuratie.",
            code="not_configured",
        )


def authorize_url(state: str) -> str:
    """URL waar de gebruiker toestemming geeft. `state` komt terug op de callback."""
    _require_oauth()
    query = urlencode({
        "response_type": "code",
        "client_id": settings.bing_client_id.strip(),
        "redirect_uri": settings.bing_webmaster_redirect_uri.strip(),
        "scope": SCOPE,
        "state": state,
    })
    return f"{AUTHORIZE_URL}?{query}"


def _token_request(form: dict[str, str], client: httpx.Client | None) -> dict[str, Any]:
    _require_oauth()
    body = {
        "client_id": settings.bing_client_id.strip(),
        "client_secret": settings.bing_client_secret.strip(),
        **form,
    }
    owns_client = client is None
    http = client or httpx.Client(timeout=settings.bing_webmaster_request_timeout_seconds)
    try:
        try:
            response = http.post(TOKEN_URL, data=body, headers={"Accept": "application/json"})
        except httpx.TimeoutException as exc:
            raise BingWebmasterServiceError("Timeout bij verbinden met Bing.", code="timeout") from exc
        except httpx.HTTPError as exc:
            raise BingWebmasterServiceError("Kon geen verbinding maken met Bing.", code="connection_error") from exc
    finally:
        if owns_client:
            http.close()
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if response.status_code >= 400 or not isinstance(payload, dict) or not payload.get("access_token"):
        error = payload.get("error") if isinstance(payload, dict) else None
        detail = (payload.get("error_description") if isinstance(payload, dict) else None) or error
        # invalid_grant: de code is verlopen/al gebruikt, of het refresh-token is ingetrokken.
        code = "token_expired" if error == "invalid_grant" else "oauth_error"
        raise BingWebmasterServiceError(
            f"Bing weigert de aanmelding: {str(detail or f'HTTP {response.status_code}')[:300]}", code=code
        )
    return payload


def exchange_code(code: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """Wissel de autorisatiecode in voor `{access_token, refresh_token, expires_in}`."""
    payload = _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            # Altijd de geconfigureerde URI, nooit de host van het verzoek: Bing eist een exacte match.
            "redirect_uri": settings.bing_webmaster_redirect_uri.strip(),
        },
        client,
    )
    if not payload.get("refresh_token"):
        raise BingWebmasterServiceError("Bing gaf geen refresh-token terug.", code="oauth_error")
    return payload


def refresh_access_token(refresh_token: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """Nieuw access-token; `refresh_token` zit alleen in het antwoord als Bing hem vervangt."""
    return _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token}, client)


# --- requests ----------------------------------------------------------------------

def _retry_wait(response: httpx.Response | None, attempt: int) -> float:
    header = response.headers.get("Retry-After") if response is not None else None
    try:
        wait = float(header) if header else float(2 ** attempt)
    except ValueError:
        wait = float(2 ** attempt)
    return max(0.0, min(wait, MAX_RETRY_WAIT_SECONDS))


def _api_error(response: httpx.Response) -> BingWebmasterServiceError:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    error_code = payload.get("ErrorCode") if isinstance(payload, dict) else None
    message = str(payload.get("Message") or "") if isinstance(payload, dict) else ""
    message = message.replace("ERROR!!!", "").strip() or f"HTTP {response.status_code}"
    code = _ERROR_CODES.get(error_code) if isinstance(error_code, int) else None
    if response.status_code == 401:
        code = "unauthorized"
    if code == "unauthorized":
        return BingWebmasterServiceError("Bing weigert de aanmelding (key of token ongeldig of verlopen).", code=code)
    if code == "site_not_found":
        return BingWebmasterServiceError("De site staat niet in het Bing Webmaster-account.", code=code)
    if code == "rate_limited":
        return BingWebmasterServiceError("Bing Webmaster beperkt het aantal aanvragen; probeer het later opnieuw.", code=code)
    return BingWebmasterServiceError(f"Bing Webmaster-fout: {message[:300]}", code=code or "bing_error")


def _get(
    method: str,
    auth: BingAuth,
    params: dict[str, Any] | None = None,
    *,
    client: httpx.Client | None = None,
) -> Any:
    """Roep één leesmethode aan en geef de inhoud van `d` terug.

    `client` is alleen bedoeld voor tests (httpx.MockTransport).
    """
    query = dict(params or {})
    headers = {"Accept": "application/json"}
    if auth.api_key:
        query["apikey"] = auth.api_key
    elif auth.access_token:
        headers["Authorization"] = f"Bearer {auth.access_token}"
    else:
        raise BingWebmasterServiceError("Bing Webmaster is niet gekoppeld.", code="not_connected")
    owns_client = client is None
    http = client or httpx.Client(timeout=settings.bing_webmaster_request_timeout_seconds)
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = http.get(f"{API_URL}/{method}", params=query, headers=headers)
            except httpx.TimeoutException as exc:
                raise BingWebmasterServiceError("Timeout bij verbinden met Bing.", code="timeout") from exc
            except httpx.HTTPError as exc:
                raise BingWebmasterServiceError(
                    "Kon geen verbinding maken met Bing.", code="connection_error"
                ) from exc
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == MAX_ATTEMPTS:
                    code = "rate_limited" if response.status_code == 429 else "bing_error"
                    raise BingWebmasterServiceError(
                        f"Bing Webmaster is tijdelijk niet beschikbaar (HTTP {response.status_code}).", code=code
                    )
                time.sleep(_retry_wait(response, attempt))
                continue
            if response.status_code >= 400:
                raise _api_error(response)
            try:
                payload = response.json()
            except ValueError as exc:
                raise BingWebmasterServiceError("Onleesbaar antwoord van Bing.", code="bing_error") from exc
            if not isinstance(payload, dict) or "d" not in payload:
                raise BingWebmasterServiceError("Onleesbaar antwoord van Bing.", code="bing_error")
            return payload["d"]
        raise BingWebmasterServiceError("Bing-request mislukt.", code="bing_error")
    finally:
        if owns_client:
            http.close()


def _rows(data: Any) -> list[dict[str, Any]]:
    return [row for row in (data or []) if isinstance(row, dict)]


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse_date(value: Any) -> date | None:
    """`/Date(1778889600000)/` (ms sinds 1970, eventueel met offset) → datum in UTC."""
    moment = parse_datetime(value)
    return moment.date() if moment else None


def parse_datetime(value: Any) -> datetime | None:
    match = _DATE_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    try:
        return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _iso(value: Any) -> str | None:
    moment = parse_datetime(value)
    # Bing gebruikt een datum ver in het verleden voor "nooit".
    return moment.isoformat() if moment and moment.year > 2000 else None


# --- leesmethodes --------------------------------------------------------------------

def list_sites(auth: BingAuth, *, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """Sites in het account: `[{url, verified}]`. De verificatiecodes laten we weg."""
    return [
        {"url": str(row.get("Url") or ""), "verified": bool(row.get("IsVerified"))}
        for row in _rows(_get("GetUserSites", auth, client=client))
        if row.get("Url")
    ]


def crawl_stats(auth: BingAuth, site_url: str, *, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """Crawl- en indexcijfers per dag (ongeveer een half jaar), oudste eerst.

    `crawled_pages` is het aantal die dag; de overige velden zijn de stand op die dag.
    """
    rows = []
    for row in _rows(_get("GetCrawlStats", auth, {"siteUrl": site_url}, client=client)):
        day = parse_date(row.get("Date"))
        if day is None:
            continue
        rows.append({
            "date": day,
            "in_index": _int(row.get("InIndex")),
            "in_links": _int(row.get("InLinks")),
            "crawled_pages": _int(row.get("CrawledPages")),
            "crawl_errors": _int(row.get("CrawlErrors")),
            "code_2xx": _int(row.get("Code2xx")),
            "code_301": _int(row.get("Code301")),
            "code_302": _int(row.get("Code302")),
            "code_4xx": _int(row.get("Code4xx")),
            "code_5xx": _int(row.get("Code5xx")),
            "other_codes": _int(row.get("AllOtherCodes")),
            "blocked_by_robots": _int(row.get("BlockedByRobotsTxt")),
            "dns_failures": _int(row.get("DnsFailures")),
            "connection_timeouts": _int(row.get("ConnectionTimeout")),
            "contains_malware": _int(row.get("ContainsMalware")),
        })
    return sorted(rows, key=lambda r: r["date"])


def decode_crawl_issues(value: Any) -> list[dict[str, str]]:
    """Vlaggen van één URL → `[{key, label}]`."""
    if isinstance(value, str) and not value.strip().lstrip("-").isdigit():
        return [{"key": value.strip(), "label": value.strip()}] if value.strip() else []
    flags = _int(value)
    return [{"key": key, "label": label} for bit, key, label in _CRAWL_ISSUE_FLAGS if flags & bit]


def crawl_issues(auth: BingAuth, site_url: str, *, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """URL's waar Bing een crawlprobleem meldt."""
    return [
        {
            "url": str(row.get("Url") or ""),
            "http_code": _int(row.get("HttpCode")) or None,
            "in_links": _int(row.get("InLinks")),
            "issues": decode_crawl_issues(row.get("Issues")),
        }
        for row in _rows(_get("GetCrawlIssues", auth, {"siteUrl": site_url}, client=client))
        if row.get("Url")
    ]


def feeds(auth: BingAuth, site_url: str, *, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """Ingediende sitemaps en feeds."""
    return [
        {
            "url": str(row.get("Url") or ""),
            "status": str(row.get("Status") or ""),
            "type": str(row.get("Type") or ""),
            "url_count": _int(row.get("UrlCount")),
            "last_crawled": _iso(row.get("LastCrawled")),
            "submitted": _iso(row.get("Submitted")),
        }
        for row in _rows(_get("GetFeeds", auth, {"siteUrl": site_url}, client=client))
        if row.get("Url")
    ]


def traffic_stats(auth: BingAuth, site_url: str, *, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """Klikken en vertoningen per dag, oudste eerst. Dagen zonder vertoningen ontbreken."""
    rows = []
    for row in _rows(_get("GetRankAndTrafficStats", auth, {"siteUrl": site_url}, client=client)):
        day = parse_date(row.get("Date"))
        if day is not None:
            rows.append({"date": day, "clicks": _int(row.get("Clicks")), "impressions": _int(row.get("Impressions"))})
    return sorted(rows, key=lambda r: r["date"])


def _keyed_stats(method: str, auth: BingAuth, site_url: str, client: httpx.Client | None) -> list[dict[str, Any]]:
    rows = []
    for row in _rows(_get(method, auth, {"siteUrl": site_url}, client=client)):
        day = parse_date(row.get("Date"))
        key = str(row.get("Query") or "").strip()
        if day is None or not key:
            continue
        position = row.get("AvgImpressionPosition")
        rows.append({
            "key": key,
            "date": day,
            "clicks": _int(row.get("Clicks")),
            "impressions": _int(row.get("Impressions")),
            # -1 betekent "geen positie".
            "position": float(position) if isinstance(position, (int, float)) and position > 0 else None,
        })
    return rows


def query_stats(auth: BingAuth, site_url: str, *, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """Zoekopdrachten per week: `[{key, date, clicks, impressions, position}]`."""
    return _keyed_stats("GetQueryStats", auth, site_url, client)


def page_stats(auth: BingAuth, site_url: str, *, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """Pagina's per week; `key` is de URL."""
    return _keyed_stats("GetPageStats", auth, site_url, client)
