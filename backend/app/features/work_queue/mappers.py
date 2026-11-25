from typing import Any

from sqlalchemy.orm import Session

from app.db.models import CustomerWebsite, User, WorkItem
from app.features.launch_checklist.services.golive_checklist import MONITOR_PHASE
from app.features.launch_checklist.services.scan_recovery import as_utc
from app.features.site_changes.services.sources import path_of
from app.features.work_queue.schemas import (
    AnalysisLink,
    BoardColumn,
    BoardCustomer,
    BoardResponse,
    BoardTotals,
    BoardUser,
    Card,
    CardDetail,
    CardItem,
    ScanLink,
    SearchConsoleLink,
    SiteChangesLink,
    UserOption,
)
from app.features.work_queue.services.board import BoardData
from app.features.work_queue.services.types import (
    BOARD_STATUSES,
    KIND_TECHNIEK,
    KINDS,
    SEVERITIES,
    SEVERITY_MEDIUM,
    SOURCE_ANALYSIS,
    SOURCE_SCAN,
    SOURCE_SEARCH_CONSOLE,
    SOURCE_SITE_CHANGES,
    unit_for,
)

COLUMN_LABELS: dict[str, str] = {
    "todo": "Te doen",
    "doing": "Bezig",
    "review": "Review",
    "done": "Klaar deze week",
}

# Fases met een eigen sectie in de scan (de monitor is fase 6).
SCAN_PHASES = frozenset({1, 2, 3, 4, MONITOR_PHASE})


def display_name(email: str | None) -> str | None:
    """Weergavenaam: het deel van het e-mailadres vóór de @ (zelfde regel als
    `site_changes.mappers.user_names`)."""
    return (email or "").split("@", 1)[0] or None


def user_name_map(db: Session, ids: set[str | None]) -> dict[str, str]:
    wanted = {user_id for user_id in ids if user_id}
    if not wanted:
        return {}
    return {
        user_id: display_name(email) or email
        for user_id, email in db.query(User.id, User.email).filter(User.id.in_(sorted(wanted)))
    }


def to_card(card: WorkItem, customer_names: dict[str, str], user_names: dict[str, str]) -> Card:
    count = int(card.item_count or 0)
    return Card(
        id=card.id,
        customer_id=card.customer_website_id,
        customer_name=customer_names.get(card.customer_website_id, ""),
        source=card.source,
        kind=card.kind if card.kind in KINDS else KIND_TECHNIEK,
        title=card.title,
        item_count=count,
        unit=unit_for(card.source, count),
        severity=card.severity if card.severity in SEVERITIES else SEVERITY_MEDIUM,
        status=card.status,
        position=float(card.position),
        assignee_id=card.assignee_id,
        assignee_name=user_names.get(card.assignee_id) if card.assignee_id else None,
        has_note=bool(card.note and card.note.strip()),
        resolved_by_source=bool(card.resolved_by_source),
        done_at=as_utc(card.done_at),
        created_at=as_utc(card.created_at),
    )


def to_board(data: BoardData) -> BoardResponse:
    user_names = {uid: display_name(email) or email for uid, email in data.user_emails.items()}
    columns = [
        BoardColumn(
            status=status,
            label=COLUMN_LABELS[status],
            count=len(data.columns[status]),
            cards=[to_card(card, data.customer_names, user_names) for card in data.columns[status]],
        )
        for status in BOARD_STATUSES
    ]
    return BoardResponse(
        week_start=data.week_start,
        columns=columns,
        totals=BoardTotals(
            **{status: len(data.columns[status]) for status in BOARD_STATUSES},
            unassigned=data.unassigned,
        ),
        customers=[BoardCustomer(id=cid, name=name, open_count=count) for cid, name, count in data.customers],
        users=[
            BoardUser(id=uid, name=display_name(email) or email, email=email, open_count=count)
            for uid, email, count in data.users
        ],
    )


def _items(card: WorkItem) -> list[dict[str, Any]]:
    return [item for item in (card.items or []) if isinstance(item, dict)]


def to_card_item(item: dict[str, Any]) -> CardItem:
    url = item.get("url") or None
    severity = item.get("severity")
    return CardItem(
        key=str(item.get("key") or ""),
        title=str(item.get("title") or ""),
        url=url,
        path=path_of(url) if url else None,
        severity=severity if severity in SEVERITIES else None,
    )


def source_link(card: WorkItem) -> ScanLink | AnalysisLink | SearchConsoleLink | SiteChangesLink | None:
    """Gestructureerde verwijzing naar de bron; de frontend bouwt er de route van. Null bij een
    eigen taak, of als de momentopname de benodigde verwijzing mist."""
    items = _items(card)
    first = items[0] if items else {}
    ref = first.get("ref") if isinstance(first.get("ref"), dict) else {}
    customer_id = card.customer_website_id

    if card.source == SOURCE_SCAN:
        # Niet op `scan_id`: die kan verouderd zijn; de fase wijst naar de juiste sectie.
        try:
            phase = int(ref.get("phase"))
        except (TypeError, ValueError):
            return None
        if phase not in SCAN_PHASES or not card.group_key:
            return None
        return ScanLink(customer_id=customer_id, phase=phase, issue_type=card.group_key)
    if card.source == SOURCE_ANALYSIS:
        analysis_id, keyword_id = ref.get("analysis_id"), ref.get("keyword_id")
        if not analysis_id:
            return None
        return AnalysisLink(customer_id=customer_id, analysis_id=str(analysis_id), keyword_id=str(keyword_id or ""))
    if card.source == SOURCE_SEARCH_CONSOLE:
        return SearchConsoleLink(customer_id=customer_id)
    if card.source == SOURCE_SITE_CHANGES:
        url = ref.get("page_url") or first.get("url") or ""
        return SiteChangesLink(customer_id=customer_id, url=str(url))
    return None


def to_card_detail(db: Session, card: WorkItem) -> CardDetail:
    customer = db.get(CustomerWebsite, card.customer_website_id)
    customer_names = {card.customer_website_id: customer.name if customer is not None else ""}
    names = user_name_map(db, {card.assignee_id, card.done_by, card.created_by})
    base = to_card(card, customer_names, names)
    return CardDetail(
        **base.model_dump(),
        note=card.note,
        items=[to_card_item(item) for item in _items(card)],
        source_link=source_link(card),
        done_by_name=names.get(card.done_by) if card.done_by else None,
        created_by_name=names.get(card.created_by) if card.created_by else None,
    )


def to_user_options(db: Session) -> list[UserOption]:
    users = [
        UserOption(id=user_id, name=display_name(email) or email or "", email=email or "")
        for user_id, email in db.query(User.id, User.email).all()
    ]
    users.sort(key=lambda user: (user.name.casefold(), user.email.casefold(), user.id))
    return users
