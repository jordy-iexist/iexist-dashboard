"""Properties van het Search Console-account, kort bewaard in het geheugen.

Het Google-account is voor alle klanten hetzelfde, dus de lijst (`sites.list`)
wordt gedeeld door de kwartaalpagina (property-kiezer) en de Search Console-
inzichten per klant. Na SITES_TTL_SECONDS wordt de lijst opnieuw opgehaald;
met `refresh=True` meteen (bijvoorbeeld na het kiezen van een property of bij
een 403 van Google). Thread-safe: endpoints draaien in de threadpool.
"""
from __future__ import annotations

import threading
import time

from app.services.search_console import client as gsc

SITES_TTL_SECONDS = 600.0

_lock = threading.Lock()
# (tijdstip, properties) van de laatste sites.list.
_cache: tuple[float, list[dict[str, str]]] | None = None


def cached_sites(*, refresh: bool = False) -> list[dict[str, str]]:
    """Properties met leesrechten (zie `client.list_sites`), uit de cache als die vers is.

    Gooit `SearchConsoleServiceError` als het ophalen mislukt; een fout wordt niet bewaard.
    """
    global _cache
    with _lock:
        cached = _cache
    if not refresh and cached is not None and time.monotonic() - cached[0] < SITES_TTL_SECONDS:
        return cached[1]
    sites = gsc.list_sites()
    with _lock:
        _cache = (time.monotonic(), sites)
    return sites


def clear_cache() -> None:
    """Vergeet de bewaarde lijst (voor tests)."""
    global _cache
    with _lock:
        _cache = None


__all__ = ["SITES_TTL_SECONDS", "cached_sites", "clear_cache"]
