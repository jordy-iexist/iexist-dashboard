"""Rekenregels van Zoekwoorden › Concurrenten: kandidaten, de vijf, KPI's en de heatmap.

Puur: geen database, geen netwerk en geen instellingen. Werkt op de ruwe gegevens (`Raw`) uit
`collect.py`, het oordeel van Claude (`DomainClass`, `TopicAssignment`) en de handmatige
keuzes (`Overrides`). De vormen staan in `features/keywords/schemas.py`.

Uitgesloten (effectief): de keuze van de gebruiker als die er is, anders het oordeel van
Claude (vergelijkingssite = uitgesloten); zonder oordeel telt een domein mee.
"""
from __future__ import annotations

from statistics import mean, median

from app.features.customers.rankings import host_of, keyword_key
from app.features.keywords.schemas import (
    CANDIDATE_LIMIT,
    HEAT_LEVEL_MIN,
    LOCAL_TOPIC,
    MAX_EXCLUDED_SHOWN,
    MIN_SHARED_KEYWORDS,
    MIN_TOPIC_KEYWORDS,
    TOP_COMPETITORS,
    TRACKED_CANDIDATES_MAX,
    TRACKED_KEYWORDS_MAX,
    UNITS_MIN_PER_REQUEST,
    UNITS_PER_COMPETITOR_ROW,
    UNITS_PER_HISTORY_ROW,
    UNITS_PER_KEYWORD_ROW,
    UNITS_PER_METRICS_ROW,
    UNIVERSE_MAX,
    Candidate,
    DomainClass,
    DomainRatingKpi,
    Heatmap,
    HeatmapCell,
    HeatmapColumn,
    HeatmapRow,
    HeatmapUniverse,
    KeywordKpi,
    Kpis,
    OverlapBasis,
    OverlapKpi,
    Overrides,
    Raw,
    RawMetrics,
    Snapshot,
    SnapshotCompetitor,
    Sources,
    Summary,
    TopicAssignment,
    TrafficKpi,
)

MAX_TITLES = 3
# Voor `unit_estimate`: standaardwaarde van AHREFS_COMPETITORS_KEYWORDS_PER_DOMAIN (deze
# module leest geen instellingen) en het aantal domeinen in stap D (klant, de vijf en de
# getoonde uitgesloten).
ESTIMATE_KEYWORDS_PER_DOMAIN = 150
# Nacontrole van een afgekapte lijst: gemiddeld twee aanvragen per domein, elk rond het minimum.
ESTIMATE_CHECK_UNITS_PER_DOMAIN = 150
ESTIMATE_METRICS_DOMAINS = 1 + TOP_COMPETITORS + MAX_EXCLUDED_SHOWN

NO_COMPETITORS_MESSAGE = "Ahrefs vond geen organische concurrenten voor dit domein."
NO_KEYWORDS_MESSAGE = "Er konden geen zoekwoorden bij de onderwerpen worden ingedeeld."


def _is_own(domain: str, customer: str) -> bool:
    return not domain or (bool(customer) and (domain == customer or domain.endswith(f".{customer}")))


def _domains(values: list[str], customer: str) -> list[str]:
    out: list[str] = []
    for value in values:
        domain = host_of(value)
        if not _is_own(domain, customer) and domain not in out:
            out.append(domain)
    return out


# --- kandidaten -------------------------------------------------------------------------------


def sample_size(raw: Raw) -> int:
    """Aantal steekproef-SERP's met minstens één organisch resultaat.

    Een zoekwoord waarvoor Ahrefs geen SERP kent telt niet mee: het zou de overlap van elk
    domein onterecht verlagen.
    """
    return sum(1 for hits in (raw.serps or {}).values() if hits)


def overlap_basis(raw: Raw) -> OverlapBasis:
    """"tracked" zodra de aanvulling via gevolgde zoekwoorden minstens één SERP opleverde."""
    return "tracked" if sample_size(raw) else "ahrefs"


def _serp_stats(raw: Raw, customer: str) -> dict[str, dict]:
    """Per domein: in hoeveel SERP's het staat, de beste positie per SERP en paginatitels."""
    stats: dict[str, dict] = {}
    for hits in (raw.serps or {}).values():
        best: dict[str, int] = {}
        for hit in hits:
            domain = host_of(hit.domain)
            if _is_own(domain, customer):
                continue
            entry = stats.setdefault(domain, {"serps": 0, "positions": [], "titles": []})
            if hit.title and hit.title not in entry["titles"] and len(entry["titles"]) < MAX_TITLES:
                entry["titles"].append(hit.title)
            if domain not in best or hit.position < best[domain]:
                best[domain] = hit.position
        for domain, position in best.items():
            stats[domain]["serps"] += 1
            stats[domain]["positions"].append(position)
    return stats


def candidates(raw: Raw, *, customer_domain: str, manual_domains: list[str]) -> list[Candidate]:
    """Kandidaat-concurrenten met Gedeeld en Overlap volgens `overlap_basis(raw)`.

    Volgorde: Ahrefs-rijen (in de volgorde van Ahrefs), handmatige domeinen zonder rij en bij
    basis "tracked" daarna de via SERP's gevonden domeinen. Nooit het klantdomein of een
    subdomein ervan.
    """
    customer = host_of(customer_domain)
    manual = _domains(manual_domains, customer)
    rows = {}
    for row in raw.competitors or []:
        domain = host_of(row.domain)
        if not _is_own(domain, customer) and domain not in rows:
            rows[domain] = row

    def origin(domain: str) -> str:
        if domain in manual:
            return "manual"
        return "ahrefs" if domain in rows else "tracked"

    def rating(domain: str) -> float | None:
        return rows[domain].domain_rating if domain in rows else None

    if overlap_basis(raw) == "ahrefs":
        out = [
            Candidate(
                domain=domain, origin=origin(domain), domain_rating=row.domain_rating,
                shared=row.keywords_common, overlap_pct=round(row.share, 1),
            )
            for domain, row in rows.items()
            if domain in manual or row.keywords_common >= MIN_SHARED_KEYWORDS
        ]
        out += [Candidate(domain=d, origin="manual") for d in manual if d not in rows]
        return out

    stats = _serp_stats(raw, customer)
    total = sample_size(raw)
    found = [d for d in stats if d not in rows and d not in manual and stats[d]["serps"] > 0]
    found.sort(key=lambda d: (-stats[d]["serps"], mean(stats[d]["positions"]), d))
    domains = [*rows, *[d for d in manual if d not in rows], *found[:TRACKED_CANDIDATES_MAX]]

    out = []
    for domain in domains:
        entry = stats.get(domain, {"serps": 0, "titles": []})
        shared = entry["serps"]
        if shared == 0 and domain not in manual:
            continue
        out.append(Candidate(
            domain=domain, origin=origin(domain), domain_rating=rating(domain), shared=shared,
            overlap_pct=round(100 * shared / total, 1) if total else 0.0,
            titles=list(entry["titles"]),
        ))
    return out


def _excluded(domain: str, classes: dict[str, DomainClass], overrides: Overrides) -> bool:
    choice = overrides.domains.get(domain)
    if choice is not None and choice.excluded is not None:
        return choice.excluded
    cls = classes.get(domain)
    return bool(cls and cls.is_aggregator)


def _manual_order(overrides: Overrides) -> list[str]:
    return [host_of(m.domain) for m in overrides.manual]


def select_top5(
    items: list[Candidate], classes: dict[str, DomainClass], overrides: Overrides
) -> list[str]:
    """"De vijf": eerst handmatige domeinen in volgorde van toevoegen, daarna op overlap.

    Uitgesloten domeinen tellen niet mee. De overige worden gesorteerd op `overlap_pct`
    aflopend, dan `shared` aflopend, dan domeinnaam.
    """
    order = _manual_order(overrides)
    allowed = [i for i in items if not _excluded(i.domain, classes, overrides)]
    manual = [i for i in allowed if i.origin == "manual"]
    manual.sort(key=lambda i: (order.index(i.domain) if i.domain in order else len(order), i.domain))
    rest = [i for i in allowed if i.origin != "manual"]
    rest.sort(key=lambda i: (-i.overlap_pct, -i.shared, i.domain))
    return [i.domain for i in [*manual, *rest][:TOP_COMPETITORS]]


def shown_excluded(
    items: list[Candidate], classes: dict[str, DomainClass], overrides: Overrides
) -> list[str]:
    """Uitgesloten kandidaten op `shared` aflopend (max MAX_EXCLUDED_SHOWN), plus elk
    handmatig uitgesloten domein dat daar niet bij zat."""
    excluded = [i for i in items if _excluded(i.domain, classes, overrides)]
    excluded.sort(key=lambda i: (-i.shared, i.domain))
    shown = [i.domain for i in excluded[:MAX_EXCLUDED_SHOWN]]
    shown += [i.domain for i in excluded if i.origin == "manual" and i.domain not in shown]
    return shown


# --- zoekwoordenverzameling -------------------------------------------------------------------


def _tracked_rows(raw: Raw):
    return list(raw.prt.rows) if raw.prt is not None else []


def keyword_universe(raw: Raw, *, customer_domain: str, top5: list[str]) -> list[str]:
    """Zoekwoorden voor de indeling door Claude en de heatmap, ontdubbeld, max UNIVERSE_MAX.

    1. de gevolgde zoekwoorden (max TRACKED_KEYWORDS_MAX, hoogste volume eerst);
    2. zoekwoorden in minstens twee top 10-lijsten (klant + de vijf), vaakst eerst;
    3. de rest om de beurt per domein, in lijstvolgorde.
    """
    customer = host_of(customer_domain)
    out: list[str] = []
    seen: set[str] = set()

    def add(keyword: str) -> bool:
        key = keyword_key(keyword)
        if key and key not in seen and len(out) < UNIVERSE_MAX:
            seen.add(key)
            out.append(keyword.strip())
        return len(out) < UNIVERSE_MAX

    tracked = sorted(
        enumerate(_tracked_rows(raw)),
        key=lambda pair: (pair[1].volume is None, -(pair[1].volume or 0), pair[0]),
    )
    tracked_added = 0
    for _, row in tracked:
        if tracked_added >= TRACKED_KEYWORDS_MAX:
            break
        if keyword_key(row.keyword) not in seen:
            tracked_added += 1
        if not add(row.keyword):
            return out

    lists = [raw.top10[d].keywords for d in [customer, *top5] if d in raw.top10]
    counts: dict[str, int] = {}
    for keywords in lists:
        for key in {keyword_key(k) for k in keywords}:
            counts[key] = counts.get(key, 0) + 1

    longest = max((len(k) for k in lists), default=0)
    round_robin = [keywords[i] for i in range(longest) for keywords in lists if i < len(keywords)]
    rank = {}
    for position, keyword in enumerate(round_robin):
        rank.setdefault(keyword_key(keyword), position)
    shared = [k for k in round_robin if counts.get(keyword_key(k), 0) >= 2]
    shared.sort(key=lambda k: (-counts[keyword_key(k)], rank[keyword_key(k)]))
    for keyword in [*shared, *round_robin]:
        if not add(keyword):
            break
    return out


# --- momentopname -----------------------------------------------------------------------------


def _top10_count(metrics: RawMetrics | None) -> int | None:
    if metrics is None or metrics.org_keywords_1_3 is None or metrics.org_keywords_4_10 is None:
        return None
    return metrics.org_keywords_1_3 + metrics.org_keywords_4_10


def _change_pct(raw: Raw) -> float | None:
    history = raw.traffic_history or []
    if len(history) < 2 or history[-2].org_traffic == 0:
        return None
    previous, last = history[-2].org_traffic, history[-1].org_traffic
    return round(100 * (last - previous) / previous, 1)


def _kpis(raw: Raw, customer: str, top: list[SnapshotCompetitor]) -> Kpis:
    """KPI's van de klant tegenover de vijf; zonder vijf zijn de vergelijkingen None."""
    own = raw.metrics.get(customer)
    ratings = [c.domain_rating for c in top if c.domain_rating is not None]
    return Kpis(
        organic_keywords=KeywordKpi(
            value=own.org_keywords if own else None, top10=_top10_count(own)
        ),
        organic_traffic=TrafficKpi(
            value=own.org_traffic if own else None, change_pct=_change_pct(raw)
        ),
        domain_rating=DomainRatingKpi(
            value=own.domain_rating if own else None,
            competitor_median=float(median(ratings)) if ratings else None,
        ),
        top5_overlap=OverlapKpi(
            pct=round(mean(c.overlap_pct for c in top), 1) if top else None,
            shared_avg=round(mean(c.shared for c in top)) if top else None,
        ),
    )


def _snapshot_competitor(
    item: Candidate, raw: Raw, classes: dict[str, DomainClass], in_top5: bool
) -> SnapshotCompetitor:
    cls = classes.get(item.domain)
    metrics = raw.metrics.get(item.domain)
    rating = metrics.domain_rating if metrics and metrics.domain_rating is not None else item.domain_rating
    return SnapshotCompetitor(
        domain=item.domain,
        origin=item.origin,
        ai_type=cls.type if cls else None,
        ai_is_aggregator=cls.is_aggregator if cls else False,
        ai_reason=(cls.reason or None) if cls else None,
        in_top5=in_top5,
        domain_rating=rating,
        organic_keywords=metrics.org_keywords if metrics else None,
        top10_keywords=_top10_count(metrics),
        traffic=metrics.org_traffic if metrics else None,
        shared=item.shared,
        overlap_pct=item.overlap_pct,
    )


def _level(pct: int) -> int:
    return max(level for level, minimum in enumerate(HEAT_LEVEL_MIN) if pct >= minimum)


def _heatmap(
    raw: Raw,
    customer: str,
    top5: list[str],
    topics: list[str],
    assignment: TopicAssignment | None,
) -> Heatmap:
    """Aandeel top 10-noteringen per onderwerp en per domein (klant + de vijf).

    Voor de klant beslist ProRankTracker bij een gevolgd zoekwoord; anders de top 10-lijst van
    Ahrefs. Percentages worden half naar boven afgerond.
    """
    universe = keyword_universe(raw, customer_domain=customer, top5=top5)
    universe_keys = {keyword_key(k) for k in universe}
    ranks = {keyword_key(r.keyword): r.rank for r in _tracked_rows(raw)}
    info = HeatmapUniverse(
        total=len(universe), tracked=sum(1 for k in universe_keys if k in ranks)
    )

    def keys_of(keywords: list[str]) -> list[str]:
        out: list[str] = []
        for keyword in keywords:
            key = keyword_key(keyword)
            if key in universe_keys and key not in out:
                out.append(key)
        return out

    groups: list[tuple[str, str, list[str]]] = []
    if assignment is not None:
        services = {keyword_key(name): words for name, words in assignment.services.items()}
        for topic in topics:
            words = assignment.services.get(topic, services.get(keyword_key(topic), []))
            groups.append((topic, "service", keys_of(words)))
        groups.append((LOCAL_TOPIC, "local", keys_of(assignment.local)))
    assigned = {key for _, _, keys in groups for key in keys}
    info.assigned = len(assigned)
    if not assigned:
        return Heatmap(state="no_keywords", message=NO_KEYWORDS_MESSAGE, universe=info)

    columns = [customer, *top5]
    lists = {d: {keyword_key(k) for k in raw.top10[d].keywords} for d in columns if d in raw.top10}

    def in_top10(domain: str, key: str) -> bool:
        if domain == customer and key in ranks:
            rank = ranks[key]
            return rank is not None and rank <= 10
        return key in lists.get(domain, set())

    def truncated(domain: str) -> bool:
        entry = raw.top10.get(domain)
        if entry is None or not entry.truncated:
            return False
        complete = {keyword_key(k) for k in [*entry.keywords, *entry.checked]}
        # Bij de klant zijn gevolgde zoekwoorden zeker (PRT), die tellen niet als onvolledig.
        open_keys = [k for k in assigned if not (domain == customer and k in ranks)]
        return any(k not in complete for k in open_keys)

    rows: list[HeatmapRow] = []
    for topic, kind, keys in groups:
        count = len(keys)
        cells: list[HeatmapCell] = []
        if count >= MIN_TOPIC_KEYWORDS:
            for domain in columns:
                hits = sum(1 for key in keys if in_top10(domain, key))
                pct = (200 * hits + count) // (2 * count)  # half naar boven afgerond
                cells.append(HeatmapCell(pct=pct, level=_level(pct)))
        rows.append(HeatmapRow(topic=topic, kind=kind, keywords=count, cells=cells))

    return Heatmap(
        state="ok",
        columns=[
            HeatmapColumn(domain=d, is_customer=d == customer, truncated=truncated(d)) for d in columns
        ],
        rows=rows,
        universe=info,
    )


def build_snapshot(
    raw: Raw,
    *,
    customer_domain: str,
    items: list[Candidate],
    classes: dict[str, DomainClass],
    top5: list[str],
    overrides: Overrides,
    topics: list[str],
    assignment: TopicAssignment | None,
    heatmap: Heatmap | None,
    sources: Sources,
    warnings: list[str],
) -> Snapshot:
    """De momentopname: concurrenten (de vijf, getoonde uitgesloten, overige handmatige),
    KPI's en de heatmap. `heatmap` meegegeven = overnemen, anders berekenen. `summary` is
    "skipped"; de worker vult die na de laatste Claude-aanroep."""
    customer = host_of(customer_domain)
    by_domain = {i.domain: i for i in items}
    excluded = shown_excluded(items, classes, overrides)
    manual_rest = [
        i.domain for i in items
        if i.origin == "manual" and i.domain not in top5 and i.domain not in excluded
    ]
    manual = set(_manual_order(overrides))

    rows: list[SnapshotCompetitor] = []
    for domain in [*top5, *excluded, *manual_rest]:
        if any(r.domain == domain for r in rows):
            continue
        item = by_domain.get(domain) or Candidate(
            domain=domain, origin="manual" if domain in manual else "ahrefs"
        )
        rows.append(_snapshot_competitor(item, raw, classes, in_top5=domain in top5))

    top = [r for r in rows if r.in_top5]
    basis = overlap_basis(raw)
    return Snapshot(
        overlap_basis=basis,
        tracked_sample=sample_size(raw) if basis == "tracked" else 0,
        warnings=list(warnings),
        sources=sources,
        kpis=_kpis(raw, customer, top),
        competitors_state="ok" if rows else "empty",
        competitors_message=None if rows else NO_COMPETITORS_MESSAGE,
        competitors=rows,
        heatmap=heatmap if heatmap is not None else _heatmap(raw, customer, top5, topics, assignment),
        summary=Summary(state="skipped"),
    )


def unit_estimate(*, with_heatmap: bool) -> int:
    """Ruwe schatting van een volledige verversing (A + D + E, plus F en de nacontrole voor
    zes domeinen), afgerond op honderdtallen. De aanvulling via SERP's (B) telt niet mee."""
    total = (
        max(UNITS_MIN_PER_REQUEST, CANDIDATE_LIMIT * UNITS_PER_COMPETITOR_ROW)
        + max(UNITS_MIN_PER_REQUEST, ESTIMATE_METRICS_DOMAINS * UNITS_PER_METRICS_ROW)
        + max(UNITS_MIN_PER_REQUEST, 3 * UNITS_PER_HISTORY_ROW)
    )
    if with_heatmap:
        per_domain = max(UNITS_MIN_PER_REQUEST, ESTIMATE_KEYWORDS_PER_DOMAIN * UNITS_PER_KEYWORD_ROW)
        # Plus de nacontrole van afgekapte lijsten: gemiddeld twee aanvragen per domein.
        total += (1 + TOP_COMPETITORS) * (per_domain + ESTIMATE_CHECK_UNITS_PER_DOMAIN)
    return (total + 50) // 100 * 100
