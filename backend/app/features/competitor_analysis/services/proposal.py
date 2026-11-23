"""Voorstel voor de wizard "Nieuwe analyse": zoekwoorden, doelpagina's en de stand van de bronnen.

Zonder betaalde aanroep:
- zoekwoorden met rankende URL, positie en volume live uit ProRankTracker (`organic_rows`);
- aangevuld met de bewaarde Ahrefs-quick wins van de klant (`CustomerQuickWins.rows`; er wordt
  níet opnieuw opgehaald, ook niet als de stand verlopen is);
- de stand per databron; voor Ahrefs het resterende aantal units uit `limits_and_usage`
  (kost 0 units).

Een trage of falende bron laat het voorstel niet mislukken: PRT en Ahrefs lopen naast elkaar
met een tijdslimiet (`SOURCE_TIMEOUT_SECONDS`); daarna krijgt de bron `error` met een melding.
De functies committen niet.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Callable, TypeVar
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import CustomerQuickWins, CustomerWebsite
from app.features.competitor_analysis.schemas import (
    PositionSource,
    ProposalDefaults,
    ProposalKeyword,
    ProposalResponse,
    Sources,
    SourceStatus,
)
from app.features.competitor_analysis.services import estimate
from app.features.customers.quick_wins import best_prt, convert_prt
from app.features.customers.rankings import STATE_MESSAGES, host_of, keyword_key, organic_rows
from app.services.ahrefs import client as ahrefs
from app.services.ahrefs.client import AhrefsServiceError
from app.services.anthropic import client as anthropic_client

T = TypeVar("T")

# Zo lang wacht het voorstel op ProRankTracker en Ahrefs (naast elkaar).
SOURCE_TIMEOUT_SECONDS = 15.0

MESSAGES: dict[str, str] = {
    "ahrefs_not_configured": "Ahrefs is niet gekoppeld: AHREFS_API_KEY ontbreekt in de "
                             "backend-configuratie. Zonder Ahrefs kan er geen analyse worden gestart.",
    "ahrefs_ok": "Ahrefs is gekoppeld.",
    "ahrefs_timeout": "Ahrefs reageerde niet op tijd; het resterende tegoed is onbekend.",
    "ahrefs_empty": "Het Ahrefs-tegoed voor deze maand is op ({used} van {limit} units gebruikt).",
    "prt_timeout": "ProRankTracker reageerde niet op tijd; de zoekwoorden komen alleen uit de "
                   "bewaarde quick wins.",
    "prt_error": "De zoekwoorden uit ProRankTracker konden niet worden opgehaald.",
    "pagespeed_ok": "PageSpeed Insights is gekoppeld: de laadtijd (LCP) wordt mobiel gemeten.",
    "pagespeed_not_configured": "PAGESPEED_API_KEY ontbreekt: de laadtijd (LCP) wordt niet gemeten.",
    "claude_ok": "Claude is gekoppeld voor onderwerpdekking, E-E-A-T en verbeterpunten.",
    "claude_not_configured": "ANTHROPIC_API_KEY ontbreekt: onderwerpdekking, E-E-A-T en verbeterpunten "
                             "blijven leeg; de vergelijkingstabel wordt wel gevuld.",
    "google_skipped": "Niet nodig: Ahrefs levert \"Mensen vragen ook\" en de AI Overview-bronnen.",
}


# --- hulpfuncties ----------------------------------------------------------------------

def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def customer_host(customer: CustomerWebsite) -> str:
    """Host van de klant zonder `www.`; leeg als de klant geen website-adres heeft."""
    return host_of(customer.base_url or "")


def normalize_url(raw: Any) -> str | None:
    """Absolute http(s)-URL; zonder schema krijgt hij `https://`. `None` als het geen webadres is."""
    text = str(raw or "").strip()
    if not text or any(char.isspace() for char in text):
        return None
    if "://" not in text:
        text = f"https://{text.lstrip('/')}"
    parts = urlsplit(text)
    try:
        parts.port  # noqa: B018 - een ongeldige poort geeft hier een ValueError
    except ValueError:
        return None
    if (
        parts.scheme.lower() not in ("http", "https")
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
    ):
        return None
    return text


def on_domain(url: Any, host: str) -> bool:
    """Of `url` op het domein van de klant ligt (zelfde host of een subdomein, `www.` genegeerd)."""
    if not host:
        return False
    url_host = host_of(url)
    return bool(url_host) and (url_host == host or url_host.endswith(f".{host}"))


def run_with_timeout(calls: dict[str, Callable[[], Any]], timeout: float) -> dict[str, tuple[bool, Any]]:
    """Voert de aanroepen naast elkaar uit: per naam `(True, resultaat)`, `(False, fout)` of
    `(False, None)` bij een time-out. Wacht niet op aanroepen die te lang duren."""
    if not calls:
        return {}
    pool = ThreadPoolExecutor(max_workers=len(calls))
    try:
        futures = {name: pool.submit(fn) for name, fn in calls.items()}
        results: dict[str, tuple[bool, Any]] = {}
        for name, future in futures.items():
            try:
                results[name] = (True, future.result(timeout=timeout))
            except FutureTimeout:
                results[name] = (False, None)
            except Exception as exc:  # noqa: BLE001 - een bron mag het voorstel niet breken
                results[name] = (False, exc)
        return results
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


# --- zoekwoorden -----------------------------------------------------------------------

def stored_quick_wins(db: Session, customer: CustomerWebsite) -> list[dict[str, Any]]:
    """Bewaarde Ahrefs-quick wins van de klant, alleen als ze bij het huidige domein horen."""
    record = db.get(CustomerQuickWins, customer.id)
    if record is None or record.fetched_at is None or record.target != customer_host(customer):
        return []
    return [row for row in (record.rows or []) if isinstance(row, dict)]


def _sort_key(row: ProposalKeyword) -> tuple:
    return (
        row.volume is None, -(row.volume or 0),
        row.position is None, row.position or 0,
        keyword_key(row.keyword),
    )


def merge_keywords(
    prt_rows: list[dict[str, Any]], quick_wins: list[dict[str, Any]], host: str,
) -> list[ProposalKeyword]:
    """PRT-rijen (organisch, ruw) en bewaarde quick wins samenvoegen tot één lijst.

    Elk zoekwoord één keer (`keyword_key`). PRT is leidend voor positie en URL (dagelijks
    gemeten), ook als PRT geen positie heeft; het volume komt uit PRT als die er is, anders uit
    de quick win. Een URL buiten het klantdomein vervalt. Gesorteerd op volume aflopend (zonder
    volume achteraan), dan positie, dan zoekwoord.
    """
    merged: dict[str, ProposalKeyword] = {}

    def add(key: str, raw: dict[str, Any], source: PositionSource) -> None:
        keyword = " ".join(str(raw.get("keyword") or "").split())
        if not key or not keyword:
            return
        url = raw.get("url")
        volume = _int(raw.get("volume"))
        position = _int(raw.get("position"))
        merged[key] = ProposalKeyword(
            keyword=keyword,
            url=str(url) if url and on_domain(url, host) else None,
            position=position if position is not None and position > 0 else None,
            volume=volume if volume is not None and volume >= 0 else None,
            source=source,
        )

    for key, raw in best_prt(prt_rows).items():
        add(key, convert_prt(raw), "prt")

    for row in quick_wins:
        key = keyword_key(row.get("keyword"))
        current = merged.get(key)
        if current is None:
            add(key, row, "ahrefs")
        elif current.volume is None and _int(row.get("volume")) is not None:
            merged[key] = current.model_copy(update={"volume": max(_int(row.get("volume")) or 0, 0)})

    return sorted(merged.values(), key=_sort_key)


def unique_pages(keywords: list[ProposalKeyword]) -> list[str]:
    """Unieke rankende URL's (al op het klantdomein), alfabetisch."""
    return sorted({row.url for row in keywords if row.url})


# --- bronnen ---------------------------------------------------------------------------

def prt_status(state: str, rows: list[dict[str, Any]], message: str | None) -> SourceStatus:
    """De uitkomst van `organic_rows` als bronstatus."""
    if state == "ok":
        count = len(best_prt(rows))
        noun = "zoekwoord" if count == 1 else "zoekwoorden"
        return SourceStatus(state="ok", message=f"{count} gevolgde {noun} uit ProRankTracker.")
    if state == "not_configured":
        return SourceStatus(state="not_configured", message=STATE_MESSAGES["not_configured"])
    if state == "not_tracked":
        return SourceStatus(state="empty", message=STATE_MESSAGES["not_tracked"])
    return SourceStatus(state="error", message=message or MESSAGES["prt_error"])


def ahrefs_status(usage: dict[str, Any]) -> SourceStatus:
    """Bronstatus uit `limits_and_usage`: het resterende aantal units deze maand.

    Heeft de API-sleutel een eigen limiet, dan telt de kleinste van sleutel en werkruimte.
    """
    remaining: list[tuple[int, int, int]] = []
    for limit_field, usage_field in (
        ("units_limit_workspace", "units_usage_workspace"),
        ("units_limit_api_key", "units_usage_api_key"),
    ):
        limit, used = _int(usage.get(limit_field)), _int(usage.get(usage_field))
        if limit is not None and limit > 0:
            remaining.append((limit - (used or 0), limit, used or 0))
    if not remaining:
        return SourceStatus(state="ok", message=MESSAGES["ahrefs_ok"])
    left, limit, used = min(remaining)
    if left <= 0:
        return SourceStatus(
            state="error",
            message=MESSAGES["ahrefs_empty"].format(used=_thousands(used), limit=_thousands(limit)),
        )
    return SourceStatus(
        state="ok",
        message=f"Ahrefs is gekoppeld: nog {_thousands(left)} van {_thousands(limit)} units deze maand.",
    )


def pagespeed_status() -> SourceStatus:
    if str(settings.pagespeed_api_key or "").strip():
        return SourceStatus(state="ok", message=MESSAGES["pagespeed_ok"])
    return SourceStatus(state="not_configured", message=MESSAGES["pagespeed_not_configured"])


def claude_status() -> SourceStatus:
    if anthropic_client.is_configured():
        return SourceStatus(state="ok", message=MESSAGES["claude_ok"])
    return SourceStatus(state="not_configured", message=MESSAGES["claude_not_configured"])


def google_status() -> SourceStatus:
    return SourceStatus(state="skipped", message=MESSAGES["google_skipped"])


def _ahrefs_from(outcome: tuple[bool, Any] | None) -> SourceStatus:
    if outcome is None:
        return SourceStatus(state="not_configured", message=MESSAGES["ahrefs_not_configured"])
    ok, value = outcome
    if ok:
        return ahrefs_status(value if isinstance(value, dict) else {})
    if value is None:
        return SourceStatus(state="error", message=MESSAGES["ahrefs_timeout"])
    if isinstance(value, AhrefsServiceError) and value.code == "not_configured":
        return SourceStatus(state="not_configured", message=MESSAGES["ahrefs_not_configured"])
    return SourceStatus(state="error", message=f"Ahrefs-tegoed niet opgehaald: {value}")


def _prt_from(outcome: tuple[bool, Any]) -> tuple[list[dict[str, Any]], SourceStatus]:
    ok, value = outcome
    if not ok:
        message = MESSAGES["prt_timeout"] if value is None else MESSAGES["prt_error"]
        return [], SourceStatus(state="error", message=message)
    state, rows, message = value
    return (rows if state == "ok" else []), prt_status(state, rows, message)


# --- samenstellen ----------------------------------------------------------------------

@dataclass
class KeywordData:
    """Zoekwoorden uit PRT en de bewaarde quick wins, met de stand van PRT."""

    keywords: list[ProposalKeyword]
    prt: SourceStatus

    def by_key(self) -> dict[str, ProposalKeyword]:
        return {keyword_key(row.keyword): row for row in self.keywords}


def _collect(db: Session, customer: CustomerWebsite, *, with_ahrefs: bool) -> tuple[KeywordData, SourceStatus | None]:
    base_url = customer.base_url or ""
    calls: dict[str, Callable[[], Any]] = {"prt": lambda: organic_rows(base_url)}
    configured = ahrefs.is_configured()
    if with_ahrefs and configured:
        calls["ahrefs"] = ahrefs.limits_and_usage
    outcomes = run_with_timeout(calls, SOURCE_TIMEOUT_SECONDS)
    prt_rows, prt = _prt_from(outcomes["prt"])
    keywords = merge_keywords(prt_rows, stored_quick_wins(db, customer), customer_host(customer))
    ahrefs_source = _ahrefs_from(outcomes.get("ahrefs")) if with_ahrefs else None
    return KeywordData(keywords=keywords, prt=prt), ahrefs_source


def keyword_data(db: Session, customer: CustomerWebsite) -> KeywordData:
    """Alleen de zoekwoorden (voor starten): eigen positie en volume per zoekwoord."""
    data, _ = _collect(db, customer, with_ahrefs=False)
    return data


def sources_without_ahrefs_call(prt: SourceStatus) -> Sources:
    """Bronstand op basis van de configuratie (Ahrefs zonder aanroep), bijv. bij het starten."""
    configured = ahrefs.is_configured()
    return Sources(
        ahrefs=SourceStatus(state="ok", message=MESSAGES["ahrefs_ok"]) if configured
        else SourceStatus(state="not_configured", message=MESSAGES["ahrefs_not_configured"]),
        prt=prt,
        pagespeed=pagespeed_status(),
        claude=claude_status(),
        google=google_status(),
    )


def build_proposal(db: Session, customer: CustomerWebsite) -> ProposalResponse:
    """Het volledige voorstel voor de wizard."""
    data, ahrefs_source = _collect(db, customer, with_ahrefs=True)
    return ProposalResponse(
        sources=Sources(
            ahrefs=ahrefs_source,
            prt=data.prt,
            pagespeed=pagespeed_status(),
            claude=claude_status(),
            google=google_status(),
        ),
        keywords=data.keywords,
        pages=unique_pages(data.keywords),
        defaults=ProposalDefaults(country=(settings.ahrefs_country or "nl").strip().lower() or "nl"),
        rates=estimate.rates(),
        max_keywords=settings.competitor_analysis_max_keywords,
    )
