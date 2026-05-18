import base64
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import settings


class WordPressServiceError(Exception):
    def __init__(self, message: str, code: str = "wordpress_error"):
        super().__init__(message)
        self.code = code


@dataclass
class WordPressValidationResult:
    site_name: str | None
    normalized_base_url: str


@dataclass
class WordPressPostResult:
    post_id: str
    post_url: str


@dataclass
class WordPressMediaResult:
    media_id: str
    media_url: str


def normalize_wordpress_url(raw_url: str) -> str:
    cleaned_url = raw_url.strip()
    if not cleaned_url:
        raise WordPressServiceError("Site URL is verplicht.", code="invalid_url")

    if not cleaned_url.startswith(("http://", "https://")):
        cleaned_url = f"https://{cleaned_url}"

    parsed = urlparse(cleaned_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WordPressServiceError(
            "Site URL is ongeldig. Gebruik bijvoorbeeld https://voorbeeld.nl.",
            code="invalid_url",
        )
    if parsed.scheme != "https":
        raise WordPressServiceError(
            "Alleen https:// WordPress URLs zijn toegestaan.",
            code="invalid_url",
        )

    path = parsed.path.rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def _build_basic_auth_header(username: str, app_password: str) -> dict[str, str]:
    raw = f"{username}:{app_password}"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {encoded}"}


def _wordpress_rest_url(base_url: str, route: str) -> str:
    route_path = route.lstrip("/")
    return f"{base_url.rstrip('/')}/wp-json/{route_path}"


def _base_url_from_rest_response_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path.endswith("/wp-json"):
        path = path[: -len("/wp-json")]
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return response.text.strip() or "Onbekende WordPress fout."

    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

        error = payload.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()

    return "Onbekende WordPress fout."


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_payload: dict[str, object] | None = None,
    raw_payload: bytes | None = None,
    follow_redirects: bool = True,
) -> httpx.Response:
    timeout = settings.wordpress_request_timeout_seconds

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            return client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_payload,
                content=raw_payload,
                follow_redirects=follow_redirects,
            )
    except httpx.TimeoutException as exc:
        raise WordPressServiceError(
            "Timeout bij verbinden met WordPress site.",
            code="timeout",
        ) from exc
    except httpx.HTTPError as exc:
        raise WordPressServiceError(
            "Kon geen verbinding maken met WordPress site.",
            code="connection_error",
        ) from exc


def _request_with_auth_redirect(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_payload: dict[str, object] | None = None,
    raw_payload: bytes | None = None,
) -> httpx.Response:
    response = _request(
        method=method,
        url=url,
        headers=headers,
        json_payload=json_payload,
        raw_payload=raw_payload,
        follow_redirects=False,
    )
    if response.status_code not in {301, 302, 303, 307, 308}:
        return response

    location = response.headers.get("location")
    if not location:
        return response

    redirected_url = urljoin(url, location)
    redirected_method = "GET" if response.status_code == 303 else method
    redirected_payload = None if redirected_method == "GET" else json_payload
    redirected_raw_payload = None if redirected_method == "GET" else raw_payload

    return _request(
        method=redirected_method,
        url=redirected_url,
        headers=headers,
        json_payload=redirected_payload,
        raw_payload=redirected_raw_payload,
        follow_redirects=False,
    )


def validate_wordpress_credentials(
    base_url: str,
    username: str,
    app_password: str,
) -> WordPressValidationResult:
    normalized_url = normalize_wordpress_url(base_url)
    auth_headers = _build_basic_auth_header(username, app_password)

    rest_root_response = _request("GET", _wordpress_rest_url(normalized_url, ""))
    if rest_root_response.status_code >= 400:
        message = _extract_error_message(rest_root_response)
        raise WordPressServiceError(
            f"WordPress REST API niet bereikbaar: {message}",
            code="rest_api_unreachable",
        )
    resolved_base_url = _base_url_from_rest_response_url(str(rest_root_response.url))

    site_name: str | None = None
    try:
        root_payload = rest_root_response.json()
    except Exception:
        root_payload = None

    if isinstance(root_payload, dict):
        raw_name = root_payload.get("name")
        if isinstance(raw_name, str) and raw_name.strip():
            site_name = raw_name.strip()

    me_response = _request_with_auth_redirect(
        method="GET",
        url=_wordpress_rest_url(resolved_base_url, "wp/v2/users/me"),
        headers=auth_headers,
    )

    if me_response.status_code in {401, 403}:
        message = _extract_error_message(me_response)
        raise WordPressServiceError(
            f"Ongeldige WordPress login of wachtwoord: {message}",
            code="invalid_credentials",
        )

    if me_response.status_code >= 400:
        message = _extract_error_message(me_response)
        raise WordPressServiceError(
            f"WordPress validatie mislukt: {message}",
            code="validation_failed",
        )

    return WordPressValidationResult(
        site_name=site_name,
        normalized_base_url=resolved_base_url,
    )


def publish_post_to_wordpress(
    *,
    base_url: str,
    username: str,
    app_password: str,
    title: str,
    content: str,
    excerpt: str,
    post_status: str = "draft",
    featured_media: str | None = None,
) -> WordPressPostResult:
    normalized_url = normalize_wordpress_url(base_url)
    auth_headers = {
        **_build_basic_auth_header(username, app_password),
        "Content-Type": "application/json",
    }
    payload: dict[str, object] = {
        "title": title,
        "content": content,
        "excerpt": excerpt,
        "status": post_status,
    }
    if featured_media:
        try:
            payload["featured_media"] = int(featured_media)
        except ValueError:
            payload["featured_media"] = featured_media

    response = _request_with_auth_redirect(
        method="POST",
        url=_wordpress_rest_url(normalized_url, "wp/v2/posts"),
        headers=auth_headers,
        json_payload=payload,
    )

    if response.status_code in {401, 403}:
        message = _extract_error_message(response)
        raise WordPressServiceError(
            f"WordPress authenticatie mislukt bij publiceren: {message}",
            code="invalid_credentials",
        )

    if response.status_code >= 400:
        message = _extract_error_message(response)
        raise WordPressServiceError(
            f"WordPress publicatie mislukt: {message}",
            code="publish_failed",
        )

    payload = response.json()
    raw_post_id = payload.get("id")
    raw_post_url = payload.get("link")

    if raw_post_id is None:
        raise WordPressServiceError(
            "WordPress gaf geen post id terug.",
            code="invalid_response",
        )

    post_url = str(raw_post_url or "").strip()
    return WordPressPostResult(post_id=str(raw_post_id), post_url=post_url)


def upload_media_to_wordpress(
    *,
    base_url: str,
    username: str,
    app_password: str,
    filename: str,
    content: bytes,
    mime_type: str,
) -> WordPressMediaResult:
    normalized_url = normalize_wordpress_url(base_url)
    auth_headers = {
        **_build_basic_auth_header(username, app_password),
        "Content-Type": mime_type,
        "Content-Disposition": f'attachment; filename="{filename}"',
    }

    response = _request_with_auth_redirect(
        method="POST",
        url=_wordpress_rest_url(normalized_url, "wp/v2/media"),
        headers=auth_headers,
        raw_payload=content,
    )

    if response.status_code in {401, 403}:
        message = _extract_error_message(response)
        raise WordPressServiceError(
            f"WordPress authenticatie mislukt bij media upload: {message}",
            code="invalid_credentials",
        )

    if response.status_code >= 400:
        message = _extract_error_message(response)
        raise WordPressServiceError(
            f"WordPress media upload mislukt: {message}",
            code="media_upload_failed",
        )

    payload = response.json()
    raw_media_id = payload.get("id")
    raw_guid = payload.get("guid")
    raw_guid_rendered = raw_guid.get("rendered") if isinstance(raw_guid, dict) else None
    raw_media_url = payload.get("source_url") or raw_guid_rendered
    if raw_media_id is None:
        raise WordPressServiceError(
            "WordPress gaf geen media id terug.",
            code="invalid_response",
        )

    return WordPressMediaResult(
        media_id=str(raw_media_id),
        media_url=str(raw_media_url or "").strip(),
    )
