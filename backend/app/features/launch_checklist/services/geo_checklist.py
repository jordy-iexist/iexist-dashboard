"""Definitie van de fase-2 GEO/SEO-checklist + samenvoegen met handmatige status.

Punten staan vast in code. `mode`:
- auto:   de scan bepaalt de status (handmatig overrulen kan altijd).
- manual: alleen handmatig af te vinken; de scan zet hooguit evidence klaar.
- hybrid: de scan geeft een hint, maar een mens moet het bevestigen.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Mode = Literal["auto", "manual", "hybrid"]
AutoStatus = Literal["ok", "warning", "error", "nvt", "unknown", "info"]
ManualStatus = Literal["open", "afgerond", "nvt"]


@dataclass(frozen=True)
class ChecklistItem:
    key: str
    section: str
    label: str
    mode: Mode = "auto"
    applies_to: Literal["all", "webshop"] = "all"
    priority: Literal["hoog", "normaal", "laag"] = "normaal"
    description: str = ""
    # Punten die fase 1 al als (pagina-)actiepunten oplevert: geen dubbele issues.
    f1_issue_types: tuple[str, ...] = ()


SECTIONS: list[tuple[str, str]] = [
    ("algemeen", "Algemeen"),
    ("schema", "Schema.org / gestructureerde data"),
    ("entiteit", "Entiteit & merkvertrouwen"),
    ("crawl", "Crawlbaarheid & indexatie"),
    ("ai", "AI-bots & crawlers"),
]
SECTION_LABELS = dict(SECTIONS)
# Issue-categorie per sectie (sluit aan op de bestaande categorieën in de UI).
SECTION_ISSUE_CATEGORY = {
    "algemeen": "techniek",
    "schema": "schema",
    "entiteit": "entiteit",
    "crawl": "techniek",
    "ai": "ai",
}

PROFILE_PLATFORMS: list[tuple[str, str]] = [
    ("linkedin", "LinkedIn"),
    ("facebook", "Facebook"),
    ("instagram", "Instagram"),
    ("tiktok", "TikTok"),
    ("youtube", "YouTube"),
    ("gmb", "Google Bedrijfsprofiel"),
    ("bing_places", "Bing Places"),
]

_ITEMS: list[ChecklistItem] = [
    # --- Algemeen ---------------------------------------------------------
    ChecklistItem("sitemap_xml", "algemeen", "XML-sitemap (sitemap_index.xml) aanwezig en bereikbaar"),
    ChecklistItem("sitemap_html", "algemeen", "HTML-sitemap aanwezig en bereikbaar"),
    # --- Schema -----------------------------------------------------------
    ChecklistItem("schema_organization", "schema", "Organization / LocalBusiness (websitebreed)", priority="hoog"),
    ChecklistItem("schema_org_nap", "schema", "NAP in Organization-markup (naam, adres, telefoon, KvK, openingstijden)", priority="hoog"),
    ChecklistItem("schema_breadcrumb", "schema", "BreadcrumbList (websitebreed)"),
    ChecklistItem("schema_service", "schema", "Service op dienstenpagina's"),
    ChecklistItem("schema_product", "schema", "Product op productpagina's"),
    ChecklistItem("schema_article", "schema", "BlogPosting / Article op blogs"),
    ChecklistItem("schema_person", "schema", "Person op blogs en/of over ons"),
    ChecklistItem("schema_faq", "schema", "FAQPage op pagina's met veelgestelde vragen"),
    ChecklistItem("schema_jobposting", "schema", "JobPosting op vacatures"),
    ChecklistItem("schema_brand", "schema", "Brand op merk- en productpagina's", applies_to="webshop"),
    ChecklistItem("schema_itemlist", "schema", "ItemList op categoriepagina's", applies_to="webshop"),
    ChecklistItem("schema_rating", "schema", "AggregateRating op pagina's met beoordelingen", applies_to="webshop",
                  description="'AggregateReview' bestaat niet als schema-type; Google gebruikt AggregateRating."),
    # --- Entiteit & merkvertrouwen -----------------------------------------
    ChecklistItem("gmb_claimed", "entiteit", "Google Bedrijfsprofiel geclaimd en gecontroleerd", mode="manual", priority="hoog"),
    ChecklistItem("bing_places_claimed", "entiteit", "Bing Places geclaimd en gecontroleerd", mode="manual"),
    ChecklistItem("directories_consistent", "entiteit", "Bedrijvengidsen en branchevermeldingen gecontroleerd op gelijke gegevens", mode="manual"),
    *[
        ChecklistItem(f"sameas_{key}", "entiteit", f"sameAs-link in Organization-markup naar {label}")
        for key, label in PROFILE_PLATFORMS
    ],
    ChecklistItem("sameas_other", "entiteit", "sameAs-links naar overige profielen (wanneer relevant)", mode="hybrid", priority="laag"),
    *[
        ChecklistItem(f"nap_{key}", "entiteit", f"NAP-controle: gegevens gelijk op {label}", mode="manual")
        for key, label in PROFILE_PLATFORMS
    ],
    ChecklistItem("about_page", "entiteit", "Over ons-pagina aanwezig"),
    ChecklistItem("trust_kvk", "entiteit", "Vertrouwenssignaal zichtbaar: KvK-nummer"),
    ChecklistItem("trust_btw", "entiteit", "Vertrouwenssignaal zichtbaar: BTW-nummer"),
    ChecklistItem("trust_terms", "entiteit", "Vertrouwenssignaal zichtbaar: algemene voorwaarden"),
    ChecklistItem("trust_privacy", "entiteit", "Vertrouwenssignaal zichtbaar: privacyverklaring"),
    ChecklistItem("trust_contact", "entiteit", "Vertrouwenssignaal zichtbaar: contactgegevens"),
    ChecklistItem("authors_bio", "entiteit", "Auteurs en teamleden met bio en foto op de website", mode="hybrid"),
    # --- Crawlbaarheid & indexatie ------------------------------------------
    ChecklistItem("canonicals", "crawl", "Canonicals gecontroleerd op alle belangrijke pagina's", f1_issue_types=("canonical_mismatch",)),
    ChecklistItem("sitemap_exclusions", "crawl", "Uitsluitingen uit de sitemap (noindex, parameter-URL's, tag-/auteursarchieven, verlopen vacatures)",
                  f1_issue_types=("noindex_in_sitemap", "redirect_in_sitemap")),
    ChecklistItem("redirects_404", "crawl", "Redirectketens en 404's opgelost", priority="hoog",
                  f1_issue_types=("redirect_chain", "status_4xx", "status_5xx")),
    ChecklistItem("internal_404_links", "crawl", "Interne links naar 404's gecorrigeerd", f1_issue_types=("broken_links",)),
    ChecklistItem("core_web_vitals", "crawl", "Paginasnelheid en Core Web Vitals gecontroleerd",
                  f1_issue_types=("cwv_lcp", "cwv_cls", "cwv_inp", "slow_response")),
    ChecklistItem("click_depth", "crawl", "Elke dienst- of productpagina binnen drie klikken vanaf de homepage"),
    ChecklistItem("pagination", "crawl", "Paginatie (page/2, page/3) gecontroleerd op indexatie en canonicals"),
    ChecklistItem("orphan_pages", "crawl", "Verweesde pagina's (zonder interne links) gevonden en gekoppeld"),
    ChecklistItem("thin_duplicate", "crawl", "Dunne en dubbele pagina's samengevoegd of verwijderd",
                  f1_issue_types=("thin_content", "title_duplicate", "meta_duplicate", "h1_duplicate")),
    # --- AI-bots & crawlers -------------------------------------------------
    ChecklistItem("robots_txt", "ai", "robots.txt aanwezig en bereikbaar", f1_issue_types=("ai_robots_txt",)),
    ChecklistItem("ai_access_robots", "ai", "AI-bots (GPTBot, ClaudeBot, PerplexityBot, Google-Extended) niet geblokkeerd in robots.txt",
                  priority="hoog", f1_issue_types=("ai_ai_bots_blocked",)),
    ChecklistItem("ai_access_cdn", "ai", "AI-toegang niet geblokkeerd door CDN/hosting (o.a. Cloudflare)", priority="hoog"),
    ChecklistItem("llms_txt", "ai", "llms.txt aanwezig en bereikbaar", priority="laag",
                  description="Lage prioriteit: het effect van llms.txt is nog niet bewezen.", f1_issue_types=("ai_llms_txt",)),
    ChecklistItem("ssr_content", "ai", "Belangrijkste content server-side in de HTML (niet achter JavaScript of klik-om-te-openen)",
                  f1_issue_types=("ai_ssr_content",)),
    ChecklistItem("bing_webmaster", "ai", "Bing Webmaster Tools gekoppeld en sitemap ingediend", mode="manual",
                  description="ChatGPT Search leunt sterk op de Bing-index."),
    ChecklistItem("indexnow", "ai", "IndexNow ingesteld", mode="hybrid"),
]

ITEMS: dict[str, ChecklistItem] = {i.key: i for i in _ITEMS}
MANUAL_STATUSES = {"open", "afgerond", "nvt"}


def effective_status(item: ChecklistItem, auto: dict[str, Any] | None, manual_status: str | None,
                     is_webshop: bool) -> str:
    """'done' | 'open' | 'nvt'."""
    if item.applies_to == "webshop" and not is_webshop and manual_status not in {"afgerond", "open"}:
        return "nvt"
    if manual_status == "afgerond":
        return "done"
    if manual_status == "nvt":
        return "nvt"
    if manual_status == "open":
        return "open"
    if item.mode == "manual" or auto is None:
        return "open"
    status = auto.get("status")
    if status == "nvt":
        return "nvt"
    if status == "ok":
        return "done"
    return "open"


def merge_checklist(
    auto_items: dict[str, Any] | None,
    states: dict[str, Any],
    *,
    is_webshop: bool,
    sections: list[tuple[str, str]] | None = None,
    items: list[ChecklistItem] | None = None,
) -> dict[str, Any]:
    """Combineer auto-resultaten (laatste scan van de fase) met handmatige states.

    `states`: item_key → object met manual_status, note, updated_at, updated_by
    en de Monday-koppeling (external_url, pushed_at).
    `sections`/`items`: catalogus van de fase (standaard fase 2).
    """
    auto_items = auto_items or {}
    catalog_sections = SECTIONS if sections is None else sections
    catalog_items = _ITEMS if items is None else items
    sections: list[dict[str, Any]] = []
    total_done = total_applicable = 0
    for section_key, section_label in catalog_sections:
        items_out: list[dict[str, Any]] = []
        done = applicable = 0
        for item in catalog_items:
            if item.section != section_key:
                continue
            state = states.get(item.key)
            manual_status = getattr(state, "manual_status", None) if state else None
            auto = auto_items.get(item.key)
            eff = effective_status(item, auto, manual_status, is_webshop)
            if eff != "nvt":
                applicable += 1
                if eff == "done":
                    done += 1
            items_out.append({
                "key": item.key,
                "label": item.label,
                "description": item.description or None,
                "mode": item.mode,
                "applies_to": item.applies_to,
                "priority": item.priority,
                "auto": auto,
                "manual_status": manual_status,
                "note": getattr(state, "note", None) if state else None,
                "updated_at": getattr(state, "updated_at", None) if state else None,
                "external_url": getattr(state, "external_url", None) if state else None,
                "pushed_at": getattr(state, "pushed_at", None) if state else None,
                "effective": eff,
                "f1_issue_types": list(item.f1_issue_types),
            })
        total_done += done
        total_applicable += applicable
        sections.append({
            "key": section_key,
            "label": section_label,
            "items": items_out,
            "done": done,
            "total": applicable,
        })
    return {
        "sections": sections,
        "done": total_done,
        "total": total_applicable,
        "percent": round(100 * total_done / total_applicable) if total_applicable else 0,
    }
