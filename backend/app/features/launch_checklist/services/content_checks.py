"""Fase 3: regelgebaseerde content- en onpage-checks.

Alles hier is puur: het leest alleen de opgeslagen pagina-inhoud
(`LaunchContentPage`-achtige objecten) en kan dus opnieuw draaien zonder de site
op te halen. Twee niveaus:

- `evaluate_pages`  → per pagina een resultaat per checklistpunt (`page.checks`).
- `aggregate_items` → per checklistpunt één status voor de hele site, waarbij
  openstaande AI-voorstellen meetellen.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Iterable
from urllib.parse import urlparse

from app.features.launch_checklist.services.content_checklist import (
    GAP_ITEM_KEYS,
    ITEMS,
    PAGE_ITEM_KEYS,
)
from app.features.launch_checklist.services.discovery import url_key
from app.features.launch_checklist.services.pixel_width import (
    DESCRIPTION_MAX_CHARS,
    DESCRIPTION_MAX_PX,
    TITLE_MAX_CHARS,
    TITLE_MAX_PX,
    description_width,
    title_width,
)

TITLE_MIN_CHARS = 30
DESCRIPTION_MIN_CHARS = 70
THIN_WORDS = 300
SCANNABLE_MIN_WORDS = 400
FIRST_PARAGRAPH_MAX_WORDS = 90
MAX_EVIDENCE_URLS = 25
MAX_LINK_DETAILS = 30
REDIRECTS_KEY = "c3_redirects_404"
META_FIXED_KEY = "c3_meta_fixed"

# Paginatypes (fase 2) waarop inhoudelijke punten van toepassing zijn.
CONTENT_TYPES = {"home", "dienst", "product", "categorie", "blog", "over_ons", "overig"}
APPLIES: dict[str, set[str]] = {
    "c3_keywords": CONTENT_TYPES,
    "c3_headings": CONTENT_TYPES | {"contact", "overzicht", "vacature"},
    "c3_scannable": {"dienst", "product", "categorie", "blog", "overig"},
    "c3_answer_first": {"dienst", "product", "categorie", "blog", "overig"},
    "c3_faq": {"dienst", "product", "categorie"},
    "c3_eeat": {"home", "dienst", "product", "over_ons", "blog"},
    "c3_conversion": {"home", "dienst", "product", "categorie", "blog"},
    "c3_internal_links": {"home", "dienst", "product", "categorie", "blog", "overig"},
}
# Fase-1 issue-types die `c3_meta_fixed` opnieuw controleert.
F1_META_TYPES = (
    "title_missing", "title_too_long", "title_too_short", "title_duplicate",
    "meta_missing", "meta_too_long", "meta_too_short", "meta_duplicate",
)

_WORD_RE = re.compile(r"[\wÀ-ÿ'-]+", re.UNICODE)
_GENERIC_ANCHORS = {
    "klik hier", "hier", "lees meer", "lees verder", "meer info", "meer informatie", "meer lezen",
    "bekijk", "bekijk meer", "meer", "link", "read more", "click here", "verder lezen",
    "ontdek meer", "meer weten", "klik", "deze pagina", "deze link", "info",
}
_GENERIC_FILENAME_RE = re.compile(
    r"^(img|dsc|dscn|dscf|image|afbeelding|foto|photo|pic|picture|screenshot|schermafbeelding|"
    r"schermopname|untitled|naamloos|whatsapp[-_ ]?image|pxl|mvimg|shutterstock|istock|"
    r"adobestock|pexels|unsplash|depositphotos|design|canva|banner|header|slide)[-_ ]?[\d\-_ ()]*$",
    re.IGNORECASE,
)
_PLACE_RE = re.compile(
    r"\b(?:in|te|regio|omgeving|rond)\s+((?:Den |De |Het |'s-|Sint |Nieuw |Oud )?[A-Z][\wÀ-ÿ'\-]{2,})"
)
_NOT_PLACES = {"nederland", "belgië", "belgie", "europa", "huis", "nl"}
# Grotere Nederlandse plaatsen: herkent locatiepagina's als /seo-bureau-apeldoorn/
# ook zonder "in <plaats>" in de titel. Niet uitputtend; de regex hierboven vangt de rest.
_PLACES = (
    "Alkmaar Almelo Almere Alphen aan den Rijn Amersfoort Amstelveen Amsterdam Apeldoorn Arnhem Assen "
    "Barneveld Bergen op Zoom Breda Bussum Capelle aan den IJssel Delft Den Bosch Den Haag Den Helder "
    "Deventer Doetinchem Dordrecht Drachten Dronten Ede Eindhoven Elburg Emmen Enschede Epe Ermelo "
    "Gorinchem Gouda Groningen Haarlem Haarlemmermeer Harderwijk Heerenveen Heerhugowaard Heerlen "
    "Helmond Hengelo Hilversum Hoofddorp Hoogeveen Hoorn Houten Kampen Katwijk Leeuwarden Leiden "
    "Leidschendam Lelystad Maastricht Meppel Middelburg Nieuwegein Nijkerk Nijmegen Nunspeet Oosterhout "
    "Oss Purmerend Putten Roermond Roosendaal Rotterdam Schiedam Sittard Soest Spijkenisse Tiel Tilburg "
    "Uden Utrecht Veenendaal Veldhoven Velsen Venlo Vlaardingen Vlissingen Wageningen Weert Woerden "
    "Zaandam Zaanstad Zeewolde Zeist Zoetermeer Zutphen Zwolle"
)
_KNOWN_PLACES: dict[str, str] = {}
_multi = ("Alphen aan den Rijn", "Bergen op Zoom", "Capelle aan den IJssel", "Den Bosch", "Den Haag", "Den Helder")
_rest = _PLACES
for _name in _multi:
    _rest = _rest.replace(_name, "")
    _KNOWN_PLACES[re.sub(r"[^a-z]+", "-", _name.lower())] = _name
for _name in _rest.split():
    _KNOWN_PLACES[_name.lower()] = _name
_REGION_RE = re.compile(r"\b(regio|omgeving|werkgebied|omstreken|omliggende)\b", re.IGNORECASE)
_FAQ_PATH_RE = re.compile(r"faq|veelgestelde|veel-gestelde", re.IGNORECASE)
_CASES_PATH_RE = re.compile(r"case|project|referentie|portfolio|klantverhal|ervaring", re.IGNORECASE)

Check = dict[str, Any]


def _c(status: str, message: str, details: Any = None) -> Check:
    return {"status": status, "message": message, "details": details}


def _r(status: str, message: str, evidence: list[Any] | None = None, details: Any = None) -> Check:
    return {"status": status, "message": message, "evidence": evidence or [], "details": details}


def _words(text: str | None) -> int:
    return len(_WORD_RE.findall(text or ""))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().replace("'", "")).strip("-")


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def is_bad(check: Check | None) -> bool:
    return bool(check) and check.get("status") in {"error", "warning"}


def detect_place(page: Any) -> str | None:
    """Plaatsnaam van een locatiepagina: staat in titel/H1 én in de URL."""
    if (page.page_type or "") in {"home", "blog", "juridisch", "contact", "archief", "vacature"}:
        return None
    path = urlparse(page.url).path.lower()
    h1 = " ".join((page.signals or {}).get("h1") or [])
    for source in (h1, page.title or ""):
        for match in _PLACE_RE.finditer(source):
            place = match.group(1).strip()
            if place.lower() in _NOT_PLACES:
                continue
            if _slug(place) and _slug(place) in path:
                return place
    # Bekende plaatsnaam als los woord in de URL én in titel/H1.
    padded = "-" + re.sub(r"[^a-z0-9]+", "-", path).strip("-") + "-"
    haystack = f"{h1} {page.title or ''}".lower()
    for slug, name in _KNOWN_PLACES.items():
        if f"-{slug}-" in padded and name.lower() in haystack:
            return name
    return None


def generic_filename(filename: str) -> bool:
    stem = filename.rsplit(".", 1)[0]
    if not stem:
        return True
    if _GENERIC_FILENAME_RE.match(stem):
        return True
    letters = sum(ch.isalpha() for ch in stem)
    if letters < 3:
        return True
    return bool(re.fullmatch(r"[a-f0-9\-_]{16,}", stem, re.IGNORECASE))


def images_needing_work(page: Any) -> list[dict[str, Any]]:
    """Inhoudsafbeeldingen zonder alt-attribuut of met nietszeggende bestandsnaam."""
    out: list[dict[str, Any]] = []
    for image in page.images or []:
        if not image.get("in_content"):
            continue
        missing_alt = image.get("alt") is None
        bad_name = generic_filename(image.get("filename") or "")
        if missing_alt or bad_name:
            out.append({**image, "missing_alt": missing_alt, "generic_filename": bad_name})
    return out


# --- per pagina --------------------------------------------------------------

def _meta_title(page: Any, duplicates: set[str]) -> Check:
    title = (page.title or "").strip()
    if not title:
        return _c("error", "Meta titel ontbreekt.")
    length, width = len(title), title_width(title)
    details = {"length": length, "pixels": width}
    problems: list[str] = []
    if length > TITLE_MAX_CHARS or width > TITLE_MAX_PX:
        problems.append(f"te lang ({length} tekens, ±{width} px; maximaal {TITLE_MAX_CHARS} tekens en {TITLE_MAX_PX} px)")
    elif length < TITLE_MIN_CHARS:
        problems.append(f"kort ({length} tekens)")
    if _norm(title) in duplicates:
        problems.append("komt op meerdere pagina's voor")
    if problems:
        return _c("warning", "Meta titel " + " en ".join(problems) + ".", details)
    return _c("ok", f"Meta titel in orde ({length} tekens, ±{width} px).", details)


def _meta_description(page: Any, duplicates: set[str]) -> Check:
    text = (page.meta_description or "").strip()
    if not text:
        return _c("error", "Meta description ontbreekt.")
    length, width = len(text), description_width(text)
    details = {"length": length, "pixels": width}
    problems: list[str] = []
    if length > DESCRIPTION_MAX_CHARS or width > DESCRIPTION_MAX_PX:
        problems.append(
            f"te lang ({length} tekens, ±{width} px; maximaal {DESCRIPTION_MAX_CHARS} tekens en {DESCRIPTION_MAX_PX} px)")
    elif length < DESCRIPTION_MIN_CHARS:
        problems.append(f"kort ({length} tekens)")
    if _norm(text) in duplicates:
        problems.append("komt op meerdere pagina's voor")
    if problems:
        return _c("warning", "Meta description " + " en ".join(problems) + ".", details)
    return _c("ok", f"Meta description in orde ({length} tekens, ±{width} px).", details)


def _headings(page: Any) -> Check:
    headings = page.headings or []
    h1_count = sum(1 for h in headings if h.get("level") == 1)
    if h1_count == 0:
        return _c("error", "Geen H1 in de inhoud.")
    problems: list[str] = []
    if h1_count > 1:
        problems.append(f"{h1_count} H1-koppen")
    previous = 0
    skips = 0
    for h in headings:
        level = int(h.get("level") or 0)
        if previous and level > previous + 1:
            skips += 1
        previous = level
    if skips:
        problems.append(f"{skips}× een kopniveau overgeslagen")
    if (page.word_count or 0) >= THIN_WORDS and not any(h.get("level") == 2 for h in headings):
        problems.append("geen tussenkoppen (H2)")
    if problems:
        return _c("warning", "Koppenstructuur: " + ", ".join(problems) + ".")
    return _c("unknown", "Koppenstructuur technisch in orde; duidelijkheid beoordeelt de AI-analyse.")


def _scannable(page: Any) -> Check:
    signals = page.signals or {}
    words = page.word_count or 0
    if words < SCANNABLE_MIN_WORDS:
        return _c("ok", f"Korte pagina ({words} woorden).")
    if not signals.get("lists") and not signals.get("tables"):
        return _c("warning", f"{words} woorden zonder lijsten of tabellen.")
    return _c("unknown", "Lijsten/tabellen aanwezig; of het genoeg is beoordeelt de AI-analyse.")


def _answer_first(page: Any) -> Check:
    first = page.first_paragraph
    if not first:
        return _c("warning", "Geen duidelijke eerste alinea gevonden onder de H1.")
    words = _words(first)
    if words > FIRST_PARAGRAPH_MAX_WORDS:
        return _c("warning", f"Eerste alinea is lang ({words} woorden); het antwoord staat waarschijnlijk niet direct bovenaan.")
    return _c("unknown", "Of de eerste alinea direct antwoord geeft, beoordeelt de AI-analyse.")


def _keywords(page: Any) -> Check:
    words = page.word_count or 0
    if words < THIN_WORDS:
        return _c("warning", f"Weinig tekst ({words} woorden).")
    return _c("unknown", "Zoekwoord, intentie en leesbaarheid beoordeelt de AI-analyse.")


def _faq(page: Any) -> Check:
    signals = page.signals or {}
    has_faq = (
        signals.get("has_faq_schema")
        or (signals.get("question_headings") or 0) >= 2
        or (signals.get("details_count") or 0) >= 2
    )
    if not has_faq:
        return _c("warning", "Geen FAQ op deze pagina gevonden.")
    return _c("unknown", "FAQ aanwezig; kwaliteit beoordeelt de AI-analyse.")


def _eeat(page: Any) -> Check:
    signals = page.signals or {}
    has_images = bool(signals.get("content_images"))
    has_reviews = bool(
        signals.get("rating_markers") or signals.get("has_review_schema") or signals.get("blockquotes"))
    details = {"content_images": has_images, "reviews": has_reviews,
               "author": bool(signals.get("author_markers"))}
    # Alleen een probleem als er geen enkel bewijs staat; de rest weegt de AI-analyse.
    if not has_images and not has_reviews:
        return _c("warning", "Geen foto's en geen reviews of klantuitspraken in de inhoud gevonden.", details)
    if (page.page_type or "") == "blog" and not details["author"]:
        return _c("warning", "Geen zichtbare auteur bij dit blog gevonden.", details)
    missing = [label for label, present in (("foto's", has_images), ("reviews", has_reviews)) if not present]
    suffix = f" (niet gevonden: {', '.join(missing)})" if missing else ""
    return _c("unknown", f"Vertrouwenssignalen beoordeelt de AI-analyse{suffix}.", details)


def _conversion(page: Any) -> Check:
    signals = page.signals or {}
    has_cta = (
        signals.get("cta_texts") or signals.get("forms")
        or signals.get("tel_links") or signals.get("mailto_links")
    )
    if not has_cta:
        return _c("warning", "Geen call-to-action, formulier of contactlink in de inhoud gevonden.")
    return _c("unknown", "Call-to-action aanwezig; het conversiepad beoordeelt de AI-analyse.",
              {"cta_texts": signals.get("cta_texts") or []})


def _internal_links(page: Any, inlinks: int, links_to_service: bool) -> Check:
    content_links = [l for l in (page.links or []) if l.get("in_content")]
    # Links zonder tekst (bijv. een klikbare kaart) zitten meestal in een sjabloonblok: alleen tellen.
    generic = [l for l in content_links if _norm(l.get("text")) in _GENERIC_ANCHORS]
    empty = sum(1 for l in content_links if not l.get("text"))
    problems: list[str] = []
    page_type = page.page_type or ""
    if generic:
        problems.append(f"{len(generic)} link(s) met nietszeggende linktekst")
    if page_type == "blog" and not links_to_service:
        problems.append("geen link naar een dienst- of productpagina")
    details = {
        "generic": [{"url": l["url"], "text": l.get("text") or ""} for l in generic[:15]],
        "content_inlinks": inlinks,
        "links_without_text": empty,
    }
    if problems:
        return _c("warning", "Interne links: " + ", ".join(problems) + ".", details)
    hint = " Geen links vanuit de lopende tekst van andere pagina's." if inlinks == 0 else ""
    return _c("unknown", f"Linkkansen beoordeelt de AI-analyse.{hint}", details)


def _images(page: Any) -> Check:
    content_images = [i for i in (page.images or []) if i.get("in_content")]
    if not content_images:
        return _c("ok", "Geen afbeeldingen in de inhoud.")
    todo = images_needing_work(page)
    missing = sum(1 for i in todo if i["missing_alt"])
    generic = sum(1 for i in todo if i["generic_filename"])
    if not todo:
        return _c("ok", f"Alle {len(content_images)} afbeeldingen hebben een alt-attribuut en een beschrijvende bestandsnaam.")
    parts: list[str] = []
    if missing:
        parts.append(f"{missing} zonder alt-tekst")
    if generic:
        parts.append(f"{generic} met nietszeggende bestandsnaam")
    details = {"images": [
        {"src": i["src"], "filename": i["filename"], "alt": i.get("alt"),
         "missing_alt": i["missing_alt"], "generic_filename": i["generic_filename"]}
        for i in todo[:20]
    ]}
    return _c("error" if missing else "warning",
              f"Afbeeldingen: {', '.join(parts)} (van {len(content_images)}).", details)


def _local(page: Any, place: str | None) -> Check:
    if not place:
        return _c("nvt", "Geen locatiepagina.")
    needle = place.lower()
    h1 = " ".join((page.signals or {}).get("h1") or []).lower()
    body = (page.body_text or "").lower()
    missing: list[str] = []
    if needle not in (page.title or "").lower():
        missing.append("meta titel")
    if needle not in h1:
        missing.append("H1")
    if needle not in (page.meta_description or "").lower():
        missing.append("meta description")
    if needle not in (page.first_paragraph or "").lower():
        missing.append("eerste alinea")
    mentions = body.count(needle)
    details = {"place": place, "mentions": mentions, "region_words": bool(_REGION_RE.search(body))}
    if mentions < 3:
        missing.append(f"lopende tekst (slechts {mentions}× genoemd)")
    # Regio/werkgebied is een kans, geen fout: dat weegt de AI-analyse.
    region = "" if details["region_words"] else " Regio/werkgebied wordt niet genoemd."
    if missing:
        return _c("warning",
                  f"Locatiepagina {place}: plaatsnaam ontbreekt in " + ", ".join(missing) + "." + region, details)
    return _c("unknown",
              f"Locatiepagina {place}: basissignalen aanwezig; verdieping beoordeelt de AI-analyse.{region}", details)


def _redirects(page: Any, link_status: dict[str, dict[str, Any]] | None) -> Check:
    if link_status is None:
        return _c("unknown", "Links zijn niet gecontroleerd.")
    # Per doel-URL alle <a>-tags die ernaar wijzen (ankertekst, href zoals in de HTML, plek).
    entries: dict[str, dict[str, Any]] = {}
    broken_keys: set[str] = set()
    for link in page.links or []:
        key = url_key(link["url"])
        info = link_status.get(key)
        if not info or not (info.get("broken") or info.get("redirect")):
            continue
        entry = entries.get(key)
        if entry is None:
            entry = entries[key] = {
                "url": link["url"], "text": link.get("text") or "", "status": info.get("status"),
                "anchors": [],
            }
            if info.get("final_url"):
                entry["final_url"] = info["final_url"]  # bij een 404 via een redirect: waar hij eindigt
                entry["final_status"] = info.get("final_status")
            if info.get("broken"):
                broken_keys.add(key)
        anchor = {
            "text": link.get("text") or "",
            "href": link.get("href") or link["url"],
            "in_content": bool(link.get("in_content", True)),
        }
        if anchor not in entry["anchors"]:
            entry["anchors"].append(anchor)

    def ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Links in de lopende tekst eerst; menu/footer-links staan op elke pagina.
        for row in rows:
            row["anchors"].sort(key=lambda a: not a["in_content"])
            row["in_content"] = any(a["in_content"] for a in row["anchors"])
            row["text"] = row["anchors"][0]["text"] if row["anchors"] else row["text"]
        return sorted(rows, key=lambda r: not r["in_content"])

    broken = ordered([e for k, e in entries.items() if k in broken_keys])
    redirects = ordered([e for k, e in entries.items() if k not in broken_keys])
    details = {
        "broken": broken[:MAX_LINK_DETAILS], "redirects": redirects[:MAX_LINK_DETAILS],
        "broken_total": len(broken), "redirects_total": len(redirects),
    }

    def counted(rows: list[dict[str, Any]], label: str) -> str:
        chrome = sum(1 for r in rows if not r["in_content"])
        return f"{len(rows)} {label}" + (f" ({chrome} in menu/footer)" if chrome else "")

    if broken:
        return _c("error", counted(broken, "link(s) naar een 404/foutpagina")
                  + (f" en {counted(redirects, 'naar een redirect')}." if redirects else "."), details)
    if redirects:
        return _c("warning", counted(redirects, "link(s) naar een redirect") + ".", details)
    return _c("ok", "Geen links naar 404's of redirects.")


def evaluate_pages(
    pages: list[Any], link_status: dict[str, dict[str, Any]] | None = None
) -> dict[str, dict[str, Check]]:
    """Regelresultaat per pagina en checklistpunt: {page_id: {item_key: check}}."""
    titles = Counter(_norm(p.title) for p in pages if (p.title or "").strip())
    descriptions = Counter(_norm(p.meta_description) for p in pages if (p.meta_description or "").strip())
    dup_titles = {t for t, n in titles.items() if n > 1}
    dup_descriptions = {d for d, n in descriptions.items() if n > 1}

    by_key = {url_key(p.url): p for p in pages}
    service_keys = {k for k, p in by_key.items() if (p.page_type or "") in {"dienst", "product"}}
    inlinks: dict[str, set[str]] = defaultdict(set)
    links_to_service: set[str] = set()
    for page in pages:
        own = url_key(page.url)
        for link in page.links or []:
            if not link.get("in_content"):
                continue
            target = url_key(link["url"])
            if target == own:
                continue
            inlinks[target].add(own)
            if target in service_keys:
                links_to_service.add(own)

    out: dict[str, dict[str, Check]] = {}
    for page in pages:
        page_type = page.page_type or "overig"
        own = url_key(page.url)
        results: dict[str, Check] = {
            "c3_meta_title": _meta_title(page, dup_titles),
            "c3_meta_description": _meta_description(page, dup_descriptions),
            "c3_images": _images(page),
            "c3_local": _local(page, detect_place(page)),
            REDIRECTS_KEY: _redirects(page, link_status),
        }
        rules = {
            "c3_keywords": lambda: _keywords(page),
            "c3_headings": lambda: _headings(page),
            "c3_scannable": lambda: _scannable(page),
            "c3_answer_first": lambda: _answer_first(page),
            "c3_faq": lambda: _faq(page),
            "c3_eeat": lambda: _eeat(page),
            "c3_conversion": lambda: _conversion(page),
            "c3_internal_links": lambda: _internal_links(page, len(inlinks.get(own, ())), own in links_to_service),
        }
        for key, rule in rules.items():
            if page_type in APPLIES[key]:
                results[key] = rule()
            else:
                results[key] = _c("nvt", "Niet van toepassing op dit paginatype.")
        out[page.id] = results
    return out


def problem_count(checks: dict[str, Check]) -> int:
    return sum(1 for c in checks.values() if is_bad(c))


# --- siteniveau ----------------------------------------------------------------

def recheck_meta(f1_issues: Iterable[tuple[str, str | None]], pages: list[Any]) -> Check:
    """Zijn de titel-/meta-problemen uit fase 1 inmiddels opgelost?"""
    by_key = {url_key(p.url): p for p in pages}
    titles = Counter(_norm(p.title) for p in pages if (p.title or "").strip())
    descriptions = Counter(_norm(p.meta_description) for p in pages if (p.meta_description or "").strip())
    total = 0
    remaining: list[str] = []
    for issue_type, url in f1_issues:
        if issue_type not in F1_META_TYPES or not url:
            continue
        page = by_key.get(url_key(url))
        if page is None:
            continue  # pagina bestaat niet meer of is niet opgehaald
        total += 1
        title = (page.title or "").strip()
        meta = (page.meta_description or "").strip()
        still = {
            "title_missing": not title,
            "title_too_long": len(title) > TITLE_MAX_CHARS,
            "title_too_short": bool(title) and len(title) < TITLE_MIN_CHARS,
            "title_duplicate": bool(title) and titles[_norm(title)] > 1,
            "meta_missing": not meta,
            "meta_too_long": len(meta) > DESCRIPTION_MAX_CHARS,
            "meta_too_short": bool(meta) and len(meta) < DESCRIPTION_MIN_CHARS,
            "meta_duplicate": bool(meta) and descriptions[_norm(meta)] > 1,
        }[issue_type]
        if still:
            remaining.append(f"{url} ({issue_type})")
    if total == 0:
        return _r("ok", "Fase 1 vond geen titel- of meta-problemen op de inhoudspagina's.")
    solved = total - len(remaining)
    if remaining:
        return _r("error" if solved == 0 else "warning",
                  f"{solved} van {total} titel-/meta-problemen uit fase 1 opgelost; {len(remaining)} staan nog open.",
                  remaining[:MAX_EVIDENCE_URLS], {"total": total, "remaining": len(remaining)})
    return _r("ok", f"Alle {total} titel-/meta-problemen uit fase 1 zijn opgelost.", details={"total": total})


def _gap_rule(key: str, pages: list[Any]) -> Check | None:
    """Wat de regels al weten over ontbrekende content (zonder AI)."""
    types = Counter((p.page_type or "overig") for p in pages)
    if key == "c3_blogs" and not types.get("blog"):
        return _r("warning", "Geen blogpagina's gevonden.")
    if key == "c3_other_content":
        missing: list[str] = []
        paths = [urlparse(p.url).path for p in pages]
        if not any(_FAQ_PATH_RE.search(path) for path in paths):
            missing.append("FAQ-pagina")
        if not any(_CASES_PATH_RE.search(path) for path in paths):
            missing.append("cases/projecten")
        if not types.get("over_ons"):
            missing.append("over ons-pagina")
        if missing:
            return _r("warning", "Niet gevonden: " + ", ".join(missing) + ".")
    if key == "c3_landing_pages":
        places = sorted({pl for pl in (detect_place(p) for p in pages) if pl})
        if not types.get("dienst"):
            return _r("warning", "Geen dienstpagina's gevonden.")
        if not places:
            return _r("info", f"{types.get('dienst', 0)} dienstpagina's, geen locatiepagina's gevonden.")
    return None


def aggregate_items(
    pages: list[Any],
    page_checks: dict[str, dict[str, Check]],
    *,
    open_suggestions: dict[tuple[str | None, str], int],
    meta_fixed: Check,
    gap_analyzed: bool,
) -> dict[str, Check]:
    """Status per checklistpunt voor de hele site.

    `open_suggestions`: (content_page_id of None, item_key) → aantal open voorstellen.
    """
    out: dict[str, Check] = {META_FIXED_KEY: meta_fixed}
    analysed = {p.id for p in pages if p.analysis_status == "done"}

    for key in [REDIRECTS_KEY, *PAGE_ITEM_KEYS]:
        item = ITEMS[key]
        applicable = [p for p in pages if page_checks.get(p.id, {}).get(key, {}).get("status") != "nvt"]
        if not applicable:
            out[key] = _r("nvt", "Geen pagina's waarop dit punt van toepassing is.")
            continue
        rule_bad = [p for p in applicable if is_bad(page_checks[p.id].get(key))]
        errors = [p for p in rule_bad if page_checks[p.id][key]["status"] == "error"]
        with_suggestions = [p for p in applicable if open_suggestions.get((p.id, key))]
        bad_ids = {p.id for p in rule_bad} | {p.id for p in with_suggestions}
        analysed_here = [p for p in applicable if p.id in analysed]
        details = {
            "pages": len(applicable),
            "with_problems": len(bad_ids),
            "analysed": len(analysed_here),
            "with_suggestions": len(with_suggestions),
        }
        if bad_ids:
            evidence = [p.url for p in applicable if p.id in bad_ids][:MAX_EVIDENCE_URLS]
            message = f"{len(bad_ids)} van {len(applicable)} pagina's met verbeterpunten"
            if with_suggestions:
                message += f" ({len(with_suggestions)} met open AI-voorstellen)"
            out[key] = _r("error" if errors else "warning", message + ".", evidence, details)
        elif item.mode == "hybrid" and not analysed_here:
            out[key] = _r("unknown", "Geen problemen uit de regelcontrole; AI-analyse nog niet gedraaid.",
                          details=details)
        else:
            suffix = f"; {len(analysed_here)} door AI beoordeeld" if item.mode == "hybrid" else ""
            out[key] = _r("ok", f"Geen verbeterpunten op {len(applicable)} pagina's{suffix}.", details=details)

    for key in GAP_ITEM_KEYS:
        count = open_suggestions.get((None, key), 0)
        rule = _gap_rule(key, pages)
        if count:
            out[key] = _r("warning", f"{count} open voorstel(len) voor nieuwe content.", details={"suggestions": count})
        elif rule is not None and rule["status"] == "warning":
            out[key] = rule
        elif not gap_analyzed:
            out[key] = _r("unknown", (rule or {}).get("message") or "Contentgap-analyse nog niet gedraaid.")
        else:
            out[key] = _r("ok", "Geen open voorstellen voor nieuwe content.")
    return out
