"""Celery-taken: wekelijkse Search Console-ronde van de werkvoorraad.

Celery beat start op `work_queue_gsc_weekday` om `work_queue_gsc_hour` (Europe/Amsterdam)
`run_work_queue_gsc_dispatch_task`; die zet per klant één `run_work_queue_gsc_task` op de
`default`-queue. Die haalt de CTR-kansen van de klant live uit Google en werkt de kaart
"Title & meta herschrijven" bij (`sources_search_console.sync_customer`).

Elke klant is een eigen taak: een fout of een onbekende klant raakt de andere niet. Voor de
startvulling kan de dispatch-taak eenmalig met de hand worden gestart.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from app.core.config import settings
from app.db.models import CustomerWebsite
from app.db.session import SessionLocal
from app.features.work_queue.services.sources_search_console import sync_customer
from app.services.search_console import client as gsc
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@celery_app.task(name="app.worker.tasks.run_work_queue_gsc_dispatch_task")
def run_work_queue_gsc_dispatch_task() -> dict[str, Any]:
    """Zet per klant (op naam) een Search Console-sync klaar.

    Antwoord: `{"state": "disabled" | "not_configured" | "ok", "queued": [klant-ids]}`.
    """
    if not settings.work_queue_gsc_enabled:
        logger.info("Werkvoorraad Search Console staat uit (WORK_QUEUE_GSC_ENABLED=false).")
        return {"state": "disabled", "queued": []}
    if not gsc.is_configured():
        logger.info("Werkvoorraad Search Console overgeslagen: Search Console is niet gekoppeld.")
        return {"state": "not_configured", "queued": []}
    with SessionLocal() as db:
        queued = [
            row[0]
            for row in db.query(CustomerWebsite.id).order_by(CustomerWebsite.name.asc()).all()
        ]
    for customer_id in queued:
        run_work_queue_gsc_task.delay(customer_id)
    logger.info("Werkvoorraad Search Console: %d klant(en) ingepland.", len(queued))
    return {"state": "ok", "queued": queued}


@celery_app.task(
    name="app.worker.tasks.run_work_queue_gsc_task",
    soft_time_limit=300,
    time_limit=360,
)
def run_work_queue_gsc_task(customer_id: str) -> dict[str, Any]:
    """Search Console-sync van één klant. Geeft de state en de tellers terug (voor logs en
    tests): zie `sync_customer`, plus `unknown_customer`, `timeout` en `failed`."""
    try:
        with SessionLocal() as db:
            customer = db.get(CustomerWebsite, customer_id)
            if customer is None:
                logger.info("Werkvoorraad Search Console: klant %s bestaat niet (meer).", customer_id)
                return {"state": "unknown_customer", "changed": False}
            result = sync_customer(db, customer, now=_now())
            db.commit()
    except SoftTimeLimitExceeded:
        logger.warning("Werkvoorraad Search Console: klant %s liep tegen de tijdslimiet.", customer_id)
        return {"state": "timeout", "changed": False}
    except Exception:
        logger.exception("Werkvoorraad Search Console: sync van klant %s mislukt.", customer_id)
        return {"state": "failed", "changed": False}
    logger.info(
        "Werkvoorraad Search Console: klant %s → %s (aangemaakt %s, bijgewerkt %s, afgerond %s).",
        customer_id, result.get("state"), result.get("created", 0), result.get("updated", 0),
        result.get("resolved", 0),
    )
    return result


__all__ = ["run_work_queue_gsc_dispatch_task", "run_work_queue_gsc_task"]
