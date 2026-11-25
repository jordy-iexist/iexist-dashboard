"""Vaste waarden en vormen van de werkvoorraad.

Een bron (scan, analyse, Search Console, aanpassingen) levert per klant een lijst groepen; elke
groep wordt één kaart. Een groep bestaat uit items: de losse punten die bij elkaar horen. De
kaart bewaart een momentopname van die items (`WorkItem.items`, lijst van `Item.as_dict()`).

Onderdrukken (zie `sync.py`):
- Een verwijderde kaart onderdrukt voorgoed de items op `suppress_key or key` binnen dezelfde
  (klant, bron, groepssleutel). Bij bronnen in `SUPPRESS_WHOLE_GROUP` onderdrukt hij de hele
  groepssleutel.
- Een handmatig afgeronde kaart van een bron in `REST_DAYS` onderdrukt zijn items zo veel dagen
  na `done_at` (rust). Een vanzelf afgeronde kaart (`resolved_by_source`) geeft geen rust.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.db.models import WorkItem

# --- bronnen ------------------------------------------------------------------------

SOURCE_SCAN = "scan"
SOURCE_ANALYSIS = "analysis"
SOURCE_SEARCH_CONSOLE = "search_console"
SOURCE_SITE_CHANGES = "site_changes"
SOURCE_MANUAL = "manual"

SOURCES: tuple[str, ...] = (
    SOURCE_SCAN,
    SOURCE_ANALYSIS,
    SOURCE_SEARCH_CONSOLE,
    SOURCE_SITE_CHANGES,
    SOURCE_MANUAL,
)

# Eenheid achter het aantal op de kaart, als (enkelvoud, meervoud); een eigen taak heeft geen
# aantal. Scan telt bevindingen, geen pagina's: een sitebrede bevinding is geen pagina.
UNIT_BY_SOURCE: dict[str, tuple[str, str] | None] = {
    SOURCE_SCAN: ("bevinding", "bevindingen"),
    SOURCE_ANALYSIS: ("punt", "punten"),
    SOURCE_SEARCH_CONSOLE: ("CTR-kans", "CTR-kansen"),
    SOURCE_SITE_CHANGES: ("voorstel", "voorstellen"),
    SOURCE_MANUAL: None,
}


def unit_for(source: str, count: int) -> str | None:
    """Eenheid bij `count` items: enkelvoud bij precies 1, anders meervoud; None zonder eenheid."""
    forms = UNIT_BY_SOURCE.get(source)
    if forms is None:
        return None
    return forms[0] if count == 1 else forms[1]

# Een verwijderde kaart van deze bronnen onderdrukt de hele groepssleutel.
SUPPRESS_WHOLE_GROUP: frozenset[str] = frozenset({SOURCE_ANALYSIS})

# Rust na handmatig afronden, in dagen.
REST_DAYS: dict[str, int] = {SOURCE_SEARCH_CONSOLE: 56}

# --- statussen ----------------------------------------------------------------------

STATUS_TODO = "todo"
STATUS_DOING = "doing"
STATUS_REVIEW = "review"
STATUS_DONE = "done"
STATUS_REMOVED = "removed"

# Open kaarten: `active_key` = `group_key`.
ACTIVE_STATUSES: tuple[str, ...] = (STATUS_TODO, STATUS_DOING, STATUS_REVIEW)
# Kolommen op het bord, in volgorde.
BOARD_STATUSES: tuple[str, ...] = (*ACTIVE_STATUSES, STATUS_DONE)
STATUSES: tuple[str, ...] = (*BOARD_STATUSES, STATUS_REMOVED)

# --- soorten ------------------------------------------------------------------------

KIND_CTR = "ctr"
KIND_TECHNIEK = "techniek"
KIND_CONTENT = "content"
KIND_LINKS = "links"
KIND_UPDATE = "update"
KIND_RAPPORT = "rapport"

KINDS: tuple[str, ...] = (KIND_CTR, KIND_TECHNIEK, KIND_CONTENT, KIND_LINKS, KIND_UPDATE, KIND_RAPPORT)

# --- ernst --------------------------------------------------------------------------

SEVERITY_HIGH = "hoog"
SEVERITY_MEDIUM = "middel"
SEVERITY_LOW = "laag"

SEVERITIES: tuple[str, ...] = (SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW)
# Hoger = belangrijker.
SEVERITY_RANK: dict[str, int] = {SEVERITY_HIGH: 3, SEVERITY_MEDIUM: 2, SEVERITY_LOW: 1}


def severity_rank(value: str | None) -> int:
    """Rang van een ernst; een onbekende of lege waarde telt als 'middel' (de standaard)."""
    return SEVERITY_RANK.get(value or "", SEVERITY_RANK[SEVERITY_MEDIUM])


# --- groepen en items ---------------------------------------------------------------


@dataclass
class Item:
    """Eén punt binnen een groep.

    `key` is stabiel binnen (klant, bron, groepssleutel). `suppress_key` is de sleutel waarop
    verwijderen en rust werken als die grover is dan het item (bij Search Console de pagina);
    leeg = `key`. `ref` bevat de verwijzing naar de bron (ids, voor terugschrijven en de link).
    """

    key: str
    title: str
    url: str | None
    severity: str | None
    ref: dict[str, Any] = field(default_factory=dict)
    suppress_key: str | None = None

    @property
    def effective_suppress_key(self) -> str:
        return self.suppress_key or self.key

    def as_dict(self) -> dict[str, Any]:
        """Vorm in `WorkItem.items`."""
        return {
            "key": self.key,
            "title": self.title,
            "url": self.url,
            "severity": self.severity,
            "ref": dict(self.ref or {}),
            "suppress_key": self.suppress_key,
        }


@dataclass
class Group:
    """Groep punten uit één bron voor één klant; wordt één kaart.

    `title` zonder aantal. `severity` bepaalt de bron (bijv. de hoogste ernst van de items).
    """

    customer_id: str
    source: str
    group_key: str
    title: str
    kind: str
    severity: str
    items: list[Item] = field(default_factory=list)


class WorkQueueConflict(Exception):
    """Actie kan niet doorgaan door de stand van de bron of het bord (wordt een 409).

    De boodschap is een platte, Nederlandse zin voor de gebruiker.
    """


@runtime_checkable
class Adapter(Protocol):
    """Koppeling tussen één bron en de werkvoorraad.

    - `collect`: de huidige open groepen van de bron, voor alle klanten (`customer_ids=None`)
      of alleen de opgegeven klanten. Leest alleen; de aanroeper geeft het resultaat aan
      `sync.apply_groups`.
    - `complete`: de kaart gaat naar Klaar; schrijf dat terug naar de bron (bijv. rijen op
      opgelost). `reopen`: de kaart gaat terug naar een open kolom; zet de bron terug.
      `dismiss`: de kaart wordt verwijderd; doe in de bron wat daarbij hoort (vaak niets).
    - Kan de actie niet, gooi dan `WorkQueueConflict`. Geen van de methoden commit.
    """

    source: str

    def collect(self, db: Session, customer_ids: set[str] | None = None) -> list[Group]: ...

    def complete(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None: ...

    def reopen(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None: ...

    def dismiss(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None: ...
