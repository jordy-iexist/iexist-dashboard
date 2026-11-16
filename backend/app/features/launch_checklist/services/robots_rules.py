"""robots.txt-regels evalueren zoals Google ze toepast.

`urllib.robotparser` neemt de eerste regel die past en kent geen `*` en `$` in
paden. Daardoor geeft hij bij `Disallow: /` + `Allow: /x/` een valse blokkade en
mist hij `Disallow: /*?`. Deze matcher volgt de documentatie van Google
(https://developers.google.com/search/docs/crawling-indexing/robots/robots_txt):

- de groep met de meest specifieke user-agent die bij de bot hoort (exact,
  dan zonder achtervoegsel: Googlebot-News valt terug op Googlebot), anders de
  `*`-groep; groepen met dezelfde user-agent worden samengevoegd;
- de langste passende regel wint, bij gelijke lengte wint `Allow`;
- `*` staat voor nul of meer tekens, `$` aan het eind voor het einde van de URL;
- een lege `Disallow:` blokkeert niets.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import urlparse

# Tekens die bij de product-token van een user-agent horen (Google negeert de rest, bv. "/1.0").
_AGENT_TOKEN = re.compile(r"[A-Za-z_-]+")


@dataclass(frozen=True)
class Rule:
    allow: bool
    path: str

    @property
    def line(self) -> str:
        return f"{'Allow' if self.allow else 'Disallow'}: {self.path}"


@dataclass
class RobotsRules:
    """Regels per user-agent (kleine letters); `*` is de standaardgroep."""
    groups: dict[str, list[Rule]] = field(default_factory=dict)

    def rules_for(self, user_agent: str) -> list[Rule] | None:
        """Regels van de best passende groep; None als geen enkele groep geldt."""
        token = user_agent.strip().lower()
        # Meest specifiek eerst: "googlebot-news", dan "googlebot", dan "*".
        while token:
            if token in self.groups:
                return self.groups[token]
            token = token.rpartition("-")[0]
        return self.groups.get("*")

    def check(self, user_agent: str, url: str) -> tuple[bool, str | None]:
        """(toegestaan, beslissende regel). Zonder passende regel: (True, None)."""
        rules = self.rules_for(user_agent)
        if not rules:
            return True, None
        target = _path_of(url)
        best: Rule | None = None
        for rule in rules:
            if not _matches(rule.path, target):
                continue
            if (
                best is None
                or len(rule.path) > len(best.path)
                or (len(rule.path) == len(best.path) and rule.allow and not best.allow)
            ):
                best = rule
        if best is None:
            return True, None
        return best.allow, best.line


def parse_robots(text: str | None) -> RobotsRules:
    result = RobotsRules()
    if not text:
        return result
    agents: list[str] = []
    in_rules = False  # na een regel begint een nieuwe user-agent-regel een nieuwe groep
    for raw in text.lstrip("﻿").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if in_rules:
                agents, in_rules = [], False
            if value == "*":
                agent = "*"
            else:
                match = _AGENT_TOKEN.match(value)
                agent = match.group(0).lower() if match else ""
            if agent:
                agents.append(agent)
                result.groups.setdefault(agent, [])
        elif key in {"allow", "disallow"}:
            in_rules = True
            if not agents or not value:
                continue  # regel buiten een groep, of lege waarde: geldt niet
            if not value.startswith(("/", "*")):
                value = "/" + value
            rule = Rule(allow=key == "allow", path=value)
            for agent in agents:
                result.groups[agent].append(rule)
        # Overige regels (Sitemap, Crawl-delay, ...) beëindigen een groep niet.
    return result


def _path_of(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    return f"{path}?{parsed.query}" if parsed.query else path


@lru_cache(maxsize=1024)
def _pattern(path: str) -> re.Pattern[str]:
    anchored = path.endswith("$")
    body = path[:-1] if anchored else path
    regex = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile(regex + ("$" if anchored else ""))


def _matches(rule_path: str, target: str) -> bool:
    return _pattern(rule_path).match(target) is not None
