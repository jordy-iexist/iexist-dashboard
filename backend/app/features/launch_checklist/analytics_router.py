"""Analytics van de livegang checklist: trend per klant, scan A tegen B en klanten onderling.

Alleen lezen. Rekenwerk staat in `services/analytics.py`.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, load_only

from app.core.dependencies import require_user_id
from app.db.models import CustomerWebsite, LaunchScan
from app.db.session import get_db
from app.features.launch_checklist.analytics_schemas import (
    BenchmarkResponse,
    CompareResponse,
    TrendResponse,
)
from app.features.launch_checklist.services import analytics
from app.features.launch_checklist.services.checklist_view import (
    checklist_progress,
    latest_scans_by_customer,
    manual_states_by_customer,
)
from app.features.launch_checklist.services.golive_checklist import PHASE as GOLIVE_PHASE
from app.features.launch_checklist.services.quarterly_compare import compare_rankings

router = APIRouter(prefix="/api/launch-checklist/analytics", tags=["launch-checklist-analytics"])

# Voor de checklist-voortgang is alleen de checklist van de scan nodig, niet de rest.
_CHECKLIST_COLUMNS = load_only(
    LaunchScan.id,
    LaunchScan.customer_website_id,
    LaunchScan.phase,
    LaunchScan.status,
    LaunchScan.created_at,
    LaunchScan.checklist,
)


def _customer_ref(customer: CustomerWebsite) -> dict[str, str]:
    return {"id": customer.id, "name": customer.name, "domain": customer.domain}


@router.get("/customers/{customer_id}/trend", response_model=TrendResponse)
def get_trend(
    customer_id: str,
    start: date | None = Query(None),
    end: date | None = Query(None),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    customer = db.get(CustomerWebsite, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Klant niet gevonden.")
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="De startdatum ligt na de einddatum.")
    snapshots = analytics.load_customer_snapshots(db, customer_id)
    return {"customer": _customer_ref(customer), **analytics.build_trend(snapshots, start=start, end=end)}


@router.get("/compare", response_model=CompareResponse)
def compare_scans(
    a: str = Query(..., min_length=1),
    b: str = Query(..., min_length=1),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    if a == b:
        raise HTTPException(status_code=400, detail="Kies twee verschillende scans.")
    found = {s.id: s for s in analytics.load_snapshots(db, LaunchScan.id.in_((a, b)))}
    missing = [scan_id for scan_id in (a, b) if scan_id not in found]
    if missing:
        raise HTTPException(status_code=404, detail="Scan niet gevonden.")
    scan_a, scan_b = found[a], found[b]
    if scan_a.customer_id != scan_b.customer_id:
        raise HTTPException(status_code=400, detail="De scans horen bij verschillende klanten.")
    for scan in (scan_a, scan_b):
        if scan.phase not in analytics.TREND_PHASES:
            raise HTTPException(
                status_code=400, detail="Alleen de nulmeting (fase 1) en kwartaalscans (fase 4) zijn te vergelijken.")
        if scan.status != "completed":
            raise HTTPException(status_code=400, detail="Alleen voltooide scans zijn te vergelijken.")

    first, second = analytics.order_pair(scan_a, scan_b)
    # Ruwe tijden uit de database, zodat ze met de SEO-tracker-tijden vergelijkbaar blijven.
    rankings = compare_rankings(
        db,
        first.customer_id,
        first.completed_at or first.created_at,
        until=second.completed_at or second.created_at,
    )
    return analytics.build_compare(
        first,
        second,
        pages_a=analytics.load_page_rows(db, first.id),
        pages_b=analytics.load_page_rows(db, second.id),
        rankings=rankings,
    )


@router.get("/benchmark", response_model=BenchmarkResponse)
def get_benchmark(
    max_age_days: int | None = Query(None, ge=1),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    # Klanten met minstens één voltooide scan (elke fase).
    customer_ids = {
        row[0]
        for row in db.query(LaunchScan.customer_website_id).filter(LaunchScan.status == "completed").distinct()
    }
    customers = (
        db.query(CustomerWebsite)
        .options(load_only(CustomerWebsite.id, CustomerWebsite.name, CustomerWebsite.domain,
                           CustomerWebsite.launch_is_webshop))
        .filter(CustomerWebsite.id.in_(customer_ids))
        .order_by(CustomerWebsite.name.asc())
        .all()
    ) if customer_ids else []

    # Checklist-voortgang: dezelfde scans en berekening als het klantenoverzicht (GET /customers).
    completed_geo = latest_scans_by_customer(db, phase=2, completed_only=True, options=(_CHECKLIST_COLUMNS,))
    latest_content = latest_scans_by_customer(db, phase=3, options=(_CHECKLIST_COLUMNS,))
    completed_golive = latest_scans_by_customer(
        db, phase=GOLIVE_PHASE, completed_only=True, options=(_CHECKLIST_COLUMNS,))
    states = manual_states_by_customer(db)
    checklist_values: dict[str, dict[str, int | None]] = {}
    for customer in customers:
        progress = checklist_progress(
            db,
            customer,
            states.get(customer.id, {}),
            geo=completed_geo.get(customer.id),
            content=latest_content.get(customer.id),
            golive=completed_golive.get(customer.id),
        )
        checklist_values[customer.id] = {
            "checklist_geo_pct": progress["geo"]["percent"] if progress["geo"] else None,
            "checklist_content_pct": progress["content"]["percent"] if progress["content"] else None,
            "checklist_golive_pct": progress["golive"]["percent"] if progress["golive"] else None,
        }

    latest = analytics.load_latest_snapshots(db)
    return analytics.build_benchmark(customers, latest, checklist_values, max_age_days=max_age_days)
