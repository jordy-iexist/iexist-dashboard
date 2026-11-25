"""Zoekwoorden › Content gap per klant.

Tweede router in deze feature (zelfde prefix `/api/keywords`, zodat de bestaande
frontend-proxy werkt). Het ophalen gebeurt in de taak `worker/gap.py`; deze router maakt de
rij aan, zet hem op `pending` en plant de taak in. Beide endpoints geven `ContentGapOverview`
terug. Klanten zijn team-globaal: geen eigenaarscontrole.

- `GET  /customers/{cid}/content-gap`: altijd 200 (404 alleen bij een onbekende klant). Een
  run zonder levensteken (ouder dan `STALE_RUN_AFTER`) wordt eerst `failed`.
- `POST /customers/{cid}/content-gap/start`: geen body. 400 als starten geblokkeerd is, 409
  tijdens een run, 503 zonder wachtrij. Er is geen automatische verversing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id
from app.db.models import CustomerCompetitorOverview, CustomerKeywordGap as Row, CustomerWebsite
from app.db.session import get_db
from app.features.keywords.gap_mappers import blocked_of, to_overview
from app.features.keywords.gap_schemas import ACTIVE_GAP_STATUSES, ContentGapOverview
from app.features.launch_checklist.services.scan_recovery import is_older_than

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/keywords", tags=["keywords-content-gap"])

# De taak heeft een harde limiet van 10 minuten; daarna loopt er zeker niets meer.
STALE_RUN_AFTER = timedelta(minutes=15)

MESSAGES: dict[str, str] = {
    "customer": "Klant niet gevonden.",
    "running": "De content gap wordt al opgehaald. Wacht tot dat klaar is.",
    "not_queued": "De content gap kon niet worden ingepland: de takenwachtrij is niet bereikbaar. "
                  "Probeer het later opnieuw.",
    "stale": "Het ophalen van de content gap is onderbroken (bijvoorbeeld door een herstart van de "
             "server). Probeer het opnieuw.",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_customer(db: Session, customer_id: str) -> CustomerWebsite:
    customer = db.get(CustomerWebsite, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=MESSAGES["customer"])
    return customer


def _find(db: Session, customer_id: str) -> Row | None:
    return db.get(Row, customer_id)


def _scan(db: Session, customer_id: str) -> CustomerCompetitorOverview | None:
    return db.get(CustomerCompetitorOverview, customer_id)


def _response(db: Session, customer: CustomerWebsite) -> ContentGapOverview:
    db.expire_all()
    return to_overview(_find(db, customer.id), customer, _scan(db, customer.id))


def recover_stale_run(db: Session, row: Row | None, now: datetime | None = None) -> bool:
    """Zet een actieve run zonder levensteken (ouder dan `STALE_RUN_AFTER`) op `failed`."""
    if row is None or row.status not in ACTIVE_GAP_STATUSES:
        return False
    if not is_older_than(row.updated_at, STALE_RUN_AFTER, now=now):
        return False
    count = db.query(Row).filter(
        Row.customer_website_id == row.customer_website_id, Row.status.in_(ACTIVE_GAP_STATUSES),
    ).update({"status": "failed", "error_message": MESSAGES["stale"], "updated_at": now or _now()},
             synchronize_session=False)
    db.commit()
    db.refresh(row)
    return count == 1


def _to_pending(db: Session, customer_id: str) -> bool:
    """Atomair naar `pending` vanaf een niet-actieve status."""
    count = db.query(Row).filter(
        Row.customer_website_id == customer_id, Row.status.notin_(ACTIVE_GAP_STATUSES),
    ).update({"status": "pending", "error_message": None, "updated_at": _now()}, synchronize_session=False)
    db.commit()
    return count == 1


def _enqueue(db: Session, customer_id: str) -> None:
    """Plan de taak in; lukt dat niet, dan `failed` met een melding en 503."""
    from app.worker.tasks import run_content_gap_task  # voorkom circulaire import

    try:
        run_content_gap_task.delay(customer_id)
    except Exception as exc:  # noqa: BLE001 - bijv. Redis niet bereikbaar
        logger.exception("Content gap van klant %s niet ingepland", customer_id)
        db.query(Row).filter(Row.customer_website_id == customer_id).update(
            {"status": "failed", "error_message": MESSAGES["not_queued"], "updated_at": _now()},
            synchronize_session=False,
        )
        db.commit()
        raise HTTPException(status_code=503, detail=MESSAGES["not_queued"]) from exc


# --- endpoints -------------------------------------------------------------------------------


@router.get("/customers/{customer_id}/content-gap", response_model=ContentGapOverview)
def get_content_gap(
    customer_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """De content gap; licht genoeg om tijdens een run elke paar seconden te pollen."""
    customer = _require_customer(db, customer_id)
    recover_stale_run(db, _find(db, customer_id))
    return _response(db, customer)


@router.post("/customers/{customer_id}/content-gap/start", response_model=ContentGapOverview)
def start_content_gap(
    customer_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Start een run; het vorige resultaat blijft zichtbaar tot de nieuwe klaar is."""
    customer = _require_customer(db, customer_id)
    blocked = blocked_of(customer, _scan(db, customer_id))
    if blocked is not None:
        raise HTTPException(status_code=400, detail=blocked[1])

    created = False
    if _find(db, customer_id) is None:
        now = _now()
        db.add(Row(customer_website_id=customer_id, status="pending", created_by=user_id,
                   created_at=now, updated_at=now))
        try:
            db.commit()
            created = True
        except IntegrityError:  # tegelijk aangemaakt: de andere aanvraag won
            db.rollback()
    if not created:
        row = _find(db, customer_id)
        recover_stale_run(db, row)
        if row is None or row.status in ACTIVE_GAP_STATUSES or not _to_pending(db, customer_id):
            raise HTTPException(status_code=409, detail=MESSAGES["running"])

    _enqueue(db, customer_id)
    return _response(db, customer)
