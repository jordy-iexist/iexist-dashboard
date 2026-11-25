"""Momentopname van de ProRankTracker-posities per klant voor het bureau-overzicht.

Een live aanroep per klant bij elk bezoek is bij twintig klanten te traag, dus de stand wordt
dagelijks om 07:00 (Celery beat) en via de knop "Posities vernieuwen" opgeslagen in
`CustomerRankSnapshot`. De rijen komen uit `organic_rows` van het klantdashboard (alleen GET,
kost geen quota) en worden op dezelfde manier geteld als `summarize`: per rij, zodat de cijfers
gelijk zijn aan het klantdashboard.

Regel "Daling": een organisch zoekwoord dat een maand geleden in de top 20 stond en nu 5 of meer
plekken lager staat, of dat een maand geleden in de top 10 stond en daar nu uit is. "NTH" (niet
in de top 100) en een lege positie tellen als 101. Een zoekwoord dat meerdere keren gevolgd wordt
(andere locatie of zoekmachine) telt voor een daling één keer: de grootste daling.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import CustomerRankSnapshot, CustomerWebsite
from app.features.customers.rankings import (
    UNEXPECTED_MESSAGE,
    is_organic,
    keyword_key,
    organic_rows,
    position,
)

logger = logging.getLogger(__name__)

# Positie voor "NTH" of leeg: net buiten de top 100.
NOT_RANKED = 101
# Een maand geleden in de top 20 ...
DROP_WATCH_LIMIT = 20
# ... en nu minstens zoveel plekken gezakt ...
DROP_MIN_PLACES = 5
# ... of uit de top 10 gevallen.
TOP10 = 10
# Gelijktijdige aanroepen naar ProRankTracker.
MAX_WORKERS = 4

# Fouten van ProRankTracker die voor het hele bureau gelden (token geweigerd of geen toegang). Ze
# komen als melding uit `organic_rows`; zie de foutteksten in services/proranktracker/client.py.
TOKEN_ERROR_MARKERS: tuple[str, ...] = ("weigert het API-token", "staat deze aanvraag niet toe")

STATES: tuple[str, ...] = ("ok", "not_configured", "not_tracked", "error")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_token_error(message: str | None) -> bool:
    """Of de melding van een mislukte ophaalpoging over het API-token van het bureau gaat."""
    text = str(message or "")
    return any(marker in text for marker in TOKEN_ERROR_MARKERS)


def _has_month_ago(row: dict[str, Any]) -> bool:
    value = row.get("monthagorank")
    return value is not None and str(value).strip() != ""


def _url(value: Any) -> str | None:
    text = str(value or "").strip()
    return None if not text or text.lower() in ("none", "null") else text


def snapshot_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Tellers en dalingen uit de zoekwoordrijen van ProRankTracker (puur, geen netwerk).

    Antwoord: `{"keywords", "top10", "top10_month_ago", "drops"}`. Alleen organische rijen tellen.
    `keywords` en `top10` tellen per rij, zoals `summarize`. `top10_month_ago` is None als geen
    enkele rij een positie van een maand geleden heeft (ook geen "NTH"). `drops` is een lijst
    `{keyword, rank, month_ago_rank, url}`, grootste daling eerst; `rank` None = niet in de top 100.
    """
    organic = [row for row in rows or [] if isinstance(row, dict) and is_organic(row)]
    top10 = sum(1 for row in organic if (position(row.get("rank")) or NOT_RANKED) <= TOP10)
    top10_month_ago = None
    if any(_has_month_ago(row) for row in organic):
        top10_month_ago = sum(
            1 for row in organic if (position(row.get("monthagorank")) or NOT_RANKED) <= TOP10
        )

    best: dict[str, tuple[int, dict[str, Any]]] = {}
    for row in organic:
        key = keyword_key(row.get("name"))
        if not key:
            continue
        month = position(row.get("monthagorank")) or NOT_RANKED
        if month > DROP_WATCH_LIMIT:
            continue
        rank = position(row.get("rank"))
        now = rank or NOT_RANKED
        drop = now - month
        if drop < DROP_MIN_PLACES and not (month <= TOP10 < now):
            continue
        current = best.get(key)
        # Grootste daling; bij gelijke daling de beste positie van een maand geleden.
        if current is None or (drop, -month) > (current[0], -current[1]["month_ago_rank"]):
            best[key] = (drop, {
                "keyword": " ".join(str(row.get("name")).split()),
                "rank": rank,
                "month_ago_rank": month,
                "url": _url(row.get("matchedurl")),
            })
    drops = sorted(
        best.values(), key=lambda item: (-item[0], item[1]["month_ago_rank"], keyword_key(item[1]["keyword"]))
    )
    return {
        "keywords": len(organic),
        "top10": top10,
        "top10_month_ago": top10_month_ago,
        "drops": [drop for _, drop in drops],
    }


def _fetch(base_url: str) -> tuple[str, list[dict[str, Any]], str | None]:
    """`organic_rows` voor één klant; draait in een thread en raakt de database niet."""
    try:
        return organic_rows(base_url)
    except Exception:  # organic_rows vangt de bekende fouten zelf; dit is het vangnet
        logger.exception("Bureau-overzicht: posities van %s niet opgehaald", base_url)
        return "error", [], UNEXPECTED_MESSAGE


def _values(state: str, rows: list[dict[str, Any]], message: str | None) -> dict[str, Any]:
    """De kolommen van de momentopname voor één ophaalresultaat."""
    empty = {"state": state, "message": message, "keywords": None, "top10": None,
             "top10_month_ago": None, "drops": []}
    if state != "ok":
        return empty
    try:
        data = snapshot_from_rows(rows)
    except (AttributeError, KeyError, TypeError, ValueError):  # onverwachte vorm van het antwoord
        return {**empty, "state": "error", "message": UNEXPECTED_MESSAGE}
    return {"state": "ok", "message": None, **data}


def _store(db: Session, results: dict[str, dict[str, Any]], now: datetime) -> None:
    existing = {
        snapshot.customer_website_id: snapshot
        for snapshot in db.query(CustomerRankSnapshot)
        .filter(CustomerRankSnapshot.customer_website_id.in_(list(results)))
        .all()
    } if results else {}
    for customer_id, values in results.items():
        snapshot = existing.get(customer_id)
        if snapshot is None:
            snapshot = CustomerRankSnapshot(customer_website_id=customer_id, created_at=now)
            db.add(snapshot)
        for name, value in values.items():
            setattr(snapshot, name, value)
        snapshot.fetched_at = now
        snapshot.updated_at = now
    db.commit()


def refresh_all(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Haalt de posities van alle klanten op en slaat per klant de momentopname op. Commit.

    Alleen de aanroepen naar ProRankTracker lopen parallel (MAX_WORKERS threads); de database
    wordt daarna in deze sessie bijgewerkt. Een fout bij één klant wordt `state = "error"` voor
    die klant en stopt de rest niet. Antwoord: het aantal klanten per state.
    """
    now = now or _now()
    customers = db.query(CustomerWebsite.id, CustomerWebsite.base_url).all()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        fetched = list(pool.map(_fetch, [str(base_url or "") for _id, base_url in customers]))
    results = {
        customer_id: _values(*result) for (customer_id, _base_url), result in zip(customers, fetched)
    }
    try:
        _store(db, results, now)
    except IntegrityError:
        # Tegelijk aangemaakt door een andere ronde (taak en knop): nog één keer, nu als update.
        db.rollback()
        _store(db, results, now)
    counts = {state: 0 for state in STATES}
    for values in results.values():
        counts[values["state"]] = counts.get(values["state"], 0) + 1
    return counts


__all__ = [
    "DROP_MIN_PLACES",
    "DROP_WATCH_LIMIT",
    "NOT_RANKED",
    "is_token_error",
    "refresh_all",
    "snapshot_from_rows",
]
