import re
from datetime import datetime, timezone


class PermanentTaskError(Exception):
    """Datafout die niet door een retry opgelost wordt (ontbrekende job/rij/gebruiker)."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_single_record(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def build_title(row_data: dict) -> str:
    klant = str(row_data.get("klant", "") or "").strip()
    if klant:
        return klant
    return "Gegenereerde blog"


_H1_PATTERN = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)


def split_markdown_title(content: str) -> tuple[str | None, str]:
    """Splits de eerste H1 af van de markdown; geeft (titel, body zonder die kop)."""
    match = _H1_PATTERN.search(content or "")
    if not match or not match.group(1).strip():
        return None, content
    body = (content[: match.start()] + content[match.end() :]).strip()
    return match.group(1).strip(), body


def _strip_markdown(text: str) -> str:
    # Links: keep link text, drop URL
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Headings
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Bold/italic
    text = re.sub(r"(\*{1,3}|_{1,3})(.+?)\1", r"\2", text)
    return text


def build_excerpt(content: str, max_length: int = 220) -> str:
    plain = _strip_markdown(content)
    normalized = " ".join(plain.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[:max_length].rsplit(" ", 1)[0].strip()
