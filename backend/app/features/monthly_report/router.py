"""Maandrapport per klant: `/api/monthly-reports`.

Het verzamelen en schrijven gebeurt in de taak `worker/report.py`; deze router maakt de rij
aan, zet hem op `pending`, plant de taak in en beheert de handmatige cijfers. Alle endpoints
geven `MonthlyReport` terug. Klanten zijn team-globaal: geen eigenaarscontrole.

- `GET   /customers/{cid}/reports/{month}`: altijd 200; zonder rij een leeg `draft`-antwoord.
  Een run die langer dan `STALE_REPORT_AFTER` geen levensteken gaf wordt eerst `failed`.
- `POST  /customers/{cid}/reports/{month}`: starten vanaf geen rij, `draft` of `failed`.
- `POST  /customers/{cid}/reports/{month}/regenerate`: opnieuw vanaf `completed` of `failed`;
  `data`, `report` en `manual` blijven staan tot de nieuwe run slaagt.
- `PATCH /customers/{cid}/reports/{month}/manual`: handmatige cijfers; maakt zo nodig een
  `draft`-rij en werkt anders alleen de kolom `manual` bij (ook tijdens een run). `updated_at`
  van de rij blijft dan ongemoeid: dat is het levensteken van de taak.

`month` is "YYYY-MM": 422 bij een andere vorm, 400 bij een maand in de toekomst of meer dan
`MAX_MONTHS_BACK` maanden terug.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id
from app.db.models import CustomerWebsite, MonthlyReport as MonthlyReportRow
from app.db.session import get_db
from app.features.launch_checklist.services.scan_recovery import is_older_than
from app.features.monthly_report.mappers import to_monthly_report
from app.features.monthly_report.schemas import (
    ACTIVE_REPORT_STATUSES,
    Manual,
    ManualUpdate,
    MonthlyReport,
)
from app.features.monthly_report.services.periods import (
    MAX_MONTHS_BACK,
    months_back,
    parse_month,
    previous_month,
    today_local,
)
from app.services.anthropic import client as anthropic_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/monthly-reports", tags=["monthly-reports"])

# De taak heeft een harde limiet van 10 minuten; daarna loopt er zeker niets meer.
STALE_REPORT_AFTER = timedelta(minutes=15)

MESSAGES: dict[str, str] = {
    "customer": "Klant niet gevonden.",
    "invalid_month": "De maand moet de vorm JJJJ-MM hebben, bijvoorbeeld 2026-11.",
    "future_month": "Voor een maand in de toekomst kan nog geen rapport worden gemaakt.",
    "too_old": f"Een rapport kan hooguit {MAX_MONTHS_BACK} maanden terug; Search Console bewaart niet langer.",
    "not_configured": "Claude is niet gekoppeld: ANTHROPIC_API_KEY ontbreekt in de backend-configuratie.",
    "running": "Het rapport voor deze maand wordt al gemaakt. Wacht tot het klaar is.",
    "exists": "Het rapport voor deze maand bestaat al. Gebruik \"Opnieuw genereren\" voor een nieuwe versie.",
    "no_report": "Er is nog geen rapport voor deze maand. Gebruik \"Genereren\".",
    "not_queued": "Het rapport kon niet worden ingepland: de takenwachtrij is niet bereikbaar. "
                  "Probeer het later opnieuw.",
    "stale": "Het maken van het rapport is onderbroken (bijvoorbeeld door een herstart van de server). "
             "Probeer het opnieuw.",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_customer(db: Session, customer_id: str) -> CustomerWebsite:
    customer = db.get(CustomerWebsite, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=MESSAGES["customer"])
    return customer


def check_month(month: str, today: date | None = None) -> str:
    """422 bij een ongeldige vorm, 400 bij een toekomstige of te oude maand."""
    try:
        parse_month(month)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=MESSAGES["invalid_month"]) from exc
    back = months_back(month, today or today_local())
    if back < 0:
        raise HTTPException(status_code=400, detail=MESSAGES["future_month"])
    if back > MAX_MONTHS_BACK:
        raise HTTPException(status_code=400, detail=MESSAGES["too_old"])
    return month


def _find(db: Session, customer_id: str, month: str) -> MonthlyReportRow | None:
    return (
        db.query(MonthlyReportRow)
        .filter(MonthlyReportRow.customer_website_id == customer_id, MonthlyReportRow.month == month)
        .first()
    )


def recover_stale_report(db: Session, row: MonthlyReportRow | None, now: datetime | None = None) -> bool:
    """Zet een actief rapport zonder levensteken (ouder dan `STALE_REPORT_AFTER`) op `failed`."""
    if row is None or row.status not in ACTIVE_REPORT_STATUSES:
        return False
    if not is_older_than(row.updated_at, STALE_REPORT_AFTER, now=now):
        return False
    row.status = "failed"
    row.error_message = MESSAGES["stale"]
    row.updated_at = now or _now()
    db.commit()
    return True


def _response(db: Session, customer_id: str, month: str, row: MonthlyReportRow | None) -> MonthlyReport:
    return to_monthly_report(row, customer_id=customer_id, month=month,
                             previous_row=_find(db, customer_id, previous_month(month)))


def _require_claude() -> None:
    if not anthropic_client.is_configured():
        raise HTTPException(status_code=503, detail=MESSAGES["not_configured"])


def _restart(db: Session, row: MonthlyReportRow, allowed: tuple[str, ...]) -> None:
    """Atomair naar `pending`, alleen vanaf een van de `allowed` statussen; anders 409."""
    count = db.query(MonthlyReportRow).filter(
        MonthlyReportRow.id == row.id, MonthlyReportRow.status.in_(allowed),
    ).update({"status": "pending", "error_message": None, "updated_at": _now()}, synchronize_session=False)
    db.commit()
    if count != 1:
        raise HTTPException(status_code=409, detail=MESSAGES["running"])
    db.refresh(row)


def _enqueue(db: Session, row: MonthlyReportRow) -> None:
    """Plan de taak in; lukt dat niet, dan `failed` met een melding en 503."""
    from app.worker.tasks import run_monthly_report_task  # voorkom circulaire import

    try:
        run_monthly_report_task.delay(row.id)
    except Exception as exc:  # noqa: BLE001 - bijv. Redis niet bereikbaar
        logger.exception("Maandrapport %s niet ingepland", row.id)
        row.status = "failed"
        row.error_message = MESSAGES["not_queued"]
        row.updated_at = _now()
        db.commit()
        raise HTTPException(status_code=503, detail=MESSAGES["not_queued"]) from exc


@router.get("/customers/{customer_id}/reports/{month}", response_model=MonthlyReport)
def get_report(
    customer_id: str,
    month: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Het rapport van deze maand; licht genoeg om elke 3 seconden te pollen."""
    _require_customer(db, customer_id)
    check_month(month)
    row = _find(db, customer_id, month)
    recover_stale_report(db, row)
    return _response(db, customer_id, month, row)


@router.post("/customers/{customer_id}/reports/{month}", response_model=MonthlyReport)
def start_report(
    customer_id: str,
    month: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Start het rapport (ook na `failed`, of vanaf een rij met alleen handmatige cijfers)."""
    _require_customer(db, customer_id)
    check_month(month)
    _require_claude()

    row = _find(db, customer_id, month)
    if row is None:
        now = _now()
        row = MonthlyReportRow(
            id=str(uuid.uuid4()), customer_website_id=customer_id, month=month, status="pending",
            created_by=user_id, created_at=now, updated_at=now,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError as exc:  # tegelijk gestart: de andere aanvraag won
            db.rollback()
            raise HTTPException(status_code=409, detail=MESSAGES["running"]) from exc
    else:
        recover_stale_report(db, row)
        if row.status in ACTIVE_REPORT_STATUSES:
            raise HTTPException(status_code=409, detail=MESSAGES["running"])
        if row.status == "completed":
            raise HTTPException(status_code=409, detail=MESSAGES["exists"])
        _restart(db, row, ("draft", "failed"))

    _enqueue(db, row)
    db.refresh(row)
    return _response(db, customer_id, month, row)


@router.post("/customers/{customer_id}/reports/{month}/regenerate", response_model=MonthlyReport)
def regenerate_report(
    customer_id: str,
    month: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Opnieuw genereren (cijfers en tekst); het vorige rapport blijft staan tot het nieuwe klaar is."""
    _require_customer(db, customer_id)
    check_month(month)
    row = _find(db, customer_id, month)
    if row is None or row.status == "draft":
        raise HTTPException(status_code=409, detail=MESSAGES["no_report"])
    recover_stale_report(db, row)
    if row.status in ACTIVE_REPORT_STATUSES:
        raise HTTPException(status_code=409, detail=MESSAGES["running"])
    _require_claude()
    _restart(db, row, ("completed", "failed"))
    _enqueue(db, row)
    db.refresh(row)
    return _response(db, customer_id, month, row)


@router.patch("/customers/{customer_id}/reports/{month}/manual", response_model=MonthlyReport)
def update_manual(
    customer_id: str,
    month: str,
    body: ManualUpdate,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Handmatige cijfers opslaan; `None` wist een cijfer. Kan altijd, ook tijdens een run."""
    _require_customer(db, customer_id)
    check_month(month)
    manual = Manual(leads=body.leads, leads_previous=body.leads_previous, updated_by=user_id,
                    updated_at=_now()).model_dump(mode="json")

    row = _find(db, customer_id, month)
    if row is None:
        now = _now()
        db.add(MonthlyReportRow(
            id=str(uuid.uuid4()), customer_website_id=customer_id, month=month, status="draft",
            manual=manual, created_by=user_id, created_at=now, updated_at=now,
        ))
        try:
            db.commit()
        except IntegrityError:  # tegelijk aangemaakt: dan de bestaande rij bijwerken
            db.rollback()
            row = _find(db, customer_id, month)
            if row is None:
                raise
    if row is not None:
        db.query(MonthlyReportRow).filter(MonthlyReportRow.id == row.id).update(
            {"manual": manual}, synchronize_session=False,
        )
        db.commit()
    row = _find(db, customer_id, month)
    if row is not None:
        db.refresh(row)
    return _response(db, customer_id, month, row)
