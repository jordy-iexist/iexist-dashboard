"""Checklist van een klant zoals de UI, de export en de agent hem zien.

Eén plek voor het samenvoegen van de auto-resultaten (fase-2 scan) met de
handmatige status per klant, inclusief de webshop-override van de klant.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import CustomerWebsite, LaunchChecklistState, LaunchScan
from app.features.launch_checklist.services.content_checklist import merge_content_checklist
from app.features.launch_checklist.services.geo_checklist import merge_checklist
from app.features.launch_checklist.services.quarterly_checklist import merge_quarterly_checklist


def latest_completed_scan(db: Session, customer_id: str, phase: int) -> LaunchScan | None:
    return (
        db.query(LaunchScan)
        .filter(
            LaunchScan.customer_website_id == customer_id,
            LaunchScan.phase == phase,
            LaunchScan.status == "completed",
        )
        .order_by(LaunchScan.created_at.desc())
        .first()
    )


def latest_completed_geo(db: Session, customer_id: str) -> LaunchScan | None:
    return latest_completed_scan(db, customer_id, 2)


def latest_content_scan(db: Session, customer_id: str) -> LaunchScan | None:
    """Laatste fase-3 scan met een checklist (ook tijdens een lopende AI-analyse)."""
    return (
        db.query(LaunchScan)
        .filter(
            LaunchScan.customer_website_id == customer_id,
            LaunchScan.phase == 3,
            LaunchScan.checklist.isnot(None),
            LaunchScan.status.in_(("completed", "analyzing")),
        )
        .order_by(LaunchScan.created_at.desc())
        .first()
    )


def states_for_customer(
    db: Session, customer_id: str, period: str = ""
) -> dict[str, LaunchChecklistState]:
    """Handmatige status per punt. `period` is leeg voor fase 2/3, een ronde voor fase 4."""
    rows = (
        db.query(LaunchChecklistState)
        .filter(
            LaunchChecklistState.customer_website_id == customer_id,
            LaunchChecklistState.period == period,
        )
        .all()
    )
    return {row.item_key: row for row in rows}


def resolve_is_webshop(customer: CustomerWebsite | None, payload: dict[str, Any]) -> bool:
    """Handmatige keuze van de klant gaat voor op de detectie van de scan."""
    if customer is not None and customer.launch_is_webshop is not None:
        return bool(customer.launch_is_webshop)
    return bool(payload.get("webshop_detected"))


def merged_checklist(
    db: Session,
    customer: CustomerWebsite | None,
    scan: LaunchScan | None,
    *,
    states: dict[str, LaunchChecklistState] | None = None,
) -> dict[str, Any]:
    """Samengevoegde checklist voor `scan` (None = nog geen fase-2 scan)."""
    payload = (scan.checklist if scan else None) or {}
    if states is None:
        customer_id = customer.id if customer else (scan.customer_website_id if scan else None)
        states = states_for_customer(db, customer_id) if customer_id else {}
    merged = merge_checklist(
        payload.get("items"), states, is_webshop=resolve_is_webshop(customer, payload)
    )
    merged["is_webshop"] = resolve_is_webshop(customer, payload)
    return merged


def merged_content_checklist(
    db: Session,
    customer_id: str,
    scan: LaunchScan | None,
    *,
    states: dict[str, LaunchChecklistState] | None = None,
) -> dict[str, Any]:
    """Samengevoegde fase-3 checklist voor `scan` (None = nog geen fase-3 scan)."""
    payload = (scan.checklist if scan else None) or {}
    if states is None:
        states = states_for_customer(db, customer_id)
    return merge_content_checklist(payload.get("items"), states)


# --- fase 4: kwartaal GEO-werkzaamheden --------------------------------------

def latest_quarterly_scan(db: Session, customer_id: str, period: str | None = None) -> LaunchScan | None:
    """Laatste voltooide fase 4-scan, optioneel binnen één ronde."""
    query = db.query(LaunchScan).filter(
        LaunchScan.customer_website_id == customer_id,
        LaunchScan.phase == 4,
        LaunchScan.status == "completed",
    )
    if period is not None:
        query = query.filter(LaunchScan.period == period)
    return query.order_by(LaunchScan.created_at.desc()).first()


def quarterly_periods(db: Session, customer_id: str) -> dict[str, bool]:
    """Rondes met een voltooide fase 4-scan of handmatige status, nieuwste eerst.

    Waarde: of de ronde een voltooide scan heeft.
    """
    scanned = {
        row[0]
        for row in db.query(LaunchScan.period).filter(
            LaunchScan.customer_website_id == customer_id,
            LaunchScan.phase == 4,
            LaunchScan.status == "completed",
            LaunchScan.period.isnot(None),
        )
    }
    stated = {
        row[0]
        for row in db.query(LaunchChecklistState.period).filter(
            LaunchChecklistState.customer_website_id == customer_id,
            LaunchChecklistState.period != "",
        )
    }
    return {period: period in scanned for period in sorted(scanned | stated, reverse=True)}


def comparison_base(db: Session, scan: LaunchScan) -> LaunchScan | None:
    """Vergelijkingsbasis: de laatste fase 4-scan uit een eerdere ronde, anders de nulmeting."""
    previous = (
        db.query(LaunchScan)
        .filter(
            LaunchScan.customer_website_id == scan.customer_website_id,
            LaunchScan.phase == 4,
            LaunchScan.status == "completed",
            LaunchScan.id != scan.id,
            LaunchScan.period != scan.period,
            LaunchScan.created_at < scan.created_at,
        )
        .order_by(LaunchScan.created_at.desc())
        .first()
    )
    return previous or latest_completed_scan(db, scan.customer_website_id, 1)


def merged_quarterly_checklist(
    db: Session,
    customer_id: str,
    scan: LaunchScan | None,
    period: str,
    *,
    states: dict[str, LaunchChecklistState] | None = None,
) -> dict[str, Any]:
    """Samengevoegde fase-4 checklist van één ronde (scan None = nog niet gescand)."""
    payload = (scan.checklist if scan else None) or {}
    if states is None:
        states = states_for_customer(db, customer_id, period)
    return merge_quarterly_checklist(payload.get("items"), states)
