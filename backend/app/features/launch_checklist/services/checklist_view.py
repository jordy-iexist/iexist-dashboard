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


def states_for_customer(db: Session, customer_id: str) -> dict[str, LaunchChecklistState]:
    rows = (
        db.query(LaunchChecklistState)
        .filter(LaunchChecklistState.customer_website_id == customer_id)
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
