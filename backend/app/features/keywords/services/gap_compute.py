"""Rekenregels van Zoekwoorden › Content gap: kandidaten, afkappen en de eindlijst.

Puur: geen database, geen netwerk en geen instellingen. Werkt op de top 10-lijsten per domein
(stap 1 in `gap_collect.py`), de nagevraagde posities (`PositionCheck`) en de cijfers uit
`keywords_overview` (`KeywordFacts`). De vormen staan in `features/keywords/gap_schemas.py`.

Zoekwoorden worden altijd vergeleken via `rankings.keyword_key`.
"""
from __future__ import annotations

from app.features.competitor_analysis.services.pipeline import KeywordFacts
from app.features.customers.rankings import host_of, keyword_key
from app.features.keywords.gap_schemas import (
    MIN_COMPETITORS,
    TOP10,
    UNITS_PER_GAP_KEYWORD,
    GapCandidate,
    GapKeyword,
    GapSnapshot,
    PositionCheck,
)


def max_keywords(units: int) -> int:
    """Hoeveel kandidaten met `units` uitgewerkt kunnen worden (posities + cijfers)."""
    return max(0, int(units or 0)) // UNITS_PER_GAP_KEYWORD


def candidates(
    lists: dict[str, list[str]], *, customer_domain: str, competitors: list[str]
) -> list[GapCandidate]:
    """Stap 2: zoekwoorden in minstens `MIN_COMPETITORS` lijsten van de concurrenten en niet
    in de lijst van de klant.

    Volgorde: meeste concurrenten eerst, daarna de vroegste plek in de lijsten (die staan op
    verkeer aflopend), daarna de sleutel. De getoonde tekst is de eerste schrijfwijze, in de
    volgorde van `competitors`.
    """
    customer = host_of(customer_domain)
    own = {keyword_key(k) for k in lists.get(customer, [])}
    found: dict[str, GapCandidate] = {}
    for domain in competitors:
        for index, keyword in enumerate(lists.get(domain, [])):
            key = keyword_key(keyword)
            if not key or key in own:
                continue
            item = found.get(key)
            if item is None:
                found[key] = GapCandidate(keyword=keyword.strip(), key=key, domains=[domain], first_index=index)
                continue
            if domain not in item.domains:
                item.domains.append(domain)
            item.first_index = min(item.first_index, index)
    out = [item for item in found.values() if len(item.domains) >= MIN_COMPETITORS]
    out.sort(key=lambda i: (-len(i.domains), i.first_index, i.key))
    return out


def _in_top10(item: GapCandidate, domain: str, check: PositionCheck | None) -> bool:
    """Is nagevraagd: de navraag beslist. Anders: staat het in de lijst van het domein?"""
    if check is not None and item.key in check.checked:
        position = check.positions.get(item.key)
        return position is not None and position <= TOP10
    return domain in item.domains


def _sort_key(pair: tuple[int, GapKeyword]):
    index, keyword = pair
    return (keyword.volume is None, -(keyword.volume or 0), -keyword.competitors_count, index)


def build_snapshot(
    items: list[GapCandidate],
    *,
    limit: int,
    customer_domain: str,
    competitors: list[str],
    checks: dict[str, PositionCheck],
    facts: dict[str, KeywordFacts],
    warnings: list[str],
) -> GapSnapshot:
    """Stap 3 tot en met de eindlijst.

    De eerste `limit` kandidaten worden uitgewerkt. Een uitgewerkt zoekwoord vervalt als de
    klant volgens de navraag toch in de top 10 staat, of als na de navraag minder dan
    `MIN_COMPETITORS` concurrenten overblijven; zulke zoekwoorden tellen ook niet mee in
    `found`. Een positie die niet is nagevraagd (overgeslagen stap) is None.
    """
    customer = host_of(customer_domain)
    own_check = checks.get(customer)
    rows: list[GapKeyword] = []
    dropped = 0
    for item in items[:max(0, limit)]:
        own = own_check.positions.get(item.key) if own_check is not None else None
        if own is not None and own <= TOP10:
            dropped += 1
            continue
        count = sum(1 for domain in competitors if _in_top10(item, domain, checks.get(domain)))
        if count < MIN_COMPETITORS:
            dropped += 1
            continue
        positions: dict[str, int | None] = {}
        for domain in competitors:
            check = checks.get(domain)
            position = check.positions.get(item.key) if check is not None else None
            positions[domain] = position if position is not None and position <= TOP10 else None
        fact = facts.get(item.key)
        rows.append(GapKeyword(
            keyword=item.keyword,
            volume=fact.volume if fact is not None else None,
            kd=fact.kd if fact is not None else None,
            intents=list(fact.intents) if fact is not None else [],
            competitors_count=count,
            positions=positions,
            own_position=own,
        ))
    ordered = [keyword for _, keyword in sorted(enumerate(rows), key=_sort_key)]
    return GapSnapshot(
        customer_domain=customer,
        competitors=list(competitors),
        found=max(0, len(items) - dropped),
        keywords=ordered,
        warnings=list(warnings),
    )
