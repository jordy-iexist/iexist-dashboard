"""Vastgelopen concurrentieanalyses herstellen.

Een run die stopt door de harde tijdslimiet of een herstart van de worker, blijft op een
actieve status staan. Zolang dat zo is weigert het start-endpoint een nieuwe analyse voor die
klant (409). `recover_stale_run` zet zo'n run op 'failed', zodat er opnieuw kan worden gestart.

Zelfde regels en drempels als de livegang-scans (`launch_checklist/services/scan_recovery.py`):
- 'pending': vastgelopen als `created_at` ouder is dan `SCAN_MAX_AGE`; de run kan in de
  wachtrij (`audit`) achter een livegang-scan staan, en de worker werkt `updated_at` pas bij
  als hij begint;
- elke andere actieve status: vastgelopen als `updated_at` ouder is dan `STALE_SCAN_AFTER`.
  De taak werkt `updated_at` bij na elke stap (en via `heartbeat` tijdens lange stappen).

Los van HTTP: de router en de taak gebruiken dit allebei. Net als `recover_stale_scan` commit
`recover_stale_run` zelf als hij iets heeft hersteld.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import CompetitorAnalysis
from app.features.competitor_analysis.schemas import ACTIVE_STATUSES
from app.features.launch_checklist.services.scan_recovery import (
    SCAN_MAX_AGE,
    STALE_SCAN_AFTER,
    is_older_than,
)

# Zelfde drempels als de livegang-scans; zie de module-docstring.
STALE_RUN_AFTER = STALE_SCAN_AFTER
PENDING_MAX_AGE = SCAN_MAX_AGE

INTERRUPTED_RUN_MESSAGE = (
    "De analyse is onderbroken (bijvoorbeeld door een herstart van de server) en kan opnieuw "
    "worden gestart."
)


def is_stale(analysis: CompetitorAnalysis, *, now: datetime | None = None) -> bool:
    """Of een actieve run te lang niets van zich heeft laten horen; False bij een afgeronde run."""
    status = str(analysis.status or "").lower()
    if status not in ACTIVE_STATUSES:
        return False
    if status == "pending":
        return is_older_than(analysis.created_at, PENDING_MAX_AGE, now=now)
    return is_older_than(analysis.updated_at, STALE_RUN_AFTER, now=now)


def recover_stale_run(db: Session, analysis: CompetitorAnalysis, *, now: datetime | None = None) -> bool:
    """Zet een actieve run die niet meer loopt op 'failed' en commit. True als dat gebeurd is."""
    now = now or datetime.now(timezone.utc)
    if not is_stale(analysis, now=now):
        return False
    analysis.status = "failed"
    analysis.error_message = INTERRUPTED_RUN_MESSAGE
    analysis.updated_at = now
    db.commit()
    return True


def recover_customer_runs(db: Session, customer_id: str, *, now: datetime | None = None) -> None:
    """Herstel alle vastgelopen actieve runs van één klant (vóór starten en in de lijst)."""
    active = (
        db.query(CompetitorAnalysis)
        .filter(
            CompetitorAnalysis.customer_website_id == customer_id,
            CompetitorAnalysis.status.in_(ACTIVE_STATUSES),
        )
        .all()
    )
    for analysis in active:
        recover_stale_run(db, analysis, now=now)
