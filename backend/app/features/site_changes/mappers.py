from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import User
from app.features.site_changes.schemas import (
    ChangeGroup,
    ChangeItem,
    PageDetail,
    PageSummary,
    SchemaSummary,
    SourceRef,
    VerifyDetail,
)
from app.features.site_changes.services.changes import (
    APPROVED,
    DONE,
    KIND_SUGGESTION,
    OPEN,
    REJECTED,
    TOPIC_ORDER,
    TOPICS,
    Entry,
)
from app.features.site_changes.services.sources import PageInfo, path_of
from app.features.site_changes.services.verify import issue_checkable, suggestion_checkable

_SEVERITY_ORDER = {"hoog": 0, "middel": 1, "laag": 2}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def user_names(db: Session, entries: list[Entry]) -> dict[str, str]:
    """Weergavenaam per gebruiker: het deel van het e-mailadres vóór de @."""
    ids: set[str] = set()
    for entry in entries:
        if entry.row is not None:
            ids.update(i for i in (entry.row.reviewed_by, entry.row.done_by) if i)
        elif entry.source is not None and entry.source.updated_by:
            ids.add(entry.source.updated_by)
    if not ids:
        return {}
    return {
        user_id: (email or "").split("@", 1)[0] or None
        for user_id, email in db.query(User.id, User.email).filter(User.id.in_(ids))
    }


def _checkable(entry: Entry) -> bool:
    if entry.kind == KIND_SUGGESTION:
        value = entry.field("approved_value") or entry.field("proposed_value")
        return suggestion_checkable(entry.topic, entry.field("ref"), value, entry.page_url)
    if entry.source is not None:
        return issue_checkable(entry.source.type_key)
    ref = entry.row.source_ref if entry.row is not None and isinstance(entry.row.source_ref, dict) else {}
    return issue_checkable(str(ref.get("type") or ""))


def _source_ref(entry: Entry) -> SourceRef:
    if entry.source is not None:
        return SourceRef(**entry.source.source_ref)
    ref = entry.row.source_ref if entry.row is not None and isinstance(entry.row.source_ref, dict) else {}
    return SourceRef(suggestion_id=ref.get("suggestion_id"), issue_id=ref.get("issue_id"))


def to_change_item(
    entry: Entry, names: dict[str, str], *, transient_detail: dict[str, Any] | None = None,
    transient_verified: bool | None = None,
) -> ChangeItem:
    row, source = entry.row, entry.source
    status = entry.status or OPEN
    reviewed_by = reviewed_at = done_by = done_at = None
    verified = None
    detail: Any = None
    if row is not None:
        reviewed_by, reviewed_at = names.get(row.reviewed_by) if row.reviewed_by else None, row.reviewed_at
        done_by, done_at = names.get(row.done_by) if row.done_by else None, row.done_at
        verified, detail = row.verified, row.verify_detail
    elif source is not None:
        # Status uit de bron (bijv. 'overgenomen' of 'genegeerd' elders in het dashboard).
        who = names.get(source.updated_by) if source.updated_by else None
        if status == DONE:
            done_by, done_at = who, source.updated_at
        elif status == REJECTED:
            reviewed_by, reviewed_at = who, source.updated_at
    if transient_detail is not None:
        detail, verified = transient_detail, transient_verified
    return ChangeItem(
        key=entry.key,
        change_id=row.id if row is not None else None,
        source_kind=entry.kind,
        source_ref=_source_ref(entry),
        topic=entry.topic,
        title=entry.field("title") or "",
        description=entry.field("description"),
        current_value=entry.field("current_value"),
        proposed_value=entry.field("proposed_value"),
        approved_value=row.approved_value if row is not None else None,
        edited=bool(row.edited) if row is not None else False,
        rationale=entry.field("rationale"),
        ref=entry.field("ref"),
        severity=entry.field("severity"),
        item_label=entry.field("item_label"),
        status=status,
        checkable=_checkable(entry),
        verified=verified,
        verify_detail=VerifyDetail(**detail) if isinstance(detail, dict) and detail.get("checked_at") else None,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        done_by=done_by,
        done_at=done_at,
        note=row.note if row is not None else None,
    )


def _open_sort(item: ChangeItem) -> tuple:
    return (
        0 if item.source_kind == KIND_SUGGESTION else 1,
        0 if item.status == APPROVED else 1,
        _SEVERITY_ORDER.get(item.severity or "", 3),
        item.title.lower(),
    )


def counts(entries: list[Entry]) -> tuple[int, int, int]:
    statuses = [e.status for e in entries]
    return statuses.count(OPEN), statuses.count(APPROVED), statuses.count(DONE)


def to_page_summary(info: PageInfo, entries: list[Entry]) -> PageSummary:
    open_count, approved_count, done_count = counts(entries)
    return PageSummary(url=info.url, path=info.path or path_of(info.url), title=info.title,
                       open_count=open_count, approved_count=approved_count, done_count=done_count)


def last_checked(entries: list[Entry]) -> datetime | None:
    latest: datetime | None = None
    for entry in entries:
        detail = entry.row.verify_detail if entry.row is not None else None
        raw = detail.get("checked_at") if isinstance(detail, dict) else None
        if not raw:
            continue
        try:
            value = datetime.fromisoformat(str(raw))
        except ValueError:
            continue
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        if latest is None or value > latest:
            latest = value
    return latest


def to_page_detail(
    info: PageInfo,
    entries: list[Entry],
    names: dict[str, str],
    schema: dict[str, Any] | None,
    *,
    transient: dict[str, tuple[dict[str, Any], bool | None]] | None = None,
    last_checked_at: datetime | None = None,
) -> PageDetail:
    transient = transient or {}
    groups: dict[str, list[ChangeItem]] = {}
    rejected: list[ChangeItem] = []
    done: list[ChangeItem] = []
    for entry in entries:
        extra = transient.get(entry.key)
        item = to_change_item(
            entry, names,
            transient_detail=extra[0] if extra else None,
            transient_verified=extra[1] if extra else None,
        )
        if item.status in (OPEN, APPROVED):
            groups.setdefault(item.topic, []).append(item)
        elif item.status == REJECTED:
            rejected.append(item)
        elif item.status == DONE:
            done.append(item)
    rejected.sort(key=lambda i: i.reviewed_at or _EPOCH, reverse=True)
    done.sort(key=lambda i: i.done_at or _EPOCH, reverse=True)
    ordered = sorted(groups, key=lambda t: TOPIC_ORDER.get(t, len(TOPICS)))
    labels = dict(TOPICS)
    return PageDetail(
        url=info.url,
        path=info.path or path_of(info.url),
        title=info.title,
        groups=[ChangeGroup(topic=t, label=labels[t], items=sorted(groups[t], key=_open_sort)) for t in ordered],
        rejected=rejected,
        done=done,
        schema=SchemaSummary(**schema) if schema is not None else None,
        last_checked_at=last_checked_at or last_checked(entries),
    )
