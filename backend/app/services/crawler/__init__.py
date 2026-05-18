from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse
import xml.etree.ElementTree as ET

import httpx

from app.features.seo_tracker.services import extract_hostname, to_root_domain

USER_AGENT = "WebCrawler/1.0"


@dataclass
class CrawlResult:
    urls: list[str]
    skipped_due_to_limit: int
    source: str  # "sitemap" | "crawl" | "none"


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value.strip())


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1].lower()
    return tag.lower()


def _normalize_path(path: str) -> str:
    normalized = str(path or "").strip()
    if not normalized:
        return "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    return normalized


def _normalize_url(raw_url: str) -> str | None:
    value = str(raw_url or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    normalized_path = _normalize_path(parsed.path or "/")
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


def _is_same_root_domain(candidate_url: str, root_domain: str) -> bool:
    try:
        hostname = extract_hostname(candidate_url)
        candidate_root = to_root_domain(hostname)
    except ValueError:
        return False
    return candidate_root == root_domain


def _dedupe_urls(urls: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped


def _fetch_url(url: str, timeout_seconds: float) -> httpx.Response | None:
    try:
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=timeout_seconds,
            headers={"User-Agent": USER_AGENT},
        )
    except Exception:
        return None

    if response.status_code >= 400:
        return None
    return response


def _url_path(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    return _normalize_path(parsed.path or "/")


def _path_allowed(
    path: str,
    include_paths: list[str],
    exclude_paths: list[str],
) -> bool:
    normalized = _normalize_path(path)

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


def _discover_from_sitemap(
    *,
    base_url: str,
    root_domain: str,
    include_paths: list[str],
    exclude_paths: list[str],
    timeout_seconds: float,
    max_sitemaps: int,
) -> list[str]:
    sitemap_urls = deque(
        [
            f"{base_url.rstrip('/')}/sitemap.xml",
            f"{base_url.rstrip('/')}/sitemap_index.xml",
        ]
    )
    visited_sitemaps: set[str] = set()
    discovered_pages: list[str] = []

    while sitemap_urls and len(visited_sitemaps) < max_sitemaps:
        sitemap_url = sitemap_urls.popleft()
        normalized_sitemap_url = _normalize_url(sitemap_url)
        if not normalized_sitemap_url:
            continue
        if normalized_sitemap_url in visited_sitemaps:
            continue
        visited_sitemaps.add(normalized_sitemap_url)

        response = _fetch_url(normalized_sitemap_url, timeout_seconds)
        if response is None:
            continue

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            continue

        root_tag = _local_name(root.tag)
        if root_tag == "sitemapindex":
            for sitemap_node in root.iter():
                if _local_name(sitemap_node.tag) != "sitemap":
                    continue
                for child in sitemap_node:
                    if _local_name(child.tag) != "loc":
                        continue
                    child_url = _normalize_url((child.text or "").strip())
                    if child_url:
                        sitemap_urls.append(child_url)
                    break
            continue

        if root_tag != "urlset":
            continue

        for url_node in root.iter():
            if _local_name(url_node.tag) != "url":
                continue
            loc_value = ""
            for child in url_node:
                if _local_name(child.tag) == "loc":
                    loc_value = (child.text or "").strip()
                    break
            normalized_page_url = _normalize_url(loc_value)
            if not normalized_page_url:
                continue
            if not _is_same_root_domain(normalized_page_url, root_domain):
                continue
            if not _path_allowed(
                _url_path(normalized_page_url),
                include_paths,
                exclude_paths,
            ):
                continue
            discovered_pages.append(normalized_page_url)

    return _dedupe_urls(discovered_pages)


def _discover_by_crawl(
    *,
    base_url: str,
    root_domain: str,
    include_paths: list[str],
    exclude_paths: list[str],
    timeout_seconds: float,
    crawl_max_depth: int,
    crawl_max_pages: int,
) -> list[str]:
    queue: deque[tuple[str, int]] = deque([(base_url, 0)])
    queued_urls: set[str] = {base_url}
    visited_urls: set[str] = set()
    discovered_pages: list[str] = []

    while queue and len(discovered_pages) < crawl_max_pages:
        current_url, depth = queue.popleft()
        if current_url in visited_urls:
            continue
        visited_urls.add(current_url)

        response = _fetch_url(current_url, timeout_seconds)
        if response is None:
            continue

        content_type = str(response.headers.get("content-type") or "").lower()
        if "text/html" not in content_type:
            continue

        final_url = _normalize_url(str(response.url))
        if not final_url:
            continue
        if not _is_same_root_domain(final_url, root_domain):
            continue

        final_path = _url_path(final_url)
        if _path_allowed(final_path, include_paths, exclude_paths):
            discovered_pages.append(final_url)

        if depth >= crawl_max_depth:
            continue

        parser = LinkParser()
        try:
            parser.feed(response.text)
        except Exception:
            continue

        for href in parser.links:
            raw_href = href.strip()
            if not raw_href:
                continue
            if raw_href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue

            absolute = urljoin(final_url, raw_href)
            normalized_candidate = _normalize_url(absolute)
            if not normalized_candidate:
                continue
            if not _is_same_root_domain(normalized_candidate, root_domain):
                continue
            if normalized_candidate in queued_urls:
                continue

            queued_urls.add(normalized_candidate)
            queue.append((normalized_candidate, depth + 1))

    return _dedupe_urls(discovered_pages)


def crawl_website_pages(
    *,
    base_url: str,
    max_pages: int,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    timeout_seconds: float = 15.0,
    crawl_max_depth: int = 2,
    crawl_max_pages: int = 200,
) -> CrawlResult:
    """Discover pages on a website via sitemap (preferred) or crawl fallback."""
    normalized_base_url = _normalize_url(base_url)
    if not normalized_base_url:
        raise ValueError("Website URL is ongeldig voor discovery.")

    resolved_include = include_paths or []
    resolved_exclude = exclude_paths or []
    root_domain = to_root_domain(normalized_base_url)

    pages = _discover_from_sitemap(
        base_url=normalized_base_url,
        root_domain=root_domain,
        include_paths=resolved_include,
        exclude_paths=resolved_exclude,
        timeout_seconds=timeout_seconds,
        max_sitemaps=20,
    )
    source = "sitemap"

    if not pages:
        pages = _discover_by_crawl(
            base_url=normalized_base_url,
            root_domain=root_domain,
            include_paths=resolved_include,
            exclude_paths=resolved_exclude,
            timeout_seconds=timeout_seconds,
            crawl_max_depth=max(0, crawl_max_depth),
            crawl_max_pages=max(1, crawl_max_pages),
        )
        source = "crawl"

    limited = pages[:max_pages]
    skipped_due_to_limit = max(0, len(pages) - len(limited))

    return CrawlResult(
        urls=limited,
        skipped_due_to_limit=skipped_due_to_limit,
        source=source if limited else "none",
    )


__all__ = ["CrawlResult", "crawl_website_pages"]
