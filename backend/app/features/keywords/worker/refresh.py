"""Celery-taak: het concurrentenoverzicht van één klant verversen (Zoekwoorden › Concurrenten).

Statussen op `customer_competitor_overviews`: pending → collecting ⇄ classifying → summarizing
→ completed, of failed met een melding. Elke statuswissel werkt `updated_at` bij (het
levensteken voor het herstel van vastgelopen runs in de router). Bij een fout blijven `data` en
`raw` van de vorige geslaagde run staan: alles wordt pas aan het eind in één UPDATE geschreven.
`overrides` en `overrides_changed_at` raakt de taak nooit aan; de router kan ze tijdens de run
bijwerken (de taak leest ze één keer bij de start).

1. Atomair claimen (`pending` → `collecting`, `started_at`); een tweede aflevering doet niets.
2. Kandidaten ophalen (`collect.collect_candidates`); een Ahrefs-fout hier = run `failed`.
3. Domeinen laten indelen door Claude (`ai.classify_domains`); bij mode "reuse" alleen nieuwe.
4. Cijfers per domein (`collect.collect_metrics`).
5. Heatmap: zoekwoorden laten indelen (`ai.assign_keywords`) en nacontroleren.
6. Momentopname berekenen (`compute.build_snapshot`).
7. Samenvatting "Kansen" (`ai.summarize`).
8. Alles in één keer wegschrijven.

Een Claude-fout raakt alleen het betreffende onderdeel (type-badges, heatmap of samenvatting).
Geen sleutels, prompts of klantgegevens in logregels en foutmeldingen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from app.core.config import settings
from app.db.models import CustomerCompetitorOverview as Row, CustomerWebsite
from app.db.session import SessionLocal
from app.features.competitor_analysis.schemas import AiUsage
from app.features.competitor_analysis.services.insights import NOT_CONFIGURED_MESSAGE, add_usage
from app.features.customers.profile import CustomerProfile, parse_profile
from app.features.keywords.mappers import (
    blocked_of,
    customer_domain,
    overrides_of,
    reusable_raw,
    snapshot_of,
)
from app.features.keywords.schemas import (
    ACTIVE_OVERVIEW_STATUSES,
    COUNTRY,
    DomainClass,
    Heatmap,
    Overrides,
    Raw,
    RawPrt,
    RefreshMode,
    SourceInfo,
    Sources,
    Summary,
    TopicAssignment,
)
from app.features.keywords.services import ai, collect, compute
from app.services.ahrefs import AhrefsServiceError
from app.services.anthropic import client as claude
from app.services.anthropic.client import AnthropicServiceError
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)

TIMEOUT_MESSAGE = "Het ophalen van de concurrenten duurde te lang en is afgebroken. Probeer het opnieuw."
GONE_MESSAGE = "De klant bestaat niet meer."
AHREFS_FAILED_MESSAGE = "Ahrefs gaf een fout bij het ophalen van de concurrenten: {detail}"
NO_PROFILE_MESSAGE = ("Het klantprofiel heeft nog geen diensten. Vul de diensten in het klantprofiel in om "
                      "de onderwerpen te zien.")
NO_PROFILE_SOURCE_MESSAGE = "Het klantprofiel heeft geen diensten."
CLASSIFY_FAILED_WARNING = "Claude kon de concurrenten niet indelen; type en vergelijkingssites ontbreken."
ASSIGN_FAILED_MESSAGE = "Claude kon de zoekwoorden niet bij de diensten indelen: {detail}"
SUMMARY_FAILED_MESSAGE = "Claude kon de samenvatting niet schrijven: {detail}"
SUMMARY_SKIPPED_MESSAGE = "Geen concurrenten om te vergelijken."
BUDGET_WARNING = "Unit-plafond bereikt: {step} overgeslagen."
# `collect` zet ook stappen die door een Ahrefs-fout zijn overgeslagen in `budget.skipped`,
# met de fout tussen haakjes erachter: "cijfers per domein (Ahrefs-fout …)".
AHREFS_SKIP_WARNING = "Ahrefs gaf een fout: {step} overgeslagen ({detail})."
_SKIP_WITH_ERROR_RE = re.compile(r"^(?P<step>.+?) \((?P<detail>.+)\)$")
PRT_NOT_TRACKED_WARNING = ("Deze site staat niet in ProRankTracker; de heatmap rekent alleen met "
                           "Ahrefs-zoekwoorden.")
PRT_ERROR_WARNING = "ProRankTracker gaf een fout; gevolgde zoekwoorden tellen niet mee."


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
            Row.customer_website_id == customer_id, Row.status.in_(ACTIVE_OVERVIEW_STATUSES),
        ).update(fields, synchronize_session=False)
        db.commit()


def _fail(customer_id: str, message: str) -> None:
    try:
        _update(customer_id, status="failed", error_message=message[:1000])
    except Exception:  # noqa: BLE001 - laatste poging; niets meer aan te doen
        logger.exception("Concurrenten %s: status 'failed' niet opgeslagen", customer_id)


@dataclass
class _Context:
    """Wat de run bij de start uit de database leest."""

    name: str
    base_url: str
    domain: str
    profile: CustomerProfile
    overrides: Overrides
    previous_raw: Raw | None = None
    previous_classes: dict[str, DomainClass] = field(default_factory=dict)

    @property
    def services(self) -> list[str]:
        return [service.name for service in self.profile.services if service.name]

    @property
    def manual(self) -> list[str]:
        return [entry.domain for entry in self.overrides.manual]


def _load(customer_id: str, mode: RefreshMode) -> _Context:
    with SessionLocal() as db:
        row = db.get(Row, customer_id)
        customer = db.get(CustomerWebsite, customer_id)
        if row is None or customer is None:
            raise _Failed(GONE_MESSAGE)
        blocked = blocked_of(customer)
        if blocked is not None:
            raise _Failed(blocked[1])
        domain = customer_domain(customer)
        context = _Context(
            name=customer.name or domain,
            base_url=str(customer.base_url or ""),
            domain=domain,
            profile=parse_profile(customer.profile),
            overrides=overrides_of(row),
        )
        if mode == "reuse":
            context.previous_raw = reusable_raw(row, domain)
            snapshot = snapshot_of(row)
            if snapshot is not None and row.target == domain and (row.country or COUNTRY) == COUNTRY:
                context.previous_classes = {
                    competitor.domain: DomainClass(type=competitor.ai_type,
                                                   is_aggregator=competitor.ai_is_aggregator,
                                                   reason=competitor.ai_reason or "")
                    for competitor in snapshot.competitors if competitor.ai_type is not None
                }
        return context


def skipped_warning(step: str) -> str:
    """Waarschuwing voor één overgeslagen stap uit `budget.skipped`."""
    match = _SKIP_WITH_ERROR_RE.match(step)
    if match:
        return AHREFS_SKIP_WARNING.format(step=match["step"], detail=match["detail"])
    return BUDGET_WARNING.format(step=step)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


# --- de taak -------------------------------------------------------------------------------


@dataclass
class _Usage:
    total: AiUsage = field(default_factory=AiUsage)
    model: str | None = None

    def add(self, usage: dict, model: str | None) -> None:
        self.total = add_usage(self.total, usage, model)
        self.model = model or self.model


def _run(customer_id: str, mode: RefreshMode) -> None:
    ctx = _load(customer_id, mode)
    claude_ready = claude.is_configured()
    usage = _Usage()
    warnings: list[str] = []
    claude_source = SourceInfo(state="ok") if claude_ready else SourceInfo(state="not_configured",
                                                                             message=NOT_CONFIGURED_MESSAGE)

    # 2. Kandidaten (PRT, Ahrefs-concurrenten, zo nodig de aanvulling via gevolgde zoekwoorden).
    budget = collect.UnitBudget(settings.ahrefs_competitors_max_units)
    try:
        raw = collect.collect_candidates(base_url=ctx.base_url, country=COUNTRY, manual_domains=ctx.manual,
                                         previous=ctx.previous_raw, budget=budget)
    except AhrefsServiceError as exc:
        raise _Failed(AHREFS_FAILED_MESSAGE.format(detail=exc)) from exc
    items = compute.candidates(raw, customer_domain=ctx.domain, manual_domains=ctx.manual)

    # 3. Domeinen indelen; bij "reuse" alleen wat nog geen oordeel heeft.
    known = {item.domain for item in items}
    classes = {domain: value for domain, value in ctx.previous_classes.items() if domain in known}
    todo = [item for item in items if item.domain not in classes]
    if claude_ready and todo:
        _update(customer_id, status="classifying")
        try:
            result, call_usage, model = ai.classify_domains(
                todo, customer_domain=ctx.domain, company_type=ctx.profile.company_type,
                service_area=ctx.profile.service_area,
            )
        except AnthropicServiceError as exc:
            logger.warning("Concurrenten %s: Claude-fout bij het indelen (%s)", customer_id, exc.code)
            claude_source = SourceInfo(state="error", message=exc.message)
            warnings.append(CLASSIFY_FAILED_WARNING)
        else:
            classes.update(result)
            usage.add(call_usage, model)

    # 4. Cijfers per domein; top 10-zoekwoorden alleen als er een heatmap komt.
    _update(customer_id, status="collecting")
    top5 = compute.select_top5(items, classes, ctx.overrides)
    excluded = compute.shown_excluded(items, classes, ctx.overrides)
    services = ctx.services
    with_heatmap = bool(services) and claude_ready
    raw = collect.collect_metrics(raw, base_url=ctx.base_url, country=COUNTRY,
                                  domains=_dedupe(top5 + excluded + ctx.manual),
                                  keyword_domains=list(top5) if with_heatmap else [], budget=budget)

    # 5. Heatmap: zoekwoorden indelen bij de diensten en nacontroleren.
    heatmap: Heatmap | None = None
    assignment: TopicAssignment | None = None
    if not services:
        heatmap = Heatmap(state="no_profile", message=NO_PROFILE_MESSAGE)
    elif not claude_ready:
        heatmap = Heatmap(state="not_configured", message=NOT_CONFIGURED_MESSAGE)
    else:
        universe = compute.keyword_universe(raw, customer_domain=ctx.domain, top5=top5)
        _update(customer_id, status="classifying")
        try:
            assignment, call_usage, model = ai.assign_keywords(
                universe, services, company_type=ctx.profile.company_type, service_area=ctx.profile.service_area,
            )
        except AnthropicServiceError as exc:
            logger.warning("Concurrenten %s: Claude-fout bij de zoekwoorden (%s)", customer_id, exc.code)
            heatmap = Heatmap(state="error", message=ASSIGN_FAILED_MESSAGE.format(detail=exc.message))
            assignment = None
        else:
            usage.add(call_usage, model)
            _update(customer_id, status="collecting")
            keywords = _dedupe([kw for values in assignment.services.values() for kw in values] + assignment.local)
            raw = collect.collect_keyword_checks(raw, base_url=ctx.base_url, country=COUNTRY, keywords=keywords,
                                                 budget=budget)

    # 6. De momentopname.
    prt = raw.prt or RawPrt()
    if prt.state == "not_tracked":
        warnings.append(PRT_NOT_TRACKED_WARNING)
    elif prt.state == "error":
        warnings.append(PRT_ERROR_WARNING)
    warnings = [skipped_warning(step) for step in budget.skipped] + warnings
    sources = Sources(
        ahrefs=SourceInfo(state="ok"),
        prt=SourceInfo(state=prt.state, message=prt.message),
        claude=claude_source,
        profile=SourceInfo(state="ok") if services else SourceInfo(state="empty", message=NO_PROFILE_SOURCE_MESSAGE),
    )
    snapshot = compute.build_snapshot(
        raw, customer_domain=ctx.domain, items=items, classes=classes, top5=top5, overrides=ctx.overrides,
        topics=services, assignment=assignment, heatmap=heatmap, sources=sources, warnings=warnings,
    )

    # 7. Samenvatting "Kansen".
    if not claude_ready:
        summary = Summary(state="not_configured", message=NOT_CONFIGURED_MESSAGE)
    elif not top5:
        summary = Summary(state="skipped", message=SUMMARY_SKIPPED_MESSAGE)
    else:
        _update(customer_id, status="summarizing")
        try:
            summary, call_usage, model = ai.summarize(snapshot, customer_name=ctx.name)
        except AnthropicServiceError as exc:
            logger.warning("Concurrenten %s: Claude-fout bij de samenvatting (%s)", customer_id, exc.code)
            summary = Summary(state="error", message=SUMMARY_FAILED_MESSAGE.format(detail=exc.message))
        else:
            usage.add(call_usage, model)
    snapshot = snapshot.model_copy(update={"summary": summary})

    # 8. Alles in één keer; `overrides` en `overrides_changed_at` blijven ongemoeid.
    _update(customer_id, status="completed", data=snapshot.model_dump(mode="json"), raw=raw.model_dump(mode="json"),
            target=ctx.domain, country=COUNTRY, ahrefs_units=int(budget.spent),
            ai_usage=usage.total.model_dump(mode="json"), model=usage.model, completed_at=_now(),
            error_message=None)


@celery_app.task(
    bind=True,
    name="app.worker.tasks.refresh_keyword_competitors_task",
    soft_time_limit=540,
    time_limit=600,
)
def refresh_keyword_competitors_task(self, customer_id: str, mode: str = "full") -> str:
    """Ververst het concurrentenoverzicht van één klant (zie de module-docstring)."""
    if not _claim(customer_id):
        logger.info("Concurrenten %s niet gestart: niet gevonden of niet meer 'pending'.", customer_id)
        return customer_id
    try:
        _run(customer_id, "reuse" if mode == "reuse" else "full")
    except SoftTimeLimitExceeded:
        logger.warning("Concurrenten %s: tijdslimiet bereikt.", customer_id)
        _fail(customer_id, TIMEOUT_MESSAGE)
    except AhrefsServiceError as exc:
        logger.warning("Concurrenten %s: Ahrefs-fout (%s)", customer_id, exc.code)
        _fail(customer_id, AHREFS_FAILED_MESSAGE.format(detail=exc))
    except _Failed as exc:
        logger.warning("Concurrenten %s mislukt: %s", customer_id, exc)
        _fail(customer_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Concurrenten %s onverwacht mislukt", customer_id)
        _fail(customer_id, f"Het ophalen is gestopt door een interne fout ({type(exc).__name__}).")
    return customer_id
