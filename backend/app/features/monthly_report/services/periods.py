"""Maanden en periodes van het maandrapport (pure functies, geen database).

- Een maand is "YYYY-MM" en loopt van de eerste tot en met de laatste dag in Europe/Amsterdam.
- Search Console loopt `lag_days` achter: de periode van een lopende maand is korter
  (`gsc_spans`). De vergelijking is even lang en begint op de eerste van de maand ervoor.
- ProRankTracker kent alleen "nu": posities en AI-vermeldingen horen alleen bij een maand als
  ze in die maand of hooguit `PRT_WINDOW_DAYS` dagen erna zijn uitgelezen (`prt_window_open`).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    _TZ: Any = ZoneInfo("Europe/Amsterdam")
except ZoneInfoNotFoundError:  # image zonder tz-database: maandgrenzen in UTC
    _TZ = timezone.utc

PRT_WINDOW_DAYS = 7
# Zo ver terug kan een rapport (Search Console bewaart 16 maanden).
MAX_MONTHS_BACK = 16

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_month(value: str) -> tuple[int, int]:
    """"YYYY-MM" → (jaar, maand); ValueError bij een andere vorm of een maand buiten 1–12."""
    match = _MONTH_RE.match(str(value or ""))
    if not match:
        raise ValueError("De maand moet de vorm JJJJ-MM hebben.")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12 or year < 2000:
        raise ValueError("De maand moet de vorm JJJJ-MM hebben.")
    return year, month


def format_month(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def month_of(day: date) -> str:
    return format_month(day.year, day.month)


def shift_month(month: str, delta: int) -> str:
    year, number = parse_month(month)
    index = year * 12 + (number - 1) + delta
    return format_month(index // 12, index % 12 + 1)


def previous_month(month: str) -> str:
    return shift_month(month, -1)


def months_back(month: str, today: date) -> int:
    """Hoeveel maanden `month` vóór de maand van `today` ligt (negatief = toekomst)."""
    year, number = parse_month(month)
    return (today.year * 12 + today.month) - (year * 12 + number)


def first_day(month: str) -> date:
    year, number = parse_month(month)
    return date(year, number, 1)


def last_day(month: str) -> date:
    return first_day(shift_month(month, 1)) - timedelta(days=1)


def today_local(now: datetime | None = None) -> date:
    """De datum van vandaag in Europe/Amsterdam."""
    return (now or datetime.now(timezone.utc)).astimezone(_TZ).date()


def month_bounds_utc(month: str) -> tuple[datetime, datetime]:
    """(begin, einde) van de maand in UTC; het einde is exclusief (begin van de volgende maand)."""
    start, end = first_day(month), first_day(shift_month(month, 1))
    return (
        datetime(start.year, start.month, start.day, tzinfo=_TZ).astimezone(timezone.utc),
        datetime(end.year, end.month, end.day, tzinfo=_TZ).astimezone(timezone.utc),
    )


def gsc_spans(month: str, today: date, lag_days: int) -> dict[str, Any] | None:
    """Search Console-periodes van een maand, of None als er nog niets van de maand is.

    `{"current": (begin, einde), "previous": (begin, einde), "complete": bool}`. Het einde is
    `min(laatste dag, vandaag − lag_days)`; de vergelijking zijn de eerste even veel dagen van
    de maand ervoor, afgekapt op het einde daarvan.
    """
    start, month_end = first_day(month), last_day(month)
    end = min(month_end, today - timedelta(days=lag_days))
    if end < start:
        return None
    days = (end - start).days + 1
    prev = previous_month(month)
    prev_start = first_day(prev)
    prev_end = min(prev_start + timedelta(days=days - 1), last_day(prev))
    return {"current": (start, end), "previous": (prev_start, prev_end), "complete": end == month_end}


def prt_window_open(month: str, today: date) -> bool:
    """Of ProRankTracker nu nog iets over deze maand zegt: in de maand of ≤ 7 dagen erna."""
    return first_day(month) <= today <= last_day(month) + timedelta(days=PRT_WINDOW_DAYS)


__all__ = [
    "MAX_MONTHS_BACK",
    "PRT_WINDOW_DAYS",
    "first_day",
    "format_month",
    "gsc_spans",
    "last_day",
    "month_bounds_utc",
    "month_of",
    "months_back",
    "parse_month",
    "previous_month",
    "prt_window_open",
    "shift_month",
    "today_local",
]
