from urllib.parse import urlparse


def clamp_meta_page_limit(requested_limit: int | None, default_limit: int) -> int:
    if requested_limit is None:
        return max(1, min(default_limit, 500))
    return max(1, min(int(requested_limit), 500))


def normalize_path_filters(paths: object) -> list[str]:
    if not isinstance(paths, list):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in paths:
        raw = str(value or "").strip()
        if not raw:
            continue
        if not raw.startswith("/"):
            raw = f"/{raw}"
        if len(raw) > 1:
            raw = raw.rstrip("/")
        if raw in seen:
            continue
        seen.add(raw)
        normalized.append(raw)
    return normalized


def normalize_path(path: str) -> str:
    normalized = str(path or "").strip()
    if not normalized:
        return "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    return normalized


def url_path(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    return normalize_path(parsed.path or "/")


def path_allowed(path: str, include_paths: list[str], exclude_paths: list[str]) -> bool:
    normalized = normalize_path(path)

    if include_paths:
        include_match = any(
            normalized == prefix or normalized.startswith(f"{prefix}/")
            for prefix in include_paths
        )
        if not include_match:
            return False

    if exclude_paths:
        exclude_match = any(
            normalized == prefix or normalized.startswith(f"{prefix}/")
            for prefix in exclude_paths
        )
        if exclude_match:
            return False

    return True
