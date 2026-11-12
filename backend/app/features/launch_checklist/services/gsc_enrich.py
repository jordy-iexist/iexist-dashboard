"""Search Console-data voor een fase 4-scan.

Zoekt de property van de klant, haalt prestaties (klikken, vertoningen, CTR,
positie) op voor de meetperiode, de periode ervoor en dezelfde periode vorig
jaar, plus de sitemaps en de indexstatus van een beperkt aantal URL's. Het
resultaat (`LaunchScan.search_console`) is een JSON-snapshot; elke call faalt
los, zodat een ontbrekend onderdeel de rest niet tegenhoudt.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from app.core.config import settings
from app.services.search_console import client as gsc
from app.services.search_console.client import FATAL_CODES, SearchConsoleServiceError

DOMAIN_PREFIX = "sc-domain:"
# Zelfde weekdagen als de meetperiode, een jaar eerder.
YEAR_SHIFT_DAYS = 364

# pageFetchState → reden waarom Google de pagina niet kan opnemen.
_FETCH_PROBLEMS: dict[str, str] = {
    "NOT_FOUND": "pagina geeft 404",
    "SOFT_404": "soft 404",
    "SERVER_ERROR": "serverfout (5xx)",
    "ACCESS_DENIED": "toegang geweigerd (401)",
    "ACCESS_FORBIDDEN": "toegang geweigerd (403)",
    "BLOCKED_4XX": "4xx-fout",
    "REDIRECT_ERROR": "redirectfout",
    "BLOCKED_ROBOTS_TXT": "geblokkeerd door robots.txt",
}
_INDEXING_PROBLEMS: dict[str, str] = {
    "BLOCKED_BY_META_TAG": "noindex in de meta-tag",
    "BLOCKED_BY_HTTP_HEADER": "noindex in de HTTP-header",
    "BLOCKED_BY_ROBOTS_TXT": "geblokkeerd door robots.txt",
}


# --- property ------------------------------------------------------------------

def _bare(host: str) -> str:
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def match_properties(base_url: str, sites: list[dict[str, str]]) -> list[str]:
    """Properties die bij de site horen, beste eerst.

    Een domein-property van precies deze host gaat voor; daarna URL-prefix-
    properties van dezelfde host (https en gelijke www-variant eerst); als
    laatste een domein-property van een bovenliggend domein, omdat die ook het
    verkeer van andere subdomeinen bevat.
    """
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if not host:
        return []
    bare = _bare(host)
    ranked: list[tuple[int, str]] = []
    for site in sites:
        site_url = site.get("site_url") or ""
        if site_url.startswith(DOMAIN_PREFIX):
            domain = site_url[len(DOMAIN_PREFIX):].lower().strip(".")
            if bare == domain:
                ranked.append((0, site_url))
            elif bare.endswith("." + domain):
                ranked.append((9, site_url))
            continue
        prop = urlparse(site_url)
        prop_host = (prop.hostname or "").lower()
        if _bare(prop_host) != bare or (prop.path or "/") != "/":
            continue
        score = 1
        if prop_host != host:
            score += 2
        if prop.scheme != "https":
            score += 4
        ranked.append((score, site_url))
    return [site_url for _, site_url in sorted(ranked)]


def resolve_property(
    manual: str | None, base_url: str, sites: list[dict[str, str]]
) -> tuple[str | None, str | None]:
    """(property, bron). Bron is "manual" (gekozen bij de klant), "auto" of None."""
    chosen = (manual or "").strip()
    if chosen:
        return chosen, "manual"
    matches = match_properties(base_url, sites)
    return (matches[0], "auto") if matches else (None, None)


# --- periodes ------------------------------------------------------------------

def _span(start: date, end: date) -> dict[str, Any]:
    return {"start": start.isoformat(), "end": end.isoformat(), "days": (end - start).days + 1}


def periods(today: date | None = None) -> dict[str, tuple[date, date]]:
    """Meetperiode, de even lange periode ervoor en dezelfde periode vorig jaar."""
    today = today or datetime.now(timezone.utc).date()
    days = settings.gsc_period_days
    end = today - timedelta(days=settings.gsc_data_lag_days)
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    shift = timedelta(days=YEAR_SHIFT_DAYS)
    return {
        "current": (start, end),
        "previous": (prev_start, prev_end),
        "last_year": (start - shift, end - shift),
    }


# --- snapshot ------------------------------------------------------------------

def _metrics(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "clicks": int(round(row["clicks"])),
        "impressions": int(round(row["impressions"])),
        "ctr": round(row["ctr"], 4),
        "position": round(row["position"], 1),
    }


def _merge_rows(
    current: list[dict[str, Any]], previous: list[dict[str, Any]], row_limit: int
) -> list[dict[str, Any]]:
    """Rijen van nu en van de vorige periode naast elkaar, per sleutel.

    Staat een sleutel maar in één van beide lijsten en was die lijst afgekapt op
    `row_limit`, dan is de andere kant onbekend (None) in plaats van nul.
    """
    cur = {r["keys"][0]: r for r in current if r.get("keys")}
    prev = {r["keys"][0]: r for r in previous if r.get("keys")}
    cur_complete, prev_complete = len(current) < row_limit, len(previous) < row_limit
    empty = {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": None}
    rows: list[dict[str, Any]] = []
    for key in list(cur) + [k for k in prev if k not in cur]:
        now = _metrics(cur.get(key)) or (dict(empty) if cur_complete else None)
        before = _metrics(prev.get(key)) or (dict(empty) if prev_complete else None)
        rows.append({
            "key": key,
            **{name: (now or {}).get(name) for name in ("clicks", "impressions", "ctr", "position")},
            **{f"{name}_prev": (before or {}).get(name) for name in ("clicks", "impressions", "position")},
        })
    rows.sort(key=lambda r: (-(r["clicks"] or 0), -(r["impressions"] or 0), r["key"]))
    return rows


def fetch_snapshot(
    site_url: str,
    source: str | None,
    *,
    service: Any | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Prestaties en sitemaps van één property.

    Elke call faalt los (melding in `errors`); bij een fatale fout (geen
    koppeling, verlopen token, geen toegang) stopt de reeks.
    """
    spans = periods(today)
    snapshot: dict[str, Any] = {
        "property": site_url,
        "property_source": source,
        "period": _span(*spans["current"]),
        "previous": _span(*spans["previous"]),
        "last_year": _span(*spans["last_year"]),
        "totals": None,
        "totals_previous": None,
        "totals_last_year": None,
        "queries": [],
        "pages": [],
        "sitemaps": None,
        "inspection": None,
        "errors": [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    row_limit = settings.gsc_row_limit
    svc = service if service is not None else gsc.get_service()
    stopped = False

    def call(label: str, fn: Callable[[], Any]) -> Any:
        nonlocal stopped
        if stopped:
            return None
        try:
            return fn()
        except SearchConsoleServiceError as exc:
            snapshot["errors"].append(f"{label}: {exc}")
            stopped = exc.code in FATAL_CODES
            return None

    def totals(span: tuple[date, date]) -> dict[str, Any] | None:
        rows = gsc.search_analytics(site_url, *span, service=svc)
        return _metrics(rows[0]) if rows else {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": None}

    def by(dimension: str, span: tuple[date, date]) -> list[dict[str, Any]]:
        return gsc.search_analytics(site_url, *span, dimensions=(dimension,), row_limit=row_limit, service=svc)

    snapshot["totals"] = call("totalen", lambda: totals(spans["current"]))
    snapshot["totals_previous"] = call("totalen vorige periode", lambda: totals(spans["previous"]))
    snapshot["totals_last_year"] = call("totalen vorig jaar", lambda: totals(spans["last_year"]))
    for name, dimension, label in (("queries", "query", "zoekopdrachten"), ("pages", "page", "pagina's")):
        current = call(label, lambda d=dimension: by(d, spans["current"]))
        previous = call(f"{label} vorige periode", lambda d=dimension: by(d, spans["previous"]))
        if current is not None:
            snapshot[name] = _merge_rows(current, previous or [], row_limit)
            if previous is None:  # geen vergelijking: laat de vorige waarden leeg
                for row in snapshot[name]:
                    row.update(clicks_prev=None, impressions_prev=None, position_prev=None)
    snapshot["sitemaps"] = call("sitemaps", lambda: gsc.list_sitemaps(site_url, service=svc))
    return snapshot


def has_data(snapshot: dict[str, Any] | None) -> bool:
    """Of de snapshot genoeg bevat om mee te rekenen (totalen of sitemaps)."""
    return bool(snapshot) and (snapshot.get("totals") is not None or snapshot.get("sitemaps") is not None)


# --- URL-inspectie ---------------------------------------------------------------

def classify_inspection(row: dict[str, Any]) -> tuple[str, str]:
    """(staat, reden) van één inspectie.

    "indexed": opgenomen door Google. "blocked": niet opgenomen door iets op de
    site (robots.txt, noindex, foutstatus). "not_indexed": niet opgenomen zonder
    harde oorzaak (nog niet gecrawld, gecrawld maar niet geïndexeerd, duplicaat).
    """
    if row.get("verdict") == "PASS":
        return "indexed", str(row.get("coverage_state") or "geïndexeerd")
    if row.get("robots_txt_state") == "DISALLOWED":
        return "blocked", "geblokkeerd door robots.txt"
    reason = _INDEXING_PROBLEMS.get(str(row.get("indexing_state") or ""))
    reason = reason or _FETCH_PROBLEMS.get(str(row.get("page_fetch_state") or ""))
    if reason:
        return "blocked", reason
    return "not_indexed", str(row.get("coverage_state") or "niet geïndexeerd")


def inspect_pages(
    site_url: str,
    urls: list[str],
    *,
    service: Any | None = None,
    should_continue: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Indexstatus per URL. Stopt bij een fatale fout of een bereikt quotum."""
    svc = service if service is not None else gsc.get_service()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for url in urls:
        if should_continue is not None and not should_continue():
            break
        try:
            row = gsc.inspect_url(site_url, url, service=svc)
        except SearchConsoleServiceError as exc:
            errors.append(f"{url}: {exc}")
            if exc.code in FATAL_CODES or exc.code == "rate_limited":
                break
            continue
        row["state"], row["reason"] = classify_inspection(row)
        rows.append(row)
    return {
        "requested": len(urls),
        "checked": len(rows),
        "indexed": len([r for r in rows if r["state"] == "indexed"]),
        "rows": rows,
        "errors": errors[:10],
    }
