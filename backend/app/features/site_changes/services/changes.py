"""Aanpassingen per pagina: onderwerpen, stabiele sleutels, beslissingen en doorschrijven.

Een `SiteChange`-rij legt een beslissing van een medewerker vast (goedgekeurd, afgewezen of
doorgevoerd). Open punten zonder beslissing hebben geen rij en komen rechtstreeks uit de bron
(zie `sources.py`). Elke beslissing wordt ook doorgeschreven naar de bestaande status van het
voorstel of actiepunt, zodat fase 3, de checklist en de Actiepunten-tab blijven kloppen.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import LaunchScan, SiteChange
from app.features.launch_checklist.services.content_rebuild import rebuild_content_checklist

if TYPE_CHECKING:
    from app.features.site_changes.services.sources import SourceItem

# --- onderwerpen ------------------------------------------------------------------

# Vaste volgorde in de weergave.
TOPICS: list[tuple[str, str]] = [
    ("meta_title", "Meta title"),
    ("meta_description", "Meta description"),
    ("headings", "Koppen"),
    ("text", "Tekst"),
    ("faq", "FAQ"),
    ("image_alt", "Alt-teksten"),
    ("internal_links", "Interne links"),
    ("technical", "Techniek"),
    ("performance", "Performance"),
    ("other", "Overig"),
]
TOPIC_LABELS = dict(TOPICS)
TOPIC_ORDER = {topic: index for index, (topic, _) in enumerate(TOPICS)}

# Fase-3 checklistpunten (voorstellen én de gelijknamige actiepunten).
ITEM_TOPICS: dict[str, str] = {
    "c3_meta_title": "meta_title",
    "c3_meta_description": "meta_description",
    "c3_headings": "headings",
    "c3_keywords": "text",
    "c3_scannable": "text",
    "c3_answer_first": "text",
    "c3_eeat": "text",
    "c3_conversion": "text",
    "c3_local": "text",
    "c3_faq": "faq",
    "c3_images": "image_alt",
    "c3_internal_links": "internal_links",
    "c3_redirects_404": "technical",
    "c3_meta_fixed": "technical",
}
# Actiepunten uit de paginaregels (services/issues.py, ISSUE_TYPES).
ISSUE_TOPICS: dict[str, str] = {
    "title_missing": "meta_title",
    "title_too_long": "meta_title",
    "title_too_short": "meta_title",
    "title_duplicate": "meta_title",
    "meta_missing": "meta_description",
    "meta_too_long": "meta_description",
    "meta_too_short": "meta_description",
    "meta_duplicate": "meta_description",
    "h1_missing": "headings",
    "h1_multiple": "headings",
    "h1_duplicate": "headings",
    "thin_content": "text",
    "images_missing_alt": "image_alt",
    "broken_links": "internal_links",
    "fetch_error": "technical",
    "status_4xx": "technical",
    "status_5xx": "technical",
    "redirect_in_sitemap": "technical",
    "redirect_chain": "technical",
    "noindex_in_sitemap": "technical",
    "canonical_mismatch": "technical",
    "broken_backlinks": "technical",
    "lang_missing": "technical",
    "og_incomplete": "technical",
    "robots_blocked_in_sitemap": "technical",
    "slow_response": "performance",
    **ITEM_TOPICS,
}
# Families met een vast voorvoegsel (hreflang_*, cwv_*, c4_* per URL, ...).
_PREFIX_TOPICS: tuple[tuple[str, str], ...] = (
    ("hreflang_", "technical"),
    ("status_", "technical"),
    ("redirect_", "technical"),
    ("c4_", "technical"),
    ("cwv_", "performance"),
)


def topic_for(type_key: str) -> str:
    """Onderwerp voor een item_key (voorstel) of issue_type (actiepunt); onbekend = 'other'."""
    if type_key in ISSUE_TOPICS:
        return ISSUE_TOPICS[type_key]
    for prefix, topic in _PREFIX_TOPICS:
        if type_key.startswith(prefix):
            return topic
    return "other"


# --- sleutels ---------------------------------------------------------------------

KIND_SUGGESTION = "content_suggestion"
KIND_ISSUE = "scan_issue"

_WS = re.compile(r"\s+")


def normalize_key_text(value: str | None) -> str:
    """Kleine letters en samengevoegde witruimte (voor sleutels en 'bewerkt?')."""
    return _WS.sub(" ", str(value or "")).strip().lower()


def _sha(material: str) -> str:
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def suggestion_key(
    topic: str, ukey: str, item_key: str, current_value: str | None, ref: str | None,
    proposed_value: str | None = None,
) -> str:
    """Sleutel van een AI-voorstel, stabiel over heranalyses.

    Basis: huidige waarde en ref (genormaliseerd). Zijn die allebei leeg, of hebben meer voorstellen
    op dezelfde pagina en hetzelfde punt dezelfde basis, dan telt ook het voorstel zelf mee
    (`proposed_value` meegeven).
    """
    basis = f"{normalize_key_text(current_value)}|{normalize_key_text(ref)}"
    if proposed_value is not None:
        basis = f"{basis}|{normalize_key_text(proposed_value)}"
    return _sha(f"{KIND_SUGGESTION}|{topic}|{ukey}|{item_key}|{basis}")


def suggestion_needs_proposal(current_value: str | None, ref: str | None) -> bool:
    return not normalize_key_text(current_value) and not normalize_key_text(ref)


def issue_source_key(issue_type: str, ukey: str) -> str:
    """Sleutel van een actiepunt: (issue_type, url_key), zoals `issue_key` in issue_state.py."""
    return _sha(f"{KIND_ISSUE}|{issue_type}|{ukey}")


# --- statussen --------------------------------------------------------------------

OPEN = "open"
APPROVED = "goedgekeurd"
REJECTED = "afgewezen"
DONE = "doorgevoerd"

# Bronstatus zonder rij -> status in de weergave (None = niet tonen).
_SUGGESTION_STATUS = {"open": OPEN, "afgewezen": REJECTED, "overgenomen": DONE}
_ISSUE_STATUS = {"open": OPEN, "doorgezet": OPEN, "genegeerd": REJECTED, "opgelost": None}


def status_from_source(kind: str, source_status: str) -> str | None:
    table = _SUGGESTION_STATUS if kind == KIND_SUGGESTION else _ISSUE_STATUS
    return table.get(source_status, OPEN)


@dataclass
class Entry:
    """Eén punt op een pagina: de bron (als die er nog is) en/of de rij met de beslissing."""

    key: str
    source: "SourceItem | None"
    row: SiteChange | None

    @property
    def kind(self) -> str:
        return self.row.source_kind if self.row is not None else self.source.source_kind

    @property
    def status(self) -> str | None:
        if self.row is not None:
            return self.row.status
        return status_from_source(self.source.source_kind, self.source.status)

    @property
    def url_key(self) -> str:
        return self.source.url_key if self.source is not None else self.row.url_key

    @property
    def page_url(self) -> str:
        return self.source.page_url if self.source is not None else self.row.page_url

    @property
    def topic(self) -> str:
        return self.row.topic if self.row is not None else self.source.topic

    def field(self, name: str) -> Any:
        """Waarde uit de rij (momentopname van de beslissing), anders uit de bron."""
        if self.row is not None:
            value = getattr(self.row, name)
            if value is not None:
                return value
        return getattr(self.source, name, None) if self.source is not None else None


def merge_entries(sources: dict[str, "SourceItem"], rows: list[SiteChange]) -> list[Entry]:
    """Koppel rijen aan bronnen op sleutel (terugval: voorstel-id uit source_ref).

    Bronnen die niet getoond worden (opgelost actiepunt zonder rij) vallen af; rijen zonder bron
    blijven staan.
    """
    by_suggestion = {
        item.source_ref.get("suggestion_id"): item for item in sources.values()
        if item.source_kind == KIND_SUGGESTION and item.source_ref.get("suggestion_id")
    }
    rows_by_key = {row.source_key: row for row in rows}
    entries: list[Entry] = []
    used_sources: set[str] = set()
    for row in rows:
        source = sources.get(row.source_key)
        if source is None:
            hint = (row.source_ref or {}).get("suggestion_id") if isinstance(row.source_ref, dict) else None
            candidate = by_suggestion.get(hint) if hint else None
            if candidate is not None and candidate.key not in rows_by_key and candidate.key not in used_sources:
                source = candidate
        if source is not None:
            used_sources.add(source.key)
        entries.append(Entry(key=row.source_key, source=source, row=row))
    for key, source in sources.items():
        if key in used_sources or key in rows_by_key:
            continue
        entry = Entry(key=key, source=source, row=None)
        if entry.status is not None:
            entries.append(entry)
    return entries


# --- acties -------------------------------------------------------------------------

class ChangeActionError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def snapshot_of(entry: Entry) -> dict[str, Any]:
    """Velden om de rij zelfstandig te kunnen tonen (uit de bron, anders de bestaande rij)."""
    source, row = entry.source, entry.row
    if source is None:
        assert row is not None
        return {}
    return {
        "page_url": source.page_url,
        "url_key": source.url_key,
        "topic": source.topic,
        "source_kind": source.source_kind,
        # Ids zijn vluchtig (hint); het type maakt de rij zelfstandig controleerbaar.
        "source_ref": {**source.source_ref, "type": source.type_key},
        "title": source.title,
        "description": source.description,
        "current_value": source.current_value,
        "proposed_value": source.proposed_value,
        "rationale": source.rationale,
        "ref": source.ref,
        "severity": source.severity,
        "item_label": source.item_label,
    }


def upsert_row(db: Session, customer_id: str, entry: Entry, fields: dict[str, Any]) -> SiteChange:
    """Rij voor dit punt aanmaken of bijwerken. Maakt een collega tegelijk dezelfde rij aan
    (unieke sleutel), dan wordt die bestaande rij bijgewerkt."""
    now = _now()
    values = {**snapshot_of(entry), **fields, "updated_at": now}
    row = entry.row
    if row is None:
        row = (
            db.query(SiteChange)
            .filter(SiteChange.customer_website_id == customer_id, SiteChange.source_key == entry.key)
            .first()
        )
    if row is None:
        new_row = SiteChange(
            id=str(uuid.uuid4()), customer_website_id=customer_id, source_key=entry.key,
            created_at=now, **{"edited": False, **values},
        )
        try:
            with db.begin_nested():
                db.add(new_row)
                db.flush()
            entry.row = new_row
            return new_row
        except IntegrityError:
            row = (
                db.query(SiteChange)
                .filter(SiteChange.customer_website_id == customer_id, SiteChange.source_key == entry.key)
                .first()
            )
            if row is None:
                raise
    for name, value in values.items():
        setattr(row, name, value)
    entry.row = row
    return row


def write_source_status(db: Session, entry: Entry, status: str, user_id: str) -> LaunchScan | None:
    """Zet de bestaande status van het voorstel of de actiepunten.

    `status` is de status in deze module (open / goedgekeurd / afgewezen / doorgevoerd).
    Geeft de fase-3 scan terug waarvan de checklist opnieuw berekend moet worden (of None).
    """
    source = entry.source
    if source is None:
        return None
    now = _now()
    if source.source_kind == KIND_SUGGESTION:
        suggestion = source.suggestion
        if suggestion is None:
            return None
        target = {OPEN: "open", APPROVED: "open", REJECTED: "afgewezen", DONE: "overgenomen"}[status]
        if suggestion.status == target:
            return None
        suggestion.status = target
        suggestion.updated_by = user_id
        suggestion.updated_at = now
        source.status = target
        return db.get(LaunchScan, suggestion.scan_id)
    for issue in source.issues:
        if status == REJECTED:
            target = "genegeerd"
        elif status == DONE:
            target = "opgelost"
        else:
            # Terug naar open; een punt met Monday-koppeling blijft 'doorgezet'.
            target = "doorgezet" if issue.external_item_id else "open"
        if issue.status != target:
            issue.status = target
            issue.updated_at = now
    if source.issues:
        source.status = source.issues[0].status
    return None


def rebuild_scans(db: Session, scans: list[LaunchScan | None]) -> None:
    """Fase-3 checklist herberekenen (zoals de router van fase 3 doet na een statuswijziging)."""
    seen: set[str] = set()
    for scan in scans:
        if scan is None or scan.id in seen:
            continue
        seen.add(scan.id)
        if scan.status == "completed":
            db.flush()
            rebuild_content_checklist(db, scan)


def apply_action(
    db: Session,
    customer_id: str,
    entry: Entry,
    *,
    action: str,
    user_id: str,
    value: str | None = None,
    note: str | None = None,
) -> SiteChange | None:
    """Voer een actie uit (approve / reject / reopen / done) en schrijf door naar de bron.

    Geeft de resulterende rij terug (None als die verwijderd is). Gooit `ChangeActionError`
    bij een ongeldige overgang. Commit niet.
    """
    status = entry.status
    kind = entry.kind
    now = _now()
    extra = {"note": note} if note is not None else {}
    scans: list[LaunchScan | None] = []

    if action == "approve":
        if kind != KIND_SUGGESTION:
            raise ChangeActionError(422, "Een actiepunt heeft geen voorstel om goed te keuren.")
        if status == DONE:
            raise ChangeActionError(409, "Dit voorstel is al doorgevoerd; heropen het eerst.")
        proposal = entry.field("proposed_value") or ""
        approved = proposal if value is None else value
        if not approved.strip():
            raise ChangeActionError(422, "De goedgekeurde tekst is leeg.")
        row = upsert_row(db, customer_id, entry, {
            "status": APPROVED,
            "approved_value": approved,
            "edited": normalize_key_text(approved) != normalize_key_text(proposal),
            "reviewed_by": user_id, "reviewed_at": now,
            "verified": None, "verify_detail": None, "done_by": None, "done_at": None,
            **extra,
        })
        scans.append(write_source_status(db, entry, APPROVED, user_id))
    elif action == "reject":
        if status == DONE:
            raise ChangeActionError(409, "Dit punt is al doorgevoerd; heropen het eerst.")
        row = upsert_row(db, customer_id, entry, {
            "status": REJECTED,
            "reviewed_by": user_id, "reviewed_at": now,
            "verified": None, "verify_detail": None, "done_by": None, "done_at": None,
            **extra,
        })
        scans.append(write_source_status(db, entry, REJECTED, user_id))
    elif action == "reopen":
        row = entry.row
        if row is not None:
            if row.status == DONE and kind == KIND_SUGGESTION and row.approved_value:
                row.status = APPROVED
                row.verified = None
                row.verify_detail = None
                row.done_by = None
                row.done_at = None
                row.updated_at = now
                if note is not None:
                    row.note = note
                scans.append(write_source_status(db, entry, APPROVED, user_id))
            else:
                db.delete(row)
                entry.row = None
                row = None
                scans.append(write_source_status(db, entry, OPEN, user_id))
        else:
            scans.append(write_source_status(db, entry, OPEN, user_id))
    elif action == "done":
        if status == REJECTED:
            raise ChangeActionError(409, "Een afgewezen punt kan niet als gedaan worden gemarkeerd; heropen het eerst.")
        if status == OPEN and kind == KIND_SUGGESTION:
            raise ChangeActionError(409, "Keur het voorstel eerst goed voordat je het als gedaan markeert.")
        if status == DONE and entry.row is not None:
            row = entry.row
            if note is not None:
                row.note = note
                row.updated_at = now
        else:
            fields: dict[str, Any] = {
                "status": DONE, "verified": None, "verify_detail": None,
                "done_by": user_id, "done_at": now, **extra,
            }
            if kind == KIND_SUGGESTION and entry.row is None:
                # Doorgevoerd zonder eerdere rij (bijv. 'overgenomen' in fase 3): het voorstel geldt.
                fields["approved_value"] = entry.field("proposed_value")
            row = upsert_row(db, customer_id, entry, fields)
        scans.append(write_source_status(db, entry, DONE, user_id))
    else:
        raise ChangeActionError(422, "Onbekende actie.")

    rebuild_scans(db, scans)
    return row


def mark_verified(
    db: Session, customer_id: str, entry: Entry, *, user_id: str, detail: dict[str, Any],
) -> SiteChange:
    """Live teruggezien: rij op doorgevoerd (verified) en de bron op overgenomen / opgelost."""
    now = _now()
    fields: dict[str, Any] = {
        "status": DONE, "verified": True, "verify_detail": detail, "done_by": user_id, "done_at": now,
    }
    if entry.kind == KIND_SUGGESTION and not entry.field("approved_value"):
        fields["approved_value"] = entry.field("proposed_value")
    row = upsert_row(db, customer_id, entry, fields)
    return row


def mark_not_found(entry: Entry, detail: dict[str, Any]) -> None:
    """Gecontroleerd maar (nog) niet live: blijft goedgekeurd, met wat er nu staat."""
    row = entry.row
    assert row is not None
    row.verified = False
    row.verify_detail = detail
    row.updated_at = _now()
