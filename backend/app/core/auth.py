from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
import uuid
from typing import Any

import bcrypt
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models import User

LEGACY_PASSWORD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD_HASH_PREFIX = "bcrypt_sha256$"


def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def _normalize_password_bytes(password: str) -> bytes:
    # Pre-hash before bcrypt to avoid the 72-byte bcrypt input limit.
    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")


def _model_to_dict(obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}  # type: ignore[union-attr]


def hash_password(password: str) -> str:
    digest = _normalize_password_bytes(password)
    hashed = bcrypt.hashpw(digest, bcrypt.gensalt()).decode("utf-8")
    return f"{PASSWORD_HASH_PREFIX}{hashed}"


def verify_password(password: str, password_hash: str) -> bool:
    normalized_hash = str(password_hash or "").strip()
    if not normalized_hash:
        return False

    if normalized_hash.startswith(PASSWORD_HASH_PREFIX):
        digest = _normalize_password_bytes(password)
        stored_hash = normalized_hash[len(PASSWORD_HASH_PREFIX) :].encode("utf-8")
        return bcrypt.checkpw(digest, stored_hash)

    try:
        return LEGACY_PASSWORD_CONTEXT.verify(password, normalized_hash)
    except ValueError:
        return False


def create_access_token(*, user_id: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None
    return payload if isinstance(payload, dict) else None


def get_user_by_email(email: str) -> dict[str, Any] | None:
    normalized_email = normalize_email(email)
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == normalized_email).first()
        return _model_to_dict(user) if user is not None else None


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        return _model_to_dict(user) if user is not None else None


def create_user(email: str, password: str) -> dict[str, Any]:
    normalized_email = normalize_email(email)
    now = datetime.now(timezone.utc)
    user_id = str(uuid.uuid4())
    with SessionLocal() as db:
        user_obj = User(
            id=user_id,
            email=normalized_email,
            password_hash=hash_password(password),
            created_at=now,
            updated_at=now,
        )
        db.add(user_obj)
        db.commit()
        db.refresh(user_obj)
        return _model_to_dict(user_obj)


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    user = get_user_by_email(email)
    if not user:
        return None
    password_hash = str(user.get("password_hash") or "")
    if not password_hash or not verify_password(password, password_hash):
        return None
    return user


def to_public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(user["id"]),
        "email": str(user["email"]),
        "created_at": user.get("created_at"),
    }
