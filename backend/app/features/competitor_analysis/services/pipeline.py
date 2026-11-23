"""Stappen van de concurrentieanalyse, los van de database en van Celery.

De taak (`worker/analysis.py`) is de regie: hij leest en schrijft de database en roept deze
functies aan. Alles hier is puur of praat alleen met een externe bron (Ahrefs-rijen
omzetten, een pagina ophalen en uitlezen, PageSpeed op de achtergrond), zodat elke stap apart
te testen is.

- SERP: `serp_facts` zet het antwoord van `serp_overview` om naar de gegevens van het
  zoekwoord (features, vragen, AI Overview, datum, eigen positie) en de paginarijen
  (`PageSpec`). `keyword_facts` doet hetzelfde voor `keywords_overview`.
- Ophalen: `fetch_and_extract` (gewone fetch) en `outcome_from_html` (ook voor de
  browser-herkansing) geven een `FetchOutcome`; de paginatekst blijft in het geheugen.
  `is_thin` en `richer` bepalen of een pagina zonder leesbare tekst een herkansing krijgt
  en of die beter was.
- Indeling zonder Claude: `page_type_from_ahrefs`.
- PageSpeed: `VitalsRunner` meet op een eigen thread met een eigen event loop en een hard
  budget; `cwv_from_psi` maakt van één meting een `Cwv`.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from celery.exceptions import SoftTimeLimitExceeded

from app.features.competitor_analysis.schemas import (
    AiOverview,
    AiOverviewSource,
    Cwv,
    OnPage,
    Paa,
)
from app.features.competitor_analysis.services.page_facts import (
    MIN_READABLE_WORDS,
    is_unreadable,
    onpage_from_extract,
)
from app.features.customers.rankings import host_of, keyword_key
from app.features.launch_checklist.services.content_extract import extract_content
from app.features.launch_checklist.services.discovery import root_domain_of, url_key
from app.features.launch_checklist.services.pagespeed import measure_vitals
from app.features.launch_checklist.services.schema_markup import SchemaMarkupError, fetch_page
from app.services.ahrefs import client as ahrefs

logger = logging.getLogger(__name__)

# Ahrefs-foutcodes waarmee geen enkel zoekwoord lukt: dan faalt de hele run.
FATAL_AHREFS_CODES = frozenset({"unauthorized", "forbidden", "not_configured"})

# Modules waarvoor de pagina's moeten worden opgehaald.
FETCH_MODULES = frozenset({"onpage", "topics", "eeat", "tech"})

# HTTP-statussen die een weigering zijn (bot-bescherming, firewall): herkansing via de browser.
BLOCKED_STATUSES = frozenset({401, 403, 429, 503})
MAX_BROWSER_RETRIES = 10
BROWSER_RETRY_TIMEOUT_SECONDS = 20.0

NOT_IN_TIME_MESSAGE = "niet op tijd gemeten"


def needs_fetch(modules: list[str] | tuple[str, ...] | set[str]) -> bool:
    """Moeten de pagina's worden opgehaald? Ja zodra on-page, onderwerpen, E-E-A-T of techniek aan staat."""
    return bool(FETCH_MODULES & set(modules))


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(round(value))


def _strip_www(netloc: str) -> str:
    netloc = netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def loose_key(url: str) -> str:
    """Sleutel om dezelfde pagina te herkennen: `url_key` zonder "www." (http/https gelijk)."""
    key = url_key(url)
    host, sep, rest = key.partition("/")
    return _strip_www(host) + sep + rest


def same_page(a: str | None, b: str | None) -> bool:
    return bool(a and b) and loose_key(a) == loose_key(b)


def on_customer_site(url: str, customer_root: str | None) -> bool:
    """Ligt de URL op het (hoofd)domein van de klant, subdomeinen inbegrepen?"""
    return bool(customer_root) and root_domain_of(url) == customer_root


# --- SERP ------------------------------------------------------------------------------------


@dataclass
class PageSpec:
    """Eén paginarij die de taak aanmaakt (velden van `CompetitorAnalysisPage`)."""

    url: str
    position: int | None
    is_own: bool = False
    is_excluded: bool = False
    exclude_reason: str | None = None
    serp_title: str | None = None
    ahrefs_page_type: str | None = None
    domain_rating: int | None = None
    refdomains: int | None = None
    ahrefs: dict[str, Any] = field(default_factory=dict)

    @property
    def domain(self) -> str | None:
        return host_of(self.url) or None

    @property
    def url_key(self) -> str:
        return url_key(self.url)


@dataclass
class SerpFacts:
    """Wat de taak per zoekwoord uit `serp_overview` opslaat."""

    pages: list[PageSpec]
    serp_features: list[str]
    paa: Paa
    ai_overview: AiOverview
    serp_date: str | None
    # Organische rang van de doelpagina (of anders de beste pagina van de klant); None = niet gevonden.
    own_rank: int | None
    # De doelpagina staat niet in de top N: DR/RD apart ophalen (`url_metrics`).
    own_needs_metrics: bool


def _features(result: ahrefs.AhrefsResult) -> list[str]:
    """SERP-features zonder de sitelink-types (die horen bij een resultaat of de AI Overview)."""
    return [name for name in ahrefs.serp_features(result) if "sitelink" not in name]


def _serp_date(rows: list[dict[str, Any]]) -> str | None:
    dates = [str(r.get("update_date")) for r in rows if r.get("update_date")]
    return max(dates) if dates else None


def _ahrefs_extra(row: dict[str, Any]) -> dict[str, Any]:
    """Overige Ahrefs-velden van de SERP-rij voor de JSON-kolom `ahrefs`."""
    return {
        "serp_position": row.get("position"),
        "url_rating": row.get("url_rating"),
        "backlinks": row.get("backlinks"),
        "keywords": row.get("keywords"),
        "update_date": row.get("update_date"),
    }


def serp_facts(
    result: ahrefs.AhrefsResult,
    *,
    top_n: int,
    target_url: str | None,
    customer_root: str | None,
    with_serp: bool,
    with_authority: bool,
) -> SerpFacts:
    """SERP van één zoekwoord → paginarijen en zoekwoordgegevens.

    - Concurrenten: de top N organische resultaten op organische rang (`organic_rows`).
    - Staat de doelpagina in de top N, dan is die rij de eigen rij (`is_own`, met positie).
      Andere pagina's van het klantdomein blijven zichtbaar maar zijn uitgesloten (`own_site`).
    - Staat de doelpagina er niet in, dan komt er een eigen rij zonder positie
      (`own_needs_metrics`). Zonder doelpagina geen eigen rij.
    - `with_serp` False: vragen en AI Overview `skipped`, geen features.
    - `with_authority` False: geen DR en verwijzende domeinen.
    """
    pages: list[PageSpec] = []
    own_found = False
    for row in ahrefs.organic_rows(result, top_n):
        url = str(row.get("url") or "").strip()
        spec = PageSpec(
            url=url,
            position=int(row["organic_position"]),
            serp_title=(row.get("title") or None),
            ahrefs_page_type=(row.get("page_type") or None),
            domain_rating=_int(row.get("domain_rating")) if with_authority else None,
            refdomains=_int(row.get("refdomains")) if with_authority else None,
            ahrefs=_ahrefs_extra(row),
        )
        if target_url and not own_found and same_page(url, target_url):
            spec.is_own = True
            own_found = True
        elif on_customer_site(url, customer_root):
            spec.is_excluded = True
            spec.exclude_reason = "own_site"
        pages.append(spec)

    own_needs_metrics = False
    if target_url and not own_found:
        pages.append(PageSpec(url=target_url, position=None, is_own=True))
        own_needs_metrics = with_authority

    # Eigen positie: de organische rang over alle opgehaalde organische resultaten (dus ook
    # net buiten de top N). Eerst de doelpagina, anders de beste pagina van de klant.
    all_organic = ahrefs.organic_rows(result, 10_000)
    own_rank = next((r["organic_position"] for r in all_organic if same_page(r.get("url"), target_url)), None)
    if own_rank is None:
        own_rank = next(
            (r["organic_position"] for r in all_organic if on_customer_site(str(r.get("url") or ""), customer_root)),
            None,
        )

    if with_serp:
        questions = ahrefs.people_also_ask(result)
        paa = Paa(state="ok" if questions else "empty", questions=questions)
        sources = [
            AiOverviewSource(domain=host_of(s["url"]) or s["url"], url=s["url"])
            for s in ahrefs.ai_overview_sources(result)
        ]
        ai_overview = AiOverview(
            state="ok" if sources else "empty",
            sources=sources,
            own_cited=any(on_customer_site(s.url or "", customer_root) for s in sources) if sources else None,
        )
        features = _features(result)
    else:
        paa = Paa(state="skipped")
        ai_overview = AiOverview(state="skipped")
        features = []

    return SerpFacts(
        pages=pages,
        serp_features=features,
        paa=paa,
        ai_overview=ai_overview,
        serp_date=_serp_date(result.rows),
        own_rank=own_rank,
        own_needs_metrics=own_needs_metrics,
    )


@dataclass
class KeywordFacts:
    volume: int | None
    kd: int | None
    intents: list[str]


def keyword_facts(result: ahrefs.AhrefsResult) -> dict[str, KeywordFacts]:
    """`keywords_overview` → per zoekwoord (`keyword_key`) volume, KD en de ware intenties."""
    facts: dict[str, KeywordFacts] = {}
    for row in result.rows:
        key = keyword_key(row.get("keyword"))
        if not key or key in facts:
            continue
        intents = row.get("intents")
        facts[key] = KeywordFacts(
            volume=_int(row.get("volume")),
            kd=_int(row.get("difficulty")),
            intents=[name for name, on in intents.items() if on is True] if isinstance(intents, dict) else [],
        )
    return facts


def url_metric_facts(result: ahrefs.AhrefsResult) -> dict[str, tuple[int | None, int | None]]:
    """`url_metrics` → per paginasleutel (DR, verwijzende domeinen), gekoppeld op `target`."""
    facts: dict[str, tuple[int | None, int | None]] = {}
    for row in result.rows:
        target = row.get("target")
        if target:
            facts[loose_key(str(target))] = (_int(row.get("domain_rating")), _int(row.get("refdomains")))
    return facts


# --- Paginatype zonder Claude ----------------------------------------------------------------

# Op volgorde: de eerste regel die past wint. Ahrefs geeft bv. "/Core_Page,/Core_Page/Homepage"
# of "/Landing_Page,/Landing_Page/Service_Page".
_AHREFS_TYPE_RULES: tuple[tuple[str, str], ...] = (
    ("homepage", "homepage"),
    ("service", "dienst"),
    ("product", "product"),
    ("comparison", "vergelijker"),
    ("review", "vergelijker"),
    ("directory", "vergelijker"),
    ("listing", "categorie"),
    ("collection", "categorie"),
    ("category", "categorie"),
    ("article", "blog"),
    ("blog", "blog"),
    ("post", "blog"),
    ("guide", "blog"),
    ("news", "blog"),
)


def page_type_from_ahrefs(value: Any) -> str:
    """Grove eigen indeling uit het Ahrefs-paginatype; onbekend wordt `overig`."""
    text = str(value or "").lower()
    for needle, page_type in _AHREFS_TYPE_RULES:
        if needle in text:
            return page_type
    return "overig"


# --- Ophalen ---------------------------------------------------------------------------------


@dataclass
class FetchOutcome:
    """Uitkomst van het ophalen van één pagina; `text` alleen in het geheugen (niet opslaan)."""

    status: str  # ok | blocked | not_html | error
    error: str | None = None
    final_url: str | None = None
    onpage: OnPage | None = None
    text: str = ""


_STATUS_RE = re.compile(r"status (\d{3})")


def fetch_error_outcome(exc: Exception) -> FetchOutcome:
    """Fout van `fetch_page` → status en korte Nederlandse melding."""
    message = str(exc)
    match = _STATUS_RE.search(message) if isinstance(exc, SchemaMarkupError) else None
    if match and int(match.group(1)) in BLOCKED_STATUSES:
        return FetchOutcome(status="blocked", error=f"Geweigerd door de website (HTTP {match.group(1)}).")
    if match:
        return FetchOutcome(status="error", error=f"Niet opgehaald (HTTP {match.group(1)}).")
    if isinstance(exc, SchemaMarkupError) and "geen HTML" in message:
        return FetchOutcome(status="not_html", error="Geen HTML-pagina.")
    if isinstance(exc, SchemaMarkupError) and "toegestane externe website" in message:
        return FetchOutcome(status="error", error="Adres niet toegestaan.")
    if isinstance(exc, SchemaMarkupError):
        return FetchOutcome(status="error", error=message[:200])
    return FetchOutcome(status="error", error=f"Ophalen mislukt ({type(exc).__name__}).")


def outcome_from_html(html: str, final_url: str) -> FetchOutcome:
    """HTML → on-page-kenmerken en paginatekst."""
    extract = extract_content(html, final_url, root_domain_of(final_url) or "")
    return FetchOutcome(
        status="ok",
        final_url=final_url,
        onpage=onpage_from_extract(extract),
        text=extract.body_text or "",
    )


def is_thin(outcome: FetchOutcome) -> bool:
    """Opgehaald, maar met minder dan `MIN_READABLE_WORDS` woorden: waarschijnlijk JavaScript."""
    return outcome.status == "ok" and is_unreadable(outcome.onpage)


def richer(after: FetchOutcome, before: FetchOutcome) -> bool:
    """Levert de herkansing een leesbare pagina met meer woorden op dan de eerste poging?"""
    words_after = after.onpage.word_count if after.onpage is not None else 0
    words_before = before.onpage.word_count if before.onpage is not None else 0
    return after.status == "ok" and words_after >= MIN_READABLE_WORDS and words_after > words_before


def fetch_and_extract(url: str) -> FetchOutcome:
    """Haal één pagina op (`fetch_page`, SSRF-veilig) en lees hem uit. Gooit nooit (behalve een time-out)."""
    try:
        page = fetch_page(url)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - elke fout wordt een status van deze pagina
        return fetch_error_outcome(exc)
    try:
        return outcome_from_html(page.html, page.final_url)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001
        return FetchOutcome(status="error", error=f"Pagina niet uit te lezen ({type(exc).__name__}).",
                            final_url=page.final_url)


# --- PageSpeed -------------------------------------------------------------------------------


def cwv_from_psi(data: dict[str, Any] | None, error: str | None) -> Cwv:
    """Eén PageSpeed-meting → `Cwv` met de lab-LCP (mobiel), of een korte foutmelding."""
    if not data:
        return Cwv(error=f"Meting mislukt ({(error or 'onbekende fout')[:120]}).")
    lcp = (data.get("lab") or {}).get("lcp")
    if not isinstance(lcp, (int, float)):
        return Cwv(error="Geen LCP in de meting.")
    return Cwv(lcp_ms=int(round(lcp)), source="lab")


class VitalsRunner:
    """PageSpeed op de achtergrond: eigen thread, eigen event loop, hard budget.

    `urls`: sleutel → URL (één meting per unieke URL). `on_measured(key, cwv)` schrijft weg
    (eigen databasesessie); het wordt onder een lock aangeroepen en nooit meer na `finish()`
    of `stop()`. `should_stop()` (bijv. geannuleerd) laat de meting stoppen. Fouten komen in
    `error` terecht en gaan nooit naar de aanroeper.
    """

    def __init__(
        self,
        urls: dict[str, str],
        *,
        api_key: str,
        concurrency: int,
        budget_seconds: float,
        on_measured: Callable[[str, Cwv], None],
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self.urls = dict(urls)
        self._key_by_url = {url: key for key, url in self.urls.items()}
        self.api_key = api_key
        self.concurrency = concurrency
        self.budget_seconds = budget_seconds
        self.on_measured = on_measured
        self.should_stop = should_stop
        self.measured: set[str] = set()
        self.failed: set[str] = set()
        self.error: str | None = None
        self._lock = threading.Lock()
        self._stopped = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._thread: threading.Thread | None = None
        self._started_at: float | None = None

    @property
    def total(self) -> int:
        return len(self.urls)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def join(self, seconds: float) -> None:
        """Wacht hooguit `seconds` op de meetthread (zonder te stoppen)."""
        if self._thread is not None:
            self._thread.join(max(0.0, seconds))

    def start(self) -> None:
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="competitor-vitals", daemon=True)
        self._thread.start()

    def remaining(self) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, self.budget_seconds - (time.monotonic() - self._started_at))

    def _on_result(self, url: str, data: dict[str, Any] | None, error: str | None) -> bool:
        key = self._key_by_url.get(url)
        with self._lock:
            if self._stopped or key is None:
                return False
            cwv = cwv_from_psi(data, error)
            try:
                self.on_measured(key, cwv)
            except Exception as exc:  # noqa: BLE001 - PageSpeed mag de run nooit laten mislukken
                logger.warning("PageSpeed-resultaat niet opgeslagen: %s", type(exc).__name__)
            self.measured.add(key)
            if cwv.lcp_ms is None:
                self.failed.add(key)
        try:
            return not self.should_stop()
        except Exception:  # noqa: BLE001
            return True

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            self._loop = loop
            self._task = loop.create_task(measure_vitals(
                list(self.urls.values()),
                api_key=self.api_key,
                concurrency=self.concurrency,
                on_result=self._on_result,
            ))
            if self._stopped:
                self._task.cancel()
            loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            self.error = f"PageSpeed-meting afgebroken ({type(exc).__name__})."
            logger.warning("PageSpeed voor de concurrentieanalyse faalde: %s", type(exc).__name__)
        finally:
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        """Stop direct: geen nieuwe resultaten meer wegschrijven en de lopende metingen afbreken."""
        with self._lock:
            self._stopped = True
        loop, task = self._loop, self._task
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:  # loop al gesloten
                pass

    def finish(self, timeout: float | None = None) -> list[str]:
        """Wacht hooguit `timeout` (standaard het resterende budget), stop en geef de niet-gemeten sleutels."""
        if self._thread is not None:
            self._thread.join(self.remaining() if timeout is None else max(0.0, timeout))
        self.stop()
        with self._lock:
            return [key for key in self.urls if key not in self.measured]
