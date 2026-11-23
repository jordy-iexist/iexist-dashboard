"""Vergelijking "Jij vs. de top X": metrieken per pagina, de mediaanrij en de rode vlaggen.

Werkt op de paginarijen van één zoekwoord: objecten met de attributen van
`CompetitorAnalysisPage` (`id`, `is_own`, `position`, `url`, `domain`, `page_type`,
`is_excluded`, `exclude_reason`, `fetch_status`, `onpage` (dict of `OnPage`), `refdomains`,
`domain_rating`, `lcp_ms`). In tests volstaat een `SimpleNamespace`; ontbrekende attributen
gelden als leeg.

Wie telt mee in de mediaan:
- Alleen concurrenten (`is_own` False) die niet zijn uitgesloten (`is_excluded` False).
- On-page-waarden (woorden, H2's, FAQ, schema) alleen bij `fetch_status == "ok"` en een
  leesbare pagina (zie `page_facts.is_unreadable`).
- DR, verwijzende domeinen en LCP tellen mee zodra ze er zijn: die komen van Ahrefs en
  PageSpeed, niet uit onze eigen ophaalpoging.
Een mediaan bestaat pas bij minimaal `MIN_MEDIAN_VALUES` waarden; anders is hij `None` ("—").

Puur: geen database, geen netwerk. De router rekent hiermee bij het lezen, de taak gebruikt
`metrics_table` als feitenblok in de Claude-prompt.
"""
from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse

from app.features.competitor_analysis.schemas import FLAG_METRICS, FlagMetric, MedianRow, OnPage
from app.features.competitor_analysis.services.page_facts import as_onpage, is_unreadable

# --- Drempels ---------------------------------------------------------------------------------

# Minimaal aantal waarden voor een mediaan (en voor de FAQ/Schema-regel).
MIN_MEDIAN_VALUES = 3

# Hoger is beter (woorden, H2's, verwijzende domeinen, DR): rood als de eigen waarde onder
# 75% van de mediaan ligt én het verschil minstens de ondergrens is.
HIGHER_IS_BETTER: tuple[FlagMetric, ...] = ("words", "h2_count", "refdomains", "domain_rating")
BELOW_MEDIAN_RATIO = 0.75
MIN_GAP: dict[str, float] = {"words": 150, "h2_count": 2, "refdomains": 3, "domain_rating": 5}

# LCP (lager is beter): rood boven 125% van de mediaan én boven de grens voor "goed" (2,5 s).
LCP_ABOVE_MEDIAN_RATIO = 1.25
LCP_GOOD_MS = 2500

# FAQ en Schema: rood als de eigen pagina het mist en minstens deze fractie van de
# meegetelde concurrenten het heeft.
PRESENCE_SHARE = 0.5

# Schema-types die bijna elke site via een SEO-plugin of thema op elke pagina heeft, plus
# hulptypes die alleen genest voorkomen. Die zeggen niets over de pagina zelf; "heeft schema"
# betekent dus: minstens één type buiten deze lijst (bijv. Service, LocalBusiness, FAQPage,
# Product, Article, Review).
GENERIC_SCHEMA_TYPES = frozenset({
    "WebSite", "WebPage", "CollectionPage", "ItemPage", "AboutPage", "ContactPage",
    "ProfilePage", "SearchResultsPage", "CheckoutPage", "Organization", "BreadcrumbList",
    "ListItem", "ImageObject", "SearchAction", "EntryPoint", "PropertyValueSpecification",
    "ReadAction", "SiteNavigationElement", "WPHeader", "WPFooter", "WPSideBar",
    "PostalAddress", "ContactPoint", "GeoCoordinates", "OpeningHoursSpecification",
    "Place", "Language", "Thing", "CreativeWork", "WebPageElement", "VideoObject",
    # Onderdelen van FAQPage, adressen en doelgroepen: alleen genest, zeggen zelf niets.
    "Question", "Answer", "City", "Country", "State", "AdministrativeArea", "Audience",
    "BusinessAudience", "Rating", "MonetaryAmount", "QuantitativeValue", "PropertyValue",
    "UnitPriceSpecification", "PriceSpecification",
})
MAX_SCHEMA_TYPES_SHOWN = 10

# Korte id's in het feitenblok en in de Claude-prompt.
OWN_ID = "EIGEN"
COMPETITOR_PREFIX = "P"

_STATUS_LABELS = {
    "blocked": "niet opgehaald (geblokkeerd)",
    "not_html": "niet opgehaald (geen HTML)",
    "error": "niet opgehaald (fout)",
}
_EXCLUDE_LABELS = {"aggregator": "vergelijkingssite/gids", "own_site": "eigen site"}
PAGE_TYPE_PLURALS: dict[str, str] = {
    "dienst": "dienstpagina's", "product": "productpagina's", "categorie": "categoriepagina's",
    "blog": "blogs/artikelen", "vergelijker": "vergelijkingssites/gidsen", "homepage": "homepages",
    "overig": "overige pagina's",
}
METRIC_LABELS: dict[str, str] = {
    "words": "woorden", "h2_count": "H2's", "faq": "FAQ", "schema": "schema",
    "refdomains": "verwijzende domeinen", "domain_rating": "DR", "lcp_ms": "LCP",
}


# --- Kleine hulpjes ---------------------------------------------------------------------------


def _get(page: Any, name: str) -> Any:
    return getattr(page, name, None)


def is_own(page: Any) -> bool:
    return bool(_get(page, "is_own"))


def is_excluded(page: Any) -> bool:
    return bool(_get(page, "is_excluded"))


def onpage_of(page: Any) -> OnPage | None:
    """De uitgelezen on-page-gegevens als `OnPage`, of `None`."""
    return as_onpage(_get(page, "onpage"))


def onpage_usable(page: Any) -> bool:
    """Opgehaald (`fetch_status == "ok"`), uitgelezen en leesbaar: on-page telt mee."""
    onpage = onpage_of(page)
    return _get(page, "fetch_status") == "ok" and onpage is not None and not is_unreadable(onpage)


def content_schema_types(types: Iterable[str] | None) -> list[str]:
    """Schema-types die iets over de pagina zeggen (zonder `GENERIC_SCHEMA_TYPES`), gesorteerd."""
    return sorted({t for t in types or [] if t and t not in GENERIC_SCHEMA_TYPES})


def domain_of(page: Any) -> str:
    """Domein zonder "www." (uit `domain`, anders uit de URL)."""
    domain = _get(page, "domain") or urlparse(str(_get(page, "url") or "")).netloc
    domain = str(domain).lower()
    return domain[4:] if domain.startswith("www.") else domain


def competitors(pages: Iterable[Any]) -> list[Any]:
    """Concurrenten in SERP-volgorde (zonder eigen pagina), uitgesloten pagina's inbegrepen."""
    rows = [p for p in pages if not is_own(p)]
    return sorted(rows, key=lambda p: (_get(p, "position") is None, _get(p, "position") or 0, str(_get(p, "url"))))


def own_page(pages: Iterable[Any]) -> Any | None:
    """De eigen doelpagina, of `None` (nieuwe pagina)."""
    return next((p for p in pages if is_own(p)), None)


def counted_competitors(pages: Iterable[Any]) -> list[Any]:
    """Concurrenten die meetellen: niet uitgesloten (on-page-filter apart, zie `onpage_usable`)."""
    return [p for p in competitors(pages) if not is_excluded(p)]


# --- Metrieken --------------------------------------------------------------------------------


def metrics(page: Any) -> dict[FlagMetric, Any]:
    """De zeven vergelijkingswaarden van één pagina; `None` waar onbekend.

    `words`/`h2_count` zijn getallen, `faq`/`schema` booleans ("heeft relevant schema", zie
    `GENERIC_SCHEMA_TYPES`). On-page-waarden zijn er zodra de pagina is opgehaald en
    uitgelezen, ook als hij onleesbaar is (de tabel toont ze dan met een markering);
    de mediaan en de vlaggen gebruiken ze alleen als `onpage_usable(page)`.
    """
    onpage = onpage_of(page) if _get(page, "fetch_status") == "ok" else None
    return {
        "words": onpage.word_count if onpage else None,
        "h2_count": onpage.h2_count if onpage else None,
        "faq": onpage.has_faq if onpage else None,
        "schema": bool(content_schema_types(onpage.schema_types)) if onpage else None,
        "refdomains": _get(page, "refdomains"),
        "domain_rating": _get(page, "domain_rating"),
        "lcp_ms": _get(page, "lcp_ms"),
    }


def _median(values: list[float]) -> float | None:
    return float(median(values)) if len(values) >= MIN_MEDIAN_VALUES else None


def median_row(pages: Iterable[Any]) -> MedianRow:
    """Mediaanrij over de meegetelde concurrenten van één zoekwoord.

    - `words`, `h2_count`, `faq_count`, `schema_count`, `schema_top` en `total`: over de
      niet-uitgesloten concurrenten waarvan de on-page meetelt (`onpage_usable`).
    - `refdomains`, `domain_rating`, `lcp_ms`: over alle niet-uitgesloten concurrenten met een
      waarde.
    - `schema_top`: het vaakst voorkomende relevante schema-type (bij gelijkstand alfabetisch;
      alleen als minstens twee pagina's het hebben).
    """
    rows = counted_competitors(pages)
    usable = [p for p in rows if onpage_usable(p)]
    measured = [metrics(p) for p in rows]
    onpage_metrics = [metrics(p) for p in usable]

    def values(source: list[dict[str, Any]], key: str) -> list[float]:
        return [float(m[key]) for m in source if isinstance(m.get(key), (int, float)) and not isinstance(m.get(key), bool)]

    schema_counter: Counter[str] = Counter()
    for page in usable:
        schema_counter.update(content_schema_types(onpage_of(page).schema_types))
    schema_top = min(schema_counter.items(), key=lambda item: (-item[1], item[0]))[0] if schema_counter else None
    # Eén pagina met een type is geen patroon: pas noemen als minstens twee pagina's het hebben.
    if schema_top is not None and schema_counter[schema_top] < 2:
        schema_top = None

    return MedianRow(
        words=_median(values(onpage_metrics, "words")),
        h2_count=_median(values(onpage_metrics, "h2_count")),
        refdomains=_median(values(measured, "refdomains")),
        domain_rating=_median(values(measured, "domain_rating")),
        lcp_ms=_median(values(measured, "lcp_ms")),
        faq_count=sum(1 for m in onpage_metrics if m["faq"]),
        schema_count=sum(1 for m in onpage_metrics if m["schema"]),
        schema_top=schema_top,
        total=len(usable),
    )


# --- Rode vlaggen -----------------------------------------------------------------------------


def _below_median(metric: str, own: Any, med: float | None) -> bool:
    if own is None or med is None:
        return False
    return own < med * BELOW_MEDIAN_RATIO and (med - own) >= MIN_GAP[metric]


def _lcp_slow(own: Any, med: float | None) -> bool:
    if own is None or med is None:
        return False
    return own > med * LCP_ABOVE_MEDIAN_RATIO and own > LCP_GOOD_MS


def _missing_common(own_has: bool | None, count: int, total: int) -> bool:
    if own_has is None or own_has or total < MIN_MEDIAN_VALUES:
        return False
    return count >= total * PRESENCE_SHARE


def flags(own: Any | None, median: MedianRow) -> dict[FlagMetric, bool]:
    """Per metriek of de eigen pagina "duidelijk onder de mediaan" zit (True = rood).

    `own` is de eigen paginarij (of `None` bij een nieuwe pagina: dan is niets rood). Een
    onbekende eigen waarde of een ontbrekende mediaan geeft nooit rood. On-page-waarden van
    de eigen pagina tellen alleen als die pagina is opgehaald en leesbaar is.
    """
    result: dict[FlagMetric, bool] = {metric: False for metric in FLAG_METRICS}
    if own is None:
        return result
    values = metrics(own)
    if not onpage_usable(own):
        for key in ("words", "h2_count", "faq", "schema"):
            values[key] = None
    for metric in HIGHER_IS_BETTER:
        result[metric] = _below_median(metric, values[metric], getattr(median, metric))
    result["lcp_ms"] = _lcp_slow(values["lcp_ms"], median.lcp_ms)
    result["faq"] = _missing_common(values["faq"], median.faq_count, median.total)
    result["schema"] = _missing_common(values["schema"], median.schema_count, median.total)
    return result


# --- Feitenblok voor de prompt ----------------------------------------------------------------


def short_ids(pages: Iterable[Any]) -> dict[str, str]:
    """Korte id per pagina (`page.id` → "P1", "P2", ... in SERP-volgorde; de eigen pagina "EIGEN").

    Dezelfde id's staan in het feitenblok en in de paginablokken van de Claude-prompt.
    """
    pages = list(pages)
    ids: dict[str, str] = {}
    for index, page in enumerate(competitors(pages), start=1):
        ids[str(_get(page, "id"))] = f"{COMPETITOR_PREFIX}{index}"
    own_rows = [p for p in pages if is_own(p)]
    for index, page in enumerate(own_rows):
        ids[str(_get(page, "id"))] = OWN_ID if index == 0 else f"{OWN_ID}{index + 1}"
    return ids


def _num(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "ja" if value else "nee"
    number = float(value)
    # Nederlandse decimale komma, zodat Claude het getal zo overneemt.
    return str(int(number)) if number.is_integer() else f"{number:.1f}".replace(".", ",")


def _status(page: Any) -> str:
    if is_excluded(page):
        reason = _EXCLUDE_LABELS.get(str(_get(page, "exclude_reason")), "uitgesloten")
        return f"uitgesloten: {reason}"
    fetch_status = _get(page, "fetch_status")
    if fetch_status is None:
        return "niet opgehaald"
    if fetch_status != "ok":
        return _STATUS_LABELS.get(fetch_status, "niet opgehaald")
    if onpage_of(page) is None:
        return "niet uitgelezen"
    if is_unreadable(onpage_of(page)):
        return "mogelijk niet leesbaar (<50 woorden, telt niet mee)"
    return "meegeteld"


def _schema_cell(page: Any) -> str:
    onpage = onpage_of(page) if _get(page, "fetch_status") == "ok" else None
    if onpage is None:
        return "—"
    types = content_schema_types(onpage.schema_types)
    if not types:
        return "nee"
    # Alle types tonen (tot een ruime grens): een afgekapte lijst leest als "heeft het niet".
    shown = types[:MAX_SCHEMA_TYPES_SHOWN]
    rest = len(types) - len(shown)
    return ", ".join(shown) + (f" (+{rest})" if rest else "")


def _page_line(short_id: str, page: Any, red: dict[FlagMetric, bool] | None = None) -> str:
    m = metrics(page)
    red = red or {}

    def cell(metric: FlagMetric, text: str) -> str:
        return f"{text} [ROOD]" if red.get(metric) else text

    return " | ".join([
        short_id,
        _num(_get(page, "position")),
        domain_of(page) or "—",
        str(_get(page, "url") or "—"),
        str(_get(page, "page_type") or "—"),
        cell("words", _num(m["words"])),
        cell("h2_count", _num(m["h2_count"])),
        cell("faq", _num(m["faq"])),
        cell("schema", _schema_cell(page)),
        cell("refdomains", _num(m["refdomains"])),
        cell("domain_rating", _num(m["domain_rating"])),
        cell("lcp_ms", _num(m["lcp_ms"])),
        _status(page),
    ])


def _composition(rows: list[Any]) -> str:
    types = Counter(str(_get(p, "page_type")) for p in rows if _get(p, "page_type"))
    parts = [
        f"{count} {PAGE_TYPE_PLURALS.get(name, name)}"
        for name, count in sorted(types.items(), key=lambda item: (-item[1], item[0]))
    ]
    unknown = sum(1 for p in rows if not _get(p, "page_type"))
    if unknown:
        parts.append(f"onbekend {unknown}")
    aggregators = sum(1 for p in rows if _get(p, "exclude_reason") == "aggregator")
    own_site = sum(1 for p in rows if _get(p, "exclude_reason") == "own_site")
    line = f"{len(rows)} pagina's van anderen in de top: {', '.join(parts) or '—'}."
    if aggregators:
        line += f" {aggregators} uitgesloten als vergelijkingssite/gids."
    if own_site:
        line += f" {own_site} van de eigen site (uitgesloten)."
    return line


def metrics_table(pages: Sequence[Any]) -> str:
    """Compacte teksttabel met alle cijfers van één zoekwoord, als vast feitenblok voor Claude.

    Per pagina: id, positie, domein, URL, type, woorden, H2's, FAQ, schema, verwijzende
    domeinen, DR, LCP en of hij meetelt. Daaronder de samenstelling, de mediaanrij en de
    eigen rij met `[ROOD]` bij de rode vlaggen (of "geen eigen pagina").
    """
    pages = list(pages)
    ids = short_ids(pages)
    rows = competitors(pages)
    med = median_row(pages)
    own = own_page(pages)

    lines = [
        "id | positie | domein | url | type | woorden | H2 | FAQ | schema | verw. domeinen | DR | LCP ms | status",
    ]
    lines += [_page_line(ids[str(_get(p, "id"))], p) for p in rows]
    lines.append("")
    lines.append(f"Samenstelling: {_composition(rows)}")
    lines.append(
        f"MEDIAAN over {med.total} meegetelde concurrenten (minimaal {MIN_MEDIAN_VALUES} waarden, anders —)"
        f" | woorden {_num(med.words)} | H2 {_num(med.h2_count)}"
        f" | FAQ bij {med.faq_count} van {med.total}"
        f" | schema bij {med.schema_count} van {med.total}"
        + (f" (meest: {med.schema_top})" if med.schema_top else "")
        + f" | verw. domeinen {_num(med.refdomains)} | DR {_num(med.domain_rating)} | LCP ms {_num(med.lcp_ms)}"
    )
    if own is None:
        lines.append(f"{OWN_ID}: geen eigen pagina; er komt een nieuwe pagina voor dit zoekwoord.")
    else:
        red = flags(own, med)
        lines.append(_page_line(ids[str(_get(own, "id"))], own, red))
        red_names = [METRIC_LABELS[name] for name in FLAG_METRICS if red[name]]
        lines.append(
            "Rode vlaggen eigen pagina (duidelijk slechter dan de mediaan): "
            + (", ".join(red_names) if red_names else "geen")
        )
    return "\n".join(lines)
