"""Kaarten op de werkvoorraad: vingerafdruk, positie binnen een kolom en de week.

Een kolom is één status over alle klanten heen; de volgorde is `position` oplopend (bij gelijke
positie op id). Posities zijn floats, zodat slepen alleen de verplaatste kaart wijzigt; wordt
het gat tussen twee buren te klein, dan wordt de kolom hernummerd (`rebalance`).

De sessies van de app hebben `autoflush=False`; de functies hier flushen zelf voordat ze de
kolom lezen, zodat nog niet weggeschreven kaarten en posities meetellen.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.db.models import WorkItem
from app.features.launch_checklist.services.scan_recovery import as_utc
from app.features.work_queue.services.types import Item, severity_rank

try:
    _TZ: Any = ZoneInfo("Europe/Amsterdam")
except ZoneInfoNotFoundError:  # image zonder tz-database: weekgrens in UTC
    _TZ = timezone.utc

# Afstand tussen kaarten bij een nieuwe kaart onderaan/bovenaan en na hernummeren.
POSITION_STEP = 1000.0
# Kleiner gat tussen twee buren → kolom hernummeren.
MIN_GAP = 1e-6


def fingerprint_of(items: Iterable[Item | dict[str, Any]], severity: str | None) -> str:
    """sha1 over de gesorteerde itemsleutels en de ernst; gelijk = niets bij te werken."""
    keys = sorted(str(item["key"] if isinstance(item, dict) else item.key) for item in items)
    payload = "\n".join([*keys, f"severity={severity or ''}"])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _column(db: Session, status: str, *, exclude_id: str | None = None) -> list[tuple[str, float, str]]:
    """(id, positie, ernst) van de kaarten in een kolom, in volgorde."""
    db.flush()
    query = db.query(WorkItem.id, WorkItem.position, WorkItem.severity).filter(WorkItem.status == status)
    if exclude_id is not None:
        query = query.filter(WorkItem.id != exclude_id)
    return [(row[0], float(row[1]), row[2]) for row in query.order_by(WorkItem.position, WorkItem.id).all()]


def _between(upper: float | None, lower: float | None) -> float:
    """Positie tussen de kaart erboven (`upper`) en eronder (`lower`); beide mogen ontbreken."""
    if upper is None and lower is None:
        return POSITION_STEP
    if upper is None:
        return lower - POSITION_STEP
    if lower is None:
        return upper + POSITION_STEP
    return (upper + lower) / 2


def position_for_new(db: Session, status: str, severity: str | None) -> float:
    """Positie voor een nieuwe kaart: na de laatste kaart in de kolom met gelijke of hogere
    ernst (in een op ernst gesorteerde kolom dus vóór de eerste kaart met lagere ernst).
    Heeft geen kaart een gelijke of hogere ernst, dan bovenaan; lege kolom → 1000."""
    rank = severity_rank(severity)
    for attempt in range(2):
        column = _column(db, status)
        if not column:
            return POSITION_STEP
        last = None
        for index, (_card_id, _position, card_severity) in enumerate(column):
            if severity_rank(card_severity) >= rank:
                last = index
        if last is None:
            return _between(None, column[0][1])
        upper = column[last][1]
        lower = column[last + 1][1] if last + 1 < len(column) else None
        if lower is None or lower - upper >= MIN_GAP or attempt:
            return _between(upper, lower)
        rebalance(db, status)
    raise AssertionError("onbereikbaar")


def position_between(
    db: Session,
    status: str,
    after_id: str | None,
    before_id: str | None,
    *,
    exclude_id: str | None = None,
) -> float:
    """Positie voor een kaart die in kolom `status` tussen twee buren wordt gezet.

    `after_id` is de kaart direct erboven, `before_id` de kaart direct eronder. Alleen
    `after_id` → direct daarna (vóór de volgende kaart in de kolom); alleen `before_id` → direct
    ervoor; geen van beide → onderaan. Staan de twee buren in de verkeerde volgorde (verouderd
    bord), dan geldt alleen `after_id`. `exclude_id` is de kaart die verplaatst wordt: die telt
    niet als buur. Een id die niet in deze kolom staat → ValueError. Hernummert de kolom als
    het gat te klein is.
    """
    for attempt in range(2):
        column = _column(db, status, exclude_id=exclude_id)
        index_of = {card_id: index for index, (card_id, _p, _s) in enumerate(column)}
        for neighbour in (after_id, before_id):
            if neighbour is not None and neighbour not in index_of:
                raise ValueError(f"Kaart {neighbour} staat niet in kolom {status}.")

        if after_id is None and before_id is None:
            return _between(column[-1][1] if column else None, None)
        if after_id is not None and (before_id is None or index_of[after_id] >= index_of[before_id]):
            index = index_of[after_id]
            upper = column[index][1]
            lower = column[index + 1][1] if index + 1 < len(column) else None
        elif after_id is not None:
            upper = column[index_of[after_id]][1]
            lower = column[index_of[before_id]][1]
        else:
            index = index_of[before_id]
            upper = column[index - 1][1] if index > 0 else None
            lower = column[index][1]

        if upper is None or lower is None or lower - upper >= MIN_GAP or attempt:
            return _between(upper, lower)
        rebalance(db, status)
    raise AssertionError("onbereikbaar")


def position_top(db: Session, status: str) -> float:
    """Positie boven de bovenste kaart van de kolom; lege kolom → 1000."""
    column = _column(db, status)
    return _between(None, column[0][1] if column else None)


def rebalance(db: Session, status: str) -> bool:
    """Hernummert de kolom (1000, 2000, ...) als het gat tussen twee buren kleiner is dan
    `MIN_GAP`; de volgorde blijft gelijk. True als er hernummerd is. Commit niet."""
    column = _column(db, status)
    if all(lower - upper >= MIN_GAP for (_a, upper, _s), (_b, lower, _t) in zip(column, column[1:])):
        return False
    cards = {
        card.id: card
        for card in db.query(WorkItem).filter(WorkItem.id.in_([card_id for card_id, _p, _s in column])).all()
    }
    for index, (card_id, _position, _severity) in enumerate(column):
        cards[card_id].position = POSITION_STEP * (index + 1)
    db.flush()
    return True


def week_start_utc(now: datetime) -> datetime:
    """Begin van de week van `now`: maandag 00:00 in Europe/Amsterdam, als UTC-tijdstip.
    Een naïeve `now` geldt als UTC."""
    local = as_utc(now).astimezone(_TZ)
    monday = local.date() - timedelta(days=local.weekday())
    start = datetime(monday.year, monday.month, monday.day, tzinfo=_TZ)
    return start.astimezone(timezone.utc)
