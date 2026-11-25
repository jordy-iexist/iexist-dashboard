"""Werkvoorraad: bureaubreed kanban-bord met kaarten uit de bronnen en eigen taken.

`GET /board` synchroniseert eerst scan, analyse en aanpassingen (zie `services/board.py`). De
acties (`services/actions.py`) committen niet; dat doet de router, en bij een fout draait hij
alles terug voordat hij antwoordt.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id
from app.db.session import get_db
from app.features.work_queue.mappers import to_board, to_card_detail, to_user_options
from app.features.work_queue.schemas import (
    BoardResponse,
    CardCreate,
    CardDetail,
    CardUpdate,
    OkResponse,
    UserOption,
)
from app.features.work_queue.services import actions
from app.features.work_queue.services.actions import ActionError, CardChanges
from app.features.work_queue.services.board import build_board, sync_board
from app.features.work_queue.services.types import WorkQueueConflict

router = APIRouter(prefix="/api/work-queue", tags=["work-queue"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fail(db: Session, exc: Exception) -> HTTPException:
    """Rollback en de bijbehorende HTTP-fout met een platte zin."""
    db.rollback()
    if isinstance(exc, ActionError):
        return HTTPException(status_code=exc.status_code, detail=exc.message)
    if isinstance(exc, WorkQueueConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, IntegrityError):
        return HTTPException(status_code=409, detail=actions.GROUP_ALREADY_OPEN)
    raise exc


def _get_card(db: Session, card_id: str):
    try:
        return actions.get_card(db, card_id)
    except ActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/board", response_model=BoardResponse)
def get_board(
    customer_id: str | None = Query(default=None, max_length=64),
    assignee_id: str | None = Query(default=None, max_length=64),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    now = _now()
    sync_board(db, now)
    data = build_board(db, now, customer_id=customer_id or None, assignee_id=assignee_id or None)
    return to_board(data)


@router.get("/users", response_model=list[UserOption])
def list_users(
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    return to_user_options(db)


@router.get("/cards/{card_id}", response_model=CardDetail)
def get_card(
    card_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    return to_card_detail(db, _get_card(db, card_id))


@router.post("/cards", response_model=CardDetail, status_code=201)
def create_card(
    payload: CardCreate,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    try:
        card = actions.create_task(
            db,
            user_id=user_id,
            now=_now(),
            title=payload.title,
            customer_id=payload.customer_id,
            kind=payload.kind,
            status=payload.status,
            assignee_id=payload.assignee_id,
            note=payload.note,
        )
        db.commit()
    except (ActionError, WorkQueueConflict, IntegrityError) as exc:
        raise _fail(db, exc) from exc
    return to_card_detail(db, card)


@router.patch("/cards/{card_id}", response_model=CardDetail)
def update_card(
    card_id: str,
    payload: CardUpdate,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    card = _get_card(db, card_id)
    changes = CardChanges(
        fields=set(payload.model_fields_set),
        status=payload.status,
        after_id=payload.after_id,
        before_id=payload.before_id,
        assignee_id=payload.assignee_id,
        note=payload.note,
        title=payload.title,
        kind=payload.kind,
    )
    try:
        actions.update_card(db, card, changes, user_id=user_id, now=_now())
        db.commit()
    except (ActionError, WorkQueueConflict, IntegrityError) as exc:
        raise _fail(db, exc) from exc
    return to_card_detail(db, card)


@router.delete("/cards/{card_id}", response_model=OkResponse)
def delete_card(
    card_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    card = _get_card(db, card_id)
    try:
        actions.delete_card(db, card, user_id=user_id, now=_now())
        db.commit()
    except (ActionError, WorkQueueConflict, IntegrityError) as exc:
        raise _fail(db, exc) from exc
    return OkResponse()
