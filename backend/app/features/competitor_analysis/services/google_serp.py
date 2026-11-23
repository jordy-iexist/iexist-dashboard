"""Eigen Google-poging: "Mensen vragen ook" en de AI-overzicht-bronnen uit de resultaatpagina.

De top 10 per zoekwoord komt uit Ahrefs. Ahrefs geeft niet de tekst van de vragen onder
"Mensen vragen ook" en mogelijk niet de bronnen van het AI-overzicht; daarvoor openen we met
één gewone Chromium de Google-resultaatpagina en lezen die twee dingen uit. Ahrefs blijkt beide
inmiddels zelf te leveren; ``fetch_google`` is daarmee hooguit een reserve. ``BrowserSession``
is ook zonder Google bruikbaar: ``page_html`` is de herkansing voor een concurrentpagina die de
gewone fetch blokkeerde.

Best-effort, zonder omzeiling
    Google blokkeert server-IP's vaak (CAPTCHA, ``/sorry/``-pagina, toestemmingsscherm). We
    gebruiken geen proxy's, CAPTCHA-oplossers, stealth-plugins of vingerafdruk-trucs: één
    headless Chromium met een normaal Nederlands profiel (locale nl-NL, tijdzone Amsterdam,
    viewport 1366x768, standaard user-agent van Playwright). Een toestemmingsscherm wijzen we
    netjes af; bij een blokkade stoppen we. Niets in deze module gooit een uitzondering naar de
    aanroeper (behalve ``SoftTimeLimitExceeded``, de tijdslimiet van de Celery-taak zelf, die
    net als in ``html_extract`` door moet): elke mislukking wordt een ``state``.

Sync Playwright, geen async
    De aanroeper is een synchrone Celery-taak die geen event loop heeft. Met de sync-API van
    Playwright houden we één browser open over meerdere zoekwoorden (en ``page_html``) zonder
    zelf een loop te beheren; ``asyncio.run`` per aanroep (zoals ``website_audit``) zou per
    zoekwoord een nieuwe browser vergen. De sync-API weigert te starten binnen een lopende
    event loop; dat controleren we vooraf in ``BrowserSession.__enter__``, zodat het een
    nette ``error`` wordt. Een ``BrowserSession`` hoort bij één thread: maak hem aan en gebruik
    hem in dezelfde thread (dus niet delen tussen threads van een ``ThreadPoolExecutor``).

Wat tegen echte HTML is geverifieerd
    De proef vanaf de ontwikkelmachine (november 2026) kwam voor beide zoekopdrachten direct op
    ``/sorry/`` uit, zonder toestemmingsscherm. Daardoor is alleen de herkenning van de
    blokkadepagina tegen echte HTML geverifieerd (fixture ``sorry_captcha.real.html``).
    NIET geverifieerd tegen echte HTML: de herkenning van het toestemmingsscherm, de
    resultaatpagina-markeringen (``id="search"``/``id="rso"``), de vragen van "Mensen vragen
    ook" (``data-q`` met tekstuele terugval onder de kop) en het AI-overzicht (kop
    "AI-overzicht"/"AI Overview" en de links eronder tot het eerste organische resultaat).
    Die selectoren volgen wat bekend is van Google's opmaak en kunnen bij een echte pagina
    bijgesteld moeten worden.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse, urlunparse

from celery.exceptions import SoftTimeLimitExceeded

from app.core.url_guard import is_safe_external_url

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 25.0
PAUSE_SECONDS = 3.0  # vaste pauze tussen twee zoekopdrachten
MAX_QUESTIONS = 8
MAX_AI_SOURCES = 10
AI_WAIT_MS = 4000  # zo lang wachten we hooguit op een laat ladend AI-overzicht
CONSENT_CLICK_MS = 5000
CONSENT_NAV_MS = 8000
SETTLE_MS = 3000

VIEWPORT = {"width": 1366, "height": 768}

MSG_BLOCKED = "Google blokkeerde de zoekopdracht (CAPTCHA, ongebruikelijk verkeer)."
MSG_CONSENT = "Google bleef op het toestemmingsscherm staan."
MSG_NO_SERP = "Geen herkenbare Google-resultaatpagina ontvangen."
MSG_PARSE = "De Google-resultaatpagina kon niet worden gelezen."
MSG_BROWSER = "De browser kon niet starten."

# Taal van de interface per land (gl). Onbekende landen krijgen Engels.
_HL_BY_COUNTRY = {"nl": "nl", "be": "nl", "de": "de", "at": "de", "ch": "de", "fr": "fr", "es": "es", "it": "it"}

_WS_RE = re.compile(r"\s+")
_PAA_HEADING_RE = re.compile(r"^(mensen vragen ook|people also ask)$", re.IGNORECASE)
_AIO_HEADING_RE = re.compile(r"^(ai[- ]?overzicht|ai overview|overzicht met ai)$", re.IGNORECASE)
_STOP_HEADING_RE = re.compile(
    r"^(gerelateerde zoekopdrachten|related searches|mensen zoeken ook naar|anderen zochten ook naar"
    r"|people also search for)$",
    re.IGNORECASE,
)
_BLOCK_TEXT_RE = re.compile(r"ongebruikelijk verkeer|unusual traffic|niet door een robot|not a robot", re.IGNORECASE)
_CONSENT_TEXT_RE = re.compile(r"^(alles afwijzen|reject all|alle ablehnen|tout refuser)$", re.IGNORECASE)
_SKIP_TEXT_TAGS = {"script", "style", "noscript", "template", "svg"}
_NON_SOURCE_HOST_RE = re.compile(
    r"(^|\.)(google\.[a-z.]+|gstatic\.com|googleusercontent\.com|googleadservices\.com|googlesyndication\.com"
    r"|doubleclick\.net)$",
    re.IGNORECASE,
)


@dataclass
class GoogleSerp:
    state: str = "error"  # "ok" | "empty" | "blocked" | "error"
    questions: list[str] = field(default_factory=list)  # "Mensen vragen ook", ontdubbeld, max 8
    ai_overview: bool = False
    ai_sources: list[dict] = field(default_factory=list)  # [{"domain": ..., "url": ...}]
    message: str = ""  # korte Nederlandse reden bij blocked/error, anders ""

    @classmethod
    def failed(cls, state: str, message: str) -> "GoogleSerp":
        return cls(state=state, message=message)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- pure parser ------------------------------------------------------------


def _clean(value: str | None) -> str:
    return _WS_RE.sub(" ", str(value or "")).strip()


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_sorry_url(url: str) -> bool:
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return False
    return parsed.path.startswith("/sorry/") or "/sorry/index" in (url or "")


def _is_consent_url(url: str) -> bool:
    return _host(url).startswith("consent.")


def _source_from_href(href: str) -> dict | None:
    """Externe bron-URL uit een link; None voor Google-eigen of relatieve links."""
    href = (href or "").strip()
    if not href:
        return None
    try:
        parsed = urlparse(href)
        # Google verpakt links soms als /url?q=<doel>; pak het doel uit.
        if parsed.path == "/url" and (not parsed.hostname or _NON_SOURCE_HOST_RE.search(parsed.hostname)):
            params = parse_qs(parsed.query)
            target = (params.get("q") or params.get("url") or [""])[0]
            if not target:
                return None
            parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        host = parsed.hostname.lower()
        if _NON_SOURCE_HOST_RE.search(host):
            return None
        # Tekstfragment (#:~:text=...) en andere ankers weg; die verschillen per citaat.
        url = urlunparse(parsed._replace(fragment=""))
    except ValueError:
        return None
    domain = host[4:] if host.startswith("www.") else host
    return {"domain": domain, "url": url}


class _SerpParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.has_results = False
        self.has_captcha = False
        self.has_block_text = False
        self.has_consent = False
        self.data_q: list[str] = []
        self.paa_text: list[str] = []  # terugval: tekst met "?" onder de kop "Mensen vragen ook"
        self.ai_overview = False
        self.ai_links: list[str] = []
        self._in_paa = False
        self._in_aio = False
        self._anchor_href: str | None = None
        self._anchor_in_aio = False
        self._anchor_has_h3 = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}

        if a.get("id") in {"search", "rso"}:
            self.has_results = True
        if tag == "form":
            action = a.get("action", "")
            if "consent.google." in action:
                self.has_consent = True
            if a.get("id") == "captcha-form":
                self.has_captcha = True
        if tag in {"textarea", "input"} and a.get("name") == "q" and a.get("type", "").lower() != "hidden":
            self.has_results = True
        if "g-recaptcha" in a.get("class", "") or "/recaptcha/" in a.get("src", ""):
            self.has_captcha = True

        question = _clean(a.get("data-q"))
        if question:
            self.data_q.append(question)

        if tag == "a":
            self._anchor_href = a.get("href", "")
            self._anchor_in_aio = self._in_aio
            self._anchor_has_h3 = False
        elif tag == "h3":
            # Een organisch resultaat (<a><h3>titel</h3></a>) sluit het AI-overzicht af.
            if self._anchor_href is not None:
                self._anchor_has_h3 = True
            self._in_aio = False

        if tag in _SKIP_TEXT_TAGS:
            self._skip_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() in _SKIP_TEXT_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        if tag.lower() == "a":
            self._anchor_href = None

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self._anchor_href is not None:
            if self._anchor_in_aio and not self._anchor_has_h3:
                self.ai_links.append(self._anchor_href)
            self._anchor_href = None
        if tag in _SKIP_TEXT_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = _clean(data)
        if not text:
            return
        if _BLOCK_TEXT_RE.search(text):
            self.has_block_text = True
        if _CONSENT_TEXT_RE.match(text):
            self.has_consent = True
        if _AIO_HEADING_RE.match(text):
            self.ai_overview = True
            self._in_aio = True
            self._in_paa = False
            return
        if _PAA_HEADING_RE.match(text):
            self._in_paa = True
            self._in_aio = False
            return
        if _STOP_HEADING_RE.match(text):
            self._in_paa = False
            self._in_aio = False
            return
        if self._in_paa and text.endswith("?") and 8 <= len(text) <= 250:
            self.paa_text.append(text)


def _dedupe_questions(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean(item)[:250]
        key = text.casefold().rstrip("?").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= MAX_QUESTIONS:
            break
    return out


def _dedupe_sources(hrefs: Iterable[str]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for href in hrefs:
        source = _source_from_href(href)
        if source is None:
            continue
        key = source["url"].rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(source)
        if len(out) >= MAX_AI_SOURCES:
            break
    return out


def parse_serp_html(html: str, final_url: str = "") -> GoogleSerp:
    """Lees "Mensen vragen ook" en het AI-overzicht uit een Google-pagina. Puur, geen netwerk.

    - ``blocked``: ``/sorry/`` in de URL, een toestemmingspagina als eindtoestand, of (zonder
      resultaatpagina-markering) een CAPTCHA/"ongebruikelijk verkeer".
    - ``error``: geen herkenbare resultaatpagina, of de HTML kon niet gelezen worden.
    - ``empty``: normale resultaatpagina zonder vragen en zonder AI-overzicht.
    - ``ok``: anders.

    Alleen de blokkadeherkenning is tegen echte Google-HTML geverifieerd; zie de module-docstring.
    """
    try:
        if _is_sorry_url(final_url):
            return GoogleSerp.failed("blocked", MSG_BLOCKED)
        if _is_consent_url(final_url):
            return GoogleSerp.failed("blocked", MSG_CONSENT)

        parser = _SerpParser()
        try:
            parser.feed(html or "")
            parser.close()
        except SoftTimeLimitExceeded:
            raise
        except Exception:  # kapotte HTML: neem wat we hebben
            pass

        if not parser.has_results:
            if parser.has_captcha or parser.has_block_text:
                return GoogleSerp.failed("blocked", MSG_BLOCKED)
            if parser.has_consent:
                return GoogleSerp.failed("blocked", MSG_CONSENT)
            return GoogleSerp.failed("error", MSG_NO_SERP)

        questions = _dedupe_questions(parser.data_q) or _dedupe_questions(parser.paa_text)
        sources = _dedupe_sources(parser.ai_links) if parser.ai_overview else []
        state = "ok" if (questions or parser.ai_overview) else "empty"
        return GoogleSerp(state=state, questions=questions, ai_overview=parser.ai_overview, ai_sources=sources)
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        logger.exception("Google-resultaatpagina uitlezen mislukt")
        return GoogleSerp.failed("error", MSG_PARSE)


# --- browser ----------------------------------------------------------------


def search_url(keyword: str, country: str = "nl") -> str:
    gl = (country or "nl").strip().lower() or "nl"
    hl = _HL_BY_COUNTRY.get(gl, "en")
    return f"https://www.google.com/search?q={quote_plus(keyword)}&hl={hl}&gl={gl}"


class _Deadline:
    """Resterende tijd in milliseconden; nooit 0, want 0 betekent bij Playwright 'geen limiet'."""

    def __init__(self, seconds: float) -> None:
        self._end = time.monotonic() + max(1.0, float(seconds))

    def left_ms(self, cap: float | None = None) -> float:
        left = max(1.0, (self._end - time.monotonic()) * 1000)
        return min(left, cap) if cap is not None else left

    def expired(self, margin_ms: float = 300) -> bool:
        return (self._end - time.monotonic()) * 1000 < margin_ms


class BrowserSession:
    """Eén Chromium voor een hele analyse (sync context manager), ook los van Google bruikbaar.

    Geen enkele methode geeft een uitzondering (behalve ``SoftTimeLimitExceeded``). Start de
    browser niet, dan staat de reden in ``start_error`` en geven ``google`` een ``error`` en
    ``page_html`` ``None``.
    """

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._host_safe: dict[str, bool] = {}
        self.start_error: str | None = None

    @property
    def available(self) -> bool:
        return self._context is not None

    def __enter__(self) -> "BrowserSession":
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            self.start_error = "Sync Playwright kan niet binnen een lopende event loop starten."
            logger.warning(self.start_error)
            return self
        try:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            # Zelfde opzet als website_audit: headless Chromium, verder standaard.
            self._browser = self._playwright.chromium.launch(headless=True)
            self._context = self._browser.new_context(
                locale="nl-NL",
                timezone_id="Europe/Amsterdam",
                viewport=VIEWPORT,
                java_script_enabled=True,
            )
        except SoftTimeLimitExceeded:
            self.close()
            raise
        except Exception as exc:
            self.close()
            self.start_error = f"{MSG_BROWSER[:-1]} ({type(exc).__name__})."
            logger.warning("Browser voor de concurrentieanalyse start niet: %s", exc)
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        for closer in (
            getattr(self._context, "close", None),
            getattr(self._browser, "close", None),
            getattr(self._playwright, "stop", None),
        ):
            if closer is None:
                continue
            try:
                closer()
            except Exception:
                pass
        self._context = self._browser = self._playwright = None

    # --- Google ---------------------------------------------------------

    def google(self, keyword: str, *, country: str = "nl", timeout: float = DEFAULT_TIMEOUT_SECONDS) -> GoogleSerp:
        """Open de resultaatpagina voor één zoekwoord en lees hem uit; altijd binnen ``timeout``."""
        try:
            return self._google(keyword, country, timeout)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            logger.warning("Google-poging voor %r mislukt: %s", keyword, exc)
            return GoogleSerp.failed("error", f"Google-pagina laden mislukt ({type(exc).__name__}).")

    def _google(self, keyword: str, country: str, timeout: float) -> GoogleSerp:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        if self._context is None:
            return GoogleSerp.failed("error", MSG_BROWSER)
        deadline = _Deadline(timeout)
        page = self._context.new_page()
        try:
            try:
                page.goto(search_url(keyword, country), wait_until="domcontentloaded", timeout=deadline.left_ms())
            except PlaywrightTimeoutError:
                return self._partial(page, f"Google reageerde niet binnen {float(timeout):g} seconden.")

            if self._on_consent(page):
                self._reject_consent(page, deadline)
            if not _is_sorry_url(page.url) and not _is_consent_url(page.url):
                self._settle(page, deadline)
            return parse_serp_html(page.content(), page.url)
        finally:
            try:
                page.close()
            except Exception:
                pass

    @staticmethod
    def _partial(page: Any, message: str) -> GoogleSerp:
        """Na een time-out: is wat er al staat een blokkade, dan dat; anders ``error``."""
        try:
            serp = parse_serp_html(page.content(), page.url)
            if serp.state == "blocked":
                return serp
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            pass
        return GoogleSerp.failed("error", message)

    @staticmethod
    def _consent_button(page: Any) -> Any:
        return page.get_by_role("button", name=_CONSENT_TEXT_RE).first

    def _on_consent(self, page: Any) -> bool:
        if _is_consent_url(page.url):
            return True
        try:
            return page.get_by_role("button", name=_CONSENT_TEXT_RE).count() > 0
        except Exception:
            return False

    def _reject_consent(self, page: Any, deadline: _Deadline) -> None:
        """Toestemmingsscherm netjes afwijzen ("Alles afwijzen"). Lukt het niet, dan beslist de parser."""
        if deadline.expired():
            return
        try:
            self._consent_button(page).click(timeout=deadline.left_ms(CONSENT_CLICK_MS))
        except Exception:
            return
        try:
            if _is_consent_url(page.url) or not deadline.expired():
                page.wait_for_url(lambda u: not _is_consent_url(u), timeout=deadline.left_ms(CONSENT_NAV_MS))
            page.wait_for_load_state("domcontentloaded", timeout=deadline.left_ms(CONSENT_NAV_MS))
        except Exception:
            pass

    def _settle(self, page: Any, deadline: _Deadline) -> None:
        """Korte wachttijd voor laat ladende blokken; het AI-overzicht krijgt hooguit AI_WAIT_MS.

        We klikken niet op "Meer tonen": de bronnen staan doorgaans al in de DOM, en een klik op
        een niet-geverifieerde knop kan de pagina laten wegnavigeren.
        """
        if deadline.expired():
            return
        try:
            page.wait_for_load_state("load", timeout=deadline.left_ms(SETTLE_MS))
        except Exception:
            pass
        if deadline.expired():
            return
        try:
            page.get_by_text(_AIO_HEADING_RE).first.wait_for(state="attached", timeout=deadline.left_ms(AI_WAIT_MS))
        except Exception:
            pass

    # --- herkansing voor een geblokkeerde pagina ------------------------

    def _url_allowed(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        if parsed.scheme not in {"http", "https"}:
            return parsed.scheme in {"data", "blob"}
        host = (parsed.hostname or "").lower()
        if host not in self._host_safe:
            self._host_safe[host] = bool(host) and is_safe_external_url(f"{parsed.scheme}://{host}/")
        return self._host_safe[host]

    def _guard_route(self, route: Any) -> None:
        try:
            request = route.request
            if request.resource_type in {"image", "media", "font"}:
                route.abort()
            elif self._url_allowed(request.url):
                route.continue_()
            else:
                route.abort("blockedbyclient")
        except Exception:
            pass

    def page_html(self, url: str, *, timeout: float = 20) -> str | None:
        """HTML van een pagina via de browser, als herkansing na een geblokkeerde gewone fetch.

        Controleert de URL vooraf met ``is_safe_external_url``; elk verzoek van de pagina gaat
        langs dezelfde controle (per host). Playwright laat redirect-stappen niet langs de
        route-handler gaan; daarom wordt de redirectketen achteraf gecontroleerd en geeft een
        onveilige stap ``None``. Geeft ``None`` bij elke fout, een HTTP-status >= 400 of een
        onveilige URL.
        """
        page = None
        try:
            if not url or not is_safe_external_url(url) or self._context is None:
                return None
            deadline = _Deadline(timeout)
            page = self._context.new_page()
            page.route("**/*", self._guard_route)
            response = page.goto(url, wait_until="domcontentloaded", timeout=deadline.left_ms())
            if response is None or response.status >= 400:
                return None
            request = response.request
            while request is not None:
                if not self._url_allowed(request.url):
                    return None
                request = request.redirected_from
            if not self._url_allowed(page.url):
                return None
            if not deadline.expired():
                try:
                    page.wait_for_load_state("networkidle", timeout=deadline.left_ms(SETTLE_MS))
                except Exception:
                    pass
            return page.content()
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            logger.info("Browser-herkansing voor %s mislukt: %s", url, exc)
            return None
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass


# --- meerdere zoekwoorden ---------------------------------------------------


def default_timeout() -> float:
    """Tijd per zoekwoord uit de instellingen (``competitor_analysis_google_timeout_seconds``), anders 25 s."""
    try:
        from app.core.config import settings

        value = float(getattr(settings, "competitor_analysis_google_timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        return value if value > 0 else DEFAULT_TIMEOUT_SECONDS
    except Exception:
        return DEFAULT_TIMEOUT_SECONDS


def fetch_google(
    keywords: list[str],
    *,
    country: str = "nl",
    timeout: float | None = None,
    pause_seconds: float = PAUSE_SECONDS,
    session_factory: Callable[[], Any] = BrowserSession,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, GoogleSerp]:
    """Zoekwoorden na elkaar in één browser, met een vaste pauze; stopt na de eerste blokkade.

    Na een blokkade krijgen de resterende zoekwoorden ``blocked`` met dezelfde melding, zonder
    verdere verzoeken. Start de browser niet, dan krijgen alle zoekwoorden ``error``. Geeft
    altijd een resultaat per (ontdubbeld, niet-leeg) zoekwoord en gooit nooit een uitzondering
    (behalve ``SoftTimeLimitExceeded``). ``timeout`` is per zoekwoord; ``None`` = de instelling.
    """
    ordered: list[str] = []
    for keyword in keywords or []:
        kw = str(keyword or "").strip()
        if kw and kw not in ordered:
            ordered.append(kw)
    results: dict[str, GoogleSerp] = {}
    if not ordered:
        return results
    per_keyword = float(timeout) if timeout and timeout > 0 else default_timeout()

    with ExitStack() as stack:
        try:
            session = stack.enter_context(session_factory())
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            logger.warning("Browser voor de Google-poging start niet: %s", exc)
            return {kw: GoogleSerp.failed("error", MSG_BROWSER) for kw in ordered}
        if getattr(session, "start_error", None):
            return {kw: GoogleSerp.failed("error", MSG_BROWSER) for kw in ordered}

        blocked_message: str | None = None
        for index, kw in enumerate(ordered):
            if blocked_message is not None:
                results[kw] = GoogleSerp.failed("blocked", blocked_message)
                continue
            if index and pause_seconds > 0:
                sleep(pause_seconds)
            try:
                serp = session.google(kw, country=country, timeout=per_keyword)
                if not isinstance(serp, GoogleSerp):
                    serp = GoogleSerp.failed("error", MSG_PARSE)
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:
                logger.warning("Google-poging voor %r mislukt: %s", kw, exc)
                serp = GoogleSerp.failed("error", f"Google-pagina laden mislukt ({type(exc).__name__}).")
            results[kw] = serp
            if serp.state == "blocked":
                blocked_message = serp.message or MSG_BLOCKED

        # Sluiten mag nooit de analyse stoppen.
        try:
            stack.pop_all().close()
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            logger.info("Browser sluiten na de Google-poging gaf een fout", exc_info=True)
    return results


__all__ = ["GoogleSerp", "BrowserSession", "parse_serp_html", "fetch_google", "search_url", "default_timeout"]
