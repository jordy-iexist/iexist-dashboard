from dataclasses import dataclass


@dataclass
class MetaPageDiscoveryResult:
    urls: list[str]
    skipped_due_to_limit: int
    source: str


@dataclass
class PageSnapshot:
    url: str
    path: str
    title: str | None
    description: str | None
    h1: str | None
    content_excerpt: str


@dataclass
class MetaSuggestion:
    title: str
    description: str
