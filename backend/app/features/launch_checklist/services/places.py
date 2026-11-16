"""Plaatsnamen herkennen in URL + titel/H1 (locatie- en landingspagina's)."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

_PLACE_RE = re.compile(
    r"\b(?:in|te|regio|omgeving|rond)\s+((?:Den |De |Het |'s-|Sint |Nieuw |Oud )?[A-Z][\wÀ-ÿ'\-]{2,})"
)
_NOT_PLACES = {"nederland", "belgië", "belgie", "europa", "huis", "nl"}
# Grotere Nederlandse plaatsen: herkent locatiepagina's als /seo-bureau-apeldoorn/
# ook zonder "in <plaats>" in de titel. Niet uitputtend; de regex hierboven vangt de rest.
_PLACES = (
    "Alkmaar Almelo Almere Alphen aan den Rijn Amersfoort Amstelveen Amsterdam Apeldoorn Arnhem Assen "
    "Barneveld Bergen op Zoom Breda Bussum Capelle aan den IJssel Delft Den Bosch Den Haag Den Helder "
    "Deventer Doetinchem Dordrecht Drachten Dronten Ede Eindhoven Elburg Emmen Enschede Epe Ermelo "
    "Gorinchem Gouda Groningen Haarlem Haarlemmermeer Harderwijk Heerenveen Heerhugowaard Heerlen "
    "Helmond Hengelo Hilversum Hoofddorp Hoogeveen Hoorn Houten Kampen Katwijk Leeuwarden Leiden "
    "Leidschendam Lelystad Maastricht Meppel Middelburg Nieuwegein Nijkerk Nijmegen Nunspeet Oosterhout "
    "Oss Purmerend Putten Roermond Roosendaal Rotterdam Schiedam Sittard Soest Spijkenisse Tiel Tilburg "
    "Uden Utrecht Veenendaal Veldhoven Velsen Venlo Vlaardingen Vlissingen Wageningen Weert Woerden "
    "Zaandam Zaanstad Zeewolde Zeist Zoetermeer Zutphen Zwolle"
)
_KNOWN_PLACES: dict[str, str] = {}
_multi = ("Alphen aan den Rijn", "Bergen op Zoom", "Capelle aan den IJssel", "Den Bosch", "Den Haag", "Den Helder")
_rest = _PLACES
for _name in _multi:
    _rest = _rest.replace(_name, "")
    _KNOWN_PLACES[re.sub(r"[^a-z]+", "-", _name.lower())] = _name
for _name in _rest.split():
    _KNOWN_PLACES[_name.lower()] = _name

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().replace("'", "")).strip("-")


def detect_place(page: Any) -> str | None:
    """Plaatsnaam van een locatiepagina: staat in titel/H1 én in de URL."""
    if (page.page_type or "") in {"home", "blog", "juridisch", "contact", "archief", "vacature"}:
        return None
    path = urlparse(page.url).path.lower()
    h1 = " ".join((getattr(page, "signals", None) or {}).get("h1") or getattr(page, "h1", None) or [])
    for source in (h1, page.title or ""):
        for match in _PLACE_RE.finditer(source):
            place = match.group(1).strip()
            if place.lower() in _NOT_PLACES:
                continue
            if _slug(place) and _slug(place) in path:
                return place
    # Bekende plaatsnaam als los woord in de URL én in titel/H1.
    padded = "-" + re.sub(r"[^a-z0-9]+", "-", path).strip("-") + "-"
    haystack = f"{h1} {page.title or ''}".lower()
    for slug, name in _KNOWN_PLACES.items():
        if f"-{slug}-" in padded and name.lower() in haystack:
            return name
    return None
