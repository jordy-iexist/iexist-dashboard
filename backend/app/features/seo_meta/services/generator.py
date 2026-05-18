import json
import re

from app.core.config import settings
from app.services.openai import create_response, response_output_text
from app.features.seo_meta.services.types import MetaSuggestion

SYSTEM_PROMPT = (
    "Je bent een senior SEO-copywriter. "
    "Schrijf heldere, natuurlijke en klikwaardige metadata in het Nederlands."
)


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _trim_to_limit(value: str, max_chars: int) -> str:
    normalized = _normalize_text(value)
    if len(normalized) <= max_chars:
        return normalized
    trimmed = normalized[:max_chars].rstrip()
    if " " in trimmed:
        trimmed = trimmed.rsplit(" ", 1)[0].strip()
    return trimmed


def _parse_json_response(output_text: str) -> dict[str, str]:
    text = str(output_text or "").strip()
    if not text:
        return {}

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError:
            pass

    lines = text.splitlines()
    title = ""
    description = ""
    for line in lines:
        lowered = line.lower()
        if lowered.startswith("title:"):
            title = line.split(":", 1)[1].strip()
        if lowered.startswith("description:"):
            description = line.split(":", 1)[1].strip()
    result: dict[str, str] = {}
    if title:
        result["title"] = title
    if description:
        result["description"] = description
    return result


def _fallback_title(*, current_title: str | None, h1: str | None, path: str) -> str:
    for candidate in [current_title, h1]:
        normalized = _normalize_text(candidate)
        if normalized:
            return normalized

    slug = path.strip("/").split("/")[-1]
    if slug:
        return slug.replace("-", " ").replace("_", " ").strip().title()
    return "Pagina"


def _fallback_description(
    *,
    current_description: str | None,
    content_excerpt: str | None,
    fallback_title: str,
) -> str:
    for candidate in [current_description, content_excerpt]:
        normalized = _normalize_text(candidate)
        if normalized:
            return normalized
    return f"Informatie over {fallback_title}."


def generate_meta_suggestion(
    *,
    user_id: str,
    model: str,
    title_max_chars: int,
    description_max_chars: int,
    page_url: str,
    path: str,
    current_title: str | None,
    current_description: str | None,
    h1: str | None,
    content_excerpt: str | None,
) -> MetaSuggestion:
    prompt = (
        "Genereer een SEO meta title en meta description als geldig JSON object met exact deze keys: "
        '{"title": "...", "description": "..."}.\n'
        f"- Doel URL: {page_url}\n"
        f"- Pad: {path}\n"
        f"- Huidige title: {current_title or '(leeg)'}\n"
        f"- Huidige description: {current_description or '(leeg)'}\n"
        f"- Eerste H1: {h1 or '(geen)'}\n"
        f"- Content samenvatting: {content_excerpt or '(geen)'}\n"
        f"- Lengte title: maximaal {title_max_chars} tekens\n"
        f"- Lengte description: maximaal {description_max_chars} tekens\n"
        "- Vermijd clickbait en onwaarheden."
    )

    response = create_response(
        user_id=user_id,
        model=model,
        instructions=SYSTEM_PROMPT,
        input=prompt,
        max_output_tokens=350,
        reasoning={"effort": settings.openai_seo_meta_reasoning_effort},
    )
    parsed = _parse_json_response(response_output_text(response))

    raw_title = _normalize_text(parsed.get("title", ""))
    raw_description = _normalize_text(parsed.get("description", ""))

    if not raw_title:
        raw_title = _fallback_title(
            current_title=current_title,
            h1=h1,
            path=path,
        )
    if not raw_description:
        raw_description = _fallback_description(
            current_description=current_description,
            content_excerpt=content_excerpt,
            fallback_title=raw_title,
        )

    final_title = _trim_to_limit(raw_title, title_max_chars)
    final_description = _trim_to_limit(raw_description, description_max_chars)

    if not final_title:
        raise ValueError("Kon geen bruikbare meta title genereren.")
    if not final_description:
        raise ValueError("Kon geen bruikbare meta description genereren.")

    return MetaSuggestion(
        title=final_title,
        description=final_description,
    )
