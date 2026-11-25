"""Search Console-inzichten van een klant, live uit Google (niets wordt opgeslagen).

Per klant: vier KPI's (klikken, vertoningen, CTR, positie) met de periode ervoor,
CTR-kansen (zoektermen die minder klikken krijgen dan hun positie doet verwachten),
zoektermen met vertoningen die nog niet in ProRankTracker gevolgd worden, en
pagina's waarvan de klikken dalen. Advies en mogelijke oorzaak komen uit vaste
regels, zonder AI. De rekenregels zijn pure functies; `customer_insights` haalt de
data op (parallel, één Search Console-service per thread) en bewaart het berekende
antwoord een uur in het geheugen.

Het antwoord heeft altijd een `state`:

- `ok`: de property is gevonden en de totalen zijn opgehaald. Mislukt een losse
  sectie, dan krijgt alleen die sectie `state: "unavailable"`;
- `not_configured`: GSC_CLIENT_ID, GSC_CLIENT_SECRET of GSC_REFRESH_TOKEN ontbreekt;
- `token_expired`: het refresh token is verlopen of ingetrokken;
- `no_property`: er is geen property gekozen en er hoort er geen bij het domein;
- `property_inaccessible`: het Google-account kan niet (meer) bij de gekozen property;
- `error`: Google gaf een andere fout (melding in `message`).
"""
from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Callable
from urllib.parse import urldefrag

import httpx

from app.core.config import settings
from app.core.dependencies import utc_now_iso
from app.features.customers.rankings import host_of, keyword_key, organic_rows
from app.features.launch_checklist.services.gsc_enrich import _merge_rows, _span, periods, resolve_property
from app.services.search_console import client as gsc
from app.services.search_console import sites as gsc_sites
from app.services.search_console.client import SearchConsoleServiceError

ALLOWED_DAYS = (7, 28, 90)

# Verwachte CTR per positie 1–20. Eigen, bewust voorzichtige schatting (geen cijfer van
# Google); tussen twee posities wordt lineair geïnterpoleerd, boven positie 20 geen waarde.
EXPECTED_CTR: tuple[float, ...] = (
    0.25, 0.13, 0.09, 0.065, 0.05, 0.04, 0.032, 0.026, 0.022, 0.019,
    0.014, 0.012, 0.010, 0.009, 0.008, 0.007, 0.006, 0.0055, 0.005, 0.0045,
)
# Een kans: de CTR is lager dan dit deel van de verwachte CTR.
OPPORTUNITY_CTR_RATIO = 0.6
OPPORTUNITIES_LIMIT = 100
DECLINING_LIMIT = 20
UNTRACKED_LIMIT = 20
UNTRACKED_MAX_POSITION = 30

# Drempels per 28 dagen met hun ondergrens; ze schalen mee met de periode (`threshold`).
THRESHOLDS: dict[str, tuple[int, int]] = {
    "opportunity_impressions": (200, 50),
    "opportunity_missed_clicks": (5, 2),
    "declining_prev_clicks": (10, 5),
    "declining_drop": (5, 3),
    "untracked_impressions": (50, 10),
}

# Merkzoektermen: een merkterm telt pas vanaf zoveel tekens (compacte vorm). Valt meer dan
# BRAND_STRICT_SHARE van de vertoningen onder de ruime regel, dan geldt de strikte regel.
BRAND_MIN_LENGTH = 4
BRAND_STRICT_SHARE = 0.5
# Rechtsvormen die niet bij de merknaam horen (compacte vorm, dus "B.V." = "bv").
LEGAL_FORMS = frozenset({
    "bv", "nv", "vof", "cv", "bvba", "vzw", "eenmanszaak", "maatschap",
    "gmbh", "ag", "ltd", "llc", "inc", "sarl", "sa",
})

# Rijen per Search Console-aanroep.
OPPORTUNITY_PAGE_SIZE = 25_000
OPPORTUNITY_MAX_ROWS = 50_000
PAGE_ROWS = 5_000
QUERY_ROWS = 5_000
WORKERS = 4
PRT_TIMEOUT_SECONDS = 10.0

CACHE_TTL_SECONDS = 3600.0
CACHE_MAX_ITEMS = 200

STATE_MESSAGES: dict[str, str] = {
    "not_configured": "Search Console is niet gekoppeld: GSC_CLIENT_ID, GSC_CLIENT_SECRET of GSC_REFRESH_TOKEN "
                      "ontbreekt in de backend-configuratie.",
    "token_expired": "Het Search Console-token is verlopen of ingetrokken. Draai scripts/gsc_authorize.py "
                     "opnieuw en zet het nieuwe GSC_REFRESH_TOKEN in de backend-configuratie.",
    "no_property": "Deze site staat niet in Search Console, of het Google-account van het bureau heeft er "
                   "geen toegang toe.",
    "property_inaccessible": "Het Google-account heeft geen toegang (meer) tot de gekozen property.",
}

ADVICE: dict[str, str] = {
    "improve_snippet_top": "Scherp de title en meta description aan en kijk of een uitgelicht fragment, "
                           "AI-overzicht of advertenties de klikken wegtrekken.",
    "improve_snippet": "Maak de title en meta description aantrekkelijker.",
    "improve_position": "Verbeter eerst de positie: onderaan pagina 1 of op pagina 2 wordt weinig geklikt.",
    "check_intent": "Veel vertoningen maar geen klikken: past de pagina bij de zoekintentie?",
}

UNTRACKED_MESSAGES: dict[str, str] = {
    "prt_not_tracked": "Deze site wordt nog niet gevolgd in ProRankTracker; dit zijn de zoektermen met de "
                       "meeste vertoningen.",
    "prt_not_configured": "ProRankTracker is niet gekoppeld (PRORANKTRACKER_API_X_TOKEN ontbreekt), dus er is "
                          "niet te zien welke zoektermen al gevolgd worden.",
}


# --- hulpfuncties ---------------------------------------------------------------------

def threshold(name: str, days: int) -> int:
    """Drempel voor een periode van `days` dagen: `max(ondergrens, ceil(x × days / 28))`."""
    per_28, floor = THRESHOLDS[name]
    return max(floor, -(-per_28 * days // 28))


def thresholds(days: int) -> dict[str, int]:
    return {name: threshold(name, days) for name in THRESHOLDS}


def expected_ctr(position: float | None) -> float | None:
    """Verwachte CTR bij een gemiddelde positie; onder 1 telt als 1, boven 20 geen waarde."""
    if position is None or position > len(EXPECTED_CTR):
        return None
    position = max(1.0, float(position))
    low = int(position)
    if low >= len(EXPECTED_CTR):
        return EXPECTED_CTR[-1]
    start, end = EXPECTED_CTR[low - 1], EXPECTED_CTR[low]
    return round(start + (end - start) * (position - low), 6)


def strip_fragment(url: Any) -> str:
    """URL zonder `#fragment` (bijv. `#:~:text=` uit een uitgelicht fragment)."""
    return urldefrag(str(url or "").strip())[0]


def compact(text: Any) -> str:
    """Kleine letters, alleen letters en cijfers: "Klant-Shop B.V." → "klantshopbv"."""
    return "".join(ch for ch in str(text or "").casefold() if ch.isalnum())


def round_potential(value: float) -> int | None:
    """Afronden voor de regel "geschat potentieel": onder 5 geen waarde, daarboven grover."""
    if value < 5:
        return None
    for limit, step in ((10, 1), (100, 5), (1000, 10)):
        if value < limit:
            return int(value / step + 0.5) * step
    return int(value / 100 + 0.5) * 100


def _decimal(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _weighted_position(parts: list[tuple[float | None, float]]) -> float | None:
    """Gemiddelde positie van meerdere rijen, gewogen naar vertoningen."""
    known = [(position, impressions) for position, impressions in parts if position is not None and impressions > 0]
    total = sum(impressions for _, impressions in known)
    if not total:
        return None
    return sum(position * impressions for position, impressions in known) / total


# --- merkzoektermen ---------------------------------------------------------------------

def brand_terms(name: Any, domain: Any) -> tuple[list[str], str]:
    """(merktermen, domein met TLD) in compacte vorm.

    Merktermen zijn het domeinlabel ("klant" uit "klant.nl") en de klantnaam zonder
    rechtsvorm, elk vanaf BRAND_MIN_LENGTH tekens.
    """
    host = str(domain or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    label = host.split(".")[0] if host else ""
    name_term = compact(" ".join(t for t in str(name or "").split() if compact(t) not in LEGAL_FORMS))
    terms = [t for t in dict.fromkeys((compact(label), name_term)) if len(t) >= BRAND_MIN_LENGTH]
    domain_term = compact(host)
    return terms, domain_term if "." in host and len(domain_term) >= BRAND_MIN_LENGTH else ""


def brand_matcher(
    name: Any, domain: Any, query_rows: list[dict[str, Any]]
) -> tuple[Callable[[str], bool], bool]:
    """(is_merkzoekterm, strikt).

    Ruim: de zoekterm bevat een merkterm of het domein. Valt meer dan de helft van de
    vertoningen in `query_rows` (rijen met de zoekterm als eerste sleutel) onder de ruime
    regel, dan is de merknaam waarschijnlijk een gewoon woord en geldt strikt: de zoekterm
    is precies een merkterm, of bevat het domein met TLD.
    """
    terms, domain_term = brand_terms(name, domain)
    contains = [*terms, domain_term] if domain_term else terms

    def broad(query: str) -> bool:
        text = compact(query)
        return any(term in text for term in contains)

    def strict(query: str) -> bool:
        text = compact(query)
        return text in terms or bool(domain_term and domain_term in text)

    if not contains:
        return (lambda _query: False), False
    total = brand = 0.0
    for row in query_rows:
        keys = row.get("keys") or []
        if not keys:
            continue
        impressions = float(row.get("impressions") or 0)
        total += impressions
        if broad(keys[0]):
            brand += impressions
    if total and brand / total > BRAND_STRICT_SHARE:
        return strict, True
    return broad, False


# --- CTR-kansen -------------------------------------------------------------------------

def advice(position: float, clicks: float, impressions: float, min_impressions: int) -> str:
    """Adviescode van een kans (zie ADVICE)."""
    if position > 10:
        return "improve_position"
    if clicks == 0 and impressions >= 2 * min_impressions:
        return "check_intent"
    if position <= 3:
        return "improve_snippet_top"
    return "improve_snippet"


def opportunities(
    rows: list[dict[str, Any]],
    days: int,
    *,
    is_brand: Callable[[str], bool] = lambda _query: False,
    truncated: bool = False,
) -> dict[str, Any]:
    """CTR-kansen uit rijen met de dimensies `query` en `page`.

    Per zoekterm telt alleen de pagina met de meeste vertoningen (`other_pages` telt de
    rest). Een kans staat op positie 1–20, heeft genoeg vertoningen, een CTR onder 60% van
    de verwachte CTR en genoeg gemiste klikken (vertoningen × verwacht − klikken).
    Merkzoektermen vallen af en worden geteld in `brand_excluded`. Gesorteerd op gemiste
    klikken; maximaal OPPORTUNITIES_LIMIT rijen, `total` is het aantal vóór het afkappen.
    """
    min_impressions = threshold("opportunity_impressions", days)
    min_missed = threshold("opportunity_missed_clicks", days)

    by_query: dict[str, tuple[str, dict[str, dict[str, Any]]]] = {}
    for row in rows:
        keys = row.get("keys") or []
        if len(keys) < 2:
            continue
        query, page = str(keys[0]).strip(), strip_fragment(keys[1])
        key = keyword_key(query)
        if not key or not page:
            continue
        pages = by_query.setdefault(key, (query, {}))[1]
        acc = pages.setdefault(page, {"clicks": 0.0, "impressions": 0.0, "parts": []})
        impressions = float(row.get("impressions") or 0)
        acc["clicks"] += float(row.get("clicks") or 0)
        acc["impressions"] += impressions
        acc["parts"].append((row.get("position"), impressions))

    found: list[dict[str, Any]] = []
    missed_total = 0.0
    brand_excluded = 0
    for query, pages in by_query.values():
        page, best = min(pages.items(), key=lambda item: (-item[1]["impressions"], -item[1]["clicks"], item[0]))
        impressions, clicks = best["impressions"], best["clicks"]
        position = _weighted_position(best["parts"])
        expected = expected_ctr(position)
        if expected is None or impressions < min_impressions:
            continue
        ctr = clicks / impressions
        missed = impressions * expected - clicks
        # Afronden voorkomt dat een grenswaarde door een floating-point-rest de verkeerde kant op valt.
        if round(ctr, 9) >= round(OPPORTUNITY_CTR_RATIO * expected, 9) or round(missed, 9) < min_missed:
            continue
        if is_brand(query):
            brand_excluded += 1
            continue
        missed_total += missed
        code = advice(position, clicks, impressions, min_impressions)
        found.append({
            "query": query,
            "page": page,
            "impressions": int(round(impressions)),
            "clicks": int(round(clicks)),
            "ctr": round(ctr, 4),
            "expected_ctr": round(expected, 4),
            "position": round(position, 1),
            "missed_clicks": int(round(missed)),
            "other_pages": len(pages) - 1,
            "advice_code": code,
            "advice": ADVICE[code],
            "_missed": missed,
        })
    found.sort(key=lambda r: (-r["_missed"], -r["impressions"], r["query"]))
    for row in found:
        del row["_missed"]
    return {
        "state": "ok",
        "message": None,
        "rows": found[:OPPORTUNITIES_LIMIT],
        "total": len(found),
        "potential_clicks_per_month": round_potential(missed_total * 30 / days),
        "brand_excluded": brand_excluded,
        "truncated": truncated,
        "min_impressions": min_impressions,
    }


# --- dalende pagina's -------------------------------------------------------------------

def _combine_pages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rijen van `_merge_rows` samengevoegd per URL zonder `#fragment`.

    Is een kant (nu of vorige periode) bij een van de rijen onbekend (None), dan is die
    kant van de samengevoegde rij ook onbekend.
    """
    combined: dict[str, dict[str, Any]] = {}
    for row in rows:
        page = strip_fragment(row.get("key"))
        if not page:
            continue
        acc = combined.get(page)
        if acc is None:
            combined[page] = {**row, "key": page}
            continue
        for suffix in ("", "_prev"):
            clicks, impressions, position = f"clicks{suffix}", f"impressions{suffix}", f"position{suffix}"
            if acc[clicks] is None or row[clicks] is None:
                acc[clicks] = acc[impressions] = acc[position] = None
                continue
            acc[position] = _weighted_position([(acc[position], acc[impressions]), (row[position], row[impressions])])
            acc[clicks] += row[clicks]
            acc[impressions] += row[impressions]
    return list(combined.values())


def decline_cause(
    impressions: int, impressions_prev: int, ctr: float, ctr_prev: float | None,
    position: float | None, position_prev: float | None,
) -> str:
    """Code van de mogelijke oorzaak; de eerste treffer wint.

    1. geen vertoningen meer; 2. positie minstens 1,0 slechter; 3. anders het grootste
    (meest negatieve) effect: minder vertoningen bij de oude CTR, of een lagere CTR bij
    de huidige vertoningen.
    """
    if not impressions:
        return "no_impressions"
    if position is not None and position_prev is not None and round(position - position_prev, 1) >= 1.0:
        return "position_drop"
    ctr_prev = ctr_prev or 0.0
    impressions_effect = (impressions - impressions_prev) * ctr_prev
    ctr_effect = impressions * (ctr - ctr_prev)
    return "less_demand" if impressions_effect <= ctr_effect else "lower_ctr"


def cause_text(code: str, position: float | None, position_prev: float | None) -> str:
    if code == "no_impressions":
        return "Geen vertoningen meer: verwijderd, omgeleid of uit de index?"
    if code == "position_drop":
        return f"Positie gedaald van {_decimal(position_prev or 0)} naar {_decimal(position or 0)}"
    if code == "less_demand":
        return "Minder vertoningen: minder zoekvraag"
    return "Lagere CTR: snippet of zoekresultaat veranderd"


def declining(
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]],
    days: int,
    *,
    row_limit: int = PAGE_ROWS,
    drop_pct: int | None = None,
) -> dict[str, Any]:
    """Pagina's met dalende klikken uit rijen met de dimensie `page` (nu en vorige periode).

    Een daler had genoeg klikken in de vorige periode, verloor er genoeg (absoluut) en
    minstens `drop_pct` procent (standaard GSC_CLICKS_DROP_WARN_PCT). Pagina's waarvan een
    kant onbekend is (lijst afgekapt) vallen af. Gesorteerd op absolute daling; maximaal
    DECLINING_LIMIT rijen, `total` is het aantal vóór het afkappen.
    """
    drop_pct = settings.gsc_clicks_drop_warn_pct if drop_pct is None else drop_pct
    min_prev = threshold("declining_prev_clicks", days)
    min_drop = threshold("declining_drop", days)
    found: list[dict[str, Any]] = []
    for row in _combine_pages(_merge_rows(current, previous, row_limit)):
        clicks, clicks_prev = row["clicks"], row["clicks_prev"]
        if clicks is None or clicks_prev is None:
            continue
        drop = clicks_prev - clicks
        if clicks_prev < min_prev or drop < min_drop or drop * 100 < drop_pct * clicks_prev:
            continue
        impressions, impressions_prev = row["impressions"], row["impressions_prev"]
        ctr = clicks / impressions if impressions else 0.0
        ctr_prev = clicks_prev / impressions_prev if impressions_prev else None
        position = round(row["position"], 1) if row["position"] is not None else None
        position_prev = round(row["position_prev"], 1) if row["position_prev"] is not None else None
        code = decline_cause(impressions, impressions_prev, ctr, ctr_prev, position, position_prev)
        found.append({
            "page": row["key"],
            "clicks": clicks,
            "clicks_prev": clicks_prev,
            "delta": clicks - clicks_prev,
            "pct": round(100 * (clicks - clicks_prev) / clicks_prev, 1),
            "impressions": impressions,
            "impressions_prev": impressions_prev,
            "ctr": round(ctr, 4),
            "ctr_prev": round(ctr_prev, 4) if ctr_prev is not None else None,
            "position": position,
            "position_prev": position_prev,
            "cause_code": code,
            "cause": cause_text(code, position, position_prev),
        })
    found.sort(key=lambda r: (r["delta"], r["page"]))
    return {"state": "ok", "message": None, "rows": found[:DECLINING_LIMIT], "total": len(found)}


# --- niet gevolgde zoektermen -----------------------------------------------------------

def untracked(
    query_rows: list[dict[str, Any]],
    days: int,
    prt_state: str,
    prt_rows: list[dict[str, Any]],
    prt_message: str | None = None,
) -> dict[str, Any]:
    """Zoektermen met genoeg vertoningen (positie ≤ 30) die niet in ProRankTracker staan.

    `prt_state` komt uit `rankings.organic_rows`. Staat de site niet in ProRankTracker,
    dan zijn het gewoon de topzoektermen (met een melding); zonder koppeling of bij een
    fout geen rijen, wel een melding. Gesorteerd op vertoningen; maximaal UNTRACKED_LIMIT.
    """
    if prt_state == "not_configured":
        return _untracked_section("prt_not_configured", UNTRACKED_MESSAGES["prt_not_configured"])
    if prt_state not in ("ok", "not_tracked"):
        return _untracked_section("prt_error", prt_message or "Zoekwoorden niet opgehaald uit ProRankTracker.")

    tracked = {keyword_key(r.get("name")) for r in prt_rows} - {""}
    min_impressions = threshold("untracked_impressions", days)
    seen: set[str] = set()
    found: list[dict[str, Any]] = []
    for row in query_rows:
        keys = row.get("keys") or []
        query = str(keys[0]).strip() if keys else ""
        key = keyword_key(query)
        if not key or key in tracked or key in seen:
            continue
        impressions, position = float(row.get("impressions") or 0), row.get("position")
        if impressions < min_impressions or position is None or position > UNTRACKED_MAX_POSITION:
            continue
        seen.add(key)
        found.append({
            "query": query,
            "impressions": int(round(impressions)),
            "clicks": int(round(float(row.get("clicks") or 0))),
            "position": round(float(position), 1),
        })
    found.sort(key=lambda r: (-r["impressions"], -r["clicks"], r["query"]))
    if prt_state == "not_tracked":
        section = _untracked_section("prt_not_tracked", UNTRACKED_MESSAGES["prt_not_tracked"])
    else:
        section = _untracked_section("ok", None)
        section["tracked_keywords"] = len(tracked)
    section.update(rows=found[:UNTRACKED_LIMIT], total=len(found))
    return section


def _untracked_section(state: str, message: str | None) -> dict[str, Any]:
    return {"state": state, "message": message, "rows": [], "total": 0, "tracked_keywords": 0}


# --- totalen ----------------------------------------------------------------------------

def totals_of(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """KPI's uit een aanroep zonder dimensies (bevat ook de geanonimiseerde zoekopdrachten)."""
    if not rows:
        return {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": None}
    row = rows[0]
    impressions = int(round(row["impressions"]))
    return {
        "clicks": int(round(row["clicks"])),
        "impressions": impressions,
        "ctr": round(row["ctr"], 4),
        "position": round(row["position"], 1) if impressions else None,
    }


# --- cache ------------------------------------------------------------------------------

_cache_lock = threading.Lock()
# sleutel → (verloopt op (monotonic), antwoord)
_cache: OrderedDict[tuple[Any, ...], tuple[float, dict[str, Any]]] = OrderedDict()


def _cache_get(key: tuple[Any, ...]) -> dict[str, Any] | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        if entry[0] <= time.monotonic():
            del _cache[key]
            return None
        _cache.move_to_end(key)
        return copy.deepcopy(entry[1])


def _cache_put(key: tuple[Any, ...], value: dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic() + CACHE_TTL_SECONDS, copy.deepcopy(value))
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX_ITEMS:
            _cache.popitem(last=False)


def clear_cache() -> None:
    """Vergeet alle bewaarde antwoorden (voor tests)."""
    with _cache_lock:
        _cache.clear()


def _cacheable(result: dict[str, Any]) -> bool:
    """Alleen een volledig antwoord: state ok, alle secties gelukt, ook PRT en de vorige periode."""
    if result["state"] != "ok" or result["totals_previous"] is None:
        return False
    if result["untracked"]["state"] == "prt_error":
        return False
    return all(result[name]["state"] != "unavailable" for name in ("opportunities", "untracked", "declining"))


# --- ophalen ----------------------------------------------------------------------------

def _empty(days: int, spans: dict[str, tuple[date, date]]) -> dict[str, Any]:
    return {
        "state": "error",
        "message": None,
        "days": days,
        "property": None,
        "property_source": None,
        "fetched_at": None,
        "period": _span(*spans["current"]),
        "previous": _span(*spans["previous"]),
        "totals": None,
        "totals_previous": None,
        "opportunities": None,
        "untracked": None,
        "declining": None,
    }


def _with_state(
    result: dict[str, Any], state: str, message: str | None = None,
    site_url: str | None = None, source: str | None = None,
) -> dict[str, Any]:
    result.update(state=state, message=message or STATE_MESSAGES.get(state), property=site_url,
                  property_source=source)
    return result


def _failed(result: dict[str, Any], exc: SearchConsoleServiceError, site_url: str | None = None,
            source: str | None = None) -> dict[str, Any]:
    if exc.code in ("not_configured", "token_expired"):
        return _with_state(result, exc.code, None, site_url, source)
    return _with_state(result, "error", str(exc), site_url, source)


def _prt_rows(base_url: str) -> tuple[str, list[dict[str, Any]], str | None]:
    """Gevolgde zoekwoorden uit ProRankTracker, met een korte timeout zodat het scherm niet wacht."""
    with httpx.Client(timeout=PRT_TIMEOUT_SECONDS) as client:
        return organic_rows(base_url, client=client)


def _fetch_all(site_url: str, spans: dict[str, tuple[date, date]], base_url: str) -> dict[str, Any]:
    """Alle aanroepen parallel; per naam het resultaat of de `SearchConsoleServiceError`.

    Elke thread maakt een eigen Search Console-service (die is niet thread-safe).
    """
    local = threading.local()
    current, previous = spans["current"], spans["previous"]

    def service() -> Any:
        if getattr(local, "service", None) is None:
            local.service = gsc.get_service()
        return local.service

    jobs: dict[str, Callable[[], Any]] = {
        # De grootste eerst: tot twee pagina's van 25.000 rijen.
        "query_page": lambda: gsc.search_analytics_all(
            site_url, *current, dimensions=("query", "page"), page_size=OPPORTUNITY_PAGE_SIZE,
            max_rows=OPPORTUNITY_MAX_ROWS, service=service(),
        ),
        "totals": lambda: gsc.search_analytics(site_url, *current, service=service()),
        "totals_previous": lambda: gsc.search_analytics(site_url, *previous, service=service()),
        "pages": lambda: gsc.search_analytics(
            site_url, *current, dimensions=("page",), row_limit=PAGE_ROWS, service=service()
        ),
        "pages_previous": lambda: gsc.search_analytics(
            site_url, *previous, dimensions=("page",), row_limit=PAGE_ROWS, service=service()
        ),
        "queries": lambda: gsc.search_analytics(
            site_url, *current, dimensions=("query",), row_limit=QUERY_ROWS, service=service()
        ),
        "prt": lambda: _prt_rows(base_url),
    }

    def run(job: Callable[[], Any]) -> Any:
        try:
            return job()
        except SearchConsoleServiceError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {name: pool.submit(run, job) for name, job in jobs.items()}
        return {name: future.result() for name, future in futures.items()}


def _unavailable(label: str, exc: SearchConsoleServiceError, **extra: Any) -> dict[str, Any]:
    return {"state": "unavailable", "message": f"{label} niet opgehaald: {exc}", "rows": [], "total": 0, **extra}


def _build(
    result: dict[str, Any], data: dict[str, Any], days: int, *, name: str, domain: str
) -> dict[str, Any]:
    """Het antwoord met `state: "ok"` uit de opgehaalde data (totalen zijn gelukt)."""
    result["totals"] = totals_of(data["totals"])
    previous = data["totals_previous"]
    result["totals_previous"] = None if isinstance(previous, Exception) else totals_of(previous)

    query_page, queries = data["query_page"], data["queries"]
    if isinstance(query_page, Exception):
        result["opportunities"] = _unavailable(
            "CTR-kansen", query_page, potential_clicks_per_month=None, brand_excluded=0, truncated=False,
            min_impressions=threshold("opportunity_impressions", days),
        )
    else:
        rows, truncated = query_page
        is_brand, _strict = brand_matcher(name, domain, rows if isinstance(queries, Exception) else queries)
        result["opportunities"] = opportunities(rows, days, is_brand=is_brand, truncated=truncated)

    if isinstance(queries, Exception):
        result["untracked"] = _unavailable("Zoektermen", queries, tracked_keywords=0)
    else:
        prt_state, prt_rows, prt_message = data["prt"]
        result["untracked"] = untracked(queries, days, prt_state, prt_rows, prt_message)

    pages, pages_previous = data["pages"], data["pages_previous"]
    failed = pages if isinstance(pages, Exception) else pages_previous
    if isinstance(failed, Exception):
        result["declining"] = _unavailable("Dalende pagina's", failed)
    else:
        result["declining"] = declining(pages, pages_previous, days)
    return result


def customer_insights(customer: Any, days: int, *, today: date | None = None) -> dict[str, Any]:
    """Search Console-inzichten voor één klant over de laatste `days` dagen (7, 28 of 90).

    `customer` is een `CustomerWebsite` (gebruikt: `gsc_property`, `base_url`, `name`,
    `domain`). Gooit geen fouten van Google of ProRankTracker; zie de toestanden bovenin.
    """
    if days not in ALLOWED_DAYS:
        raise ValueError(f"days moet een van {ALLOWED_DAYS} zijn.")
    base_url = str(customer.base_url or "")
    name = str(customer.name or "")
    domain = str(getattr(customer, "domain", None) or host_of(base_url))
    spans = periods(today, days)
    result = _empty(days, spans)

    if not gsc.is_configured():
        return _with_state(result, "not_configured")
    try:
        sites = gsc_sites.cached_sites()
    except SearchConsoleServiceError as exc:
        return _failed(result, exc)
    site_url, source = resolve_property(customer.gsc_property, base_url, sites)
    if not site_url:
        return _with_state(result, "no_property")

    retried = False
    while True:
        key = (site_url, days, spans["current"][1].isoformat(), host_of(base_url))
        cached = _cache_get(key)
        if cached is not None:
            return cached
        data = _fetch_all(site_url, spans, base_url)
        totals = data["totals"]
        if not isinstance(totals, SearchConsoleServiceError):
            break
        if totals.code not in ("forbidden", "not_found") or retried:
            return _failed(result, totals, site_url, source)
        # Geen toegang of niet gevonden: kijk met een verse lijst of de property er nog is.
        retried = True
        try:
            sites = gsc_sites.cached_sites(refresh=True)
        except SearchConsoleServiceError:
            return _failed(result, totals, site_url, source)
        if source == "manual":
            if site_url not in {site["site_url"] for site in sites}:
                return _with_state(result, "property_inaccessible", None, site_url, source)
            return _failed(result, totals, site_url, source)
        new_url, new_source = resolve_property(None, base_url, sites)
        if not new_url:
            return _with_state(result, "no_property")
        if new_url == site_url:
            return _failed(result, totals, site_url, source)
        site_url, source = new_url, new_source

    _with_state(result, "ok", None, site_url, source)
    result["fetched_at"] = utc_now_iso()
    result = _build(result, data, days, name=name, domain=domain)
    if _cacheable(result):
        _cache_put(key, result)
    return result


__all__ = [
    "ALLOWED_DAYS",
    "EXPECTED_CTR",
    "brand_matcher",
    "clear_cache",
    "customer_insights",
    "declining",
    "expected_ctr",
    "opportunities",
    "round_potential",
    "threshold",
    "thresholds",
    "totals_of",
    "untracked",
]
