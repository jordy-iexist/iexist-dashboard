"""Actiepunten en checklistpunten doorzetten naar Monday.

Per klant één bord in de Monday-map (settings.monday_folder_name), met een
groep per fase. Doorzetten is eenrichtingsverkeer en idempotent: een punt dat
al een Monday-item heeft wordt overgeslagen. Een fase-2 checklistpunt en het
bijbehorende `geo_<key>`-actiepunt delen één Monday-item.

Actiepunten per pagina (fase 1 en fase 3) worden op onderwerp gegroepeerd: per
issue_type één hoofditem (bijv. "Meta description ontbreekt"), met elk
actiepunt als subitem. Sitebrede punten en fase-2 punten blijven losse items.
Bij fase-3 actiepunten gaan de AI-voorstellen voor die pagina mee in de
toelichting.
"""
from __future__ import annotations

import html
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    CustomerWebsite,
    LaunchChecklistState,
    LaunchContentPage,
    LaunchContentSuggestion,
    LaunchMondayTopic,
    LaunchScan,
    LaunchScanIssue,
)
from app.features.launch_checklist.services.checklist_view import (
    latest_completed_geo,
    latest_content_scan,
    merged_checklist,
    merged_content_checklist,
)
from app.features.launch_checklist.services.geo_checklist import ITEMS
from app.features.launch_checklist.services.issues import ISSUE_TYPES
from app.services.monday import client as monday
from app.services.monday.client import MondayBoard, MondayServiceError

PROVIDER = "monday"
MAX_BATCH = 25
GROUP_TITLES = {
    1: "Fase 1 – Nulmeting",
    2: "Fase 2 – GEO/SEO-checklist",
    3: "Fase 3 – Content & onpage",
}
PHASES = tuple(sorted(GROUP_TITLES))
CHECKLIST_SOURCE = {
    2: "Livegang fase 2 – GEO/SEO-checklist",
    3: "Livegang fase 3 – Contentcreatie & onpage optimalisatie",
}
# Fases waarvan actiepunten per pagina onder een onderwerp (hoofditem) hangen.
GROUPED_PHASES = {1, 3}
MAX_SUGGESTIONS_IN_BODY = 10
GEO_ISSUE_PREFIX = "geo_"
MAX_ITEM_NAME = 250
MAX_EVIDENCE = 15
# Fouten waarbij doorgaan met de rest van de batch geen zin heeft.
_FATAL_CODES = {"not_configured", "unauthorized", "rate_limited", "timeout", "connection_error"}

PushStatus = Literal["pushed", "skipped", "failed"]


@dataclass
class PushOutcome:
    ref: str
    status: PushStatus
    message: str | None = None
    external_url: str | None = None


@dataclass
class PushResult:
    board_url: str | None
    outcomes: list[PushOutcome]

    def count(self, status: PushStatus) -> int:
        return sum(1 for o in self.outcomes if o.status == status)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def board_name_for(customer: CustomerWebsite) -> str:
    return f"Website checklist – {customer.name}"


# --- bord ------------------------------------------------------------------

def _folder():
    if settings.monday_folder_id.strip():
        return monday.get_folder(settings.monday_folder_id.strip())
    return monday.find_folder(settings.monday_folder_name)


def _ensure_groups(db: Session, customer: CustomerWebsite, board: MondayBoard) -> None:
    """Zorg dat alle fasegroepen bestaan en hun id's bij de klant staan."""
    by_id = {g.id: g for g in board.groups}
    by_title = {g.title.strip().casefold(): g for g in board.groups}
    # Laatste fase eerst: Monday zet een nieuwe groep bovenaan, zo komt fase 1 bovenaan.
    for phase in reversed(PHASES):
        title = GROUP_TITLES[phase]
        current = _group_id(customer, phase)
        if current and current in by_id:
            resolved = current
        elif title.casefold() in by_title:
            resolved = by_title[title.casefold()].id
        else:
            resolved = monday.create_group(board.id, title).id
        setattr(customer, _group_attr(phase), resolved)


def _group_attr(phase: int) -> str:
    return f"monday_group_fase{phase if phase in GROUP_TITLES else 1}_id"


def _group_id(customer: CustomerWebsite, phase: int) -> str | None:
    return getattr(customer, _group_attr(phase))


def _clear_groups(customer: CustomerWebsite) -> None:
    for phase in PHASES:
        setattr(customer, _group_attr(phase), None)


def _forget_topics(db: Session, customer: CustomerWebsite) -> None:
    """Hoofditems horen bij één bord; bij een ander bord beginnen we opnieuw."""
    db.query(LaunchMondayTopic).filter(
        LaunchMondayTopic.customer_website_id == customer.id
    ).delete(synchronize_session=False)


def link_board(db: Session, customer: CustomerWebsite, board: MondayBoard) -> None:
    if customer.monday_board_id != board.id:
        _forget_topics(db, customer)
    customer.monday_board_id = board.id
    customer.monday_board_url = board.url
    _clear_groups(customer)
    # Meteen vastleggen: zonder dit zou een fout bij de groepen een tweede bord opleveren.
    db.commit()
    _ensure_groups(db, customer, board)
    db.commit()


def unlink_board(db: Session, customer: CustomerWebsite) -> None:
    _forget_topics(db, customer)
    customer.monday_board_id = None
    customer.monday_board_url = None
    _clear_groups(customer)
    db.commit()


def ensure_customer_board(db: Session, customer: CustomerWebsite) -> MondayBoard:
    """Het Monday-bord van de klant; maakt het in de map aan als het er nog niet is.

    Een gekoppeld bord dat in Monday verdwenen is levert een fout op: er wordt
    niet stilzwijgend een nieuw bord gemaakt.
    """
    if customer.monday_board_id:
        try:
            board = monday.get_board(customer.monday_board_id)
        except MondayServiceError as exc:
            if exc.code == "board_not_found":
                raise MondayServiceError(
                    "Het gekoppelde Monday-bord bestaat niet meer of is niet toegankelijk. "
                    "Ontkoppel het bord bij deze klant en maak een nieuw bord aan.",
                    code="board_not_found",
                ) from exc
            raise
        _ensure_groups(db, customer, board)
        customer.monday_board_url = board.url or customer.monday_board_url
        db.commit()
        return board

    folder = _folder()
    board = monday.create_board(
        board_name_for(customer), folder_id=folder.id, workspace_id=folder.workspace_id
    )
    link_board(db, customer, board)
    return board


# --- inhoud ----------------------------------------------------------------

def _p(label: str, value: Any) -> str:
    return f"<p><b>{html.escape(label)}:</b> {html.escape(str(value))}</p>"


def _link(url: str) -> str:
    safe = html.escape(url, quote=True)
    return f'<a href="{safe}">{html.escape(url)}</a>'


def _evidence_html(evidence: list[Any]) -> str:
    if not evidence:
        return ""
    rows = "".join(f"<li>{html.escape(str(e))}</li>" for e in evidence[:MAX_EVIDENCE])
    more = len(evidence) - MAX_EVIDENCE
    if more > 0:
        rows += f"<li>… en nog {more}</li>"
    return f"<p><b>Bevindingen:</b></p><ul>{rows}</ul>"


def _dashboard_link(customer: CustomerWebsite) -> str:
    base = settings.dashboard_public_url.strip().rstrip("/")
    if not base:
        return ""
    return f"<p>{_link(f'{base}/dashboard/livegang/{customer.id}')}</p>"


def issue_item_name(issue: LaunchScanIssue) -> str:
    return (issue.title or issue.issue_type)[:MAX_ITEM_NAME]


def suggestions_html(db: Session, issue: LaunchScanIssue) -> str:
    """AI-voorstellen (fase 3) voor de pagina en het checklistpunt van dit actiepunt."""
    if not issue.url:
        return ""
    rows = (
        db.query(LaunchContentSuggestion)
        .join(LaunchContentPage, LaunchContentPage.id == LaunchContentSuggestion.content_page_id)
        .filter(
            LaunchContentSuggestion.scan_id == issue.scan_id,
            LaunchContentSuggestion.item_key == issue.issue_type,
            LaunchContentSuggestion.status != "afgewezen",
            LaunchContentPage.url == issue.url,
        )
        .order_by(LaunchContentSuggestion.created_at)
        .limit(MAX_SUGGESTIONS_IN_BODY)
        .all()
    )
    if not rows:
        return ""
    parts = ["<p><b>AI-voorstellen:</b></p>"]
    for row in rows:
        if row.title:
            parts.append(f"<p><u>{html.escape(row.title)}</u></p>")
        if row.current_value:
            parts.append(_p("Huidig", row.current_value))
        parts.append(_p("Voorstel", row.proposed_value))
        if row.rationale:
            parts.append(_p("Waarom", row.rationale))
    return "".join(parts)


def issue_body(
    issue: LaunchScanIssue, customer: CustomerWebsite, phase: int, *, extra_html: str = ""
) -> str:
    label = ISSUE_TYPES.get(issue.issue_type, {}).get("label", issue.issue_type)
    parts = [f"<p>{html.escape(issue.description or '')}</p>"]
    if issue.recommendation:
        parts.append(_p("Aanpak", issue.recommendation))
    if issue.url:
        parts.append(f"<p><b>Pagina:</b> {_link(issue.url)}</p>")
    parts.append(_p("Ernst", issue.severity))
    parts.append(_p("Categorie", issue.category))
    parts.append(_p("Type", label))
    details = issue.details if isinstance(issue.details, dict) else {}
    evidence = details.get("evidence")
    if isinstance(evidence, list):
        parts.append(_evidence_html(evidence))
    parts.append(extra_html)
    parts.append(_p("Bron", f"Livegang-scan fase {phase}"))
    parts.append(_dashboard_link(customer))
    return "".join(p for p in parts if p)


def is_grouped(issue: LaunchScanIssue, phase: int) -> bool:
    """Punten per pagina (fase 1 en 3) gaan als subitem onder een onderwerp."""
    return phase in GROUPED_PHASES and bool(issue.url)


def topic_name(issue_type: str) -> str:
    return ISSUE_TYPES.get(issue_type, {}).get("label", issue_type)[:MAX_ITEM_NAME]


def topic_body(issue: LaunchScanIssue, customer: CustomerWebsite, phase: int = 1) -> str:
    """Toelichting bij het hoofditem: wat er per pagina moet gebeuren."""
    parts = ["<p>De pagina's waar dit speelt staan als subitems onder dit item.</p>"]
    if issue.recommendation:
        parts.append(_p("Aanpak", issue.recommendation))
    parts.append(_p("Categorie", issue.category))
    parts.append(_p("Bron", f"Livegang-scan fase {phase}"))
    parts.append(_dashboard_link(customer))
    return "".join(p for p in parts if p)


def checklist_item_name(item: dict[str, Any]) -> str:
    return str(item["label"])[:MAX_ITEM_NAME]


def checklist_body(
    item: dict[str, Any], section_label: str, customer: CustomerWebsite, phase: int = 2
) -> str:
    parts: list[str] = []
    if item.get("description"):
        parts.append(f"<p>{html.escape(item['description'])}</p>")
    auto = item.get("auto") if isinstance(item.get("auto"), dict) else {}
    if auto.get("message"):
        parts.append(_p("Scanresultaat", auto["message"]))
    if isinstance(auto.get("evidence"), list):
        parts.append(_evidence_html(auto["evidence"]))
    if item.get("note"):
        parts.append(_p("Notitie", item["note"]))
    parts.append(_p("Prioriteit", item.get("priority") or "normaal"))
    parts.append(_p("Sectie", section_label))
    parts.append(_p("Bron", CHECKLIST_SOURCE.get(phase, f"Livegang fase {phase}")))
    parts.append(_dashboard_link(customer))
    return "".join(p for p in parts if p)


def _create(board: MondayBoard, group_id: str | None, name: str, body: str) -> tuple[Any, str | None]:
    """Maak item + toelichting. Geeft (item, waarschuwing) terug."""
    item = monday.create_item(board.id, name, group_id=group_id)
    try:
        monday.create_update(item.id, body)
    except MondayServiceError as exc:
        # Het item bestaat al; alleen de toelichting ontbreekt. Wel koppelen,
        # anders levert opnieuw doorzetten een dubbel item op.
        return item, f"Item aangemaakt, maar de toelichting is niet geplaatst: {exc}"
    return item, None


def _topic(db: Session, customer_id: str, issue_type: str) -> LaunchMondayTopic | None:
    return (
        db.query(LaunchMondayTopic)
        .filter(
            LaunchMondayTopic.customer_website_id == customer_id,
            LaunchMondayTopic.issue_type == issue_type,
        )
        .first()
    )


def _create_topic(
    db: Session, board: MondayBoard, customer: CustomerWebsite, issue: LaunchScanIssue,
    existing: LaunchMondayTopic | None, phase: int = 1,
) -> LaunchMondayTopic:
    parent = monday.create_item(
        board.id, topic_name(issue.issue_type), group_id=_group_id(customer, phase)
    )
    topic = existing or LaunchMondayTopic(
        id=str(uuid.uuid4()), customer_website_id=customer.id, issue_type=issue.issue_type
    )
    topic.item_id = parent.id
    topic.item_url = parent.url
    if existing is None:
        db.add(topic)
    # Meteen vastleggen: anders krijgt het volgende punt een tweede hoofditem.
    db.commit()
    try:
        monday.create_update(parent.id, topic_body(issue, customer, phase))
    except MondayServiceError:
        pass  # hoofditem bestaat; de toelichting is niet essentieel
    return topic


def _create_grouped(
    db: Session, board: MondayBoard, customer: CustomerWebsite, issue: LaunchScanIssue,
    fresh_topics: set[str], phase: int = 1,
) -> tuple[Any, str | None]:
    """Maak het actiepunt als subitem onder het hoofditem van zijn onderwerp."""
    topic = _topic(db, customer.id, issue.issue_type)
    if topic is None:
        topic = _create_topic(db, board, customer, issue, None, phase)
        fresh_topics.add(issue.issue_type)
    name = issue_item_name(issue)
    try:
        sub = monday.create_subitem(topic.item_id, name)
    except MondayServiceError as exc:
        if exc.code != "monday_error" or issue.issue_type in fresh_topics:
            raise
        # Een eerder hoofditem kan in Monday verwijderd zijn: één keer opnieuw aanmaken.
        topic = _create_topic(db, board, customer, issue, topic, phase)
        fresh_topics.add(issue.issue_type)
        sub = monday.create_subitem(topic.item_id, name)
    if sub.url is None:
        sub = monday.MondayItem(id=sub.id, url=topic.item_url)
    try:
        extra = suggestions_html(db, issue) if phase == 3 else ""
        monday.create_update(sub.id, issue_body(issue, customer, phase, extra_html=extra))
    except MondayServiceError as exc:
        return sub, f"Subitem aangemaakt, maar de toelichting is niet geplaatst: {exc}"
    return sub, None


# --- koppeling vastleggen --------------------------------------------------

def _state_for(db: Session, customer_id: str, key: str) -> LaunchChecklistState | None:
    return (
        db.query(LaunchChecklistState)
        .filter(
            LaunchChecklistState.customer_website_id == customer_id,
            LaunchChecklistState.item_key == key,
        )
        .first()
    )


def _link_state(
    db: Session, customer_id: str, key: str, *, item_id: str, url: str | None,
    pushed_at: datetime, user_id: str | None,
) -> None:
    state = _state_for(db, customer_id, key)
    if state is None:
        state = LaunchChecklistState(
            id=str(uuid.uuid4()), customer_website_id=customer_id, item_key=key,
            updated_by=user_id, updated_at=pushed_at,
        )
        db.add(state)
    state.external_provider = PROVIDER
    state.external_item_id = item_id
    state.external_url = url
    state.pushed_at = pushed_at


def _link_issue(issue: LaunchScanIssue, *, item_id: str, url: str | None, pushed_at: datetime) -> None:
    issue.external_provider = PROVIDER
    issue.external_item_id = item_id
    issue.external_url = url
    issue.pushed_at = pushed_at
    if issue.status == "open":
        issue.status = "doorgezet"
    issue.updated_at = _now()


def _geo_issue(db: Session, scan: LaunchScan | None, key: str) -> LaunchScanIssue | None:
    if scan is None:
        return None
    return (
        db.query(LaunchScanIssue)
        .filter(
            LaunchScanIssue.scan_id == scan.id,
            LaunchScanIssue.issue_type == f"{GEO_ISSUE_PREFIX}{key}",
        )
        .first()
    )


def _fail_rest(outcomes: list[PushOutcome], refs: list[str], message: str) -> None:
    done = {o.ref for o in outcomes}
    outcomes.extend(PushOutcome(ref, "failed", message) for ref in refs if ref not in done)


# --- koppelingen controleren -----------------------------------------------

def sync_links(db: Session, customer: CustomerWebsite) -> int:
    """Ruim koppelingen op naar Monday-items die daar verwijderd zijn.

    Zonder dit blijft een in Monday verwijderd punt in het dashboard 'doorgezet'
    en kan het niet opnieuw worden doorgezet. Geeft het aantal opgeruimde
    koppelingen terug.
    """
    scan_ids = [
        row.id
        for row in db.query(LaunchScan.id).filter(LaunchScan.customer_website_id == customer.id)
    ]
    issues = (
        db.query(LaunchScanIssue)
        .filter(
            LaunchScanIssue.scan_id.in_(scan_ids),
            LaunchScanIssue.external_provider == PROVIDER,
            LaunchScanIssue.external_item_id.isnot(None),
        )
        .all()
        if scan_ids else []
    )
    states = (
        db.query(LaunchChecklistState)
        .filter(
            LaunchChecklistState.customer_website_id == customer.id,
            LaunchChecklistState.external_item_id.isnot(None),
        )
        .all()
    )
    topics = (
        db.query(LaunchMondayTopic)
        .filter(LaunchMondayTopic.customer_website_id == customer.id)
        .all()
    )
    ids = (
        [i.external_item_id for i in issues]
        + [s.external_item_id for s in states]
        + [t.item_id for t in topics]
    )
    if not ids:
        return 0
    missing = monday.missing_item_ids(ids)
    if not missing:
        return 0

    cleared = 0
    now = _now()
    for issue in issues:
        if issue.external_item_id in missing:
            issue.external_provider = None
            issue.external_item_id = None
            issue.external_url = None
            issue.pushed_at = None
            if issue.status == "doorgezet":
                issue.status = "open"
            issue.updated_at = now
            cleared += 1
    for state in states:
        if state.external_item_id in missing:
            state.external_provider = None
            state.external_item_id = None
            state.external_url = None
            state.pushed_at = None
            cleared += 1
    for topic in topics:
        if topic.item_id in missing:
            db.delete(topic)
    db.commit()
    return cleared


# --- doorzetten ------------------------------------------------------------

def push_issues(db: Session, issue_ids: list[str], user_id: str | None) -> PushResult:
    """Zet actiepunten (fase 1, 2 en 3) door. Alle punten moeten van één klant zijn."""
    ids = list(dict.fromkeys(issue_ids))
    issues = {i.id: i for i in db.query(LaunchScanIssue).filter(LaunchScanIssue.id.in_(ids)).all()}
    scans = {
        s.id: s
        for s in db.query(LaunchScan)
        .filter(LaunchScan.id.in_({i.scan_id for i in issues.values()}))
        .all()
    }
    customer_ids = {s.customer_website_id for s in scans.values()}
    if not issues:
        raise ValueError("Geen actiepunten gevonden.")
    if len(customer_ids) != 1:
        raise ValueError("Zet actiepunten van één klant tegelijk door.")
    customer = db.get(CustomerWebsite, customer_ids.pop())
    if customer is None:
        raise ValueError("Klant niet gevonden.")

    board = ensure_customer_board(db, customer)
    # Eerst opruimen wat in Monday verwijderd is, zodat dat opnieuw kan.
    sync_links(db, customer)
    outcomes: list[PushOutcome] = []
    fresh_topics: set[str] = set()
    for issue_id in ids:
        issue = issues.get(issue_id)
        if issue is None:
            outcomes.append(PushOutcome(issue_id, "failed", "Actiepunt niet gevonden."))
            continue
        if issue.external_item_id:
            outcomes.append(PushOutcome(issue_id, "skipped", "Al doorgezet.", issue.external_url))
            continue
        phase = scans[issue.scan_id].phase or 1
        geo_key = (
            issue.issue_type[len(GEO_ISSUE_PREFIX):]
            if issue.issue_type.startswith(GEO_ISSUE_PREFIX) else None
        )
        # Het checklistpunt van dit actiepunt staat mogelijk al in Monday.
        state = _state_for(db, customer.id, geo_key) if geo_key else None
        if state is not None and state.external_item_id:
            _link_issue(issue, item_id=state.external_item_id, url=state.external_url,
                        pushed_at=state.pushed_at or _now())
            db.commit()
            outcomes.append(PushOutcome(
                issue_id, "skipped", "Al doorgezet via de checklist.", state.external_url))
            continue
        try:
            if is_grouped(issue, phase):
                item, warning = _create_grouped(db, board, customer, issue, fresh_topics, phase)
            else:
                item, warning = _create(
                    board, _group_id(customer, phase), issue_item_name(issue),
                    issue_body(issue, customer, phase),
                )
        except MondayServiceError as exc:
            db.rollback()
            outcomes.append(PushOutcome(issue_id, "failed", str(exc)))
            if exc.code in _FATAL_CODES:
                _fail_rest(outcomes, ids, str(exc))
                break
            continue
        pushed_at = _now()
        _link_issue(issue, item_id=item.id, url=item.url, pushed_at=pushed_at)
        if geo_key and geo_key in ITEMS:
            _link_state(db, customer.id, geo_key, item_id=item.id, url=item.url,
                        pushed_at=pushed_at, user_id=user_id)
        db.commit()
        outcomes.append(PushOutcome(issue_id, "pushed", warning, item.url))
    return PushResult(board_url=customer.monday_board_url, outcomes=outcomes)


def push_checklist_items(
    db: Session, customer: CustomerWebsite, item_keys: list[str], user_id: str | None,
    phase: int = 2,
) -> PushResult:
    """Zet checklistpunten (fase 2 of 3) door naar de fasegroep van het klantbord."""
    keys = list(dict.fromkeys(item_keys))
    if phase == 3:
        # Fase-3 actiepunten zijn per pagina; die delen geen item met het checklistpunt.
        geo = None
        merged = merged_content_checklist(db, customer.id, latest_content_scan(db, customer.id))
    else:
        geo = latest_completed_geo(db, customer.id)
        merged = merged_checklist(db, customer, geo)
    items: dict[str, tuple[dict[str, Any], str]] = {
        item["key"]: (item, section["label"])
        for section in merged["sections"]
        for item in section["items"]
    }

    board = ensure_customer_board(db, customer)
    sync_links(db, customer)
    outcomes: list[PushOutcome] = []
    for key in keys:
        entry = items.get(key)
        if entry is None:
            outcomes.append(PushOutcome(key, "failed", "Onbekend checklistpunt."))
            continue
        item, section_label = entry
        state = _state_for(db, customer.id, key)
        if state is not None and state.external_item_id:
            outcomes.append(PushOutcome(key, "skipped", "Al doorgezet.", state.external_url))
            continue
        issue = _geo_issue(db, geo, key)
        # Het actiepunt van dit checklistpunt staat mogelijk al in Monday.
        if issue is not None and issue.external_item_id:
            _link_state(db, customer.id, key, item_id=issue.external_item_id,
                        url=issue.external_url, pushed_at=issue.pushed_at or _now(),
                        user_id=user_id)
            db.commit()
            outcomes.append(PushOutcome(
                key, "skipped", "Al doorgezet via de actiepunten.", issue.external_url))
            continue
        try:
            created, warning = _create(
                board, _group_id(customer, phase), checklist_item_name(item),
                checklist_body(item, section_label, customer, phase),
            )
        except MondayServiceError as exc:
            db.rollback()
            outcomes.append(PushOutcome(key, "failed", str(exc)))
            if exc.code in _FATAL_CODES:
                _fail_rest(outcomes, keys, str(exc))
                break
            continue
        pushed_at = _now()
        _link_state(db, customer.id, key, item_id=created.id, url=created.url,
                    pushed_at=pushed_at, user_id=user_id)
        if issue is not None:
            _link_issue(issue, item_id=created.id, url=created.url, pushed_at=pushed_at)
        db.commit()
        outcomes.append(PushOutcome(key, "pushed", warning, created.url))
    return PushResult(board_url=customer.monday_board_url, outcomes=outcomes)
