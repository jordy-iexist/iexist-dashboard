"""Het bord van de werkvoorraad: synchroniseren bij het ophalen en de kaarten per kolom.

Bij elk `GET /board` worden de drie bronnen die in de database staan (scan, analyse,
aanpassingen) voor alle klanten gesynchroniseerd. Search Console hoort daar niet bij: die bron
roept Google aan en loopt via de wekelijkse taak. Een fout in de synchronisatie breekt het bord
niet: dan volgen een rollback en een logregel, en toont het bord de opgeslagen kaarten.

Op het bord staan de open kaarten (todo, doing, review) en de kaarten die deze week naar Klaar
gingen (`done_at` vanaf maandag 00:00 Amsterdam). Verwijderde kaarten staan er nooit op.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.models import CustomerWebsite, User, WorkItem
from app.features.launch_checklist.services.scan_recovery import as_utc
from app.features.work_queue.services.cards import week_start_utc
from app.features.work_queue.services.sources_analysis import analysis_adapter
from app.features.work_queue.services.sources_scan import scan_adapter
from app.features.work_queue.services.sources_search_console import search_console_adapter
from app.features.work_queue.services.sources_site_changes import site_changes_adapter
from app.features.work_queue.services.sync import SyncResult, apply_groups
from app.features.work_queue.services.types import (
    ACTIVE_STATUSES,
    BOARD_STATUSES,
    STATUS_DONE,
    Adapter,
    Group,
)

logger = logging.getLogger(__name__)

# Alle bronnen met een adapter (voor de acties op een kaart); een eigen taak heeft er geen.
ADAPTERS: dict[str, Adapter] = {
    adapter.source: adapter
    for adapter in (scan_adapter, analysis_adapter, search_console_adapter, site_changes_adapter)
}

# Bronnen die bij het ophalen van het bord gesynchroniseerd worden (niet Search Console).
BOARD_SYNC_ADAPTERS: tuple[Adapter, ...] = (scan_adapter, analysis_adapter, site_changes_adapter)

# Waarde van `assignee_id` voor "niet toegewezen".
UNASSIGNED = "none"


def sync_board(db: Session, now: datetime) -> SyncResult | None:
    """Synchroniseert scan, analyse en aanpassingen voor alle klanten en commit.

    Bij een fout: rollback, loggen en None; het bord toont dan de opgeslagen kaarten.
    """
    try:
        groups: list[Group] = []
        for adapter in BOARD_SYNC_ADAPTERS:
            groups.extend(adapter.collect(db, None))
        result = apply_groups(
            db,
            groups,
            sources={adapter.source for adapter in BOARD_SYNC_ADAPTERS},
            customer_ids=None,
            now=now,
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        logger.exception("Werkvoorraad: synchroniseren van het bord mislukt; opgeslagen kaarten worden getoond")
        return None


@dataclass
class BoardData:
    """Alles wat de mapper nodig heeft voor het antwoord van `GET /board`."""

    week_start: datetime
    # Per status (todo, doing, review, done) de kaarten, op positie.
    columns: dict[str, list[WorkItem]]
    unassigned: int
    customers: list[tuple[str, str, int]]  # (id, naam, open kaarten)
    users: list[tuple[str, str, int]]  # (id, e-mail, open kaarten)
    customer_names: dict[str, str] = field(default_factory=dict)
    user_emails: dict[str, str] = field(default_factory=dict)


def _open_counts(db: Session, column) -> Counter:
    rows = (
        db.query(column, func.count(WorkItem.id))
        .filter(WorkItem.status.in_(ACTIVE_STATUSES), column.isnot(None))
        .group_by(column)
        .all()
    )
    return Counter({key: count for key, count in rows})


def build_board(
    db: Session,
    now: datetime,
    *,
    customer_id: str | None = None,
    assignee_id: str | None = None,
) -> BoardData:
    """De kaarten op het bord, gefilterd op klant en medewerker (`UNASSIGNED` = niet
    toegewezen). De lijsten met klanten en medewerkers zijn ongefilterd. Laadt `items` niet."""
    week_start = week_start_utc(now)

    query = db.query(WorkItem).filter(
        or_(
            WorkItem.status.in_(ACTIVE_STATUSES),
            # Ruime grens in SQL (naïeve datums uit SQLite), precies in Python hieronder.
            (WorkItem.status == STATUS_DONE) & (WorkItem.done_at >= week_start - timedelta(days=1)),
        )
    )
    if customer_id:
        query = query.filter(WorkItem.customer_website_id == customer_id)
    if assignee_id == UNASSIGNED:
        query = query.filter(WorkItem.assignee_id.is_(None))
    elif assignee_id:
        query = query.filter(WorkItem.assignee_id == assignee_id)

    columns: dict[str, list[WorkItem]] = {status: [] for status in BOARD_STATUSES}
    for card in query.order_by(WorkItem.position, WorkItem.id).all():
        if card.status == STATUS_DONE and (card.done_at is None or as_utc(card.done_at) < week_start):
            continue
        columns[card.status].append(card)
    unassigned = sum(
        1 for status in ACTIVE_STATUSES for card in columns[status] if not card.assignee_id
    )

    customer_rows = db.query(CustomerWebsite.id, CustomerWebsite.name).all()
    customer_open = _open_counts(db, WorkItem.customer_website_id)
    customers = sorted(
        ((cid, name or "", customer_open.get(cid, 0)) for cid, name in customer_rows),
        key=lambda row: (row[1].casefold(), row[0]),
    )

    user_rows = db.query(User.id, User.email).all()
    user_open = _open_counts(db, WorkItem.assignee_id)
    users = sorted(
        ((uid, email or "", user_open.get(uid, 0)) for uid, email in user_rows),
        key=lambda row: (row[1].split("@", 1)[0].casefold(), row[1].casefold(), row[0]),
    )

    return BoardData(
        week_start=week_start,
        columns=columns,
        unassigned=unassigned,
        customers=customers,
        users=users,
        customer_names={cid: name for cid, name, _count in customers},
        user_emails={uid: email for uid, email, _count in users},
    )
