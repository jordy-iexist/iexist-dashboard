"""Synchroniseren van bronnen naar kaarten, en de statusovergangen van een kaart.

`apply_groups` krijgt de open groepen van één of meer bronnen en:
- maakt een kaart in 'todo' voor een groep zonder open kaart;
- werkt een open kaart bij als de groep veranderd is (andere items of ernst); positie, status,
  toewijzing en notitie blijven staan;
- rondt een open kaart zonder groep vanzelf af (`resolved_by_source`), maar alleen voor de
  klanten en bronnen die in deze ronde beoordeeld zijn.
Verwijderde kaarten en de rust na handmatig afronden onderdrukken items (zie `types.py`).

Gelijktijdig aanmaken (twee medewerkers openen tegelijk het bord) wordt opgevangen door de
unieke sleutel op (klant, bron, `active_key`): de nieuwe kaart gaat in een savepoint en bij een
`IntegrityError` wint de kaart van de collega, naar het patroon van `site_changes.upsert_row`.
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, undefer

from app.db.models import WorkItem
from app.features.launch_checklist.services.scan_recovery import as_utc
from app.features.work_queue.services.cards import fingerprint_of, position_for_new, position_top
from app.features.work_queue.services.types import (
    ACTIVE_STATUSES,
    REST_DAYS,
    STATUS_DONE,
    STATUS_REMOVED,
    STATUS_TODO,
    SUPPRESS_WHOLE_GROUP,
    Group,
)

logger = logging.getLogger(__name__)

# (klant, bron, groepssleutel)
GroupId = tuple[str, str, str]


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    resolved: int = 0


# --- statusovergangen ---------------------------------------------------------------


def mark_done(card: WorkItem, user_id: str | None, now: datetime, *, by_source: bool = False) -> None:
    """Kaart naar Klaar. `by_source` = vanzelf afgerond (geeft geen rust). De positie zet de
    aanroeper (bijv. `cards.position_top`)."""
    card.status = STATUS_DONE
    card.active_key = None
    card.done_at = now
    card.done_by = user_id
    card.resolved_by_source = by_source
    card.updated_at = now


def mark_active(card: WorkItem, status: str, *, now: datetime | None = None) -> None:
    """Kaart (terug) naar een open kolom; wist de velden van afronden. Staat er al een open
    kaart voor dezelfde groep, dan faalt de flush op de unieke sleutel; de aanroeper
    controleert dat vooraf. De positie zet de aanroeper."""
    if status not in ACTIVE_STATUSES:
        raise ValueError(f"Geen open status: {status}")
    card.status = status
    card.active_key = card.group_key
    card.done_at = None
    card.done_by = None
    card.resolved_by_source = False
    if now is not None:
        card.updated_at = now


def mark_removed(card: WorkItem, now: datetime) -> None:
    """Kaart verwijderen. De rij blijft bestaan en onderdrukt voortaan zijn items (of de hele
    groep, zie `SUPPRESS_WHOLE_GROUP`)."""
    card.status = STATUS_REMOVED
    card.active_key = None
    card.updated_at = now


# --- onderdrukken -------------------------------------------------------------------


@dataclass
class _Suppression:
    whole: set[GroupId]
    items: dict[GroupId, set[str]]

    def filter(self, group: Group) -> Group | None:
        """Groep zonder onderdrukte items; None als er niets overblijft."""
        group_id = (group.customer_id, group.source, group.group_key)
        if group_id in self.whole:
            return None
        hidden = self.items.get(group_id)
        items = [item for item in group.items if not hidden or item.effective_suppress_key not in hidden]
        if not items:
            return None
        return replace(group, items=items) if len(items) != len(group.items) else group


def _stored_suppress_keys(card: WorkItem) -> set[str]:
    keys: set[str] = set()
    for item in card.items or []:
        if isinstance(item, dict):
            key = item.get("suppress_key") or item.get("key")
            if key:
                keys.add(str(key))
    return keys


def _scoped(query, sources: set[str], customer_ids: set[str] | None):
    query = query.filter(WorkItem.source.in_(sorted(sources)))
    if customer_ids is not None:
        query = query.filter(WorkItem.customer_website_id.in_(sorted(customer_ids)))
    return query


def _load_suppression(
    db: Session, sources: set[str], customer_ids: set[str] | None, now: datetime
) -> _Suppression:
    whole: set[GroupId] = set()
    items: dict[GroupId, set[str]] = defaultdict(set)

    removed = (
        _scoped(db.query(WorkItem), sources, customer_ids)
        .filter(WorkItem.status == STATUS_REMOVED, WorkItem.group_key.isnot(None))
        .options(undefer(WorkItem.items))
        .all()
    )
    for card in removed:
        group_id = (card.customer_website_id, card.source, card.group_key)
        if card.source in SUPPRESS_WHOLE_GROUP:
            whole.add(group_id)
        else:
            items[group_id] |= _stored_suppress_keys(card)

    resting_sources = {source for source in sources if source in REST_DAYS}
    if resting_sources:
        oldest = now - timedelta(days=max(REST_DAYS[source] for source in resting_sources))
        done = (
            _scoped(db.query(WorkItem), resting_sources, customer_ids)
            .filter(
                WorkItem.status == STATUS_DONE,
                WorkItem.resolved_by_source.is_(False),
                WorkItem.group_key.isnot(None),
                WorkItem.done_at.isnot(None),
                WorkItem.done_at >= oldest.astimezone(timezone.utc),
            )
            .options(undefer(WorkItem.items))
            .all()
        )
        for card in done:
            if now - as_utc(card.done_at) < timedelta(days=REST_DAYS[card.source]):
                items[(card.customer_website_id, card.source, card.group_key)] |= _stored_suppress_keys(card)

    return _Suppression(whole=whole, items=dict(items))


# --- synchroniseren -----------------------------------------------------------------


def _apply_group(card: WorkItem, group: Group, fingerprint: str, now: datetime) -> None:
    card.item_count = len(group.items)
    card.severity = group.severity
    card.title = group.title
    card.kind = group.kind
    card.items = [item.as_dict() for item in group.items]
    card.fingerprint = fingerprint
    card.updated_at = now


def _load_active(db: Session, sources: set[str], customer_ids: set[str] | None) -> dict[GroupId, WorkItem]:
    """Open kaarten per groep (zonder de zware `items`-kolom: die is deferred)."""
    cards = (
        _scoped(db.query(WorkItem), sources, customer_ids)
        .filter(WorkItem.status.in_(ACTIVE_STATUSES), WorkItem.group_key.isnot(None))
        .all()
    )
    return {(card.customer_website_id, card.source, card.group_key): card for card in cards}


def _create_card(db: Session, group: Group, fingerprint: str, now: datetime) -> WorkItem | None:
    """Nieuwe kaart in 'todo'; None als een collega hem net aanmaakte (unieke sleutel)."""
    card = WorkItem(
        id=str(uuid.uuid4()),
        customer_website_id=group.customer_id,
        source=group.source,
        group_key=group.group_key,
        active_key=group.group_key,
        status=STATUS_TODO,
        position=position_for_new(db, STATUS_TODO, group.severity),
        resolved_by_source=False,
        created_by=None,
        created_at=now,
    )
    _apply_group(card, group, fingerprint, now)
    try:
        with db.begin_nested():
            db.add(card)
            db.flush()
    except IntegrityError:
        logger.info(
            "Werkvoorraad: kaart voor %s/%s/%s bestond al (gelijktijdig aangemaakt)",
            group.customer_id, group.source, group.group_key,
        )
        return None
    return card


def apply_groups(
    db: Session,
    groups: list[Group],
    *,
    sources: set[str],
    customer_ids: set[str] | None = None,
    now: datetime,
) -> SyncResult:
    """Zet de open groepen van de bronnen in `sources` om naar kaarten. Commit niet.

    `customer_ids=None` = alle klanten zijn beoordeeld; anders alleen deze klanten. Alleen
    voor beoordeelde klanten en bronnen worden open kaarten zonder groep afgerond. Groepen van
    een bron of klant buiten die afbakening worden genegeerd. `Group.severity` wordt
    overgenomen zoals de bron hem aanlevert, ook als er items onderdrukt zijn.
    """
    result = SyncResult()
    sources = set(sources)
    if not sources:
        return result
    customer_ids = set(customer_ids) if customer_ids is not None else None

    # 1. Open kaarten.
    active = _load_active(db, sources, customer_ids)

    # 2. en 3. Onderdrukken; een groep zonder overgebleven items geldt als afwezig.
    suppression = _load_suppression(db, sources, customer_ids, now)
    wanted: dict[GroupId, Group] = {}
    for group in groups:
        if group.source not in sources:
            continue
        if customer_ids is not None and group.customer_id not in customer_ids:
            continue
        kept = suppression.filter(group)
        if kept is not None:
            wanted[(group.customer_id, group.source, group.group_key)] = kept

    # 4. en 5. Bijwerken of aanmaken, in vaste volgorde.
    for group_id in sorted(wanted):
        group = wanted[group_id]
        fingerprint = fingerprint_of(group.items, group.severity)
        card = active.get(group_id)
        if card is None:
            card = _create_card(db, group, fingerprint, now)
            if card is None:
                continue
            active[group_id] = card
            result.created += 1
        elif card.fingerprint != fingerprint:
            _apply_group(card, group, fingerprint, now)
            result.updated += 1

    # 6. Open kaarten zonder groep: vanzelf klaar, bovenaan de Klaar-kolom.
    for group_id in sorted(active):
        if group_id in wanted:
            continue
        card = active[group_id]
        card.position = position_top(db, STATUS_DONE)
        mark_done(card, None, now, by_source=True)
        db.flush()
        result.resolved += 1

    return result
