"""Bron 'site_changes' van de werkvoorraad: AI-tekstvoorstellen uit Aanpassingen, één groep per
klant per pagina.

Open = voorstellen met status open of goedgekeurd (een goedgekeurde rij waarvan de bron weg is
telt mee); doorgevoerd en afgewezen tellen niet. Scan-actiepunten op dezelfde pagina staan op de
scankaart en tellen hier niet mee.

Afronden gebeurt in Aanpassingen: naar Klaar slepen wordt geweigerd zolang er op de pagina nog
iets open of goedgekeurd staat (anders gebeurt er niets; de sync rondt de kaart dan zelf af), en
terugzetten wordt altijd geweigerd. Verwijderen schrijft niets terug: de voorstellen blijven open
in Aanpassingen en de sync onderdrukt ze op sleutel.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import LaunchContentSuggestion, LaunchScan, SiteChange, WorkItem
from app.features.launch_checklist.services.scan_recovery import as_utc
from app.features.site_changes.services.changes import APPROVED, KIND_SUGGESTION, OPEN, Entry
from app.features.site_changes.services.sources import PageInfo, path_of, suggestion_entries
from app.features.work_queue.services.types import (
    KIND_CONTENT,
    SEVERITY_MEDIUM,
    SOURCE_SITE_CHANGES,
    Group,
    Item,
    WorkQueueConflict,
)

OPEN_STATUSES = frozenset({OPEN, APPROVED})
REOPEN_MESSAGE = "Heropenen gebeurt in Aanpassingen: heropen daar een voorstel, dan komt de kaart vanzelf terug."


def group_title(path: str) -> str:
    return f"Teksten aanpassen {path}"


def _is_open(entry: Entry) -> bool:
    return entry.kind == KIND_SUGGESTION and entry.status in OPEN_STATUSES


def candidate_customers(db: Session, customer_ids: set[str] | None) -> set[str]:
    """Klanten die open voorstellen kunnen hebben (drie lichte queries voor alle klanten).

    Ja als de laatste voltooide fase 3-scan een voorstel op een pagina met bronstatus 'open'
    heeft (ook een goedgekeurd voorstel staat in de bron op 'open'), of als er een goedgekeurde
    beslissing over een voorstel is.
    """
    scans = db.query(LaunchScan.id, LaunchScan.customer_website_id, LaunchScan.created_at).filter(
        LaunchScan.phase == 3, LaunchScan.status == "completed")
    approved = db.query(SiteChange.customer_website_id).filter(
        SiteChange.source_kind == KIND_SUGGESTION, SiteChange.status == APPROVED)
    if customer_ids is not None:
        scans = scans.filter(LaunchScan.customer_website_id.in_(sorted(customer_ids)))
        approved = approved.filter(SiteChange.customer_website_id.in_(sorted(customer_ids)))

    latest: dict[str, tuple] = {}
    for scan_id, customer_id, created_at in scans.all():
        order = (as_utc(created_at), scan_id)
        if customer_id not in latest or order > latest[customer_id]:
            latest[customer_id] = order
    found: set[str] = {row[0] for row in approved.distinct().all()}
    scan_owner = {order[1]: customer_id for customer_id, order in latest.items()}
    if scan_owner:
        found |= {
            scan_owner[row[0]]
            for row in db.query(LaunchContentSuggestion.scan_id)
            .filter(
                LaunchContentSuggestion.scan_id.in_(sorted(scan_owner)),
                LaunchContentSuggestion.content_page_id.isnot(None),
                LaunchContentSuggestion.status == "open",
            )
            .distinct()
            .all()
        }
    return found


def _groups_for(db: Session, customer_id: str) -> list[Group]:
    pages, entries = suggestion_entries(db, customer_id)
    by_page: dict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        if _is_open(entry):
            by_page[entry.url_key].append(entry)
    groups: list[Group] = []
    for ukey, members in sorted(by_page.items()):
        page = pages.get(ukey) or PageInfo(url=members[0].page_url, path=path_of(members[0].page_url))
        items = [
            Item(
                key=entry.key,
                title=entry.field("title") or entry.field("item_label") or "Voorstel",
                url=page.url,
                severity=None,
                ref={"page_url": page.url},
            )
            for entry in members
        ]
        items.sort(key=lambda item: (item.title, item.key))
        groups.append(Group(
            customer_id=customer_id,
            source=SOURCE_SITE_CHANGES,
            group_key=ukey,
            title=group_title(page.path or path_of(page.url)),
            kind=KIND_CONTENT,
            severity=SEVERITY_MEDIUM,
            items=items,
        ))
    return groups


class SiteChangesAdapter:
    """Koppeling tussen de tekstvoorstellen in Aanpassingen en de werkvoorraad."""

    source = SOURCE_SITE_CHANGES

    def collect(self, db: Session, customer_ids: set[str] | None = None) -> list[Group]:
        """Open groepen; na een bulkcontrole per klant met voorstellen een paar queries."""
        if customer_ids is not None and not customer_ids:
            return []
        groups: list[Group] = []
        for customer_id in sorted(candidate_customers(db, set(customer_ids) if customer_ids is not None else None)):
            groups.extend(_groups_for(db, customer_id))
        return groups

    def complete(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None:
        """Weigert zolang er op de pagina iets open of goedgekeurd staat; anders niets."""
        _pages, entries = suggestion_entries(db, card.customer_website_id)
        count = sum(1 for entry in entries if _is_open(entry) and entry.url_key == card.group_key)
        if count == 1:
            raise WorkQueueConflict(
                "Op deze pagina staat nog 1 voorstel open in Aanpassingen. Rond het daar af; "
                "de kaart gaat dan vanzelf naar Klaar."
            )
        if count:
            raise WorkQueueConflict(
                f"Op deze pagina staan nog {count} voorstellen open in Aanpassingen. Rond ze daar af; "
                "de kaart gaat dan vanzelf naar Klaar."
            )

    def reopen(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None:
        raise WorkQueueConflict(REOPEN_MESSAGE)

    def dismiss(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None:
        """Niets terugschrijven: de voorstellen blijven open in Aanpassingen; de sync onderdrukt
        de items van de verwijderde kaart op sleutel."""
        return None


site_changes_adapter = SiteChangesAdapter()
