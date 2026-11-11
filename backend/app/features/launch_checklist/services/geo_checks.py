"""Automatische evaluatie van de fase-2 GEO/SEO-checklist.

`evaluate_checklist` werkt alleen op opgeslagen data (verrijkte fase-1 pagina's,
fase-1 ai_checks en de `extras` die de worker éénmalig ophaalt), zodat we de
checklist zonder nieuwe fetches kunnen herberekenen (bijv. na een
paginatype-correctie).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

from app.core.url_guard import is_safe_external_url
from app.db.models import LaunchScanPage
from app.features.launch_checklist.services.discovery import USER_AGENT, url_key
from app.features.launch_checklist.services.geo_checklist import ITEMS, PROFILE_PLATFORMS
from app.features.launch_checklist.services.geo_extract import all_types, platform_of, types_of
from app.features.launch_checklist.services.issues import (
    THIN_CONTENT_WORDS,
    _is_indexable_html,
    _is_ok_html,
    final_status,
    redirect_hops,
)
from app.features.launch_checklist.services.page_types import PAGE_TYPES, is_pagination

MAX_EVIDENCE_URLS = 15
ORG_TYPES = {
    "Organization", "LocalBusiness", "Corporation", "ProfessionalService", "Store", "Restaurant",
    "LegalService", "MedicalBusiness", "HomeAndConstructionBusiness", "AutomotiveBusiness",
    "FinancialService", "RealEstateAgent", "HealthAndBeautyBusiness", "Dentist", "Physician",
    "LodgingBusiness", "FoodEstablishment", "SportsActivityLocation", "EducationalOrganization",
    "NGO", "OnlineStore", "OnlineBusiness", "EmploymentAgency", "TravelAgency", "Electrician",
    "Plumber", "RoofingContractor", "GeneralContractor", "HVACBusiness", "Locksmith",
    "MovingCompany", "InsuranceAgency", "AccountingService", "Attorney", "Notary",
}
ARTICLE_TYPES = {"BlogPosting", "Article", "NewsArticle", "TechArticle", "Report"}
PRODUCT_TYPES = {"Product", "ProductGroup", "IndividualProduct"}
EXCLUDED_THIN_TYPES = {"contact", "juridisch", "archief"}


def is_org_type(t: str) -> bool:
    return t in ORG_TYPES or (t != "Service" and t.endswith(("Business", "Store", "Organization", "Service")))


def is_home_page(p: LaunchScanPage) -> bool:
    """Homepage = pad '/' (ook als het domein naar www of https doorverwijst)."""
    for candidate in (p.final_url, p.url):
        if not candidate:
            continue
        parsed = urlparse(candidate)
        if parsed.path in ("", "/") and not parsed.query:
            return True
    return False


def find_home(pages: list[LaunchScanPage]) -> LaunchScanPage | None:
    homes = [p for p in pages if is_home_page(p)]
    homes.sort(key=lambda p: (not _is_ok_html(p), bool(p.redirect_chain)))
    return homes[0] if homes else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _r(status: str, message: str, evidence: list[Any] | None = None, details: Any = None) -> dict[str, Any]:
    return {"status": status, "message": message, "evidence": evidence or [], "details": details}


def _urls(pages: Iterable[LaunchScanPage]) -> list[str]:
    return [p.url for p in pages][:MAX_EVIDENCE_URLS]


def _sig(p: LaunchScanPage) -> dict[str, Any]:
    return p.signals or {}


# --- extras (worker haalt dit één keer op) ---------------------------------

def _get(url: str) -> httpx.Response | None:
    if not is_safe_external_url(url):
        return None
    try:
        return httpx.get(url, follow_redirects=True, timeout=15.0, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError:
        return None


def check_sitemap_index(origin: str) -> dict[str, Any]:
    url = f"{origin}/sitemap_index.xml"
    resp = _get(url)
    if resp is None:
        return {"url": url, "status": None}
    body = resp.text[:500_000] if resp.status_code == 200 else ""
    content_type = resp.headers.get("content-type", "")
    is_xml = "xml" in content_type.lower() or body.lstrip().startswith("<?xml") or "<urlset" in body or "<sitemapindex" in body
    return {
        "url": url,
        "final_url": str(resp.url),
        "status": resp.status_code,
        "is_xml": bool(is_xml),
        "child_sitemaps": body.count("<sitemap>") + body.count("<sitemap "),
        "urls": body.count("<url>"),
    }


def check_html_sitemap(origin: str, linked: str | None) -> dict[str, Any]:
    candidates = [linked] if linked else []
    candidates += [f"{origin}/sitemap/", f"{origin}/html-sitemap/", f"{origin}/sitemap.html"]
    tried: list[dict[str, Any]] = []
    for url in candidates:
        resp = _get(url)
        if resp is None:
            tried.append({"url": url, "status": None})
            continue
        is_html = "html" in resp.headers.get("content-type", "").lower()
        tried.append({"url": url, "status": resp.status_code})
        if resp.status_code == 200 and is_html and url_key(str(resp.url)) != url_key(origin + "/"):
            links = resp.text.lower().count("<a ")
            return {"found": True, "url": str(resp.url), "linked": url == linked, "links": links, "tried": tried}
    return {"found": False, "tried": tried}


def detect_webshop(pages: list[LaunchScanPage]) -> dict[str, Any]:
    plugins: Counter[str] = Counter()
    product_pages = 0
    product_schema = 0
    for p in pages:
        sig = _sig(p)
        plugins.update(sig.get("plugins") or [])
        if p.page_type in {"product", "categorie"}:
            product_pages += 1
        if all_types(p.jsonld or []) & PRODUCT_TYPES:
            product_schema += 1
    reasons: list[str] = []
    for name in ("woocommerce", "shopify", "lightspeed", "magento"):
        if plugins.get(name):
            reasons.append(f"{name} gedetecteerd")
    if product_pages >= 3:
        reasons.append(f"{product_pages} product-/categoriepagina's")
    if product_schema >= 3:
        reasons.append(f"{product_schema} pagina's met Product-schema")
    return {"detected": bool(reasons), "reasons": reasons, "plugins": sorted(plugins)}


# --- evaluatie -------------------------------------------------------------

def _org_nodes(pages: list[LaunchScanPage]) -> list[tuple[LaunchScanPage, dict[str, Any]]]:
    out = []
    for p in pages:
        for node in p.jsonld or []:
            if isinstance(node, dict) and any(is_org_type(t) for t in types_of(node)):
                out.append((p, node))
    return out


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _address_text(value: Any) -> str | None:
    for v in _as_list(value):
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            parts = [v.get("streetAddress"), v.get("postalCode"), v.get("addressLocality"), v.get("addressCountry")]
            parts = [p if isinstance(p, str) else (p.get("name") if isinstance(p, dict) else None) for p in parts]
            text = ", ".join(str(p) for p in parts if p)
            if text:
                return text
    return None


def _org_nap(node: dict[str, Any]) -> dict[str, Any]:
    identifiers = []
    for ident in _as_list(node.get("identifier")):
        if isinstance(ident, dict):
            identifiers.append(f"{ident.get('name') or ident.get('propertyID') or 'id'}: {ident.get('value')}")
        elif ident:
            identifiers.append(str(ident))
    opening = node.get("openingHours") or node.get("openingHoursSpecification")
    location = node.get("location")
    address = node.get("address") or (location.get("address") if isinstance(location, dict) else None)
    return {
        "type": ", ".join(types_of(node)),
        "name": node.get("name") or node.get("legalName"),
        "address": _address_text(address),
        "telephone": node.get("telephone") or next(
            (cp.get("telephone") for cp in _as_list(node.get("contactPoint")) if isinstance(cp, dict) and cp.get("telephone")),
            None,
        ),
        "email": node.get("email") or next(
            (cp.get("email") for cp in _as_list(node.get("contactPoint")) if isinstance(cp, dict) and cp.get("email")),
            None,
        ),
        "kvk_or_id": ", ".join(identifiers) or node.get("taxID") or None,
        "vat": node.get("vatID"),
        "opening_hours": bool(opening),
        "logo": bool(node.get("logo")),
        "same_as": [s for s in _as_list(node.get("sameAs")) if isinstance(s, str)],
    }


def _coverage_result(
    pages: list[LaunchScanPage], expected: set[str], label_pages: str, label_schema: str,
) -> dict[str, Any]:
    if not pages:
        return _r("nvt", f"Geen {label_pages} gevonden.")
    missing = [p for p in pages if not (all_types(p.jsonld or []) & expected)]
    have = len(pages) - len(missing)
    pct = round(100 * have / len(pages))
    details = {"pages": len(pages), "with_schema": have, "coverage": pct}
    if not missing:
        return _r("ok", f"Alle {len(pages)} {label_pages} hebben {label_schema}.", details=details)
    status = "warning" if pct >= 50 else "error"
    return _r(status, f"{len(missing)} van de {len(pages)} {label_pages} missen {label_schema} ({pct}% dekking).",
              _urls(missing), details)


def evaluate_checklist(
    *,
    base_url: str,
    pages: list[LaunchScanPage],
    ai_checks: dict[str, Any] | None,
    extras: dict[str, Any],
    is_webshop: bool,
    discovery_source: str | None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    ok_html = [p for p in pages if _is_ok_html(p)]
    fetched = [p for p in ok_html if p.signals is not None]
    indexable = [p for p in ok_html if p.indexable is True]
    by_type: dict[str, list[LaunchScanPage]] = defaultdict(list)
    for p in indexable:
        by_type[p.page_type or "overig"].append(p)
    home = find_home(ok_html)
    ai_by_key = {c.get("key"): c for c in (ai_checks or {}).get("checks", [])}

    # ---------------- Algemeen ----------------
    sm = extras.get("sitemap_index") or {}
    if sm.get("status") == 200 and sm.get("is_xml"):
        msg = f"{sm.get('url')} is bereikbaar"
        if sm.get("child_sitemaps"):
            msg += f" en bevat {sm['child_sitemaps']} sub-sitemaps."
        elif sm.get("urls"):
            msg += f" ({sm['urls']} URL's)."
        else:
            msg += ", maar bevat geen sub-sitemaps of URL's."
        out["sitemap_xml"] = _r("ok" if (sm.get("child_sitemaps") or sm.get("urls")) else "warning", msg, [sm.get("url")], sm)
    else:
        others = ((ai_by_key.get("sitemap") or {}).get("details") or {}).get("sitemaps") or []
        if others:
            out["sitemap_xml"] = _r("warning", f"/sitemap_index.xml niet bereikbaar (status {sm.get('status')}), wel een andere sitemap gevonden.", others[:5], sm)
        else:
            out["sitemap_xml"] = _r("error", f"Geen bereikbare XML-sitemap gevonden (/sitemap_index.xml gaf status {sm.get('status')}).", details=sm)

    hs = extras.get("html_sitemap") or {}
    if hs.get("found"):
        out["sitemap_html"] = _r("ok", f"HTML-sitemap gevonden ({hs.get('links', 0)} links)" + (", gelinkt vanaf de site." if hs.get("linked") else ", maar niet gelinkt vanaf de site."), [hs.get("url")], hs)
    else:
        out["sitemap_html"] = _r("warning", "Geen HTML-sitemappagina gevonden voor bezoekers.", details=hs)

    # ---------------- Schema ----------------
    if not fetched:
        for key in [k for k, i in ITEMS.items() if i.section == "schema"]:
            out[key] = _r("unknown", "Geen pagina's opgehaald; schema kon niet worden gecontroleerd.")
    else:
        org = _org_nodes(fetched)
        org_pages = {p.id for p, _ in org}
        home_org = [n for p, n in org if home is not None and p.id == home.id]
        pct = round(100 * len(org_pages) / len(fetched))
        if home_org:
            out["schema_organization"] = _r("ok", f"Homepage heeft Organization/LocalBusiness-schema ({pct}% van de pagina's).", details={"coverage": pct})
        elif org:
            out["schema_organization"] = _r("warning", f"Organization-schema staat niet op de homepage, wel op {len(org_pages)} pagina's.", _urls(p for p, _ in org), {"coverage": pct})
        else:
            out["schema_organization"] = _r("error", "Geen Organization- of LocalBusiness-schema gevonden op de site.")

        primary = (home_org or [n for _, n in org] or [None])[0]
        if primary is None:
            out["schema_org_nap"] = _r("error", "Geen Organization-markup, dus ook geen NAP-gegevens in schema.")
        else:
            nap = _org_nap(primary)
            core_missing = [label for field, label in (("name", "naam"), ("address", "adres"), ("telephone", "telefoon")) if not nap.get(field)]
            extra_missing = [label for field, label in (("kvk_or_id", "KvK/identifier"), ("opening_hours", "openingstijden")) if not nap.get(field)]
            evidence = [f"{k}: {v}" for k, v in nap.items() if k != "same_as" and v not in (None, "", False)]
            if core_missing:
                out["schema_org_nap"] = _r("error" if len(core_missing) == 3 else "warning",
                                           f"Organization-markup mist: {', '.join(core_missing + extra_missing)}.", evidence, nap)
            elif extra_missing:
                out["schema_org_nap"] = _r("warning", f"Naam, adres en telefoon aanwezig; mist nog: {', '.join(extra_missing)}.", evidence, nap)
            else:
                out["schema_org_nap"] = _r("ok", "Naam, adres, telefoon, KvK/identifier en openingstijden staan in de markup.", evidence, nap)

        content_pages = [p for p in fetched if p.indexable is True and p.page_type not in {"home", "archief"}]
        with_bc = [p for p in content_pages if "BreadcrumbList" in all_types(p.jsonld or [])]
        if not content_pages:
            out["schema_breadcrumb"] = _r("nvt", "Geen subpagina's om te controleren.")
        else:
            bc_pct = round(100 * len(with_bc) / len(content_pages))
            missing = [p for p in content_pages if p not in with_bc]
            out["schema_breadcrumb"] = _r("ok" if bc_pct >= 90 else "warning" if bc_pct >= 40 else "error",
                                          f"{bc_pct}% van de subpagina's heeft BreadcrumbList.", _urls(missing), {"coverage": bc_pct})

        def typed(*types: str) -> list[LaunchScanPage]:
            return [p for p in fetched if p.indexable is True and p.page_type in types]

        out["schema_service"] = _coverage_result(typed("dienst"), {"Service"}, "dienstpagina's", "Service-schema")
        out["schema_product"] = _coverage_result(typed("product"), PRODUCT_TYPES, "productpagina's", "Product-schema")
        out["schema_article"] = _coverage_result(typed("blog"), ARTICLE_TYPES, "blogpagina's", "BlogPosting/Article-schema")
        person_pages = typed("blog", "over_ons")
        if not person_pages:
            out["schema_person"] = _r("nvt", "Geen blog- of over-ons-pagina's gevonden.")
        else:
            with_person = [p for p in person_pages if "Person" in all_types(p.jsonld or [])]
            if with_person:
                out["schema_person"] = _r("ok" if len(with_person) * 2 >= len(person_pages) else "warning",
                                          f"{len(with_person)} van de {len(person_pages)} blog-/over-ons-pagina's hebben Person-schema.",
                                          _urls(p for p in person_pages if p not in with_person))
            else:
                out["schema_person"] = _r("warning", "Geen Person-schema gevonden op blogs of over ons (auteur/teamleden).", _urls(person_pages))
        faq_pages = [p for p in fetched if p.indexable is True and (_sig(p).get("faq") or "FAQPage" in all_types(p.jsonld or []))]
        out["schema_faq"] = _coverage_result(faq_pages, {"FAQPage"}, "pagina's met FAQ", "FAQPage-schema")
        out["schema_jobposting"] = _coverage_result(typed("vacature"), {"JobPosting"}, "vacaturepagina's", "JobPosting-schema")
        if is_webshop:
            brand_pages = typed("product")
            if not brand_pages:
                out["schema_brand"] = _r("nvt", "Geen productpagina's gevonden.")
            else:
                no_brand = [p for p in brand_pages if "Brand" not in all_types(p.jsonld or [])
                            and not any(isinstance(n, dict) and n.get("brand") for n in (p.jsonld or []))]
                have = len(brand_pages) - len(no_brand)
                out["schema_brand"] = _r("ok" if not no_brand else "warning" if have else "error",
                                         f"{have} van de {len(brand_pages)} productpagina's hebben een Brand.", _urls(no_brand))
            out["schema_itemlist"] = _coverage_result(typed("categorie"), {"ItemList", "OfferCatalog"}, "categoriepagina's", "ItemList-schema")
            rating_pages = [p for p in fetched if p.indexable is True and _sig(p).get("reviews")]
            out["schema_rating"] = _coverage_result(rating_pages, {"AggregateRating"}, "pagina's met beoordelingen", "AggregateRating-schema")
        else:
            for key in ("schema_brand", "schema_itemlist", "schema_rating"):
                out[key] = _r("nvt", "Geen webshop.")

    # ---------------- Entiteit ----------------
    org_nodes = _org_nodes(fetched)
    same_as: dict[str, list[str]] = defaultdict(list)
    for _, node in org_nodes:
        for link in _org_nap(node)["same_as"]:
            platform = platform_of(link) or "other"
            if link not in same_as[platform]:
                same_as[platform].append(link)
    site_profiles: dict[str, list[str]] = defaultdict(list)
    for p in fetched:
        for platform, links in (_sig(p).get("profiles") or {}).items():
            for link in links:
                if link not in site_profiles[platform] and len(site_profiles[platform]) < 5:
                    site_profiles[platform].append(link)

    for key, label in PROFILE_PLATFORMS:
        in_schema = same_as.get(key) or []
        on_site = site_profiles.get(key) or []
        if not fetched:
            out[f"sameas_{key}"] = _r("unknown", "Geen pagina's opgehaald.")
        elif in_schema:
            out[f"sameas_{key}"] = _r("ok", f"{label} staat in sameAs.", in_schema)
        elif on_site:
            out[f"sameas_{key}"] = _r("error" if org_nodes else "warning",
                                      f"De site linkt naar {label}, maar het profiel staat niet in sameAs.", on_site)
        else:
            out[f"sameas_{key}"] = _r("warning", f"Geen {label}-profiel gevonden in sameAs of op de site. Zet op n.v.t. als de klant dit profiel niet heeft.")
    other_links = same_as.get("other") or []
    out["sameas_other"] = (
        _r("ok", f"{len(other_links)} overige profielen in sameAs.", other_links)
        if other_links else
        _r("info", "Geen overige profielen in sameAs (bijv. KvK, Trustpilot, branchegidsen). Alleen nodig wanneer relevant.",
           site_profiles.get("other") or [])
    )

    # Gevonden NAP op de site (niet vergeleken: het team beoordeelt).
    site_nap = _site_nap(fetched, home)
    nap_evidence = [f"{k}: {', '.join(v)}" for k, v in site_nap.items() if v and k != "sources"]
    for key, label in PROFILE_PLATFORMS:
        links = (same_as.get(key) or []) + [link for link in (site_profiles.get(key) or []) if link not in (same_as.get(key) or [])]
        out[f"nap_{key}"] = _r("info", f"Controleer of naam, adres en telefoon op {label} gelijk zijn aan de site.",
                               links[:5] + nap_evidence, {"profiles": links[:5], "site_nap": site_nap})
    gmb_links = (same_as.get("gmb") or []) + (site_profiles.get("gmb") or [])
    out["gmb_claimed"] = _r("info", "Controleer in Google Bedrijfsprofiel of het profiel geclaimd en geverifieerd is.", gmb_links[:5] + nap_evidence)
    bing_links = (same_as.get("bing_places") or []) + (site_profiles.get("bing_places") or [])
    out["bing_places_claimed"] = _r("info", "Controleer in Bing Places of de vermelding geclaimd en geverifieerd is.", bing_links[:5] + nap_evidence)
    out["directories_consistent"] = _r("info", "Vergelijk de NAP-gegevens hieronder met bedrijvengidsen (o.a. Telefoonboek, Goudengids, branchevermeldingen).", nap_evidence)

    about_pages = by_type.get("over_ons") or []
    about_link = _first_link(fetched, "about")
    if about_pages:
        out["about_page"] = _r("ok", f"Over ons-pagina gevonden ({len(about_pages)}).", _urls(about_pages))
    elif about_link:
        out["about_page"] = _r("ok", "Over ons-pagina gelinkt vanaf de site.", [about_link])
    elif fetched:
        out["about_page"] = _r("error", "Geen over ons-pagina gevonden.")
    else:
        out["about_page"] = _r("unknown", "Geen pagina's opgehaald.")

    out["trust_kvk"] = _found_signal(site_nap, "kvk", "KvK-nummer", fetched, schema_hint=bool(any(_org_nap(n)["kvk_or_id"] for _, n in org_nodes)))
    out["trust_btw"] = _found_signal(site_nap, "btw", "BTW-nummer", fetched, schema_hint=bool(any(_org_nap(n)["vat"] for _, n in org_nodes)))
    for key, kind, label, path_needles in (
        ("trust_terms", "terms", "algemene voorwaarden", ("voorwaarden", "terms")),
        ("trust_privacy", "privacy", "privacyverklaring", ("privacy",)),
    ):
        link = _first_link(fetched, kind)
        legal = [p for p in by_type.get("juridisch", []) if any(n in p.path.lower() for n in path_needles)]
        if link or legal:
            out[key] = _r("ok", f"Link naar {label} gevonden.", [link] if link else _urls(legal))
        elif fetched:
            out[key] = _r("error" if kind == "privacy" else "warning", f"Geen {label} gevonden op de site.")
        else:
            out[key] = _r("unknown", "Geen pagina's opgehaald.")
    contact_link = _first_link(fetched, "contact") or next((p.url for p in by_type.get("contact", [])), None)
    has_phone_or_mail = bool(site_nap.get("telefoon") or site_nap.get("e-mail"))
    if contact_link and has_phone_or_mail:
        out["trust_contact"] = _r("ok", "Contactpagina en telefoon/e-mail gevonden.", [contact_link] + nap_evidence)
    elif contact_link or has_phone_or_mail:
        out["trust_contact"] = _r("warning", "Contactgegevens maar deels gevonden" + (" (geen telefoon of e-mail in de HTML)." if contact_link else " (geen contactpagina)."),
                                  ([contact_link] if contact_link else []) + nap_evidence)
    elif fetched:
        out["trust_contact"] = _r("error", "Geen contactpagina of contactgegevens gevonden.")
    else:
        out["trust_contact"] = _r("unknown", "Geen pagina's opgehaald.")

    persons_with_image = []
    for p in fetched:
        for node in _walk_nodes(p.jsonld or []):
            if "Person" in types_of(node) and node.get("image") and (node.get("description") or node.get("jobTitle")):
                persons_with_image.append(p)
                break
    author_blocks = [p for p in fetched if (_sig(p).get("author_markers") or 0) > 0 and (_sig(p).get("author_images") or 0) > 0]
    if persons_with_image:
        out["authors_bio"] = _r("ok", f"Person-markup met foto en bio gevonden op {len(persons_with_image)} pagina's. Controleer of alle auteurs/teamleden erin staan.", _urls(persons_with_image))
    elif author_blocks:
        out["authors_bio"] = _r("warning", f"Auteur-/teamblokken met afbeelding gevonden op {len(author_blocks)} pagina's; controleer handmatig of er een bio bij staat.", _urls(author_blocks))
    else:
        out["authors_bio"] = _r("warning", "Geen auteurs of teamleden met bio en foto herkend. Controleer handmatig.")

    # ---------------- Crawl ----------------
    no_canonical = [p for p in indexable if not p.canonical]
    canon_elsewhere = [p for p in ok_html if p.indexability_reason == "Canonical naar andere URL"]
    if not indexable:
        out["canonicals"] = _r("unknown", "Geen indexeerbare pagina's.")
    elif not no_canonical and not canon_elsewhere:
        out["canonicals"] = _r("ok", f"Alle {len(indexable)} indexeerbare pagina's hebben een canonical.")
    else:
        parts = []
        if no_canonical:
            parts.append(f"{len(no_canonical)} pagina's zonder canonical")
        if canon_elsewhere:
            parts.append(f"{len(canon_elsewhere)} pagina's met canonical naar een andere URL")
        status = "error" if len(no_canonical) > 0.2 * len(indexable) else "warning"
        out["canonicals"] = _r(status, "; ".join(parts) + ".", _urls(no_canonical + canon_elsewhere),
                               {"missing": len(no_canonical), "elsewhere": len(canon_elsewhere)})

    sitemap_pages = [p for p in pages if p.in_sitemap]
    if not sitemap_pages:
        out["sitemap_exclusions"] = _r("unknown", "Geen sitemap-URL's in de scan (pagina's zijn gecrawld).")
    else:
        now = _now()
        groups: dict[str, list[LaunchScanPage]] = {
            "noindex": [p for p in sitemap_pages if "noindex" in (p.indexability_reason or "")],
            "canonical elders": [p for p in sitemap_pages if p.indexability_reason == "Canonical naar andere URL"],
            "redirect/fout": [p for p in sitemap_pages if p.redirect_chain or (final_status(p) or 0) >= 400 or p.status_code is None],
            "parameter-URL": [p for p in sitemap_pages if "?" in p.url],
            "tag-/auteursarchief": [p for p in sitemap_pages if re.search(r"/(tag|tags|author|auteur)/", p.path.lower())],
            "paginatie": [p for p in sitemap_pages if is_pagination(p.url)],
            "verlopen vacature": [p for p in sitemap_pages if _expired_job(p, now)],
        }
        bad = {k: v for k, v in groups.items() if v}
        if not bad:
            out["sitemap_exclusions"] = _r("ok", f"De sitemap ({len(sitemap_pages)} URL's) bevat geen URL's die eruit horen.")
        else:
            summary = ", ".join(f"{len(v)}× {k}" for k, v in bad.items())
            evidence = [f"{k}: {p.url}" for k, v in bad.items() for p in v[:5]]
            out["sitemap_exclusions"] = _r("error" if sum(len(v) for v in bad.values()) > 10 else "warning",
                                           f"Sitemap bevat URL's die eruit horen: {summary}.", evidence[:MAX_EVIDENCE_URLS],
                                           {k: len(v) for k, v in bad.items()})

    chains = [p for p in pages if redirect_hops(p) > 1]
    errors_4xx = [p for p in pages if (final_status(p) or 0) >= 400]
    if not chains and not errors_4xx:
        out["redirects_404"] = _r("ok", "Geen redirectketens of 4xx/5xx-pagina's gevonden.")
    else:
        parts = []
        if errors_4xx:
            parts.append(f"{len(errors_4xx)} pagina's met 4xx/5xx")
        if chains:
            parts.append(f"{len(chains)} redirectketens")
        out["redirects_404"] = _r("error" if errors_4xx else "warning", "; ".join(parts) + ".", _urls(errors_4xx + chains))

    broken = [p for p in pages if p.broken_links]
    total_broken = sum(len(p.broken_links or []) for p in broken)
    out["internal_404_links"] = (
        _r("error", f"{total_broken} kapotte interne links op {len(broken)} pagina's.", _urls(broken))
        if broken else _r("ok", "Geen interne links naar 404's gevonden.")
    )

    measured = [p for p in pages if p.cwv_status]
    if not measured:
        out["core_web_vitals"] = _r("unknown", "Core Web Vitals zijn in fase 1 niet gemeten (PageSpeed-key ontbreekt of geen pagina's).")
    else:
        counts = Counter(p.cwv_status for p in measured)
        msg = f"{len(measured)} pagina's gemeten: {counts.get('good', 0)} goed, {counts.get('needs_improvement', 0)} verbeteren, {counts.get('poor', 0)} slecht."
        status = "error" if counts.get("poor") else "warning" if counts.get("needs_improvement") else "ok"
        out["core_web_vitals"] = _r(status, msg, _urls(p for p in measured if p.cwv_status != "good"), dict(counts))

    has_graph = any(p.click_depth is not None for p in pages)
    targets = [p for p in indexable if p.page_type in {"dienst", "product", "categorie"}]
    scope = "dienst-/productpagina's"
    if not targets:
        targets = [p for p in indexable if p.page_type not in {"archief", "juridisch"}]
        scope = "indexeerbare pagina's"
    if not has_graph:
        out["click_depth"] = _r("unknown", "Linkgraaf niet beschikbaar (homepage niet opgehaald).")
    elif not targets:
        out["click_depth"] = _r("nvt", "Geen pagina's om te controleren.")
    else:
        deep = [p for p in targets if p.click_depth is not None and p.click_depth > 3]
        unreachable = [p for p in targets if p.click_depth is None]
        if not deep and not unreachable:
            out["click_depth"] = _r("ok", f"Alle {len(targets)} {scope} zijn binnen 3 klikken bereikbaar.")
        else:
            parts = []
            if deep:
                parts.append(f"{len(deep)} dieper dan 3 klikken")
            if unreachable:
                parts.append(f"{len(unreachable)} niet via interne links bereikbaar vanaf de homepage")
            out["click_depth"] = _r("error" if unreachable else "warning", f"Van de {len(targets)} {scope}: " + "; ".join(parts) + ".",
                                    [f"{p.url} (diepte {p.click_depth if p.click_depth is not None else '∞'})" for p in (deep + unreachable)][:MAX_EVIDENCE_URLS])

    paginated = [p for p in ok_html if is_pagination(p.url)]
    linked_pagination = sorted({link for p in fetched for link in (p.outlinks or []) if is_pagination(link)})
    if not paginated and not linked_pagination:
        out["pagination"] = _r("nvt", "Geen paginatie-URL's gevonden.")
    elif paginated:
        bad_pag = [p for p in paginated if p.indexability_reason == "Canonical naar andere URL"]
        noindex_pag = [p for p in paginated if "noindex" in (p.indexability_reason or "")]
        if bad_pag:
            out["pagination"] = _r("warning", f"{len(bad_pag)} paginatiepagina's hebben een canonical naar een andere URL (meestal pagina 1); gebruik een canonical naar zichzelf.", _urls(bad_pag))
        else:
            msg = f"{len(paginated)} paginatiepagina's gecontroleerd; canonicals verwijzen naar zichzelf."
            if noindex_pag:
                msg += f" {len(noindex_pag)} staan op noindex (bewuste keuze?)."
            out["pagination"] = _r("ok", msg, _urls(paginated))
    else:
        out["pagination"] = _r("info", f"{len(linked_pagination)} paginatie-URL's gelinkt, maar niet gescand (niet in sitemap). Controleer canonical en indexatie handmatig.",
                               linked_pagination[:MAX_EVIDENCE_URLS])

    if not has_graph:
        out["orphan_pages"] = _r("unknown", "Linkgraaf niet beschikbaar.")
    elif discovery_source != "sitemap":
        out["orphan_pages"] = _r("nvt", "Pagina's zijn gevonden door te crawlen, dus elke pagina heeft per definitie een interne link.")
    else:
        orphans = [p for p in indexable if p.in_sitemap and (p.inlinks or 0) == 0
                   and not is_home_page(p) and p.page_type != "archief"]
        out["orphan_pages"] = (
            _r("warning" if len(orphans) < 10 else "error", f"{len(orphans)} pagina's staan in de sitemap maar krijgen geen enkele interne link.", _urls(orphans))
            if orphans else _r("ok", "Geen verweesde pagina's gevonden.")
        )

    thin = [p for p in indexable if (p.word_count or 0) < THIN_CONTENT_WORDS and p.page_type not in EXCLUDED_THIN_TYPES
            and not is_home_page(p)]
    hashes: dict[str, list[LaunchScanPage]] = defaultdict(list)
    for p in indexable:
        h = _sig(p).get("text_hash")
        if h:
            hashes[h].append(p)
    dup_groups = [g for g in hashes.values() if len(g) > 1]
    titles: dict[str, list[LaunchScanPage]] = defaultdict(list)
    for p in indexable:
        if p.title:
            titles[p.title.strip().lower()].append(p)
    dup_titles = [g for g in titles.values() if len(g) > 1]
    if not thin and not dup_groups and not dup_titles:
        out["thin_duplicate"] = _r("ok", "Geen dunne of dubbele pagina's gevonden.")
    else:
        parts = []
        if thin:
            parts.append(f"{len(thin)} dunne pagina's (< {THIN_CONTENT_WORDS} woorden)")
        if dup_groups:
            parts.append(f"{sum(len(g) for g in dup_groups)} pagina's met identieke content in {len(dup_groups)} groepen")
        if dup_titles:
            parts.append(f"{len(dup_titles)} dubbele titles")
        evidence = [f"dun: {p.url} ({p.word_count} w)" for p in thin[:6]]
        evidence += [f"dubbel: {' = '.join(p.url for p in g[:3])}" for g in dup_groups[:5]]
        evidence += [f"zelfde title: {' = '.join(p.url for p in g[:3])}" for g in dup_titles[:4]]
        out["thin_duplicate"] = _r("warning", "; ".join(parts) + ".", evidence)

    # ---------------- AI-bots ----------------
    def from_ai(key: str, check_key: str, fallback: str) -> None:
        check = ai_by_key.get(check_key)
        if not check:
            out[key] = _r("unknown", fallback)
            return
        out[key] = _r(check.get("status") or "unknown", check.get("message") or "", details=check.get("details"))

    from_ai("robots_txt", "robots_txt", "robots.txt niet gecontroleerd in fase 1.")
    from_ai("ai_access_robots", "ai_bots_blocked", "AI-bottoegang niet gecontroleerd in fase 1.")
    if "ai_access_robots" in out:
        bots = (ai_checks or {}).get("bots") or []
        out["ai_access_robots"]["evidence"] = [f"{b['bot']}: {'toegestaan' if b.get('allowed') else 'GEBLOKKEERD'}" for b in bots]
    from_ai("llms_txt", "llms_txt", "llms.txt niet gecontroleerd in fase 1.")
    if out["llms_txt"]["status"] == "warning":
        out["llms_txt"]["message"] += " (Lage prioriteit.)"

    ba = extras.get("bot_access") or {}
    if not ba:
        out["ai_access_cdn"] = _r("unknown", "Bot-toegangstest niet uitgevoerd.")
    elif not ba.get("baseline_ok"):
        out["ai_access_cdn"] = _r("unknown", "Ook een gewone browser kreeg geen 200; de scanner zelf wordt geblokkeerd.", details=ba)
    else:
        blocked = [b for b in ba.get("bots", []) if b.get("blocked")]
        blocked_search = [b for b in blocked if b.get("search_bot")]
        cdn = f" ({ba['cdn']})" if ba.get("cdn") else ""
        evidence = [f"{b['bot']}: {'GEBLOKKEERD' if b.get('blocked') else 'ok'} {list((b.get('statuses') or {}).values())}" for b in ba.get("bots", [])]
        if blocked_search:
            out["ai_access_cdn"] = _r("error", f"CDN/hosting{cdn} blokkeert AI-zoekbots: {', '.join(b['bot'] for b in blocked_search)}.", evidence, ba)
        elif blocked:
            out["ai_access_cdn"] = _r("warning", f"CDN/hosting{cdn} blokkeert trainingsbots: {', '.join(b['bot'] for b in blocked)}. Zoekbots komen erdoor.", evidence, ba)
        else:
            out["ai_access_cdn"] = _r("ok", f"Geen user-agent-blokkade gevonden{cdn}. Let op: IP-blokkades zijn zo niet te zien.", evidence, ba)

    ssr = ai_by_key.get("ssr_content")
    low_text = [p for p in indexable if (p.word_count or 0) < 150 and p.page_type in {"dienst", "product", "blog", "over_ons"}]
    hidden_heavy = [p for p in fetched if (_sig(p).get("hidden_blocks") or 0) >= 8]
    # Accordions/tabs zijn alleen een probleem als de tekst er niet in de HTML staat.
    hidden_thin = [p for p in hidden_heavy if (p.word_count or 0) < THIN_CONTENT_WORDS]
    problems = []
    if ssr and ssr.get("status") != "ok":
        problems.append(ssr.get("message") or "Homepage heeft weinig tekst in de server-HTML.")
    if low_text:
        problems.append(f"{len(low_text)} belangrijke pagina's hebben < 150 woorden in de ruwe HTML.")
    if hidden_thin:
        problems.append(f"{len(hidden_thin)} pagina's hebben veel klik-om-te-openen-blokken én weinig tekst in de HTML; content wordt mogelijk pas na een klik geladen.")
    if problems:
        out["ssr_content"] = _r("warning", " ".join(problems), _urls(low_text + hidden_thin))
    elif ssr or fetched:
        msg = (ssr or {}).get("message") or "Content staat in de server-HTML."
        if hidden_heavy:
            msg += f" {len(hidden_heavy)} pagina's gebruiken accordions/tabs; de tekst staat wel in de HTML."
        out["ssr_content"] = _r("ok", msg, _urls(hidden_heavy))
    else:
        out["ssr_content"] = _r("unknown", "Niet gecontroleerd.")

    out["bing_webmaster"] = _r("info", "Controleer in Bing Webmaster Tools of de site geverifieerd is en de sitemap is ingediend (of importeer vanuit Google Search Console).")
    plugins = sorted({pl for p in fetched for pl in (_sig(p).get("plugins") or [])})
    hints = [pl for pl in plugins if pl in {"rank_math", "yoast", "indexnow"}]
    if "indexnow" in plugins:
        out["indexnow"] = _r("info", "IndexNow-sporen gevonden in de HTML; controleer of het actief is.", plugins)
    elif hints:
        out["indexnow"] = _r("info", f"Plugin met IndexNow-ondersteuning gevonden ({', '.join(hints)}); controleer of IndexNow aan staat (Rank Math: standaard, Yoast: Premium/Cloudflare).", plugins)
    else:
        out["indexnow"] = _r("info", "IndexNow is van buitenaf niet te detecteren; controleer handmatig (plugin, CDN of Bing Webmaster Tools).", plugins)

    # Ontbrekende keys afvangen
    for key in ITEMS:
        out.setdefault(key, _r("unknown", "Niet gecontroleerd."))
    return out


def _walk_nodes(value: Any, depth: int = 0) -> Iterable[dict[str, Any]]:
    if depth > 6:
        return
    if isinstance(value, list):
        for v in value:
            yield from _walk_nodes(v, depth + 1)
    elif isinstance(value, dict):
        yield value
        for v in value.values():
            if isinstance(v, (dict, list)):
                yield from _walk_nodes(v, depth + 1)


def _expired_job(p: LaunchScanPage, now: datetime) -> bool:
    for node in _walk_nodes(p.jsonld or []):
        if "JobPosting" in types_of(node) and isinstance(node.get("validThrough"), str):
            try:
                valid = datetime.fromisoformat(node["validThrough"].replace("Z", "+00:00"))
            except ValueError:
                continue
            if valid.tzinfo is None:
                valid = valid.replace(tzinfo=timezone.utc)
            if valid < now:
                return True
    return False


def _first_link(pages: list[LaunchScanPage], kind: str) -> str | None:
    for p in pages:
        link = (_sig(p).get("links") or {}).get(kind)
        if link:
            return link
    return None


def _site_nap(pages: list[LaunchScanPage], home: LaunchScanPage | None) -> dict[str, list[str]]:
    """Verzamel wat de site zelf aan NAP-/bedrijfsgegevens toont (home + contact eerst)."""
    priority = sorted(
        pages,
        key=lambda p: (p is not home, p.page_type not in {"contact", "over_ons"}, len(p.path)),
    )
    found: dict[str, list[str]] = {"telefoon": [], "e-mail": [], "adres": [], "kvk": [], "btw": [], "sources": []}
    mapping = {"phones": "telefoon", "emails": "e-mail", "addresses": "adres", "kvk": "kvk", "btw": "btw"}
    for p in priority[:60]:
        sig = _sig(p)
        hit = False
        for src, dest in mapping.items():
            for value in sig.get(src) or []:
                if value not in found[dest] and len(found[dest]) < 4:
                    found[dest].append(value)
                    hit = True
        if hit and len(found["sources"]) < 5:
            found["sources"].append(p.url)
    return found


def _found_signal(site_nap: dict[str, list[str]], key: str, label: str, fetched: list[LaunchScanPage], *, schema_hint: bool) -> dict[str, Any]:
    values = site_nap.get(key) or []
    if values:
        return _r("ok", f"{label} zichtbaar op de site: {', '.join(values)}.", values + (site_nap.get("sources") or [])[:3])
    if not fetched:
        return _r("unknown", "Geen pagina's opgehaald.")
    if schema_hint:
        return _r("warning", f"{label} staat wel in de schema-markup, maar is niet zichtbaar in de tekst van de site.")
    return _r("error" if key == "kvk" else "warning", f"Geen {label} gevonden in de tekst van de site.")


def page_type_counts(pages: list[LaunchScanPage]) -> dict[str, int]:
    counts = Counter((p.page_type or "overig") for p in pages if _is_indexable_html(p))
    return {k: counts.get(k, 0) for k in PAGE_TYPES if counts.get(k)}
