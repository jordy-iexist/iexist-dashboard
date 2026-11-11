"""Site-inventaris (Screaming Frog-vervanger) met async httpx over HTTP/2."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from app.core.url_guard import is_safe_external_url
from app.features.launch_checklist.services.discovery import (
    USER_AGENT,
    clean_url,
    is_internal,
    root_domain_of,
    url_key,
)
from app.features.launch_checklist.services.html_extract import extract_page

MAX_REDIRECTS = 10
MAX_BODY_BYTES = 5_000_000
BATCH_SIZE = 20
MAX_BROKEN_LINK_CHECKS = 400
BROKEN_LINK_CONCURRENCY = 4
RATE_LIMIT_BACKOFF_SECONDS = 5
# Statussen die op blokkade/rate-limiting wijzen, niet op een kapotte link.
_INCONCLUSIVE_STATUSES = {401, 403, 429, 503}
_SKIP_LINK_PREFIXES = ("#", "mailto:", "tel:", "javascript:", "data:", "sms:", "whatsapp:")
_NON_PAGE_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif", ".ico",
    ".pdf", ".zip", ".mp4", ".mp3", ".webm", ".css", ".js", ".xml", ".json",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".woff", ".woff2",
)


@dataclass
class PageRecord:
    url: str
    path: str
    in_sitemap: bool
    status_code: int | None = None
    final_url: str | None = None
    redirect_chain: list[dict[str, Any]] = field(default_factory=list)
    response_time_ms: int | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    http_version: str | None = None
    indexable: bool | None = None
    indexability_reason: str | None = None
    meta_robots: str | None = None
    title: str | None = None
    title_length: int | None = None
    meta_description: str | None = None
    meta_description_length: int | None = None
    h1: list[str] = field(default_factory=list)
    h1_count: int | None = None
    h2: list[str] = field(default_factory=list)
    canonical: str | None = None
    word_count: int | None = None
    lang: str | None = None
    hreflang: list[dict[str, str]] = field(default_factory=list)
    internal_links: int | None = None
    external_links: int | None = None
    broken_links: list[dict[str, Any]] = field(default_factory=list)
    images_total: int | None = None
    images_missing_alt: int | None = None
    schema_types: list[str] = field(default_factory=list)
    open_graph: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    # Ahrefs-verrijking (services/ahrefs_enrich.py).
    org_traffic: int | None = None
    refdomains: int | None = None
    ahrefs: dict[str, Any] | None = None
    final_status: int | None = None
    # Niet opgeslagen: interne linkdoelen voor crawl + broken-link-check.
    internal_targets: list[str] = field(default_factory=list)

    @property
    def is_html(self) -> bool:
        return "html" in (self.content_type or "").lower()


def _path_of(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    return f"{path}?{parsed.query}" if parsed.query else path


def _looks_like_page(url: str) -> bool:
    return not urlparse(url).path.lower().endswith(_NON_PAGE_EXTENSIONS)


def _determine_indexability(rec: PageRecord, x_robots: str) -> None:
    if rec.status_code is None:
        rec.indexable, rec.indexability_reason = False, "Niet bereikbaar"
        return
    if 300 <= rec.status_code < 400:
        rec.indexable, rec.indexability_reason = False, f"Redirect ({rec.status_code})"
        return
    if rec.status_code != 200:
        rec.indexable, rec.indexability_reason = False, f"Statuscode {rec.status_code}"
        return
    if "noindex" in x_robots.lower():
        rec.indexable, rec.indexability_reason = False, "noindex (X-Robots-Tag)"
        return
    if not rec.is_html:
        rec.indexable, rec.indexability_reason = None, "Geen HTML"
        return
    if rec.meta_robots and "noindex" in rec.meta_robots.lower():
        rec.indexable, rec.indexability_reason = False, "noindex (meta robots)"
        return
    if rec.canonical:
        canonical_abs = clean_url(rec.canonical, rec.final_url or rec.url)
        if canonical_abs and url_key(canonical_abs) != url_key(rec.final_url or rec.url):
            rec.indexable, rec.indexability_reason = False, "Canonical naar andere URL"
            return
    rec.indexable, rec.indexability_reason = True, None


async def fetch_page(
    client: httpx.AsyncClient, url: str, *, in_sitemap: bool, root_domain: str
) -> PageRecord:
    rec = PageRecord(url=url, path=_path_of(url), in_sitemap=in_sitemap)
    current = url
    started = time.perf_counter()
    response: httpx.Response | None = None

    try:
        for _ in range(MAX_REDIRECTS + 1):
            if not is_safe_external_url(current):
                rec.error = "URL wijst naar een intern of ongeldig adres."
                break
            response = await client.get(current)
            if response.is_redirect and response.headers.get("location"):
                target = clean_url(response.headers["location"], current)
                rec.redirect_chain.append(
                    {"url": current, "status": response.status_code, "location": target}
                )
                if rec.status_code is None:
                    rec.status_code = response.status_code
                if not target or target == current:
                    break
                current = target
                continue
            break
        else:
            rec.error = "Te veel redirects."
    except httpx.TimeoutException:
        rec.error = "Timeout"
    except httpx.HTTPError as exc:
        rec.error = f"Verbindingsfout: {exc.__class__.__name__}"

    rec.response_time_ms = int((time.perf_counter() - started) * 1000)
    if response is None:
        _determine_indexability(rec, "")
        return rec

    if rec.status_code is None:
        rec.status_code = response.status_code
    rec.final_url = str(response.url)
    rec.http_version = response.http_version
    rec.content_type = response.headers.get("content-type", "").split(";")[0].strip() or None
    rec.size_bytes = len(response.content)

    final_status = response.status_code
    rec.final_status = final_status
    if rec.redirect_chain:
        rec.redirect_chain.append({"url": rec.final_url, "status": final_status, "final": True})
    if rec.is_html and final_status == 200 and not rec.redirect_chain:
        html = response.content[:MAX_BODY_BYTES].decode(
            response.encoding or "utf-8", errors="replace"
        )
        page = extract_page(html)
        rec.title = page.title
        rec.title_length = len(page.title) if page.title is not None else None
        rec.meta_description = page.meta_description
        rec.meta_description_length = (
            len(page.meta_description) if page.meta_description is not None else None
        )
        rec.meta_robots = page.meta_robots
        rec.canonical = page.canonical
        rec.lang = page.lang
        rec.hreflang = page.hreflang
        rec.h1 = page.h1
        rec.h1_count = len(page.h1)
        rec.h2 = page.h2[:30]
        rec.word_count = page.word_count
        rec.images_total = page.images_total
        rec.images_missing_alt = page.images_missing_alt
        rec.schema_types = page.schema_types
        rec.open_graph = page.open_graph

        internal: list[str] = []
        external = 0
        seen: set[str] = set()
        for href in page.links:
            if href.lower().startswith(_SKIP_LINK_PREFIXES):
                continue
            absolute = clean_url(href, rec.final_url)
            if not absolute:
                continue
            if is_internal(absolute, root_domain):
                key = url_key(absolute)
                if key not in seen:
                    seen.add(key)
                    internal.append(absolute)
            else:
                external += 1
        rec.internal_links = len(internal)
        rec.external_links = external
        rec.internal_targets = internal

    _determine_indexability(rec, response.headers.get("x-robots-tag", ""))
    return rec


def _new_client(concurrency: int, timeout_seconds: float, *, http2: bool = True) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        http2=http2,
        follow_redirects=False,
        timeout=timeout_seconds,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
        limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
    )


async def run_inventory(
    *,
    seed_urls: list[str],
    in_sitemap: bool,
    follow_links: bool,
    max_pages: int,
    concurrency: int,
    on_batch: Callable[[list[PageRecord]], bool],
    timeout_seconds: float = 20.0,
) -> list[PageRecord]:
    """Haal alle URL's op. Met follow_links=True wordt het een BFS-crawl.

    `on_batch` krijgt elke batch resultaten en geeft False terug om te stoppen
    (bijv. als de scan geannuleerd is).
    """
    if not seed_urls:
        return []
    root_domain = root_domain_of(seed_urls[0]) or ""
    queue: list[str] = list(seed_urls)
    queued: set[str] = {url_key(u) for u in seed_urls}
    records: list[PageRecord] = []
    sem = asyncio.Semaphore(concurrency)

    async with _new_client(concurrency, timeout_seconds) as client, _new_client(
        concurrency, timeout_seconds, http2=False
    ) as h1_client:

        async def _one(url: str) -> PageRecord:
            async with sem:
                rec = await fetch_page(client, url, in_sitemap=in_sitemap, root_domain=root_domain)
                if rec.final_status == 429:
                    await asyncio.sleep(RATE_LIMIT_BACKOFF_SECONDS)
                    rec = await fetch_page(client, url, in_sitemap=in_sitemap, root_domain=root_domain)
                # Sommige bot-protecties (o.a. Shopify) weigeren HTTP/2-clients
                # met een onbekende user-agent, maar staan HTTP/1.1 wel toe.
                if rec.final_status == 403 and (rec.http_version or "").upper() == "HTTP/2":
                    retry = await fetch_page(h1_client, url, in_sitemap=in_sitemap, root_domain=root_domain)
                    if retry.final_status != 403:
                        return retry
                return rec

        while queue and len(records) < max_pages:
            batch = queue[: min(BATCH_SIZE, max_pages - len(records))]
            queue = queue[len(batch):]
            results = await asyncio.gather(*(_one(u) for u in batch))
            records.extend(results)

            if follow_links:
                for rec in results:
                    targets = list(rec.internal_targets)
                    if rec.redirect_chain and rec.final_url and is_internal(rec.final_url, root_domain):
                        targets.insert(0, rec.final_url)
                    for target in targets:
                        key = url_key(target)
                        if key in queued or not _looks_like_page(target):
                            continue
                        queued.add(key)
                        queue.append(target)

            if not on_batch(list(results)):
                break

        # Timeouts kunnen door piekbelasting komen: één keer rustiger opnieuw.
        timed_out = [i for i, r in enumerate(records) if r.error == "Timeout"]
        if timed_out:
            retry_sem = asyncio.Semaphore(max(1, concurrency // 2))

            async def _retry(index: int) -> None:
                async with retry_sem:
                    old = records[index]
                    fresh = await fetch_page(
                        h1_client, old.url, in_sitemap=old.in_sitemap, root_domain=root_domain
                    )
                    if fresh.error != "Timeout":
                        records[index] = fresh

            await asyncio.gather(*(_retry(i) for i in timed_out))

        await _check_broken_links(h1_client, records)

    return records


def _is_broken(status: int | None) -> bool:
    return status is not None and status >= 400 and status not in _INCONCLUSIVE_STATUSES


async def _check_broken_links(client: httpx.AsyncClient, records: list[PageRecord]) -> None:
    """Markeer interne links die naar 4xx/5xx/onbereikbare doelen wijzen."""
    known: dict[str, int | None] = {}
    for rec in records:
        # Voor redirects telt de eindstatus van de keten.
        known[url_key(rec.url)] = None if rec.error else rec.final_status

    to_check: list[str] = []
    seen: set[str] = set()
    for rec in records:
        for target in rec.internal_targets:
            key = url_key(target)
            if key in known or key in seen or not _looks_like_page(target):
                continue
            seen.add(key)
            to_check.append(target)
    to_check = to_check[:MAX_BROKEN_LINK_CHECKS]

    sem = asyncio.Semaphore(BROKEN_LINK_CONCURRENCY)

    async def _request(url: str) -> int:
        resp = await client.head(url, follow_redirects=True)
        if resp.status_code in {405, 501}:
            resp = await client.get(url, follow_redirects=True)
        return resp.status_code

    async def _status(url: str) -> tuple[str, int | None]:
        if not is_safe_external_url(url):
            return url, None
        async with sem:
            try:
                status = await _request(url)
                if status == 429:
                    await asyncio.sleep(RATE_LIMIT_BACKOFF_SECONDS)
                    status = await _request(url)
                return url, status
            except httpx.HTTPError:
                return url, None

    for url, status in await asyncio.gather(*(_status(u) for u in to_check)):
        known[url_key(url)] = status

    for rec in records:
        broken: list[dict[str, Any]] = []
        for target in rec.internal_targets:
            key = url_key(target)
            if key not in known:
                continue
            status = known[key]
            if _is_broken(status):
                broken.append({"url": target, "status": status})
        rec.broken_links = broken[:50]
