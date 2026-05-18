import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from app.core.config import settings


def _storage_root() -> Path:
    return Path(settings.storage_root).resolve()


def _sign_value(value: str) -> str:
    return hmac.new(
        settings.storage_signing_secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _build_signed_url(bucket: str, path: str, ttl_seconds: int) -> str:
    expires = int(time.time()) + ttl_seconds
    payload = f"{bucket}:{path}:{expires}"
    signature = _sign_value(payload)
    base_url = settings.backend_public_url.rstrip("/")
    encoded_path = quote(path, safe="/")
    return (
        f"{base_url}/api/storage/{bucket}/{encoded_path}"
        f"?exp={expires}&sig={signature}"
    )


def verify_signed_request(bucket: str, path: str, expires: int, signature: str) -> bool:
    if expires < int(time.time()):
        return False
    expected = _sign_value(f"{bucket}:{path}:{expires}")
    return hmac.compare_digest(expected, signature)


@dataclass
class LocalBucketClient:
    bucket: str

    def _bucket_root(self) -> Path:
        root = _storage_root() / self.bucket
        root.mkdir(parents=True, exist_ok=True)
        return root

    def upload(self, path: str, content: bytes, file_options: dict | None = None) -> None:
        target = self._bucket_root() / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def download(self, path: str) -> bytes:
        target = self._bucket_root() / path
        return target.read_bytes()

    def create_signed_url(self, path: str, ttl_seconds: int) -> dict[str, str]:
        return {"signedURL": _build_signed_url(self.bucket, path, ttl_seconds)}


class LocalStorageClient:
    def list_buckets(self) -> list[dict[str, str]]:
        root = _storage_root()
        root.mkdir(parents=True, exist_ok=True)
        buckets: list[dict[str, str]] = []
        for child in root.iterdir():
            if child.is_dir():
                buckets.append({"id": child.name, "name": child.name})
        return buckets

    def create_bucket(self, bucket: str, options: dict | None = None) -> None:
        (_storage_root() / bucket).mkdir(parents=True, exist_ok=True)

    def from_(self, bucket: str) -> LocalBucketClient:
        return LocalBucketClient(bucket=bucket)


storage_client = LocalStorageClient()
