"""Google Search Console-client, gedeeld door features.

Dunne laag om `google-api-python-client`. Eén Google-account (OAuth desktop-client
plus refresh token uit `scripts/gsc_authorize.py`) heeft alle klanten als property;
`google-auth` ververst het access token zelf. Fouten worden vertaald naar
`SearchConsoleServiceError` met een `code`, zoals bij de Ahrefs-client.

Een service-object (`get_service()`) draait op httplib2 en is niet thread-safe:
maak er één per scan of request en deel hem niet tussen threads.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable

import google_auth_httplib2
import httplib2
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
NUM_RETRIES = 2
# Rechten waarmee de API data teruggeeft; een niet-geverifieerde property doet dat niet.
READABLE_PERMISSIONS = {"siteOwner", "siteFullUser", "siteRestrictedUser"}

# Codes waarbij verder proberen geen zin heeft.
FATAL_CODES = {"not_configured", "token_expired", "forbidden"}


class SearchConsoleServiceError(Exception):
    def __init__(self, message: str, code: str = "gsc_error"):
        super().__init__(message)
        self.code = code


def is_configured() -> bool:
    return all(
        value.strip()
        for value in (settings.gsc_client_id, settings.gsc_client_secret, settings.gsc_refresh_token)
    )


def _credentials() -> Credentials:
    if not is_configured():
        raise SearchConsoleServiceError(
            "Search Console is niet gekoppeld: GSC_CLIENT_ID, GSC_CLIENT_SECRET of GSC_REFRESH_TOKEN "
            "ontbreekt in de backend-configuratie.",
            code="not_configured",
        )
    return Credentials(
        token=None,
        refresh_token=settings.gsc_refresh_token.strip(),
        client_id=settings.gsc_client_id.strip(),
        client_secret=settings.gsc_client_secret.strip(),
        token_uri=TOKEN_URI,
        scopes=SCOPES,
    )


def get_service(http: Any | None = None) -> Any:
    """Service-object voor de Search Console API.

    `http` is alleen bedoeld voor tests (googleapiclient.http.HttpMockSequence).
    """
    if http is None:
        http = google_auth_httplib2.AuthorizedHttp(
            _credentials(), http=httplib2.Http(timeout=settings.gsc_request_timeout_seconds)
        )
    return build("searchconsole", "v1", http=http, cache_discovery=False)


def _http_error(exc: HttpError) -> SearchConsoleServiceError:
    status = int(getattr(exc.resp, "status", 0) or 0)
    reason = str(getattr(exc, "reason", "") or "").strip()[:300] or f"HTTP {status}"
    if status == 401:
        return SearchConsoleServiceError(
            "Google weigert het token. Draai scripts/gsc_authorize.py opnieuw.", code="token_expired"
        )
    if status == 403:
        return SearchConsoleServiceError(
            f"Geen toegang tot deze Search Console-property of API: {reason}", code="forbidden"
        )
    if status == 404:
        return SearchConsoleServiceError(f"Property of URL niet gevonden in Search Console: {reason}",
                                         code="not_found")
    if status == 429:
        return SearchConsoleServiceError("Search Console-quotum bereikt; probeer het later opnieuw.",
                                         code="rate_limited")
    return SearchConsoleServiceError(f"Search Console-fout: {reason}", code="gsc_error")


def _execute(make_request: Callable[[Any], Any], service: Any | None) -> dict[str, Any]:
    """Voer één API-call uit en vertaal fouten."""
    try:
        svc = service if service is not None else get_service()
        payload = make_request(svc).execute(num_retries=NUM_RETRIES)
    except SearchConsoleServiceError:
        raise
    except RefreshError as exc:
        raise SearchConsoleServiceError(
            "Het Search Console-token is verlopen of ingetrokken. Draai scripts/gsc_authorize.py opnieuw "
            "en zet het nieuwe GSC_REFRESH_TOKEN in de backend-configuratie.",
            code="token_expired",
        ) from exc
    except HttpError as exc:
        raise _http_error(exc) from exc
    except TimeoutError as exc:
        raise SearchConsoleServiceError("Timeout bij verbinden met Search Console.", code="timeout") from exc
    except (TransportError, httplib2.HttpLib2Error, OSError) as exc:
        raise SearchConsoleServiceError(
            "Kon geen verbinding maken met Search Console.", code="connection_error"
        ) from exc
    return payload if isinstance(payload, dict) else {}


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def list_sites(*, service: Any | None = None) -> list[dict[str, str]]:
    """Alle properties van het account waar data van opgevraagd kan worden."""
    payload = _execute(lambda svc: svc.sites().list(), service)
    sites = [
        {"site_url": str(entry.get("siteUrl") or ""), "permission": str(entry.get("permissionLevel") or "")}
        for entry in payload.get("siteEntry") or []
        if isinstance(entry, dict)
    ]
    return sorted(
        (s for s in sites if s["site_url"] and s["permission"] in READABLE_PERMISSIONS),
        key=lambda s: s["site_url"],
    )


def search_analytics(
    site_url: str,
    start: date,
    end: date,
    *,
    dimensions: tuple[str, ...] = (),
    row_limit: int = 1,
    service: Any | None = None,
) -> list[dict[str, Any]]:
    """Prestaties (zoekresultaten op het web) over een periode.

    Zonder `dimensions` één rij met de totalen van de property; anders per rij
    `keys` in de volgorde van de dimensies. Geen data = lege lijst.
    """
    body: dict[str, Any] = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "type": "web",
        "rowLimit": max(1, row_limit),
    }
    if dimensions:
        body["dimensions"] = list(dimensions)
    payload = _execute(lambda svc: svc.searchanalytics().query(siteUrl=site_url, body=body), service)
    rows = []
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        rows.append({
            "keys": [str(k) for k in row.get("keys") or []],
            "clicks": float(row.get("clicks") or 0),
            "impressions": float(row.get("impressions") or 0),
            "ctr": float(row.get("ctr") or 0),
            "position": float(row.get("position") or 0),
        })
    return rows


def list_sitemaps(site_url: str, *, service: Any | None = None) -> list[dict[str, Any]]:
    payload = _execute(lambda svc: svc.sitemaps().list(siteUrl=site_url), service)
    sitemaps = []
    for entry in payload.get("sitemap") or []:
        if not isinstance(entry, dict):
            continue
        sitemaps.append({
            "path": str(entry.get("path") or ""),
            "last_submitted": entry.get("lastSubmitted"),
            "last_downloaded": entry.get("lastDownloaded"),
            "is_pending": bool(entry.get("isPending")),
            "is_index": bool(entry.get("isSitemapsIndex")),
            "errors": _int(entry.get("errors")),
            "warnings": _int(entry.get("warnings")),
            "submitted": sum(
                _int(c.get("submitted")) for c in entry.get("contents") or [] if isinstance(c, dict)
            ),
        })
    return sitemaps


def inspect_url(site_url: str, url: str, *, service: Any | None = None) -> dict[str, Any]:
    """Indexstatus van één URL volgens Google (URL Inspection API)."""
    body = {"inspectionUrl": url, "siteUrl": site_url, "languageCode": "nl-NL"}
    payload = _execute(lambda svc: svc.urlInspection().index().inspect(body=body), service)
    result = payload.get("inspectionResult") or {}
    index = result.get("indexStatusResult") or {}
    return {
        "url": url,
        "verdict": index.get("verdict"),
        "coverage_state": index.get("coverageState"),
        "robots_txt_state": index.get("robotsTxtState"),
        "indexing_state": index.get("indexingState"),
        "page_fetch_state": index.get("pageFetchState"),
        "google_canonical": index.get("googleCanonical"),
        "user_canonical": index.get("userCanonical"),
        "last_crawl_time": index.get("lastCrawlTime"),
        "link": result.get("inspectionResultLink"),
    }


__all__ = [
    "FATAL_CODES",
    "SCOPES",
    "SearchConsoleServiceError",
    "get_service",
    "inspect_url",
    "is_configured",
    "list_sitemaps",
    "list_sites",
    "search_analytics",
]
