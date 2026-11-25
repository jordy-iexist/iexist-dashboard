"""Bron 'scan' van de werkvoorraad: actiepunten uit de SEO/GEO-scan, één groep per klant per
`issue_type`.

Bronscans per klant: de laatste voltooide scan van fase 1, 2, 3 en 4 plus de monitor-scan. De
monitor-scan is één doorlopende rij die bij elke run even op 'inventory' en daarna weer op
'completed' gaat, terwijl zijn actiepunten blijven staan; hij telt mee zodra hij één keer voltooid
is (`completed_at` gevuld). Anders zouden de kaarten van de monitor bij elke dagelijkse run even
naar Klaar gaan en daarna als nieuwe kaart terugkomen.

Een bevinding is (`issue_type`, `url_key` van de absolute URL); een bevinding zonder URL is
sitebreed en heeft itemsleutel `SITE_KEY`. Ze is open als de nieuwste rij (op `created_at`)
'open' is en geen enkele rij in de bronscans 'doorgezet' is of een Monday-koppeling heeft. Niet
mee tellen:
- rijen met `details.source == "ai"`: spiegels van AI-voorstellen (`content_rebuild.
  sync_suggestion_issues`), die al op de Aanpassingen-kaart staan;
- een sitebrede bevinding uit een checklistpunt (geo_*, c3_*, c4_*) als het checklistpunt van
  die klant (fase 4: van die ronde) in Monday staat (`LaunchChecklistState.external_item_id`):
  een checklist-push in fase 3 en 4 koppelt het actiepunt zelf niet.

Naar Klaar zet de open rijen op 'opgelost'; een volgende scan die het probleem opnieuw vindt
maakt nieuwe open rijen (zie `issue_state.py`). Verwijderen zet ze op 'genegeerd'; dat wordt
over scans heen meegenomen.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.db.models import LaunchChecklistState, LaunchScan, LaunchScanIssue, WorkItem
from app.features.launch_checklist.services.discovery import url_key
from app.features.launch_checklist.services.golive_checklist import MONITOR_PHASE
from app.features.launch_checklist.services.issues import ISSUE_TYPES
from app.features.launch_checklist.services.scan_recovery import as_utc
from app.features.site_changes.services.sources import absolute_url, path_of
from app.features.work_queue.services.cards import fingerprint_of
from app.features.work_queue.services.types import (
    KIND_CONTENT,
    KIND_TECHNIEK,
    SEVERITIES,
    SEVERITY_MEDIUM,
    SOURCE_SCAN,
    Group,
    Item,
    severity_rank,
)

# Fases waarvan de laatste voltooide scan meetelt (plus de monitor).
SOURCE_PHASES: tuple[int, ...] = (1, 2, 3, 4)
# Itemsleutel van een sitebrede bevinding. Niet leeg: een lege sleutel telt in `sync.py` niet
# mee bij het onderdrukken van een verwijderde kaart.
SITE_KEY = "*"
SITE_TITLE = "Hele site"
# Categorie van het actiepunt → soort op het bord; onbekend = techniek.
CONTENT_CATEGORIES = frozenset({"on-page", "content"})

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)

STATUS_OPEN = "open"
STATUS_FORWARDED = "doorgezet"
STATUS_RESOLVED = "opgelost"
STATUS_IGNORED = "genegeerd"


@dataclass
class _Scan:
    id: str
    customer_id: str
    phase: int
    base_url: str
    period: str
    created_at: datetime


@dataclass
class _Finding:
    """Eén bevinding (klant, issue_type, sleutel) met al zijn rijen in de bronscans."""

    customer_id: str
    issue_type: str
    key: str
    # (rij, scan), nieuwste eerst na `_sort`.
    rows: list[tuple[Any, _Scan]] = field(default_factory=list)

    def sort(self) -> None:
        self.rows.sort(key=lambda pair: (_ts(pair[0].created_at), _ts(pair[1].created_at), pair[0].id), reverse=True)

    @property
    def newest(self) -> tuple[Any, _Scan]:
        return self.rows[0]


def _ts(value: datetime | None) -> datetime:
    return as_utc(value) if value is not None else _EPOCH


def _severity(value: str | None) -> str | None:
    return value if value in SEVERITIES else None


def kind_for(category: str | None) -> str:
    """Soort op het bord voor een categorie van een actiepunt."""
    return KIND_CONTENT if (category or "") in CONTENT_CATEGORIES else KIND_TECHNIEK


def checklist_state_key(issue_type: str, phase: int, period: str) -> tuple[str, str] | None:
    """(item_key, period) van het checklistpunt waar een sitebreed actiepunt uit voortkomt.

    Fase 2 maakt `geo_<punt>`, fase 3 `c3_*` en fase 4 `c4_*` (status per ronde); de
    checklist-push in `monday_push.push_checklist_items` gebruikt dezelfde sleutels.
    """
    if phase == 2 and issue_type.startswith("geo_"):
        return issue_type[len("geo_"):], ""
    if phase == 3 and issue_type.startswith("c3_"):
        return issue_type, ""
    if phase == 4 and issue_type.startswith("c4_"):
        return issue_type, period or ""
    return None


# --- lezen ---------------------------------------------------------------------------


def _source_scans(db: Session, customer_ids: set[str] | None) -> dict[str, _Scan]:
    """Bronscans van de klanten (één query op lichte kolommen), op id."""
    query = db.query(
        LaunchScan.id, LaunchScan.customer_website_id, LaunchScan.phase, LaunchScan.status,
        LaunchScan.base_url, LaunchScan.period, LaunchScan.created_at, LaunchScan.completed_at,
    ).filter(
        or_(
            and_(LaunchScan.phase.in_(SOURCE_PHASES), LaunchScan.status == "completed"),
            LaunchScan.phase == MONITOR_PHASE,
        )
    )
    if customer_ids is not None:
        query = query.filter(LaunchScan.customer_website_id.in_(sorted(customer_ids)))
    latest: dict[tuple[str, int], Any] = {}
    for row in query.all():
        slot = (row.customer_website_id, row.phase)
        current = latest.get(slot)
        if current is None or (_ts(row.created_at), row.id) > (_ts(current.created_at), current.id):
            latest[slot] = row
    scans: dict[str, _Scan] = {}
    for (customer_id, phase), row in latest.items():
        # De monitor telt mee zodra hij één keer voltooid is (zie de moduledocstring).
        if phase == MONITOR_PHASE and row.status != "completed" and row.completed_at is None:
            continue
        scans[row.id] = _Scan(id=row.id, customer_id=customer_id, phase=phase, base_url=row.base_url or "",
                              period=row.period or "", created_at=row.created_at)
    return scans


def _findings(
    db: Session, customer_ids: set[str] | None, issue_type: str | None = None,
) -> dict[tuple[str, str, str], _Finding]:
    """Alle bevindingen in de bronscans (zonder AI-spiegels), op (klant, issue_type, sleutel)."""
    scans = _source_scans(db, customer_ids)
    if not scans:
        return {}
    query = db.query(
        LaunchScanIssue.id, LaunchScanIssue.scan_id, LaunchScanIssue.issue_type, LaunchScanIssue.category,
        LaunchScanIssue.severity, LaunchScanIssue.title, LaunchScanIssue.url, LaunchScanIssue.status,
        LaunchScanIssue.external_item_id, LaunchScanIssue.created_at,
        LaunchScanIssue.details["source"].as_string().label("detail_source"),
    ).filter(LaunchScanIssue.scan_id.in_(sorted(scans)))
    if issue_type is not None:
        query = query.filter(LaunchScanIssue.issue_type == issue_type)

    findings: dict[tuple[str, str, str], _Finding] = {}
    for row in query.all():
        if row.detail_source == "ai":
            continue
        scan = scans[row.scan_id]
        key = url_key(absolute_url(row.url, scan.base_url)) if row.url else SITE_KEY
        finding_id = (scan.customer_id, row.issue_type, key)
        finding = findings.get(finding_id)
        if finding is None:
            finding = findings[finding_id] = _Finding(customer_id=scan.customer_id, issue_type=row.issue_type, key=key)
        finding.rows.append((row, scan))
    for finding in findings.values():
        finding.sort()
    return findings


def _linked_checklist_states(db: Session, customer_ids: set[str]) -> set[tuple[str, str, str]]:
    """(klant, item_key, period) van checklistpunten met een Monday-koppeling."""
    if not customer_ids:
        return set()
    rows = (
        db.query(LaunchChecklistState.customer_website_id, LaunchChecklistState.item_key, LaunchChecklistState.period)
        .filter(
            LaunchChecklistState.customer_website_id.in_(sorted(customer_ids)),
            LaunchChecklistState.external_item_id.isnot(None),
            LaunchChecklistState.external_item_id != "",
        )
        .all()
    )
    return {(row[0], row[1], row[2] or "") for row in rows}


def _is_open(finding: _Finding, linked: set[tuple[str, str, str]]) -> bool:
    newest, _scan = finding.newest
    if newest.status != STATUS_OPEN:
        return False
    if any(row.status == STATUS_FORWARDED or row.external_item_id for row, _s in finding.rows):
        return False
    if finding.key == SITE_KEY:
        for row, scan in finding.rows:
            state_key = checklist_state_key(row.issue_type, scan.phase, scan.period)
            if state_key is not None and (finding.customer_id, *state_key) in linked:
                return False
    return True


def _item(finding: _Finding) -> Item:
    newest, scan = finding.newest
    url = absolute_url(newest.url, scan.base_url) if finding.key != SITE_KEY else None
    return Item(
        key=finding.key,
        title=path_of(url) if url else SITE_TITLE,
        url=url,
        severity=_severity(newest.severity),
        ref={
            "issue_ids": [row.id for row, _s in finding.rows],
            "phase": scan.phase,
            "scan_id": scan.id,
        },
    )


def _highest(severities: list[str | None]) -> str:
    known = [value for value in severities if value]
    return max(known, key=severity_rank) if known else SEVERITY_MEDIUM


def _open_groups(
    db: Session, customer_ids: set[str] | None, issue_type: str | None = None,
) -> tuple[list[Group], dict[tuple[str, str, str], _Finding]]:
    findings = _findings(db, customer_ids, issue_type)
    linked = _linked_checklist_states(db, {finding.customer_id for finding in findings.values()
                                           if finding.key == SITE_KEY})
    by_group: dict[tuple[str, str], list[_Finding]] = defaultdict(list)
    for finding in findings.values():
        if _is_open(finding, linked):
            by_group[(finding.customer_id, finding.issue_type)].append(finding)

    groups: list[Group] = []
    for (customer_id, type_key), members in sorted(by_group.items()):
        items = sorted((_item(finding) for finding in members), key=lambda item: (item.key != SITE_KEY, item.title))
        newest_row = max((finding.newest for finding in members),
                         key=lambda pair: (_ts(pair[0].created_at), _ts(pair[1].created_at)))[0]
        info = ISSUE_TYPES.get(type_key, {})
        groups.append(Group(
            customer_id=customer_id,
            source=SOURCE_SCAN,
            group_key=type_key,
            title=info.get("label") or newest_row.title or type_key,
            kind=kind_for(info.get("category") or newest_row.category),
            severity=_highest([item.severity for item in items]),
            items=items,
        ))
    return groups, findings


# --- schrijven -----------------------------------------------------------------------


def _issues_by_id(db: Session, ids: list[str]) -> list[LaunchScanIssue]:
    if not ids:
        return []
    return db.query(LaunchScanIssue).filter(LaunchScanIssue.id.in_(sorted(set(ids)))).all()


def _card_items(card: WorkItem) -> list[dict[str, Any]]:
    return [item for item in (card.items or []) if isinstance(item, dict)]


class ScanAdapter:
    """Koppeling tussen de scan-actiepunten en de werkvoorraad (zie de moduledocstring)."""

    source = SOURCE_SCAN

    def collect(self, db: Session, customer_ids: set[str] | None = None) -> list[Group]:
        """Open groepen; voor alle klanten in drie queries (scans, actiepunten, checklist)."""
        if customer_ids is not None and not customer_ids:
            return []
        groups, _findings_by_id = _open_groups(db, set(customer_ids) if customer_ids is not None else None)
        return groups

    def complete(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None:
        """Open rijen van de groep (zoals de bron hem nu ziet) op 'opgelost'.

        De momentopname op de kaart wordt de verse groep; per item staat in `ref.completed_ids`
        welke rijen hier zijn afgerond, zodat terugzetten alleen die rijen heropent.
        """
        groups, findings = _open_groups(db, {card.customer_website_id}, card.group_key)
        group = next((g for g in groups if g.group_key == card.group_key), None)
        if group is None:
            # Niets meer open in de bron: niets afronden, en bij terugzetten ook niets heropenen.
            card.items = [{**item, "ref": {**(item.get("ref") or {}), "completed_ids": []}}
                          for item in _card_items(card)]
            return

        wanted: dict[str, str] = {}  # rij-id → itemsleutel
        for item in group.items:
            finding = findings[(card.customer_website_id, card.group_key, item.key)]
            for row, _scan in finding.rows:
                if row.status == STATUS_OPEN:
                    wanted[row.id] = item.key
        completed: dict[str, list[str]] = defaultdict(list)
        for issue in _issues_by_id(db, list(wanted)):
            if issue.status == STATUS_OPEN:
                issue.status = STATUS_RESOLVED
                issue.updated_at = now
                completed[wanted[issue.id]].append(issue.id)

        for item in group.items:
            item.ref = {**item.ref, "completed_ids": sorted(completed.get(item.key, []))}
        card.items = [item.as_dict() for item in group.items]
        card.item_count = len(group.items)
        card.severity = group.severity
        card.fingerprint = fingerprint_of(group.items, group.severity)
        db.flush()

    def reopen(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None:
        """Rijen uit de momentopname die 'opgelost' zijn terug op 'open' (met Monday-koppeling:
        'doorgezet', zoals `site_changes.write_source_status`)."""
        ids: list[str] = []
        for item in _card_items(card):
            ref = item.get("ref") or {}
            ids.extend(ref["completed_ids"] if "completed_ids" in ref else ref.get("issue_ids") or [])
        for issue in _issues_by_id(db, ids):
            if issue.status == STATUS_RESOLVED:
                issue.status = STATUS_FORWARDED if issue.external_item_id else STATUS_OPEN
                issue.updated_at = now
        db.flush()

    def dismiss(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None:
        """Open rijen van de items op de kaart op 'genegeerd' (gaat mee naar volgende scans)."""
        keys = {str(item.get("key")) for item in _card_items(card) if item.get("key") is not None}
        if not keys or not card.group_key:
            return
        findings = _findings(db, {card.customer_website_id}, card.group_key)
        ids = [
            row.id
            for (_customer, _type, key), finding in findings.items()
            if key in keys
            for row, _scan in finding.rows
            if row.status == STATUS_OPEN
        ]
        for issue in _issues_by_id(db, ids):
            if issue.status == STATUS_OPEN:
                issue.status = STATUS_IGNORED
                issue.updated_at = now
        db.flush()


scan_adapter = ScanAdapter()
