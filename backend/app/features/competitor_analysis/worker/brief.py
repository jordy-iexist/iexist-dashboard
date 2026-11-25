"""Celery-task: content brief en concepttekst voor één zoekwoord van een concurrentieanalyse.

Statussen op `content_briefs` (eigen tabel, los van `competitor_analyses`):
- volledig: pending → brief → concept → completed;
- alleen het concept (`concept_only`, of er staat al een brief): pending → concept → completed;
- bij een fout: failed met een melding. Wat al klaar was (de brief, het vorige concept) blijft
  staan, zodat een nieuwe poging vanaf de mislukte stap verder kan.

1. Atomair claimen: alleen een rij op `pending` wordt opgepakt (de taak kan na een
   worker-herstart opnieuw worden afgeleverd; dan niets doen).
2. De invoer komt uit de database (`_load_input`): zoekwoord, paginarijen met on-page,
   onderwerpen, verbeterpunten, klantprofiel en de sitemap van de klant.
3. Aanroep 1 (`write_brief`) en aanroep 2 (`write_concept`) uit `services/brief_agent.py`.
   Het verbruik telt op in `ai_usage` (`add_usage` met het model dat werkelijk antwoordde).

Geen sleutels, prompts of paginagegevens in logregels en foutmeldingen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from app.db.models import (
    CompetitorAnalysis,
    CompetitorAnalysisAction,
    CompetitorAnalysisKeyword,
    CompetitorAnalysisPage,
    ContentBrief,
    CustomerWebsite,
    LaunchSitemapSnapshot,
)
from app.db.session import SessionLocal
from app.features.competitor_analysis.mappers import _model, _models, _strings
from app.features.competitor_analysis.schemas import (
    ACTIVE_BRIEF_STATUSES,
    AiOverview,
    AiUsage,
    Brief,
    Concept,
    MissingTopic,
    OnPage,
    Paa,
    TopicCoverage,
)
from app.features.competitor_analysis.services.brief_agent import (
    BriefInput,
    Customer,
    link_candidates,
    write_brief,
    write_concept,
)
from app.features.competitor_analysis.services.insights import NOT_CONFIGURED_MESSAGE, add_usage
from app.features.customers.profile import parse_profile
from app.features.customers.rankings import host_of
from app.services.anthropic.client import AnthropicServiceError
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)

TIMEOUT_MESSAGE = "Het schrijven duurde te lang en is afgebroken. Probeer het opnieuw."
NO_BRIEF_MESSAGE = "Er is nog geen brief om een concept op te baseren; maak eerst de brief."
GONE_MESSAGE = "Het zoekwoord of de analyse bestaat niet meer."


class _Failed(Exception):
    """De run kan niet verder; de tekst is de melding voor de gebruiker."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- database ------------------------------------------------------------------------------


def _claim(brief_id: str, concept_only: bool) -> str | None:
    """`pending` → `brief` (of `concept` als er al een brief is of `concept_only`), in één update.

    Geeft de stap terug, of None als de rij niet bestaat of niet (meer) op `pending` staat.
    """
    with SessionLocal() as db:
        row = db.get(ContentBrief, brief_id)
        if row is None or row.status != "pending":
            return None
        stage = "concept" if concept_only or row.brief is not None else "brief"
        count = db.query(ContentBrief).filter(
            ContentBrief.id == brief_id, ContentBrief.status == "pending",
        ).update({"status": stage, "error_message": None, "updated_at": _now()}, synchronize_session=False)
        db.commit()
        return stage if count == 1 else None


def _update(brief_id: str, **fields: Any) -> None:
    """Werk de brief bij (altijd `updated_at`), maar alleen zolang hij actief is."""
    fields["updated_at"] = _now()
    with SessionLocal() as db:
        db.query(ContentBrief).filter(
            ContentBrief.id == brief_id, ContentBrief.status.in_(ACTIVE_BRIEF_STATUSES),
        ).update(fields, synchronize_session=False)
        db.commit()


def _page_view(row: CompetitorAnalysisPage) -> SimpleNamespace:
    """Paginarij los van de sessie, met een gecontroleerde `onpage` (ongeldig wordt leeg)."""
    columns = {c.key: getattr(row, c.key) for c in CompetitorAnalysisPage.__table__.columns}
    columns["onpage"] = _model(OnPage, row.onpage)
    return SimpleNamespace(**columns)


def _load(brief_id: str) -> tuple[BriefInput, Brief | None, Concept | None, AiUsage]:
    """Invoer voor de agent, de bestaande brief en het vorige concept, en het verbruik tot nu toe."""
    with SessionLocal() as db:
        row = db.get(ContentBrief, brief_id)
        keyword = db.get(CompetitorAnalysisKeyword, row.keyword_id) if row is not None else None
        analysis = db.get(CompetitorAnalysis, row.analysis_id) if row is not None else None
        if row is None or keyword is None or analysis is None:
            raise _Failed(GONE_MESSAGE)
        customer = db.get(CustomerWebsite, row.customer_website_id)
        pages = [
            _page_view(p)
            for p in db.query(CompetitorAnalysisPage).filter(CompetitorAnalysisPage.keyword_id == keyword.id).all()
        ]
        actions = (
            db.query(CompetitorAnalysisAction)
            .filter(CompetitorAnalysisAction.keyword_id == keyword.id)
            .order_by(CompetitorAnalysisAction.sort_order.asc(), CompetitorAnalysisAction.id.asc())
            .all()
        )
        snapshot = db.get(LaunchSitemapSnapshot, row.customer_website_id)
        entries = snapshot.entries if snapshot is not None and isinstance(snapshot.entries, dict) else {}

        paa = _model(Paa, keyword.paa)
        overview = _model(AiOverview, keyword.ai_overview)
        if overview is not None and overview.state == "empty":
            overview = AiOverview(state="ok", sources=[], own_cited=None)
        topics = None if keyword.topics is None else _models(TopicCoverage, keyword.topics)
        base_url = (customer.base_url if customer else "") or ""
        inp = BriefInput(
            keyword=keyword.keyword,
            customer=Customer(
                name=(customer.name if customer else "") or "",
                domain=host_of(base_url) or (customer.domain if customer else None) or None,
                seo_goals=customer.seo_goals if customer else None,
                tone_of_voice=customer.tone_of_voice if customer else None,
                form_of_address=customer.form_of_address if customer else None,
                profile=parse_profile(customer.profile if customer else None),
            ),
            pages=pages,
            target_url=keyword.target_url,
            country=analysis.country,
            volume=keyword.volume,
            kd=keyword.kd,
            intents=_strings(keyword.intents),
            serp_features=_strings(keyword.serp_features),
            serp_summary=keyword.serp_summary,
            search_intent=keyword.search_intent,
            paa=paa.questions if paa is not None else [],
            ai_overview=overview,
            topics=topics,
            missing_topics=_models(MissingTopic, keyword.missing_topics),
            actions=[SimpleNamespace(title=a.title, description=a.description) for a in actions],
            link_paths=link_candidates(entries, keyword=keyword.keyword, target_url=keyword.target_url),
        )
        return inp, _model(Brief, row.brief), _model(Concept, row.concept), _model(AiUsage, row.ai_usage) or AiUsage()


def _fail(brief_id: str, message: str) -> None:
    try:
        _update(brief_id, status="failed", error_message=message[:1000])
    except Exception:  # noqa: BLE001 - laatste poging; niets meer aan te doen
        logger.exception("Content brief %s: status 'failed' niet opgeslagen", brief_id)


# --- de taak -------------------------------------------------------------------------------


def _run(brief_id: str, stage: str) -> None:
    inp, brief, previous, usage = _load(brief_id)

    if stage == "brief":
        result = write_brief(inp)
        if result.state != "ok" or result.brief is None:
            raise _Failed(result.message or NOT_CONFIGURED_MESSAGE)
        brief = result.brief
        usage = add_usage(usage, result.usage, result.model)
        _update(brief_id, status="concept", brief=brief.model_dump(mode="json"), model=result.model,
                ai_usage=usage.model_dump(mode="json"))
    if brief is None:
        raise _Failed(NO_BRIEF_MESSAGE)

    version = (previous.version + 1) if previous is not None else 1
    result = write_concept(inp, brief, version=version)
    if result.state != "ok" or result.concept is None:
        raise _Failed(result.message or NOT_CONFIGURED_MESSAGE)
    usage = add_usage(usage, result.usage, result.model)
    _update(brief_id, status="completed", concept=result.concept.model_dump(mode="json"), model=result.model,
            ai_usage=usage.model_dump(mode="json"), error_message=None, completed_at=_now())


@celery_app.task(
    bind=True,
    name="app.worker.tasks.run_content_brief_task",
    soft_time_limit=540,
    time_limit=600,
)
def run_content_brief_task(self, brief_id: str, concept_only: bool = False) -> str:
    """Schrijft de content brief en/of de concepttekst (zie de module-docstring)."""
    stage = _claim(brief_id, concept_only)
    if stage is None:
        logger.info("Content brief %s niet gestart: niet gevonden of niet meer 'pending'.", brief_id)
        return brief_id
    try:
        _run(brief_id, stage)
    except SoftTimeLimitExceeded:
        logger.warning("Content brief %s: tijdslimiet bereikt.", brief_id)
        _fail(brief_id, TIMEOUT_MESSAGE)
    except AnthropicServiceError as exc:
        logger.warning("Content brief %s: Claude-fout (%s)", brief_id, exc.code)
        _fail(brief_id, f"Claude gaf een fout: {exc.message}")
    except _Failed as exc:
        logger.warning("Content brief %s mislukt: %s", brief_id, exc)
        _fail(brief_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Content brief %s onverwacht mislukt", brief_id)
        _fail(brief_id, f"Het schrijven is gestopt door een interne fout ({type(exc).__name__}).")
    return brief_id
