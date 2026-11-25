"""Bron Search Console: één kaart per klant "Title & meta herschrijven".

De kansen komen live uit Google via `customer_insights` (CTR-kansen over 28 dagen). Alleen de
title- en meta-adviezen tellen mee (`improve_snippet` en `improve_snippet_top`);
`improve_position` en `check_intent` blijven alleen op de Search Console-pagina staan.

Een item is pagina plus zoekterm; verwijderen en de rust na handmatig afronden (56 dagen,
`types.REST_DAYS`) gelden per pagina (`suppress_key`). De momentopname op de kaart is de
rustlijst: bij Klaar, terugzetten of verwijderen hoeft in de bron niets te gebeuren.

Deze bron wordt niet gesynchroniseerd bij het ophalen van het bord (dat zou bij elke
paginalading Google aanroepen), maar alleen door de wekelijkse taak
(`worker/search_console.py`), via `sync_customer`.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING, Any, Iterable

from app.features.customers.rankings import keyword_key
from app.features.customers.search_console_insights import customer_insights
from app.features.launch_checklist.services.discovery import url_key
from app.features.work_queue.services.sync import apply_groups
from app.features.work_queue.services.types import (
    KIND_CTR,
    SEVERITY_MEDIUM,
    SOURCE_SEARCH_CONSOLE,
    Group,
    Item,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.db.models import CustomerWebsite, WorkItem

logger = logging.getLogger(__name__)

GROUP_KEY = "ctr"
GROUP_TITLE = "Title & meta herschrijven"
# Alleen deze adviezen horen op de kaart: de rest vraagt geen nieuwe title of meta.
ADVICE_CODES: frozenset[str] = frozenset({"improve_snippet", "improve_snippet_top"})
# Periode van de kansen, in dagen (zoals de standaard op de Search Console-pagina).
DAYS = 28

_REF_FIELDS = ("query", "missed_clicks", "position", "impressions", "clicks", "advice_code")


def group_from(customer_id: str, rows: Iterable[dict[str, Any]]) -> Group | None:
    """De kaart van één klant uit de rijen van de CTR-kansen; None als er geen title- of
    meta-advies bij zit. Volgorde van de items = volgorde van de rijen (meeste gemiste
    klikken eerst). Itemsleutel is pagina plus zoekterm, `suppress_key` de pagina."""
    items: list[Item] = []
    seen: set[str] = set()
    for row in rows or []:
        if row.get("advice_code") not in ADVICE_CODES:
            continue
        page = str(row.get("page") or "").strip()
        query = str(row.get("query") or "").strip()
        if not page or not keyword_key(query):
            continue
        page_key = url_key(page)
        key = f"{page_key}|{keyword_key(query)}"
        if key in seen:
            continue
        seen.add(key)
        items.append(Item(
            key=key,
            title=query,
            url=page,
            severity=None,
            ref={name: row.get(name) for name in _REF_FIELDS},
            suppress_key=page_key,
        ))
    if not items:
        return None
    return Group(
        customer_id=customer_id,
        source=SOURCE_SEARCH_CONSOLE,
        group_key=GROUP_KEY,
        title=GROUP_TITLE,
        kind=KIND_CTR,
        severity=SEVERITY_MEDIUM,
        items=items,
    )


class SearchConsoleAdapter:
    """Adapter volgens `types.Adapter`.

    `collect` geeft altijd een lege lijst: deze bron wordt niet bij het ophalen van het bord
    gesynchroniseerd, alleen door de wekelijkse taak (`sync_customer`). `complete`, `reopen`
    en `dismiss` doen niets: de momentopname op de kaart is de rustlijst, en onderdrukken doet
    de sync zelf (rust via `REST_DAYS`, verwijderd via kaarten op `removed`).
    """

    source = SOURCE_SEARCH_CONSOLE

    def collect(self, db: Session, customer_ids: set[str] | None = None) -> list[Group]:
        return []

    def complete(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None:
        return None

    def reopen(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None:
        return None

    def dismiss(self, db: Session, card: WorkItem, user_id: str | None, now: datetime) -> None:
        return None


search_console_adapter = SearchConsoleAdapter()


def sync_customer(
    db: Session,
    customer: CustomerWebsite,
    *,
    now: datetime,
    insights: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Synchroniseert de Search Console-kaart van één klant. Commit niet.

    `insights` is het antwoord van `customer_insights` (28 dagen); zonder wordt het opgehaald.
    Is de `state` niet `ok`, of zijn de CTR-kansen niet opgehaald, dan verandert er niets:
    `{"state": ..., "changed": False, "message": ...}`. Anders gaat de groep (of geen groep)
    naar `apply_groups`; zonder title- of meta-adviezen rondt dat een open kaart vanzelf af,
    zonder rustperiode. Antwoord dan: `{"state": "ok", "changed", "created", "updated",
    "resolved", "items"}`.
    """
    if insights is None:
        insights = customer_insights(customer, DAYS)

    state = str(insights.get("state") or "error")
    if state != "ok":
        return {"state": state, "changed": False, "message": insights.get("message")}
    section = insights.get("opportunities") or {}
    section_state = str(section.get("state") or "error")
    if section_state != "ok":
        return {"state": section_state, "changed": False, "message": section.get("message")}

    group = group_from(customer.id, section.get("rows") or [])
    result = apply_groups(
        db,
        [group] if group is not None else [],
        sources={SOURCE_SEARCH_CONSOLE},
        customer_ids={customer.id},
        now=now,
    )
    counts = asdict(result)
    return {
        "state": "ok",
        "changed": any(counts.values()),
        **counts,
        "items": len(group.items) if group is not None else 0,
    }


__all__ = [
    "ADVICE_CODES",
    "DAYS",
    "GROUP_KEY",
    "GROUP_TITLE",
    "SearchConsoleAdapter",
    "group_from",
    "search_console_adapter",
    "sync_customer",
]
