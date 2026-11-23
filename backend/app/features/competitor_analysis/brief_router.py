"""Content brief + concepttekst per zoekwoord van een concurrentieanalyse.

Tweede router in deze feature (zelfde prefix `/api/competitor-analyses`, zodat de bestaande
frontend-proxy werkt). Het schrijven zelf gebeurt in de taak `worker/brief.py`; deze router
maakt de rij aan, zet hem op `pending` en plant de taak in.

- `GET  /analyses/{aid}/keywords/{kid}/brief`: de brief; 404 als er nog geen is. Een brief die
  langer dan `STALE_BRIEF_AFTER` actief staat zonder levensteken wordt eerst `failed`.
- `POST /analyses/{aid}/keywords/{kid}/brief`: starten, of na `failed` hervatten vanaf de
  mislukte stap (staat de brief er al, dan alleen het concept). 409 bij een lopende of
  afgeronde brief.
- `POST /analyses/{aid}/keywords/{kid}/brief/concept`: alleen de concepttekst opnieuw; de brief
  en het vorige concept blijven staan tot het nieuwe concept klaar is.
- `GET  /customers/{cid}/briefs`: overzicht van de briefs van een klant, laatst gewijzigd eerst.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id
from app.db.models import (
    CompetitorAnalysis,
    CompetitorAnalysisKeyword,
    ContentBrief as ContentBriefRow,
    CustomerWebsite,
)
from app.db.session import get_db
from app.features.competitor_analysis.mappers import to_content_brief, to_content_brief_list_item
from app.features.competitor_analysis.schemas import (
    ACTIVE_BRIEF_STATUSES,
    ContentBrief,
    ContentBriefListResponse,
)
from app.features.launch_checklist.services.scan_recovery import is_older_than
from app.services.anthropic import client as anthropic_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/competitor-analyses", tags=["competitor-analyses-brief"])

# De taak heeft een harde limiet van 10 minuten; daarna loopt er zeker niets meer.
STALE_BRIEF_AFTER = timedelta(minutes=15)

MESSAGES: dict[str, str] = {
    "customer": "Klant niet gevonden.",
    "analysis": "Analyse niet gevonden.",
    "keyword": "Zoekwoord niet gevonden in deze analyse.",
    "no_brief": "Er is nog geen content brief voor dit zoekwoord.",
    "not_completed": "Dit zoekwoord is nog niet klaar in de analyse; een content brief kan pas daarna.",
    "not_configured": "Claude is niet gekoppeld: ANTHROPIC_API_KEY ontbreekt in de backend-configuratie.",
    "running": "Er wordt al aan deze content brief geschreven. Wacht tot die klaar is.",
    "exists": "De content brief voor dit zoekwoord bestaat al. Gebruik \"Opnieuw genereren\" voor een nieuwe concepttekst.",
    "concept_without_brief": "Er is nog geen brief om een concept op te baseren; maak eerst de content brief.",
    "not_queued": "De content brief kon niet worden ingepland: de takenwachtrij is niet bereikbaar. "
                  "Probeer het later opnieuw.",
    "stale": "Het schrijven is onderbroken (bijvoorbeeld door een herstart van de server). Probeer het opnieuw.",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_keyword(db: Session, analysis_id: str, keyword_id: str) -> tuple[CompetitorAnalysis, CompetitorAnalysisKeyword]:
    analysis = db.get(CompetitorAnalysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail=MESSAGES["analysis"])
    keyword = db.get(CompetitorAnalysisKeyword, keyword_id)
    if keyword is None or keyword.analysis_id != analysis_id:
        raise HTTPException(status_code=404, detail=MESSAGES["keyword"])
    return analysis, keyword


def _find(db: Session, keyword_id: str) -> ContentBriefRow | None:
    return db.query(ContentBriefRow).filter(ContentBriefRow.keyword_id == keyword_id).first()


def recover_stale_brief(db: Session, row: ContentBriefRow, *, now: datetime | None = None) -> bool:
    """Zet een actieve brief zonder levensteken (ouder dan `STALE_BRIEF_AFTER`) op `failed`."""
    if row.status not in ACTIVE_BRIEF_STATUSES or not is_older_than(row.updated_at, STALE_BRIEF_AFTER, now=now):
        return False
    row.status = "failed"
    row.error_message = MESSAGES["stale"]
    row.updated_at = now or _now()
    db.commit()
    return True


def _require_claude() -> None:
    if not anthropic_client.is_configured():
        raise HTTPException(status_code=503, detail=MESSAGES["not_configured"])


def _enqueue(db: Session, row: ContentBriefRow, *, concept_only: bool) -> None:
    """Plan de taak in; lukt dat niet, dan `failed` met een melding en 503."""
    from app.worker.tasks import run_content_brief_task  # voorkom circulaire import

    try:
        run_content_brief_task.delay(row.id, concept_only=concept_only)
    except Exception as exc:  # noqa: BLE001 - bijv. Redis niet bereikbaar
        logger.exception("Content brief %s niet ingepland", row.id)
        row.status = "failed"
        row.error_message = MESSAGES["not_queued"]
        row.updated_at = _now()
        db.commit()
        raise HTTPException(status_code=503, detail=MESSAGES["not_queued"]) from exc


def _restart(db: Session, row: ContentBriefRow) -> None:
    row.status = "pending"
    row.error_message = None
    row.updated_at = _now()
    db.commit()


@router.get("/analyses/{analysis_id}/keywords/{keyword_id}/brief", response_model=ContentBrief)
async def get_brief(
    analysis_id: str,
    keyword_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """De brief van dit zoekwoord; licht genoeg om elke 3 seconden te pollen."""
    analysis, keyword = _get_keyword(db, analysis_id, keyword_id)
    row = _find(db, keyword.id)
    if row is None:
        raise HTTPException(status_code=404, detail=MESSAGES["no_brief"])
    recover_stale_brief(db, row)
    return to_content_brief(row, keyword, analysis)


@router.post("/analyses/{analysis_id}/keywords/{keyword_id}/brief", response_model=ContentBrief)
def start_brief(
    analysis_id: str,
    keyword_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Start de brief (of hervat na `failed`: met een bestaande brief alleen het concept)."""
    analysis, keyword = _get_keyword(db, analysis_id, keyword_id)
    if keyword.status != "completed":
        raise HTTPException(status_code=400, detail=MESSAGES["not_completed"])
    _require_claude()

    row = _find(db, keyword.id)
    if row is not None:
        recover_stale_brief(db, row)
        if row.status in ACTIVE_BRIEF_STATUSES:
            raise HTTPException(status_code=409, detail=MESSAGES["running"])
        if row.status != "failed":
            raise HTTPException(status_code=409, detail=MESSAGES["exists"])
        _restart(db, row)
    else:
        now = _now()
        row = ContentBriefRow(
            id=str(uuid.uuid4()),
            keyword_id=keyword.id,
            analysis_id=analysis.id,
            customer_website_id=analysis.customer_website_id,
            status="pending",
            created_by=user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError as exc:  # tegelijk gestart: de andere aanvraag won
            db.rollback()
            raise HTTPException(status_code=409, detail=MESSAGES["running"]) from exc

    _enqueue(db, row, concept_only=row.brief is not None)
    db.refresh(row)
    return to_content_brief(row, keyword, analysis)


@router.post("/analyses/{analysis_id}/keywords/{keyword_id}/brief/concept", response_model=ContentBrief)
def regenerate_concept(
    analysis_id: str,
    keyword_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Alleen de concepttekst opnieuw; de brief blijft staan (en het vorige concept tot het
    nieuwe klaar is)."""
    analysis, keyword = _get_keyword(db, analysis_id, keyword_id)
    row = _find(db, keyword.id)
    if row is None:
        raise HTTPException(status_code=409, detail=MESSAGES["no_brief"])
    recover_stale_brief(db, row)
    if row.status in ACTIVE_BRIEF_STATUSES:
        raise HTTPException(status_code=409, detail=MESSAGES["running"])
    if row.brief is None:
        raise HTTPException(status_code=409, detail=MESSAGES["concept_without_brief"])
    _require_claude()
    _restart(db, row)
    _enqueue(db, row, concept_only=True)
    db.refresh(row)
    return to_content_brief(row, keyword, analysis)


@router.get("/customers/{customer_id}/briefs", response_model=ContentBriefListResponse)
async def list_briefs(
    customer_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Content briefs van de klant, laatst gewijzigd eerst. Vastgelopen briefs eerst `failed`."""
    if db.get(CustomerWebsite, customer_id) is None:
        raise HTTPException(status_code=404, detail=MESSAGES["customer"])
    active = (
        db.query(ContentBriefRow)
        .filter(ContentBriefRow.customer_website_id == customer_id,
                ContentBriefRow.status.in_(ACTIVE_BRIEF_STATUSES))
        .all()
    )
    for row in active:
        recover_stale_brief(db, row)
    rows = (
        db.query(ContentBriefRow, CompetitorAnalysisKeyword, CompetitorAnalysis)
        .join(CompetitorAnalysisKeyword, CompetitorAnalysisKeyword.id == ContentBriefRow.keyword_id)
        .join(CompetitorAnalysis, CompetitorAnalysis.id == ContentBriefRow.analysis_id)
        .filter(ContentBriefRow.customer_website_id == customer_id)
        .order_by(ContentBriefRow.updated_at.desc(), ContentBriefRow.id.desc())
        .limit(limit)
        .all()
    )
    return ContentBriefListResponse(
        items=[to_content_brief_list_item(row, keyword, analysis) for row, keyword, analysis in rows]
    )
