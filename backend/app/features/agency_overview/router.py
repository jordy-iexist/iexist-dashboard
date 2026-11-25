"""Bureau-overzicht: hoe alle klanten ervoor staan en wat aandacht vraagt.

`GET /overview` leest de opgeslagen positie-momentopnames (geen live ProRankTracker), synchroniseert
het bord van de werkvoorraad en vraagt Search Console één keer de lijst met properties.
`POST /rankings/refresh` haalt eerst de posities van alle klanten opnieuw op (synchroon).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id
from app.db.session import get_db
from app.features.agency_overview.mappers import to_overview
from app.features.agency_overview.schemas import OverviewResponse
from app.features.agency_overview.services.overview import build_overview
from app.features.agency_overview.services.rank_snapshots import refresh_all

router = APIRouter(prefix="/api/agency-overview", tags=["agency-overview"])


@router.get("/overview", response_model=OverviewResponse)
def get_overview(
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    return to_overview(build_overview(db))


@router.post("/rankings/refresh", response_model=OverviewResponse)
def refresh_rankings(
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Posities van alle klanten opnieuw ophalen en daarna het overzicht."""
    refresh_all(db)
    return to_overview(build_overview(db))
