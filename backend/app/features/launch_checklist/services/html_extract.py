"""SEO-gegevens uit HTML halen met de stdlib-parser (geen extra dependencies)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

_SKIP_TEXT_TAGS = {"script", "style", "noscript", "template", "svg", "head"}
_WORD_RE = re.compile(r"[\wÀ-ÿ'-]+", re.UNICODE)
_WS_RE = re.compile(r"\s+")


@dataclass
class ExtractedPage:
    title: str | None = None
    meta_description: str | None = None
    meta_robots: str | None = None
    canonical: str | None = None
    lang: str | None = None
    hreflang: list[dict[str, str]] = field(default_factory=list)
    h1: list[str] = field(default_factory=list)
    h2: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    images_total: int = 0
    images_missing_alt: int = 0
    schema_types: list[str] = field(default_factory=list)
    open_graph: dict[str, str] = field(default_factory=dict)
    word_count: int = 0


def _clean(value: str | None) -> str:
    return _WS_RE.sub(" ", str(value or "")).strip()


def _collect_schema_types(node: Any, out: list[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _collect_schema_types(item, out)
        return
    if not isinstance(node, dict):
        return
    raw_type = node.get("@type")
    if isinstance(raw_type, str):
        out.append(raw_type)
    elif isinstance(raw_type, list):
        out.extend(str(t) for t in raw_type if isinstance(t, str))
    graph = node.get("@graph")
    if graph is not None:
        _collect_schema_types(graph, out)


class _SeoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.page = ExtractedPage()
        self._in_title = False
        self._title_parts: list[str] = []
        self._heading: str | None = None
        self._heading_parts: list[str] = []
        self._skip_depth = 0
        self._in_jsonld = False
        self._jsonld_parts: list[str] = []
        self._words = 0

    # --- tags -----------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}

        if tag == "html" and a.get("lang"):
            self.page.lang = a["lang"].strip()
        elif tag == "title" and self.page.title is None:
            self._in_title = True
        elif tag == "meta":
            self._handle_meta(a)
        elif tag == "link":
            rel = a.get("rel", "").lower().split()
            href = a.get("href", "").strip()
            if "canonical" in rel and href and self.page.canonical is None:
                self.page.canonical = href
            if "alternate" in rel and a.get("hreflang") and href:
                self.page.hreflang.append({"lang": a["hreflang"], "href": href})
        elif tag in {"h1", "h2"}:
            self._heading = tag
            self._heading_parts = []
        elif tag == "a":
            href = a.get("href", "").strip()
            if href:
                self.page.links.append(href)
        elif tag == "img":
            self.page.images_total += 1
            if "alt" not in a:
                # alt="" is bewust decoratief; alleen ontbrekend attribuut telt.
                self.page.images_missing_alt += 1
        elif tag == "script":
            if "ld+json" in a.get("type", "").lower():
                self._in_jsonld = True
                self._jsonld_parts = []

        if tag in _SKIP_TEXT_TAGS:
            self._skip_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() in _SKIP_TEXT_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self._in_title:
            self._in_title = False
            self.page.title = _clean("".join(self._title_parts))
        elif tag in {"h1", "h2"} and self._heading == tag:
            text = _clean("".join(self._heading_parts))
            (self.page.h1 if tag == "h1" else self.page.h2).append(text)
            self._heading = None
        elif tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            self._parse_jsonld("".join(self._jsonld_parts))

        if tag in _SKIP_TEXT_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._in_jsonld:
            self._jsonld_parts.append(data)
        if self._heading:
            self._heading_parts.append(data)
        if self._skip_depth == 0:
            self._words += len(_WORD_RE.findall(data))

    # --- helpers --------------------------------------------------------
    def _handle_meta(self, a: dict[str, str]) -> None:
        name = a.get("name", "").lower()
        prop = a.get("property", "").lower()
        content = _clean(a.get("content"))
        if name == "description" and self.page.meta_description is None:
            self.page.meta_description = content
        elif name in {"robots", "googlebot"} and content:
            existing = self.page.meta_robots
            self.page.meta_robots = f"{existing}, {content}" if existing else content
        if prop.startswith("og:") and content:
            self.page.open_graph.setdefault(prop, content)

    def _parse_jsonld(self, raw: str) -> None:
        raw = raw.strip()
        if not raw:
            return
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return
        found: list[str] = []
        _collect_schema_types(data, found)
        for t in found:
            if t not in self.page.schema_types:
                self.page.schema_types.append(t)

    def result(self) -> ExtractedPage:
        if self._in_title and self.page.title is None:
            self.page.title = _clean("".join(self._title_parts))
        self.page.word_count = self._words
        return self.page


def extract_page(html: str) -> ExtractedPage:
    parser = _SeoParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # kapotte HTML: neem wat we hebben
        pass
    return parser.result()
