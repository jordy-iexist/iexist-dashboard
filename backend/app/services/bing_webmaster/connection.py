"""De Bing Webmaster-koppeling van de app: tokens bewaren, verversen en uitdelen.

Er is één koppeling voor alle klanten (één Bing-account met alle sites). De
tokens staan versleuteld in `oauth_connections`; API en worker lezen dezelfde
rij, dus het access-token wordt onder een rij-lock ververst.

Is `BING_WEBMASTER_API_KEY` gezet (lokaal testen), dan wint die en wordt de
database niet geraakt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx
from sqlalchemy.orm import Session

from app.core.secrets import decrypt_secret, encrypt_secret
from app.db.models import OAuthConnection
from app.services.bing_webmaster import client
from app.services.bing_webmaster.client import BingAuth, BingWebmasterServiceError

PROVIDER = "bing_webmaster"
# Ververs iets voor het verlopen, zodat een token niet halverwege een reeks calls verloopt.
EXPIRY_MARGIN = timedelta(seconds=120)
DEFAULT_EXPIRES_IN = 3600

_NOT_CONNECTED = "Bing Webmaster is niet gekoppeld: koppel het account bij fase 4."
_EXPIRED = "De Bing Webmaster-koppeling is verlopen of ingetrokken: koppel het account opnieuw."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(moment: datetime | None) -> datetime | None:
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _row(db: Session, *, lock: bool = False) -> OAuthConnection | None:
    query = db.query(OAuthConnection).filter(OAuthConnection.provider == PROVIDER)
    if lock:
        query = query.with_for_update()
    return query.first()


def _store_access(row: OAuthConnection, tokens: dict[str, Any]) -> None:
    try:
        expires_in = int(tokens.get("expires_in") or DEFAULT_EXPIRES_IN)
    except (TypeError, ValueError):
        expires_in = DEFAULT_EXPIRES_IN
    row.access_token_encrypted = encrypt_secret(str(tokens["access_token"]))
    row.access_token_expires_at = _now() + timedelta(seconds=expires_in)
    # Bing vervangt het refresh-token volgens de documentatie niet; doet het dat toch, bewaar het.
    if tokens.get("refresh_token"):
        row.refresh_token_encrypted = encrypt_secret(str(tokens["refresh_token"]))
    row.last_error = None
    row.updated_at = _now()


def status(db: Session) -> dict[str, Any]:
    """Stand van de koppeling voor de UI. Doet geen calls naar Bing."""
    oauth_available = client.oauth_configured()
    if client.api_key_auth() is not None:
        return {
            "configured": True, "mode": "api_key", "oauth_available": oauth_available,
            "connected": True, "connected_at": None, "error": None,
        }
    row = _row(db) if oauth_available else None
    return {
        "configured": oauth_available,
        "mode": "oauth" if oauth_available else None,
        "oauth_available": oauth_available,
        "connected": row is not None and not row.last_error,
        "connected_at": _aware(row.connected_at) if row is not None else None,
        "error": row.last_error if row is not None else None,
    }


def save_tokens(db: Session, tokens: dict[str, Any], user_id: str | None) -> None:
    """Bewaar de tokens van een geslaagde koppeling (vervangt een bestaande)."""
    row = _row(db, lock=True)
    if row is None:
        row = OAuthConnection(provider=PROVIDER, refresh_token_encrypted="")
        db.add(row)
    row.refresh_token_encrypted = encrypt_secret(str(tokens["refresh_token"]))
    row.connected_by = user_id
    row.connected_at = _now()
    _store_access(row, tokens)
    db.commit()


def disconnect(db: Session) -> bool:
    """Verwijder de koppeling. True als er een was."""
    deleted = db.query(OAuthConnection).filter(OAuthConnection.provider == PROVIDER).delete()
    db.commit()
    return bool(deleted)


def _mark_error(db: Session, message: str) -> None:
    row = _row(db, lock=True)
    if row is not None:
        row.last_error = message
        row.access_token_encrypted = None
        row.access_token_expires_at = None
        row.updated_at = _now()
    db.commit()


def get_auth(
    db: Session, *, force_refresh: bool = False, http: httpx.Client | None = None
) -> BingAuth:
    """Aanmelding voor de client: de API-key, of een geldig OAuth access-token.

    Ververst het access-token als het (bijna) verlopen is. Raises
    `BingWebmasterServiceError` met code `not_configured`, `not_connected` of
    `token_expired`.
    """
    key_auth = client.api_key_auth()
    if key_auth is not None:
        return key_auth
    if not client.oauth_configured():
        raise BingWebmasterServiceError(
            "Bing Webmaster is niet geconfigureerd (BING_CLIENT_ID, BING_CLIENT_SECRET, "
            "BING_WEBMASTER_REDIRECT_URI).",
            code="not_configured",
        )
    row = _row(db, lock=True)
    try:
        if row is None:
            raise BingWebmasterServiceError(_NOT_CONNECTED, code="not_connected")
        if row.last_error and not force_refresh:
            raise BingWebmasterServiceError(_EXPIRED, code="token_expired")
        expires_at = _aware(row.access_token_expires_at)
        fresh = (
            row.access_token_encrypted
            and expires_at is not None
            and expires_at - EXPIRY_MARGIN > _now()
        )
        if fresh and not force_refresh:
            return BingAuth(access_token=decrypt_secret(row.access_token_encrypted))
        try:
            tokens = client.refresh_access_token(decrypt_secret(row.refresh_token_encrypted), client=http)
        except BingWebmasterServiceError as exc:
            if exc.code == "token_expired":
                row.last_error = _EXPIRED
                row.access_token_encrypted = None
                row.access_token_expires_at = None
                row.updated_at = _now()
                raise BingWebmasterServiceError(_EXPIRED, code="token_expired") from exc
            raise
        _store_access(row, tokens)
        return BingAuth(access_token=str(tokens["access_token"]))
    finally:
        db.commit()  # bewaart een nieuw token of de foutmelding en geeft de rij-lock vrij


class BingSession:
    """Leesmethodes van de client met de aanmelding van de app.

    Weigert Bing het access-token terwijl het volgens ons nog geldig was (toegang
    ingetrokken), dan ververst de sessie één keer en probeert het opnieuw. Lukt
    dat niet, dan wordt de koppeling als verlopen gemarkeerd.
    """

    def __init__(self, db: Session, *, http: httpx.Client | None = None):
        self._db = db
        self._http = http
        self._auth: BingAuth | None = None

    @property
    def auth(self) -> BingAuth:
        if self._auth is None:
            self._auth = get_auth(self._db, http=self._http)
        return self._auth

    @property
    def mode(self) -> str:
        return self.auth.mode

    def _call(self, fn: Callable[..., Any], *args: Any) -> Any:
        auth = self.auth
        try:
            return fn(auth, *args, client=self._http)
        except BingWebmasterServiceError as exc:
            if exc.code != "unauthorized":
                raise
            if auth.api_key:
                raise BingWebmasterServiceError(
                    "Bing weigert de API-key (BING_WEBMASTER_API_KEY is ongeldig).", code="unauthorized"
                ) from exc
        self._auth = get_auth(self._db, force_refresh=True, http=self._http)
        try:
            return fn(self._auth, *args, client=self._http)
        except BingWebmasterServiceError as exc:
            if exc.code == "unauthorized":
                _mark_error(self._db, _EXPIRED)
                raise BingWebmasterServiceError(_EXPIRED, code="token_expired") from exc
            raise

    def list_sites(self) -> list[dict[str, Any]]:
        return self._call(client.list_sites)

    def crawl_stats(self, site_url: str) -> list[dict[str, Any]]:
        return self._call(client.crawl_stats, site_url)

    def crawl_issues(self, site_url: str) -> list[dict[str, Any]]:
        return self._call(client.crawl_issues, site_url)

    def feeds(self, site_url: str) -> list[dict[str, Any]]:
        return self._call(client.feeds, site_url)

    def traffic_stats(self, site_url: str) -> list[dict[str, Any]]:
        return self._call(client.traffic_stats, site_url)

    def query_stats(self, site_url: str) -> list[dict[str, Any]]:
        return self._call(client.query_stats, site_url)

    def page_stats(self, site_url: str) -> list[dict[str, Any]]:
        return self._call(client.page_stats, site_url)
