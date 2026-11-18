"""Deterministische regels die scanresultaten omzetten naar actiepunten.

Elke regel krijgt de pagina's (+ ai_checks) en levert issue-dicts op. Nieuwe
regels toevoegen = functie schrijven en in RULES zetten. Elk issue is los
genoeg om later als Monday-item door te zetten.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from app.core.config import settings
from app.db.models import LaunchScanPage
from app.features.launch_checklist.services.discovery import clean_url, url_key
from app.features.launch_checklist.services.pagespeed import THRESHOLDS, rate

TITLE_MIN, TITLE_MAX = 30, 60
META_MIN, META_MAX = 70, 160
# 'Weinig content': bij voorkeur gemeten op de hoofdinhoud (zonder menu, kop, voet en
# zijbalk); heeft de pagina geen herkenbare structuur, dan op alle woorden in de HTML.
THIN_MAIN_WORDS = 200
THIN_CONTENT_WORDS = 300
SLOW_RESPONSE_MS = 5000
# Google-grens voor een 'goede' TTFB; dezelfde band als de CWV-beoordeling in pagespeed.py.
SLOW_TTFB_MS = int(THRESHOLDS["ttfb"][0])
# Lighthouse-audit total-byte-weight: boven p10 (2667 KiB) niet meer 'groen', boven de
# mediaan (4000 KiB) 'rood'. Bron: core/audits/byte-efficiency/total-byte-weight.js.
PAGE_WEIGHT_WARN_BYTES = 2667 * 1024
PAGE_WEIGHT_POOR_BYTES = 4000 * 1024

# Versie van de regelset. Fase 4 vergelijkt aantallen per type met een basis-scan;
# een type dat pas na die scan is toegevoegd, telt daar niet mee (anders verschijnt
# het als 'nieuwe problemen'). De versie staat in summary_stats["ruleset"].
RULESET_VERSION = 2
# Vanaf welke regelset een type bestaat (of sinds wanneer het op deze manier gemeten
# wordt); niet genoemd = versie 1.
ISSUE_TYPE_SINCE: dict[str, int] = {
    "thin_content": 2,  # sinds v2 gemeten op de hoofdinhoud
    "robots_blocked_in_sitemap": 2,
    "hreflang_invalid": 2,
    "hreflang_no_return": 2,
    "hreflang_target_broken": 2,
    "og_incomplete": 2,
    "cwv_page_weight": 2,
}


def issue_type_since(issue_type: str) -> int:
    return ISSUE_TYPE_SINCE.get(issue_type, 1)


THIN_MEASURE_LABELS = {"main": "woorden in de hoofdinhoud", "total": "woorden in de HTML"}


def thin_content_check(page: LaunchScanPage) -> tuple[bool, int, str]:
    """(dun?, aantal woorden, maat) voor een fase 1-pagina.

    maat = "main": woorden buiten nav/header/footer/aside, drempel THIN_MAIN_WORDS;
    maat = "total": geen herkenbare paginastructuur, alle woorden, drempel THIN_CONTENT_WORDS.
    """
    main = getattr(page, "main_word_count", None)  # niet elk pagina-object heeft het veld
    if main is not None:
        return main < THIN_MAIN_WORDS, main, "main"
    words = page.word_count or 0
    return words < THIN_CONTENT_WORDS, words, "total"


Issue = dict[str, Any]
Rule = Callable[[list[LaunchScanPage], dict[str, Any]], Iterable[Issue]]

# Labels per issue_type (voor UI-groepering en Monday later).
ISSUE_TYPES: dict[str, dict[str, str]] = {
    "fetch_error": {"label": "Pagina niet bereikbaar", "category": "techniek"},
    "status_4xx": {"label": "Pagina geeft 4xx-fout", "category": "techniek"},
    "status_5xx": {"label": "Pagina geeft serverfout (5xx)", "category": "techniek"},
    "redirect_in_sitemap": {"label": "Redirect in sitemap", "category": "techniek"},
    "redirect_chain": {"label": "Redirectketen", "category": "techniek"},
    "noindex_in_sitemap": {"label": "Noindex-pagina in sitemap", "category": "techniek"},
    "canonical_mismatch": {"label": "Canonical wijst naar andere URL", "category": "techniek"},
    "broken_links": {"label": "Kapotte interne links", "category": "techniek"},
    "broken_backlinks": {"label": "Backlinks naar kapotte pagina", "category": "techniek"},
    "slow_response": {"label": "Trage serverrespons", "category": "performance"},
    "title_missing": {"label": "Title ontbreekt", "category": "on-page"},
    "title_too_long": {"label": "Title te lang", "category": "on-page"},
    "title_too_short": {"label": "Title te kort", "category": "on-page"},
    "title_duplicate": {"label": "Dubbele title", "category": "on-page"},
    "meta_missing": {"label": "Meta description ontbreekt", "category": "on-page"},
    "meta_too_long": {"label": "Meta description te lang", "category": "on-page"},
    "meta_too_short": {"label": "Meta description te kort", "category": "on-page"},
    "meta_duplicate": {"label": "Dubbele meta description", "category": "on-page"},
    "h1_missing": {"label": "H1 ontbreekt", "category": "on-page"},
    "h1_multiple": {"label": "Meerdere H1's", "category": "on-page"},
    "h1_duplicate": {"label": "Dubbele H1 over pagina's", "category": "on-page"},
    "images_missing_alt": {"label": "Afbeeldingen zonder alt-tekst", "category": "content"},
    "thin_content": {"label": "Weinig content", "category": "content"},
    "lang_missing": {"label": "lang-attribuut ontbreekt", "category": "techniek"},
    "robots_blocked_in_sitemap": {"label": "Pagina in sitemap geblokkeerd door robots.txt", "category": "techniek"},
    "hreflang_invalid": {"label": "Ongeldige hreflang-tags", "category": "techniek"},
    "hreflang_no_return": {"label": "hreflang zonder terugverwijzing", "category": "techniek"},
    "hreflang_target_broken": {"label": "hreflang wijst naar kapotte of niet-indexeerbare pagina", "category": "techniek"},
    "og_incomplete": {"label": "Open Graph-tags onvolledig", "category": "on-page"},
    "cwv_lcp": {"label": "LCP te traag", "category": "performance"},
    "cwv_cls": {"label": "CLS te hoog", "category": "performance"},
    "cwv_inp": {"label": "INP/TBT te hoog", "category": "performance"},
    "cwv_page_weight": {"label": "Pagina te zwaar", "category": "performance"},
    "ai_robots_txt": {"label": "robots.txt ontbreekt", "category": "ai"},
    "ai_ai_bots_blocked": {"label": "AI-bots geblokkeerd", "category": "ai"},
    "ai_sitemap": {"label": "Sitemap-probleem", "category": "ai"},
    "ai_llms_txt": {"label": "llms.txt ontbreekt", "category": "ai"},
    "ai_schema_coverage": {"label": "Weinig structured data", "category": "ai"},
    "ai_org_schema": {"label": "Organisatie-schema ontbreekt", "category": "ai"},
    "ai_website_schema": {"label": "WebSite-schema ontbreekt", "category": "ai"},
    "ai_ssr_content": {"label": "Content afhankelijk van JavaScript", "category": "ai"},
    "ai_page_access": {"label": "Pagina's niet bereikbaar voor crawlers", "category": "ai"},
}


def _issue(
    issue_type: str,
    severity: str,
    *,
    page: LaunchScanPage | None,
    title: str,
    description: str,
    recommendation: str,
    details: Any = None,
) -> Issue:
    return {
        "issue_type": issue_type,
        "category": ISSUE_TYPES.get(issue_type, {}).get("category", "techniek"),
        "severity": severity,
        "page_id": page.id if page is not None else None,
        "url": page.url if page is not None else None,
        "title": title,
        "description": description,
        "recommendation": recommendation,
        "details": details,
    }


def final_status(page: LaunchScanPage) -> int | None:
    chain = page.redirect_chain or []
    if chain and isinstance(chain[-1], dict) and chain[-1].get("final"):
        return chain[-1].get("status")
    return page.status_code


def redirect_hops(page: LaunchScanPage) -> int:
    return len([h for h in (page.redirect_chain or []) if not (isinstance(h, dict) and h.get("final"))])


def _is_ok_html(page: LaunchScanPage) -> bool:
    return (
        page.status_code == 200
        and not page.redirect_chain
        and "html" in (page.content_type or "").lower()
    )


def _is_indexable_html(page: LaunchScanPage) -> bool:
    return _is_ok_html(page) and page.indexable is True


# --- regels ---------------------------------------------------------------

def rule_status(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    for p in pages:
        if p.error and p.status_code is None:
            yield _issue(
                "fetch_error", "hoog", page=p,
                title=f"Pagina niet bereikbaar: {p.path}",
                description=f"De pagina kon niet worden opgehaald ({p.error}).",
                recommendation="Controleer of de URL bestaat en de server/firewall de crawler niet blokkeert.",
            )
            continue
        status = final_status(p)
        if status is None:
            continue
        if 400 <= status < 500:
            yield _issue(
                "status_4xx", "hoog", page=p,
                title=f"{status}-fout op {p.path}",
                description=f"De pagina geeft statuscode {status}" + (" en staat in de sitemap." if p.in_sitemap else "."),
                recommendation="Herstel de pagina of zet een 301-redirect naar de juiste pagina en haal hem uit de sitemap.",
                details={"status": status},
            )
        elif status >= 500:
            yield _issue(
                "status_5xx", "hoog", page=p,
                title=f"Serverfout ({status}) op {p.path}",
                description=f"De server geeft statuscode {status}.",
                recommendation="Laat de developer/hosting de serverfout onderzoeken.",
                details={"status": status},
            )


# Statussen die op blokkade/rate-limiting wijzen, niet op een kapotte pagina.
_INCONCLUSIVE_STATUSES = {401, 403, 429, 503}


def rule_backlinks(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    """Pagina's waar andere websites naar linken (Ahrefs) maar die niet meer werken."""
    for p in pages:
        refdomains = getattr(p, "refdomains", None) or 0
        if refdomains <= 0:
            continue
        status = final_status(p)
        if status is None:
            if not p.error:
                continue
            state = "is niet bereikbaar"
        elif status >= 400 and status not in _INCONCLUSIVE_STATUSES:
            state = f"geeft statuscode {status}"
        else:
            continue
        traffic = getattr(p, "org_traffic", None) or 0
        domains = "1 website linkt" if refdomains == 1 else f"{refdomains} websites linken"
        yield _issue(
            "broken_backlinks", "hoog", page=p,
            title=f"{refdomains} verwijzend(e) domein(en) naar kapotte pagina {p.path}",
            description=(
                f"De pagina {state}, maar {domains} ernaar volgens Ahrefs"
                + (f" en de URL trok circa {traffic} organische bezoeken per maand." if traffic else ".")
                + " De linkwaarde gaat nu verloren."
            ),
            recommendation="Zet een 301-redirect naar de best passende bestaande pagina, of herstel de pagina.",
            details={
                "status": status,
                "refdomains": refdomains,
                "org_traffic": traffic or None,
                "backlinks": (getattr(p, "ahrefs", None) or {}).get("broken_backlinks") or [],
            },
        )


def rule_redirects(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    for p in pages:
        hops = redirect_hops(p)
        if not hops:
            continue
        if p.in_sitemap:
            yield _issue(
                "redirect_in_sitemap", "middel", page=p,
                title=f"Redirect in sitemap: {p.path}",
                description=f"De sitemap bevat een URL die doorverwijst naar {p.final_url}.",
                recommendation="Vervang de URL in de sitemap door de eind-URL.",
                details={"chain": p.redirect_chain},
            )
        if hops > 1:
            yield _issue(
                "redirect_chain", "middel", page=p,
                title=f"Redirectketen ({hops} stappen) op {p.path}",
                description=f"De URL gaat via {hops} redirects naar {p.final_url}.",
                recommendation="Laat de eerste redirect direct naar de eind-URL wijzen.",
                details={"chain": p.redirect_chain},
            )


def rule_indexability(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    for p in pages:
        reason = p.indexability_reason or ""
        if "noindex" in reason and p.in_sitemap:
            yield _issue(
                "noindex_in_sitemap", "middel", page=p,
                title=f"Noindex-pagina in sitemap: {p.path}",
                description=f"De pagina staat in de sitemap maar heeft {reason}.",
                recommendation="Haal de noindex weg als de pagina gevonden moet worden, anders uit de sitemap halen.",
            )
        if reason == "Canonical naar andere URL":
            yield _issue(
                "canonical_mismatch", "middel", page=p,
                title=f"Canonical wijst naar andere URL: {p.path}",
                description=f"De canonical verwijst naar {p.canonical}.",
                recommendation="Controleer of dit bewust is; anders de canonical naar de pagina zelf laten wijzen.",
                details={"canonical": p.canonical},
            )


def rule_onpage(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    for p in pages:
        if not _is_indexable_html(p):
            continue
        # Title
        if not p.title:
            yield _issue(
                "title_missing", "hoog", page=p,
                title=f"Title ontbreekt op {p.path}",
                description="De pagina heeft geen <title>.",
                recommendation=f"Schrijf een unieke title van {TITLE_MIN}–{TITLE_MAX} tekens met het belangrijkste zoekwoord.",
            )
        elif (p.title_length or 0) > TITLE_MAX:
            yield _issue(
                "title_too_long", "laag", page=p,
                title=f"Title te lang ({p.title_length} tekens) op {p.path}",
                description=f"\"{p.title}\" wordt waarschijnlijk afgekapt in Google.",
                recommendation=f"Kort de title in tot maximaal {TITLE_MAX} tekens.",
                details={"title": p.title, "length": p.title_length},
            )
        elif (p.title_length or 0) < TITLE_MIN:
            yield _issue(
                "title_too_short", "laag", page=p,
                title=f"Title te kort ({p.title_length} tekens) op {p.path}",
                description=f"\"{p.title}\" benut de ruimte in de zoekresultaten niet.",
                recommendation=f"Breid de title uit naar {TITLE_MIN}–{TITLE_MAX} tekens.",
                details={"title": p.title, "length": p.title_length},
            )
        # Meta description
        if not p.meta_description:
            yield _issue(
                "meta_missing", "middel", page=p,
                title=f"Meta description ontbreekt op {p.path}",
                description="De pagina heeft geen meta description.",
                recommendation=f"Schrijf een wervende meta description van {META_MIN}–{META_MAX} tekens.",
            )
        elif (p.meta_description_length or 0) > META_MAX:
            yield _issue(
                "meta_too_long", "laag", page=p,
                title=f"Meta description te lang ({p.meta_description_length} tekens) op {p.path}",
                description="De meta description wordt afgekapt in Google.",
                recommendation=f"Kort in tot maximaal {META_MAX} tekens.",
                details={"meta_description": p.meta_description, "length": p.meta_description_length},
            )
        elif (p.meta_description_length or 0) < META_MIN:
            yield _issue(
                "meta_too_short", "laag", page=p,
                title=f"Meta description te kort ({p.meta_description_length} tekens) op {p.path}",
                description="De meta description is erg kort.",
                recommendation=f"Breid uit naar {META_MIN}–{META_MAX} tekens.",
                details={"meta_description": p.meta_description, "length": p.meta_description_length},
            )
        # H1
        h1_count = p.h1_count or 0
        if h1_count == 0:
            yield _issue(
                "h1_missing", "hoog", page=p,
                title=f"H1 ontbreekt op {p.path}",
                description="De pagina heeft geen H1-kop.",
                recommendation="Voeg één duidelijke H1 toe die het onderwerp van de pagina beschrijft.",
            )
        elif h1_count > 1:
            yield _issue(
                "h1_multiple", "middel", page=p,
                title=f"{h1_count} H1's op {p.path}",
                description=f"De pagina heeft {h1_count} H1-koppen.",
                recommendation="Houd één H1 over en maak de rest H2/H3.",
                details={"h1": p.h1},
            )
        # Content
        thin, words, measure = thin_content_check(p)
        if thin:
            if measure == "main":
                description = (
                    f"De hoofdinhoud van de pagina (zonder menu, kop, voet en zijbalk) heeft minder "
                    f"dan {THIN_MAIN_WORDS} woorden; in totaal staan er {p.word_count or 0} in de HTML."
                )
            else:
                description = (
                    f"De pagina heeft minder dan {THIN_CONTENT_WORDS} woorden in de HTML (alle tekst "
                    f"geteld: menu en hoofdinhoud zijn niet te onderscheiden)."
                )
            yield _issue(
                "thin_content", "laag", page=p,
                title=f"Weinig content ({words} {THIN_MEASURE_LABELS[measure]}) op {p.path}",
                description=description,
                recommendation="Breid de content uit of voeg de pagina samen met een verwante pagina.",
                details={"word_count": words, "measure": measure},
            )
        if (p.images_missing_alt or 0) > 0:
            yield _issue(
                "images_missing_alt", "middel" if (p.images_missing_alt or 0) >= 5 else "laag", page=p,
                title=f"{p.images_missing_alt} afbeelding(en) zonder alt op {p.path}",
                description=f"{p.images_missing_alt} van de {p.images_total} afbeeldingen hebben geen alt-attribuut.",
                recommendation="Geef elke inhoudelijke afbeelding een beschrijvende alt-tekst (decoratief: alt=\"\").",
                details={"missing": p.images_missing_alt, "total": p.images_total},
            )


def rule_duplicates(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    indexable = [p for p in pages if _is_indexable_html(p)]
    specs = [
        ("title_duplicate", "middel", lambda p: (p.title or "").strip().lower(), "title",
         "Meerdere pagina's hebben dezelfde title.", "Maak de title per pagina uniek."),
        ("meta_duplicate", "laag", lambda p: (p.meta_description or "").strip().lower(), "meta description",
         "Meerdere pagina's hebben dezelfde meta description.", "Schrijf per pagina een unieke meta description."),
        ("h1_duplicate", "laag", lambda p: ((p.h1 or [""])[0] or "").strip().lower() if (p.h1_count or 0) else "", "H1",
         "Meerdere pagina's hebben dezelfde H1.", "Maak de H1 per pagina uniek."),
    ]
    for issue_type, severity, key_fn, label, desc, rec in specs:
        groups: dict[str, list[LaunchScanPage]] = defaultdict(list)
        for p in indexable:
            key = key_fn(p)
            if key:
                groups[key].append(p)
        for group in groups.values():
            if len(group) < 2:
                continue
            for p in group:
                others = [o.url for o in group if o.id != p.id]
                yield _issue(
                    issue_type, severity, page=p,
                    title=f"Dubbele {label} op {p.path}",
                    description=f"{desc} Deze {label} komt ook voor op {len(others)} andere pagina('s).",
                    recommendation=rec,
                    details={"value": key_fn(p), "duplicates": others[:20]},
                )


def rule_links_and_speed(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    for p in pages:
        broken = p.broken_links or []
        if broken:
            yield _issue(
                "broken_links", "hoog", page=p,
                title=f"{len(broken)} kapotte link(s) op {p.path}",
                description="De pagina linkt naar interne URL's die een fout geven.",
                recommendation="Pas de links aan naar werkende pagina's of zet redirects.",
                details={"links": broken},
            )
        if not _is_ok_html(p):
            continue
        # Voorkeur: TTFB uit PageSpeed (Google meet los van onze scanbelasting).
        lab_ttfb = ((p.cwv or {}).get("lab") or {}).get("ttfb")
        if isinstance(lab_ttfb, (int, float)):
            if lab_ttfb > SLOW_TTFB_MS:
                yield _issue(
                    "slow_response", "middel", page=p,
                    title=f"Trage serverrespons (TTFB {int(lab_ttfb)} ms) op {p.path}",
                    description=f"Google meet een server-responstijd van {int(lab_ttfb)} ms (doel: hooguit {SLOW_TTFB_MS} ms).",
                    recommendation="Controleer page caching/CDN, PHP-workers en hosting.",
                    details={"ttfb_ms": lab_ttfb, "source": "pagespeed"},
                )
        elif (p.response_time_ms or 0) > SLOW_RESPONSE_MS:
            yield _issue(
                "slow_response", "laag", page=p,
                title=f"Trage serverrespons ({p.response_time_ms} ms) op {p.path}",
                description=f"Tijdens de scan duurde het {p.response_time_ms} ms om de HTML te leveren (gemeten onder scanbelasting).",
                recommendation="Controleer caching (page cache/CDN) en hosting.",
                details={"response_time_ms": p.response_time_ms, "source": "scan"},
            )


def rule_lang(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    missing = [p for p in pages if _is_indexable_html(p) and not p.lang]
    if missing:
        yield _issue(
            "lang_missing", "laag", page=None,
            title=f"lang-attribuut ontbreekt op {len(missing)} pagina('s)",
            description="Het <html>-element heeft geen lang-attribuut.",
            recommendation="Stel <html lang=\"nl\"> (of de juiste taal) in het thema in.",
            details={"urls": [p.url for p in missing[:50]]},
        )


def robots_blocked_in_sitemap(
    pages: list[LaunchScanPage], ai_checks: dict[str, Any] | None
) -> list[tuple[LaunchScanPage, dict[str, Any]]]:
    """Sitemap-pagina's (eindstatus 200) die Googlebot of Bingbot niet mag ophalen.

    Alleen sitemap-pagina's: zonder sitemap levert dit bewust niets op, want
    winkelwagen- en filter-URL's zijn meestal met opzet geblokkeerd.
    """
    blocked = {
        url_key(row["url"]): row
        for row in ((ai_checks or {}).get("robots_pages") or {}).get("pages") or []
        if row.get("url")
    }
    if not blocked:
        return []
    return [
        (p, blocked[url_key(p.url)])
        for p in pages
        if p.in_sitemap and final_status(p) == 200 and url_key(p.url) in blocked
    ]


def rule_robots(pages: list[LaunchScanPage], ctx: dict[str, Any]) -> Iterable[Issue]:
    for p, row in robots_blocked_in_sitemap(pages, ctx.get("ai_checks")):
        bots = row.get("blocked_for") or []
        rule = row.get("rule")
        yield _issue(
            "robots_blocked_in_sitemap", "hoog", page=p,
            title=f"Pagina in sitemap geblokkeerd door robots.txt: {p.path}",
            description=(
                f"De pagina staat in de sitemap, maar robots.txt verbiedt {' en '.join(bots)} haar op te halen"
                + (f" (regel \"{rule}\")." if rule else ".")
                + " Zoekmachines krijgen zo tegenstrijdige signalen en kunnen de inhoud niet lezen."
            ),
            recommendation="Haal de blokkade uit robots.txt als de pagina gevonden moet worden; anders de pagina uit de sitemap halen.",
            details={"blocked_for": bots, "rule": rule},
        )


# hreflang: taal ISO 639-1, regio ISO 3166-1 alpha-2 (zoals Google vraagt).
_ISO_639_1 = frozenset("""
aa ab ae af ak am an ar as av ay az ba be bg bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de dv dz ee el
en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu
ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na
nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so
sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu
""".split())
_ISO_3166_1 = frozenset("""
ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bl bm bn bo bq br bs bt bv bw by bz
ca cc cd cf cg ch ci ck cl cm cn co cr cu cv cw cx cy cz de dj dk dm do dz ec ee eg eh er es et fi fj fk fm fo
fr ga gb gd ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw gy hk hm hn hr ht hu id ie il im in io iq ir is it je
jm jo jp ke kg kh ki km kn kp kr kw ky kz la lb lc li lk lr ls lt lu lv ly ma mc md me mf mg mh mk ml mm mn mo
mp mq mr ms mt mu mv mw mx my mz na nc ne nf ng ni nl no np nr nu nz om pa pe pf pg ph pk pl pm pn pr ps pt pw
py qa re ro rs ru rw sa sb sc sd se sg sh si sj sk sl sm sn so sr ss st sv sx sy sz tc td tf tg th tj tk tl
tm tn to tr tt tv tw tz ua ug um us uy uz va vc ve vg vi vn vu wf ws ye yt za zm zw
""".split())
_HREFLANG_CODE = re.compile(r"^([a-z]{2})(?:-([a-z]{4}))?(?:-([a-z]{2}))?$")
_ABSOLUTE_URL = re.compile(r"^https?://", re.IGNORECASE)


def is_valid_hreflang(code: str) -> bool:
    """`x-default`, of taal[-schrift][-regio] met geldige ISO-codes (dus niet en-UK of nl_NL)."""
    value = (code or "").strip().lower()
    if value == "x-default":
        return True
    match = _HREFLANG_CODE.match(value)
    if not match:
        return False
    language, _script, region = match.groups()
    return language in _ISO_639_1 and (region is None or region in _ISO_3166_1)


def _page_keys(page: LaunchScanPage) -> set[str]:
    return {url_key(u) for u in (page.url, page.final_url) if u}


def _hreflang_entries(page: LaunchScanPage) -> list[tuple[str, str, str | None]]:
    """[(code, href zoals in de HTML, absolute URL of None)], zonder exacte dubbelingen."""
    base = page.final_url or page.url
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str | None]] = []
    for entry in page.hreflang or []:
        if not isinstance(entry, dict):
            continue
        code, href = str(entry.get("lang") or "").strip(), str(entry.get("href") or "").strip()
        if not code or not href or (code.lower(), href) in seen:
            continue
        seen.add((code.lower(), href))
        out.append((code, href, clean_url(href, base)))
    return out


def rule_hreflang(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    sources = [p for p in pages if _is_ok_html(p) and p.hreflang]
    if not sources:
        return
    by_key = {url_key(p.url): p for p in pages}

    for p in sources:
        entries = _hreflang_entries(p)
        own = _page_keys(p)

        # Ongeldige codes, relatieve URL's, dubbele codes en geen verwijzing naar zichzelf.
        problems: list[dict[str, Any]] = []
        urls_per_code: dict[str, set[str]] = defaultdict(set)
        for code, href, absolute in entries:
            if not is_valid_hreflang(code):
                problems.append({"lang": code, "href": href, "problem": "ongeldige taal-/regiocode"})
            if not _ABSOLUTE_URL.match(href):
                problems.append({"lang": code, "href": href, "problem": "relatieve URL (moet volledig zijn, met https://)"})
            urls_per_code[code.lower()].add(url_key(absolute) if absolute else href)
        for code, href, _absolute in entries:
            if len(urls_per_code[code.lower()]) > 1:
                problems.append({"lang": code, "href": href, "problem": "dezelfde code verwijst naar meerdere URL's"})
        if not any(absolute and url_key(absolute) in own for _, _, absolute in entries):
            problems.append({"lang": None, "href": p.url, "problem": "geen hreflang naar de pagina zelf"})
        if problems:
            yield _issue(
                "hreflang_invalid", "middel", page=p,
                title=f"Ongeldige hreflang-tags op {p.path} ({len(problems)}×)",
                description="De hreflang-tags bevatten fouten; Google negeert dan (een deel van) de taalversies.",
                recommendation=(
                    "Gebruik geldige codes (taal ISO 639-1, regio ISO 3166-1, bv. nl-NL of en-GB, met een "
                    "koppelteken), één URL per code, volledige URL's en een hreflang naar de pagina zelf."
                ),
                details={"problems": problems},
            )

        # Doelpagina's die in de crawl zitten: kapot/niet-indexeerbaar, of zonder terugverwijzing.
        broken: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        checked: set[str] = set()
        for code, _href, absolute in entries:
            if not absolute:
                continue
            key = url_key(absolute)
            target = by_key.get(key)
            if target is None or key in own or (code.lower(), key) in checked:
                continue
            checked.add((code.lower(), key))
            status = final_status(target)
            if status is None or status in _INCONCLUSIVE_STATUSES:
                continue
            reason = None
            if status >= 400:
                reason = f"statuscode {status}"
            elif target.redirect_chain:
                reason = f"redirect naar {target.final_url}"
            elif "noindex" in (target.indexability_reason or ""):
                reason = "noindex"
            elif target.indexability_reason == "Canonical naar andere URL":
                reason = f"canonical naar {target.canonical}"
            if reason:
                broken.append({"lang": code, "url": target.url, "status": target.status_code, "reason": reason})
                continue
            if not _is_ok_html(target):
                continue
            back = {url_key(a) for _, _, a in _hreflang_entries(target) if a}
            if not (back & own):
                missing.append({"lang": code, "url": target.url})
        if broken:
            yield _issue(
                "hreflang_target_broken", "hoog", page=p,
                title=f"hreflang naar {len(broken)} kapotte of niet-indexeerbare pagina('s) op {p.path}",
                description="Een taalversie waar de hreflang naar verwijst, werkt niet, verwijst door of mag niet geïndexeerd worden.",
                recommendation="Laat de hreflang naar de werkende, indexeerbare eind-URL van elke taalversie wijzen.",
                details={"targets": broken},
            )
        if missing:
            yield _issue(
                "hreflang_no_return", "middel", page=p,
                title=f"{len(missing)} taalversie(s) zonder terugverwijzing naar {p.path}",
                description="Een taalversie verwijst niet terug met een hreflang naar deze pagina; Google negeert de koppeling dan.",
                recommendation="Zet op elke taalversie dezelfde, volledige set hreflang-tags (inclusief deze pagina).",
                details={"missing": missing},
            )


OG_REQUIRED = ("og:title", "og:description", "og:image")


def _is_home(page: LaunchScanPage) -> bool:
    for candidate in (page.final_url, page.url):
        if candidate:
            parsed = urlparse(candidate)
            if parsed.path in ("", "/") and not parsed.query:
                return True
    return False


def rule_open_graph(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    indexable = [p for p in pages if _is_indexable_html(p)]
    if not indexable:
        return

    def has(p: LaunchScanPage, tag: str) -> bool:
        return bool(str((p.open_graph or {}).get(tag) or "").strip())

    missing = {tag: [p for p in indexable if not has(p, tag)] for tag in OG_REQUIRED}
    incomplete = [p for p in indexable if not all(has(p, tag) for tag in OG_REQUIRED)]
    relative_image = [
        p for p in indexable
        if has(p, "og:image") and not _ABSOLUTE_URL.match(str(p.open_graph["og:image"]).strip())
    ]
    if not incomplete and not relative_image:
        return
    lacks_key = [p for p in indexable if not (has(p, "og:title") and has(p, "og:image"))]
    home_lacks = any(_is_home(p) for p in lacks_key)
    severity = "middel" if home_lacks or 2 * len(lacks_key) >= len(indexable) else "laag"
    parts = [f"{len(v)}× geen {tag}" for tag, v in missing.items() if v]
    if relative_image:
        parts.append(f"{len(relative_image)}× relatieve og:image")
    yield _issue(
        "og_incomplete", severity, page=None,
        title=f"Open Graph-tags onvolledig op {len({p.id for p in incomplete + relative_image})} pagina('s)",
        description=(
            f"Van de {len(indexable)} indexeerbare pagina's: {', '.join(parts)}."
            + (" Ook de homepage mist og:title of og:image." if home_lacks else "")
            + " Bij delen op social media en in chat-apps ontbreekt dan een nette titel, tekst of afbeelding."
        ),
        recommendation=(
            "Laat het SEO-plugin of thema op elke pagina og:title, og:description en og:image zetten, "
            "met een volledige URL (https://…) voor de afbeelding."
        ),
        details={
            "total": len(indexable),
            "missing": {tag: len(v) for tag, v in missing.items()},
            "urls": [p.url for p in incomplete[:50]],
            "relative_image": [p.url for p in relative_image[:20]],
        },
    )


def rule_vitals(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    for p in pages:
        cwv = p.cwv or {}
        if not cwv:
            continue
        lab = cwv.get("lab") or {}
        field = cwv.get("field") or {}
        use_field = bool(field) and not field.get("origin_fallback")

        def metric(name: str) -> tuple[float | None, str | None, str]:
            if use_field and isinstance(field.get(name), dict):
                return field[name].get("value"), field[name].get("rating"), "veld"
            return None, None, "lab"

        # LCP
        value, rating, src = metric("lcp")
        if rating is None:
            value, rating, src = lab.get("lcp"), rate("lcp", lab.get("lcp")), "lab"
        if rating in {"poor", "needs_improvement"} and value is not None:
            yield _issue(
                "cwv_lcp", "hoog" if rating == "poor" else "middel", page=p,
                title=f"LCP {value / 1000:.1f}s op {p.path}",
                description=f"Largest Contentful Paint is {value / 1000:.1f}s ({src}data, mobiel). Doel: ≤ 2,5s.",
                recommendation="Optimaliseer de hero-afbeelding (formaat/WebP/preload), verminder render-blocking CSS/JS en verbeter de serverrespons.",
                details={"value": value, "rating": rating, "source": src},
            )
        # CLS
        value, rating, src = metric("cls")
        if rating is None:
            value, rating, src = lab.get("cls"), rate("cls", lab.get("cls")), "lab"
        if rating in {"poor", "needs_improvement"} and value is not None:
            yield _issue(
                "cwv_cls", "hoog" if rating == "poor" else "middel", page=p,
                title=f"CLS {value:.2f} op {p.path}",
                description=f"Cumulative Layout Shift is {value:.2f} ({src}data, mobiel). Doel: ≤ 0,1.",
                recommendation="Geef afbeeldingen/embeds vaste afmetingen, reserveer ruimte voor banners en laad fonts met font-display.",
                details={"value": value, "rating": rating, "source": src},
            )
        # INP (veld) of TBT (lab)
        value, rating, src = metric("inp")
        label = "INP"
        if rating is None:
            value, rating, src, label = lab.get("tbt"), rate("tbt", lab.get("tbt")), "lab", "TBT"
        if rating in {"poor", "needs_improvement"} and value is not None:
            yield _issue(
                "cwv_inp", "hoog" if rating == "poor" else "middel", page=p,
                title=f"{label} {int(value)} ms op {p.path}",
                description=f"{label} is {int(value)} ms ({src}data, mobiel). Doel: {'≤ 200 ms' if label == 'INP' else '≤ 200 ms TBT'}.",
                recommendation="Verminder en splits JavaScript (plugins, trackers, sliders), stel scripts uit en vermijd lange taken.",
                details={"value": value, "rating": rating, "source": src, "metric": label},
            )

        # Paginagewicht (Lighthouse total-byte-weight); ontbreekt bij metingen van vóór deze regel.
        weight = lab.get("total_byte_weight")
        if isinstance(weight, (int, float)) and weight > PAGE_WEIGHT_WARN_BYTES:
            mb = f"{weight / (1024 * 1024):.1f}".replace(".", ",")
            yield _issue(
                "cwv_page_weight", "hoog" if weight > PAGE_WEIGHT_POOR_BYTES else "middel", page=p,
                title=f"Pagina te zwaar ({mb} MB) op {p.path}",
                description=(
                    f"Google PageSpeed meet {mb} MB aan bestanden voor deze pagina (mobiel). Lighthouse keurt "
                    f"meer dan {PAGE_WEIGHT_WARN_BYTES // 1024} KiB af; boven {PAGE_WEIGHT_POOR_BYTES // 1024} KiB is het slecht."
                ),
                recommendation="Verklein afbeeldingen en video (WebP/AVIF, juiste afmetingen, lazy loading) en verwijder ongebruikte scripts, fonts en plugins.",
                details={"bytes": int(weight), "source": "pagespeed"},
            )


_AI_RECOMMENDATIONS = {
    "robots_txt": "Plaats een robots.txt met een verwijzing naar de sitemap.",
    "ai_bots_blocked": "Pas robots.txt aan zodat in elk geval de AI-zoekbots (OAI-SearchBot, ChatGPT-User, Claude-SearchBot, PerplexityBot) toegang hebben.",
    "sitemap": "Zorg voor een XML-sitemap en vermeld die in robots.txt (Sitemap: https://…/sitemap.xml).",
    "llms_txt": "Voeg een /llms.txt toe met een korte beschrijving van het bedrijf en links naar de belangrijkste pagina's.",
    "schema_coverage": "Voeg JSON-LD toe (Organization, WebPage, Service/Product, FAQ, BreadcrumbList) via het SEO-plugin/thema.",
    "org_schema": "Voeg Organization- of LocalBusiness-schema met NAW, logo en sameAs-profielen toe aan de homepage.",
    "website_schema": "Voeg WebSite-schema toe aan de homepage.",
    "page_access": "Controleer firewall/bot-protectie (Cloudflare, Shopify, Wordfence): crawlers moeten de pagina's kunnen ophalen.",
    "ssr_content": "Zorg dat de belangrijkste content server-side in de HTML staat (geen client-only rendering).",
}
# Voor checks waarvan het bestand niet kon worden opgehaald (details.fetched == False).
_AI_NOT_FETCHED_RECOMMENDATION = (
    "Controleer of het bestand bereikbaar is voor crawlers (firewall, bot-protectie, hosting) en draai de scan opnieuw."
)


def rule_ai(_: list[LaunchScanPage], ctx: dict[str, Any]) -> Iterable[Issue]:
    for check in (ctx.get("ai_checks") or {}).get("checks", []):
        if check.get("status") == "ok":
            continue
        key = check.get("key", "")
        not_fetched = (check.get("details") or {}).get("fetched") is False
        yield _issue(
            f"ai_{key}", "hoog" if check.get("status") == "error" else "middel", page=None,
            title=f"{check.get('label')}: {check.get('message')}",
            description=check.get("message") or "",
            recommendation=_AI_NOT_FETCHED_RECOMMENDATION if not_fetched else _AI_RECOMMENDATIONS.get(key, ""),
            details=check.get("details"),
        )


RULES: list[Rule] = [
    rule_status,
    rule_backlinks,
    rule_redirects,
    rule_indexability,
    rule_onpage,
    rule_duplicates,
    rule_links_and_speed,
    rule_lang,
    rule_robots,
    rule_hreflang,
    rule_open_graph,
    rule_vitals,
    rule_ai,
]


_RAISED_SEVERITY = {"laag": "middel", "middel": "hoog"}


def is_valuable(page: LaunchScanPage) -> bool:
    """Pagina met genoeg organisch verkeer of verwijzende domeinen (Ahrefs) om voorrang te krijgen."""
    return (
        (getattr(page, "org_traffic", None) or 0) >= settings.ahrefs_value_min_traffic
        or (getattr(page, "refdomains", None) or 0) >= settings.ahrefs_value_min_refdomains
    )


def apply_value_boost(issues: list[Issue], pages: list[LaunchScanPage]) -> None:
    """Actiepunten op pagina's met waarde gaan één stap omhoog in prioriteit.

    `details.value_boost` legt vast waarom (en vanaf welke prioriteit), zodat de
    UI het kan tonen.
    """
    valuable = {p.id: p for p in pages if is_valuable(p)}
    for issue in issues:
        page = valuable.get(issue.get("page_id"))
        if page is None:
            continue
        previous = issue["severity"]
        raised = _RAISED_SEVERITY.get(previous)
        boost = {
            "org_traffic": getattr(page, "org_traffic", None),
            "refdomains": getattr(page, "refdomains", None),
            "from": previous if raised else None,
        }
        details = issue.get("details")
        if details is None:
            issue["details"] = {"value_boost": boost}
        elif isinstance(details, dict):
            issue["details"] = {**details, "value_boost": boost}
        else:
            issue["details"] = {"data": details, "value_boost": boost}
        if raised:
            issue["severity"] = raised


def generate_issues(pages: list[LaunchScanPage], ai_checks: dict[str, Any] | None) -> list[Issue]:
    ctx = {"ai_checks": ai_checks or {}}
    issues: list[Issue] = []
    for rule in RULES:
        issues.extend(rule(pages, ctx))
    apply_value_boost(issues, pages)
    return issues


# Regels die per pagina iets zeggen, zonder de rest van de site te kennen (sitemap-monitor).
# Buiten de monitor: regels die over de hele site kijken (dubbele titels, hreflang,
# robots.txt, AI-checks) en regels zonder data in de monitor (Core Web Vitals, Ahrefs).
PAGE_RULES: list[Rule] = [
    rule_status,
    rule_redirects,
    rule_indexability,
    rule_onpage,
    rule_links_and_speed,
    rule_lang,
    rule_open_graph,
]


def generate_page_issues(pages: list[LaunchScanPage]) -> list[Issue]:
    """Actiepunten per pagina met PAGE_RULES (sitemap-monitor).

    Elke pagina wordt los beoordeeld. Regels die normaal één sitebreed punt geven
    (lang, Open Graph) leveren zo een punt op die ene pagina op, met `page_id` en
    `url` van die pagina: de monitor vervangt actiepunten per URL.
    """
    ctx: dict[str, Any] = {"ai_checks": {}}
    issues: list[Issue] = []
    for page in pages:
        for rule in PAGE_RULES:
            for issue in rule([page], ctx):
                if issue.get("page_id") is None:
                    issue = {**issue, "page_id": page.id, "url": page.url}
                issues.append(issue)
    apply_value_boost(issues, pages)
    return issues


# --- fase 2: GEO/SEO-checklist ---------------------------------------------
from app.features.launch_checklist.services.geo_checklist import (  # noqa: E402
    ITEMS as _GEO_ITEMS,
    SECTION_ISSUE_CATEGORY as _GEO_CATEGORY,
)

for _item in _GEO_ITEMS.values():
    ISSUE_TYPES[f"geo_{_item.key}"] = {
        "label": _item.label,
        "category": _GEO_CATEGORY.get(_item.section, "techniek"),
    }


def generate_geo_issues(checklist: dict[str, dict[str, Any]], manual_states: dict[str, str | None]) -> list[Issue]:
    """Eén actiepunt per niet-ok auto-checklistpunt.

    Punten die fase 1 al als pagina-issues oplevert (f1_issue_types) en punten
    die handmatig afgerond / n.v.t. zijn, slaan we over.
    """
    issues: list[Issue] = []
    for key, result in checklist.items():
        item = _GEO_ITEMS.get(key)
        if item is None or item.mode == "manual" or item.f1_issue_types:
            continue
        if manual_states.get(key) in {"afgerond", "nvt"}:
            continue
        status = result.get("status")
        if status not in {"error", "warning"}:
            continue
        severity = "laag" if item.priority == "laag" else ("hoog" if status == "error" else "middel")
        issues.append({
            "issue_type": f"geo_{key}",
            "category": _GEO_CATEGORY.get(item.section, "techniek"),
            "severity": severity,
            "page_id": None,
            "url": None,
            "title": f"{item.label}: {result.get('message', '')}"[:500],
            "description": result.get("message") or "",
            "recommendation": item.description or None,
            "details": {"evidence": result.get("evidence") or [], **({"data": result.get("details")} if result.get("details") else {})},
        })
    return issues


# --- fase 3: content & onpage ---------------------------------------------
from app.features.launch_checklist.services.content_checklist import (  # noqa: E402
    ITEMS as _CONTENT_ITEMS,
    SECTION_ISSUE_CATEGORY as _CONTENT_CATEGORY,
)

for _item in _CONTENT_ITEMS.values():
    ISSUE_TYPES[_item.key] = {
        "label": _item.label,
        "category": _CONTENT_CATEGORY.get(_item.section, "content"),
    }

_CONTENT_RECOMMENDATIONS: dict[str, str] = {
    "c3_meta_fixed": "Werk de resterende titel- en meta-problemen uit fase 1 bij en draai de fase 3-scan opnieuw.",
    "c3_redirects_404": "Pas de links aan zodat ze direct naar de juiste, bestaande pagina wijzen.",
    "c3_keywords": "Bepaal het focuszoekwoord en de zoekintentie en herschrijf de tekst daarop; houd zinnen kort.",
    "c3_headings": "Gebruik één H1 en logische tussenkoppen; begin elke sectie met 2-3 zinnen uitleg.",
    "c3_scannable": "Voeg opsommingen, tabellen of een blok met kernpunten toe.",
    "c3_answer_first": "Geef in de eerste alinea direct antwoord op de vraag van de bezoeker.",
    "c3_faq": "Voeg een FAQ toe met echte vragen van klanten (verifieer de vragen bij de klant).",
    "c3_eeat": "Voeg eigen foto's, projecten/cases en reviews toe die ervaring en expertise aantonen.",
    "c3_conversion": "Zorg voor een duidelijke call-to-action boven de vouw en na elke hoofdsectie.",
    "c3_meta_title": "Schrijf een unieke meta titel van maximaal 60 tekens / 580 pixels met het zoekwoord vooraan.",
    "c3_meta_description": "Schrijf een unieke meta description van maximaal 160 tekens / 920 pixels met een reden om te klikken.",
    "c3_internal_links": "Link vanuit de lopende tekst naar relevante dienst- en blogpagina's met beschrijvende linktekst.",
    "c3_images": "Geef elke inhoudsafbeelding een beschrijvende alt-tekst en bestandsnaam.",
    "c3_local": "Noem plaats, regio en werkgebied in titel, H1, eerste alinea en lopende tekst.",
    "c3_landing_pages": "Maak landingspagina's voor de ontbrekende combinaties van dienst en locatie.",
    "c3_blogs": "Plan blogs in op de voorgestelde onderwerpen.",
    "c3_other_content": "Voeg de ontbrekende pagina's toe (FAQ, cases, over ons).",
}


def content_issue(
    key: str, check: dict[str, Any], *, page_id: str | None, url: str | None, path: str | None,
    ai: bool = False,
) -> Issue:
    """Actiepunt voor één fase-3 checklistpunt (per pagina, of sitebreed zonder url)."""
    item = _CONTENT_ITEMS[key]
    status = check.get("status")
    severity = "hoog" if status == "error" else ("middel" if item.priority != "laag" else "laag")
    message = check.get("message") or item.label
    title = f"{message} – {path}" if path else f"{item.label}: {message}"
    details: dict[str, Any] = {"evidence": check.get("evidence") or []}
    if check.get("details"):
        details["data"] = check["details"]
    if ai:
        details["source"] = "ai"
    return {
        "issue_type": key,
        "category": _CONTENT_CATEGORY.get(item.section, "content"),
        "severity": severity,
        "page_id": page_id,
        "url": url,
        "title": title[:500],
        "description": message,
        "recommendation": _CONTENT_RECOMMENDATIONS.get(key) or item.description or None,
        "details": details,
    }


def generate_content_issues(
    pages: list[Any],
    page_checks: dict[str, dict[str, dict[str, Any]]],
    items: dict[str, dict[str, Any]],
    manual_states: dict[str, str | None],
) -> list[Issue]:
    """Actiepunten van de fase-3 regelcontrole.

    Per pagina één actiepunt per checklistpunt met een probleem; sitebrede
    punten (hercontrole fase 1, ontbrekende content) één actiepunt in totaal.
    Punten die handmatig afgerond / n.v.t. zijn, slaan we over.
    """
    skip = {k for k, v in manual_states.items() if v in {"afgerond", "nvt"}}
    issues: list[Issue] = []
    for page in pages:
        for key, check in (page_checks.get(page.id) or {}).items():
            if key in skip or key not in _CONTENT_ITEMS:
                continue
            if check.get("status") not in {"error", "warning"}:
                continue
            issues.append(content_issue(
                key, check, page_id=page.source_page_id, url=page.url, path=page.path))
    page_level = {k for checks in page_checks.values() for k in checks}
    for key, result in items.items():
        if key in skip or key in page_level or key not in _CONTENT_ITEMS:
            continue
        if result.get("status") in {"error", "warning"}:
            issues.append(content_issue(key, result, page_id=None, url=None, path=None))
    return issues


# --- fase 4: kwartaal GEO-werkzaamheden -------------------------------------
from app.features.launch_checklist.services.quarterly_checklist import (  # noqa: E402
    ITEM_ISSUE_CATEGORY as _QUARTERLY_CATEGORY,
    ITEMS as _QUARTERLY_ITEMS,
)

for _item in _QUARTERLY_ITEMS.values():
    ISSUE_TYPES[_item.key] = {
        "label": _item.label,
        "category": _QUARTERLY_CATEGORY.get(_item.key, "techniek"),
    }

_QUARTERLY_RECOMMENDATIONS: dict[str, str] = {
    "c4_ai_scan": "Bekijk welke AI-checks zijn verslechterd en herstel die (robots.txt, sitemap, schema, bereikbaarheid).",
    "c4_new_pages": "Zorg dat de pagina bereikbaar is (200), indexeerbaar (geen noindex), een eigen canonical heeft en "
                    "in de sitemap staat. Vraag daarna indexering aan in Search Console.",
    "c4_schema_validation": "Herstel de JSON-LD (ongeldige JSON, ontbrekende verplichte eigenschappen) en controleer de "
                            "pagina met de Rich Results Test van Google.",
    "c4_search_console": "Bekijk de melding in Search Console (URL-inspectie, Sitemaps, Prestaties), los de oorzaak "
                         "op en vraag waar nodig opnieuw indexering aan.",
    "c4_bing_webmaster": "Bekijk de melding in Bing Webmaster Tools (Site Explorer, Sitemaps, URL Inspection), los "
                         "de oorzaak op en dien de URL of sitemap daarna opnieuw in.",
}

# Bing kan honderden URL's met een crawlfout melden: de rest staat bij Vergelijking.
MAX_BING_CRAWL_ISSUES = 25
# Idem voor de URL-inspectie van Google, per soort (niet geïndexeerd, rich results).
MAX_GSC_URL_ISSUES = 25


def _quarterly_issue(
    key: str, severity: str, *, page_id: str | None, url: str | None, title: str, description: str,
    details: dict[str, Any],
) -> Issue:
    return {
        "issue_type": key,
        "category": _QUARTERLY_CATEGORY.get(key, "techniek"),
        "severity": severity,
        "page_id": page_id,
        "url": url,
        "title": title[:500],
        "description": description,
        "recommendation": _QUARTERLY_RECOMMENDATIONS.get(key),
        "details": details,
    }


def generate_quarterly_issues(
    items: dict[str, dict[str, Any]], manual_states: dict[str, str | None]
) -> list[Issue]:
    """Actiepunten van de fase-4 checklist.

    Nieuwe pagina's en schemafouten krijgen een actiepunt per pagina; de
    AI-vergelijking één actiepunt voor de site. Search Console geeft een actiepunt
    per niet-geïndexeerde pagina en per sitemap met meldingen, plus één voor een
    sterke daling in klikken. Punten die handmatig afgerond of
    n.v.t. zijn, slaan we over. Kapotgegane bestaande pagina's leveren al een
    4xx/5xx-actiepunt op via de fase 1-regels.
    """
    skip = {k for k, v in manual_states.items() if v in {"afgerond", "nvt"}}
    issues: list[Issue] = []

    ai = items.get("c4_ai_scan") or {}
    if "c4_ai_scan" not in skip and ai.get("status") in {"error", "warning"}:
        issues.append(_quarterly_issue(
            "c4_ai_scan", "hoog" if ai["status"] == "error" else "middel", page_id=None, url=None,
            title=f"AI-vindbaarheid verslechterd: {ai.get('message', '')}",
            description=ai.get("message") or "",
            details={"evidence": ai.get("evidence") or []},
        ))

    new_pages = items.get("c4_new_pages") or {}
    if "c4_new_pages" not in skip:
        for row in ((new_pages.get("details") or {}).get("new") or []):
            if row.get("result") not in {"error", "warning"}:
                continue
            problems = ", ".join(row.get("problems") or [])
            issues.append(_quarterly_issue(
                "c4_new_pages", "hoog" if row["result"] == "error" else "middel",
                page_id=row.get("page_id"), url=row.get("url"),
                title=f"Nieuwe pagina {problems} – {row.get('path')}",
                description=f"Nieuwe pagina sinds de vorige ronde: {problems}.",
                details={"evidence": [], "data": row},
            ))

    schema = items.get("c4_schema_validation") or {}
    if "c4_schema_validation" not in skip:
        from app.features.launch_checklist.services.schema_validate import describe_problem

        for row in ((schema.get("details") or {}).get("pages") or []):
            parts = [describe_problem(p) for p in row.get("problems") or []]
            if row.get("invalid_blocks"):
                parts.insert(0, f"{row['invalid_blocks']}× ongeldige JSON-LD")
            if row.get("lost_types"):
                parts.append("schema-types verdwenen: " + ", ".join(row["lost_types"]))
            issues.append(_quarterly_issue(
                "c4_schema_validation", "hoog" if row.get("result") == "error" else "laag",
                page_id=row.get("page_id"), url=row.get("url"),
                title=f"Schema: {parts[0] if parts else 'controleren'} – {row.get('path')}",
                description="; ".join(parts) + ".",
                details={"evidence": parts, "data": row},
            ))

    search_console = items.get("c4_search_console") or {}
    if "c4_search_console" not in skip:
        gsc = search_console.get("details") or {}
        not_indexed = sorted(gsc.get("not_indexed") or [], key=lambda r: r.get("state") != "blocked")
        for row in not_indexed[:MAX_GSC_URL_ISSUES]:
            blocked = row.get("state") == "blocked"
            issues.append(_quarterly_issue(
                "c4_search_console", "hoog" if blocked else "middel", page_id=None, url=row.get("url"),
                title=f"Niet geïndexeerd door Google: {row.get('reason')} – {row.get('url')}",
                description=f"Volgens de URL-inspectie in Search Console is deze pagina niet opgenomen: "
                            f"{row.get('reason')}.",
                details={"evidence": [], "data": row},
            ))
        rich_errors = [r for r in gsc.get("rich_results") or [] if r.get("errors")]
        for row in rich_errors[:MAX_GSC_URL_ISSUES]:
            messages = [
                f"{i.get('type') or 'Rich result'}: {i.get('message')}"
                for i in row.get("issues") or [] if i.get("severity") == "ERROR"
            ]
            count = int(row.get("errors") or 0)
            issues.append(_quarterly_issue(
                "c4_search_console", "middel", page_id=None, url=row.get("url"),
                title=f"Rich results: {count} {'fout' if count == 1 else 'fouten'} volgens Google – {row.get('url')}",
                description="Volgens de URL-inspectie in Search Console komt deze pagina door fouten in de "
                            "structured data niet in aanmerking voor rich results: " + "; ".join(messages[:3]) + ".",
                details={"evidence": messages, "data": row},
            ))
        for row in gsc.get("sitemaps") or []:
            errors, warnings = int(row.get("errors") or 0), int(row.get("warnings") or 0)
            counts = (f"{errors} {'fout' if errors == 1 else 'fouten'}, "
                      f"{warnings} {'waarschuwing' if warnings == 1 else 'waarschuwingen'}")
            issues.append(_quarterly_issue(
                "c4_search_console", "hoog" if row.get("errors") else "laag", page_id=None, url=row.get("path"),
                title=f"Sitemap in Search Console: {counts} – {row.get('path')}",
                description=f"Search Console meldt {counts} bij deze sitemap.",
                details={"evidence": [], "data": row},
            ))
        if gsc.get("clicks_drop_pct") is not None:
            drop = f"{abs(gsc['clicks_drop_pct']):g}%"
            issues.append(_quarterly_issue(
                "c4_search_console", "middel", page_id=None, url=None,
                title=f"Klikken uit Google {drop} gedaald t.o.v. de vorige periode",
                description=f"Search Console toont {drop} minder klikken dan in de periode ervoor. Bekijk bij "
                            "Vergelijking welke zoekopdrachten en pagina's het meest zijn gedaald.",
                details={"evidence": search_console.get("evidence") or []},
            ))

    bing_item = items.get("c4_bing_webmaster") or {}
    bing = bing_item.get("details") or {}
    # Zonder koppeling of zonder site in het Bing-account is er niets om actie op te ondernemen.
    if "c4_bing_webmaster" not in skip and bing.get("state") == "ok":
        for row in (bing.get("crawl_issues") or [])[:MAX_BING_CRAWL_ISSUES]:
            reason = ", ".join(i.get("label") or "" for i in row.get("issues") or []) or "crawlfout"
            issues.append(_quarterly_issue(
                "c4_bing_webmaster", "hoog" if row.get("severe") else "middel", page_id=None, url=row.get("url"),
                title=f"Crawlfout in Bing: {reason} – {row.get('url')}",
                description=f"Bing Webmaster meldt bij deze URL: {reason}.",
                details={"evidence": [], "data": row},
            ))
        for row in bing.get("sitemaps") or []:
            issues.append(_quarterly_issue(
                "c4_bing_webmaster", "hoog", page_id=None, url=row.get("url"),
                title=f"Sitemap in Bing Webmaster heeft status {row.get('status') or 'onbekend'} – {row.get('url')}",
                description="Bing kon deze sitemap niet verwerken.",
                details={"evidence": [], "data": row},
            ))
        if bing.get("no_sitemap"):
            issues.append(_quarterly_issue(
                "c4_bing_webmaster", "middel", page_id=None, url=None,
                title="Geen sitemap ingediend in Bing Webmaster Tools",
                description="Zonder sitemap vindt Bing nieuwe pagina's later. Dien de sitemap in bij Bing Webmaster "
                            "Tools (Sitemaps).",
                details={"evidence": []},
            ))
        if bing.get("malware"):
            issues.append(_quarterly_issue(
                "c4_bing_webmaster", "hoog", page_id=None, url=None,
                title=f"Bing meldt malware op {bing['malware']} URL('s)",
                description="Bing toont bij malware een waarschuwing in de zoekresultaten. Controleer de site en "
                            "vraag daarna een herbeoordeling aan in Bing Webmaster Tools.",
                details={"evidence": bing_item.get("evidence") or []},
            ))
        if bing.get("index_drop_pct") is not None:
            drop = f"{abs(bing['index_drop_pct']):g}%"
            issues.append(_quarterly_issue(
                "c4_bing_webmaster", "middel", page_id=None, url=None,
                title=f"Pagina's in de Bing-index {drop} gedaald",
                description=f"Bing heeft {drop} minder pagina's van de site in de index dan aan het begin van de "
                            "meetperiode. Controleer de crawlfouten en de sitemap in Bing Webmaster Tools.",
                details={"evidence": bing_item.get("evidence") or []},
            ))
        if bing.get("clicks_drop_pct") is not None:
            drop = f"{abs(bing['clicks_drop_pct']):g}%"
            issues.append(_quarterly_issue(
                "c4_bing_webmaster", "laag", page_id=None, url=None,
                title=f"Klikken uit Bing {drop} gedaald t.o.v. de vorige periode",
                description=f"Bing Webmaster toont {drop} minder klikken dan in de periode ervoor. Bekijk bij "
                            "Vergelijking welke zoekopdrachten en pagina's het meest zijn gedaald.",
                details={"evidence": bing_item.get("evidence") or []},
            ))
    return issues
