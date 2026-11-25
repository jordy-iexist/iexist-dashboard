"""Ophalen voor Zoekwoorden › Concurrenten: ProRankTracker en Ahrefs, binnen een unit-budget.

Drie functies, in de volgorde van de worker:
- `collect_candidates`: stap 0 (PRT), A (organische concurrenten), A2 (handmatige domeinen
  buiten A) en zo nodig B (aanvulling via de SERP's van gevolgde zoekwoorden);
- `collect_metrics`: stap D (cijfers per domein), E (verkeersgeschiedenis van de klant) en
  F (top 10-zoekwoorden per domein);
- `collect_keyword_checks`: nacontrole van afgekapte top 10-lijsten.

Elke functie geeft een nieuwe `Raw` terug; de meegegeven `Raw` blijft ongewijzigd. Wat al in
de invoer staat wordt niet opnieuw opgehaald (hergebruik bij "Bijwerken").

Elke Ahrefs-aanroep loopt via `UnitBudget`: vooraf een schatting (minimaal
`UNITS_MIN_PER_REQUEST`), achteraf de werkelijke kosten uit de responseheader. Past een stap
niet meer, dan wordt die overgeslagen en komt een korte omschrijving in `budget.skipped`.
Geen databasecode: de worker bewaart het resultaat.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from app.core.config import settings
from app.features.customers import rankings
from app.features.customers.quick_wins import best_prt, convert_prt
from app.features.keywords.schemas import (
    CANDIDATE_LIMIT,
    MIN_SHARED_KEYWORDS,
    TOP_COMPETITORS,
    TRACKED_SAMPLE_MAX,
    TRACKED_SAMPLE_MIN,
    UNITS_MIN_PER_REQUEST,
    UNITS_PER_COMPETITOR_ROW,
    UNITS_PER_HISTORY_ROW,
    UNITS_PER_KEYWORD_ROW,
    UNITS_PER_METRICS_ROW,
    UNITS_PER_SERP_ROW,
    Raw,
    RawCompetitor,
    RawMetrics,
    RawPrt,
    RawTop10,
    SerpHit,
    TrackedKeyword,
    TrafficPoint,
)
from app.services.ahrefs import client as ahrefs
from app.services.ahrefs.client import AhrefsServiceError

# Steekproef-SERP's: tien SERP-blokken, met features en sitelinks circa twintig rijen.
SERP_TOP_POSITIONS = 10
SERP_ROWS_ESTIMATE = 20
# `organic_rows` heeft position, url en type nodig; title gaat mee voor de paginatitels.
SERP_SELECT = ("position", "url", "type", "title")
# Nacontrole van een afgekapte lijst: zoekwoorden per aanvraag en aanvragen per domein.
# Gemeten: een `where` met 250 zoekwoorden werkt; 150 houdt het adres ruim onder de grens.
CHECK_CHUNK = 150
CHECK_MAX_REQUESTS = 4
# Na deze fouten heeft een volgende SERP-aanvraag geen zin.
_FATAL_CODES = {"not_configured", "unauthorized", "forbidden"}


class UnitBudget:
    """Ahrefs-units van één verversing: plafond, verbruik en overgeslagen stappen."""

    def __init__(self, cap: int):
        self.cap = cap
        self.spent = 0
        self.skipped: list[str] = []

    def allows(self, estimate: int) -> bool:
        return self.spent + estimate <= self.cap

    def add(self, units: int) -> None:
        self.spent += max(0, int(units or 0))


def _estimate(rows: int, per_row: int) -> int:
    return max(UNITS_MIN_PER_REQUEST, rows * per_row)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_own(domain: str, customer: str) -> bool:
    return bool(customer) and (domain == customer or domain.endswith(f".{customer}"))


def _int(value) -> int:
    try:
        return int(float(value)) if value is not None and not isinstance(value, bool) else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def _float(value) -> float | None:
    try:
        return float(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _opt_int(value) -> int | None:
    return _int(value) if _float(value) is not None else None


def _domains(values: list[str], customer: str) -> list[str]:
    """Genormaliseerd, ontdubbeld, zonder het klantdomein en zijn subdomeinen."""
    out: list[str] = []
    for value in values:
        domain = rankings.host_of(value)
        if domain and not _is_own(domain, customer) and domain not in out:
            out.append(domain)
    return out


# --- stap 0: ProRankTracker -------------------------------------------------------------------


def _collect_prt(base_url: str) -> RawPrt:
    """Gevolgde zoekwoorden, één per zoekwoord (beste positie wint). Gooit nooit."""
    state, rows, message = rankings.organic_rows(base_url)
    if state != "ok":
        return RawPrt(state=state, message=message or rankings.STATE_MESSAGES.get(state))
    try:
        tracked = []
        for raw in best_prt(rows).values():
            row = convert_prt(raw)
            if row["keyword"]:
                tracked.append(
                    TrackedKeyword(keyword=row["keyword"], rank=row["position"], volume=row["volume"])
                )
    except (AttributeError, KeyError, TypeError, ValueError):
        return RawPrt(state="error", message=rankings.UNEXPECTED_MESSAGE)
    if not tracked:
        return RawPrt(state="not_tracked", message=rankings.STATE_MESSAGES["not_tracked"])
    return RawPrt(state="ok", rows=tracked)


# --- stap A, A2 en B: kandidaten --------------------------------------------------------------


def _competitor_rows(rows: list[dict], customer: str) -> list[RawCompetitor]:
    out: list[RawCompetitor] = []
    seen: set[str] = set()
    for row in rows:
        domain = rankings.host_of(row.get("competitor_domain"))
        if not domain or _is_own(domain, customer) or domain in seen:
            continue
        seen.add(domain)
        out.append(RawCompetitor(
            domain=domain,
            domain_rating=_float(row.get("domain_rating")),
            keywords_common=_int(row.get("keywords_common")),
            keywords_competitor=_int(row.get("keywords_competitor")),
            keywords_target=_int(row.get("keywords_target")),
            share=_float(row.get("share")) or 0.0,
        ))
    return out


def _tracked_sample(prt: RawPrt) -> list[str]:
    """De gevolgde zoekwoorden met het hoogste volume (zonder volume achteraan)."""
    rows = sorted(
        prt.rows,
        key=lambda r: (r.volume is None, -(r.volume or 0), rankings.keyword_key(r.keyword)),
    )
    return [r.keyword for r in rows[:TRACKED_SAMPLE_MAX]]


def _needs_sample(raw: Raw) -> bool:
    usable = sum(1 for c in raw.competitors or [] if c.keywords_common >= MIN_SHARED_KEYWORDS)
    prt = raw.prt
    return (
        usable < TOP_COMPETITORS
        and prt is not None
        and prt.state == "ok"
        and len(prt.rows) >= TRACKED_SAMPLE_MIN
    )


def _collect_serps(raw: Raw, *, customer: str, country: str, budget: UnitBudget) -> dict[str, list[SerpHit]]:
    serps: dict[str, list[SerpHit]] = {}
    sample = _tracked_sample(raw.prt)
    estimate = _estimate(SERP_ROWS_ESTIMATE, UNITS_PER_SERP_ROW)
    for index, keyword in enumerate(sample):
        if not budget.allows(estimate):
            budget.skipped.append(
                f"{len(sample) - index} van {len(sample)} SERP's voor de aanvulling via gevolgde zoekwoorden"
            )
            break
        try:
            result = ahrefs.serp_overview(
                keyword, country=country, top_positions=SERP_TOP_POSITIONS, fields=SERP_SELECT
            )
        except AhrefsServiceError as exc:
            if exc.code in _FATAL_CODES:
                break
            continue  # alleen dit zoekwoord overslaan
        budget.add(result.units)
        hits: list[SerpHit] = []
        for row in ahrefs.organic_rows(result, SERP_TOP_POSITIONS):
            domain = rankings.host_of(row.get("url"))
            if not domain or _is_own(domain, customer):
                continue
            title = str(row.get("title") or "").strip() or None
            hits.append(SerpHit(domain=domain, position=row["organic_position"], title=title))
        serps[keyword] = hits
    return serps


def collect_candidates(
    *,
    base_url: str,
    country: str,
    manual_domains: list[str],
    previous: Raw | None,
    budget: UnitBudget,
) -> Raw:
    """Stap 0 (PRT), A, A2 en zo nodig B.

    `previous` (alleen bij mode "reuse"): alles wat erin staat wordt overgenomen, inclusief
    `fetched_at`; alleen ontbrekende onderdelen worden opgehaald. Gooit `AhrefsServiceError`
    als stap A mislukt; PRT-fouten staan in `raw.prt.state`.
    """
    customer = rankings.host_of(base_url)
    raw = previous.model_copy(deep=True) if previous is not None else Raw(fetched_at=_now())

    # Stap 0: gevolgde zoekwoorden (kost geen Ahrefs-units).
    if raw.prt is None:
        raw.prt = _collect_prt(base_url)

    # Stap A: organische concurrenten van het klantdomein.
    if raw.competitors is None:
        if budget.allows(_estimate(CANDIDATE_LIMIT, UNITS_PER_COMPETITOR_ROW)):
            result = ahrefs.organic_competitors(customer, country=country, limit=CANDIDATE_LIMIT)
            budget.add(result.units)
            raw.competitors = _competitor_rows(result.rows, customer)
        else:
            budget.skipped.append(f"organische concurrenten van {customer}")

    # Stap A2: handmatige domeinen die niet in A zitten, in één aanroep.
    known = {c.domain for c in raw.competitors or []}
    missing = [d for d in _domains(manual_domains, customer) if d not in known]
    if missing:
        if budget.allows(_estimate(len(missing), UNITS_PER_COMPETITOR_ROW)):
            try:
                result = ahrefs.organic_competitors(customer, country=country, domains=missing)
            except AhrefsServiceError as exc:
                budget.skipped.append(f"overlap van handmatige concurrenten ({exc})")
            else:
                budget.add(result.units)
                found = _competitor_rows(result.rows, customer)
                found_domains = {c.domain for c in found}
                # Een domein zonder gedeelde zoekwoorden komt niet terug: bewaar 0/0, zodat
                # "Bijwerken" het niet steeds opnieuw navraagt.
                found += [RawCompetitor(domain=d) for d in missing if d not in found_domains]
                raw.competitors = (raw.competitors or []) + found
        else:
            budget.skipped.append("overlap van handmatige concurrenten")

    # Stap B: te weinig bruikbare concurrenten, dan de SERP's van gevolgde zoekwoorden.
    if raw.serps is None and _needs_sample(raw):
        raw.serps = _collect_serps(raw, customer=customer, country=country, budget=budget)

    return raw


# --- stap D, E en F: cijfers per domein -------------------------------------------------------


def _months_back(today: date, months: int) -> date:
    """Eerste dag van de maand `months` maanden vóór `today`."""
    index = today.year * 12 + (today.month - 1) - months
    return date(index // 12, index % 12 + 1, 1)


def _traffic_points(rows: list[dict]) -> list[TrafficPoint]:
    points: list[TrafficPoint] = []
    for row in rows:
        day = str(row.get("date") or "")[:10]
        traffic = _opt_int(row.get("org_traffic"))
        if day and traffic is not None:
            points.append(TrafficPoint(date=day, org_traffic=traffic))
    return sorted(points, key=lambda p: p.date)


def _keyword_list(rows: list[dict]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        keyword = str(row.get("keyword") or "").strip()
        key = rankings.keyword_key(keyword)
        if key and key not in seen:
            seen.add(key)
            out.append(keyword)
    return out


def collect_metrics(
    raw: Raw,
    *,
    base_url: str,
    country: str,
    domains: list[str],
    keyword_domains: list[str],
    budget: UnitBudget,
) -> Raw:
    """Stap D voor klant + `domains`, E voor de klant en F voor klant + `keyword_domains`.

    Slaat over wat al in `raw` staat. `keyword_domains` leeg = stap F helemaal overslaan (ook
    voor de klant). Een Ahrefs-fout slaat alleen die stap (bij F: dat domein) over en komt in
    `budget.skipped`.
    """
    raw = raw.model_copy(deep=True)
    customer = rankings.host_of(base_url)

    # Stap D: cijfers per domein in één batch.
    wanted = [d for d in [customer, *_domains(domains, customer)] if d and d not in raw.metrics]
    if wanted:
        if budget.allows(_estimate(len(wanted), UNITS_PER_METRICS_ROW)):
            try:
                result = ahrefs.domains_metrics(wanted, country=country)
            except AhrefsServiceError as exc:
                budget.skipped.append(f"cijfers per domein ({exc})")
            else:
                budget.add(result.units)
                by_target = {row.get("target"): row for row in result.rows}
                for domain in wanted:
                    row = by_target.get(domain) or {}
                    raw.metrics[domain] = RawMetrics(
                        domain_rating=_float(row.get("domain_rating")),
                        org_keywords=_opt_int(row.get("org_keywords")),
                        org_keywords_1_3=_opt_int(row.get("org_keywords_1_3")),
                        org_keywords_4_10=_opt_int(row.get("org_keywords_4_10")),
                        org_traffic=_opt_int(row.get("org_traffic")),
                    )
        else:
            budget.skipped.append("cijfers per domein")

    # Stap E: verkeer per maand van de klant (twee maanden terug, voor de wijziging).
    if raw.traffic_history is None and customer:
        if budget.allows(_estimate(3, UNITS_PER_HISTORY_ROW)):
            try:
                result = ahrefs.metrics_history(
                    customer, country=country, date_from=_months_back(date.today(), 2)
                )
            except AhrefsServiceError as exc:
                budget.skipped.append(f"verkeersgeschiedenis van {customer} ({exc})")
            else:
                budget.add(result.units)
                raw.traffic_history = _traffic_points(result.rows)
        else:
            budget.skipped.append(f"verkeersgeschiedenis van {customer}")

    # Stap F: top 10-zoekwoorden per domein (zonder onderwerpen geen heatmap, dus niet nodig).
    if keyword_domains:
        limit = settings.ahrefs_competitors_keywords_per_domain
        estimate = _estimate(limit, UNITS_PER_KEYWORD_ROW)
        for domain in [customer, *_domains(keyword_domains, customer)]:
            if not domain or domain in raw.top10:
                continue
            if not budget.allows(estimate):
                budget.skipped.append(f"top 10-zoekwoorden van {domain}")
                continue
            try:
                result = ahrefs.top10_keywords(domain, country=country, limit=limit)
            except AhrefsServiceError as exc:
                budget.skipped.append(f"top 10-zoekwoorden van {domain} ({exc})")
                continue
            budget.add(result.units)
            raw.top10[domain] = RawTop10(
                keywords=_keyword_list(result.rows), truncated=len(result.rows) >= limit
            )

    return raw


# --- nacontrole -------------------------------------------------------------------------------


def collect_keyword_checks(
    raw: Raw,
    *,
    base_url: str,
    country: str,
    keywords: list[str],
    budget: UnitBudget,
) -> Raw:
    """Nacontrole van afgekapte lijsten in `raw.top10`.

    Per afgekapt domein de `keywords` die nog niet in zijn lijst of `checked` staan navragen,
    in delen van `CHECK_CHUNK` en hoogstens `CHECK_MAX_REQUESTS` aanvragen per domein.
    Gevonden zoekwoorden gaan naar `keywords`, alle nagevraagde naar `checked`. `base_url`
    hoort bij het contract maar is hier niet nodig: het klantdomein staat al in `raw.top10`.
    """
    raw = raw.model_copy(deep=True)
    for domain, entry in raw.top10.items():
        if not entry.truncated:
            continue
        known = {rankings.keyword_key(k) for k in [*entry.keywords, *entry.checked]}
        todo: list[str] = []
        for keyword in keywords:
            key = rankings.keyword_key(keyword)
            if key and key not in known:
                known.add(key)
                todo.append(keyword.strip())
        chunks = [todo[i:i + CHECK_CHUNK] for i in range(0, len(todo), CHECK_CHUNK)]
        for chunk in chunks[:CHECK_MAX_REQUESTS]:
            if not budget.allows(_estimate(len(chunk), UNITS_PER_KEYWORD_ROW)):
                budget.skipped.append(f"nacontrole van de zoekwoorden van {domain}")
                break
            try:
                result = ahrefs.top10_keywords(domain, country=country, limit=len(chunk), keywords=chunk)
            except AhrefsServiceError as exc:
                budget.skipped.append(f"nacontrole van de zoekwoorden van {domain} ({exc})")
                break
            budget.add(result.units)
            found = {rankings.keyword_key(row.get("keyword")) for row in result.rows}
            entry.keywords += [k for k in chunk if rankings.keyword_key(k) in found]
            entry.checked += chunk
    return raw
