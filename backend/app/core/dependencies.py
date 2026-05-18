from contextvars import ContextVar
from datetime import datetime, timezone

from fastapi import Cookie, Header, HTTPException

from app.core.auth import decode_access_token

_request_user_id: ContextVar[str | None] = ContextVar("request_user_id", default=None)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_request_user_id() -> str | None:
    return _request_user_id.get()


def require_user_id(
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    access_token: str | None = Cookie(default=None),
) -> str:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_user_id and x_user_id.strip():
        token = x_user_id.strip()
    elif access_token and access_token.strip():
        token = access_token.strip()

    payload = decode_access_token(token) if token else None
    user_id = str((payload or {}).get("sub") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Ingelogde gebruiker ontbreekt.")
    _request_user_id.set(user_id)
    return user_id
