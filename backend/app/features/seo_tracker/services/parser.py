from typing import Any
from urllib.parse import urlparse

from app.features.seo_tracker.services.domain_matching import matches_domain
from app.features.seo_tracker.services.types import SerpMatch


def _to_positive_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _organic_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("organic_results")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def find_first_domain_match(payload: dict[str, Any], target_domain: str) -> SerpMatch:
    for index, row in enumerate(_organic_results(payload), start=1):
        link = row.get("link") or row.get("url")
        if not isinstance(link, str) or not link.strip():
            continue
        normalized_link = link.strip()
        host = str(urlparse(normalized_link).hostname or "").strip().lower()
        if not host:
            continue
        if not matches_domain(host, target_domain):
            continue

        position = _to_positive_int(row.get("position")) or index
        return SerpMatch(
            position=position,
            result_url=normalized_link,
            matched_host=host,
        )

    return SerpMatch(
        position=None,
        result_url=None,
        matched_host=None,
    )
