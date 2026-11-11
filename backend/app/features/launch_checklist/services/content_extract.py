"""Fase 3: inhoud van een pagina uit de HTML halen voor content- en onpage-checks.

Bovenop de fase-2 parser verzamelen we de zichtbare hoofdinhoud (zonder
navigatie, zijbalk en footer): tekst als eenvoudige markdown, de koppenstructuur
(H1–H4), de eerste alinea, afbeeldingen met alt-tekst en bestandsnaam, interne
links met ankertekst en signalen voor scanbaarheid, conversie en vertrouwen.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from app.features.launch_checklist.services.discovery import clean_url, is_internal, url_key
from app.features.launch_checklist.services.geo_extract import _GeoParser, all_types
from app.features.launch_checklist.services.html_extract import _WORD_RE, _clean

MAX_BODY_CHARS = 30_000
MAX_HEADINGS = 120
MAX_IMAGES = 80
MAX_LINKS = 300
FIRST_PARAGRAPH_MIN_CHARS = 60

_CHROME_TAGS = {"nav", "aside", "header", "footer"}
_MAIN_TAGS = {"main", "article"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_TAGS = _HEADING_TAGS | {
    "p", "li", "div", "section", "article", "main", "td", "th", "tr", "ul", "ol", "table",
    "blockquote", "br", "dt", "dd", "figure", "figcaption", "summary", "details", "form",
}
_SKIP_LINK_PREFIXES = ("#", "mailto:", "tel:", "javascript:", "data:", "sms:", "whatsapp:")
_CTA_RE = re.compile(
    r"\b(offerte|contact|afspraak|bel ons|bel direct|bel nu|aanvragen|aanvraag|bestel|koop|"
    r"in winkelwagen|inschrijven|aanmelden|demo|adviesgesprek|gratis advies|plan |reserveer|"
    r"boek |download|probeer|start nu|kennismak|terugbel)",
    re.IGNORECASE,
)


_SKIP_LINK_RE = re.compile(r"skip-link|skip-to|screen-reader-text|sr-only|visually-hidden", re.IGNORECASE)


@dataclass
class ContentExtract:
    title: str | None = None
    meta_description: str | None = None
    headings: list[dict[str, Any]] = field(default_factory=list)
    body_text: str = ""
    first_paragraph: str | None = None
    word_count: int = 0
    images: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)


class _ContentParser(_GeoParser):
    def __init__(self) -> None:
        super().__init__()
        self._chrome: list[str] = []
        self._main_depth = 0
        self.blocks: list[tuple[str, str]] = []
        self._kind = "p"
        self._buf: list[str] = []
        self.raw_images: list[dict[str, Any]] = []
        self.raw_links: list[dict[str, Any]] = []
        self._a: dict[str, Any] | None = None
        self.counts = {
            "lists": 0, "list_items": 0, "tables": 0, "forms": 0, "buttons": 0,
            "videos": 0, "blockquotes": 0, "strong": 0, "tel_links": 0, "mailto_links": 0,
        }
        self.cta_texts: list[str] = []
        self._button: list[str] | None = None

    @property
    def in_content(self) -> bool:
        return not self._chrome and self._skip_depth == 0

    def _flush(self) -> None:
        text = _clean("".join(self._buf))
        self._buf = []
        if text:
            self.blocks.append((self._kind, text))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        tag = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}

        if tag in _MAIN_TAGS:
            self._main_depth += 1
        if tag in _CHROME_TAGS:
            # <header>/<footer> binnen <main>/<article> horen bij de inhoud.
            always = tag in {"nav", "aside"}
            if self._chrome or always or self._main_depth == 0:
                self._chrome.append(tag)
        elif a.get("role", "").lower() == "navigation" and tag in {"div", "ul", "section"}:
            self._chrome.append(tag)
        elif tag == "a" and _SKIP_LINK_RE.search(a.get("class", "")):
            self._chrome.append(tag)  # "Ga naar de inhoud"

        if tag in _BLOCK_TAGS:
            self._flush()
            if tag in _HEADING_TAGS:
                self._kind = tag
            elif tag == "li":
                self._kind = "li"
            else:
                self._kind = "p"

        if tag == "img":
            self.raw_images.append({**a, "_in_content": self.in_content, "_has_alt": "alt" in a})
            if self._a is not None and a.get("alt"):
                self._a["fallback"].append(a["alt"])
        elif tag == "a":
            href = a.get("href", "").strip()
            if href:
                self._a = {
                    "href": href, "parts": [], "in_content": self.in_content,
                    "fallback": [a.get("aria-label", ""), a.get("title", "")],
                    "button": bool(re.search(r"\b(btn|button|cta)\b", a.get("class", ""), re.IGNORECASE)),
                }
                low = href.lower()
                if low.startswith("tel:"):
                    self.counts["tel_links"] += 1
                elif low.startswith("mailto:"):
                    self.counts["mailto_links"] += 1
        elif tag == "button":
            self._button = []

        if not self.in_content:
            return
        if tag in {"ul", "ol"}:
            self.counts["lists"] += 1
        elif tag == "li":
            self.counts["list_items"] += 1
        elif tag == "table":
            self.counts["tables"] += 1
        elif tag == "form":
            self.counts["forms"] += 1
        elif tag == "button":
            self.counts["buttons"] += 1
        elif tag in {"video", "iframe"}:
            src = a.get("src", "").lower()
            if tag == "video" or any(h in src for h in ("youtube", "vimeo", "wistia")):
                self.counts["videos"] += 1
        elif tag == "blockquote":
            self.counts["blockquotes"] += 1
        elif tag in {"strong", "b"}:
            self.counts["strong"] += 1

    def handle_endtag(self, tag: str) -> None:
        super().handle_endtag(tag)
        tag = tag.lower()
        if tag in _BLOCK_TAGS:
            self._flush()
            self._kind = "p"
        if tag == "a" and self._a is not None:
            text = _clean("".join(self._a["parts"])) or _clean(" ".join(self._a["fallback"]))
            self.raw_links.append({
                "href": self._a["href"], "text": text[:200], "in_content": self._a["in_content"],
            })
            if self._a["in_content"] and (self._a["button"] or _CTA_RE.search(text)) and text:
                self.cta_texts.append(text[:80])
            self._a = None
        elif tag == "button" and self._button is not None:
            text = _clean("".join(self._button))
            if text and not self._chrome and _CTA_RE.search(text):
                self.cta_texts.append(text[:80])
            self._button = None
        if tag in _MAIN_TAGS:
            self._main_depth = max(0, self._main_depth - 1)
        if self._chrome and self._chrome[-1] == tag:
            self._chrome.pop()

    def handle_data(self, data: str) -> None:
        super().handle_data(data)
        if self._a is not None:
            self._a["parts"].append(data)
        if self._button is not None:
            self._button.append(data)
        if self.in_content:
            self._buf.append(data)


def _image_src(attrs: dict[str, Any]) -> str:
    src = str(attrs.get("src") or "").strip()
    if not src or src.startswith("data:"):
        for key in ("data-src", "data-lazy-src", "data-original"):
            if attrs.get(key):
                return str(attrs[key]).strip()
        srcset = str(attrs.get("srcset") or attrs.get("data-srcset") or "").strip()
        if srcset:
            return srcset.split(",")[0].strip().split(" ")[0]
    return src


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip().rstrip("px"))
    except (TypeError, ValueError):
        return None


def _markdown(blocks: list[tuple[str, str]]) -> str:
    lines: list[str] = []
    size = 0
    for kind, text in blocks:
        if kind in _HEADING_TAGS:
            line = f"{'#' * int(kind[1])} {text}"
        elif kind == "li":
            line = f"- {text}"
        else:
            line = text
        if size + len(line) > MAX_BODY_CHARS:
            lines.append("…(ingekort)")
            break
        lines.append(line)
        size += len(line) + 1
    return "\n".join(lines)


def extract_content(html: str, page_url: str, root_domain: str) -> ContentExtract:
    parser = _ContentParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # kapotte HTML: neem wat we hebben
        pass
    parser._flush()
    page = parser.result()
    blocks = parser.blocks

    headings = [
        {"level": int(kind[1]), "text": text[:300]}
        for kind, text in blocks
        if kind in {"h1", "h2", "h3", "h4"}
    ][:MAX_HEADINGS]

    first_paragraph: str | None = None
    seen_h1 = not any(kind == "h1" for kind, _ in blocks)
    for kind, text in blocks:
        if kind == "h1":
            seen_h1 = True
        elif kind == "p" and seen_h1 and len(text) >= FIRST_PARAGRAPH_MIN_CHARS:
            first_paragraph = text[:1500]
            break

    images: list[dict[str, Any]] = []
    for raw in parser.raw_images:
        src = _image_src(raw)
        if not src or src.startswith("data:"):
            continue
        width, height = _int(raw.get("width")), _int(raw.get("height"))
        if (width is not None and width <= 2) or (height is not None and height <= 2):
            continue  # trackingpixels
        absolute = urljoin(page_url, src)
        filename = unquote(posixpath.basename(urlparse(absolute).path))
        images.append({
            "src": absolute,
            "alt": raw.get("alt") if raw["_has_alt"] else None,
            "filename": filename,
            "width": width,
            "height": height,
            "in_content": bool(raw["_in_content"]),
        })
        if len(images) >= MAX_IMAGES:
            break

    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str, bool]] = set()
    external = 0
    for raw in parser.raw_links:
        href = raw["href"]
        if href.lower().startswith(_SKIP_LINK_PREFIXES):
            continue
        absolute = clean_url(href, page_url)
        if not absolute:
            continue
        if not is_internal(absolute, root_domain):
            external += 1
            continue
        # Dezelfde link in de tekst én in menu/footer apart houden: de plek is nodig om hem te vinden.
        key = (url_key(absolute), raw["text"].lower(), bool(raw["in_content"]))
        if key in seen or len(links) >= MAX_LINKS:
            continue
        seen.add(key)
        links.append({
            "url": absolute, "href": href, "text": raw["text"], "in_content": bool(raw["in_content"]),
        })

    schema_types = sorted(all_types(parser.jsonld_nodes))
    content_words = sum(len(_WORD_RE.findall(text)) for _, text in blocks)
    signals = {
        **parser.counts,
        "cta_texts": list(dict.fromkeys(parser.cta_texts))[:15],
        "question_headings": parser.question_headings,
        "details_count": parser.details_count,
        "rating_markers": parser.rating_markers,
        "author_markers": parser.author_markers,
        "schema_types": schema_types,
        "has_faq_schema": "FAQPage" in schema_types,
        "has_review_schema": bool({"Review", "AggregateRating"} & set(schema_types)),
        "external_links": external,
        "content_images": sum(1 for i in images if i["in_content"]),
        "h1": page.h1[:5],
    }

    return ContentExtract(
        title=page.title or None,
        meta_description=page.meta_description or None,
        headings=headings,
        body_text=_markdown(blocks),
        first_paragraph=first_paragraph,
        word_count=content_words,
        images=images,
        links=links,
        signals=signals,
    )
