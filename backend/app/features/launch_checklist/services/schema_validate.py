"""Schema-validatie (fase 4): is de JSON-LD geldig en compleet?

Werkt op de ruwe <script type="application/ld+json">-blokken uit de HTML, zodat
ongeldige JSON en lange velden (die `geo_extract` inkort) meetellen.

De regels volgen de verplichte eigenschappen voor Google-rich results, aangevuld
met wat AI-zoekmachines nodig hebben om een entiteit te herkennen. Elk vereiste
is een tuple van alternatieven: één ervan moet aanwezig zijn.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.features.launch_checklist.services.geo_extract import flatten_jsonld, types_of

MAX_BLOCKS = 30
MAX_PROBLEMS_PER_PAGE = 20

_JSONLD_RE = re.compile(
    r"<script\b[^>]*\btype\s*=\s*[\"']?application/ld\+json[\"']?[^>]*>(.*?)</script\s*>",
    re.IGNORECASE | re.DOTALL,
)

Requirement = tuple[str, ...]

_ORG: list[Requirement] = [("name",)]
_LOCAL: list[Requirement] = [("name",), ("address",)]

# Verplicht per type. Onbekende types worden niet gecontroleerd.
REQUIRED: dict[str, list[Requirement]] = {
    "Organization": _ORG,
    "Corporation": _ORG,
    "OnlineStore": _ORG,
    "NGO": _ORG,
    "LocalBusiness": _LOCAL,
    "ProfessionalService": _LOCAL,
    "HomeAndConstructionBusiness": _LOCAL,
    "Store": _LOCAL,
    "Restaurant": _LOCAL,
    "Electrician": _LOCAL,
    "Plumber": _LOCAL,
    "RoofingContractor": _LOCAL,
    "HVACBusiness": _LOCAL,
    "GeneralContractor": _LOCAL,
    "HousePainter": _LOCAL,
    "Locksmith": _LOCAL,
    "MovingCompany": _LOCAL,
    "AutoRepair": _LOCAL,
    "Dentist": _LOCAL,
    "MedicalBusiness": _LOCAL,
    "LegalService": _LOCAL,
    "AccountingService": _LOCAL,
    "FinancialService": _LOCAL,
    "RealEstateAgent": _LOCAL,
    "LodgingBusiness": _LOCAL,
    "Hotel": _LOCAL,
    "Person": [("name",)],
    "WebSite": [("name", "url")],
    "BreadcrumbList": [("itemListElement",)],
    "FAQPage": [("mainEntity",)],
    "Article": [("headline",)],
    "BlogPosting": [("headline",)],
    "NewsArticle": [("headline",)],
    "Product": [("name",), ("offers", "review", "aggregateRating")],
    "Service": [("name", "serviceType")],
    "JobPosting": [("title",), ("datePosted",), ("description",), ("hiringOrganization",),
                   ("jobLocation", "jobLocationType", "applicantLocationRequirements")],
    "Event": [("name",), ("startDate",), ("location",)],
    "AggregateRating": [("ratingValue",), ("ratingCount", "reviewCount")],
    "Review": [("author",), ("reviewRating", "reviewBody")],
    "ItemList": [("itemListElement",)],
}

# Aanbevolen (geeft een waarschuwing, geen fout).
RECOMMENDED: dict[str, list[Requirement]] = {
    "Organization": [("url",), ("logo",)],
    "LocalBusiness": [("telephone",), ("url",)],
    "Article": [("author",), ("datePublished",)],
    "BlogPosting": [("author",), ("datePublished",)],
    "NewsArticle": [("author",), ("datePublished",)],
    "Product": [("image",)],
}
for _local_type, _rules in REQUIRED.items():
    if _rules is _LOCAL and _local_type != "LocalBusiness":
        RECOMMENDED.setdefault(_local_type, RECOMMENDED["LocalBusiness"])


def extract_jsonld_blocks(html: str) -> list[str]:
    return [m.group(1) for m in _JSONLD_RE.finditer(html or "")][:MAX_BLOCKS]


def _present(node: dict[str, Any], key: str) -> bool:
    value = node.get(key)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _missing(node: dict[str, Any], rules: list[Requirement]) -> list[str]:
    return [" of ".join(alternatives) for alternatives in rules if not any(_present(node, k) for k in alternatives)]


def _nested_problems(type_name: str, node: dict[str, Any]) -> list[str]:
    """Inhoudelijke controles die verder gaan dan 'veld aanwezig'."""
    problems: list[str] = []
    if type_name == "BreadcrumbList":
        elements = node.get("itemListElement")
        elements = elements if isinstance(elements, list) else [elements]
        for index, element in enumerate(elements, start=1):
            if not isinstance(element, dict):
                continue
            item = element.get("item")
            has_name = _present(element, "name") or (isinstance(item, dict) and _present(item, "name"))
            if not _present(element, "position") or not has_name:
                problems.append(f"kruimelpad-item {index} mist position of name")
                break
    elif type_name == "FAQPage":
        entities = node.get("mainEntity")
        entities = entities if isinstance(entities, list) else [entities]
        for index, question in enumerate(entities, start=1):
            if not isinstance(question, dict):
                continue
            answer = question.get("acceptedAnswer")
            if isinstance(answer, list):
                answer = answer[0] if answer else None
            if not _present(question, "name") or not (isinstance(answer, dict) and _present(answer, "text")):
                problems.append(f"vraag {index} mist name of acceptedAnswer.text")
                break
    return problems


def validate_node(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Problemen van één JSON-LD-node (en een geneste aggregateRating)."""
    found: list[dict[str, Any]] = []
    for type_name in types_of(node):
        missing = _missing(node, REQUIRED.get(type_name, []))
        nested = _nested_problems(type_name, node)
        if missing or nested:
            found.append({"type": type_name, "severity": "error", "missing": missing, "problems": nested})
            continue
        recommended = _missing(node, RECOMMENDED.get(type_name, []))
        if recommended:
            found.append({"type": type_name, "severity": "warning", "missing": recommended, "problems": []})
    rating = node.get("aggregateRating")
    if isinstance(rating, dict):
        missing = _missing(rating, REQUIRED["AggregateRating"])
        if missing:
            found.append({"type": "AggregateRating", "severity": "error", "missing": missing, "problems": []})
    return found


def validate_blocks(blocks: list[str]) -> dict[str, Any]:
    """Resultaat per pagina: aantal blokken, ongeldige JSON, types en problemen."""
    invalid = 0
    types: set[str] = set()
    problems: list[dict[str, Any]] = []
    for raw in blocks:
        text = raw.strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            invalid += 1
            continue
        for node in flatten_jsonld(data):
            types.update(types_of(node))
            problems.extend(validate_node(node))
    # Dezelfde melding (bijv. elk product in een lijst) maar één keer tonen.
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for problem in problems:
        key = (problem["type"], problem["severity"], tuple(problem["missing"]), tuple(problem["problems"]))
        if key not in seen:
            seen.add(key)
            unique.append(problem)
    return {
        "blocks": len([b for b in blocks if b.strip()]),
        "invalid_blocks": invalid,
        "types": sorted(types),
        "problems": unique[:MAX_PROBLEMS_PER_PAGE],
    }


def validate_html(html: str) -> dict[str, Any]:
    return validate_blocks(extract_jsonld_blocks(html))


def describe_problem(problem: dict[str, Any]) -> str:
    parts: list[str] = []
    if problem.get("missing"):
        parts.append("mist " + ", ".join(problem["missing"]))
    parts.extend(problem.get("problems") or [])
    return f"{problem.get('type')}: {'; '.join(parts)}"
