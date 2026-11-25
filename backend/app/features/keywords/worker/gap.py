"""Celery-taak: de content gap van één klant ophalen (Zoekwoorden › Content gap).

Statussen op `customer_keyword_gaps`: pending → collecting → enriching → completed, of failed
met een melding. Elke statuswissel werkt `updated_at` bij (het levensteken voor het herstel van
vastgelopen runs in de router). Bij een fout blijft `data` van de vorige geslaagde run staan:
het resultaat wordt pas aan het eind in één UPDATE geschreven. Geen AI in deze stap.

1. Atomair claimen (`pending` → `collecting`, `started_at`); een tweede aflevering doet niets.
2. Lijsten: de top 10-zoekwoorden van klant en de vijf uit de concurrentenscan
   (`gap_collect.collect_lists`; wat in `raw.top10` staat kost niets).
3. Kandidaten: in minstens twee lijsten van de vijf en niet in die van de klant
   (`gap_compute.candidates`).
4. Afkappen op K = resterend budget // `UNITS_PER_GAP_KEYWORD`.
5. Posities navragen bij de vijf (top 10) en bij de klant (zonder grens).
6. `enriching`: volume, KD en intentie (`gap_collect.collect_facts`).
7. Eindlijst berekenen (`gap_compute.build_snapshot`) en alles in één keer wegschrijven.

Een overgeslagen stap (plafond bereikt of een Ahrefs-fout) komt als waarschuwing op het
scherm. Geen sleutels of klantgegevens in logregels en foutmeldingen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from app.core.config import settings
from app.db.models import CustomerCompetitorOverview, CustomerKeywordGap as Row, CustomerWebsite
from app.db.session import SessionLocal
from app.features.competitor_analysis.mappers import _model
from app.features.keywords.gap_mappers import blocked_of, scan_top5
from app.features.keywords.gap_schemas import ACTIVE_GAP_STATUSES, MIN_COMPETITORS, TOP10, PositionCheck
from app.features.keywords.mappers import customer_domain
from app.features.keywords.schemas import COUNTRY, Raw
from app.features.keywords.services import gap_collect, gap_compute
from app.features.keywords.services.collect import UnitBudget
from app.features.keywords.worker.refresh import skipped_warning
from app.services.ahrefs import AhrefsServiceError
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)

TIMEOUT_MESSAGE = "Het ophalen van de content gap duurde te lang en is afgebroken. Probeer het opnieuw."
GONE_MESSAGE = "De klant bestaat niet meer."
AHREFS_FAILED_MESSAGE = "Ahrefs gaf een fout bij het ophalen van de content gap: {detail}"
TOO_FEW_LISTS_MESSAGE = (f"Van minder dan {MIN_COMPETITORS} concurrenten konden de zoekwoorden worden opgehaald; "
                         "er is geen content gap te bepalen. Probeer het later opnieuw.")
NO_ROOM_WARNING = "Unit-plafond bereikt: er was geen budget meer om zoekwoorden uit te werken."


class _Failed(Exception):
    """De run kan niet verder; de tekst is de melding voor de gebruiker."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- database ------------------------------------------------------------------------------


def _claim(customer_id: str) -> bool:
    """`pending` → `collecting` in één update; False als de rij niet (meer) op `pending` staat."""
    now = _now()
    with SessionLocal() as db:
        count = db.query(Row).filter(
            Row.customer_website_id == customer_id, Row.status == "pending",
        ).update({"status": "collecting", "started_at": now, "updated_at": now}, synchronize_session=False)
        db.commit()
        return count == 1


def _update(customer_id: str, **fields: Any) -> None:
    """Werk de rij bij (altijd `updated_at`), maar alleen zolang de run actief is."""
    fields["updated_at"] = _now()
    with SessionLocal() as db:
        db.query(Row).filter(
            Row.customer_website_id == customer_id, Row.status.in_(ACTIVE_GAP_STATUSES),
        ).update(fields, synchronize_session=False)
        db.commit()


def _fail(customer_id: str, message: str) -> None:
    try:
        _update(customer_id, status="failed", error_message=message[:1000])
    except Exception:  # noqa: BLE001 - laatste poging; niets meer aan te doen
        logger.exception("Content gap %s: status 'failed' niet opgeslagen", customer_id)


@dataclass
class _Context:
    """Wat de run bij de start uit de database leest."""

    domain: str
    competitors: list[str]
    raw: Raw
    source_completed_at: datetime | None


def _load(customer_id: str) -> _Context:
    with SessionLocal() as db:
        row = db.get(Row, customer_id)
        customer = db.get(CustomerWebsite, customer_id)
        if row is None or customer is None:
            raise _Failed(GONE_MESSAGE)
        scan = db.get(CustomerCompetitorOverview, customer_id)
        blocked = blocked_of(customer, scan)
        if blocked is not None:
            raise _Failed(blocked[1])
        domain = customer_domain(customer)
        return _Context(
            domain=domain,
            competitors=scan_top5(scan, domain) or [],
            raw=_model(Raw, scan.raw) or Raw(),
            source_completed_at=scan.completed_at,
        )


# --- de taak -------------------------------------------------------------------------------


def _run(customer_id: str) -> None:
    ctx = _load(customer_id)
    budget = UnitBudget(settings.ahrefs_content_gap_max_units)

    # 2. Lijsten (uit de scan; ontbrekende ophalen).
    lists = gap_collect.collect_lists(ctx.raw, customer_domain=ctx.domain, competitors=ctx.competitors,
                                      country=COUNTRY, budget=budget)
    if sum(1 for domain in ctx.competitors if domain in lists) < MIN_COMPETITORS:
        raise _Failed(TOO_FEW_LISTS_MESSAGE)

    # 3 + 4. Kandidaten, afgekapt op wat het resterende budget kan uitwerken.
    items = gap_compute.candidates(lists, customer_domain=ctx.domain, competitors=ctx.competitors)
    limit = gap_compute.max_keywords(budget.cap - budget.spent)
    worked = [item.keyword for item in items[:limit]]
    extra: list[str] = []
    if items and not worked:
        extra.append(NO_ROOM_WARNING)

    # 5. Posities: de vijf binnen de top 10, de klant zonder grens.
    checks: dict[str, PositionCheck] = {}
    if worked:
        for domain in ctx.competitors:
            checks[domain] = gap_collect.collect_positions(domain, worked, country=COUNTRY, max_position=TOP10,
                                                           budget=budget)
        checks[ctx.domain] = gap_collect.collect_positions(ctx.domain, worked, country=COUNTRY, max_position=None,
                                                           budget=budget)

    # 6. Volume, KD en intentie voor wat na de klantcontrole overblijft (klant in de top 10 vervalt).
    facts = {}
    own = checks[ctx.domain].positions if worked else {}
    remaining = [item.keyword for item in items[:limit] if own.get(item.key, TOP10 + 1) > TOP10]
    if remaining:
        _update(customer_id, status="enriching")
        facts = gap_collect.collect_facts(remaining, country=COUNTRY, budget=budget)

    # 7. Eindlijst en alles in één keer wegschrijven.
    warnings = [skipped_warning(step) for step in budget.skipped] + extra
    snapshot = gap_compute.build_snapshot(items, limit=limit, customer_domain=ctx.domain,
                                          competitors=ctx.competitors, checks=checks, facts=facts,
                                          warnings=warnings)
    _update(customer_id, status="completed", data=snapshot.model_dump(mode="json"), target=ctx.domain,
            country=COUNTRY, ahrefs_units=int(budget.spent), source_completed_at=ctx.source_completed_at,
            completed_at=_now(), error_message=None)


@celery_app.task(
    bind=True,
    name="app.worker.tasks.run_content_gap_task",
    soft_time_limit=540,
    time_limit=600,
)
def run_content_gap_task(self, customer_id: str) -> str:
    """Haalt de content gap van één klant op (zie de module-docstring)."""
    if not _claim(customer_id):
        logger.info("Content gap %s niet gestart: niet gevonden of niet meer 'pending'.", customer_id)
        return customer_id
    try:
        _run(customer_id)
    except SoftTimeLimitExceeded:
        logger.warning("Content gap %s: tijdslimiet bereikt.", customer_id)
        _fail(customer_id, TIMEOUT_MESSAGE)
    except AhrefsServiceError as exc:
        logger.warning("Content gap %s: Ahrefs-fout (%s)", customer_id, exc.code)
        _fail(customer_id, AHREFS_FAILED_MESSAGE.format(detail=exc))
    except _Failed as exc:
        logger.warning("Content gap %s mislukt: %s", customer_id, exc)
        _fail(customer_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Content gap %s onverwacht mislukt", customer_id)
        _fail(customer_id, f"Het ophalen is gestopt door een interne fout ({type(exc).__name__}).")
    return customer_id
