"""Triage van actiepunten meenemen naar een nieuwe scan.

Elke scan maakt nieuwe issue-rijen. Zonder overdracht zou de status
(genegeerd / doorgezet) en de Monday-koppeling bij elke rescan verdwijnen, en
zou hetzelfde punt opnieuw naar Monday gaan.
"""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import LaunchScan, LaunchScanIssue

IssueKey = tuple[str, str]


def issue_key(issue_type: str, url: str | None) -> IssueKey:
    return (issue_type, url or "")


def previous_issue_state(db: Session, scan: LaunchScan) -> dict[IssueKey, dict[str, Any]]:
    """Over te nemen velden per (issue_type, url) uit de vorige voltooide scan
    van dezelfde klant en fase."""
    previous = (
        db.query(LaunchScan)
        .filter(
            LaunchScan.customer_website_id == scan.customer_website_id,
            LaunchScan.phase == scan.phase,
            LaunchScan.status == "completed",
            LaunchScan.id != scan.id,
        )
        .order_by(LaunchScan.created_at.desc())
        .first()
    )
    if previous is None:
        return {}
    rows = (
        db.query(LaunchScanIssue)
        .filter(
            LaunchScanIssue.scan_id == previous.id,
            or_(LaunchScanIssue.status != "open", LaunchScanIssue.external_item_id.isnot(None)),
        )
        .all()
    )
    return carried_state_from_rows(rows)


def carried_state_from_rows(rows: Iterable[LaunchScanIssue]) -> dict[IssueKey, dict[str, Any]]:
    """Over te nemen velden per (issue_type, url) uit bestaande issue-rijen.

    Genegeerd blijft genegeerd; een punt met Monday-koppeling wordt 'doorgezet'
    (met de koppeling); al het andere (open, of opgelost zonder koppeling)
    levert niets op en begint dus weer als 'open'. Bij dubbele sleutels wint
    de eerste rij. Rijen hoeven niet vooraf gefilterd te zijn.
    """
    carried: dict[IssueKey, dict[str, Any]] = {}
    for row in rows:
        linked = bool(row.external_item_id)
        if row.status == "genegeerd":
            status = "genegeerd"
        elif linked:
            # Ook een eerder 'opgelost' punt dat terugkomt: het Monday-item bestaat al.
            status = "doorgezet"
        else:
            # 'opgelost' zonder koppeling maar opnieuw gevonden: weer open.
            continue
        carried.setdefault(issue_key(row.issue_type, row.url), {
            "status": status,
            "external_provider": row.external_provider,
            "external_item_id": row.external_item_id,
            "external_url": row.external_url,
            "pushed_at": row.pushed_at,
        })
    return carried


def with_carried_state(
    issue: dict[str, Any], carried: dict[IssueKey, dict[str, Any]]
) -> dict[str, Any]:
    """Issue-velden voor een nieuwe rij, aangevuld met overgenomen triage."""
    state = carried.get(issue_key(issue["issue_type"], issue.get("url")))
    return {"status": "open", **issue, **(state or {})}
