from typing import Any
from urllib.parse import urlparse

from serpapi import GoogleSearch

from app.core.config import settings
from app.features.seo_tracker.services.domain_matching import matches_domain


class SerpApiServiceError(Exception):
    pass


def _results_depth() -> int:
    depth = int(settings.serpapi_results_depth)
    return max(1, min(depth, 100))


def _extract_error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    return "Onbekende SerpApi fout."


def _organic_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("organic_results")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _contains_target_domain(
    organic_results: list[dict[str, Any]],
    target_domain: str,
) -> bool:
    normalized_target = str(target_domain or "").strip().lower()
    if not normalized_target:
        return False

    for row in organic_results:
        link = row.get("link") or row.get("url")
        if not isinstance(link, str) or not link.strip():
            continue
        host = str(urlparse(link.strip()).hostname or "").strip().lower()
        if not host:
            continue
        if matches_domain(host, normalized_target):
            return True
    return False


def _base_params(keyword: str, *, api_key: str) -> dict[str, Any]:
    return {
        "engine": "google",
        "q": keyword,
        "location": "Netherlands",
        "api_key": api_key,
        "google_domain": "google.nl",
        "gl": "nl",
        "hl": "nl",
        "device": "desktop",
        # Force a fresh lookup per keyword so every scan is an actual SerpApi request.
        "no_cache": "true",
    }


def _run_google_search(search_params: dict[str, Any]) -> dict[str, Any]:
    request_params: dict[str, Any] = {
        **search_params,
    }

    try:
        payload = GoogleSearch(request_params).get_dict()
    except Exception as exc:
        raise SerpApiServiceError(f"Kon SerpApi niet bereiken: {exc}") from exc

    if not isinstance(payload, dict):
        raise SerpApiServiceError("SerpApi response heeft een ongeldig formaat.")

    search_metadata = payload.get("search_metadata")
    if not isinstance(search_metadata, dict):
        raise SerpApiServiceError(
            "SerpApi response mist search_metadata; ongeldige search response."
        )

    error_message = _extract_error_message(payload)
    if error_message != "Onbekende SerpApi fout.":
        raise SerpApiServiceError(f"SerpApi fout: {error_message}")

    return payload


def search_google_nl_desktop(
    keyword: str,
    *,
    target_domain: str | None = None,
) -> dict[str, Any]:
    api_key = settings.serpapi_api_key.strip()
    if not api_key:
        raise SerpApiServiceError("SERPAPI_API_KEY ontbreekt.")

    normalized_keyword = str(keyword or "").strip()
    if not normalized_keyword:
        raise SerpApiServiceError("Keyword ontbreekt voor SerpApi query.")

    desired_depth = _results_depth()
    normalized_target_domain = str(target_domain or "").strip().lower()

    first_payload = _run_google_search(
        {
            **_base_params(normalized_keyword, api_key=api_key),
            "start": 0,
            "num": min(desired_depth, 100),
        }
    )
    first_organic = _organic_results(first_payload)
    if normalized_target_domain and _contains_target_domain(
        first_organic,
        normalized_target_domain,
    ):
        merged_payload = dict(first_payload)
        merged_payload["organic_results"] = first_organic[:desired_depth]
        return merged_payload

    if desired_depth <= len(first_organic):
        merged_payload = dict(first_payload)
        merged_payload["organic_results"] = first_organic[:desired_depth]
        return merged_payload

    # Fallback pagination for cases where Google only returns ~10 organic results.
    combined_organic: list[dict[str, Any]] = []
    for index, row in enumerate(first_organic, start=1):
        normalized_row = dict(row)
        if not isinstance(normalized_row.get("position"), int):
            normalized_row["position"] = index
        combined_organic.append(normalized_row)

    next_start = max(len(first_organic), 10)
    max_pages = max(1, (desired_depth + 9) // 10)
    page_number = 1

    while len(combined_organic) < desired_depth and page_number < max_pages:
        remaining = desired_depth - len(combined_organic)
        page_payload = _run_google_search(
            {
                **_base_params(normalized_keyword, api_key=api_key),
                "start": next_start,
                "num": min(remaining, 10),
            }
        )
        page_organic = _organic_results(page_payload)
        if not page_organic:
            break

        found_target_domain = False
        for row_offset, row in enumerate(page_organic, start=1):
            normalized_row = dict(row)
            if not isinstance(normalized_row.get("position"), int):
                normalized_row["position"] = next_start + row_offset
            combined_organic.append(normalized_row)
            if normalized_target_domain and _contains_target_domain(
                [normalized_row],
                normalized_target_domain,
            ):
                found_target_domain = True
            if len(combined_organic) >= desired_depth:
                break

        if found_target_domain:
            break

        next_start += max(len(page_organic), 10)
        page_number += 1

    merged_payload = dict(first_payload)
    merged_payload["organic_results"] = combined_organic[:desired_depth]
    return merged_payload
