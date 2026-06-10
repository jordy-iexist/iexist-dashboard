from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse, urlunparse

import httpx

from app.core.url_guard import validate_external_url
from app.features.seo_meta.services.types import PageSnapshot
from app.features.seo_meta.services.validation import normalize_path

USER_AGENT = "SEO-Meta-Optimizer/1.0"


def _normalize_text(value: str | None) -> str | None:
    normalized = " ".join(unescape(str(value or "")).split()).strip()
    return normalized if normalized else None


def _normalize_url(raw_url: str) -> str:
    parsed = urlparse(str(raw_url or "").strip())
    normalized_path = normalize_path(parsed.path or "/")
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            normalized_path,
            "",
            "",
            "",
        )
    )


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self._in_h1 = False
        self._ignore_depth = 0
        self._title_parts: list[str] = []
        self._h1_parts: list[str] = []
        self._text_parts: list[str] = []
        self.description: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in {"script", "style", "noscript"}:
            self._ignore_depth += 1
            return

        if tag_lower == "title":
            self._in_title = True
            return
        if tag_lower == "h1":
            self._in_h1 = True
            return

        if tag_lower != "meta" or self.description is not None:
            return

        attr_map = {key.lower(): str(value or "") for key, value in attrs}
        meta_name = attr_map.get("name", "").strip().lower()
        if meta_name != "description":
            return
        content = _normalize_text(attr_map.get("content"))
        if content:
            self.description = content

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in {"script", "style", "noscript"} and self._ignore_depth > 0:
            self._ignore_depth -= 1
            return
        if tag_lower == "title":
            self._in_title = False
            return
        if tag_lower == "h1":
            self._in_h1 = False

    def handle_data(self, data: str) -> None:
        if self._ignore_depth > 0:
            return
        text = _normalize_text(data)
        if not text:
            return
        if self._in_title:
            self._title_parts.append(text)
            return
        if self._in_h1:
            self._h1_parts.append(text)
            return
        if len(self._text_parts) < 120:
            self._text_parts.append(text)

    @property
    def title(self) -> str | None:
        return _normalize_text(" ".join(self._title_parts))

    @property
    def h1(self) -> str | None:
        return _normalize_text(" ".join(self._h1_parts))

    @property
    def content_excerpt(self) -> str:
        excerpt = _normalize_text(" ".join(self._text_parts))
        if not excerpt:
            return ""
        if len(excerpt) <= 800:
            return excerpt
        return excerpt[:800].rsplit(" ", 1)[0].strip()


def fetch_page_snapshot(url: str, *, timeout_seconds: float) -> PageSnapshot:
    validate_external_url(url)
    response = httpx.get(
        url,
        follow_redirects=True,
        timeout=timeout_seconds,
        headers={"User-Agent": USER_AGENT},
    )
    if response.status_code >= 400:
        raise ValueError(f"Pagina gaf HTTP {response.status_code}.")

    content_type = str(response.headers.get("content-type") or "").lower()
    if "text/html" not in content_type:
        raise ValueError("Pagina is geen HTML.")

    final_url = _normalize_url(str(response.url))
    path = normalize_path(urlparse(final_url).path or "/")

    parser = MetadataParser()
    parser.feed(response.text)

    return PageSnapshot(
        url=final_url,
        path=path,
        title=parser.title,
        description=parser.description,
        h1=parser.h1,
        content_excerpt=parser.content_excerpt,
    )
