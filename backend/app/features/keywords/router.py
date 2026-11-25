"""Zoekwoorden › Concurrenten per klant: `/api/keywords`.

Het ophalen en rekenen gebeurt in de taak `worker/refresh.py`; deze router maakt de rij aan,
zet hem op `pending`, plant de taak in en beheert de handmatige keuzes (`overrides`). Alle
endpoints geven `CompetitorOverview` terug. Klanten zijn team-globaal: geen eigenaarscontrole.

- `GET   /customers/{cid}/competitors`: altijd 200. Een run zonder levensteken (ouder dan
  `STALE_RUN_AFTER`) wordt eerst `failed`. Een verlopen geslaagde momentopname plant zelf een
  volledige run in (nooit vanaf `idle` of `failed`); lukt dat niet, dan blijft de oude staan.
- `POST  /customers/{cid}/competitors/refresh` `{mode}`: 409 tijdens een run, 400 als ophalen
  geblokkeerd is, 503 zonder wachtrij. `reuse` zonder bruikbare `raw` wordt `full`.
- `POST  /customers/{cid}/competitors/manual` en `/manual/remove` `{domain}`: handmatige
  concurrenten; kan altijd, ook zonder momentopname en tijdens een run.
- `PATCH /customers/{cid}/competitors/choice` `{domain, type, excluded}`: keuze per domein.

Alleen deze router schrijft `overrides` (gelezen met `with_for_update()`), en alleen die kolom
plus `overrides_changed_at`: `updated_at` is het levensteken van de taak.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id
from app.db.models import CustomerCompetitorOverview as Row, CustomerWebsite
from app.db.session import get_db
from app.features.customers.rankings import host_of
from app.features.keywords.mappers import (
    blocked_of,
    customer_domain,
    effective_excluded,
    is_expired,
    overrides_of,
    reusable_raw,
    snapshot_of,
    to_overview,
)
from app.features.keywords.schemas import (
    ACTIVE_OVERVIEW_STATUSES,
    MAX_MANUAL_COMPETITORS,
    ChoiceRequest,
    CompetitorOverview,
    DomainChoice,
    DomainRequest,
    ManualDomain,
    Overrides,
    RefreshMode,
    RefreshRequest,
)
from app.features.launch_checklist.services.scan_recovery import is_older_than

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/keywords", tags=["keywords"])

# De taak heeft een harde limiet van 10 minuten; daarna loopt er zeker niets meer.
STALE_RUN_AFTER = timedelta(minutes=15)

MESSAGES: dict[str, str] = {
    "customer": "Klant niet gevonden.",
    "running": "De concurrenten worden al opgehaald. Wacht tot dat klaar is.",
    "not_queued": "Het ophalen kon niet worden ingepland: de takenwachtrij is niet bereikbaar. "
                  "Probeer het later opnieuw.",
    "stale": "Het ophalen van de concurrenten is onderbroken (bijvoorbeeld door een herstart van de "
             "server). Probeer het opnieuw.",
    "invalid_domain": "Dit is geen geldig domein. Vul een domein in zoals voorbeeld.nl.",
    "own_domain": "Dit is het domein van de klant zelf; dat kan geen concurrent zijn.",
    "duplicate": "Dit domein staat al bij de handmatig toegevoegde concurrenten.",
    "too_many": f"Er kunnen hooguit {MAX_MANUAL_COMPETITORS} concurrenten handmatig worden toegevoegd. "
                "Verwijder er eerst een.",
}

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_DOMAIN_RE = re.compile(rf"^(?:{_LABEL}\.)+(?:[a-z]{{2,63}}|xn--[a-z0-9-]{{1,59}})$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_customer(db: Session, customer_id: str) -> CustomerWebsite:
    customer = db.get(CustomerWebsite, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=MESSAGES["customer"])
    return customer


def _find(db: Session, customer_id: str, *, lock: bool = False) -> Row | None:
    query = db.query(Row).filter(Row.customer_website_id == customer_id)
    if lock:
        query = query.with_for_update()
    return query.first()


def _response(db: Session, customer: CustomerWebsite) -> CompetitorOverview:
    db.expire_all()
    return to_overview(_find(db, customer.id), customer)


def normalize_domain(value: str) -> str:
    """"https://www.voorbeeld.nl/pad" → "voorbeeld.nl"; leeg als het geen geldig domein is."""
    domain = host_of(value).strip(".")
    try:
        domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return ""
    return domain if len(domain) <= 253 and _DOMAIN_RE.match(domain) else ""


def recover_stale_run(db: Session, row: Row | None, now: datetime | None = None) -> bool:
    """Zet een actieve run zonder levensteken (ouder dan `STALE_RUN_AFTER`) op `failed`."""
    if row is None or row.status not in ACTIVE_OVERVIEW_STATUSES:
        return False
    if not is_older_than(row.updated_at, STALE_RUN_AFTER, now=now):
        return False
    count = db.query(Row).filter(
        Row.customer_website_id == row.customer_website_id, Row.status.in_(ACTIVE_OVERVIEW_STATUSES),
    ).update({"status": "failed", "error_message": MESSAGES["stale"], "updated_at": now or _now()},
             synchronize_session=False)
    db.commit()
    db.refresh(row)
    return count == 1


def _to_pending(db: Session, customer_id: str, allowed: tuple[str, ...] | None = None) -> bool:
    """Atomair naar `pending` vanaf een niet-actieve status (of alleen vanaf `allowed`)."""
    query = db.query(Row).filter(Row.customer_website_id == customer_id)
    if allowed is not None:
        query = query.filter(Row.status.in_(allowed))
    else:
        query = query.filter(Row.status.notin_(ACTIVE_OVERVIEW_STATUSES))
    count = query.update({"status": "pending", "error_message": None, "updated_at": _now()},
                         synchronize_session=False)
    db.commit()
    return count == 1


def _delay(customer_id: str, mode: RefreshMode) -> None:
    from app.worker.tasks import refresh_keyword_competitors_task  # voorkom circulaire import

    refresh_keyword_competitors_task.delay(customer_id, mode)


def _enqueue(db: Session, customer_id: str, mode: RefreshMode) -> None:
    """Plan de taak in; lukt dat niet, dan `failed` met een melding en 503."""
    try:
        _delay(customer_id, mode)
    except Exception as exc:  # noqa: BLE001 - bijv. Redis niet bereikbaar
        logger.exception("Concurrenten van klant %s niet ingepland", customer_id)
        db.query(Row).filter(Row.customer_website_id == customer_id).update(
            {"status": "failed", "error_message": MESSAGES["not_queued"], "updated_at": _now()},
            synchronize_session=False,
        )
        db.commit()
        raise HTTPException(status_code=503, detail=MESSAGES["not_queued"]) from exc


def _auto_refresh(db: Session, customer: CustomerWebsite, row: Row | None) -> None:
    """Plan een volledige run in bij een verlopen geslaagde momentopname. Geen fout naar de
    gebruiker: lukt het inplannen niet, dan blijft de oude momentopname gewoon staan."""
    if row is None or blocked_of(customer) is not None or not is_expired(row, customer_domain(customer)):
        return
    if not _to_pending(db, customer.id, allowed=("completed",)):
        return
    try:
        _delay(customer.id, "full")
    except Exception:  # noqa: BLE001 - bijv. Redis niet bereikbaar
        logger.exception("Automatisch verversen van klant %s niet ingepland", customer.id)
        db.query(Row).filter(Row.customer_website_id == customer.id, Row.status == "pending").update(
            {"status": "completed"}, synchronize_session=False,
        )
        db.commit()


def _locked_row(db: Session, customer_id: str, user_id: str) -> Row:
    """De rij met een schrijfslot; maakt hem aan (status `idle`) als hij ontbreekt."""
    row = _find(db, customer_id, lock=True)
    if row is not None:
        return row
    now = _now()
    db.add(Row(customer_website_id=customer_id, status="idle", overrides=Overrides().model_dump(mode="json"),
               created_by=user_id, created_at=now, updated_at=now))
    try:
        db.commit()
    except IntegrityError:  # tegelijk aangemaakt: dan de bestaande rij
        db.rollback()
    row = _find(db, customer_id, lock=True)
    if row is None:  # pragma: no cover - net weer verwijderd
        raise HTTPException(status_code=404, detail=MESSAGES["customer"])
    return row


def _save_overrides(db: Session, customer_id: str, overrides: Overrides, *, changed: bool) -> None:
    """Alleen `overrides` (en zo nodig `overrides_changed_at`); `updated_at` blijft ongemoeid."""
    fields: dict = {"overrides": overrides.model_dump(mode="json")}
    if changed:
        fields["overrides_changed_at"] = _now()
    db.query(Row).filter(Row.customer_website_id == customer_id).update(fields, synchronize_session=False)
    db.commit()


# --- endpoints -------------------------------------------------------------------------------


@router.get("/customers/{customer_id}/competitors", response_model=CompetitorOverview)
def get_competitors(
    customer_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Het overzicht; licht genoeg om tijdens een run elke paar seconden te pollen."""
    customer = _require_customer(db, customer_id)
    row = _find(db, customer_id)
    recover_stale_run(db, row)
    _auto_refresh(db, customer, row)
    return _response(db, customer)


@router.post("/customers/{customer_id}/competitors/refresh", response_model=CompetitorOverview)
def refresh_competitors(
    customer_id: str,
    body: RefreshRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Start een verversing; `reuse` hergebruikt de ruwe gegevens van de vorige run."""
    customer = _require_customer(db, customer_id)
    blocked = blocked_of(customer)
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
        except IntegrityError:  # tegelijk aangemaakt (bijv. door een handmatige keuze)
            db.rollback()
    if not created:
        row = _find(db, customer_id)
        recover_stale_run(db, row)
        if row is None or row.status in ACTIVE_OVERVIEW_STATUSES or not _to_pending(db, customer_id):
            raise HTTPException(status_code=409, detail=MESSAGES["running"])
    db.expire_all()
    row = _find(db, customer_id)

    mode: RefreshMode = body.mode
    if mode == "reuse" and reusable_raw(row, customer_domain(customer)) is None:
        mode = "full"
    _enqueue(db, customer_id, mode)
    return _response(db, customer)


@router.post("/customers/{customer_id}/competitors/manual", response_model=CompetitorOverview)
def add_manual(
    customer_id: str,
    body: DomainRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Voeg een concurrent handmatig toe; de cijfers komen bij de volgende run."""
    customer = _require_customer(db, customer_id)
    domain = normalize_domain(body.domain)
    if not domain:
        raise HTTPException(status_code=400, detail=MESSAGES["invalid_domain"])
    own = customer_domain(customer)
    if own and (domain == own or domain.endswith(f".{own}")):
        raise HTTPException(status_code=400, detail=MESSAGES["own_domain"])

    row = _locked_row(db, customer_id, user_id)
    overrides = overrides_of(row)
    if any(entry.domain == domain for entry in overrides.manual):
        db.rollback()
        raise HTTPException(status_code=400, detail=MESSAGES["duplicate"])
    if len(overrides.manual) >= MAX_MANUAL_COMPETITORS:
        db.rollback()
        raise HTTPException(status_code=400, detail=MESSAGES["too_many"])
    overrides.manual.append(ManualDomain(domain=domain, added_by=user_id, added_at=_now()))
    _save_overrides(db, customer_id, overrides, changed=True)
    return _response(db, customer)


@router.post("/customers/{customer_id}/competitors/manual/remove", response_model=CompetitorOverview)
def remove_manual(
    customer_id: str,
    body: DomainRequest,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Verwijder een handmatige concurrent (en de keuze voor dat domein); onbekend = geen fout."""
    customer = _require_customer(db, customer_id)
    domain = normalize_domain(body.domain) or host_of(body.domain)
    row = _find(db, customer_id, lock=True)
    if row is None or not domain:
        db.rollback()
        return _response(db, customer)
    overrides = overrides_of(row)
    remaining = [entry for entry in overrides.manual if entry.domain != domain]
    if len(remaining) == len(overrides.manual):
        db.rollback()
        return _response(db, customer)
    overrides.manual = remaining
    overrides.domains.pop(domain, None)
    _save_overrides(db, customer_id, overrides, changed=True)
    return _response(db, customer)


@router.patch("/customers/{customer_id}/competitors/choice", response_model=CompetitorOverview)
def update_choice(
    customer_id: str,
    body: ChoiceRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Type en uitsluiting voor één domein; `None` = terug naar het oordeel van Claude.

    `overrides_changed_at` verandert alleen als de uitsluiting van het domein werkelijk
    verandert: een ander type vraagt geen nieuwe run.
    """
    customer = _require_customer(db, customer_id)
    domain = normalize_domain(body.domain)
    if not domain:
        raise HTTPException(status_code=400, detail=MESSAGES["invalid_domain"])

    row = _locked_row(db, customer_id, user_id)
    overrides = overrides_of(row)
    snapshot = snapshot_of(row)
    before = effective_excluded(domain, overrides, snapshot)
    if body.type is None and body.excluded is None:
        overrides.domains.pop(domain, None)
    else:
        overrides.domains[domain] = DomainChoice(type=body.type, excluded=body.excluded)
    after = effective_excluded(domain, overrides, snapshot)
    _save_overrides(db, customer_id, overrides, changed=before != after)
    return _response(db, customer)
