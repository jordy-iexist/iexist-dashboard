"""Concurrentieanalyse per klant: voorstel, starten, volgen, resultaat en verbeterpunten afvinken.

De endpoints en hun request/response-modellen staan vast in `schemas.py`. De services
committen niet; dit bestand wel (behalve `recover_stale_run`, die net als bij de
livegang-scans zelf commit als hij een vastgelopen run herstelt).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import require_user_id
from app.db.models import (
    CompetitorAnalysis,
    CompetitorAnalysisAction,
    CompetitorAnalysisKeyword,
    CompetitorAnalysisPage,
    ContentBrief,
    CustomerWebsite,
)
from app.db.session import get_db
from app.features.competitor_analysis.mappers import (
    to_action_item,
    to_analysis_detail,
    to_keyword_detail,
    to_list_item,
    user_names,
)
from app.features.competitor_analysis.schemas import (
    ACTIVE_STATUSES,
    ActionItem,
    ActionUpdate,
    AnalysisCreateRequest,
    AnalysisDetail,
    AnalysisListResponse,
    Estimate,
    KeywordDetail,
    ProposalResponse,
)
from app.features.competitor_analysis.services import estimate, proposal
from app.features.competitor_analysis.services.recovery import (
    recover_customer_runs,
    recover_stale_run,
)
from app.features.customers.rankings import keyword_key
from app.services.ahrefs import client as ahrefs
from app.services.anthropic import client as anthropic_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/competitor-analyses", tags=["competitor-analyses"])

NOT_FOUND_CUSTOMER = "Klant niet gevonden."
NOT_FOUND_ANALYSIS = "Analyse niet gevonden."
NOT_FOUND_KEYWORD = "Zoekwoord niet gevonden in deze analyse."
NOT_FOUND_ACTION = "Verbeterpunt niet gevonden."

MESSAGES: dict[str, str] = {
    "ahrefs": "Ahrefs is niet gekoppeld (AHREFS_API_KEY ontbreekt in de backend-configuratie); "
              "zonder Ahrefs kan er geen analyse worden gestart.",
    "too_many": "Kies maximaal {max} zoekwoorden per analyse (nu {count}).",
    "duplicate": "Het zoekwoord \"{keyword}\" staat er meer dan één keer in.",
    "no_site": "Deze klant heeft geen website-adres, dus er kan geen doelpagina worden gekozen. "
               "Laat de doelpagina leeg (nieuwe pagina) of vul eerst het website-adres van de klant in.",
    "invalid_url": "De doelpagina \"{url}\" is geen geldig webadres.",
    "off_domain": "De doelpagina \"{url}\" ligt niet op het domein van de klant ({host}).",
    "running": "Er loopt al een analyse voor deze klant. Wacht tot die klaar is of annuleer hem.",
    "not_queued": "De analyse kon niet worden ingepland: de takenwachtrij is niet bereikbaar. "
                  "Probeer het later opnieuw.",
    "cancel_final": "Deze analyse is al afgerond (status: {status}) en kan niet meer worden geannuleerd.",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_customer(db: Session, customer_id: str) -> CustomerWebsite:
    customer = db.get(CustomerWebsite, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_CUSTOMER)
    return customer


def _get_analysis(db: Session, analysis_id: str) -> CompetitorAnalysis:
    analysis = db.get(CompetitorAnalysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_ANALYSIS)
    return analysis


def _keywords(db: Session, analysis_id: str) -> list[CompetitorAnalysisKeyword]:
    return (
        db.query(CompetitorAnalysisKeyword)
        .filter(CompetitorAnalysisKeyword.analysis_id == analysis_id)
        .order_by(CompetitorAnalysisKeyword.sort_order.asc(), CompetitorAnalysisKeyword.id.asc())
        .all()
    )


def _brief_statuses(db: Session, analysis_id: str) -> dict[str, str]:
    """`keyword_id` → status van de content brief, voor het label van de briefknop."""
    rows = db.query(ContentBrief.keyword_id, ContentBrief.status).filter(ContentBrief.analysis_id == analysis_id)
    return {keyword_id: status for keyword_id, status in rows}


def _detail(db: Session, analysis: CompetitorAnalysis) -> AnalysisDetail:
    return to_analysis_detail(analysis, _keywords(db, analysis.id), _brief_statuses(db, analysis.id))


# --- voorstel ----------------------------------------------------------------------------

@router.get("/customers/{customer_id}/proposal", response_model=ProposalResponse)
def get_proposal(
    customer_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Voorstel voor de wizard: zoekwoorden (PRT + bewaarde quick wins), doelpagina's, bronnen
    en tarieven. Geen betaalde aanroep. Synchrone functie (threadpool), want PRT en Ahrefs
    worden live bevraagd; een trage of falende bron geeft een `state` met melding."""
    customer = _get_customer(db, customer_id)
    return proposal.build_proposal(db, customer)


# --- starten -----------------------------------------------------------------------------

def _validated_targets(payload: AnalysisCreateRequest, host: str) -> list[str | None]:
    """Genormaliseerde doel-URL's per zoekwoord; 400 bij een ongeldige of externe URL."""
    targets: list[str | None] = []
    for item in payload.keywords:
        if item.target_url is None:
            targets.append(None)
            continue
        if not host:
            raise HTTPException(status_code=400, detail=MESSAGES["no_site"])
        url = proposal.normalize_url(item.target_url)
        if url is None:
            raise HTTPException(status_code=400, detail=MESSAGES["invalid_url"].format(url=item.target_url))
        if not proposal.on_domain(url, host):
            raise HTTPException(status_code=400, detail=MESSAGES["off_domain"].format(url=item.target_url, host=host))
        targets.append(url)
    return targets


def _validate_keywords(payload: AnalysisCreateRequest) -> None:
    maximum = settings.competitor_analysis_max_keywords
    if len(payload.keywords) > maximum:
        raise HTTPException(
            status_code=400, detail=MESSAGES["too_many"].format(max=maximum, count=len(payload.keywords)))
    seen: set[str] = set()
    for item in payload.keywords:
        key = keyword_key(item.keyword)
        if key in seen:
            raise HTTPException(status_code=400, detail=MESSAGES["duplicate"].format(keyword=item.keyword))
        seen.add(key)


@router.post("/customers/{customer_id}/analyses", response_model=AnalysisDetail)
def start_analysis(
    customer_id: str,
    payload: AnalysisCreateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Maakt de run en de zoekwoordrijen aan, bewaart de schatting en start de taak.

    Eigen positie en volume komen uit het voorstel (PRT live + bewaarde quick wins) als ze
    bekend zijn. Synchrone functie (threadpool), want PRT wordt live bevraagd.
    """
    from app.worker.tasks import run_competitor_analysis_task  # voorkom circulaire import

    customer = _get_customer(db, customer_id)
    if not ahrefs.is_configured():
        raise HTTPException(status_code=400, detail=MESSAGES["ahrefs"])
    _validate_keywords(payload)
    targets = _validated_targets(payload, proposal.customer_host(customer))

    recover_customer_runs(db, customer.id)
    running = (
        db.query(CompetitorAnalysis.id)
        .filter(
            CompetitorAnalysis.customer_website_id == customer.id,
            CompetitorAnalysis.status.in_(ACTIVE_STATUSES),
        )
        .first()
    )
    if running is not None:
        raise HTTPException(status_code=409, detail=MESSAGES["running"])

    known = proposal.keyword_data(db, customer)
    by_key = known.by_key()
    modules = list(payload.modules)
    plan: Estimate = estimate.estimate(
        keywords=len(payload.keywords),
        top_n=payload.top_n,
        own_urls=sum(1 for url in targets if url),
        modules=modules,
        ai_configured=anthropic_client.is_configured(),
    )

    now = _now()
    analysis = CompetitorAnalysis(
        id=str(uuid.uuid4()),
        customer_website_id=customer.id,
        created_by=user_id,
        status="pending",
        warnings=[],
        country=payload.country,
        top_n=payload.top_n,
        exclude_aggregators=payload.exclude_aggregators,
        modules=modules,
        total_keywords=len(payload.keywords),
        done_keywords=0,
        total_pages=0,
        fetched_pages=0,
        failed_pages=0,
        vitals_total=0,
        vitals_measured=0,
        ahrefs_units=0,
        estimate=plan.model_dump(mode="json"),
        sources=proposal.sources_without_ahrefs_call(known.prt).model_dump(mode="json"),
        created_at=now,
        updated_at=now,
    )
    db.add(analysis)
    for index, (item, target) in enumerate(zip(payload.keywords, targets)):
        key = keyword_key(item.keyword)
        hint = by_key.get(key)
        db.add(CompetitorAnalysisKeyword(
            id=str(uuid.uuid4()),
            analysis_id=analysis.id,
            sort_order=index,
            keyword=item.keyword,
            keyword_key=key,
            target_url=target,
            own_position=hint.position if hint is not None else None,
            own_position_source=hint.source if hint is not None and hint.position is not None else None,
            volume=hint.volume if hint is not None else None,
            status="pending",
            created_at=now,
            updated_at=now,
        ))
    db.commit()

    try:
        run_competitor_analysis_task.delay(analysis.id)
    except Exception as exc:  # noqa: BLE001 - bijv. Redis niet bereikbaar
        logger.exception("Concurrentieanalyse %s niet ingepland", analysis.id)
        analysis.status = "failed"
        analysis.error_message = MESSAGES["not_queued"]
        analysis.updated_at = _now()
        db.commit()
        raise HTTPException(status_code=503, detail=MESSAGES["not_queued"]) from exc

    db.refresh(analysis)
    return _detail(db, analysis)


# --- lijst en volgen ---------------------------------------------------------------------

@router.get("/customers/{customer_id}/analyses", response_model=AnalysisListResponse)
async def list_analyses(
    customer_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Analyses van de klant, nieuwste eerst. Vastgelopen runs worden eerst hersteld."""
    _get_customer(db, customer_id)
    recover_customer_runs(db, customer_id)
    analyses = (
        db.query(CompetitorAnalysis)
        .filter(CompetitorAnalysis.customer_website_id == customer_id)
        .order_by(CompetitorAnalysis.created_at.desc(), CompetitorAnalysis.id.desc())
        .limit(limit)
        .all()
    )
    keywords: dict[str, list[CompetitorAnalysisKeyword]] = {a.id: [] for a in analyses}
    if analyses:
        rows = (
            db.query(CompetitorAnalysisKeyword)
            .filter(CompetitorAnalysisKeyword.analysis_id.in_(list(keywords)))
            .order_by(CompetitorAnalysisKeyword.sort_order.asc(), CompetitorAnalysisKeyword.id.asc())
            .all()
        )
        for row in rows:
            keywords[row.analysis_id].append(row)
    return AnalysisListResponse(items=[to_list_item(a, keywords[a.id]) for a in analyses])


@router.get("/analyses/{analysis_id}", response_model=AnalysisDetail)
async def get_analysis(
    analysis_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Status, tellers en zoekwoorden; licht genoeg om elke 3 seconden te pollen.

    Herstelt eerst een vastgelopen run (dan 'failed' met een melding)."""
    analysis = _get_analysis(db, analysis_id)
    recover_stale_run(db, analysis)
    return _detail(db, analysis)


@router.get("/analyses/{analysis_id}/keywords/{keyword_id}", response_model=KeywordDetail)
async def get_keyword(
    analysis_id: str,
    keyword_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Volledig resultaat van één zoekwoord, ook halverwege de run (dan deels leeg)."""
    _get_analysis(db, analysis_id)
    keyword = db.get(CompetitorAnalysisKeyword, keyword_id)
    if keyword is None or keyword.analysis_id != analysis_id:
        raise HTTPException(status_code=404, detail=NOT_FOUND_KEYWORD)
    pages = (
        db.query(CompetitorAnalysisPage)
        .filter(CompetitorAnalysisPage.keyword_id == keyword.id)
        .all()
    )
    actions = (
        db.query(CompetitorAnalysisAction)
        .filter(CompetitorAnalysisAction.keyword_id == keyword.id)
        .order_by(CompetitorAnalysisAction.sort_order.asc(), CompetitorAnalysisAction.id.asc())
        .all()
    )
    return to_keyword_detail(keyword, pages, actions, user_names(db, actions))


@router.post("/analyses/{analysis_id}/cancel", response_model=AnalysisDetail)
async def cancel_analysis(
    analysis_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Zet een actieve run op 'canceled'; de taak stopt bij de volgende stap.

    Een afgeronde run (ook een run die net als vastgelopen is hersteld) blijft ongewijzigd: 409.
    """
    analysis = _get_analysis(db, analysis_id)
    recover_stale_run(db, analysis)
    if analysis.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail=MESSAGES["cancel_final"].format(status=analysis.status))
    analysis.status = "canceled"
    analysis.updated_at = _now()
    db.commit()
    return _detail(db, analysis)


# --- verbeterpunten ----------------------------------------------------------------------

@router.patch("/actions/{action_id}", response_model=ActionItem)
async def update_action(
    action_id: str,
    payload: ActionUpdate,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Verbeterpunt afvinken (`done`, `done_by`, `done_at`) of weer openzetten (beide leeg).

    Nogmaals afvinken laat de oorspronkelijke afvinker en het tijdstip staan."""
    action = db.get(CompetitorAnalysisAction, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_ACTION)
    if bool(action.done) != payload.done:
        now = _now()
        action.done = payload.done
        action.done_by = user_id if payload.done else None
        action.done_at = now if payload.done else None
        action.updated_at = now
        db.commit()
    return to_action_item(action, user_names(db, [action]))
