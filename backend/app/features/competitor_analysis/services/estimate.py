"""Schatting vooraf van een concurrentieanalyse: pagina's, doorlooptijd, Ahrefs-units en Claude-kosten.

`rates()` geeft de tarieven aan de wizard (de frontend rekent live mee), `estimate()` rekent
dezelfde formules in de backend uit en wordt bij het starten bewaard (`competitor_analyses.estimate`).

Formules (per analyse, `k` = zoekwoorden, `n` = top_n):
- pagina's        = k × (n + 1)                (top n plus de eigen pagina)
- Ahrefs-units    = k × (n + extra) × units_per_serp_position     (SERP-overzicht)
                  + k × units_per_keyword                          (volume/KD/intentie)
                  + eigen URL's × units_per_url                    (alleen met module "authority")
- Claude (USD)    = pagina's × usd_per_page + k × usd_per_keyword  (0 zonder sleutel)
- seconden        = pagina's × seconds_per_page + k × seconds_per_keyword

Modules die uit staan kosten niets: zonder `topics` én `eeat` draait aanroep B niet (alleen de
pagina-indeling A blijft), zonder `authority` geen URL-metrics.
"""
from __future__ import annotations

import math
from typing import Iterable

from app.features.competitor_analysis.schemas import Estimate, Rates
from app.services.ahrefs.client import SERP_EXTRA_POSITIONS

# --- Ahrefs (gemeten 23-11-2026 op "seo bureau", land nl; zie commentaar in de Ahrefs-client) ---

# SERP-overzicht: 15 units per rij; top_positions=10 gaf 21 rijen (315 units) omdat sitelinks,
# AI Overview-bronnen en vragen hun positie delen. Dus 31,5 units per opgevraagde positie.
AHREFS_UNITS_PER_SERP_POSITION = 31.5
# Volume, KD en intentie (keywords-explorer/overview): 31 units per zoekwoord (62 voor twee).
AHREFS_UNITS_PER_KEYWORD = 31
# DR/RD van een eigen doelpagina buiten de SERP (batch-analysis): nominaal 50 units voor twee
# URL's; niet precies gemeten, dus 25 per URL.
AHREFS_UNITS_PER_URL = 25
# Gemeten in een echte run (23 nov 2026): keywords_overview met één zoekwoord en url_metrics met
# één URL kostten elk 50 units. Beide gaan in één aanvraag per analyse.
AHREFS_MIN_UNITS_PER_REQUEST = 50

# --- Claude (claude-opus-5-5: $4 per miljoen invoertokens, $20 per miljoen uitvoertokens) ---
# Gekalibreerd op de echte proef van 23-11-2026 ("seo bureau", 7 pagina's, waarvan 2
# vergelijkingssites uitgesloten). Uitvoertokens zijn inclusief thinking. Nederlandse
# markdown kwam uit op ~2,1 tekens per token.
#
# Aanroep A (pagina-indeling, effort low): 7 pagina's = 5.139 tokens in, 418 uit = $0,029
# (7,5 s). Per pagina ~700 tokens in (URL, titel, H1, tot 30 koppen) en ~60 uit.
CLAUDE_USD_PER_PAGE_CLASSIFY = 0.004
# Aanroep B (inhoudsanalyse, effort high): 4 concurrenten + eigen pagina (74.000 tekens tekst)
# = 38.491 tokens in, 5.176 uit = $0,26 (46 s). Model: per pagina met tekst ~7.000 tokens
# in (gemiddeld ~15.000 tekens) en ~250 uit (E-E-A-T en dekking) = $0,033.
CLAUDE_USD_PER_PAGE_ANALYZE = 0.033
# Aanroep B, vast deel per zoekwoord: systeemtekst, kop en feitenblok (~3.000 tokens in)
# plus thinking, samenvatting, onderwerpen en verbeterpunten (~4.000 tokens uit) = $0,09.
CLAUDE_USD_PER_KEYWORD = 0.09
# Vaste koers voor de schatting in euro.
USD_TO_EUR = 0.90

# --- Doorlooptijd (beredeneerd) ---------------------------------------------------------------
# Per pagina: ophalen en uitlezen met ~8 tegelijk (~0,5 s per pagina) plus het aandeel van
# PageSpeed (~25 s per URL, paar tegelijk; loopt parallel en stopt na een budget van 8 minuten).
# Gemiddeld ~4 s per pagina.
SECONDS_PER_PAGE = 4.0
# Per zoekwoord: Ahrefs-SERP (~5 s), de Google-poging (tot 25 s, zoekwoorden na elkaar) en
# aanroep B (46 s gemeten met 5 pagina's, met 11 pagina's ~60-90 s; 3 tegelijk).
# Zonder aanroep B alleen het eerste deel.
SECONDS_PER_KEYWORD_BASE = 30.0
SECONDS_PER_KEYWORD_ANALYZE = 50.0

# Modules die aanroep B nodig hebben, en die de URL-metrics van Ahrefs nodig heeft.
ANALYZE_MODULES = frozenset({"topics", "eeat"})
AUTHORITY_MODULE = "authority"


def _eur(usd: float) -> float:
    return round(usd * USD_TO_EUR, 4)


def rates() -> Rates:
    """Tarieven voor de wizard; Claude- en tijdtarieven gaan uit van alle modules aan."""
    usd_per_page = CLAUDE_USD_PER_PAGE_CLASSIFY + CLAUDE_USD_PER_PAGE_ANALYZE
    return Rates(
        ahrefs_units_per_serp_position=AHREFS_UNITS_PER_SERP_POSITION,
        serp_extra_positions=SERP_EXTRA_POSITIONS,
        ahrefs_units_per_keyword=AHREFS_UNITS_PER_KEYWORD,
        ahrefs_units_per_url=AHREFS_UNITS_PER_URL,
        ahrefs_min_units_per_request=AHREFS_MIN_UNITS_PER_REQUEST,
        claude_usd_per_page=round(usd_per_page, 4),
        claude_eur_per_page=_eur(usd_per_page),
        claude_usd_per_keyword=CLAUDE_USD_PER_KEYWORD,
        claude_eur_per_keyword=_eur(CLAUDE_USD_PER_KEYWORD),
        seconds_per_page=SECONDS_PER_PAGE,
        seconds_per_keyword=SECONDS_PER_KEYWORD_BASE + SECONDS_PER_KEYWORD_ANALYZE,
    )


def runs_analysis(modules: Iterable[str]) -> bool:
    """Draait aanroep B (inhoudsanalyse)? Alleen met module `topics` of `eeat`."""
    return bool(ANALYZE_MODULES & set(modules))


def estimate(
    *,
    keywords: int,
    top_n: int,
    own_urls: int,
    modules: list[str],
    ai_configured: bool,
) -> Estimate:
    """Schatting voor `keywords` zoekwoorden met de top `top_n`.

    `own_urls` = aantal eigen doelpagina's (zoekwoorden met een doel-URL); hun DR/RD kost
    alleen units met module `authority`. Zonder Claude-sleutel (`ai_configured` False) zijn de
    AI-kosten 0 en telt de tijd van aanroep B niet mee.
    """
    keywords = max(0, keywords)
    pages = keywords * (top_n + 1)

    units = keywords * (top_n + SERP_EXTRA_POSITIONS) * AHREFS_UNITS_PER_SERP_POSITION
    if keywords:
        units += max(AHREFS_MIN_UNITS_PER_REQUEST, keywords * AHREFS_UNITS_PER_KEYWORD)
    if AUTHORITY_MODULE in modules and own_urls > 0:
        units += max(AHREFS_MIN_UNITS_PER_REQUEST, own_urls * AHREFS_UNITS_PER_URL)

    analyze = ai_configured and runs_analysis(modules)
    usd = 0.0
    if ai_configured and pages:
        usd = pages * CLAUDE_USD_PER_PAGE_CLASSIFY
        if analyze:
            usd += pages * CLAUDE_USD_PER_PAGE_ANALYZE + keywords * CLAUDE_USD_PER_KEYWORD

    per_keyword = SECONDS_PER_KEYWORD_BASE + (SECONDS_PER_KEYWORD_ANALYZE if analyze else 0.0)
    seconds = pages * SECONDS_PER_PAGE + keywords * per_keyword

    return Estimate(
        pages=pages,
        seconds=int(math.ceil(seconds)),
        ahrefs_units=int(math.ceil(units)),
        ai_cost_eur=round(usd * USD_TO_EUR, 2),
    )
