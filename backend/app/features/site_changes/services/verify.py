"""Live-controle: staat een goedgekeurde wijziging echt op de pagina, en treden actiepunten nog op?

Eén fetch per pagina (met cache-buster, zodat een paginacache de verse versie geeft), daarna
`extract_page` / `extract_content`. Voor actiepunten bouwen we van de verse pagina een NIET
opgeslagen `LaunchScanPage`, zoals de sitemap-monitor, en draaien we `generate_page_issues`.
Er wordt niets naar de site geschreven en er worden geen scan- of paginarijen opgeslagen.
"""
from __future__ import annotations

import html as html_lib
import posixpath
import re
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlparse

from app.db.models import LaunchScanPage
from app.features.launch_checklist.services import schema_markup
from app.features.launch_checklist.services.content_extract import extract_content
from app.features.launch_checklist.services.discovery import clean_url, root_domain_of, url_key
from app.features.launch_checklist.services.inventory import (
    PageRecord,
    _determine_indexability,
    _path_of,
    fill_from_html,
)
from app.features.launch_checklist.services.issues import generate_page_issues
from app.features.launch_checklist.services.rankmath_schema import with_cache_buster, without_cache_buster

# --- wat is controleerbaar -------------------------------------------------------

CHECKABLE_SUGGESTION_TOPICS = frozenset({
    "meta_title", "meta_description", "headings", "text", "faq", "image_alt", "internal_links",
})

# Actiepunten die PAGE_RULES (services/issues.py) voor één losse pagina kan opleveren.
# Niet: slow_response (één ongecachte fetch is geen eerlijke meting), dubbele titels/meta/H1
# (sitebreed), hreflang, robots.txt, Core Web Vitals, Ahrefs-backlinks, AI- en fase 3/4-punten.
CHECKABLE_ISSUE_TYPES = frozenset({
    "fetch_error", "status_4xx", "status_5xx",
    "redirect_in_sitemap", "redirect_chain",
    "noindex_in_sitemap", "canonical_mismatch",
    "title_missing", "title_too_long", "title_too_short",
    "meta_missing", "meta_too_long", "meta_too_short",
    "h1_missing", "h1_multiple",
    "thin_content", "images_missing_alt",
    "broken_links", "lang_missing", "og_incomplete",
})
# Stuurt de pagina door, dan zijn alleen deze types op déze URL te beoordelen.
REDIRECT_DETERMINABLE_TYPES = frozenset({
    "fetch_error", "status_4xx", "status_5xx", "redirect_in_sitemap", "redirect_chain",
    "noindex_in_sitemap", "canonical_mismatch",
})

LIVE_VALUE_MAX = 300
MIN_LINE_CHARS = 4

_PAGE_FIELDS = {c.key for c in LaunchScanPage.__table__.columns} - {"id", "scan_id", "created_at"}
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]*)[^)]*\)")
_LINK_TARGET = re.compile(r"\]\(([^)\s]+)")
_PLACEHOLDER = re.compile(r"\[[^\]]*\]")
_LINE_PREFIX = re.compile(r"^\s*(?:#{1,6}\s+|[-*+•]\s+|>\s*)+")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}")
_WS = re.compile(r"\s+")
_PUNCT = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "­": "",
})
_WP_SIZE = re.compile(r"-(?:\d+x\d+|scaled)$")
_ALT_LINE = re.compile(r"^\s*alt\s*:\s*(.*)$", re.IGNORECASE)
_FILENAME_LINE = re.compile(r"^\s*bestandsnaam\s*:\s*(.*)$", re.IGNORECASE)


class LiveFetchError(Exception):
    """De pagina kon niet worden opgehaald (time-out, 4xx/5xx, geen HTML, onveilige URL)."""


# --- normaliseren ---------------------------------------------------------------

def normalize(text: str | None) -> str:
    """HTML-entities, markdown-tekens, NFKC, typografische tekens, witruimte en hoofdletters."""
    value = html_lib.unescape(str(text or ""))
    value = unicodedata.normalize("NFKC", value).translate(_PUNCT)
    value = _MD_LINK.sub(r"\1", value)
    value = _LINE_PREFIX.sub("", value)
    value = value.replace("**", "").replace("__", "").replace("*", "").replace("`", "")
    return _WS.sub(" ", value).strip().lower()


def clip(value: str | None, limit: int = LIVE_VALUE_MAX) -> str | None:
    if value is None:
        return None
    value = _WS.sub(" ", value).strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


# --- de live pagina ---------------------------------------------------------------

@dataclass
class LivePage:
    url: str
    final_url: str
    redirected: bool
    title: str | None
    meta_description: str | None
    headings: list[str]
    body_lines: list[str]
    images: list[dict[str, Any]]
    link_keys: set[str]
    record: PageRecord
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def haystack(self) -> str:
        lines = [normalize(h) for h in self.headings] + [normalize(line) for line in self.body_lines]
        return "\n".join(line for line in lines if line)


def fetch_live(url: str) -> LivePage:
    """Haal de pagina één keer op en lees titel, meta, koppen, tekst, afbeeldingen en links."""
    try:
        fetched = schema_markup.fetch_page(with_cache_buster(url))
    except schema_markup.SchemaMarkupError as exc:
        raise LiveFetchError(str(exc)) from exc
    return parse_live(url, fetched)


def parse_live(url: str, fetched: schema_markup.FetchedPage) -> LivePage:
    final_url = without_cache_buster(fetched.final_url)
    root_domain = root_domain_of(final_url) or urlparse(final_url).netloc
    content = extract_content(fetched.html, final_url, root_domain)

    # Pagina-object zoals inventory.fetch_page het opbouwt (niet opgeslagen).
    rec = PageRecord(url=url, path=_path_of(url), in_sitemap=True)
    chain = [
        {"url": without_cache_buster(hop["url"]), "status": hop["status"],
         "location": without_cache_buster(hop["location"]) if hop.get("location") else None}
        for hop in fetched.redirects
    ]
    rec.final_url = final_url
    rec.final_status = 200
    rec.status_code = chain[0]["status"] if chain else 200
    content_type = (fetched.headers.get("content-type") or "").split(";")[0].strip()
    rec.content_type = content_type or "text/html"
    rec.size_bytes = len(fetched.html.encode("utf-8", errors="replace"))
    if chain:
        chain.append({"url": final_url, "status": 200, "final": True})
        rec.redirect_chain = chain
    else:
        fill_from_html(rec, fetched.html, root_domain)
    _determine_indexability(rec, fetched.headers.get("x-robots-tag", ""))

    link_keys = {url_key(link["url"]) for link in content.links if link.get("url")}
    link_keys |= {url_key(target) for target in rec.internal_targets}
    return LivePage(
        url=url, final_url=final_url, redirected=bool(chain),
        title=content.title, meta_description=content.meta_description,
        headings=[str(h.get("text") or "") for h in content.headings],
        body_lines=[line for line in (content.body_text or "").splitlines() if line.strip()],
        images=list(content.images), link_keys=link_keys, record=rec,
    )


def scan_page_of(live: LivePage, broken_candidates: list[dict[str, Any]]) -> LaunchScanPage:
    """Niet-opgeslagen pagina-object voor de paginaregels.

    Kapotte links: we halen de doelen niet opnieuw op; een eerder gemelde kapotte link telt
    nog als kapot zolang de pagina er naar linkt.
    """
    rec = live.record
    rec.broken_links = [
        link for link in broken_candidates
        if isinstance(link, dict) and link.get("url") and url_key(str(link["url"])) in live.link_keys
    ][:50]
    data = {k: v for k, v in asdict(rec).items() if k in _PAGE_FIELDS}
    return LaunchScanPage(id=str(uuid.uuid4()), scan_id="", **data)


def live_issue_types(live: LivePage, broken_candidates: list[dict[str, Any]]) -> set[str]:
    """issue_types die PAGE_RULES nu op de live pagina geven."""
    page = scan_page_of(live, broken_candidates)
    return {issue["issue_type"] for issue in generate_page_issues([page])}


def determinable_types(live: LivePage) -> frozenset[str]:
    return REDIRECT_DETERMINABLE_TYPES if live.redirected else CHECKABLE_ISSUE_TYPES


# --- controleerbaar? ----------------------------------------------------------------

def link_targets(value: str | None, page_url: str) -> set[str]:
    keys: set[str] = set()
    for target in _LINK_TARGET.findall(value or ""):
        absolute = clean_url(target, page_url)
        if absolute:
            keys.add(url_key(absolute))
    return keys


def suggestion_checkable(topic: str, ref: str | None, value: str | None, page_url: str) -> bool:
    if topic not in CHECKABLE_SUGGESTION_TOPICS:
        return False
    if topic == "image_alt":
        return bool(ref)
    if topic == "internal_links":
        # Alleen een voorstel dat zelf de link naar `ref` bevat (niet "link hierheen vanaf ...").
        target = clean_url(ref or "", page_url)
        return bool(target) and url_key(target) in link_targets(value, page_url)
    return True


def issue_checkable(issue_type: str) -> bool:
    return issue_type in CHECKABLE_ISSUE_TYPES


# --- waardecontrole voor voorstellen -----------------------------------------------

@dataclass
class CheckResult:
    found: bool
    message: str | None = None
    live_value: str | None = None
    missing: list[str] = field(default_factory=list)


def _line_fragments(raw: str) -> tuple[str, list[str]]:
    """(weergaveregel, genormaliseerde stukken die op de pagina moeten staan) voor één regel."""
    line = _MD_LINK.sub(r"\1", raw)
    line = _LINE_PREFIX.sub("", line).replace("**", "").replace("__", "").replace("`", "").strip()
    if line.startswith("|"):
        parts = [cell for cell in line.strip("|").split("|")]
    else:
        # Plaatshouders voor de klant ([...]) staan niet letterlijk op de pagina.
        parts = _PLACEHOLDER.split(line)
    fragments = [normalize(part) for part in parts]
    return line, [f for f in fragments if len(f) >= MIN_LINE_CHARS]


def expected_lines(value: str) -> list[tuple[str, list[str]]]:
    out: list[tuple[str, list[str]]] = []
    for raw in (value or "").splitlines():
        if not raw.strip() or _TABLE_SEPARATOR.match(raw):
            continue
        display, fragments = _line_fragments(raw)
        if fragments:
            out.append((display, fragments))
    return out


def _check_text(value: str, live: LivePage) -> CheckResult:
    haystack = live.haystack()
    lines = expected_lines(value)
    if not lines:
        return CheckResult(False, "De goedgekeurde tekst bevat niets om te controleren.")
    missing = [display for display, fragments in lines if not all(f in haystack for f in fragments)]
    if not missing:
        return CheckResult(True, "Alle regels staan op de live pagina.")
    found = len(lines) - len(missing)
    return CheckResult(
        False,
        f"Nog niet live: {len(missing)} van de {len(lines)} regels niet gevonden op de pagina."
        if found else "Nog niet live: de tekst staat niet op de pagina.",
        missing=[clip(m, 200) or "" for m in missing],
    )


def parse_alt(value: str) -> tuple[str | None, str | None]:
    """(alt-tekst, nieuwe bestandsnaam) uit "alt: ...\\nbestandsnaam: ..."."""
    alt: str | None = None
    filename: str | None = None
    for line in (value or "").splitlines():
        if (m := _ALT_LINE.match(line)) and alt is None:
            alt = m.group(1).strip()
        elif (m := _FILENAME_LINE.match(line)) and filename is None:
            filename = m.group(1).strip() or None
    if alt is None:
        first = next((line.strip() for line in (value or "").splitlines() if line.strip()), "")
        alt = first
    if alt in ('""', "''"):
        alt = ""
    elif len(alt) >= 2 and alt[0] == alt[-1] and alt[0] in "\"'":
        alt = alt[1:-1]
    return alt, filename


def image_stem(name_or_url: str) -> str:
    """Bestandsnaam zonder extensie en zonder WordPress-maatachtervoegsel (-300x200, -scaled)."""
    name = unquote(posixpath.basename(urlparse(name_or_url).path or name_or_url)).lower()
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return _WP_SIZE.sub("", stem)


def _check_alt(value: str, ref: str, live: LivePage) -> CheckResult:
    expected, new_filename = parse_alt(value)
    ref_abs = clean_url(ref, live.final_url) or ref
    ref_key = url_key(ref_abs)
    stems = {s for s in (image_stem(ref_abs), image_stem(new_filename) if new_filename else "") if s}
    matches = [
        img for img in live.images
        if url_key(str(img.get("src") or "")) == ref_key or image_stem(str(img.get("src") or "")) in stems
    ]
    if not matches:
        return CheckResult(False, "Nog niet live: de afbeelding staat niet (meer) op de pagina.")
    want = normalize(expected)
    for img in matches:
        if img.get("alt") is not None and normalize(img.get("alt")) == want:
            return CheckResult(True, "De alt-tekst staat op de afbeelding.", live_value=clip(img.get("alt")))
    current = matches[0].get("alt")
    return CheckResult(
        False,
        "Nog niet live: de afbeelding heeft geen alt-tekst." if current is None
        else "Nog niet live: de afbeelding heeft een andere alt-tekst.",
        live_value=clip(current),
    )


def _check_link(ref: str, live: LivePage) -> CheckResult:
    target = clean_url(ref, live.final_url)
    if target and url_key(target) in live.link_keys:
        return CheckResult(True, "De link staat op de pagina.")
    return CheckResult(False, f"Nog niet live: geen link naar {ref} gevonden op de pagina.")


def check_suggestion(topic: str, value: str, ref: str | None, live: LivePage) -> CheckResult:
    """Staat de goedgekeurde waarde op de live pagina?"""
    if topic == "meta_title":
        live_title, want = normalize(live.title), normalize(value)
        if want and (live_title == want or live_title.startswith(want)):
            return CheckResult(True, "De title staat op de pagina.", live_value=clip(live.title))
        return CheckResult(False, "Nog niet live: op de pagina staat een andere title."
                           if live.title else "Nog niet live: de pagina heeft geen title.",
                           live_value=clip(live.title))
    if topic == "meta_description":
        if normalize(live.meta_description) == normalize(value) and normalize(value):
            return CheckResult(True, "De meta description staat op de pagina.",
                               live_value=clip(live.meta_description))
        return CheckResult(False, "Nog niet live: op de pagina staat een andere meta description."
                           if live.meta_description else "Nog niet live: de pagina heeft geen meta description.",
                           live_value=clip(live.meta_description))
    if topic in {"headings", "text", "faq"}:
        return _check_text(value, live)
    if topic == "image_alt" and ref:
        return _check_alt(value, ref, live)
    if topic == "internal_links" and ref:
        return _check_link(ref, live)
    return CheckResult(False, "Dit punt is niet automatisch te controleren.")


def detail_of(result: CheckResult, checked_at: datetime) -> dict[str, Any]:
    return {
        "checked_at": checked_at.isoformat(),
        "message": result.message,
        "live_value": result.live_value,
        "missing": list(result.missing),
    }
