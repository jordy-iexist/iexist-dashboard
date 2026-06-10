"""Eenvoudige fixed-window rate limiter op Redis (per IP)."""
import time

from fastapi import HTTPException, Request

from app.core.redis_client import get_redis


def enforce_rate_limit(
    request: Request,
    key: str,
    *,
    limit: int,
    window_seconds: int,
) -> None:
    client_ip = request.client.host if request.client else "unknown"
    window = int(time.time() // window_seconds)
    bucket = f"ratelimit:{key}:{client_ip}:{window}"

    try:
        redis_client = get_redis()
        count = redis_client.incr(bucket)
        if count == 1:
            redis_client.expire(bucket, window_seconds)
    except Exception:
        # Redis onbereikbaar: niet blokkeren, alleen geen rate limiting.
        return

    if int(count) > limit:
        raise HTTPException(
            status_code=429,
            detail="Te veel pogingen. Probeer het over een minuut opnieuw.",
        )


__all__ = ["enforce_rate_limit"]
