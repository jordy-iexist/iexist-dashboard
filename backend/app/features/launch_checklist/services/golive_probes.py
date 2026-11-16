"""Livegang (fase 5): een handvol extra verzoeken per scan.

- hostmatrix: http/https × www/apex, met redirects stap voor stap gevolgd zodat
  de keten en elke statuscode bewaard blijven (zoals `inventory.fetch_page`);
- certificaat: de https-variant van de klant-URL gaat via een geverifieerd
  verzoek; een certificaatfout komt als fout terug. HSTS alleen ter informatie;
- 404-probe: een willekeurig pad dat niet kan bestaan, met en zonder slash;
- favicon: hooguit twee `<link rel=icon>` van de homepage plus /favicon.ico.

Elke URL gaat eerst langs dezelfde SSRF-bescherming als de rest van de feature.
"""
from __future__ import annotations

import uuid
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from celery.exceptions import SoftTimeLimitExceeded

from app.core.url_guard import is_safe_external_url
from app.features.launch_checklist.services.discovery import USER_AGENT, clean_url
from app.features.launch_checklist.services.golive_extract import GoLiveSite

MAX_HOPS = 10
TIMEOUT_SECONDS = 15.0
MAX_FAVICON_LINKS = 2
# Statussen die op een blokkade van de scanner wijzen, niet op de site zelf.
BLOCKED_STATUSES = {401, 403, 429, 503}


def origin_of(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else None


def _connect_error(exc: Exception) -> tuple[str, bool]:
    """(melding, certificaatfout)."""
    text = str(exc)
    low = text.lower()
    if "certificate" in low or "ssl" in low or "tls" in low:
        reason = text.split("certificate verify failed:")[-1].strip(" )]") if "verify failed" in low else text
        return f"Certificaatfout: {reason[:200]}", True
    return f"Verbindingsfout: {exc.__class__.__name__}", False


def follow(client: httpx.Client, url: str, *, on_progress: Callable[[], Any] | None = None) -> dict[str, Any]:
    """Volg redirects met de hand. Keten: [{url, status, location}], plus eindadres en -status."""
    result: dict[str, Any] = {
        "start": url, "chain": [], "final_url": None, "final_status": None,
        "content_type": None, "hsts": None, "error": None, "cert_error": False,
    }
    current = url
    for _ in range(MAX_HOPS + 1):
        if not is_safe_external_url(current):
            result["error"] = "URL wijst naar een intern of ongeldig adres."
            return result
        try:
            response = client.get(current)
        except SoftTimeLimitExceeded:
            raise
        except httpx.TimeoutException:
            result["error"] = "Timeout"
            return result
        except httpx.HTTPError as exc:
            result["error"], result["cert_error"] = _connect_error(exc)
            return result
        finally:
            if on_progress is not None:
                on_progress()
        location = response.headers.get("location")
        if response.is_redirect and location:
            target = clean_url(location, current)
            result["chain"].append({"url": current, "status": response.status_code, "location": target})
            if not target or target == current:
                result["final_url"], result["final_status"] = current, response.status_code
                return result
            current = target
            continue
        result["final_url"] = str(response.url)
        result["final_status"] = response.status_code
        result["content_type"] = response.headers.get("content-type", "").split(";")[0].strip() or None
        result["hsts"] = response.headers.get("strict-transport-security")
        return result
    result["error"] = f"Meer dan {MAX_HOPS} redirects."
    return result


def host_matrix(client: httpx.Client, site: GoLiveSite, **kwargs: Any) -> list[dict[str, Any]]:
    """Alle varianten (http/https × www/apex, of alleen de host bij een subdomein)."""
    hosts = sorted(site.hosts, key=lambda h: (h.startswith("www."), h))
    variants = []
    for scheme in ("http", "https"):
        for host in hosts:
            variant = follow(client, f"{scheme}://{host}/", **kwargs)
            variant.update(scheme=scheme, host=host)
            variants.append(variant)
    return variants


def base_https_variant(variants: list[dict[str, Any]], site: GoLiveSite) -> dict[str, Any] | None:
    return next((v for v in variants if v["scheme"] == "https" and v["host"] == site.host), None)


def preferred_origin(variants: list[dict[str, Any]], site: GoLiveSite) -> str:
    """Eindadres van de https-variant van de klant-URL als die 200 geeft, anders https://<host>."""
    base = base_https_variant(variants, site)
    if base and base.get("final_status") == 200 and origin_of(base.get("final_url")):
        return origin_of(base["final_url"]) or f"https://{site.host}"
    return f"https://{site.host}"


def probe_not_found(client: httpx.Client, origin: str, **kwargs: Any) -> list[dict[str, Any]]:
    slug = f"/livegang-404-controle-{uuid.uuid4().hex[:12]}"
    return [follow(client, f"{origin}{slug}", **kwargs), follow(client, f"{origin}{slug}/", **kwargs)]


def _is_image(content_type: str | None) -> bool:
    ct = (content_type or "").lower()
    return ct.startswith("image/") or "icon" in ct


def probe_favicon(
    client: httpx.Client, origin: str, icon_links: list[str], **kwargs: Any
) -> list[dict[str, Any]]:
    candidates: list[str] = []
    for url in [*icon_links[:MAX_FAVICON_LINKS], f"{origin}/favicon.ico"]:
        if url and url.startswith(("http://", "https://")) and url not in candidates:
            candidates.append(url)
    out = []
    for url in candidates:
        result = follow(client, url, **kwargs)
        out.append({
            "url": url,
            "final_url": result["final_url"],
            "status": result["final_status"],
            "content_type": result["content_type"],
            "error": result["error"],
            "ok": result["final_status"] == 200 and _is_image(result["content_type"]),
        })
    return out


def new_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        follow_redirects=False,
        timeout=TIMEOUT_SECONDS,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
        transport=transport,
    )


def run_probes(
    site: GoLiveSite,
    *,
    icon_links: list[str] | None = None,
    on_progress: Callable[[], Any] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Alle probes van de livegangscan. `icon_links`: favicon-links van de homepage."""
    with new_client(transport) as client:
        variants = host_matrix(client, site, on_progress=on_progress)
        origin = preferred_origin(variants, site)
        return {
            "site": {"host": site.host, "hosts": sorted(site.hosts), "pair": site.has_host_pair},
            "variants": variants,
            "https": base_https_variant(variants, site),
            "origin": origin,
            "not_found": probe_not_found(client, origin, on_progress=on_progress),
            "favicon": probe_favicon(client, origin, icon_links or [], on_progress=on_progress),
        }
