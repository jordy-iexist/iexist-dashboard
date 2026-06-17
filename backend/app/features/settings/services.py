from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.secrets import decrypt_secret, encrypt_secret
from app.db.models import UserAISettings
from app.db.session import SessionLocal


class MissingUserOpenAIKeyError(ValueError):
    def __init__(self, user_id: str):
        super().__init__(
            "Geen persoonlijke OpenAI API key ingesteld voor deze gebruiker."
        )
        self.user_id = user_id


def _normalize_user_id(user_id: str | None) -> str:
    return str(user_id or "").strip()


def get_user_ai_settings(user_id: str, db: Session) -> UserAISettings | None:
    normalized_user_id = _normalize_user_id(user_id)
    if not normalized_user_id:
        return None

    return (
        db.query(UserAISettings)
        .filter(UserAISettings.user_id == normalized_user_id)
        .first()
    )


def has_personal_openai_api_key(user_id: str, db: Session) -> bool:
    row = get_user_ai_settings(user_id, db)
    encrypted_key = str(row.encrypted_openai_api_key or "").strip() if row else ""
    return bool(encrypted_key)


def get_personal_openai_api_key(user_id: str, db: Session) -> str | None:
    row = get_user_ai_settings(user_id, db)
    encrypted_key = str(row.encrypted_openai_api_key or "").strip() if row else ""
    if not encrypted_key:
        return None

    return decrypt_secret(
        encrypted_key,
        invalid_message="Kon opgeslagen OpenAI API key niet ontsleutelen.",
    )


def require_personal_openai_api_key(user_id: str, db: Session) -> str:
    normalized_user_id = _normalize_user_id(user_id)
    if not normalized_user_id:
        raise MissingUserOpenAIKeyError(user_id="")

    api_key = get_personal_openai_api_key(normalized_user_id, db)
    if not api_key:
        raise MissingUserOpenAIKeyError(user_id=normalized_user_id)
    return api_key


def require_personal_openai_api_key_for_user(user_id: str) -> str:
    with SessionLocal() as db:
        return require_personal_openai_api_key(user_id, db)


def resolve_openai_api_key(user_id: str, db: Session) -> str:
    """Persoonlijke key eerst, anders fallback naar de gedeelde .env-key."""
    personal = get_personal_openai_api_key(_normalize_user_id(user_id), db)
    if personal:
        return personal
    fallback = str(settings.openai_api_key or "").strip()
    if fallback:
        return fallback
    raise MissingUserOpenAIKeyError(user_id=_normalize_user_id(user_id))


def resolve_openai_api_key_for_user(user_id: str) -> str:
    with SessionLocal() as db:
        return resolve_openai_api_key(user_id, db)


def upsert_personal_openai_api_key(
    user_id: str,
    openai_api_key: str | None,
    db: Session,
) -> UserAISettings:
    normalized_user_id = _normalize_user_id(user_id)
    if not normalized_user_id:
        raise ValueError("Gebruiker ontbreekt.")

    normalized_key = str(openai_api_key or "").strip()
    encrypted_key = encrypt_secret(normalized_key) if normalized_key else None
    now = datetime.now(timezone.utc)

    existing = get_user_ai_settings(normalized_user_id, db)
    if existing:
        existing.encrypted_openai_api_key = encrypted_key
        existing.updated_at = now
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    created = UserAISettings(
        id=str(uuid.uuid4()),
        user_id=normalized_user_id,
        encrypted_openai_api_key=encrypted_key,
        updated_at=now,
    )
    db.add(created)
    db.commit()
    db.refresh(created)
    return created


__all__ = [
    "MissingUserOpenAIKeyError",
    "get_personal_openai_api_key",
    "get_user_ai_settings",
    "has_personal_openai_api_key",
    "require_personal_openai_api_key",
    "require_personal_openai_api_key_for_user",
    "resolve_openai_api_key",
    "resolve_openai_api_key_for_user",
    "upsert_personal_openai_api_key",
]
