"""Klantprofiel: wat het bureau over de klant vastlegt (bedrijf, diensten en prijzen, USP's,
bewijs, schrijfregels). Opgeslagen als één JSON-kolom `customer_websites.profile`.

Naam, website, tone of voice en aanspreekvorm staan niet hierin maar in de eigen kolommen
van `customer_websites`.

Opschonen in plaats van weigeren: witruimte samengevoegd, lege regels en dubbelen weg
(volgorde blijft), te lange teksten en lijsten afgekapt. Alleen een echt verkeerd type (een
getal waar een lijst hoort) geeft een validatiefout. `parse_profile` leest de opslag en geeft
bij lege of ongeldige inhoud een leeg profiel, nooit een exception.

Alleen Pydantic: deze module wordt geïmporteerd door `seo_tracker/schemas.py` en de
brief-agent en mag zelf niets uit de features importeren.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

# Limieten (tekens per tekst, items per lijst).
MAX_TEXT_CHARS = 300
MAX_LIST_ITEMS = 30
MAX_LIST_ITEM_CHARS = 300
MAX_EXAMPLE_URLS = 10
MAX_EXAMPLE_URL_CHARS = 500
MAX_AVOID_WORDS = 60
MAX_AVOID_WORD_CHARS = 60
MAX_SERVICES = 40
MAX_SERVICE_CHARS = 120

_TEXT_FIELDS = (
    "company_type",
    "service_area",
    "target_audience",
    "specialties",
    "services_source",
    "reviews",
    "certifications",
    "team",
    "language_level",
    "fixed_cta",
)
# Lijstveld → (max. items, max. tekens per item).
_LIST_LIMITS: dict[str, tuple[int, int]] = {
    "usps": (MAX_LIST_ITEMS, MAX_LIST_ITEM_CHARS),
    "cases": (MAX_LIST_ITEMS, MAX_LIST_ITEM_CHARS),
    "content_rules": (MAX_LIST_ITEMS, MAX_LIST_ITEM_CHARS),
    "example_urls": (MAX_EXAMPLE_URLS, MAX_EXAMPLE_URL_CHARS),
    "avoid_words": (MAX_AVOID_WORDS, MAX_AVOID_WORD_CHARS),
}


def _clean_text(value: Any, limit: int) -> Any:
    """Witruimte samenvoegen en afkappen; None wordt "". Geen string → ongewijzigd (Pydantic
    geeft dan de typefout)."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    text = " ".join(value.split())
    return text[:limit].rstrip()


def _clean_list(value: Any, max_items: int, max_chars: int) -> Any:
    """Items opschonen, lege en dubbele weg (hoofdletters genegeerd, volgorde blijft), afkappen."""
    if value is None:
        return []
    if not isinstance(value, list):
        return value
    result: list[Any] = []
    seen: set[str] = set()
    for item in value:
        if item is None:
            continue
        text = _clean_text(item, max_chars)
        if not isinstance(text, str):
            result.append(text)  # verkeerd type: Pydantic meldt het
            continue
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            result.append(text)
    return result[:max_items]


class CustomerService(BaseModel):
    """Eén dienst met (vanaf-)prijs zoals de klant hem noemt, bijv. "vanaf € 750 per maand"."""

    model_config = ConfigDict(extra="ignore")

    name: str = ""
    price: str = ""

    @field_validator("name", "price", mode="before")
    @classmethod
    def _text(cls, value: Any) -> Any:
        return _clean_text(value, MAX_SERVICE_CHARS)


class CustomerProfile(BaseModel):
    """Het klantprofiel; alle velden standaard leeg. Zie de moduledocstring voor het opschonen."""

    model_config = ConfigDict(extra="ignore")

    # Bedrijf
    company_type: str = ""
    service_area: str = ""
    target_audience: str = ""
    specialties: str = ""
    # Diensten & prijzen; `services_source`: waar de prijzen vandaan komen (bijv. "prijslijst 2026").
    services: list[CustomerService] = []
    services_source: str = ""
    # USP's en bewijs (E-E-A-T)
    usps: list[str] = []
    reviews: str = ""
    certifications: str = ""
    team: str = ""
    cases: list[str] = []
    # Regels voor AI-content
    language_level: str = ""
    fixed_cta: str = ""
    # Alleen bewaard en getoond; gaat niet naar Claude (de agent kan geen pagina's ophalen).
    example_urls: list[str] = []
    avoid_words: list[str] = []
    content_rules: list[str] = []

    @field_validator(*_TEXT_FIELDS, mode="before")
    @classmethod
    def _text(cls, value: Any) -> Any:
        return _clean_text(value, MAX_TEXT_CHARS)

    @field_validator(*_LIST_LIMITS, mode="before")
    @classmethod
    def _list(cls, value: Any, info: Any) -> Any:
        max_items, max_chars = _LIST_LIMITS[info.field_name]
        return _clean_list(value, max_items, max_chars)

    @field_validator("services", mode="before")
    @classmethod
    def _services(cls, value: Any) -> Any:
        """Rijen zonder naam vervallen, dubbele rijen (naam + prijs) ook; hooguit `MAX_SERVICES`."""
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        result: list[Any] = []
        seen: set[tuple[str, str]] = set()
        for item in value:
            if item is None:
                continue
            if isinstance(item, CustomerService):
                item = item.model_dump()
            if not isinstance(item, dict):
                result.append(item)  # verkeerd type: Pydantic meldt het
                continue
            name = _clean_text(item.get("name"), MAX_SERVICE_CHARS)
            price = _clean_text(item.get("price"), MAX_SERVICE_CHARS)
            if not isinstance(name, str) or not isinstance(price, str):
                result.append(item)  # verkeerd type: Pydantic meldt het
                continue
            key = (name.casefold(), price.casefold())
            if name and key not in seen:
                seen.add(key)
                result.append({"name": name, "price": price})
        return result[:MAX_SERVICES]


def parse_profile(raw: Any) -> CustomerProfile:
    """De opgeslagen kolom → `CustomerProfile`. None, leeg of ongeldig → leeg profiel.

    Een veld met een verkeerd type valt weg; de rest blijft staan. Gooit nooit een exception.
    """
    if not isinstance(raw, dict) or not raw:
        return CustomerProfile()
    try:
        return CustomerProfile.model_validate(raw)
    except ValidationError as exc:
        bad = {err["loc"][0] for err in exc.errors() if err.get("loc")}
    except (TypeError, ValueError):
        return CustomerProfile()
    try:
        return CustomerProfile.model_validate({k: v for k, v in raw.items() if k not in bad})
    except (ValidationError, TypeError, ValueError):
        return CustomerProfile()
