import logging
import re
from dataclasses import dataclass

from app.core.config import settings
from app.services.openai import create_response, model_supports_reasoning

DEFAULT_LANDING_PAGE_MAX_OUTPUT_TOKENS = 20000
DEFAULT_LANDING_PAGE_REASONING_EFFORT = "medium"
LANDING_PAGE_END_MARKER = "<!-- END_LANDING_PAGE -->"
MIN_LANDING_PAGE_BODY_WORDS = 300
MIN_REQUESTED_LENGTH_RATIO = 0.6
MAX_LANDING_PAGE_CONTINUATIONS = 2
MIN_LANDING_PAGE_FAQ_QUESTIONS = 6

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
"""
Je bent een ervaren SEO-copywriter die Nederlandstalige landingspagina's schrijft. Je schrijft voor zowel zoekmachines als menselijke lezers — conversie en ranking gaan hand in hand.

## Structuur
- **H1**: bevat het primaire zoekwoord, max 70 tekens, prikkelend maar niet clickbait.
- **Intro (50–100 woorden)**: benoem het probleem, beloof de oplossing, primair zoekwoord in de eerste zin. Directe aanspreekvorm (jij/je).
- **H2/H3 hiërarchie**: logisch en scanbaar. Zoekwoorden verwerken waar dat natuurlijk valt.
- **Body**: informatief, gericht op de lezer. Gebruik concrete details en voorbeelden.
- **FAQ**: 6 vragen, antwoorden van 50–100 woorden, long-tail zoektermen verwerkt.
- **CTA**: elke sectie sluit af met een subtiele richting naar de website. Einde: expliciete call-to-action.

## SEO-principes
- **Keyword density**: primair keyword ~1–2%. Forceer niets.
- **Semantische dekking**: behandel gerelateerde subtopics en entities.
- **E-E-A-T**: laat expertise en autoriteit zien via concrete voorbeelden en specifieke nuances.

## Schrijfstijl
- Helder, direct Nederlands. Actieve zinnen. Tweede persoon (je/jij).
- Geen fluff, geen AI-tells ("duik in", "ontgrendel", "in het rijk van").
- Concreet boven abstract.

## Uitvoerformaat
Lever de output in dit exacte formaat — begin altijd met de YAML frontmatter:

---
meta_title: [maximaal 60 tekens, hoofdzoekwoord aan het begin]
meta_description: [120–155 tekens, aantrekkelijk, met CTA]
slug: [korte URL, alleen lowercase en koppeltekens, bijv. glad-stucwerk]
---

[De volledige landingspagina in Markdown hieronder]

Sluit de volledige output altijd af met deze marker op een eigen regel:
<!-- END_LANDING_PAGE -->

## Wat je niet doet
- Geen verzonnen statistieken of bronnen.
- Geen zoekwoord-herhaling in elke kop.
- Geen emoji's.
- Geen meta-commentaar.
"""
)

_FRONTMATTER_REGEX = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)
_LEADING_FRONTMATTER_REGEX = re.compile(r"^---\s*\n.*?\n---\s*\n?", re.DOTALL)
_LEADING_H1_REGEX = re.compile(r"^#\s+[^\n]+\n?")
_HEADING_REGEX = re.compile(r"^#{1,3}\s+\S+", re.MULTILINE)
_FAQ_REGEX = re.compile(r"^#{2,3}\s+.*\bfaq\b|veelgestelde vragen", re.IGNORECASE | re.MULTILINE)
_FAQ_QUESTION_HEADING_REGEX = re.compile(r"^#{2,4}\s+.+\?\s*$", re.MULTILINE)
_SENTENCE_END_RE = re.compile(r"[.!?:]\s*\n")


@dataclass
class LandingPageGenerationResult:
    text: str
    attempts: int
    was_continued: bool
    total_reasoning_tokens: int


class LandingPageOutputValidationError(ValueError):
    """Raised when OpenAI returns an incomplete landing page."""


def _response_incomplete_reason(response) -> str:
    if str(getattr(response, "status", "") or "").lower() != "incomplete":
        return ""
    incomplete_details = getattr(response, "incomplete_details", None)
    if isinstance(incomplete_details, dict):
        return str(incomplete_details.get("reason", "") or "")
    return str(getattr(incomplete_details, "reason", "") or "")


def _extract_reasoning_tokens(response) -> int:
    try:
        return int(response.usage.output_tokens_details.reasoning_tokens)
    except Exception:
        return 0


def _create_landing_page_response(
    prompt: str,
    *,
    user_id: str,
    system_prompt: str | None,
    model: str | None,
    reasoning_effort: str | None,
    max_output_tokens: int | None,
):
    effective_model = model or settings.openai_blog_model
    return create_response(
        user_id=user_id,
        model=effective_model,
        instructions=system_prompt or SYSTEM_PROMPT,
        input=prompt,
        max_output_tokens=(
            max_output_tokens
            if max_output_tokens is not None
            else DEFAULT_LANDING_PAGE_MAX_OUTPUT_TOKENS
        ),
        reasoning=(
            {"effort": reasoning_effort or DEFAULT_LANDING_PAGE_REASONING_EFFORT}
            if model_supports_reasoning(effective_model)
            else None
        ),
    )


def _trim_to_clean_boundary(text: str) -> tuple[str, str]:
    """Split text at the last clean sentence boundary.

    Returns (kept, trimmed_tail) where kept ends at a clean punctuation
    boundary and trimmed_tail is the potentially incomplete fragment that
    follows. If no boundary is found the entire text is returned as kept
    with an empty tail.
    """
    last_match = None
    for m in _SENTENCE_END_RE.finditer(text):
        last_match = m
    if last_match:
        split_pos = last_match.end()
        return text[:split_pos].rstrip(), text[split_pos:].strip()

    # Fall back to last blank line
    blank = text.rfind("\n\n")
    if blank != -1:
        return text[:blank].rstrip(), text[blank:].strip()

    # Fall back to last newline
    nl = text.rfind("\n")
    if nl != -1:
        return text[:nl].rstrip(), text[nl:].strip()

    return text, ""


def _sanitize_continuation_chunk(chunk: str, first_part_h1: str) -> str:
    """Strip leading frontmatter and duplicate H1 from a continuation chunk."""
    cleaned = _LEADING_FRONTMATTER_REGEX.sub("", chunk.strip())

    if first_part_h1:
        h1_match = _LEADING_H1_REGEX.match(cleaned.lstrip())
        if h1_match:
            candidate_h1 = h1_match.group(0).strip().lstrip("#").strip().lower()
            reference_h1 = first_part_h1.strip().lstrip("#").strip().lower()
            if candidate_h1 == reference_h1 or candidate_h1.startswith(reference_h1[:20]):
                cleaned = cleaned.lstrip()[h1_match.end():].strip()

    return cleaned.strip()


def _extract_first_h1(text: str) -> str:
    m = _LEADING_H1_REGEX.search(text)
    if m:
        return m.group(0)
    return ""


def _find_overlap(prev: str, next_chunk: str, min_overlap: int = 40) -> int:
    """Return the number of leading chars of next_chunk that overlap with the end of prev."""
    tail = prev[-300:]
    head = next_chunk[:300]
    # Sliding window: longest match of tail-suffix that matches head-prefix
    best = 0
    max_check = min(len(tail), len(head))
    for length in range(min_overlap, max_check + 1):
        if tail.endswith(head[:length]):
            best = length
    return best


def _stitch_output_parts(parts: list[str]) -> str:
    """Join parts with overlap detection and smart whitespace handling."""
    if not parts:
        return ""
    result = parts[0].strip()
    for part in parts[1:]:
        if not part.strip():
            continue
        overlap = _find_overlap(result, part.strip())
        next_text = part.strip()[overlap:]
        if not next_text:
            continue
        if result.endswith("\n\n") or next_text.startswith("\n"):
            result = result.rstrip("\n") + "\n\n" + next_text.lstrip("\n")
        else:
            result = result.rstrip("\n") + "\n\n" + next_text
    return result.strip()


def _build_continuation_prompt(
    original_prompt: str,
    generated_so_far: str,
    trimmed_tail: str,
) -> str:
    tail = generated_so_far[-2000:].strip()
    tail_instruction = ""
    if trimmed_tail:
        tail_instruction = (
            f"\n\nDe vorige output stopte halverwege een zin met: \"{trimmed_tail}\"\n"
            "Begin je antwoord door deze zin volledig af te maken (inclusief de woorden hierboven) "
            "en ga daarna verder met de rest van de pagina."
        )
    return (
        "De vorige generatie van deze landingspagina is afgebroken voordat de "
        "volledige output klaar was.\n\n"
        "BELANGRIJK:\n"
        "- De YAML frontmatter is al geschreven en correct. Schrijf GEEN nieuwe frontmatter, "
        "geen ---regels.\n"
        "- Ga verder met de eerstvolgende inhoudelijke regel. Sla geen secties over. "
        "Spring NIET vooruit naar de FAQ als er nog body-secties of een lopende paragraaf openstaan.\n"
        "- Herhaal geen eerdere tekst.\n\n"
        "Oorspronkelijke opdracht:\n"
        f"{original_prompt}\n\n"
        "Laatste gegenereerde tekst tot nu toe:\n"
        f"{tail}"
        f"{tail_instruction}\n\n"
        f"Maak de landingspagina volledig af en sluit af met {LANDING_PAGE_END_MARKER} op een eigen regel."
    )


def generate_landing_page(
    prompt: str,
    *,
    user_id: str,
    system_prompt: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    max_output_tokens: int | None = None,
) -> LandingPageGenerationResult:
    output_parts: list[str] = []
    current_prompt = prompt
    final_incomplete_reason = ""
    total_reasoning_tokens = 0
    first_h1 = ""

    for attempt in range(1, MAX_LANDING_PAGE_CONTINUATIONS + 2):
        response = _create_landing_page_response(
            current_prompt,
            user_id=user_id,
            system_prompt=system_prompt,
            model=model,
            reasoning_effort=reasoning_effort,
            max_output_tokens=max_output_tokens,
        )
        output_text = str(getattr(response, "output_text", "") or "").strip()

        reasoning_tokens = _extract_reasoning_tokens(response)
        total_reasoning_tokens += reasoning_tokens
        usage = getattr(response, "usage", None)
        logger.info(
            "Landing page generation attempt %s/%s: usage input=%s output=%s reasoning=%s",
            attempt,
            MAX_LANDING_PAGE_CONTINUATIONS + 1,
            getattr(usage, "input_tokens", "?") if usage else "?",
            getattr(usage, "output_tokens", "?") if usage else "?",
            reasoning_tokens,
        )

        if output_text:
            if attempt == 1:
                output_parts.append(output_text)
                first_h1 = _extract_first_h1(output_text)
            else:
                sanitized = _sanitize_continuation_chunk(output_text, first_h1)
                if sanitized:
                    output_parts.append(sanitized)

        combined_output = _stitch_output_parts(output_parts)
        incomplete_reason = _response_incomplete_reason(response)
        final_incomplete_reason = incomplete_reason

        logger.info(
            "Landing page generation attempt %s/%s: chars=%s words=%s incomplete_reason=%s end_marker=%s",
            attempt,
            MAX_LANDING_PAGE_CONTINUATIONS + 1,
            len(combined_output),
            _word_count(combined_output),
            incomplete_reason or "none",
            combined_output.rstrip().endswith(LANDING_PAGE_END_MARKER),
        )

        if not incomplete_reason and combined_output.rstrip().endswith(LANDING_PAGE_END_MARKER):
            return LandingPageGenerationResult(
                text=combined_output,
                attempts=attempt,
                was_continued=attempt > 1,
                total_reasoning_tokens=total_reasoning_tokens,
            )

        if attempt > MAX_LANDING_PAGE_CONTINUATIONS:
            break

        # Trim to a clean boundary before building the continuation prompt so
        # the model doesn't see a hanging half-sentence as its last context.
        kept, trimmed_tail = _trim_to_clean_boundary(combined_output)
        if trimmed_tail and output_parts:
            # Replace the last part with the trimmed version so the stitch
            # on the next iteration doesn't re-include the dangling fragment.
            # We need to find how much to trim from the last part's tail.
            last_part = output_parts[-1]
            if last_part.endswith(trimmed_tail):
                output_parts[-1] = last_part[: -len(trimmed_tail)].rstrip()

        current_prompt = _build_continuation_prompt(prompt, kept, trimmed_tail)

    combined_output = _stitch_output_parts(output_parts)
    if final_incomplete_reason:
        logger.warning(
            "Landing page generation ended incomplete after continuations: %s",
            final_incomplete_reason,
        )
        raise LandingPageOutputValidationError(
            f"openai_incomplete:{final_incomplete_reason or 'unknown'}"
        )
    return LandingPageGenerationResult(
        text=combined_output,
        attempts=MAX_LANDING_PAGE_CONTINUATIONS + 1,
        was_continued=True,
        total_reasoning_tokens=total_reasoning_tokens,
    )


def parse_landing_page_output(raw: str) -> tuple[str, str, str, str]:
    match = _FRONTMATTER_REGEX.match(raw.strip())
    if not match:
        return ("", "", "", raw.strip())

    frontmatter_block = match.group(1)
    body_markdown = match.group(2).strip()

    meta_title = ""
    meta_description = ""
    slug = ""

    for line in frontmatter_block.splitlines():
        stripped = line.strip()
        if stripped.startswith("meta_title:"):
            meta_title = stripped[len("meta_title:"):].strip()
        elif stripped.startswith("meta_description:"):
            meta_description = stripped[len("meta_description:"):].strip()
        elif stripped.startswith("slug:"):
            slug = stripped[len("slug:"):].strip()

    if not meta_title or not meta_description or not slug:
        return ("", "", "", raw.strip())

    return (meta_title, meta_description, slug, body_markdown)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE))


def _strip_required_end_marker(body_markdown: str) -> str:
    stripped_body = body_markdown.rstrip()
    if not stripped_body.endswith(LANDING_PAGE_END_MARKER):
        raise LandingPageOutputValidationError("missing_end_marker")
    return stripped_body[: -len(LANDING_PAGE_END_MARKER)].rstrip()


def _count_faq_questions(body_markdown: str) -> int:
    faq_match = _FAQ_REGEX.search(body_markdown)
    if not faq_match:
        return 0
    faq_body = body_markdown[faq_match.start():]
    return len(_FAQ_QUESTION_HEADING_REGEX.findall(faq_body))


def validate_landing_page_output(
    raw: str,
    *,
    requested_length: int | None = None,
) -> tuple[str, str, str, str]:
    normalized = str(raw or "").strip()
    if not normalized:
        raise LandingPageOutputValidationError("empty_output")

    meta_title, meta_description, slug, body_markdown = parse_landing_page_output(normalized)
    if not meta_title or not meta_description or not slug:
        raise LandingPageOutputValidationError("missing_or_incomplete_frontmatter")

    body_word_count = _word_count(body_markdown)
    minimum_words = MIN_LANDING_PAGE_BODY_WORDS
    if requested_length and requested_length > 0:
        minimum_words = max(
            minimum_words,
            int(requested_length * MIN_REQUESTED_LENGTH_RATIO),
        )
    if body_word_count < minimum_words:
        raise LandingPageOutputValidationError(
            f"too_short:{body_word_count}_words_min_{minimum_words}"
        )

    if not _HEADING_REGEX.search(body_markdown):
        raise LandingPageOutputValidationError("missing_markdown_headings")

    if not _FAQ_REGEX.search(body_markdown):
        raise LandingPageOutputValidationError("missing_faq")

    faq_questions = _count_faq_questions(body_markdown)
    if faq_questions < MIN_LANDING_PAGE_FAQ_QUESTIONS:
        raise LandingPageOutputValidationError(
            f"too_few_faq_questions:{faq_questions}_min_{MIN_LANDING_PAGE_FAQ_QUESTIONS}"
        )

    body_markdown = _strip_required_end_marker(body_markdown)

    return (meta_title, meta_description, slug, body_markdown)
