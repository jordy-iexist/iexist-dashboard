"""Modellen van de concurrentieanalyse omzetten naar de schema's van `/api/competitor-analyses`.

Pure functies (behalve `user_names`, dat namen opzoekt). Verdraagzaam voor lege of onvolledige
JSON-kolommen: een run die halverwege is heeft nog geen `onpage`, `page_type`, `paa`, enz.,
en een onverwachte waarde in een kolom wordt `None` in plaats van een fout. Zo geeft elk
endpoint in elke fase van de run een geldig antwoord.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable, TypeVar, get_args

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.db.models import (
    CompetitorAnalysis,
    CompetitorAnalysisAction,
    CompetitorAnalysisKeyword,
    CompetitorAnalysisPage,
    User,
)
from app.features.competitor_analysis.schemas import (
    ALL_MODULES,
    ActionItem,
    AiOverview,
    AiState,
    AiUsage,
    AnalysisDetail,
    AnalysisListItem,
    Cwv,
    Eeat,
    Estimate,
    ExcludeReason,
    FetchStatus,
    KeywordDetail,
    KeywordStatus,
    KeywordSummary,
    Level,
    MissingTopic,
    OnPage,
    OwnPageRow,
    Paa,
    PageRow,
    PageType,
    PositionSource,
    Sources,
)
from app.features.competitor_analysis.services import comparison, page_facts
from app.features.customers.rankings import host_of

M = TypeVar("M", bound=BaseModel)


# --- hulpfuncties ----------------------------------------------------------------------

def _model(model: type[M], value: Any) -> M | None:
    """`model.model_validate(value)`; `None` bij een lege of ongeldige waarde."""
    if value is None or value == {}:
        return None
    try:
        return model.model_validate(value)
    except ValidationError:
        return None


def _choice(value: Any, literal: Any) -> Any:
    """De waarde als hij in het Literal-type voorkomt, anders `None`."""
    return value if value in get_args(literal) else None


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float)) and str(item).strip()]


def _models(model: type[M], value: Any) -> list[M]:
    if not isinstance(value, list):
        return []
    return [item for item in (_model(model, raw) for raw in value) if item is not None]


def _modules(value: Any) -> list[str]:
    values = value if isinstance(value, list) else []
    return [module for module in ALL_MODULES if module in values]


def _position_key(page: CompetitorAnalysisPage) -> tuple:
    return (page.position is None, page.position or 0, page.url or "")


# --- run -------------------------------------------------------------------------------

def to_keyword_summary(keyword: CompetitorAnalysisKeyword) -> KeywordSummary:
    return KeywordSummary(
        id=keyword.id,
        keyword=keyword.keyword,
        target_url=keyword.target_url,
        status=_choice(keyword.status, KeywordStatus) or "pending",
        error_message=keyword.error_message,
        own_position=keyword.own_position,
        volume=keyword.volume,
        kd=keyword.kd,
        ai_state=_choice(keyword.ai_state, AiState),
    )


def to_list_item(analysis: CompetitorAnalysis, keywords: list[CompetitorAnalysisKeyword]) -> AnalysisListItem:
    """`keywords` in `sort_order`."""
    return AnalysisListItem(
        id=analysis.id,
        status=analysis.status,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
        top_n=analysis.top_n,
        keywords=[k.keyword for k in keywords],
        total_keywords=analysis.total_keywords or len(keywords),
    )


def to_analysis_detail(analysis: CompetitorAnalysis, keywords: list[CompetitorAnalysisKeyword]) -> AnalysisDetail:
    """`keywords` in `sort_order`."""
    return AnalysisDetail(
        id=analysis.id,
        customer_website_id=analysis.customer_website_id,
        status=analysis.status,
        error_message=analysis.error_message,
        warnings=_strings(analysis.warnings),
        country=analysis.country,
        top_n=analysis.top_n,
        exclude_aggregators=bool(analysis.exclude_aggregators),
        modules=_modules(analysis.modules),
        total_keywords=analysis.total_keywords or 0,
        done_keywords=analysis.done_keywords or 0,
        total_pages=analysis.total_pages or 0,
        fetched_pages=analysis.fetched_pages or 0,
        failed_pages=analysis.failed_pages or 0,
        vitals_total=analysis.vitals_total or 0,
        vitals_measured=analysis.vitals_measured or 0,
        sources=_model(Sources, analysis.sources) or Sources(),
        estimate=_model(Estimate, analysis.estimate),
        ahrefs_units=analysis.ahrefs_units or 0,
        ai_usage=_model(AiUsage, analysis.ai_usage),
        created_by=analysis.created_by,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
        completed_at=analysis.completed_at,
        keywords=[to_keyword_summary(k) for k in keywords],
    )


# --- resultaat per zoekwoord -----------------------------------------------------------

def _lcp_ms(page: CompetitorAnalysisPage, cwv: Cwv | None) -> int | None:
    """De scalaire kolom; anders de waarde uit `cwv`."""
    if page.lcp_ms is not None:
        return page.lcp_ms
    return cwv.lcp_ms if cwv is not None else None


def _page_fields(page: CompetitorAnalysisPage) -> dict[str, Any]:
    onpage = _model(OnPage, page.onpage)
    cwv = _model(Cwv, page.cwv)
    lcp_ms = _lcp_ms(page, cwv)
    return {
        "id": page.id,
        "position": page.position,
        "url": page.url,
        "domain": page.domain or host_of(page.url) or None,
        "serp_title": page.serp_title,
        "page_type": _choice(page.page_type, PageType),
        "is_excluded": bool(page.is_excluded),
        "exclude_reason": _choice(page.exclude_reason, ExcludeReason),
        "fetch_status": _choice(page.fetch_status, FetchStatus),
        "fetch_error": page.fetch_error,
        "words": onpage.word_count if onpage is not None else None,
        "h2_count": onpage.h2_count if onpage is not None else None,
        "has_faq": onpage.has_faq if onpage is not None else None,
        # Zelfde types als waar de mediaan en de rode vlag mee rekenen (zonder generieke types).
        "schema_types": comparison.content_schema_types(onpage.schema_types) if onpage is not None else [],
        "refdomains": page.refdomains,
        "domain_rating": page.domain_rating,
        "lcp_ms": lcp_ms,
        "lcp_error": cwv.error if cwv is not None else None,
        "eeat": _model(Eeat, page.eeat),
        "unreadable": page_facts.is_unreadable(onpage),
    }


def _comparison_view(page: CompetitorAnalysisPage) -> SimpleNamespace:
    """De paginarij voor `comparison`, met een gecontroleerde `onpage` (ongeldig wordt leeg)."""
    return SimpleNamespace(
        id=page.id, is_own=bool(page.is_own), position=page.position, url=page.url,
        domain=page.domain, page_type=page.page_type, is_excluded=bool(page.is_excluded),
        exclude_reason=page.exclude_reason, fetch_status=page.fetch_status,
        onpage=_model(OnPage, page.onpage), refdomains=page.refdomains,
        domain_rating=page.domain_rating, lcp_ms=_lcp_ms(page, _model(Cwv, page.cwv)),
    )


def to_page_row(page: CompetitorAnalysisPage) -> PageRow:
    return PageRow(**_page_fields(page))


def to_action_item(action: CompetitorAnalysisAction, names: dict[str, str]) -> ActionItem:
    return ActionItem(
        id=action.id,
        title=action.title,
        description=action.description,
        impact=_choice(action.impact, Level),
        effort=_choice(action.effort, Level),
        category=action.category if action.category in ALL_MODULES else None,
        done=bool(action.done),
        done_by_name=names.get(action.done_by) if action.done and action.done_by else None,
        done_at=action.done_at if action.done else None,
    )


def to_keyword_detail(
    keyword: CompetitorAnalysisKeyword,
    pages: Iterable[CompetitorAnalysisPage],
    actions: Iterable[CompetitorAnalysisAction],
    names: dict[str, str],
) -> KeywordDetail:
    """Volledig resultaat van één zoekwoord; de mediaanrij en vlaggen worden hier berekend.

    `pages`: alle paginarijen van het zoekwoord (concurrenten en de eigen pagina).
    Concurrenten op positie (zonder positie achteraan); verbeterpunten op `sort_order`.
    `own` is `None` zonder doelpagina of zolang de rij van de eigen pagina nog niet bestaat.
    """
    pages = list(pages)
    competitors = [to_page_row(p) for p in sorted((p for p in pages if not p.is_own), key=_position_key)]
    own_page = next((p for p in sorted(pages, key=_position_key) if p.is_own), None)
    views = {p.id: _comparison_view(p) for p in pages}
    median = comparison.median_row(views.values())
    own = None
    if own_page is not None and keyword.target_url:
        own = OwnPageRow(
            **to_page_row(own_page).model_dump(),
            flags=comparison.flags(views[own_page.id], median),
        )
    ordered_actions = sorted(actions, key=lambda a: (a.sort_order or 0, a.created_at is None, a.id))
    return KeywordDetail(
        id=keyword.id,
        analysis_id=keyword.analysis_id,
        keyword=keyword.keyword,
        target_url=keyword.target_url,
        status=_choice(keyword.status, KeywordStatus) or "pending",
        error_message=keyword.error_message,
        own_position=keyword.own_position,
        own_position_source=_choice(keyword.own_position_source, PositionSource),
        volume=keyword.volume,
        kd=keyword.kd,
        intents=_strings(keyword.intents),
        serp_features=_strings(keyword.serp_features),
        serp_date=keyword.serp_date,
        serp_summary=keyword.serp_summary,
        search_intent=keyword.search_intent,
        ai_state=_choice(keyword.ai_state, AiState),
        ai_error=keyword.ai_error,
        pages=competitors,
        own=own,
        median=median,
        actions=[to_action_item(a, names) for a in ordered_actions],
        missing_topics=_models(MissingTopic, keyword.missing_topics),
        paa=_model(Paa, keyword.paa),
        ai_overview=_model(AiOverview, keyword.ai_overview),
    )


# --- namen -----------------------------------------------------------------------------

def user_names(db: Session, actions: Iterable[CompetitorAnalysisAction]) -> dict[str, str]:
    """Weergavenaam per gebruiker bij `done_by`: het deel van het e-mailadres vóór de @."""
    ids = {a.done_by for a in actions if a.done_by}
    if not ids:
        return {}
    return {
        user_id: (email or "").split("@", 1)[0] or None
        for user_id, email in db.query(User.id, User.email).filter(User.id.in_(ids))
    }
