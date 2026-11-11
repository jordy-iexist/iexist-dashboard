"""Sitemap-discovery voor de nulmeting.

Anders dan `app.services.crawler` laten we URL's exact zoals ze in de sitemap
staan (trailing slash, query), zodat de inventaris geen valse redirects meldt.
"""
from __future__ import annotations

import gzip
import time
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse

import httpx

from app.core.url_guard import is_safe_external_url
from app.features.seo_tracker.services import extract_hostname, to_root_domain

USER_AGENT = "Mozilla/5.0 (compatible; iExistLaunchScan/1.0; +https://iexist.nl)"
DEFAULT_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml")


@dataclass
class DiscoveryResult:
    urls: list[str]
    sitemaps: list[str] = field(default_factory=list)
    robots_txt: str | None = None
    robots_status: int | None = None
    skipped_due_to_limit: int = 0


def clean_url(raw: str, base: str | None = None) -> str | None:
    """Absolute http(s)-URL zonder fragment; verder ongewijzigd."""
    value = str(raw or "").strip()
    if not value:
        return None
    if base:
        value = urljoin(base, value)
    value, _ = urldefrag(value)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower()).geturl()


def url_key(url: str) -> str:
    """Vergelijkingssleutel: zonder trailing slash, fragment en default host-casing."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.netloc.lower()}{path}{query}"


def root_domain_of(url: str) -> str | None:
    try:
        return to_root_domain(extract_hostname(url))
    except ValueError:
        return None


def is_internal(url: str, root_domain: str) -> bool:
    return root_domain_of(url) == root_domain


_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _is_plain_loc(tag: str) -> bool:
    """<loc> zonder namespace of in de standaard sitemap-namespace."""
    return tag == "loc" or tag == f"{{{_SITEMAP_NS}}}loc" or (
        tag.endswith("}loc") and "image" not in tag and "video" not in tag and "news" not in tag
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _fetch(client: httpx.Client, url: str) -> httpx.Response | None:
    if not is_safe_external_url(url):
        return None
    try:
        response = client.get(url)
        if response.status_code == 429:
            time.sleep(5)
            response = client.get(url)
        return response
    except Exception:
        return None


def _decode_sitemap(response: httpx.Response) -> str:
    content = response.content
    if content[:2] == b"\x1f\x8b":  # gzip (sitemap.xml.gz)
        try:
            content = gzip.decompress(content)
        except OSError:
            return ""
    return content.decode(response.encoding or "utf-8", errors="replace")


def parse_robots_sitemaps(robots_txt: str, base_url: str) -> list[str]:
    found: list[str] = []
    for line in robots_txt.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "sitemap" and value.strip():
            cleaned = clean_url(value.strip(), base_url)
            if cleaned and cleaned not in found:
                found.append(cleaned)
    return found


def discover_from_sitemaps(
    base_url: str,
    *,
    max_urls: int,
    timeout_seconds: float = 20.0,
    max_sitemaps: int = 50,
) -> DiscoveryResult:
    origin = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    root_domain = root_domain_of(base_url)
    result = DiscoveryResult(urls=[])

    with httpx.Client(
        follow_redirects=True,
        timeout=timeout_seconds,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        robots = _fetch(client, f"{origin}/robots.txt")
        if robots is not None:
            result.robots_status = robots.status_code
            if robots.status_code == 200 and "html" not in robots.headers.get("content-type", ""):
                result.robots_txt = robots.text[:200_000]

        candidates = parse_robots_sitemaps(result.robots_txt or "", origin)
        if not candidates:
            candidates = [f"{origin}{p}" for p in DEFAULT_SITEMAP_PATHS]

        queue: deque[str] = deque(candidates)
        visited: set[str] = set()
        seen_keys: set[str] = set()
        total_found = 0

        while queue and len(visited) < max_sitemaps:
            sitemap_url = queue.popleft()
            if sitemap_url in visited:
                continue
            visited.add(sitemap_url)

            response = _fetch(client, sitemap_url)
            if response is None or response.status_code != 200:
                continue
            try:
                root = ET.fromstring(_decode_sitemap(response))
            except ET.ParseError:
                continue

            root_tag = _local_name(root.tag)
            if root_tag == "sitemapindex":
                result.sitemaps.append(sitemap_url)
                for sitemap_node in root:
                    loc = next((c for c in sitemap_node if _is_plain_loc(c.tag)), None)
                    if loc is not None and loc.text:
                        child = clean_url(loc.text)
                        if child and child not in visited:
                            queue.append(child)
                continue
            if root_tag != "urlset":
                continue

            result.sitemaps.append(sitemap_url)
            for url_node in root:
                if _local_name(url_node.tag) != "url":
                    continue
                # Alleen de directe <loc>; <image:loc>/<video:loc> negeren.
                loc = next(
                    (c for c in url_node if _is_plain_loc(c.tag)),
                    None,
                )
                if loc is None or not loc.text:
                    continue
                page_url = clean_url(loc.text)
                if not page_url:
                    continue
                if root_domain and not is_internal(page_url, root_domain):
                    continue
                key = url_key(page_url)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                total_found += 1
                if len(result.urls) < max_urls:
                    result.urls.append(page_url)

    result.skipped_due_to_limit = max(0, total_found - len(result.urls))
    return result
