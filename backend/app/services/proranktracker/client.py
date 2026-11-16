"""ProRankTracker API v3-client (sync httpx) voor AI Tracking, alleen-lezen.

Deze client doet uitsluitend GET-requests: POST- en DELETE-endpoints van
ProRankTracker verbruiken quota of verwijderen data en horen niet bij deze koppeling.
Elk antwoord heeft een envelop `{"result", "data", "error_message"}`; een fout
kan ook met HTTP 200 komen, dus `result` wordt altijd gecontroleerd.
Fouten worden vertaald naar `ProRankTrackerServiceError` met een `code`.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import settings

API_URL = "https://api.proranktracker.com/v3"
MAX_ATTEMPTS = 3
MAX_RETRY_WAIT_SECONDS = 15.0
# Met een kleine `per_page` kapt ProRankTracker de promptlijsten af.
REPORT_PER_PAGE = 10000
PROMPT_RECORDS_PER_PAGE = 100

FATAL_CODES = {"not_configured", "unauthorized", "forbidden"}


class ProRankTrackerServiceError(Exception):
    def __init__(self, message: str, code: str = "prt_error"):
        super().__init__(message)
        self.code = code


def is_configured() -> bool:
    return bool(settings.proranktracker_api_token.strip())


def _retry_wait(response: httpx.Response | None, attempt: int) -> float:
    header = response.headers.get("Retry-After") if response is not None else None
    try:
        wait = float(header) if header else float(2 ** attempt)
    except ValueError:
        wait = float(2 ** attempt)
    return max(0.0, min(wait, MAX_RETRY_WAIT_SECONDS))


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(payload, dict) and payload.get("error_message"):
        return str(payload["error_message"])[:300]
    return f"HTTP {response.status_code}"


def _request(path: str, *, params: dict[str, Any] | None = None, client: httpx.Client | None = None) -> Any:
    """Voer één GET-request uit en geef `data` uit de envelop terug.

    `client` is alleen bedoeld voor tests (httpx.MockTransport).
    """
    token = settings.proranktracker_api_token.strip()
    if not token:
        raise ProRankTrackerServiceError(
            "ProRankTracker is niet gekoppeld: PRORANKTRACKER_API_X_TOKEN ontbreekt in de backend-configuratie.",
            code="not_configured",
        )
    headers = {"X-TOKEN": token, "Accept": "application/json"}
    owns_client = client is None
    http = client or httpx.Client(timeout=settings.proranktracker_request_timeout_seconds)
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            last_attempt = attempt == MAX_ATTEMPTS
            try:
                response = http.get(f"{API_URL}/{path}", headers=headers, params=params)
            except httpx.TimeoutException as exc:
                raise ProRankTrackerServiceError("Timeout bij verbinden met ProRankTracker.", code="timeout") from exc
            except httpx.HTTPError as exc:
                raise ProRankTrackerServiceError(
                    "Kon geen verbinding maken met ProRankTracker.", code="connection_error"
                ) from exc

            if response.status_code == 401:
                raise ProRankTrackerServiceError(
                    "ProRankTracker weigert het API-token (ongeldig of verlopen).", code="unauthorized"
                )
            if response.status_code == 403:
                raise ProRankTrackerServiceError(
                    f"ProRankTracker staat deze aanvraag niet toe: {_error_message(response)}", code="forbidden"
                )
            if response.status_code == 429 or response.status_code >= 500:
                if last_attempt:
                    code = "rate_limited" if response.status_code == 429 else "prt_error"
                    raise ProRankTrackerServiceError(
                        f"ProRankTracker is tijdelijk niet beschikbaar (HTTP {response.status_code}).", code=code
                    )
                time.sleep(_retry_wait(response, attempt))
                continue
            if response.status_code >= 400:
                raise ProRankTrackerServiceError(
                    f"ProRankTracker-fout: {_error_message(response)}", code="prt_error"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise ProRankTrackerServiceError("Onleesbaar antwoord van ProRankTracker.", code="prt_error") from exc
            if not isinstance(payload, dict):
                raise ProRankTrackerServiceError("Onleesbaar antwoord van ProRankTracker.", code="prt_error")
            # Een fout kan ook met HTTP 200 komen; "partial_success" levert wel bruikbare data.
            if payload.get("result") == "error":
                message = str(payload.get("error_message") or "onbekende fout")[:300]
                raise ProRankTrackerServiceError(f"ProRankTracker-fout: {message}", code="prt_error")
            return payload.get("data")
        raise ProRankTrackerServiceError("ProRankTracker-request mislukt.", code="prt_error")
    finally:
        if owns_client:
            http.close()


def _dict(data: Any) -> dict[str, Any]:
    return data if isinstance(data, dict) else {}


def visibility_report(url_id: int | None = None, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """AI-zichtbaarheidsrapport: zonder `url_id` alle getrackte URL's, met `url_id`
    de `summary_cards` en alle prompts van die ene URL."""
    params: dict[str, Any] = {"per_page": REPORT_PER_PAGE}
    if url_id is not None:
        params["url_id"] = url_id
    return _dict(_request("reports/ai/ai-visibility", params=params, client=client))


def prompt_records(url_id: int, prompt: str, *, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """De records (per engine, mentions en links) van één prompt, inclusief antwoordtekst."""
    params = {
        "url_ids[]": url_id,
        "term_match_type": "exact",
        "bulk_terms": prompt,
        "per_page": PROMPT_RECORDS_PER_PAGE,
    }
    data = _dict(_request("ai/urls", params=params, client=client))
    return [row for row in (data.get("url_terms") or []) if isinstance(row, dict)]


def quota(*, client: httpx.Client | None = None) -> dict[str, Any]:
    """Pakket, actieve en resterende termen."""
    return _dict(_request("user/quota", client=client))
