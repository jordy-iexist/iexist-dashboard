"""Bron 'analysis' van de werkvoorraad: verbeterpunten uit de concurrentieanalyse, één groep per
klant per zoekwoord.

Elke nieuwe analyse maakt nieuwe zoekwoordrijen; de vaste identiteit is de kolom
`CompetitorAnalysisKeyword.keyword_key` (gevuld met `customers.rankings.keyword_key`). Per (klant,
`keyword_key`) telt de nieuwste zoekwoordrij die voltooid is (`status == "completed"`) en waarvan
de AI-stap geslaagd is (`ai_state == "ok"`); alleen dan zijn de verbeterpunten gemaakt. Een
lopende, mislukte of zonder AI afgeronde nieuwere analyse verdringt de vorige dus niet.

Open = verbeterpunten van die rij met `done == False`. Naar Klaar vinkt ze af zoals het
afvinken in de concurrentieanalyse (`done_by`, `done_at`); terugzetten vinkt ze weer uit.
Verwijderen schrijft niets terug: de sync onderdrukt dan de hele groepssleutel.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import CompetitorAnalysis, CompetitorAnalysisAction, CompetitorAnalysisKeyword, WorkItem
from app.features.launch_checklist.services.scan_recovery import as_utc
from app.features.work_queue.services.cards import fingerprint_of
from app.features.work_queue.services.types import (
    KIND_CONTENT,
    SEVERITIES,
    SEVERITY_MEDIUM,
    SOURCE_ANALYSIS,
    Group,
    Item,
    severity_rank,
)

KEYWORD_COMPLETED = "completed"
AI_OK = "ok"

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _ts(value: datetime | None) -> datetime:
    return as_utc(value) if value is not None else _EPOCH


def _severity(value: str | None) -> str | None:
    return value if value in SEVERITIES else None


def group_title(keyword: str) -> str:
    return f"Verbeterpunten “{keyword}”"


def _newest_keywords(
    db: Session, customer_ids: set[str] | None, keyword_key: str | None = None,
) -> dict[tuple[str, str], Any]:
    """Nieuwste geslaagde zoekwoordrij per (klant, keyword_key), lichte kolommen."""
    query = (
        db.query(
            CompetitorAnalysisKeyword.id, CompetitorAnalysisKeyword.analysis_id,
            CompetitorAnalysisKeyword.keyword, CompetitorAnalysisKeyword.keyword_key,
            CompetitorAnalysisKeyword.created_at, CompetitorAnalysis.customer_website_id,
            CompetitorAnalysis.created_at.label("analysis_created_at"),
        )
        .join(CompetitorAnalysis, CompetitorAnalysis.id == CompetitorAnalysisKeyword.analysis_id)
        .filter(CompetitorAnalysisKeyword.status == KEYWORD_COMPLETED, CompetitorAnalysisKeyword.ai_state == AI_OK)
    )
    if customer_ids is not None:
        query = query.filter(CompetitorAnalysis.customer_website_id.in_(sorted(customer_ids)))
    if keyword_key is not None:
        query = query.filter(CompetitorAnalysisKeyword.keyword_key == keyword_key)

    def order(row: Any) -> tuple[datetime, datetime, str]:
        return _ts(row.analysis_created_at), _ts(row.created_at), row.id

    newest: dict[tuple[str, str], Any] = {}
    for row in query.all():
        slot = (row.customer_website_id, row.keyword_key)
        if slot not in newest or order(row) > order(newest[slot]):
            newest[slot] = row
    return newest


def _open_groups(db: Session, customer_ids: set[str] | None, keyword_key: str | None = None) -> list[Group]:
    newest = _newest_keywords(db, customer_ids, keyword_key)
    if not newest:
        return []
    by_keyword: dict[str, list[Any]] = defaultdict(list)
    for action in (
        db.query(
            CompetitorAnalysisAction.id, CompetitorAnalysisAction.keyword_id, CompetitorAnalysisAction.analysis_id,
            CompetitorAnalysisAction.title, CompetitorAnalysisAction.impact, CompetitorAnalysisAction.sort_order,
        )
        .filter(
            CompetitorAnalysisAction.keyword_id.in_(sorted(row.id for row in newest.values())),
            CompetitorAnalysisAction.done.is_(False),
        )
        .all()
    ):
        by_keyword[action.keyword_id].append(action)

    groups: list[Group] = []
    for (customer_id, key), keyword in sorted(newest.items()):
        actions = sorted(by_keyword.get(keyword.id, []), key=lambda a: (a.sort_order or 0, a.id))
        if not actions:
            continue
        items = [
            Item(
                key=action.id,
                title=action.title,
                url=None,
                severity=_severity(action.impact),
                ref={"analysis_id": keyword.analysis_id, "keyword_id": keyword.id, "action_id": action.id},
            )
            for action in actions
        ]
        known = [item.severity for item in items if item.severity]
        groups.append(Group(
            customer_id=customer_id,
            source=SOURCE_ANALYSIS,
            group_key=key,
            title=group_title(keyword.keyword),
            kind=KIND_CONTENT,
            severity=max(known, key=severity_rank) if known else SEVERITY_MEDIUM,
            items=items,
        ))
    return groups


class AnalysisAdapter:
    """Koppeling tussen de verbeterpunten van de concurrentieanalyse en de werkvoorraad."""

    source = SOURCE_ANALYSIS

    def collect(self, db: Session, customer_ids: set[str] | None = None) -> list[Group]:
        """Open groepen; voor alle klanten in twee queries (zoekwoorden, open verbeterpunten)."""
        if customer_ids is not None and not customer_ids:
            return []
        return _open_groups(db, set(customer_ids) if customer_ids is not None else None)

    def complete(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None:
        """Open verbeterpunten van de huidige zoekwoordrij afvinken; de momentopname op de kaart
        wordt wat er is afgevinkt."""
        group = next(iter(_open_groups(db, {card.customer_website_id}, card.group_key)), None)
        if group is None:
            return
        ids = [item.key for item in group.items]
        for action in db.query(CompetitorAnalysisAction).filter(CompetitorAnalysisAction.id.in_(ids)).all():
            if not action.done:
                action.done = True
                action.done_by = user_id
                action.done_at = now
                action.updated_at = now
        card.items = [item.as_dict() for item in group.items]
        card.item_count = len(group.items)
        card.severity = group.severity
        card.fingerprint = fingerprint_of(group.items, group.severity)
        db.flush()

    def reopen(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None:
        """Verbeterpunten uit de momentopname die nog bestaan weer uitvinken."""
        ids = sorted({
            str((item.get("ref") or {}).get("action_id") or item.get("key"))
            for item in (card.items or [])
            if isinstance(item, dict) and ((item.get("ref") or {}).get("action_id") or item.get("key"))
        })
        if not ids:
            return
        for action in db.query(CompetitorAnalysisAction).filter(CompetitorAnalysisAction.id.in_(ids)).all():
            if action.done:
                action.done = False
                action.done_by = None
                action.done_at = None
                action.updated_at = now
        db.flush()

    def dismiss(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None:
        """Niets terugschrijven: de sync onderdrukt de hele groepssleutel (`SUPPRESS_WHOLE_GROUP`)."""
        return None


analysis_adapter = AnalysisAdapter()
