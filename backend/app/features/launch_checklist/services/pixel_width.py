"""Schatting van de pixelbreedte van een titel/description in de Google-SERP.

We rekenen met de tekenbreedtes van Arial (in duizendsten van de fontgrootte):
titels op 20px en descriptions op 13px, de maten waarmee SEO-tools hun
pixelgrenzen (580 px / 920 px) hanteren. Het blijft een benadering. Let op: bij
gewone tekst is 920 px eerder bereikt (±140 tekens) dan de grens van 160 tekens.
"""
from __future__ import annotations

TITLE_FONT_PX = 20
DESCRIPTION_FONT_PX = 13
TITLE_MAX_CHARS, TITLE_MAX_PX = 60, 580
DESCRIPTION_MAX_CHARS, DESCRIPTION_MAX_PX = 160, 920

_DEFAULT = 556
_WIDTHS: dict[str, int] = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191,
    "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278,
    ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015,
    "[": 278, "\\": 278, "]": 278, "_": 556, "|": 260, "€": 556, "–": 556, "—": 1000,
    "’": 222, "‘": 222, "“": 333, "”": 333, "•": 350, "…": 1000, "·": 278, "»": 556, "«": 556,
    "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778, "H": 722,
    "I": 278, "J": 500, "K": 667, "L": 556, "M": 833, "N": 722, "O": 778, "P": 667,
    "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944, "X": 667,
    "Y": 667, "Z": 611,
    "a": 556, "b": 556, "c": 500, "d": 556, "e": 556, "f": 278, "g": 556, "h": 556,
    "i": 222, "j": 222, "k": 500, "l": 222, "m": 833, "n": 556, "o": 556, "p": 556,
    "q": 556, "r": 333, "s": 500, "t": 278, "u": 556, "v": 500, "w": 722, "x": 500,
    "y": 500, "z": 500,
}
# Letters met accenten zijn even breed als hun basisletter.
_ACCENTS = {
    "à": "a", "á": "a", "â": "a", "ä": "a", "ã": "a", "å": "a", "ç": "c",
    "è": "e", "é": "e", "ê": "e", "ë": "e", "ì": "i", "í": "i", "î": "i", "ï": "i",
    "ñ": "n", "ò": "o", "ó": "o", "ô": "o", "ö": "o", "õ": "o",
    "ù": "u", "ú": "u", "û": "u", "ü": "u", "ý": "y", "ÿ": "y",
    "À": "A", "Á": "A", "Ä": "A", "È": "E", "É": "E", "Ë": "E", "Ï": "I",
    "Ö": "O", "Ó": "O", "Ü": "U",
}


def pixel_width(text: str | None, font_px: int) -> int:
    total = 0
    for ch in text or "":
        total += _WIDTHS.get(_ACCENTS.get(ch, ch), _DEFAULT)
    return round(total * font_px / 1000)


def title_width(text: str | None) -> int:
    return pixel_width(text, TITLE_FONT_PX)


def description_width(text: str | None) -> int:
    return pixel_width(text, DESCRIPTION_FONT_PX)


def fits_title(text: str | None) -> bool:
    return len(text or "") <= TITLE_MAX_CHARS and title_width(text) <= TITLE_MAX_PX


def fits_description(text: str | None) -> bool:
    return len(text or "") <= DESCRIPTION_MAX_CHARS and description_width(text) <= DESCRIPTION_MAX_PX
