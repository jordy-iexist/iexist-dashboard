"""Bing Webmaster-data voor een fase 4-scan.

Zoekt de site van de klant in het Bing-account en haalt daar de indexcijfers,
crawlfouten, sitemaps, klikken en vertoningen op. Het resultaat
(`LaunchScan.bing_webmaster`) is een JSON-snapshot met altijd een `state`:

- `ok`: de site staat in het account en er is data opgehaald;
- `not_configured` / `not_connected`: er is geen (werkende) koppeling;
- `site_not_linked` / `site_not_verified`: de koppeling werkt, maar deze site
  staat niet (geverifieerd) in het account — het punt wordt dan handmatig gedaan;
- `error`: Bing gaf een fout.

Elke call faalt los, zodat een ontbrekend onderdeel de rest niet tegenhoudt.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from app.features.launch_checklist.services.gsc_enrich import _bare, _span, periods
from app.services.bing_webmaster.client import FATAL_CODES, BingWebmasterServiceError

MAX_ROWS = 250
MAX_CRAWL_ISSUES = 200
# Deze vlaggen zijn een probleem; 301 en 302 zijn gewone redirects.
PROBLEM_ISSUES = {
    "code_4xx", "code_5xx", "blocked_by_robots", "contains_malware",
    "important_blocked_by_robots", "dns_errors", "timeout_errors",
}
SEVERE_ISSUES = {"code_5xx", "contains_malware", "important_blocked_by_robots"}

STATE_MESSAGES: dict[str, str] = {
    "not_configured": "Bing Webmaster is niet geconfigureerd — voer deze controle handmatig uit in Bing Webmaster Tools.",
    "not_connected": "Bing Webmaster is niet gekoppeld — koppel het account bij fase 4 of voer deze controle handmatig uit.",
    "token_expired": "De Bing Webmaster-koppeling is verlopen — koppel opnieuw of voer deze controle handmatig uit.",
    "site_not_linked": "Site niet gekoppeld in Bing Webmaster Tools — voer deze controle handmatig uit.",
    "site_not_verified": "Site staat in Bing Webmaster Tools maar is niet geverifieerd — verifieer de site of voer "
                         "deze controle handmatig uit.",
}


# --- site --------------------------------------------------------------------------

def _ranked(base_url: str, sites: list[dict[str, Any]], *, verified: bool) -> list[str]:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if not host:
        return []
    ranked: list[tuple[int, str]] = []
    for site in sites:
        site_url = str(site.get("url") or "")
        if bool(site.get("verified")) != verified:
            continue
        prop = urlparse(site_url)
        prop_host = (prop.hostname or "").lower()
        if _bare(prop_host) != _bare(host) or (prop.path or "/") != "/":
            continue
        score = 0
        if prop_host != host:
            score += 2
        if prop.scheme != "https":
            score += 4
        ranked.append((score, site_url))
    return [site_url for _, site_url in sorted(ranked)]


def match_sites(base_url: str, sites: list[dict[str, Any]]) -> list[str]:
    """Geverifieerde sites in het Bing-account die bij de klant horen, beste eerst.

    Alleen dezelfde host (met of zonder www) telt: een hoofddomein in Bing dekt
    een subdomein-klant niet. Https en dezelfde www-variant gaan voor.
    """
    return _ranked(base_url, sites, verified=True)


def resolve_site(base_url: str, sites: list[dict[str, Any]]) -> tuple[str | None, str]:
    """(site, staat): "linked", "not_verified" (wel toegevoegd, niet geverifieerd) of "not_linked"."""
    matches = match_sites(base_url, sites)
    if matches:
        return matches[0], "linked"
    unverified = _ranked(base_url, sites, verified=False)
    if unverified:
        return unverified[0], "not_verified"
    return None, "not_linked"


# --- snapshot ------------------------------------------------------------------------

def empty_snapshot(state: str, *, message: str | None = None, mode: str | None = None) -> dict[str, Any]:
    return {
        "state": state,
        "message": message or STATE_MESSAGES.get(state),
        "auth_mode": mode,
        "site": None,
        "period": None,
        "previous": None,
        "totals": None,
        "totals_previous": None,
        "queries": [],
        "pages": [],
        "crawl": None,
        "crawl_issues": None,
        "sitemaps": None,
        "errors": [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _traffic_totals(rows: list[dict[str, Any]], span: tuple[date, date]) -> dict[str, Any] | None:
    """Som over de periode. None als de geschiedenis van Bing de periode niet dekt.

    Dagen zonder vertoningen ontbreken in de data: die tellen als nul, maar alleen
    als er data van vóór de periode is. Anders is de periode onbekend, niet nul.
    """
    if not rows or rows[0]["date"] > span[0]:
        return None
    inside = [r for r in rows if span[0] <= r["date"] <= span[1]]
    clicks = sum(r["clicks"] for r in inside)
    impressions = sum(r["impressions"] for r in inside)
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": round(clicks / impressions, 4) if impressions else 0.0,
    }


def _keyed_totals(rows: list[dict[str, Any]], span: tuple[date, date]) -> dict[str, dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not span[0] <= row["date"] <= span[1]:
            continue
        entry = totals.setdefault(row["key"], {"clicks": 0, "impressions": 0, "_weighted": 0.0, "_weight": 0})
        entry["clicks"] += row["clicks"]
        entry["impressions"] += row["impressions"]
        if row.get("position") is not None and row["impressions"]:
            entry["_weighted"] += row["position"] * row["impressions"]
            entry["_weight"] += row["impressions"]
    return totals


def _merge_keyed(rows: list[dict[str, Any]], spans: dict[str, tuple[date, date]]) -> list[dict[str, Any]]:
    """Zoekopdrachten of pagina's van de meetperiode naast de periode ervoor.

    Zelfde vorm als de Search Console-rijen, zodat vergelijking en weergave gelijk
    zijn. Dekt de geschiedenis de vorige periode niet, dan is die kant onbekend.
    """
    current = _keyed_totals(rows, spans["current"])
    covered = bool(rows) and min(r["date"] for r in rows) <= spans["previous"][0]
    previous = _keyed_totals(rows, spans["previous"]) if covered else {}

    def position(entry: dict[str, Any] | None) -> float | None:
        return round(entry["_weighted"] / entry["_weight"], 1) if entry and entry["_weight"] else None

    merged: list[dict[str, Any]] = []
    for key in list(current) + [k for k in previous if k not in current]:
        now, before = current.get(key), previous.get(key)
        clicks = now["clicks"] if now else 0
        impressions = now["impressions"] if now else 0
        merged.append({
            "key": key,
            "clicks": clicks,
            "impressions": impressions,
            "ctr": round(clicks / impressions, 4) if impressions else 0.0,
            "position": position(now),
            "clicks_prev": (before["clicks"] if before else 0) if covered else None,
            "impressions_prev": (before["impressions"] if before else 0) if covered else None,
            "position_prev": position(before),
        })
    merged.sort(key=lambda r: (-r["clicks"], -r["impressions"], r["key"]))
    return merged[:MAX_ROWS]


def _crawl_summary(rows: list[dict[str, Any]], spans: dict[str, tuple[date, date]]) -> dict[str, Any] | None:
    """Laatste stand van index en crawl, plus de stand aan het begin van de meetperiode."""
    if not rows:
        return None
    latest = rows[-1]
    start = spans["current"][0]
    before = [r for r in rows if r["date"] <= start]
    return {
        **{k: v for k, v in latest.items() if k not in {"date", "crawled_pages"}},
        "date": latest["date"].isoformat(),
        # Gecrawlde pagina's zijn per dag: optellen over de meetperiode.
        "crawled_pages": sum(r["crawled_pages"] for r in rows if r["date"] >= start),
        "in_index_before": before[-1]["in_index"] if before else None,
        "in_index_before_date": before[-1]["date"].isoformat() if before else None,
    }


def fetch_snapshot(site_url: str, session: Any, *, today: date | None = None) -> dict[str, Any]:
    """Index, crawlfouten, sitemaps en prestaties van één site.

    `session` is een `BingSession` (of in tests iets met dezelfde methodes). Elke
    call faalt los (melding in `errors`); bij een fatale fout stopt de reeks.
    """
    spans = periods(today)
    snapshot = empty_snapshot("ok")
    snapshot.update(
        message=None,
        site=site_url,
        period=_span(*spans["current"]),
        previous=_span(*spans["previous"]),
    )
    stopped = False

    def call(label: str, fn: Callable[[], Any]) -> Any:
        nonlocal stopped
        if stopped:
            return None
        try:
            return fn()
        except BingWebmasterServiceError as exc:
            snapshot["errors"].append(f"{label}: {exc}")
            if exc.code in FATAL_CODES:
                stopped = True
                snapshot["state"] = "token_expired" if exc.code == "token_expired" else "error"
                snapshot["message"] = STATE_MESSAGES.get(snapshot["state"]) or str(exc)
            return None

    crawl = call("crawlstatistieken", lambda: session.crawl_stats(site_url))
    if crawl is not None:
        snapshot["crawl"] = _crawl_summary(crawl, spans)
    issues = call("crawlfouten", lambda: session.crawl_issues(site_url))
    if issues is not None:
        problems = [
            {**row, "severe": any(i["key"] in SEVERE_ISSUES for i in row["issues"])}
            for row in issues
            if any(i["key"] in PROBLEM_ISSUES for i in row["issues"])
        ]
        problems.sort(key=lambda r: (not r["severe"], -(r.get("in_links") or 0), r["url"]))
        snapshot["crawl_issues"] = {"total": len(problems), "rows": problems[:MAX_CRAWL_ISSUES]}
    snapshot["sitemaps"] = call("sitemaps", lambda: session.feeds(site_url))
    traffic = call("klikken en vertoningen", lambda: session.traffic_stats(site_url))
    if traffic is not None:
        snapshot["totals"] = _traffic_totals(traffic, spans["current"])
        snapshot["totals_previous"] = _traffic_totals(traffic, spans["previous"])
        if snapshot["totals"] is None and traffic:
            # Geschiedenis begint binnen de meetperiode (nieuwe site): toon wat er is.
            snapshot["totals"] = _traffic_totals(traffic, (traffic[0]["date"], spans["current"][1]))
    for name, label, method in (
        ("queries", "zoekopdrachten", "query_stats"),
        ("pages", "pagina's", "page_stats"),
    ):
        rows = call(label, lambda m=method: getattr(session, m)(site_url))
        if rows is not None:
            snapshot[name] = _merge_keyed(rows, spans)
    return snapshot


def has_data(snapshot: dict[str, Any] | None) -> bool:
    """Of Bing voor deze site al iets heeft: indexcijfers, sitemaps of verkeer."""
    if not snapshot or snapshot.get("state") != "ok":
        return False
    return (
        snapshot.get("crawl") is not None
        or bool(snapshot.get("sitemaps"))
        or snapshot.get("totals") is not None
    )


def collect(base_url: str, session_factory: Callable[[], Any], *, today: date | None = None) -> dict[str, Any]:
    """Snapshot voor één klant, inclusief de gevallen zonder koppeling of zonder site.

    `session_factory` levert een `BingSession`; hij wordt pas aangeroepen als er
    iets op te halen valt. Deze functie gooit geen `BingWebmasterServiceError`.
    """
    try:
        session = session_factory()
        mode = session.mode
        sites = session.list_sites()
    except BingWebmasterServiceError as exc:
        state = exc.code if exc.code in {"not_configured", "not_connected", "token_expired"} else "error"
        snapshot = empty_snapshot(state, message=STATE_MESSAGES.get(state) or str(exc))
        if state == "error":
            snapshot["errors"].append(str(exc))
        return snapshot
    site_url, site_state = resolve_site(base_url, sites)
    if site_state != "linked":
        snapshot = empty_snapshot(f"site_{site_state}", mode=mode)
        snapshot["site"] = site_url
        return snapshot
    snapshot = fetch_snapshot(site_url, session, today=today)
    snapshot["auth_mode"] = mode
    return snapshot
