"""Celery-taak: dagelijkse momentopname van de posities voor het bureau-overzicht.

Celery beat start `refresh_rank_snapshots_task` elke dag om 07:00 (Europe/Amsterdam). Die haalt
per klant de ProRankTracker-posities op (alleen GET, kost geen quota) en slaat ze op
(`services/rank_snapshots.refresh_all`). Met AGENCY_RANKINGS_ENABLED=false slaat de taak over.
"""
from __future__ import annotations

from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from app.core.config import settings
from app.db.session import SessionLocal
from app.features.agency_overview.services.rank_snapshots import refresh_all
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    name="agency_overview.refresh_rank_snapshots",
    soft_time_limit=600,
    time_limit=660,
)
def refresh_rank_snapshots_task() -> dict[str, Any]:
    """Antwoord: `{"state": "disabled" | "ok" | "timeout" | "failed", "counts": {state: aantal}}`."""
    if not settings.agency_rankings_enabled:
        logger.info("Bureau-overzicht: posities ophalen staat uit (AGENCY_RANKINGS_ENABLED=false).")
        return {"state": "disabled", "counts": {}}
    try:
        with SessionLocal() as db:
            counts = refresh_all(db)
    except SoftTimeLimitExceeded:
        logger.warning("Bureau-overzicht: posities ophalen liep tegen de tijdslimiet.")
        return {"state": "timeout", "counts": {}}
    except Exception:
        logger.exception("Bureau-overzicht: posities ophalen mislukt.")
        return {"state": "failed", "counts": {}}
    logger.info("Bureau-overzicht: posities opgeslagen %s.", counts)
    return {"state": "ok", "counts": counts}


__all__ = ["refresh_rank_snapshots_task"]
