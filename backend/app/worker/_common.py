import re
from datetime import datetime, timezone


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
