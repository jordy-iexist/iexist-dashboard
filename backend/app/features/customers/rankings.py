"""Zoekwoordposities van een klant, live uit ProRankTracker (niets wordt opgeslagen).

Haalt alle gevolgde zoekwoorden van de site op (`reports/overview`) en vat ze samen
voor het klantdashboard: gemiddelde positie, top 3 en de verschillen met een maand
geleden. Alleen organische zoekwoorden tellen mee; AI-termen vallen af. De quick wins
combineren Ahrefs met dezelfde organische rijen (`organic_rows`, zie `quick_wins.py`).

Het antwoord heeft altijd een `state`:

- `ok`: de site wordt gevolgd en de posities zijn opgehaald;
- `not_configured`: er staat geen API-token in de configuratie;
- `not_tracked`: de koppeling werkt, maar er worden geen zoekwoorden voor deze site gevolgd;
- `error`: ProRankTracker gaf een fout.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.dependencies import utc_now_iso
from app.features.launch_checklist.services.ahrefs_enrich import target_of
from app.services.proranktracker import client as prt
from app.services.proranktracker.client import ProRankTrackerServiceError

MAX_POSITION = 100
# Maximaal aantal contentkansen (gevolgd, geen positie, wel zoekvolume) in het antwoord.
CONTENT_GAPS_LIMIT = 5

STATE_MESSAGES: dict[str, str] = {
    "not_configured": "ProRankTracker is niet gekoppeld: PRORANKTRACKER_API_X_TOKEN ontbreekt in de "
                      "backend-configuratie.",
    "not_tracked": "Deze site staat niet in ProRankTracker: er worden geen zoekwoorden voor gevolgd. "
                   "Voeg de site en zoekwoorden toe in ProRankTracker om de posities te zien.",
}


# --- hulpfuncties ---------------------------------------------------------------------

def host_of(base_url: Any) -> str:
    """Host zonder schema en zonder `www.`, ook voor een URL zonder schema."""
    text = str(base_url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"http://{text}"
    return target_of(text)


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def position(value: Any) -> int | None:
    """Positie 1–100; "NTH" (niet in de top 100), leeg of een andere waarde wordt `None`."""
    rank = _int(value)
    if rank is None or rank <= 0 or rank > MAX_POSITION:
        return None
    return rank


def keyword_key(keyword: Any) -> str:
    """Sleutel voor "hetzelfde zoekwoord": `casefold()` en samengevoegde witruimte."""
    return " ".join(str(keyword or "").split()).casefold()


def is_organic(row: dict[str, Any]) -> bool:
    """Alleen gewone organische zoekwoorden; AI-termen tellen niet mee."""
    term_type = str(row.get("term_type") or "").strip().lower()
    return term_type == "organic" and _int(row.get("is_ai_term")) == 0


def _avg(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


# --- samenvatting ----------------------------------------------------------------------

def empty_summary(state: str, message: str | None = None) -> dict[str, Any]:
    return {
        "state": state,
        "message": message or STATE_MESSAGES.get(state),
        "fetched_at": utc_now_iso() if state in ("ok", "not_tracked") else None,
        "keywords": 0,
        "ranked": 0,
        "avg_position": None,
        "avg_position_delta": None,
        "top3": 0,
        "top3_delta": None,
        "content_gaps": [],
        "content_gaps_total": 0,
    }


def content_gaps(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Gevolgde zoekwoorden zonder positie in de top 100 maar met zoekvolume: `(top, totaal)`.

    Een zoekwoord dat meerdere keren gevolgd wordt (andere zoekmachine of locatie) telt alleen
    als geen van zijn rijen een positie heeft; dan geldt het hoogste volume van die rijen.
    Gesorteerd op volume aflopend, daarna zoekwoord; maximaal CONTENT_GAPS_LIMIT rijen.
    """
    ranked: set[str] = set()
    gaps: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = keyword_key(row.get("name"))
        if not key:
            continue
        if position(row.get("rank")) is not None:
            ranked.add(key)
            continue
        volume = _int(row.get("localmonthlysearches"))
        if volume is None or volume <= 0:
            continue
        if key not in gaps or volume > gaps[key]["volume"]:
            gaps[key] = {"keyword": str(row.get("name")).strip(), "volume": volume}
    found = [gap for key, gap in gaps.items() if key not in ranked]
    found.sort(key=lambda gap: (-gap["volume"], keyword_key(gap["keyword"])))
    return found[:CONTENT_GAPS_LIMIT], len(found)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Samenvatting van de organische rijen (al gefilterd) met `state = "ok"`."""
    ranks = [(position(r.get("rank")), position(r.get("monthagorank"))) for r in rows]
    now = [rank for rank, _ in ranks if rank is not None]
    both = [(rank, month) for rank, month in ranks if rank is not None and month is not None]

    avg_delta = None
    if both:
        avg_delta = round(sum(m for _, m in both) / len(both) - sum(r for r, _ in both) / len(both), 1)

    top3 = sum(1 for rank in now if rank <= 3)
    top3_delta = None
    if any("monthagorank" in r for r in rows):
        top3_delta = top3 - sum(1 for _, month in ranks if month is not None and month <= 3)

    gaps, gaps_total = content_gaps(rows)
    summary = empty_summary("ok")
    summary.update({
        "content_gaps": gaps,
        "content_gaps_total": gaps_total,
        "keywords": len(rows),
        "ranked": len(now),
        "avg_position": _avg(now),
        "avg_position_delta": avg_delta,
        "top3": top3,
        "top3_delta": top3_delta,
    })
    return summary


# --- ophalen ---------------------------------------------------------------------------

UNEXPECTED_MESSAGE = "Onverwacht antwoord van ProRankTracker."


def organic_rows(
    base_url: str, *, client: httpx.Client | None = None
) -> tuple[str, list[dict[str, Any]], str | None]:
    """De organische zoekwoordrijen van één site als `(state, rijen, melding)`.

    `state` is `ok` (met rijen), `not_configured`, `not_tracked` (geen host of geen organische
    zoekwoorden) of `error` (met melding). Eerst op de host zonder `www.`; levert dat geen
    organische zoekwoorden op, dan één keer met `www.` ervoor. Gooit geen fouten van
    ProRankTracker; `client` is alleen voor tests. Gebruikt door de rankings en de quick wins.
    """
    if not prt.is_configured():
        return "not_configured", [], None
    host = host_of(base_url)
    if not host:
        return "not_tracked", [], None
    try:
        rows = [r for r in prt.rank_overview(host, client=client) if is_organic(r)]
        if not rows:
            rows = [r for r in prt.rank_overview(f"www.{host}", client=client) if is_organic(r)]
    except ProRankTrackerServiceError as exc:
        if exc.code == "not_configured":
            return "not_configured", [], None
        return "error", [], f"Posities niet opgehaald uit ProRankTracker: {exc}"
    except (AttributeError, KeyError, TypeError, ValueError):  # onverwachte vorm van het antwoord
        return "error", [], UNEXPECTED_MESSAGE
    if not rows:
        return "not_tracked", [], None
    return "ok", rows, None


def customer_rankings(base_url: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """Samenvatting voor één klant, inclusief de gevallen zonder token of zonder tracking.

    De rijen komen uit `organic_rows`. Deze functie gooit geen fouten van ProRankTracker;
    `client` is alleen voor tests.
    """
    state, rows, message = organic_rows(base_url, client=client)
    if state != "ok":
        return empty_summary(state, message)
    try:
        return summarize(rows)
    except (AttributeError, KeyError, TypeError, ValueError):  # onverwachte vorm van het antwoord
        return empty_summary("error", UNEXPECTED_MESSAGE)
