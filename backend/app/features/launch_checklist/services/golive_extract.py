"""Livegang (fase 5): extra signalen per pagina uit de HTML van de inventaris.

Wordt via de `page_hook` van `run_inventory` aangeroepen, dus zonder tweede
verzoek. Bovenop `html_extract._SeoParser` verzamelen we:
- mixed content op https-pagina's (actief: script, stylesheet, iframe, formulier;
  passief: img, video, audio, source),
- interne links, canonicals en hreflang via http:// of de andere hostvariant,
- verwijzingen naar een testomgeving (getypeerd, plus één regex-ronde over de
  ruwe HTML voor hosts in inline CSS/JS),
- viewport-meta, formulieren (zonder zoek- en winkelwagenformulieren),
  tracking-ID's en cookiebanners (in de ruwe HTML: consent-plugins zetten `src`
  vaak om naar `data-src`).

Per pagina houden we hooguit MAX_PER_PAGE items per lijst, met het echte totaal erbij.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

from celery.exceptions import SoftTimeLimitExceeded

from app.features.launch_checklist.services.discovery import clean_url, root_domain_of
from app.features.launch_checklist.services.html_extract import _SeoParser

MAX_PER_PAGE = 20
MAX_FORMS_PER_PAGE = 10
MAX_ICONS = 2
MAX_RAW_HTML = 2_000_000

# --- testomgeving herkennen -------------------------------------------------------

# Subdomeinlabels die (bijna) altijd een testomgeving zijn: fout.
STRONG_TEST_LABELS = frozenset({
    "staging", "stage", "stg", "test", "dev", "acc", "acceptatie", "uat", "otap", "sandbox", "temp",
})
# Labels die ook een echte publieke site kunnen zijn: waarschuwing.
AMBIGUOUS_TEST_LABELS = frozenset({"new", "nieuw", "old", "oud", "demo", "beta", "preview"})
# Tijdelijke platformdomeinen (alleen subdomeinen ervan; het platform zelf niet).
PLATFORM_DOMAINS = (
    "wpengine.com", "kinsta.cloud", "myshopify.com", "webflow.io", "vercel.app", "netlify.app",
    "pages.dev", "cloudwaysapps.com", "sg-host.com", "wpcomstaging.com", "pantheonsite.io", "transurl.nl",
)
# Hostnamen die nooit publiek zijn.
LOCAL_SUFFIXES = (".local", ".test", ".localhost", ".invalid", ".example")
# Shopify: een live winkel laadt assets van cdn.shopify.com en zet `Shopify.shop =
# "<winkel>.myshopify.com"` in elke pagina; de checkout kan op myshopify.com staan.
# Daarom tellen myshopify.com-verwijzingen alleen als canonical, og:url, hreflang of
# gewone link buiten de winkelwagen-, checkout- en accountpaden.
SHOPIFY_DOMAIN = "myshopify.com"
SHOPIFY_ALLOWED_PATHS = ("/cart", "/checkout", "/checkouts", "/account", "/apps/", "/tools/", "/services/")
# Verwijzingstypes waarvoor een myshopify.com-host meetelt.
SHOPIFY_COUNTED_TYPES = frozenset({"canonical", "og_url", "hreflang", "link"})

_LABEL_TOKEN_RE = re.compile(r"[a-z]+")


@dataclass(frozen=True)
class GoLiveSite:
    """De gescande site: host uit de klant-URL, rootdomein en de www/apex-variant."""
    host: str
    root: str
    hosts: frozenset[str]
    test_domains: tuple[str, ...] = ()

    @property
    def has_host_pair(self) -> bool:
        return len(self.hosts) == 2

    @classmethod
    def from_base_url(cls, base_url: str, test_domains: list[str] | tuple[str, ...] = ()) -> "GoLiveSite":
        host = (urlparse(base_url).hostname or "").lower().strip(".")
        root = root_domain_of(base_url) or host
        apex = host[4:] if host.startswith("www.") else host
        hosts = frozenset({apex, f"www.{apex}"}) if apex == root else frozenset({host})
        return cls(host=host, root=root, hosts=hosts, test_domains=tuple(test_domains))


def _split_netloc(netloc: str) -> tuple[str, int | None]:
    parsed = urlparse(f"//{netloc}")
    try:
        port = parsed.port
    except ValueError:
        port = None
    return (parsed.hostname or "").lower().strip("."), port


def classify_host(netloc: str, site: GoLiveSite) -> tuple[str, str] | None:
    """(niveau 'error'/'warning', reden) als de host een testomgeving is, anders None.

    Nooit "elke vreemde host": alleen testlabels op het eigen rootdomein, tijdelijke
    platformdomeinen, lokale adressen en de testdomeinen van het bureau.
    """
    host, port = _split_netloc(netloc)
    if not host:
        return None
    if host == "localhost" or host.endswith(LOCAL_SUFFIXES):
        return "error", f"lokaal adres ({host})"
    try:
        ipaddress.ip_address(host)
        return "error", f"IP-adres ({host})"
    except ValueError:
        pass
    if port is not None and port not in (80, 443):
        return "error", f"host met poort ({host}:{port})"
    for domain in site.test_domains:
        if host == domain or host.endswith(f".{domain}"):
            return "error", f"testdomein van het bureau ({domain})"
    for domain in PLATFORM_DOMAINS:
        if host.endswith(f".{domain}"):
            return "error", f"tijdelijk platformdomein ({domain})"
    if site.root and host.endswith(f".{site.root}") and host not in site.hosts:
        labels = host[: -len(site.root) - 1].split(".")
        tokens = {t for label in labels for t in _LABEL_TOKEN_RE.findall(label)}
        strong = sorted(tokens & STRONG_TEST_LABELS)
        if strong:
            return "error", f"testsubdomein ({strong[0]})"
        ambiguous = sorted(tokens & AMBIGUOUS_TEST_LABELS)
        if ambiguous:
            return "warning", f"mogelijk testsubdomein ({ambiguous[0]})"
    return None


def _is_shopify_allowed(url: str, ref_type: str) -> bool:
    """True als een myshopify.com-verwijzing bij een live winkel hoort (niet meetellen)."""
    if ref_type not in SHOPIFY_COUNTED_TYPES:
        return True
    path = urlparse(url).path.lower()
    return ref_type == "link" and path.startswith(SHOPIFY_ALLOWED_PATHS)


# --- tracking en cookiebanners ----------------------------------------------------

GTM_RE = re.compile(r"(?<![A-Za-z0-9])GTM-[A-Z0-9]{4,10}(?![A-Za-z0-9-])")
# GA4 alleen in een gtag/js-URL of een gtag('config', ...)-aanroep, zodat losse strings niet matchen.
GA4_RE = re.compile(
    r"gtag/js\?id=(G-[A-Z0-9]{8,12})(?![A-Za-z0-9])"
    r"|gtag\(\s*['\"]config['\"]\s*,\s*['\"](G-[A-Z0-9]{8,12})['\"]"
)
UA_RE = re.compile(r"(?<![A-Za-z0-9])UA-\d{4,10}-\d{1,4}(?![0-9])")
OTHER_TRACKERS: dict[str, re.Pattern[str]] = {
    "Matomo": re.compile(r"matomo\.js|piwik\.js|_paq\.push", re.I),
    "Plausible": re.compile(r"plausible\.io/js", re.I),
    "Meta-pixel": re.compile(r"connect\.facebook\.net/[^\"']*fbevents\.js|fbq\(\s*['\"]init", re.I),
    "Microsoft Clarity": re.compile(r"clarity\.ms/tag", re.I),
    "Hotjar": re.compile(r"static\.hotjar\.com|hotjar\.com/c/hotjar-", re.I),
}
CONSENT_SIGNATURES: dict[str, re.Pattern[str]] = {
    "Cookiebot": re.compile(r"consent\.cookiebot\.(?:com|eu)|cookiebot\.com/uc\.js|id=\"cookiebot\"", re.I),
    "CookieYes": re.compile(r"cookieyes\.com|cookie-law-info|cky-consent", re.I),
    "Complianz": re.compile(r"cmplz", re.I),
    "OneTrust": re.compile(r"cookielaw\.org|onetrust-banner", re.I),
    "Borlabs Cookie": re.compile(r"borlabs-cookie|borlabscookie", re.I),
    "Usercentrics": re.compile(r"usercentrics", re.I),
    "iubenda": re.compile(r"iubenda", re.I),
    "Cookie Notice": re.compile(r"id=['\"]cookie-notice['\"]|cookie-notice-front|cn-notice-text", re.I),
    "Real Cookie Banner": re.compile(r"real-cookie-banner", re.I),
    "Moove GDPR": re.compile(r"moove[_-]gdpr", re.I),
    "CookieFirst": re.compile(r"cookiefirst", re.I),
    "Didomi": re.compile(r"didomi", re.I),
    "Axeptio": re.compile(r"axeptio", re.I),
    "Klaro": re.compile(r"klaro(?:\.min)?\.js|klaroconfig|klaro-config", re.I),
    "tarteaucitron": re.compile(r"tarteaucitron", re.I),
    "CookieScript": re.compile(r"cookie-script\.com", re.I),
    "HubSpot-cookiebanner": re.compile(r"hs-banner", re.I),
    "Shopify-cookiebanner": re.compile(r"shopify-pc__banner|consent-tracking-api", re.I),
    "Google Consent Mode (standaard)": re.compile(r"gtag\(\s*['\"]consent['\"]\s*,\s*['\"]default['\"]", re.I),
}


def _placeholder(value: str) -> bool:
    return set(value.split("-", 1)[1]) <= {"X"}


def find_tracking(raw_html: str) -> dict[str, list[str]]:
    """Tracking-ID's in de ruwe HTML: gtm, ga4, ua (verouderd) en overige tools."""
    gtm = sorted({m for m in GTM_RE.findall(raw_html) if not _placeholder(m)})
    ga4 = sorted({a or b for a, b in GA4_RE.findall(raw_html) if not _placeholder(a or b)})
    ua = sorted(set(UA_RE.findall(raw_html)))
    other = [name for name, pattern in OTHER_TRACKERS.items() if pattern.search(raw_html)]
    return {"gtm": gtm, "ga4": ga4, "ua": ua, "other": other}


def find_consent(raw_html: str) -> list[str]:
    return [name for name, pattern in CONSENT_SIGNATURES.items() if pattern.search(raw_html)]


# --- parser -----------------------------------------------------------------------

_ACTIVE_TAGS = {"script": "src", "iframe": "src", "object": "data", "embed": "src"}
_PASSIVE_TAGS = {"img", "video", "audio", "source", "track"}
_SEARCH_NAMES = {"s", "q", "search", "zoek", "zoeken", "query", "search_query", "keyword"}
_SEARCH_HINT_RE = re.compile(r"search|zoek", re.I)
_CART_HINT_RE = re.compile(r"/cart|add-to-cart|add_to_cart|winkelwagen|product-form", re.I)
# Hosts in inline CSS/JS: alleen met schema (ook JSON-escaped "https:\/\/"), zodat
# JavaScript-commentaar als "//foo.test(" niet als host telt.
_HOST_IN_TEXT_RE = re.compile(
    r"https?:(?:\\?/){2}((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z][a-z0-9-]*[a-z0-9]|localhost|\d{1,3}(?:\.\d{1,3}){3})"
    r"(?::(\d{2,5}))?",
    re.I,
)


def _srcset_urls(value: str) -> list[str]:
    return [part.strip().split()[0] for part in value.split(",") if part.strip()]


class _GoLiveParser(_SeoParser):
    def __init__(self) -> None:
        super().__init__()
        # (tag, soort, url-zoals-in-html): soort 'active' of 'passive' (voor mixed content)
        self.resources: list[tuple[str, str, str]] = []
        self.link_tags: list[tuple[list[str], str]] = []
        self.form_actions: list[str] = []
        self.forms: list[dict[str, Any]] = []
        self._form: dict[str, Any] | None = None
        self.viewport: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        tag = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta" and a.get("name", "").lower() == "viewport" and self.viewport is None:
            self.viewport = a.get("content", "").strip()
        elif tag in _ACTIVE_TAGS:
            src = a.get(_ACTIVE_TAGS[tag], "").strip()
            if src:
                self.resources.append((tag, "active", src))
        elif tag in _PASSIVE_TAGS:
            for attr in ("src", "poster"):
                if a.get(attr, "").strip():
                    self.resources.append((tag, "passive", a[attr].strip()))
            for url in _srcset_urls(a.get("srcset", "")):
                self.resources.append((tag, "passive", url))
        elif tag == "link":
            rel = a.get("rel", "").lower().split()
            href = a.get("href", "").strip()
            if href:
                self.link_tags.append((rel, href))
                if "stylesheet" in rel:
                    self.resources.append((tag, "active", href))
                elif "icon" in rel:
                    self.resources.append((tag, "passive", href))
        elif tag == "form":
            action = a.get("action", "").strip()
            hints = " ".join((a.get("role", ""), a.get("class", ""), a.get("id", ""), action))
            self._form = {
                "action": action,
                "method": (a.get("method") or "get").lower(),
                "search": a.get("role", "").lower() == "search" or bool(_SEARCH_HINT_RE.search(hints)),
                "cart": bool(_CART_HINT_RE.search(hints)),
                "fields": 0,
            }
            self.forms.append(self._form)
            if action:
                self.form_actions.append(action)
        elif tag in {"input", "textarea", "select"} and self._form is not None:
            kind = a.get("type", "text").lower()
            if kind == "search" or (a.get("name", "").lower() in _SEARCH_NAMES and kind in {"text", "search"}):
                self._form["search"] = True
            if kind not in {"hidden", "submit", "button", "image", "reset"}:
                self._form["fields"] += 1

    def handle_endtag(self, tag: str) -> None:
        super().handle_endtag(tag)
        if tag.lower() == "form":
            self._form = None


@dataclass
class _Collector:
    limit: int = MAX_PER_PAGE
    items: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    _seen: set[tuple[str, ...]] = field(default_factory=set)

    def add(self, key: tuple[str, ...], item: dict[str, Any]) -> None:
        if key in self._seen:
            return
        self._seen.add(key)
        self.total += 1
        if len(self.items) < self.limit:
            self.items.append(item)


def extract_golive(html: str, page_url: str, site: GoLiveSite) -> dict[str, Any]:
    """Signalen van één pagina (JSON-baar, gecapt)."""
    parser = _GoLiveParser()
    try:
        parser.feed(html)
        parser.close()
    except SoftTimeLimitExceeded:  # time-out van de taak, geen kapotte HTML
        raise
    except Exception:  # kapotte HTML: neem wat we hebben
        pass
    page = parser.result()
    raw = html[:MAX_RAW_HTML]
    page_host = (urlparse(page_url).hostname or "").lower()
    is_https = page_url.lower().startswith("https://")

    # Mixed content: alleen absolute http://-URL's op een https-pagina.
    mixed_active, mixed_passive = _Collector(), _Collector()
    if is_https:
        for tag, kind, raw_url in parser.resources:
            if not raw_url.lower().startswith("http://"):
                continue
            absolute = clean_url(raw_url, page_url)
            if not absolute:
                continue
            (mixed_active if kind == "active" else mixed_passive).add((absolute,), {"tag": tag, "url": absolute})
        for action in parser.form_actions:
            if action.lower().startswith("http://"):
                absolute = clean_url(action, page_url)
                if absolute:
                    mixed_active.add((absolute,), {"tag": "form", "url": absolute})

    # Interne links, canonical en hreflang via http of de andere hostvariant.
    insecure = _Collector()
    candidates: list[tuple[str, str]] = [("link", href) for href in page.links]
    if page.canonical:
        candidates.append(("canonical", page.canonical))
    candidates.extend(("hreflang", h.get("href", "")) for h in page.hreflang)
    for kind, href in candidates:
        absolute = clean_url(href, page_url)
        if not absolute:
            continue
        parsed = urlparse(absolute)
        host = (parsed.hostname or "").lower()
        if host not in site.hosts:
            continue
        problems = []
        if parsed.scheme == "http":
            problems.append("http")
        if page_host in site.hosts and host != page_host:
            problems.append("host")
        if problems:
            insecure.add((kind, absolute), {"kind": kind, "url": absolute, "issue": "+".join(problems)})

    # Verwijzingen naar een testomgeving.
    refs = _Collector()
    typed_hosts: set[str] = set()

    def add_ref(ref_type: str, raw_url: str) -> None:
        absolute = clean_url(raw_url, page_url)
        if not absolute:
            return
        netloc = urlparse(absolute).netloc
        host, _ = _split_netloc(netloc)
        if host in site.hosts or host == site.host:
            return  # de site zelf (ook als die op een testadres staat; dat meldt de check apart)
        verdict = classify_host(netloc, site)
        if verdict is None:
            return
        if host.endswith(f".{SHOPIFY_DOMAIN}") and _is_shopify_allowed(absolute, ref_type):
            return
        typed_hosts.add(host)
        refs.add((ref_type, absolute), {
            "type": ref_type, "url": absolute, "host": host, "level": verdict[0], "reason": verdict[1],
        })

    if page.canonical:
        add_ref("canonical", page.canonical)
    if page.open_graph.get("og:url"):
        add_ref("og_url", page.open_graph["og:url"])
    for h in page.hreflang:
        add_ref("hreflang", h.get("href", ""))
    for href in page.links:
        add_ref("link", href)
    for rel, href in parser.link_tags:
        if "canonical" in rel or ("alternate" in rel and any(h.get("href") == href for h in page.hreflang)):
            continue
        add_ref("asset", href)
    for _tag, _kind, raw_url in parser.resources:
        add_ref("asset", raw_url)
    for action in parser.form_actions:
        add_ref("form", action)
    for match in _HOST_IN_TEXT_RE.finditer(raw):
        host = match.group(1).lower().rstrip(".")
        if host in typed_hosts or host in site.hosts or host == site.host:
            continue
        if host.endswith(f".{SHOPIFY_DOMAIN}"):
            continue  # Shopify zet de winkelhost in inline JS van elke live winkel
        netloc = f"{host}:{match.group(2)}" if match.group(2) else host
        verdict = classify_host(netloc, site)
        if verdict is None:
            continue
        typed_hosts.add(host)
        url = match.group(0).replace("\\/", "/")
        refs.add(("inline", host), {
            "type": "inline", "url": url, "host": host, "level": verdict[0], "reason": verdict[1],
        })

    forms = [
        {"action": clean_url(f["action"], page_url) if f["action"] else page_url, "method": f["method"]}
        for f in parser.forms
        if not f["search"] and not f["cart"] and f["fields"] > 0
    ]
    icons = []
    for rel, href in parser.link_tags:
        if "icon" in rel:
            absolute = clean_url(href, page_url)
            if absolute and absolute not in icons:
                icons.append(absolute)

    viewport = parser.viewport
    return {
        "https": is_https,
        "mixed_active": mixed_active.items,
        "mixed_active_total": mixed_active.total,
        "mixed_passive": mixed_passive.items,
        "mixed_passive_total": mixed_passive.total,
        "insecure_urls": insecure.items,
        "insecure_urls_total": insecure.total,
        "test_refs": refs.items,
        "test_refs_total": refs.total,
        "viewport": viewport,
        "viewport_ok": bool(viewport) and "width=device-width" in re.sub(r"\s+", "", viewport.lower()),
        "forms": forms[:MAX_FORMS_PER_PAGE],
        "forms_total": len(forms),
        "tracking": find_tracking(raw),
        "consent": find_consent(raw),
        "icons": icons[:MAX_ICONS],
    }


def make_page_hook(site: GoLiveSite) -> Callable[[Any, str, Any], None]:
    """`page_hook` voor `run_inventory`: zet de signalen op `rec.extra['golive']`."""

    def hook(rec: Any, html: str, _response: Any) -> None:
        try:
            rec.extra["golive"] = extract_golive(html, rec.final_url or rec.url, site)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # een fout in de extractie mag de inventaris niet stoppen
            rec.extra["golive"] = {"error": str(exc)[:200]}

    return hook
