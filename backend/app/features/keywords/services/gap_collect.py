"""Ophalen voor Zoekwoorden › Content gap: lijsten, posities en cijfers, binnen een unit-budget.

Drie functies, in de volgorde van de worker:
- `collect_lists`: stap 1, de top 10-lijsten van klant en concurrenten. Wat in de
  concurrentenscan staat (`Raw.top10`) kost niets; een ontbrekend domein wordt opgehaald.
- `collect_positions`: stap 4, de kandidaten bij één domein navragen (klant zonder
  positiegrens, zodat "#14" zichtbaar wordt).
- `collect_facts`: stap 5, volume, KD en intentie via `keywords_overview`.

Elke Ahrefs-aanroep loopt via `collect.UnitBudget` (dezelfde als de concurrentenscan): vooraf
een schatting, achteraf de werkelijke kosten uit de responseheader. Past een stap niet meer,
dan wordt die overgeslagen en komt een korte omschrijving in `budget.skipped`; bij een
Ahrefs-fout staat de fout tussen haakjes erachter (zie `worker/refresh.skipped_warning`).
Een fout met een code uit `FATAL_CODES` (sleutel ontbreekt of geweigerd, units op) heeft
geen zin om door te zetten en wordt doorgegooid. Geen databasecode.
"""
from __future__ import annotations

from app.core.config import settings
from app.features.competitor_analysis.services.pipeline import KeywordFacts, keyword_facts
from app.features.customers import rankings
from app.features.keywords.gap_schemas import UNITS_PER_GAP_KEYWORD_FACTS, PositionCheck
from app.features.keywords.schemas import UNITS_PER_KEYWORD_ROW, Raw
from app.features.keywords.services.collect import CHECK_CHUNK, UnitBudget, _estimate, _keyword_list
from app.services.ahrefs import client as ahrefs
from app.services.ahrefs.client import AhrefsServiceError

FATAL_CODES = frozenset({"not_configured", "unauthorized", "forbidden"})


def _chunks(values: list[str], size: int = CHECK_CHUNK) -> list[list[str]]:
    return [values[i:i + size] for i in range(0, len(values), size)]


def _unique(keywords: list[str]) -> list[str]:
    """Ontdubbeld op `keyword_key`, eerste schrijfwijze, zonder lege."""
    seen: set[str] = set()
    out: list[str] = []
    for keyword in keywords:
        key = rankings.keyword_key(keyword)
        if key and key not in seen:
            seen.add(key)
            out.append(keyword.strip())
    return out


def _position(value) -> int | None:
    try:
        return int(float(value)) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


# --- stap 1: lijsten --------------------------------------------------------------------------


def collect_lists(
    raw: Raw,
    *,
    customer_domain: str,
    competitors: list[str],
    country: str,
    budget: UnitBudget,
) -> dict[str, list[str]]:
    """Top 10-zoekwoorden per domein (klant + `competitors`), in lijstvolgorde.

    Uit `raw.top10` als het domein daar staat, anders opgehaald met
    `AHREFS_COMPETITORS_KEYWORDS_PER_DOMAIN` rijen. Een overgeslagen of mislukt domein
    ontbreekt in het resultaat.
    """
    customer = rankings.host_of(customer_domain)
    lists: dict[str, list[str]] = {}
    limit = settings.ahrefs_competitors_keywords_per_domain
    estimate = _estimate(limit, UNITS_PER_KEYWORD_ROW)
    for domain in dict.fromkeys(d for d in [customer, *competitors] if d):
        entry = raw.top10.get(domain)
        if entry is not None:
            lists[domain] = list(entry.keywords)
            continue
        if not budget.allows(estimate):
            budget.skipped.append(f"top 10-zoekwoorden van {domain}")
            continue
        try:
            result = ahrefs.top10_keywords(domain, country=country, limit=limit)
        except AhrefsServiceError as exc:
            if exc.code in FATAL_CODES:
                raise
            budget.skipped.append(f"top 10-zoekwoorden van {domain} ({exc})")
            continue
        budget.add(result.units)
        lists[domain] = _keyword_list(result.rows)
    return lists


# --- stap 4: posities -------------------------------------------------------------------------


def collect_positions(
    domain: str,
    keywords: list[str],
    *,
    country: str,
    max_position: int | None,
    budget: UnitBudget,
) -> PositionCheck:
    """Beste positie per zoekwoord bij één domein, in delen van `CHECK_CHUNK`.

    `max_position=None` vraagt zonder positiegrens (voor de klant). Een deel dat niet in het
    budget past of mislukt wordt overgeslagen, de rest niet: `checked` zegt wat echt is
    nagevraagd.
    """
    check = PositionCheck()
    todo = _unique(keywords)
    chunks = _chunks(todo)
    for index, chunk in enumerate(chunks):
        if not budget.allows(_estimate(len(chunk), UNITS_PER_KEYWORD_ROW)):
            left = sum(len(c) for c in chunks[index:])
            budget.skipped.append(f"posities van {left} van {len(todo)} zoekwoorden bij {domain}")
            break
        try:
            result = ahrefs.top10_keywords(domain, country=country, limit=len(chunk), keywords=chunk,
                                           max_position=max_position)
        except AhrefsServiceError as exc:
            if exc.code in FATAL_CODES:
                raise
            budget.skipped.append(f"posities van {len(chunk)} zoekwoorden bij {domain} ({exc})")
            continue
        budget.add(result.units)
        check.checked.update(rankings.keyword_key(k) for k in chunk)
        for row in result.rows:
            key = rankings.keyword_key(row.get("keyword"))
            position = _position(row.get("best_position"))
            if key and position is not None and position > 0:
                best = check.positions.get(key)
                check.positions[key] = position if best is None else min(best, position)
    return check


# --- stap 5: volume, KD en intentie -----------------------------------------------------------


def _fits(budget: UnitBudget, wanted: int) -> int:
    """Hoeveel zoekwoorden (hoogstens `wanted`) nog in het budget passen."""
    room = budget.cap - budget.spent
    count = min(wanted, max(0, room) // UNITS_PER_GAP_KEYWORD_FACTS)
    while count > 0 and not budget.allows(_estimate(count, UNITS_PER_GAP_KEYWORD_FACTS)):
        count -= 1
    return count


def collect_facts(keywords: list[str], *, country: str, budget: UnitBudget) -> dict[str, KeywordFacts]:
    """Volume, KD en intentie per `keyword_key`, in delen van `CHECK_CHUNK`.

    Past niet alles in het budget, dan de eerste zoekwoorden die nog passen; de rest blijft
    zonder cijfers en komt in `budget.skipped`. Een mislukt deel slaat alleen dat deel over.
    """
    facts: dict[str, KeywordFacts] = {}
    todo = _unique(keywords)
    if not todo:
        return facts
    fits = _fits(budget, len(todo))
    if fits < len(todo):
        budget.skipped.append(f"volume, KD en intentie van {len(todo) - fits} van {len(todo)} zoekwoorden")
    for chunk in _chunks(todo[:fits]):
        if not budget.allows(_estimate(len(chunk), UNITS_PER_GAP_KEYWORD_FACTS)):
            budget.skipped.append(f"volume, KD en intentie van {len(chunk)} zoekwoorden")
            continue
        try:
            result = ahrefs.keywords_overview(chunk, country=country)
        except AhrefsServiceError as exc:
            if exc.code in FATAL_CODES:
                raise
            budget.skipped.append(f"volume, KD en intentie van {len(chunk)} zoekwoorden ({exc})")
            continue
        budget.add(result.units)
        facts.update(keyword_facts(result))
    return facts
