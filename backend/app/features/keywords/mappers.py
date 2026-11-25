"""Rij van `customer_competitor_overviews` + klant omzetten naar `CompetitorOverview`.

Pure functies (op `ahrefs.is_configured()` na). Verdraagzaam voor lege of ongeldige
JSON-kolommen: die gelden als afwezig, zodat elk endpoint in elke fase van een run een geldig
antwoord geeft. De handmatige keuzes (`overrides`) worden bij elk lezen op de momentopname
toegepast; een type-wijziging is dus direct zichtbaar zonder nieuwe run.

Ook de gedeelde regels voor router en worker staan hier: wanneer ophalen geblokkeerd is
(`blocked_of`), wanneer een momentopname verlopen is (`is_expired`) en wanneer de ruwe gegevens
van de vorige run nog bruikbaar zijn (`reusable_raw`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import settings
from app.db.models import CustomerCompetitorOverview, CustomerWebsite
from app.features.competitor_analysis.mappers import _choice, _model
from app.features.competitor_analysis.schemas import AiUsage
from app.features.customers.profile import parse_profile
from app.features.customers.rankings import host_of
from app.features.keywords.schemas import (
    ACTIVE_OVERVIEW_STATUSES,
    COUNTRY,
    BlockedReason,
    CompetitorOverview,
    CompetitorRow,
    CompetitorsSection,
    DomainChoice,
    Heatmap,
    OverviewStatus,
    Overrides,
    Raw,
    Snapshot,
    SnapshotCompetitor,
    Summary,
)
from app.features.keywords.services import compute
from app.features.launch_checklist.services.scan_recovery import as_utc
from app.services import ahrefs

BLOCKED_MESSAGES: dict[str, str] = {
    "ahrefs_not_configured": "Ahrefs is niet gekoppeld: AHREFS_API_KEY ontbreekt in de backend-configuratie.",
    "no_website": "Deze klant heeft nog geen website-adres. Vul het adres in bij het klantprofiel om "
                  "concurrenten op te halen.",
}
EXCLUDED_MANUAL_REASON = "handmatig uitgesloten"
EXCLUDED_AI_REASON = "vergelijkingssite"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ttl() -> timedelta | None:
    """Geldigheid van een momentopname; None bij TTL 0 (alleen verversen via de knop)."""
    days = int(getattr(settings, "ahrefs_competitors_ttl_days", 0) or 0)
    return timedelta(days=days) if days > 0 else None


def customer_domain(customer: CustomerWebsite) -> str:
    return host_of(customer.base_url)


def service_names(customer: CustomerWebsite) -> list[str]:
    """De diensten uit het klantprofiel: de onderwerpen van de heatmap (zonder "Lokaal")."""
    return [service.name for service in parse_profile(customer.profile).services if service.name]


def blocked_of(customer: CustomerWebsite) -> tuple[BlockedReason, str] | None:
    """Waarom ophalen niet kan, met de melding; None als het wel kan."""
    if not ahrefs.is_configured():
        return "ahrefs_not_configured", BLOCKED_MESSAGES["ahrefs_not_configured"]
    if not customer_domain(customer):
        return "no_website", BLOCKED_MESSAGES["no_website"]
    return None


def snapshot_of(row: CustomerCompetitorOverview | None) -> Snapshot | None:
    return _model(Snapshot, row.data) if row is not None else None


def overrides_of(row: CustomerCompetitorOverview | None) -> Overrides:
    return (_model(Overrides, row.overrides) if row is not None else None) or Overrides()


def _matches(row: CustomerCompetitorOverview, domain: str) -> bool:
    """Hoort wat in de rij staat bij het huidige klantdomein en land?"""
    return bool(domain) and row.target == domain and (row.country or COUNTRY) == COUNTRY


def is_expired(row: CustomerCompetitorOverview | None, domain: str, now: datetime | None = None) -> bool:
    """Een geslaagde momentopname die verlopen is (TTL voorbij, of ander domein of land)."""
    if row is None or row.status != "completed" or snapshot_of(row) is None:
        return False
    if not _matches(row, domain):
        return True
    ttl = _ttl()
    completed_at = as_utc(row.completed_at)
    if ttl is None or completed_at is None:
        return False
    return (now or _now()) - completed_at >= ttl


def reusable_raw(row: CustomerCompetitorOverview | None, domain: str, now: datetime | None = None) -> Raw | None:
    """De ruwe gegevens van de vorige run, als ze bij dit domein en land horen en jong genoeg zijn."""
    if row is None or not _matches(row, domain):
        return None
    raw = _model(Raw, row.raw)
    if raw is None:
        return None
    fetched_at = as_utc(raw.fetched_at) or as_utc(row.completed_at)
    ttl = _ttl()
    if ttl is not None and (fetched_at is None or (now or _now()) - fetched_at >= ttl):
        return None
    return raw


# --- rijen van de tabel ----------------------------------------------------------------------


def _apply_choice(
    choice: DomainChoice | None, *, ai_type: Any, ai_is_aggregator: bool
) -> dict[str, Any]:
    """Type en uitsluiting: de keuze van de gebruiker gaat voor het oordeel van Claude."""
    fields: dict[str, Any] = {}
    if choice is not None and choice.type is not None:
        fields.update(type=choice.type, type_source="manual")
    elif ai_type is not None:
        fields.update(type=ai_type, type_source="ai")
    else:
        fields.update(type=None, type_source=None)
    if choice is not None and choice.excluded is not None:
        fields.update(excluded=choice.excluded, excluded_source="manual",
                      exclude_reason=EXCLUDED_MANUAL_REASON if choice.excluded else None)
    elif ai_is_aggregator:
        fields.update(excluded=True, excluded_source="ai", exclude_reason=EXCLUDED_AI_REASON)
    else:
        fields.update(excluded=False, excluded_source=None, exclude_reason=None)
    return fields


def effective_excluded(domain: str, overrides: Overrides, snapshot: Snapshot | None) -> bool:
    """Telt dit domein nu als uitgesloten (keuze van de gebruiker, anders Claude)?"""
    choice = overrides.domains.get(domain)
    if choice is not None and choice.excluded is not None:
        return choice.excluded
    for competitor in snapshot.competitors if snapshot is not None else []:
        if competitor.domain == domain:
            return competitor.ai_is_aggregator
    return False


def _snapshot_row(competitor: SnapshotCompetitor, overrides: Overrides) -> CompetitorRow:
    return CompetitorRow(
        domain=competitor.domain,
        origin=competitor.origin,
        in_top5=competitor.in_top5,
        domain_rating=competitor.domain_rating,
        organic_keywords=competitor.organic_keywords,
        top10_keywords=competitor.top10_keywords,
        traffic=competitor.traffic,
        shared=competitor.shared,
        overlap_pct=competitor.overlap_pct,
        **_apply_choice(overrides.domains.get(competitor.domain), ai_type=competitor.ai_type,
                        ai_is_aggregator=competitor.ai_is_aggregator),
    )


def competitor_rows(snapshot: Snapshot | None, overrides: Overrides) -> list[CompetitorRow]:
    """De tabel: momentopname + handmatige keuzes. Meetellend op overlap aflopend (handmatige
    domeinen zonder cijfers onderaan die groep), daarna de uitgesloten."""
    manual = [entry.domain for entry in overrides.manual]
    manual_set = set(manual)
    rows: list[CompetitorRow] = []
    seen: set[str] = set()
    for competitor in snapshot.competitors if snapshot is not None else []:
        if competitor.domain in seen:
            continue
        if competitor.origin == "manual" and competitor.domain not in manual_set:
            continue  # handmatig toegevoegd en daarna weer verwijderd
        seen.add(competitor.domain)
        rows.append(_snapshot_row(competitor, overrides))
    for domain in manual:
        if domain in seen:
            continue
        seen.add(domain)
        rows.append(CompetitorRow(
            domain=domain, origin="manual", pending=True,
            **_apply_choice(overrides.domains.get(domain), ai_type=None, ai_is_aggregator=False),
        ))
    rows.sort(key=lambda row: (row.excluded, row.pending, -row.overlap_pct))
    return rows


# --- het antwoord ----------------------------------------------------------------------------


def is_dirty(row: CustomerCompetitorOverview | None, snapshot: Snapshot | None) -> bool:
    """Keuzes gemaakt na de start van de laatste run, en er loopt nu geen run."""
    if row is None or snapshot is None or row.status in ACTIVE_OVERVIEW_STATUSES:
        return False
    changed_at = as_utc(row.overrides_changed_at)
    if changed_at is None:
        return False
    started_at = as_utc(row.started_at)
    return started_at is None or changed_at > started_at


def to_overview(row: CustomerCompetitorOverview | None, customer: CustomerWebsite) -> CompetitorOverview:
    """Het antwoord voor één klant; zonder rij of momentopname lege secties."""
    blocked = blocked_of(customer)
    snapshot = snapshot_of(row)
    overrides = overrides_of(row)
    status: OverviewStatus = "idle" if row is None else (_choice(row.status, OverviewStatus) or "failed")
    completed_at = as_utc(row.completed_at) if row is not None else None
    ttl = _ttl()

    base: dict[str, Any] = dict(
        status=status,
        error_message=row.error_message if row is not None else None,
        customer_id=customer.id,
        domain=customer_domain(customer) or None,
        units=int(row.ahrefs_units or 0) if row is not None else 0,
        unit_cap=int(settings.ahrefs_competitors_max_units),
        unit_estimate=int(compute.unit_estimate(with_heatmap=bool(service_names(customer)))),
        blocked_reason=blocked[0] if blocked else None,
        blocked_message=blocked[1] if blocked else None,
        ai_usage=_model(AiUsage, row.ai_usage) if row is not None else None,
        model=row.model if row is not None else None,
    )
    rows = competitor_rows(snapshot, overrides)
    if snapshot is None:
        return CompetitorOverview(
            **base,
            competitors=CompetitorsSection(state="empty", rows=rows),
            heatmap=Heatmap(state="no_keywords"),
            summary=Summary(state="skipped"),
        )
    return CompetitorOverview(
        **base,
        fetched_at=completed_at,
        expires_at=completed_at + ttl if completed_at is not None and ttl is not None else None,
        dirty=is_dirty(row, snapshot),
        warnings=list(snapshot.warnings),
        overlap_basis=snapshot.overlap_basis,
        tracked_sample=snapshot.tracked_sample,
        sources=snapshot.sources,
        kpis=snapshot.kpis,
        competitors=CompetitorsSection(state=snapshot.competitors_state, message=snapshot.competitors_message,
                                       rows=rows),
        heatmap=snapshot.heatmap,
        summary=snapshot.summary,
    )
