"""Rij van `customer_keyword_gaps` + klant + concurrentenscan omzetten naar `ContentGapOverview`.

Pure functies (op `ahrefs.is_configured()` en de instellingen na). Verdraagzaam voor een lege
of ongeldige `data`: die geldt als afwezig. Ook de gedeelde regels voor router en worker staan
hier: welke concurrenten de content gap gebruikt (`scan_top5`) en wanneer starten geblokkeerd
is (`blocked_of`).
"""
from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.db.models import CustomerCompetitorOverview, CustomerKeywordGap, CustomerWebsite
from app.features.competitor_analysis.mappers import _choice, _model
from app.features.keywords.gap_schemas import (
    MIN_COMPETITORS,
    ContentGapOverview,
    GapBlockedReason,
    GapSnapshot,
    GapStatus,
)
from app.features.keywords.mappers import BLOCKED_MESSAGES as SCAN_BLOCKED_MESSAGES
from app.features.keywords.mappers import customer_domain, snapshot_of as scan_snapshot_of
from app.features.keywords.schemas import COUNTRY, TOP_COMPETITORS
from app.features.launch_checklist.services.scan_recovery import as_utc
from app.services import ahrefs

BLOCKED_MESSAGES: dict[str, str] = {
    "ahrefs_not_configured": SCAN_BLOCKED_MESSAGES["ahrefs_not_configured"],
    "no_scan": "Er is nog geen voltooide concurrentenscan voor deze klant. Haal eerst de concurrenten op "
               "bij Zoekwoorden › Concurrenten.",
    "too_few_competitors": f"De concurrentenscan heeft minder dan {MIN_COMPETITORS} concurrenten in de top 5. "
                           "Voeg concurrenten toe bij Zoekwoorden › Concurrenten en ververs de scan.",
}


def gap_snapshot_of(row: CustomerKeywordGap | None) -> GapSnapshot | None:
    return _model(GapSnapshot, row.data) if row is not None else None


def scan_top5(scan: CustomerCompetitorOverview | None, domain: str) -> list[str] | None:
    """De vijf (`in_top5`) uit een voltooide concurrentenscan voor dit klantdomein en land, in
    de volgorde van de scan. None = geen bruikbare scan.

    Een scan die opnieuw loopt telt mee zolang zijn vorige momentopname er nog staat: die
    wordt pas aan het eind van een run vervangen.
    """
    if scan is None or not domain or scan.completed_at is None:
        return None
    if scan.target != domain or (scan.country or COUNTRY) != COUNTRY:
        return None
    snapshot = scan_snapshot_of(scan)
    if snapshot is None:
        return None
    top5 = list(dict.fromkeys(c.domain for c in snapshot.competitors if c.in_top5 and c.domain))
    return top5[:TOP_COMPETITORS]


def blocked_of(
    customer: CustomerWebsite, scan: CustomerCompetitorOverview | None
) -> tuple[GapBlockedReason, str] | None:
    """Waarom starten niet kan, met de melding; None als het wel kan."""
    if not ahrefs.is_configured():
        return "ahrefs_not_configured", BLOCKED_MESSAGES["ahrefs_not_configured"]
    top5 = scan_top5(scan, customer_domain(customer))
    if top5 is None:
        return "no_scan", BLOCKED_MESSAGES["no_scan"]
    if len(top5) < MIN_COMPETITORS:
        return "too_few_competitors", BLOCKED_MESSAGES["too_few_competitors"]
    return None


def is_stale(
    row: CustomerKeywordGap | None,
    snapshot: GapSnapshot | None,
    scan: CustomerCompetitorOverview | None,
    domain: str,
) -> bool:
    """De concurrentenscan is na deze content gap vernieuwd (of het klantdomein is gewijzigd)."""
    if row is None or snapshot is None:
        return False
    if snapshot.customer_domain != domain:
        return True
    scan_completed = as_utc(scan.completed_at) if scan is not None else None
    source = as_utc(row.source_completed_at)
    return scan_completed is not None and (source is None or scan_completed > source)


def to_overview(
    row: CustomerKeywordGap | None,
    customer: CustomerWebsite,
    scan: CustomerCompetitorOverview | None,
) -> ContentGapOverview:
    """Het antwoord voor één klant; zonder resultaat een lege lijst en de huidige vijf."""
    domain = customer_domain(customer)
    blocked = blocked_of(customer, scan)
    snapshot = gap_snapshot_of(row)
    status: GapStatus = "idle" if row is None else (_choice(row.status, GapStatus) or "failed")
    base: dict[str, Any] = dict(
        status=status,
        error=row.error_message if row is not None else None,
        blocked=blocked[0] if blocked else None,
        has_result=snapshot is not None,
        customer_domain=domain,
        units=int(row.ahrefs_units or 0) if row is not None else 0,
        max_units=int(settings.ahrefs_content_gap_max_units),
        started_at=as_utc(row.started_at) if row is not None else None,
        completed_at=as_utc(row.completed_at) if row is not None else None,
        stale=is_stale(row, snapshot, scan, domain),
    )
    if snapshot is None:
        return ContentGapOverview(**base, competitors=scan_top5(scan, domain) or [])
    return ContentGapOverview(
        **base,
        competitors=list(snapshot.competitors),
        found=snapshot.found,
        keywords=list(snapshot.keywords),
        warnings=list(snapshot.warnings),
    )
