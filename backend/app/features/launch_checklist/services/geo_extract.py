"""Fase 2: rijkere HTML-extractie voor de GEO/SEO-checklist.

Bovenop `html_extract._SeoParser` verzamelen we:
- volledige JSON-LD-nodes (fase 1 bewaart alleen de types),
- links met ankertekst (interne linkgraaf, over ons/contact/voorwaarden/privacy/sitemap),
- social-/bedrijfsprofielen waar de site naar linkt,
- NAP- en vertrouwenssignalen in de zichtbare tekst (telefoon, adres, KvK, BTW),
- hints voor FAQ, reviews, auteurs, verborgen content en gebruikte plugins.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.features.launch_checklist.services.discovery import clean_url, is_internal, url_key
from app.features.launch_checklist.services.html_extract import _SeoParser, _clean

MAX_TEXT_CHARS = 200_000
MAX_JSONLD_CHARS = 30_000
MAX_OUTLINKS = 400
_SKIP_LINK_PREFIXES = ("#", "mailto:", "tel:", "javascript:", "data:", "sms:", "whatsapp:")

# --- regexen (NL-gericht) ---------------------------------------------------
_PHONE_RE = re.compile(r"(?<![\d+])(?:\+31|0031|0)[\s.\-]?(?:\(0\)[\s.\-]?)?[1-9](?:[\s.\-]?\d){8}(?!\d)")
_POSTCODE_RE = re.compile(r"\b[1-9]\d{3}\s?(?!SA|SD|SS)[A-Z]{2}\b")
_ADDRESS_RE = re.compile(
    r"([A-Z][A-Za-zÀ-ÿ'.\-]+(?:\s[A-Za-zÀ-ÿ'.\-]+){0,3}\s\d{1,5}(?:\s?[a-zA-Z]{1,2}\b|-\d+)?)"
    r"[,\s]+([1-9]\d{3}\s?[A-Z]{2})\s+((?:(?:Den|De|Het|'s|Sint|Nieuw|Oud|Groot|Klein)\s)?[A-Z][A-Za-zÀ-ÿ'\-]+)"
)
_KVK_RE = re.compile(
    r"(?:kvk|k\.v\.k\.?|kamer van koophandel|coc|handelsregister)[^0-9]{0,30}(\d{8})(?!\d)",
    re.IGNORECASE,
)
_BTW_RE = re.compile(r"\bNL\s?\d{9}\s?B\s?\d{2}\b", re.IGNORECASE)
_FAQ_TEXT_RE = re.compile(r"veelgestelde vragen|veel gestelde vragen|\bfaq\b|frequently asked", re.IGNORECASE)

# Ankertekst/href → type link
_LINK_KINDS: dict[str, tuple[str, ...]] = {
    "about": ("over ons", "over-ons", "about", "wie zijn wij", "wie-zijn-wij", "ons team", "ons-team", "over mij", "over-mij"),
    "contact": ("contact",),
    "terms": ("algemene voorwaarden", "algemene-voorwaarden", "voorwaarden", "terms", "leveringsvoorwaarden"),
    "privacy": ("privacy",),
    "sitemap": ("sitemap",),
}

_PLUGIN_MARKERS: dict[str, tuple[str, ...]] = {
    "wordpress": ("wp-content/", "wp-includes/"),
    "woocommerce": ("wp-content/plugins/woocommerce", "woocommerce-page", "woocommerce-js", "wc-block-"),
    "shopify": ("cdn.shopify.com", "shopify.theme", "myshopify.com"),
    "yoast": ("yoast seo", "yoast-schema-graph"),
    "rank_math": ("rank math",),
    "elementor": ("elementor-",),
    "indexnow": ("indexnow-key", "indexnow.js"),
    "lightspeed": ("webshopapp.com", "cdn.webshopapp"),
    "magento": ("mage/cookies", "/static/frontend/", "magento_theme"),
}

_HIDDEN_CLASS_RE = re.compile(r"\b(accordion|collapse|tab-pane|e-n-accordion|elementor-tab-content|toggle-content|read-more|readmore)\b", re.IGNORECASE)
_AUTHOR_CLASS_RE = re.compile(r"\b(author|auteur|byline|team-member|teamlid|team__member|bio)\b", re.IGNORECASE)
_RATING_CLASS_RE = re.compile(r"\b(star-rating|stars|rating|woocommerce-product-rating|trustpilot-widget|kiyoh-widget)\b", re.IGNORECASE)


def platform_of(url: str) -> str | None:
    """Herken social/bedrijfsprofielen op basis van de URL."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.netloc or "").lower().removeprefix("www.").removeprefix("m.")
    path = (parsed.path or "").lower()
    if not host:
        return None
    if host.endswith("linkedin.com"):
        return "linkedin"
    if host.endswith("facebook.com") or host == "fb.com" or host == "fb.me":
        return "facebook"
    if host.endswith("instagram.com"):
        return "instagram"
    if host.endswith("tiktok.com"):
        return "tiktok"
    if host.endswith("youtube.com") or host == "youtu.be":
        return "youtube"
    if (
        host in {"g.page", "maps.app.goo.gl", "business.google.com", "g.co"}
        or host.startswith("maps.google.")
        or (host.startswith("google.") and path.startswith("/maps"))
        or (host == "goo.gl" and path.startswith("/maps"))
        or (host.startswith("share.google"))
    ):
        return "gmb"
    if host.endswith("bing.com") and (path.startswith("/maps") or path.startswith("/local") or "places" in path):
        return "bing_places"
    if host.endswith("bingplaces.com"):
        return "bing_places"
    if host in {"x.com", "twitter.com"} or host.endswith("pinterest.com") or host.endswith("pinterest.nl") \
            or host.endswith("kvk.nl") or host.endswith("trustpilot.com") or host.endswith("kiyoh.com") \
            or host.endswith("threads.net") or host.endswith("vimeo.com") or host.endswith("github.com") \
            or host.endswith("wikipedia.org") or host.endswith("wikidata.org") or host.endswith("werkspot.nl") \
            or host.endswith("telefoonboek.nl") or host.endswith("goudengids.nl") or host.endswith("yelp.com"):
        return "other"
    return None


def flatten_jsonld(data: Any) -> list[dict[str, Any]]:
    """Top-level nodes (incl. @graph-items) uit een JSON-LD-blok."""
    out: list[dict[str, Any]] = []
    if isinstance(data, list):
        for item in data:
            out.extend(flatten_jsonld(item))
    elif isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            out.extend(flatten_jsonld(graph))
        if data.get("@type"):
            out.append({k: v for k, v in data.items() if k != "@graph"})
    return out


def types_of(node: Any) -> list[str]:
    raw = node.get("@type") if isinstance(node, dict) else None
    if isinstance(raw, str):
        return [raw.split("/")[-1]]
    if isinstance(raw, list):
        return [str(t).split("/")[-1] for t in raw if isinstance(t, str)]
    return []


def all_types(nodes: Any) -> set[str]:
    """Alle @types, ook geneste (bijv. Article.author → Person)."""
    found: set[str] = set()

    def walk(value: Any, depth: int) -> None:
        if depth > 8:
            return
        if isinstance(value, list):
            for v in value:
                walk(v, depth + 1)
        elif isinstance(value, dict):
            found.update(types_of(value))
            for v in value.values():
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)

    walk(nodes, 0)
    return found


def _trim(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return None
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in {"articleBody", "text", "reviewBody", "hasPart"}:
                continue
            out[k] = _trim(v, depth + 1)
        return out
    if isinstance(value, list):
        return [_trim(v, depth + 1) for v in value[:25]]
    if isinstance(value, str) and len(value) > 300:
        return value[:300] + "…"
    return value


@dataclass
class GeoExtract:
    jsonld: list[dict[str, Any]] = field(default_factory=list)
    outlinks: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)


class _GeoParser(_SeoParser):
    def __init__(self) -> None:
        super().__init__()
        self.jsonld_nodes: list[dict[str, Any]] = []
        self.anchors: list[tuple[str, str]] = []
        self._anchor_href: str | None = None
        self._anchor_parts: list[str] = []
        self.text_parts: list[str] = []
        self._text_len = 0
        self.body_classes = ""
        self.details_count = 0
        self.question_headings = 0
        self._h3: bool = False
        self._h3_parts: list[str] = []
        self.hidden_blocks = 0
        self.author_markers = 0
        self.author_images = 0
        self.rating_markers = 0
        self.rel_author: list[str] = []
        self.comments: list[str] = []
        self._in_author_block = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        tag = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        cls = a.get("class", "")

        if tag == "body":
            self.body_classes = cls[:2000]
        elif tag == "a":
            href = a.get("href", "").strip()
            if href:
                self._anchor_href = href
                self._anchor_parts = [a.get("aria-label", ""), a.get("title", "")]
            if "author" in a.get("rel", "").lower().split() and href:
                self.rel_author.append(href)
        elif tag == "link" and "author" in a.get("rel", "").lower().split() and a.get("href"):
            self.rel_author.append(a["href"])
        elif tag == "details":
            self.details_count += 1
        elif tag in {"h2", "h3", "h4", "button", "summary", "dt"}:
            self._h3 = True
            self._h3_parts = []
        elif tag == "img" and self._in_author_block:
            self.author_images += 1

        if cls:
            if _HIDDEN_CLASS_RE.search(cls):
                self.hidden_blocks += 1
            if _AUTHOR_CLASS_RE.search(cls):
                self.author_markers += 1
                self._in_author_block += 1
            if _RATING_CLASS_RE.search(cls):
                self.rating_markers += 1

    def handle_endtag(self, tag: str) -> None:
        super().handle_endtag(tag)
        tag = tag.lower()
        if tag == "a" and self._anchor_href is not None:
            self.anchors.append((self._anchor_href, _clean(" ".join(self._anchor_parts))[:200]))
            self._anchor_href = None
        elif tag in {"h2", "h3", "h4", "button", "summary", "dt"} and self._h3:
            text = _clean("".join(self._h3_parts))
            if text.endswith("?") and len(text) < 200:
                self.question_headings += 1
            self._h3 = False
        elif tag in {"div", "section", "aside", "article"} and self._in_author_block:
            # Ruwe benadering: een auteurblok sluit bij de eerstvolgende container-sluiting.
            self._in_author_block = max(0, self._in_author_block - 1)

    def handle_data(self, data: str) -> None:
        super().handle_data(data)
        if self._anchor_href is not None:
            self._anchor_parts.append(data)
        if self._h3:
            self._h3_parts.append(data)
        if self._skip_depth == 0 and self._text_len < MAX_TEXT_CHARS:
            self.text_parts.append(data)
            self._text_len += len(data)

    def handle_comment(self, data: str) -> None:
        if len(self.comments) < 50:
            self.comments.append(data[:300])

    def _parse_jsonld(self, raw: str) -> None:
        super()._parse_jsonld(raw)
        try:
            data = json.loads(raw.strip())
        except (ValueError, TypeError):
            return
        self.jsonld_nodes.extend(flatten_jsonld(data))


def _dedupe(values: list[str], limit: int = 10) -> list[str]:
    out: list[str] = []
    for v in values:
        v = _clean(v)
        if v and v not in out:
            out.append(v)
        if len(out) >= limit:
            break
    return out


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("0031"):
        digits = "+31" + digits[4:]
    elif digits.startswith("0"):
        digits = "+31" + digits[1:]
    return digits


def extract_geo(html: str, page_url: str, root_domain: str) -> GeoExtract:
    parser = _GeoParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # kapotte HTML: neem wat we hebben
        pass
    parser.result()

    text = _clean(" ".join(parser.text_parts))
    lower_html = html[:2_000_000].lower()

    outlinks: list[str] = []
    seen: set[str] = set()
    link_kinds: dict[str, str] = {}
    profiles: dict[str, list[str]] = {}
    phones_from_links: list[str] = []
    emails: list[str] = []

    for href, anchor_text in parser.anchors:
        low = href.lower()
        if low.startswith("tel:"):
            phones_from_links.append(href[4:])
            continue
        if low.startswith("mailto:"):
            emails.append(href[7:].split("?")[0])
            continue
        if low.startswith(_SKIP_LINK_PREFIXES):
            continue
        absolute = clean_url(href, page_url)
        if not absolute:
            continue
        if is_internal(absolute, root_domain):
            key = url_key(absolute)
            if key not in seen and len(outlinks) < MAX_OUTLINKS:
                seen.add(key)
                outlinks.append(absolute)
            haystack = f"{anchor_text.lower()} {urlparse(absolute).path.lower()}"
            for kind, needles in _LINK_KINDS.items():
                if kind not in link_kinds and any(n in haystack for n in needles):
                    link_kinds[kind] = absolute
        else:
            platform = platform_of(absolute)
            if platform:
                bucket = profiles.setdefault(platform, [])
                if absolute not in bucket and len(bucket) < 5:
                    bucket.append(absolute)

    phones = _dedupe([_normalize_phone(p) for p in phones_from_links + _PHONE_RE.findall(text)])
    addresses = _dedupe([" ".join(m) for m in _ADDRESS_RE.findall(text)], limit=5)
    kvk = _dedupe(_KVK_RE.findall(text), limit=5)
    btw = _dedupe([re.sub(r"\s", "", m).upper() for m in _BTW_RE.findall(text)], limit=5)

    plugins = sorted(
        name for name, markers in _PLUGIN_MARKERS.items()
        if any(m in lower_html for m in markers)
        or any(any(m in c.lower() for m in markers) for c in parser.comments)
    )

    jsonld_raw = [_trim(n) for n in parser.jsonld_nodes]
    encoded = json.dumps(jsonld_raw, ensure_ascii=False, default=str)
    if len(encoded) > MAX_JSONLD_CHARS:
        # Te groot: hou alleen de belangrijkste velden per node.
        keep = {"@type", "@id", "name", "url", "sameAs", "address", "telephone", "email", "vatID",
                "taxID", "identifier", "openingHours", "openingHoursSpecification", "logo", "image",
                "author", "brand", "aggregateRating", "validThrough", "itemListElement", "description"}
        jsonld_raw = [{k: v for k, v in n.items() if k in keep} for n in jsonld_raw if isinstance(n, dict)]

    normalized_text = re.sub(r"\W+", " ", text.lower()).strip()
    text_hash = hashlib.md5(normalized_text.encode("utf-8")).hexdigest() if len(normalized_text) > 200 else None

    signals: dict[str, Any] = {
        "phones": phones,
        "emails": _dedupe(emails, limit=5),
        "addresses": addresses,
        "postcodes": _dedupe(_POSTCODE_RE.findall(text), limit=5),
        "kvk": kvk,
        "btw": btw,
        "links": link_kinds,
        "profiles": profiles,
        "faq": bool(
            parser.details_count >= 2
            or parser.question_headings >= 3
            or (_FAQ_TEXT_RE.search(text) and parser.question_headings >= 1)
        ),
        "question_headings": parser.question_headings,
        "details_count": parser.details_count,
        "reviews": parser.rating_markers >= 2,
        "author_markers": parser.author_markers,
        "author_images": parser.author_images,
        "rel_author": _dedupe(parser.rel_author, limit=3),
        "hidden_blocks": parser.hidden_blocks,
        "body_classes": parser.body_classes,
        "plugins": plugins,
        "text_hash": text_hash,
    }
    return GeoExtract(jsonld=jsonld_raw, outlinks=outlinks, signals=signals)
