"""Interne linkgraaf: klikdiepte vanaf de homepage en inkomende links per pagina."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from app.features.launch_checklist.services.discovery import url_key


@dataclass
class GraphNode:
    page_id: str
    url: str
    final_url: str | None
    outlinks: list[str] | None  # None = niet opgehaald


@dataclass
class GraphResult:
    depth: dict[str, int | None] = field(default_factory=dict)   # page_id → klikdiepte
    inlinks: dict[str, int] = field(default_factory=dict)        # page_id → aantal linkende pagina's
    unknown_targets: list[str] = field(default_factory=list)     # gelinkte URL's die niet in de scan zitten


def build_link_graph(nodes: list[GraphNode], home_page_id: str | None) -> GraphResult:
    key_to_id: dict[str, str] = {}
    for n in nodes:
        key_to_id.setdefault(url_key(n.url), n.page_id)
        if n.final_url:
            key_to_id.setdefault(url_key(n.final_url), n.page_id)

    edges: dict[str, set[str]] = {}
    incoming: dict[str, set[str]] = {n.page_id: set() for n in nodes}
    unknown: set[str] = set()
    for n in nodes:
        targets: set[str] = set()
        for link in n.outlinks or []:
            target = key_to_id.get(url_key(link))
            if target is None:
                if len(unknown) < 500:
                    unknown.add(link)
                continue
            if target != n.page_id:
                targets.add(target)
                incoming[target].add(n.page_id)
        edges[n.page_id] = targets

    result = GraphResult(inlinks={pid: len(src) for pid, src in incoming.items()})
    result.depth = {n.page_id: None for n in nodes}
    home_id = home_page_id
    if home_id is not None and home_id in result.depth:
        result.depth[home_id] = 0
        queue: deque[str] = deque([home_id])
        while queue:
            current = queue.popleft()
            for nxt in edges.get(current, ()):
                if result.depth[nxt] is None:
                    result.depth[nxt] = (result.depth[current] or 0) + 1
                    queue.append(nxt)
    result.unknown_targets = sorted(unknown)
    return result
