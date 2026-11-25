"""Signalen van het bureau-overzicht ("Vraagt aandacht"): de zinnen, de ernst en de volgorde.

Pure functies: `overview.py` verzamelt de gegevens uit de database en de koppelingen en maakt
hier de signalen van. Per klant hooguit één signaal per soort; bij meerdere problemen staat het
eerste in de zin met "(en N andere)" erachter.

| soort   | ernst | wanneer                                                              | link            |
|---------|-------|----------------------------------------------------------------------|-----------------|
| daling  | hoog  | zoekwoord gezakt (zie `rank_snapshots.py`)                           | customer_home   |
| storing | hoog  | scan mislukt, sitemap-monitor faalt, posities of Search Console      | seo_geo, customer_profile of customer_home |
| werk    | middel| kaart > 7 dagen in Review, of ernst hoog > 14 dagen in Te doen       | work_board      |
| rapport | middel| dag 1–7: geen voltooid rapport van vorige maand; of dat is mislukt   | monthly_report  |

Werkt de Search Console- of ProRankTracker-koppeling van het hele bureau niet, dan is er één
signaal zonder klant (`customer_id = None`, link `none`) in plaats van een signaal per klant.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

KIND_DROP = "daling"
KIND_FAILURE = "storing"
KIND_WORK = "werk"
KIND_REPORT = "rapport"
KINDS: tuple[str, ...] = (KIND_DROP, KIND_FAILURE, KIND_WORK, KIND_REPORT)

SEVERITY_HIGH = "hoog"
SEVERITY_MEDIUM = "middel"
SEVERITY_LOW = "laag"
SEVERITIES: tuple[str, ...] = (SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW)

KIND_SEVERITY: dict[str, str] = {
    KIND_DROP: SEVERITY_HIGH,
    KIND_FAILURE: SEVERITY_HIGH,
    KIND_WORK: SEVERITY_MEDIUM,
    KIND_REPORT: SEVERITY_MEDIUM,
}

LINK_CUSTOMER_HOME = "customer_home"
LINK_MONTHLY_REPORT = "monthly_report"
LINK_CUSTOMER_PROFILE = "customer_profile"
LINK_SEO_GEO = "seo_geo"
LINK_WORK_BOARD = "work_board"
LINK_NONE = "none"

# Sleutel van een bureaubreed signaal in het id ("storing:bureau:search_console").
BUREAU = "bureau"
BUREAU_SEARCH_CONSOLE = "search_console"
BUREAU_PRORANKTRACKER = "proranktracker"

# Drempels van "Werk loopt vast" (in dagen).
REVIEW_STALE_DAYS = 7
TODO_HIGH_STALE_DAYS = 14
# Dag 1 t/m deze dag van de maand moet het rapport van de vorige maand klaar zijn (PRT-cijfers
# gelden tot 7 dagen na het maandeinde, zie monthly_report/services/periods.py).
REPORT_DUE_DAY = 7

PHASE_LABELS: dict[int, str] = {
    1: "Nulmeting",
    2: "GEO/SEO-scan",
    3: "Contentscan",
    4: "Kwartaalscan",
    5: "Livegangscan",
    6: "Sitemap-monitor",
}

MONTH_NAMES: tuple[str, ...] = (
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
)
MONTH_SHORT: tuple[str, ...] = (
    "jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec",
)

GSC_NO_PROPERTY = "Staat niet in Search Console"
GSC_PROPERTY_INACCESSIBLE = "Geen toegang (meer) tot de gekozen Search Console-property"
PRT_ERROR = "Posities niet opgehaald uit ProRankTracker"
MONITOR_FAILED = "Sitemap-monitor mislukt"


@dataclass(frozen=True)
class Problem:
    """Eén probleem achter een signaal "Storing": de zin en waar de link heen gaat."""

    text: str
    link_type: str


@dataclass(frozen=True)
class Signal:
    kind: str
    severity: str
    customer_id: str | None
    customer_name: str | None
    text: str
    link_type: str
    link_customer_id: str | None = None
    link_month: str | None = None
    # Onderscheidt de bureaubrede signalen van dezelfde soort (Search Console, ProRankTracker).
    bureau_key: str | None = None

    @property
    def id(self) -> str:
        if self.customer_id:
            return f"{self.kind}:{self.customer_id}"
        return f"{self.kind}:{BUREAU}:{self.bureau_key}" if self.bureau_key else f"{self.kind}:{BUREAU}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "severity": self.severity,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "text": self.text,
            "link": {
                "type": self.link_type,
                "customer_id": self.link_customer_id,
                "month": self.link_month,
            },
        }


# --- teksten ----------------------------------------------------------------------------

def with_more(first: str, others: int) -> str:
    """De eerste zin, met "(en N andere)" als er meer is."""
    return f"{first} (en {others} andere)" if others > 0 else first


def short_date(day: date) -> str:
    """"18 nov"."""
    return f"{day.day} {MONTH_SHORT[day.month - 1]}"


def month_name(month: str) -> str:
    """"2026-10" → "oktober"."""
    return MONTH_NAMES[int(month[5:7]) - 1]


def _cards(count: int) -> str:
    return "1 kaart staat" if count == 1 else f"{count} kaarten staan"


def drop_text(drop: dict[str, Any]) -> str:
    keyword = drop.get("keyword") or ""
    rank = drop.get("rank")
    month = drop.get("month_ago_rank")
    if rank is None:
        return f'"{keyword}" uit de top 100 gezakt (was #{month})'
    return f'"{keyword}" gezakt van #{month} naar #{rank}'


def scan_failed_text(phase: int, day: date | None) -> str:
    label = PHASE_LABELS.get(phase, "Scan")
    return f"{label} mislukt op {short_date(day)}" if day else f"{label} mislukt"


def monitor_failed_text(day: date | None) -> str:
    return f"{MONITOR_FAILED} op {short_date(day)}" if day else MONITOR_FAILED


# --- signalen ---------------------------------------------------------------------------

def _signal(kind: str, customer_id: str, customer_name: str, text: str, link_type: str,
            *, month: str | None = None, severity: str | None = None) -> Signal:
    return Signal(
        kind=kind,
        severity=severity or KIND_SEVERITY[kind],
        customer_id=customer_id,
        customer_name=customer_name,
        text=text,
        link_type=link_type,
        link_customer_id=customer_id,
        link_month=month,
    )


def drop_signal(customer_id: str, customer_name: str, drops: list[dict[str, Any]] | None) -> Signal | None:
    """Daling: de grootste daling in de zin, de rest als "(en N andere)"."""
    drops = [d for d in drops or [] if isinstance(d, dict)]
    if not drops:
        return None
    return _signal(KIND_DROP, customer_id, customer_name,
                   with_more(drop_text(drops[0]), len(drops) - 1), LINK_CUSTOMER_HOME)


def failure_signal(customer_id: str, customer_name: str, problems: list[Problem]) -> Signal | None:
    """Storing: het eerste probleem bepaalt de zin en de link."""
    if not problems:
        return None
    first = problems[0]
    return _signal(KIND_FAILURE, customer_id, customer_name,
                   with_more(first.text, len(problems) - 1), first.link_type)


def work_signal(customer_id: str, customer_name: str, review_stale: int, todo_stale: int) -> Signal | None:
    """Werk: kaarten die vastlopen in Review of (ernst hoog) in Te doen."""
    if review_stale > 0:
        text = with_more(f"{_cards(review_stale)} langer dan {REVIEW_STALE_DAYS} dagen in Review", todo_stale)
    elif todo_stale > 0:
        text = (f"{_cards(todo_stale)} met hoge prioriteit langer dan {TODO_HIGH_STALE_DAYS} dagen "
                "in Te doen")
    else:
        return None
    return _signal(KIND_WORK, customer_id, customer_name, text, LINK_WORK_BOARD)


def report_signal(
    customer_id: str, customer_name: str, *, month: str, status: str | None, today: date
) -> Signal | None:
    """Rapport van `month` (de vorige maand). `status` is die van het rapport, None = er is er geen.

    Mislukt: de hele maand een signaal. Anders alleen in dag 1–REPORT_DUE_DAY zolang het niet
    voltooid is.
    """
    name = month_name(month)
    if status == "failed":
        text = f"Maandrapport {name} is mislukt; maak het opnieuw"
    elif status == "completed" or today.day > REPORT_DUE_DAY:
        return None
    else:
        state = "nog niet klaar" if status in ("pending", "collecting", "writing") else "nog niet gemaakt"
        text = (f"Maandrapport {name} {state}; de posities gelden t/m {REPORT_DUE_DAY} "
                f"{MONTH_NAMES[today.month - 1]}")
    return _signal(KIND_REPORT, customer_id, customer_name, text, LINK_MONTHLY_REPORT, month=month)


def bureau_signal(bureau_key: str, text: str) -> Signal:
    """Storing van een koppeling van het hele bureau: geen klant en geen link."""
    return Signal(
        kind=KIND_FAILURE,
        severity=SEVERITY_HIGH,
        customer_id=None,
        customer_name=None,
        text=text,
        link_type=LINK_NONE,
        bureau_key=bureau_key,
    )


# --- volgorde ---------------------------------------------------------------------------

_SEVERITY_ORDER = {severity: index for index, severity in enumerate(SEVERITIES)}
_KIND_ORDER = {kind: index for index, kind in enumerate(KINDS)}


def sort_key(signal: Signal) -> tuple[Any, ...]:
    """Ernst (hoog eerst), dan soort (daling, storing, werk, rapport), dan klantnaam.

    Een bureaubreed signaal (zonder klantnaam) staat binnen zijn soort vooraan."""
    return (
        _SEVERITY_ORDER.get(signal.severity, len(SEVERITIES)),
        _KIND_ORDER.get(signal.kind, len(KINDS)),
        signal.customer_name is not None,
        (signal.customer_name or "").casefold(),
        signal.id,
    )


def sort_signals(signals: list[Signal]) -> list[Signal]:
    return sorted(signals, key=sort_key)


__all__ = [
    "KINDS",
    "Problem",
    "Signal",
    "bureau_signal",
    "drop_signal",
    "failure_signal",
    "report_signal",
    "sort_signals",
    "work_signal",
]
