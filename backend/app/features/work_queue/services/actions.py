"""Acties op een kaart: aanmaken, verplaatsen, toewijzen, notitie, verwijderen.

Geen van de functies commit; de router commit, en draait bij een fout alles terug (rollback)
voordat hij antwoordt, zodat een `WorkQueueConflict` halverwege geen half werk achterlaat.

Fouten:
- `WorkQueueConflict` → 409 (stand van de bron of het bord laat het niet toe);
- `ActionError` → de status in de fout (404 of 422), met een platte Nederlandse zin.

Statusovergangen van een automatische kaart:
- open → open: alleen de kolom en positie;
- open → Klaar: eerst de bron (`Adapter.complete`, kan weigeren), dan `mark_done`;
- Klaar → open (terugzetten): geweigerd als de bron de kaart zelf afrondde of als er al een open
  kaart voor de groep staat; dan de bron terug (`Adapter.reopen`), en bij scan en analyse de groep
  opnieuw uit de bron halen: heeft de bron niets meer open, dan 409.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import CustomerWebsite, User, WorkItem
from app.features.work_queue.services.board import ADAPTERS
from app.features.work_queue.services.cards import (
    fingerprint_of,
    position_between,
    position_for_new,
    position_top,
)
from app.features.work_queue.services.sync import mark_active, mark_done, mark_removed
from app.features.work_queue.services.types import (
    ACTIVE_STATUSES,
    BOARD_STATUSES,
    KINDS,
    SEVERITY_MEDIUM,
    SOURCE_ANALYSIS,
    SOURCE_MANUAL,
    SOURCE_SCAN,
    STATUS_DONE,
    STATUS_REMOVED,
    STATUS_TODO,
    WorkQueueConflict,
)

TITLE_MAX = 300

NOT_FOUND_CARD = "Deze kaart bestaat niet (meer). Ververs het bord."
NOT_FOUND_CUSTOMER = "Klant niet gevonden."
RESOLVED_BY_SOURCE = "Deze kaart is vanzelf afgerond: de bron heeft niets meer open staan."
GROUP_ALREADY_OPEN = "Er staat al een open kaart voor deze groep."
NOTHING_OPEN = "De bron heeft voor deze kaart niets meer open staan."

# Bronnen waarvan de groep bij terugzetten opnieuw uit de bron komt.
RECOLLECT_SOURCES = frozenset({SOURCE_SCAN, SOURCE_ANALYSIS})


class ActionError(Exception):
    """Ongeldig verzoek (404 of 422) met een platte Nederlandse zin."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# --- lezen en controleren ---------------------------------------------------------


def get_card(db: Session, card_id: str) -> WorkItem:
    """Kaart op id; een onbekende of verwijderde kaart → 404."""
    card = db.get(WorkItem, card_id)
    if card is None or card.status == STATUS_REMOVED:
        raise ActionError(404, NOT_FOUND_CARD)
    return card


def _clean_title(value: Any) -> str:
    title = " ".join(str(value or "").split())
    if not title:
        raise ActionError(422, "Geef de taak een titel.")
    if len(title) > TITLE_MAX:
        raise ActionError(422, f"De titel is te lang (hooguit {TITLE_MAX} tekens).")
    return title


def _check_kind(value: Any) -> str:
    if value not in KINDS:
        raise ActionError(422, "Kies een geldige soort.")
    return value


def _check_status(value: Any) -> str:
    if value not in BOARD_STATUSES:
        raise ActionError(422, "Kies een geldige kolom.")
    return value


def _check_assignee(db: Session, value: Any) -> str | None:
    """Bestaande medewerker of None (leeg = niet toegewezen); onbekend → 422."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if db.get(User, str(value)) is None:
        raise ActionError(422, "Deze medewerker bestaat niet.")
    return str(value)


def _clean_note(value: Any) -> str | None:
    text = str(value) if value is not None else ""
    return text if text.strip() else None


# --- aanmaken -----------------------------------------------------------------------


def create_task(
    db: Session,
    *,
    user_id: str,
    now: datetime,
    title: Any,
    customer_id: Any,
    kind: Any,
    status: Any = None,
    assignee_id: Any = None,
    note: Any = None,
) -> WorkItem:
    """Eigen taak (`source = manual`), ernst middel. Status Klaar mag (bovenaan, afgerond door
    de gebruiker); anders op ernst in de kolom."""
    clean_title = _clean_title(title)
    if not customer_id or not str(customer_id).strip():
        raise ActionError(422, "Kies een klant.")
    if db.get(CustomerWebsite, str(customer_id)) is None:
        raise ActionError(404, NOT_FOUND_CUSTOMER)
    clean_kind = _check_kind(kind)
    clean_status = _check_status(status or STATUS_TODO)
    assignee = _check_assignee(db, assignee_id)

    card = WorkItem(
        id=str(uuid.uuid4()),
        customer_website_id=str(customer_id),
        source=SOURCE_MANUAL,
        group_key=None,
        active_key=None,
        status=STATUS_TODO,
        kind=clean_kind,
        title=clean_title,
        severity=SEVERITY_MEDIUM,
        item_count=0,
        items=[],
        fingerprint=None,
        assignee_id=assignee,
        note=_clean_note(note),
        resolved_by_source=False,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    if clean_status == STATUS_DONE:
        card.position = position_top(db, STATUS_DONE)
        mark_done(card, user_id, now)
    else:
        card.position = position_for_new(db, clean_status, SEVERITY_MEDIUM)
        mark_active(card, clean_status, now=now)
    db.add(card)
    db.flush()
    return card


# --- wijzigen -----------------------------------------------------------------------


@dataclass
class CardChanges:
    """Gevraagde wijzigingen; alleen de velden in `fields` zijn meegestuurd."""

    fields: set[str]
    status: Any = None
    after_id: Any = None
    before_id: Any = None
    assignee_id: Any = None
    note: Any = None
    title: Any = None
    kind: Any = None


def _complete(db: Session, card: WorkItem, user_id: str, now: datetime) -> None:
    if card.source != SOURCE_MANUAL:
        ADAPTERS[card.source].complete(db, card, user_id, now)
    mark_done(card, user_id, now)


def _reopen(db: Session, card: WorkItem, status: str, user_id: str, now: datetime) -> None:
    if card.source == SOURCE_MANUAL:
        mark_active(card, status, now=now)
        return
    if card.resolved_by_source:
        raise WorkQueueConflict(RESOLVED_BY_SOURCE)
    duplicate = (
        db.query(WorkItem.id)
        .filter(
            WorkItem.customer_website_id == card.customer_website_id,
            WorkItem.source == card.source,
            WorkItem.group_key == card.group_key,
            WorkItem.status.in_(ACTIVE_STATUSES),
            WorkItem.id != card.id,
        )
        .first()
    )
    if duplicate is not None:
        raise WorkQueueConflict(GROUP_ALREADY_OPEN)

    adapter = ADAPTERS[card.source]
    adapter.reopen(db, card, user_id, now)

    if card.source in RECOLLECT_SOURCES:
        db.flush()
        group = next(
            (g for g in adapter.collect(db, {card.customer_website_id}) if g.group_key == card.group_key),
            None,
        )
        if group is None or not group.items:
            # De router draait het terugzetten in de bron terug (rollback).
            raise WorkQueueConflict(NOTHING_OPEN)
        card.items = [item.as_dict() for item in group.items]
        card.item_count = len(group.items)
        card.severity = group.severity
        card.fingerprint = fingerprint_of(group.items, group.severity)

    mark_active(card, status, now=now)


def update_card(db: Session, card: WorkItem, changes: CardChanges, *, user_id: str, now: datetime) -> WorkItem:
    """Past een kaart aan. Eerst alles controleren, dan pas schrijven (ook naar de bron)."""
    fields = changes.fields
    manual = card.source == SOURCE_MANUAL

    # 1. Controleren.
    new_title = new_kind = None
    if "title" in fields and changes.title is not None:
        if not manual:
            raise ActionError(422, "De titel van een automatische kaart kan niet worden gewijzigd.")
        new_title = _clean_title(changes.title)
    if "kind" in fields and changes.kind is not None:
        if not manual:
            raise ActionError(422, "De soort van een automatische kaart kan niet worden gewijzigd.")
        new_kind = _check_kind(changes.kind)
    assignee = _check_assignee(db, changes.assignee_id) if "assignee_id" in fields else None

    target = card.status
    if "status" in fields and changes.status is not None:
        target = _check_status(changes.status)
    after_id = changes.after_id or None
    before_id = changes.before_id or None
    status_changes = target != card.status

    # 2. Nieuwe positie (controleert ook de buren; een buur uit een andere kolom → 422).
    position: float | None = None
    if after_id or before_id:
        try:
            position = position_between(db, target, after_id, before_id, exclude_id=card.id)
        except ValueError as exc:
            raise ActionError(422, "De kaart kan daar niet worden neergezet. Ververs het bord.") from exc
    elif status_changes:
        position = (
            position_top(db, STATUS_DONE)
            if target == STATUS_DONE
            else position_between(db, target, None, None, exclude_id=card.id)
        )

    # 3. Velden.
    if new_title is not None:
        card.title = new_title
    if new_kind is not None:
        card.kind = new_kind
    if "assignee_id" in fields:
        card.assignee_id = assignee
    if "note" in fields:
        card.note = _clean_note(changes.note)

    # 4. Status, met terugschrijven naar de bron.
    if status_changes:
        if target == STATUS_DONE:
            _complete(db, card, user_id, now)
        elif card.status == STATUS_DONE:
            _reopen(db, card, target, user_id, now)
        else:
            mark_active(card, target, now=now)
    if position is not None:
        card.position = position
    card.updated_at = now
    db.flush()
    return card


# --- verwijderen --------------------------------------------------------------------


def delete_card(db: Session, card: WorkItem, *, user_id: str, now: datetime) -> None:
    """Eigen taak: rij weg. Automatische kaart: bron bijwerken (`dismiss`) en de kaart op
    'removed', zodat hij als geheugen blijft bestaan en niet terugkomt."""
    if card.source == SOURCE_MANUAL:
        db.delete(card)
        db.flush()
        return
    ADAPTERS[card.source].dismiss(db, card, user_id, now)
    mark_removed(card, now)
    db.flush()
