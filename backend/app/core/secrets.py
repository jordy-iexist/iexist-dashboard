import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _build_fernet_key(secret: str) -> bytes:
    cleaned_secret = secret.strip()
    if not cleaned_secret:
        raise ValueError("WORDPRESS_CREDENTIALS_KEY mag niet leeg zijn.")

    encoded_secret = cleaned_secret.encode("utf-8")

    try:
        decoded = base64.urlsafe_b64decode(encoded_secret)
        if len(decoded) == 32:
            return encoded_secret
    except Exception:
        pass

    digest = hashlib.sha256(encoded_secret).digest()
    return base64.urlsafe_b64encode(digest)


def _resolve_secret() -> str:
    secret = settings.wordpress_credentials_key.strip()
    if not secret:
        raise ValueError("WORDPRESS_CREDENTIALS_KEY is verplicht en mag niet leeg zijn.")
    return secret


_fernet = Fernet(_build_fernet_key(_resolve_secret()))


def encrypt_secret(value: str) -> str:
    return _fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(
    value: str,
    *,
    invalid_message: str = "Kon opgeslagen secret niet ontsleutelen.",
) -> str:
    try:
        return _fernet.decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(invalid_message) from exc


__all__ = ["encrypt_secret", "decrypt_secret"]
