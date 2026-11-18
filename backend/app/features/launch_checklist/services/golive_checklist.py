"""Definitie van de livegangchecklist: controle direct na het live zetten van een nieuwe website.

Staat los van de SEO/GEO-scan (fase 1-4): werkt op het live domein, ook voor een
klant zonder nulmeting. Livegangscans zijn `LaunchScan`-rijen met `phase = 5`.
Keys hebben de prefix `gl_`, omdat de handmatige status per klant en item_key
wordt opgeslagen (zonder fase-kolom, `period` leeg).

Zolang er geen livegangscan is, hebben automatische punten geen resultaat: ze
staan dan op open en zijn met de hand af te vinken (zie `effective_status`).
"""
from __future__ import annotations

from typing import Any

from app.features.launch_checklist.services.geo_checklist import (
    ChecklistItem,
    merge_checklist,
)

PHASE = 5
# De dagelijkse sitemap-monitor: één doorlopende `LaunchScan` per klant met `phase = 6`.
# Staat hier naast PHASE zodat alle fasenummers buiten 1-4 op één plek staan.
MONITOR_PHASE = 6
KEY_PREFIX = "gl_"

SECTIONS: list[tuple[str, str]] = [
    ("domein", "Domein, HTTPS & redirects"),
    ("indexatie", "Indexatie & testomgeving"),
    ("meting", "Tracking & cookies"),
    ("basis", "Basis"),
]
SECTION_LABELS = dict(SECTIONS)

_ITEMS: list[ChecklistItem] = [
    # --- Domein, HTTPS & redirects --------------------------------------------
    ChecklistItem("gl_https", "domein", "Site bereikbaar via HTTPS met geldig certificaat", priority="hoog",
                  description="De homepage laadt via https:// zonder certificaatwaarschuwing: het certificaat "
                              "is geldig, niet verlopen en hoort bij dit domein."),
    ChecklistItem("gl_http_redirect", "domein", "http:// verwijst met 301 door naar https://", priority="hoog",
                  description="Elk adres via http:// gaat met één permanente redirect (301) naar dezelfde "
                              "pagina op https://, niet via een 302 of een keten."),
    ChecklistItem("gl_host_variants", "domein", "www en non-www komen uit op één adres", priority="hoog",
                  description="De varianten met en zonder www (http en https) komen met een 301 uit op één "
                              "voorkeursadres; de andere variant geeft geen eigen kopie van de site."),
    ChecklistItem("gl_mixed_content", "domein", "Geen mixed content",
                  description="Pagina's op https laden geen afbeeldingen, scripts, stylesheets of iframes via "
                              "http://; browsers blokkeren die of tonen een waarschuwing."),
    ChecklistItem("gl_internal_urls", "domein", "Interne links en canonicals gebruiken https en het juiste adres",
                  description="Interne links, canonicals en hreflang wijzen naar https en het voorkeursadres "
                              "(juiste www-variant), niet naar http of een andere host."),
    # --- Indexatie & testomgeving ----------------------------------------------
    ChecklistItem("gl_robots_open", "indexatie", "robots.txt blokkeert de site niet", priority="hoog",
                  description="robots.txt bevat geen 'Disallow: /' voor alle bots, een veelvoorkomend "
                              "overblijfsel van de testomgeving."),
    ChecklistItem("gl_noindex", "indexatie", "Geen noindex op pagina's die gevonden moeten worden", priority="hoog",
                  description="Geen noindex in de meta robots of de X-Robots-Tag-header op pagina's die in "
                              "Google moeten komen; in WordPress staat 'Zoekmachines ontmoedigen' uit."),
    ChecklistItem("gl_sitemap", "indexatie", "XML-sitemap aanwezig, in robots.txt, met de juiste URL's",
                  description="Er is een XML-sitemap, robots.txt verwijst ernaar en de sitemap bevat alleen "
                              "live https-adressen van het juiste domein (geen testomgeving)."),
    ChecklistItem("gl_staging_refs", "indexatie", "Geen verwijzingen meer naar de testomgeving", priority="hoog",
                  description="Geen links, afbeeldingen, scripts of canonicals meer naar het adres van de "
                              "testomgeving (bijv. een staging- of tijdelijk subdomein)."),
    ChecklistItem("gl_pages_ok", "indexatie", "Alle pagina's bereikbaar en geen kapotte interne links",
                  priority="hoog",
                  description="Alle gevonden pagina's geven een 200 en interne links wijzen niet naar 404's, "
                              "serverfouten of redirects."),
    ChecklistItem("gl_staging_shielded", "indexatie", "Testomgeving offline of afgeschermd", mode="hybrid",
                  description="De testomgeving is offline, staat achter een wachtwoord of verwijst door naar de "
                              "live site, zodat Google geen dubbele site vindt. Controleer: open het oude "
                              "testadres in een privévenster."),
    ChecklistItem("gl_redirect_map", "indexatie", "Redirects van oude URL's gecontroleerd", mode="manual",
                  priority="hoog",
                  description="Bij een vervangen site: de belangrijkste oude URL's (uit de oude sitemap, Search "
                              "Console of Ahrefs) verwijzen met een 301 naar de best passende nieuwe pagina. "
                              "Controleer een steekproef met de hand of met een redirect-checker."),
    ChecklistItem("gl_search_console", "indexatie", "Search Console: property geverifieerd en sitemap ingediend",
                  mode="manual",
                  description="In Google Search Console is de property van het live domein geverifieerd (bij "
                              "voorkeur een domeinproperty) en is de XML-sitemap ingediend zonder fouten."),
    # --- Tracking & cookies ----------------------------------------------------
    ChecklistItem("gl_tracking_installed", "meting", "Trackingcode (GTM/GA4) staat op alle pagina's",
                  priority="hoog",
                  description="De Google Tag Manager- of GA4-code staat in de HTML van alle pagina's, met het "
                              "container- of meet-ID van de live site."),
    ChecklistItem("gl_tracking_verified", "meting", "Meting gecontroleerd in GA4 realtime / Tag Assistant",
                  mode="manual", priority="hoog",
                  description="Bezoek de site en controleer in GA4 (Rapporten › Realtime) of Tag Assistant dat "
                              "paginaweergaven en belangrijke events (bijv. formulierverzending) binnenkomen."),
    ChecklistItem("gl_consent_banner", "meting", "Cookiebanner aanwezig en werkt", mode="hybrid", priority="hoog",
                  description="Er verschijnt een cookiebanner en de keuze werkt: zonder toestemming worden geen "
                              "marketing- en analysecookies geplaatst. Controleer in een privévenster met de "
                              "ontwikkelaarstools (Application › Cookies) vóór en na accepteren."),
    # --- Basis -----------------------------------------------------------------
    ChecklistItem("gl_404", "basis", "Onbekende URL geeft een echte 404",
                  description="Een niet-bestaand adres geeft statuscode 404 (geen 200 of redirect naar de "
                              "homepage) en toont een nette foutpagina."),
    ChecklistItem("gl_viewport", "basis", "Viewport-meta op alle pagina's",
                  description="Alle pagina's hebben een viewport-meta-tag, zodat ze op mobiel goed schalen."),
    ChecklistItem("gl_favicon", "basis", "Favicon aanwezig", priority="laag",
                  description="Er is een favicon die laadt (link-tag in de HTML of /favicon.ico)."),
    ChecklistItem("gl_forms_tested", "basis", "Formulieren getest", mode="hybrid", priority="hoog",
                  description="Elk formulier (contact, offerte, nieuwsbrief) is op de live site ingevuld en "
                              "verzonden: de bedankpagina of -melding verschijnt en de e-mail komt aan bij de "
                              "klant en, waar van toepassing, de bevestiging bij de bezoeker."),
]

ITEMS: dict[str, ChecklistItem] = {i.key: i for i in _ITEMS}


def merge_golive_checklist(auto_items: dict[str, Any] | None, states: dict[str, Any]) -> dict[str, Any]:
    return merge_checklist(auto_items, states, is_webshop=False, sections=SECTIONS, items=_ITEMS)
