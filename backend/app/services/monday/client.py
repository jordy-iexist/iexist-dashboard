"""Monday.com GraphQL-client (sync httpx), gedeeld door features.

Monday geeft applicatiefouten terug met HTTP 200 en een `errors`-lijst; alleen
transportfouten (401, 429, 5xx) hebben een afwijkende statuscode. Beide worden
hier vertaald naar `MondayServiceError` met een `code`.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings

API_URL = "https://api.monday.com/v2"
MAX_ATTEMPTS = 3
MAX_RETRY_WAIT_SECONDS = 15.0
_FOLDER_PAGE_SIZE = 100
_FOLDER_MAX_PAGES = 20
_ITEMS_PAGE_SIZE = 100
_BOARD_URL_PATTERN = re.compile(r"/boards/(\d+)")
_RATE_LIMIT_CODES = {
    "COMPLEXITY_BUDGET_EXHAUSTED",
    "RATE_LIMIT_EXCEEDED",
    "IP_RATE_LIMIT_EXCEEDED",
    "maxConcurrencyExceeded",
}
_UNAUTHORIZED_CODES = {"UserUnauthorizedException", "USER_UNAUTHORIZED", "Unauthorized"}


class MondayServiceError(Exception):
    def __init__(self, message: str, code: str = "monday_error"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MondayFolder:
    id: str
    name: str
    workspace_id: str | None


@dataclass(frozen=True)
class MondayGroup:
    id: str
    title: str


@dataclass(frozen=True)
class MondayBoard:
    id: str
    name: str
    url: str | None
    groups: list[MondayGroup] = field(default_factory=list)


@dataclass(frozen=True)
class MondayItem:
    id: str
    url: str | None


def is_configured() -> bool:
    return bool(settings.monday_api_token.strip())


def parse_board_id(raw: str) -> str | None:
    """Bord-id uit een los id of een geplakte bord-URL."""
    value = str(raw or "").strip()
    if value.isdigit():
        return value
    match = _BOARD_URL_PATTERN.search(value)
    return match.group(1) if match else None


def _retry_wait(response: httpx.Response | None, attempt: int) -> float:
    header = response.headers.get("Retry-After") if response is not None else None
    try:
        wait = float(header) if header else float(2 ** attempt)
    except ValueError:
        wait = float(2 ** attempt)
    return max(0.0, min(wait, MAX_RETRY_WAIT_SECONDS))


def _error_from_payload(errors: list[Any]) -> MondayServiceError:
    first = errors[0] if errors and isinstance(errors[0], dict) else {}
    message = str(first.get("message") or "Onbekende Monday-fout.")
    extensions = first.get("extensions") if isinstance(first.get("extensions"), dict) else {}
    code = str(extensions.get("code") or "")
    if code in _RATE_LIMIT_CODES:
        return MondayServiceError(f"Monday-limiet bereikt: {message}", code="rate_limited")
    if code in _UNAUTHORIZED_CODES:
        return MondayServiceError(
            f"Geen rechten in Monday voor deze actie: {message}", code="unauthorized"
        )
    return MondayServiceError(f"Monday-fout: {message}", code="monday_error")


def _graphql(
    query: str,
    variables: dict[str, Any] | None = None,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Voer één GraphQL-request uit en geef `data` terug.

    `client` is alleen bedoeld voor tests (httpx.MockTransport).
    """
    token = settings.monday_api_token.strip()
    if not token:
        raise MondayServiceError(
            "Monday is niet gekoppeld: MONDAY_API_TOKEN ontbreekt in de backend-configuratie.",
            code="not_configured",
        )
    headers = {
        "Authorization": token,
        "API-Version": settings.monday_api_version,
        "Content-Type": "application/json",
    }
    body = {"query": query, "variables": variables or {}}
    owns_client = client is None
    http = client or httpx.Client(timeout=settings.monday_request_timeout_seconds)
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            last_attempt = attempt == MAX_ATTEMPTS
            try:
                response = http.post(API_URL, headers=headers, json=body)
            except httpx.TimeoutException as exc:
                raise MondayServiceError(
                    "Timeout bij verbinden met Monday.", code="timeout"
                ) from exc
            except httpx.HTTPError as exc:
                raise MondayServiceError(
                    "Kon geen verbinding maken met Monday.", code="connection_error"
                ) from exc

            if response.status_code in (401, 403):
                raise MondayServiceError(
                    "Monday weigert het API-token (ongeldig of onvoldoende rechten).",
                    code="unauthorized",
                )
            if response.status_code == 429 or response.status_code >= 500:
                if last_attempt:
                    code = "rate_limited" if response.status_code == 429 else "monday_error"
                    raise MondayServiceError(
                        f"Monday is tijdelijk niet beschikbaar (HTTP {response.status_code}).",
                        code=code,
                    )
                time.sleep(_retry_wait(response, attempt))
                continue

            try:
                payload = response.json()
            except ValueError as exc:
                raise MondayServiceError(
                    f"Onleesbaar antwoord van Monday (HTTP {response.status_code}).",
                    code="monday_error",
                ) from exc
            if not isinstance(payload, dict):
                raise MondayServiceError("Onleesbaar antwoord van Monday.", code="monday_error")

            errors = payload.get("errors")
            if errors:
                error = _error_from_payload(errors if isinstance(errors, list) else [])
                if error.code == "rate_limited" and not last_attempt:
                    time.sleep(_retry_wait(response, attempt))
                    continue
                raise error
            if response.status_code >= 400:
                message = payload.get("error_message") or f"HTTP {response.status_code}"
                raise MondayServiceError(f"Monday-fout: {message}", code="monday_error")

            data = payload.get("data")
            return data if isinstance(data, dict) else {}
        raise MondayServiceError("Monday-request mislukt.", code="monday_error")
    finally:
        if owns_client:
            http.close()


def _to_board(raw: dict[str, Any]) -> MondayBoard:
    groups = [
        MondayGroup(id=str(g["id"]), title=str(g.get("title") or ""))
        for g in (raw.get("groups") or [])
        if isinstance(g, dict) and g.get("id") is not None
    ]
    return MondayBoard(
        id=str(raw["id"]),
        name=str(raw.get("name") or ""),
        url=raw.get("url") or None,
        groups=groups,
    )


def find_folder(name: str, *, client: httpx.Client | None = None) -> MondayFolder:
    """Zoek een map op naam (hoofdletterongevoelig) over alle werkruimtes."""
    wanted = name.strip().casefold()
    query = """
    query ($limit: Int!, $page: Int!) {
      folders(limit: $limit, page: $page) { id name workspace { id } }
    }
    """
    for page in range(1, _FOLDER_MAX_PAGES + 1):
        data = _graphql(query, {"limit": _FOLDER_PAGE_SIZE, "page": page}, client=client)
        folders = data.get("folders") or []
        for raw in folders:
            if str(raw.get("name") or "").strip().casefold() == wanted:
                workspace = raw.get("workspace") or {}
                workspace_id = workspace.get("id")
                return MondayFolder(
                    id=str(raw["id"]),
                    name=str(raw["name"]),
                    workspace_id=str(workspace_id) if workspace_id is not None else None,
                )
        if len(folders) < _FOLDER_PAGE_SIZE:
            break
    raise MondayServiceError(
        f'Map "{name}" niet gevonden in Monday.', code="folder_not_found"
    )


def get_folder(folder_id: str, *, client: httpx.Client | None = None) -> MondayFolder:
    query = "query ($ids: [ID!]) { folders(ids: $ids) { id name workspace { id } } }"
    data = _graphql(query, {"ids": [folder_id]}, client=client)
    folders = data.get("folders") or []
    if not folders:
        raise MondayServiceError(
            f"Monday-map {folder_id} niet gevonden.", code="folder_not_found"
        )
    raw = folders[0]
    workspace_id = (raw.get("workspace") or {}).get("id")
    return MondayFolder(
        id=str(raw["id"]),
        name=str(raw.get("name") or ""),
        workspace_id=str(workspace_id) if workspace_id is not None else None,
    )


def get_board(board_id: str, *, client: httpx.Client | None = None) -> MondayBoard:
    query = """
    query ($ids: [ID!]) {
      boards(ids: $ids) { id name url state groups { id title } }
    }
    """
    data = _graphql(query, {"ids": [board_id]}, client=client)
    boards = [b for b in (data.get("boards") or []) if isinstance(b, dict)]
    if not boards or boards[0].get("state") == "deleted":
        raise MondayServiceError(
            f"Monday-bord {board_id} niet gevonden (verwijderd of geen toegang).",
            code="board_not_found",
        )
    return _to_board(boards[0])


def create_board(
    name: str,
    *,
    folder_id: str,
    workspace_id: str | None,
    client: httpx.Client | None = None,
) -> MondayBoard:
    """Maak een leeg, openbaar (binnen het account) bord in een map."""
    query = """
    mutation ($name: String!, $folder: ID, $workspace: ID) {
      create_board(
        board_name: $name, board_kind: public,
        folder_id: $folder, workspace_id: $workspace, empty: true
      ) { id name url groups { id title } }
    }
    """
    data = _graphql(
        query,
        {"name": name, "folder": folder_id, "workspace": workspace_id},
        client=client,
    )
    raw = data.get("create_board")
    if not isinstance(raw, dict) or raw.get("id") is None:
        raise MondayServiceError("Monday gaf geen bord terug.", code="monday_error")
    return _to_board(raw)


def create_group(board_id: str, name: str, *, client: httpx.Client | None = None) -> MondayGroup:
    query = """
    mutation ($board: ID!, $name: String!) {
      create_group(board_id: $board, group_name: $name) { id title }
    }
    """
    data = _graphql(query, {"board": board_id, "name": name}, client=client)
    raw = data.get("create_group")
    if not isinstance(raw, dict) or raw.get("id") is None:
        raise MondayServiceError("Monday gaf geen groep terug.", code="monday_error")
    return MondayGroup(id=str(raw["id"]), title=str(raw.get("title") or name))


def create_item(
    board_id: str,
    item_name: str,
    *,
    group_id: str | None = None,
    client: httpx.Client | None = None,
) -> MondayItem:
    query = """
    mutation ($board: ID!, $group: String, $name: String!) {
      create_item(board_id: $board, group_id: $group, item_name: $name) { id url }
    }
    """
    data = _graphql(
        query, {"board": board_id, "group": group_id, "name": item_name}, client=client
    )
    raw = data.get("create_item")
    if not isinstance(raw, dict) or raw.get("id") is None:
        raise MondayServiceError("Monday gaf geen item terug.", code="monday_error")
    return MondayItem(id=str(raw["id"]), url=raw.get("url") or None)


def missing_item_ids(item_ids: list[str], *, client: httpx.Client | None = None) -> set[str]:
    """Welke van deze items bestaan niet meer in Monday (verwijderd of onvindbaar).

    Gearchiveerde items tellen als bestaand: die zijn bewust opgeborgen.
    """
    ids = list(dict.fromkeys(str(i) for i in item_ids if i))
    query = "query ($ids: [ID!], $limit: Int!) { items(ids: $ids, limit: $limit) { id state } }"
    alive: set[str] = set()
    for start in range(0, len(ids), _ITEMS_PAGE_SIZE):
        chunk = ids[start:start + _ITEMS_PAGE_SIZE]
        data = _graphql(query, {"ids": chunk, "limit": _ITEMS_PAGE_SIZE}, client=client)
        for raw in data.get("items") or []:
            if isinstance(raw, dict) and raw.get("state") != "deleted":
                alive.add(str(raw.get("id")))
    return set(ids) - alive


def create_subitem(
    parent_item_id: str, item_name: str, *, client: httpx.Client | None = None
) -> MondayItem:
    query = """
    mutation ($parent: ID!, $name: String!) {
      create_subitem(parent_item_id: $parent, item_name: $name) { id url }
    }
    """
    data = _graphql(query, {"parent": parent_item_id, "name": item_name}, client=client)
    raw = data.get("create_subitem")
    if not isinstance(raw, dict) or raw.get("id") is None:
        raise MondayServiceError("Monday gaf geen subitem terug.", code="monday_error")
    return MondayItem(id=str(raw["id"]), url=raw.get("url") or None)


def create_update(item_id: str, body_html: str, *, client: httpx.Client | None = None) -> None:
    """Plaats een update (toelichting) bij een item; werkt op elk bord."""
    query = """
    mutation ($item: ID!, $body: String!) {
      create_update(item_id: $item, body: $body) { id }
    }
    """
    _graphql(query, {"item": item_id, "body": body_html}, client=client)
