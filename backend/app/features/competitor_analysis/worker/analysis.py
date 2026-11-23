"""Celery-task: concurrentieanalyse per klant.

Stappen (status op `competitor_analyses`): serp → fetching → analyzing → completed.

1. Start alleen bij status `pending` (de taak kan na een worker-herstart opnieuw worden
   afgeleverd; dan niets doen, zodat er geen Ahrefs-units dubbel worden besteed).
2. `serp`: per zoekwoord het SERP-overzicht van Ahrefs, één `keywords_overview` voor alle
   zoekwoorden samen, en DR/RD van eigen doelpagina's buiten de top N (`url_metrics`).
   Daarna de paginarijen. Een fout op één zoekwoord laat alleen dat zoekwoord mislukken.
3. PageSpeed (module `tech`) start daarna op de achtergrond met een hard budget.
4. `fetching`: elke unieke URL één keer ophalen en uitlezen, met één browser-herkansing voor
   geblokkeerde pagina's en voor pagina's zonder leesbare tekst (met JavaScript opgebouwd).
   De paginatekst blijft in het geheugen voor stap 5.
5. `analyzing`: aanroep A (pagina-indeling, aggregators uitsluiten) en aanroep B per
   zoekwoord (drie tegelijk).
6. Afronden: wachten op PageSpeed binnen het resterende budget en `completed`.

De stappen zelf staan in `services/pipeline.py`; dit bestand is de regie en de enige plek die
de database schrijft. Achtergrondthreads (ophalen, Claude) raken de database niet; de
PageSpeed-thread schrijft zijn metingen met een eigen sessie, net als in `launch_scan.py`.
Tussen de stappen en in lange lussen wordt gecontroleerd of de run nog actief is (annuleren);
`updated_at` loopt mee via `_update` en `heartbeat`, zodat `services/recovery.py` een levende
run niet als vastgelopen ziet.

In logregels en foutmeldingen staan geen sleutels, prompts of paginateksten.
"""
from __future__ import annotations

import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable

from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from app.core.config import settings
from app.db.models import (
    CompetitorAnalysis,
    CompetitorAnalysisAction,
    CompetitorAnalysisKeyword,
    CompetitorAnalysisPage,
    CustomerWebsite,
)
from app.db.session import SessionLocal
from app.features.competitor_analysis.schemas import (
    ACTIVE_STATUSES,
    AiOverview,
    AiUsage,
    Cwv,
    Sources,
    SourceStatus,
)
from app.features.competitor_analysis.services import pipeline
from app.features.competitor_analysis.services.estimate import runs_analysis
from app.features.competitor_analysis.services.google_serp import BrowserSession
from app.features.competitor_analysis.services.insights import (
    NOT_CONFIGURED_MESSAGE,
    KeywordInsights,
    add_usage,
    analyze_keyword,
    classify_pages,
)
from app.features.customers.rankings import host_of, keyword_key
from app.features.launch_checklist.services.discovery import root_domain_of
from app.features.launch_checklist.services.scan_recovery import heartbeat
from app.services.ahrefs import client as ahrefs
from app.services.ahrefs.client import SERP_EXTRA_POSITIONS, AhrefsServiceError
from app.services.anthropic import client as claude
from app.services.anthropic.client import AnthropicServiceError
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)

# Aanroep B: zoveel zoekwoorden tegelijk.
ANALYZE_CONCURRENCY = 3
# Zo vaak (seconden) kijkt de regie tijdens het wachten op threads of de run nog loopt.
POLL_SECONDS = 5.0

TIMEOUT_MESSAGE = "De analyse duurde te lang en is afgebroken; afgeronde zoekwoorden zijn bewaard."
NO_AGGREGATOR_EXCLUSION_WARNING = (
    "Claude is niet ingesteld: vergelijkingssites zijn niet uitgesloten en het paginatype komt "
    "grofweg uit Ahrefs."
)
PAGESPEED_NOT_CONFIGURED = "PAGESPEED_API_KEY ontbreekt: laadtijd (LCP) is niet gemeten."


class _Stopped(Exception):
    """De run staat niet meer op een actieve status (geannuleerd of hersteld): stil stoppen."""


class _RunFailed(Exception):
    """De run kan niet verder; de tekst is de melding voor de gebruiker."""


@dataclass
class _Keyword:
    id: str
    keyword: str
    target_url: str | None
    own_position: int | None
    volume: int | None
    failed: bool = False
    # Voor aanroep B (uit stap 2, in het geheugen).
    intents: list[str] = field(default_factory=list)
    serp_features: list[str] = field(default_factory=list)
    paa: list[str] = field(default_factory=list)
    ai_overview: AiOverview | None = None


@dataclass
class _Run:
    analysis_id: str
    country: str
    top_n: int
    exclude_aggregators: bool
    modules: list[str]
    customer_root: str | None
    customer_domain: str | None
    keywords: list[_Keyword]
    sources: Sources
    warnings: list[str]
    units: int = 0
    usage: AiUsage | None = None
    done_keywords: int = 0
    total_pages: int = 0
    fetched_pages: int = 0
    failed_pages: int = 0
    # Paginatekst per `url_key` (alleen in het geheugen, nooit opslaan of loggen).
    texts: dict[str, str] = field(default_factory=dict)
    vitals: pipeline.VitalsRunner | None = None
    claude_errors: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    def state_fields(self) -> dict[str, Any]:
        """De run-velden die de regie in het geheugen bijhoudt."""
        return {
            "warnings": list(self.warnings),
            "sources": self.sources.model_dump(mode="json"),
            "ahrefs_units": self.units,
            "ai_usage": self.usage.model_dump(mode="json") if self.usage else None,
            "done_keywords": self.done_keywords,
            "total_pages": self.total_pages,
            "fetched_pages": self.fetched_pages,
            "failed_pages": self.failed_pages,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- database ------------------------------------------------------------------------------


def _status(analysis_id: str) -> str:
    with SessionLocal() as db:
        row = db.query(CompetitorAnalysis.status).filter(CompetitorAnalysis.id == analysis_id).first()
        return "deleted" if row is None else str(row[0] or "").lower()


def _stopped(analysis_id: str) -> bool:
    """Geannuleerd, verwijderd of door het herstel al afgesloten."""
    return _status(analysis_id) not in ACTIVE_STATUSES


def _check(analysis_id: str) -> None:
    if _stopped(analysis_id):
        raise _Stopped()


def _update(analysis_id: str, **fields: Any) -> None:
    """Werk de run bij (altijd `updated_at`), maar alleen zolang hij actief is.

    Zo overschrijft de taak nooit een annulering of een afgesloten run.
    """
    fields["updated_at"] = _now()
    with SessionLocal() as db:
        db.query(CompetitorAnalysis).filter(
            CompetitorAnalysis.id == analysis_id,
            CompetitorAnalysis.status.in_(ACTIVE_STATUSES),
        ).update(fields, synchronize_session=False)
        db.commit()


def _claim(analysis_id: str) -> bool:
    """Zet `pending` → `serp` in één update; False als een andere aflevering hem al heeft."""
    with SessionLocal() as db:
        count = db.query(CompetitorAnalysis).filter(
            CompetitorAnalysis.id == analysis_id, CompetitorAnalysis.status == "pending",
        ).update({"status": "serp", "updated_at": _now()}, synchronize_session=False)
        db.commit()
        return count == 1


def _update_keyword(keyword_id: str, **fields: Any) -> None:
    fields["updated_at"] = _now()
    with SessionLocal() as db:
        db.query(CompetitorAnalysisKeyword).filter(CompetitorAnalysisKeyword.id == keyword_id).update(
            fields, synchronize_session=False
        )
        db.commit()


def _update_pages(page_ids: list[str], **fields: Any) -> None:
    if not page_ids:
        return
    fields["updated_at"] = _now()
    with SessionLocal() as db:
        db.query(CompetitorAnalysisPage).filter(CompetitorAnalysisPage.id.in_(page_ids)).update(
            fields, synchronize_session=False
        )
        db.commit()


def _page_rows(analysis_id: str) -> list[SimpleNamespace]:
    """Alle paginarijen van de run als losse objecten (los van een sessie, veilig voor threads)."""
    columns = [c.key for c in CompetitorAnalysisPage.__table__.columns]
    with SessionLocal() as db:
        rows = (
            db.query(CompetitorAnalysisPage)
            .filter(CompetitorAnalysisPage.analysis_id == analysis_id)
            .order_by(CompetitorAnalysisPage.keyword_id, CompetitorAnalysisPage.is_own,
                      CompetitorAnalysisPage.position, CompetitorAnalysisPage.id)
            .all()
        )
        return [SimpleNamespace(**{name: getattr(row, name) for name in columns}) for row in rows]


def _url_groups(analysis_id: str) -> dict[str, tuple[str, list[str]]]:
    """Per unieke URL (`url_key`): de URL en de id's van alle paginarijen met die URL."""
    groups: dict[str, tuple[str, list[str]]] = {}
    for row in _page_rows(analysis_id):
        url, ids = groups.setdefault(row.url_key, (row.url, []))
        ids.append(row.id)
    return groups


def _load(analysis_id: str) -> _Run | None:
    """De run en zijn zoekwoorden; None als de run niet bestaat of niet op `pending` staat."""
    with SessionLocal() as db:
        analysis = db.get(CompetitorAnalysis, analysis_id)
        if analysis is None or str(analysis.status or "").lower() != "pending":
            return None
        customer = db.get(CustomerWebsite, analysis.customer_website_id)
        base_url = (customer.base_url if customer else "") or ""
        try:
            sources = Sources.model_validate(analysis.sources or {})
        except ValueError:
            sources = Sources()
        keywords = (
            db.query(CompetitorAnalysisKeyword)
            .filter(CompetitorAnalysisKeyword.analysis_id == analysis_id)
            .order_by(CompetitorAnalysisKeyword.sort_order, CompetitorAnalysisKeyword.id)
            .all()
        )
        return _Run(
            analysis_id=analysis_id,
            country=analysis.country,
            top_n=int(analysis.top_n or 10),
            exclude_aggregators=bool(analysis.exclude_aggregators),
            modules=[m for m in (analysis.modules or []) if isinstance(m, str)],
            customer_root=root_domain_of(base_url) if base_url else None,
            customer_domain=host_of(base_url) or None,
            keywords=[
                _Keyword(id=k.id, keyword=k.keyword, target_url=k.target_url,
                         own_position=k.own_position, volume=k.volume)
                for k in keywords
            ],
            sources=sources,
            warnings=[str(w) for w in (analysis.warnings or [])],
        )


def _wait(pending: set[Future], analysis_id: str, beat: Callable[[], None]) -> tuple[set[Future], set[Future]]:
    """Wacht op het eerste klare resultaat; tussendoor levensteken en annuleringscontrole."""
    done, rest = wait(pending, timeout=POLL_SECONDS, return_when=FIRST_COMPLETED)
    beat()
    if not done:
        _check(analysis_id)
    return done, rest


# --- stap 2: SERP --------------------------------------------------------------------------


def _fail_keyword(run: _Run, keyword: _Keyword, message: str) -> None:
    keyword.failed = True
    run.done_keywords += 1
    _update_keyword(keyword.id, status="failed", error_message=message)
    _update(run.analysis_id, done_keywords=run.done_keywords)


def _save_serp(run: _Run, keyword: _Keyword, facts: pipeline.SerpFacts) -> None:
    now = _now()
    keyword.serp_features = list(facts.serp_features)
    keyword.paa = list(facts.paa.questions)
    keyword.ai_overview = facts.ai_overview
    with SessionLocal() as db:
        row = db.get(CompetitorAnalysisKeyword, keyword.id)
        row.serp_features = facts.serp_features
        row.paa = facts.paa.model_dump(mode="json")
        row.ai_overview = facts.ai_overview.model_dump(mode="json")
        row.serp_date = facts.serp_date
        if row.own_position is None and facts.own_rank is not None:
            row.own_position = facts.own_rank
            row.own_position_source = "ahrefs"
            keyword.own_position = facts.own_rank
        row.updated_at = now
        for spec in facts.pages:
            db.add(CompetitorAnalysisPage(
                id=str(uuid.uuid4()),
                keyword_id=keyword.id,
                analysis_id=run.analysis_id,
                is_own=spec.is_own,
                position=spec.position,
                url=spec.url,
                url_key=spec.url_key,
                domain=spec.domain,
                serp_title=spec.serp_title,
                ahrefs_page_type=spec.ahrefs_page_type,
                is_excluded=spec.is_excluded,
                exclude_reason=spec.exclude_reason,
                domain_rating=spec.domain_rating,
                refdomains=spec.refdomains,
                ahrefs=spec.ahrefs or None,
                created_at=now,
                updated_at=now,
            ))
        db.commit()


def _keywords_overview(run: _Run, keywords: list[_Keyword]) -> None:
    """Volume, KD en intenties voor alle geslaagde zoekwoorden in één aanroep."""
    try:
        result = ahrefs.keywords_overview([k.keyword for k in keywords], country=run.country)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - een verrijking: de run gaat door
        message = str(exc) if isinstance(exc, AhrefsServiceError) else type(exc).__name__
        logger.warning("Analyse %s: keywords_overview mislukt: %s", run.analysis_id, message)
        run.warnings.append(f"Volume, KD en intentie niet opgehaald: {message}")
        return
    run.units += result.units
    logger.info("Analyse %s: keywords_overview %d zoekwoorden, %d units", run.analysis_id, len(keywords), result.units)
    facts = pipeline.keyword_facts(result)
    for keyword in keywords:
        fact = facts.get(keyword_key(keyword.keyword))
        if fact is None:
            continue
        fields: dict[str, Any] = {"kd": fact.kd}
        if "serp" in run.modules:
            fields["intents"] = fact.intents
            keyword.intents = list(fact.intents)
        if keyword.volume is None and fact.volume is not None:
            fields["volume"] = fact.volume
            keyword.volume = fact.volume
        _update_keyword(keyword.id, **fields)


def _own_url_metrics(run: _Run) -> None:
    """DR en verwijzende domeinen van eigen doelpagina's buiten de top N, in één aanroep."""
    rows = [r for r in _page_rows(run.analysis_id) if r.is_own and r.position is None]
    urls = list(dict.fromkeys(r.url for r in rows))
    if not urls:
        return
    try:
        result = ahrefs.url_metrics(urls)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - een verrijking: de run gaat door
        message = str(exc) if isinstance(exc, AhrefsServiceError) else type(exc).__name__
        logger.warning("Analyse %s: url_metrics mislukt: %s", run.analysis_id, message)
        run.warnings.append(f"DR en verwijzende domeinen van de eigen pagina niet opgehaald: {message}")
        return
    run.units += result.units
    logger.info("Analyse %s: url_metrics %d URL's, %d units", run.analysis_id, len(urls), result.units)
    facts = pipeline.url_metric_facts(result)
    for row in rows:
        fact = facts.get(pipeline.loose_key(row.url))
        if fact is not None:
            _update_pages([row.id], domain_rating=fact[0], refdomains=fact[1])


def _step_serp(run: _Run) -> None:
    with_serp = "serp" in run.modules
    with_authority = "authority" in run.modules
    last_error: str | None = None
    for keyword in run.keywords:
        _check(run.analysis_id)
        try:
            result = ahrefs.serp_overview(
                keyword.keyword, country=run.country, top_positions=run.top_n + SERP_EXTRA_POSITIONS,
            )
        except SoftTimeLimitExceeded:
            raise
        except AhrefsServiceError as exc:
            if exc.code in pipeline.FATAL_AHREFS_CODES:
                run.sources.ahrefs = SourceStatus(state="error", message=str(exc))
                raise _RunFailed(str(exc)) from exc
            last_error = str(exc)
            _fail_keyword(run, keyword, f"Ahrefs gaf geen zoekresultaten: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - alleen dit zoekwoord
            logger.warning("Analyse %s: SERP-overzicht onverwacht mislukt (%s)", run.analysis_id, type(exc).__name__)
            last_error = f"onverwachte fout ({type(exc).__name__})"
            _fail_keyword(run, keyword, "Onverwachte fout bij het ophalen van de zoekresultaten.")
            continue
        run.units += result.units
        logger.info("Analyse %s: serp_overview %d rijen, %d units", run.analysis_id, len(result.rows), result.units)
        facts = pipeline.serp_facts(
            result, top_n=run.top_n, target_url=keyword.target_url, customer_root=run.customer_root,
            with_serp=with_serp, with_authority=with_authority,
        )
        _save_serp(run, keyword, facts)
        _update(run.analysis_id, ahrefs_units=run.units)

    succeeded = [k for k in run.keywords if not k.failed]
    if not succeeded:
        run.sources.ahrefs = SourceStatus(state="error", message=last_error)
        raise _RunFailed(
            "Ahrefs gaf voor geen enkel zoekwoord zoekresultaten" + (f": {last_error}" if last_error else ".")
        )
    _check(run.analysis_id)
    _keywords_overview(run, succeeded)
    if with_authority:
        _own_url_metrics(run)

    failed = len(run.keywords) - len(succeeded)
    run.sources.ahrefs = SourceStatus(
        state="ok",
        message=f"{failed} van de {len(run.keywords)} zoekwoorden mislukt." if failed else None,
    )
    run.total_pages = len(_page_rows(run.analysis_id))
    _update(run.analysis_id, **run.state_fields())


# --- stap 3: PageSpeed ---------------------------------------------------------------------


def _start_vitals(run: _Run) -> None:
    """Start PageSpeed op de achtergrond (alleen met module `tech` en een sleutel)."""
    if "tech" not in run.modules:
        run.sources.pagespeed = SourceStatus(state="skipped")
        return
    api_key = str(settings.pagespeed_api_key or "").strip()
    if not api_key:
        run.sources.pagespeed = SourceStatus(state="not_configured", message=PAGESPEED_NOT_CONFIGURED)
        return
    groups = _url_groups(run.analysis_id)
    if not groups:
        return
    analysis_id = run.analysis_id
    counter = {"measured": 0}

    def on_measured(key: str, cwv: Cwv) -> None:
        # Draait op de PageSpeed-thread: eigen sessies, nooit die van de regie.
        _update_pages(groups[key][1], lcp_ms=cwv.lcp_ms, cwv=cwv.model_dump(mode="json"))
        counter["measured"] += 1
        _update(analysis_id, vitals_measured=counter["measured"])

    run.vitals = pipeline.VitalsRunner(
        {key: url for key, (url, _ids) in groups.items()},
        api_key=api_key,
        concurrency=settings.launch_scan_psi_concurrency,
        budget_seconds=settings.competitor_analysis_vitals_budget_seconds,
        on_measured=on_measured,
        should_stop=lambda: _stopped(analysis_id),
    )
    _update(analysis_id, vitals_total=run.vitals.total, vitals_measured=0)
    run.vitals.start()


def _finish_vitals(run: _Run, beat: Callable[[], None]) -> None:
    """Wacht binnen het resterende budget; wat niet af is krijgt "niet op tijd gemeten"."""
    runner = run.vitals
    if runner is None:
        return
    while runner.is_alive() and runner.remaining() > 0:
        runner.join(min(POLL_SECONDS, runner.remaining()))
        beat()
        _check(run.analysis_id)
    pending = runner.finish(0)
    groups = _url_groups(run.analysis_id)
    late = [pid for key in pending if key in groups for pid in groups[key][1]]
    # Brak de meting af door een fout, dan is "niet op tijd" niet de reden.
    reason = pipeline.NOT_IN_TIME_MESSAGE if runner.error is None else "meting mislukt"
    _update_pages(late, lcp_ms=None, cwv=Cwv(error=reason).model_dump(mode="json"))

    measured, failed = len(runner.measured), len(runner.failed)
    if runner.error and not measured:
        run.sources.pagespeed = SourceStatus(state="error", message=runner.error)
    else:
        notes = []
        if pending:
            notes.append(f"{len(pending)} van de {runner.total} URL's niet op tijd gemeten")
        if failed:
            notes.append(f"{failed} meting(en) mislukt")
        if runner.error:
            notes.append(runner.error)
        run.sources.pagespeed = SourceStatus(state="ok", message="; ".join(notes) + "." if notes else None)
    _update(run.analysis_id, vitals_measured=measured)


# --- stap 4: ophalen -----------------------------------------------------------------------


def _save_fetch(run: _Run, key: str, page_ids: list[str], outcome: pipeline.FetchOutcome) -> None:
    _update_pages(
        page_ids,
        fetch_status=outcome.status,
        fetch_error=outcome.error,
        final_url=outcome.final_url,
        onpage=outcome.onpage.model_dump(mode="json") if outcome.onpage is not None else None,
    )
    if outcome.status == "ok" and outcome.text:
        run.texts[key] = outcome.text


def _retry_in_browser(
    run: _Run,
    groups: dict[str, tuple[str, list[str]]],
    outcomes: dict[str, pipeline.FetchOutcome],
    beat: Callable[[], None],
) -> None:
    """Eén herkansing via de browser (één sessie, in deze thread, na elkaar).

    Eerst de geblokkeerde pagina's, daarna pagina's die wel binnenkwamen maar zo weinig tekst
    hadden dat ze waarschijnlijk met JavaScript worden opgebouwd (`pipeline.is_thin`); de
    browser voert dat JavaScript uit. Samen hooguit `MAX_BROWSER_RETRIES`. De browser start
    alleen als er iets te herkansen valt.
    """
    blocked = [key for key, outcome in outcomes.items() if outcome.status == "blocked"]
    thin = [key for key, outcome in outcomes.items() if pipeline.is_thin(outcome)]
    candidates = (blocked + thin)[: pipeline.MAX_BROWSER_RETRIES]
    if not candidates:
        return
    if len(blocked) + len(thin) > pipeline.MAX_BROWSER_RETRIES:
        run.warnings.append(
            f"{len(blocked) + len(thin)} pagina's geblokkeerd of zonder leesbare tekst; alleen de eerste "
            f"{pipeline.MAX_BROWSER_RETRIES} kregen een herkansing via de browser."
        )
    with BrowserSession() as browser:
        if not browser.available:
            run.warnings.append(
                f"Herkansing via de browser niet mogelijk: {browser.start_error or 'geen browser'}"
            )
            return
        for key in candidates:
            _check(run.analysis_id)
            beat()
            url, page_ids = groups[key]
            before = outcomes[key]
            outcome: pipeline.FetchOutcome | None = None
            html = browser.page_html(url, timeout=pipeline.BROWSER_RETRY_TIMEOUT_SECONDS)
            if html:
                try:
                    outcome = pipeline.outcome_from_html(html, url)
                except SoftTimeLimitExceeded:
                    raise
                except Exception:  # noqa: BLE001 - dan blijft de eerste uitkomst staan
                    outcome = None
            if before.status == "blocked":
                if outcome is not None:
                    _save_fetch(run, key, page_ids, outcome)
                    run.failed_pages -= len(page_ids)
                    _update(run.analysis_id, failed_pages=run.failed_pages)
                else:
                    original = before.error or "Geweigerd door de website."
                    _update_pages(page_ids, fetch_error=f"{original} Ook via de browser niet gelukt.")
            elif outcome is not None and pipeline.richer(outcome, before):
                # Alleen vervangen als de browser echt meer tekst opleverde.
                _save_fetch(run, key, page_ids, outcome)


def _step_fetch(run: _Run, beat: Callable[[], None]) -> None:
    _update(run.analysis_id, status="fetching", fetched_pages=0, failed_pages=0)
    groups = _url_groups(run.analysis_id)
    outcomes: dict[str, pipeline.FetchOutcome] = {}
    # Geen `with`: bij een time-out of annulering niet wachten op pagina's die nog in de rij staan.
    pool = ThreadPoolExecutor(max_workers=settings.launch_scan_http_concurrency)
    try:
        futures = {pool.submit(pipeline.fetch_and_extract, url): key for key, (url, _ids) in groups.items()}
        pending = set(futures)
        while pending:
            done, pending = _wait(pending, run.analysis_id, beat)
            for future in done:
                key = futures[future]
                try:
                    outcome = future.result()
                except Exception as exc:  # noqa: BLE001 - `fetch_and_extract` gooit normaal niet
                    outcome = pipeline.FetchOutcome(status="error", error=f"Ophalen mislukt ({type(exc).__name__}).")
                outcomes[key] = outcome
                page_ids = groups[key][1]
                _save_fetch(run, key, page_ids, outcome)
                run.fetched_pages += len(page_ids)
                if outcome.status != "ok":
                    run.failed_pages += len(page_ids)
            if done:
                _update(run.analysis_id, fetched_pages=run.fetched_pages, failed_pages=run.failed_pages)
                _check(run.analysis_id)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    _retry_in_browser(run, groups, outcomes, beat)
    _update(run.analysis_id, fetched_pages=run.fetched_pages, failed_pages=run.failed_pages,
            warnings=list(run.warnings))


# --- stap 5: analyseren --------------------------------------------------------------------


def _classify(run: _Run, configured: bool) -> Any:
    """Aanroep A; None zonder sleutel of bij een fout (dan valt de indeling terug op Ahrefs)."""
    if not configured:
        return None
    _update(run.analysis_id)  # levensteken: de aanroep kan even duren
    try:
        result = classify_pages(_page_rows(run.analysis_id))
    except SoftTimeLimitExceeded:
        raise
    except AnthropicServiceError as exc:
        logger.warning("Analyse %s: pagina-indeling mislukt (%s)", run.analysis_id, exc.code)
        run.claude_errors.append(f"Pagina-indeling mislukt: {exc.message}")
        run.warnings.append(
            "De pagina-indeling door Claude is mislukt: vergelijkingssites zijn niet uitgesloten en het "
            "paginatype komt grofweg uit Ahrefs."
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Analyse %s: pagina-indeling onverwacht mislukt (%s)", run.analysis_id, type(exc).__name__)
        run.claude_errors.append("Pagina-indeling mislukt door een onverwachte fout.")
        return None
    if result.state == "ok":
        run.usage = add_usage(run.usage, result.usage, result.model)
        return result
    return None


def _apply_classification(run: _Run, result: Any) -> None:
    """Paginatype, aggregator en uitsluiting per rij; zonder indeling grofweg uit Ahrefs."""
    with SessionLocal() as db:
        rows = db.query(CompetitorAnalysisPage).filter(CompetitorAnalysisPage.analysis_id == run.analysis_id).all()
        now = _now()
        for row in rows:
            found = result.for_page(row) if result is not None else None
            if found is None:
                row.page_type = pipeline.page_type_from_ahrefs(row.ahrefs_page_type)
            else:
                row.page_type = found.page_type
                row.is_aggregator = found.is_aggregator
                row.ahrefs = {**(row.ahrefs or {}), "classify_reason": found.reason}
                if run.exclude_aggregators and found.is_aggregator and not row.is_own and not row.is_excluded:
                    row.is_excluded = True
                    row.exclude_reason = "aggregator"
            row.updated_at = now
        db.commit()


def _complete_keyword(run: _Run, keyword: _Keyword, **fields: Any) -> None:
    run.done_keywords += 1
    _update_keyword(keyword.id, status="completed", **fields)
    _update(run.analysis_id, done_keywords=run.done_keywords,
            ai_usage=run.usage.model_dump(mode="json") if run.usage else None)


def _save_insights(run: _Run, keyword: _Keyword, insights: KeywordInsights) -> None:
    now = _now()
    with SessionLocal() as db:
        row = db.get(CompetitorAnalysisKeyword, keyword.id)
        row.ai_state = insights.state
        row.ai_error = insights.message if insights.state == "skipped" else None
        if insights.state == "ok":
            row.serp_summary = insights.serp_summary
            row.search_intent = insights.search_intent
            if "topics" in run.modules:
                row.missing_topics = [t.model_dump(mode="json") for t in insights.missing_topics]
            if "eeat" in run.modules:
                for page_id, eeat in insights.eeat.items():
                    page = db.get(CompetitorAnalysisPage, page_id)
                    if page is not None and page.keyword_id == keyword.id:
                        page.eeat = eeat.model_dump(mode="json")
                        page.updated_at = now
            db.query(CompetitorAnalysisAction).filter(
                CompetitorAnalysisAction.keyword_id == keyword.id
            ).delete(synchronize_session=False)
            for index, action in enumerate(insights.actions):
                db.add(CompetitorAnalysisAction(
                    id=str(uuid.uuid4()), keyword_id=keyword.id, analysis_id=run.analysis_id,
                    sort_order=index, title=action.title, description=action.description,
                    impact=action.impact, effort=action.effort, category=action.category,
                    done=False, created_at=now, updated_at=now,
                ))
        row.updated_at = now
        db.commit()
    if insights.state == "ok":
        run.usage = add_usage(run.usage, insights.usage, insights.model)
        if insights.message:
            run.warnings.append(f"\"{keyword.keyword}\": {insights.message}")
    _complete_keyword(run, keyword)


def _analyze_kwargs(run: _Run, keyword: _Keyword, rows: list[SimpleNamespace]) -> dict[str, Any]:
    pages = [r for r in rows if r.keyword_id == keyword.id]
    texts = {r.id: run.texts[r.url_key] for r in pages if r.url_key in run.texts}
    overview = keyword.ai_overview
    if overview is not None and overview.state == "empty":
        # "Geen AI Overview gevonden" in plaats van "onbekend" in de prompt.
        overview = AiOverview(state="ok", sources=[], own_cited=None)
    elif overview is not None and overview.state != "ok":
        overview = None
    return dict(
        keyword=keyword.keyword, pages=pages, texts=texts, modules=list(run.modules), top_n=run.top_n,
        country=run.country, intents=keyword.intents, serp_features=keyword.serp_features,
        paa=keyword.paa, ai_overview=overview, customer_domain=run.customer_domain,
    )


def _step_analyze(run: _Run, beat: Callable[[], None]) -> None:
    _update(run.analysis_id, status="analyzing", warnings=list(run.warnings),
            sources=run.sources.model_dump(mode="json"))
    configured = claude.is_configured()
    classification = _classify(run, configured)
    _apply_classification(run, classification)
    if not configured and run.exclude_aggregators:
        run.warnings.append(NO_AGGREGATOR_EXCLUSION_WARNING)
    _update(run.analysis_id, warnings=list(run.warnings),
            ai_usage=run.usage.model_dump(mode="json") if run.usage else None)
    _check(run.analysis_id)

    keywords = [k for k in run.keywords if not k.failed]
    if not runs_analysis(run.modules) or not configured:
        state = "not_configured" if runs_analysis(run.modules) else "skipped"
        for keyword in keywords:
            _complete_keyword(run, keyword, ai_state=state)
        _set_claude_source(run, configured)
        return

    rows = _page_rows(run.analysis_id)
    pool = ThreadPoolExecutor(max_workers=ANALYZE_CONCURRENCY)
    try:
        futures = {pool.submit(analyze_keyword, **_analyze_kwargs(run, k, rows)): k for k in keywords}
        pending = set(futures)
        while pending:
            done, pending = _wait(pending, run.analysis_id, beat)
            for future in done:
                keyword = futures[future]
                try:
                    insights = future.result()
                except AnthropicServiceError as exc:
                    logger.warning("Analyse %s: inhoudsanalyse mislukt (%s)", run.analysis_id, exc.code)
                    run.claude_errors.append(f"Inhoudsanalyse \"{keyword.keyword}\" mislukt: {exc.message}")
                    _complete_keyword(run, keyword, ai_state="error", ai_error=exc.message)
                    continue
                except Exception as exc:  # noqa: BLE001 - alleen dit zoekwoord
                    logger.warning("Analyse %s: inhoudsanalyse onverwacht mislukt (%s)",
                                   run.analysis_id, type(exc).__name__)
                    message = f"Inhoudsanalyse mislukt door een onverwachte fout ({type(exc).__name__})."
                    run.claude_errors.append(message)
                    _complete_keyword(run, keyword, ai_state="error", ai_error=message)
                    continue
                _save_insights(run, keyword, insights)
            if done:
                _check(run.analysis_id)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    _set_claude_source(run, configured)


def _set_claude_source(run: _Run, configured: bool) -> None:
    if not configured:
        run.sources.claude = SourceStatus(state="not_configured", message=NOT_CONFIGURED_MESSAGE)
    elif run.claude_errors:
        run.sources.claude = SourceStatus(state="error", message=" ".join(run.claude_errors)[:500])
    else:
        run.sources.claude = SourceStatus(state="ok")


# --- afronden ------------------------------------------------------------------------------


def _complete(run: _Run, beat: Callable[[], None]) -> None:
    _finish_vitals(run, beat)
    failed = [k.keyword for k in run.keywords if k.failed]
    if failed:
        run.warnings.append(
            f"{len(failed)} van de {len(run.keywords)} zoekwoorden mislukt: {', '.join(failed)}."
        )
    _update(run.analysis_id, status="completed", completed_at=_now(), error_message=None, **run.state_fields())


def _fail(run: _Run, message: str) -> None:
    """Run op `failed` met een korte melding; afgeronde zoekwoorden blijven staan."""
    if run.vitals is not None:
        run.vitals.stop()
    try:
        _update(run.analysis_id, status="failed", error_message=message[:1000], **run.state_fields())
    except Exception:  # noqa: BLE001 - laatste poging; niets meer aan te doen
        logger.exception("Analyse %s: status 'failed' niet opgeslagen", run.analysis_id)


def _timed(run: _Run, name: str, step: Callable[[], None]) -> None:
    started = time.monotonic()
    try:
        step()
    finally:
        run.timings[name] = round(time.monotonic() - started, 1)


@celery_app.task(
    bind=True,
    name="app.worker.tasks.run_competitor_analysis_task",
    soft_time_limit=1500,
    time_limit=1800,
)
def run_competitor_analysis_task(self, analysis_id: str) -> str:
    """Voert één concurrentieanalyse uit (zie de module-docstring)."""
    run = _load(analysis_id)
    if run is None or not _claim(analysis_id):
        logger.info("Concurrentieanalyse %s niet gestart: niet gevonden of niet meer 'pending'.", analysis_id)
        return analysis_id

    beat = heartbeat(lambda: _update(analysis_id))
    try:
        _timed(run, "serp", lambda: _step_serp(run))
        _check(analysis_id)
        _start_vitals(run)
        if pipeline.needs_fetch(run.modules):
            _timed(run, "fetching", lambda: _step_fetch(run, beat))
            _check(analysis_id)
        _timed(run, "analyzing", lambda: _step_analyze(run, beat))
        _check(analysis_id)
        _timed(run, "finishing", lambda: _complete(run, beat))
    except _Stopped:
        logger.info("Concurrentieanalyse %s gestopt: niet meer actief (geannuleerd).", analysis_id)
    except SoftTimeLimitExceeded:
        logger.warning("Concurrentieanalyse %s: tijdslimiet bereikt.", analysis_id)
        _fail(run, TIMEOUT_MESSAGE)
    except _RunFailed as exc:
        logger.warning("Concurrentieanalyse %s mislukt: %s", analysis_id, exc)
        _fail(run, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Concurrentieanalyse %s onverwacht mislukt", analysis_id)
        _fail(run, f"De analyse is gestopt door een interne fout ({type(exc).__name__}).")
    finally:
        if run.vitals is not None:
            run.vitals.stop()
        logger.info(
            "Concurrentieanalyse %s: duur per stap %s, %s Ahrefs-units, Claude %s",
            analysis_id, run.timings, run.units,
            run.usage.model_dump() if run.usage else "—",
        )
    return analysis_id
