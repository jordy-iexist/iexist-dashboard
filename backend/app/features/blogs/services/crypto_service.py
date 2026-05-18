from app.core.secrets import decrypt_secret as decrypt_generic_secret
from app.core.secrets import encrypt_secret as encrypt_generic_secret


def encrypt_secret(value: str) -> str:
    return encrypt_generic_secret(value)


def decrypt_secret(value: str) -> str:
    return decrypt_generic_secret(
        value,
        invalid_message="Kon opgeslagen WordPress credentials niet ontsleutelen.",
    )
