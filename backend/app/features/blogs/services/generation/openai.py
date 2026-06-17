import base64

from app.core.config import settings
from app.services.openai import (
    create_image,
    create_response,
    download_binary,
    model_supports_reasoning,
)

SYSTEM_PROMPT = (
"""
Je bent een ervaren SEO-copywriter die Nederlandstalige blogartikelen schrijft. Je schrijft voor zowel zoekmachines als menselijke lezers — ranking zonder leesbaarheid op te offeren.

## Structuur
- **H1**: bevat het primaire zoekwoord, max 60 tekens, prikkelt tot doorlezen. Geen clickbait.
- **Intro (50–100 woorden)**: benoem het probleem, beloof de oplossing, primair zoekwoord in de eerste zin of alinea. Geen "In dit artikel bespreken we…" — direct ter zake.
- **H2/H3 hiërarchie**: logisch en scanbaar. Semantische varianten van het zoekwoord verwerken waar dat natuurlijk valt.
- **Body**: informatief, diepgaand, goed onderbouwd. Gebruik voorbeelden, data en concrete details om je punten te illustreren. Vermijd vage beweringen.

## SEO-principes
- **Search intent first**: match het format aan wat er ranked voor het keyword (lijst, gids, vergelijking, definitie). Schrijf geen how-to als de SERP listicles toont.
- **Keyword density**: natuurlijk. Primair keyword ~0,5–1,5%. Forceer niets.
- **Semantische dekking**: behandel gerelateerde subtopics en entities die Google verwacht bij dit onderwerp.
- **E-E-A-T**: laat ervaring, expertise en autoriteit zien via concrete voorbeelden, cijfers en specifieke nuances in plaats van vage algemeenheden.
- **Featured snippet-kansen**: bij geschikte vragen lever je een directe, definitiegerichte alinea van 40–60 woorden onder een H2/H3-vraag.

## Schrijfstijl
- Helder, direct Nederlands. Geen anglicismen tenzij het vakjargon van de doelgroep is.
- Actieve zinnen boven passieve. Korte zinnen wisselen met iets langere voor ritme.
- Tweede persoon (je/jij) tenzij het merk anders voorschrijft.
- Geen fluff: schrap zinnen als "in de wereld van vandaag", "het is geen geheim dat", "in dit snel veranderende landschap". Elke zin moet iets toevoegen.
- Geen AI-tells: vermijd "duik in", "ontgrendel", "in het rijk van", overdreven drieslagen ("snel, efficiënt en betrouwbaar") en samenvattende slotalinea's die niets nieuws zeggen.
- Concreet boven abstract: vervang "veel bedrijven" door een getal of voorbeeld waar mogelijk.

## Wat je niet doet
- Geen verzonnen statistieken, citaten of bronnen. Als je een cijfer noemt dat je niet zeker weet, markeer het met [bron nodig].
- Geen zoekwoord-herhaling in elke kop.
- Geen emoji's tenzij expliciet gevraagd.
- Geen meta-commentaar in het artikel ("zoals we eerder zagen…" alleen waar het echt nodig is).

Lever het artikel in Markdown.
"""
)


def generate_blog(
    prompt: str,
    *,
    user_id: str,
    system_prompt: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    max_output_tokens: int | None = None,
) -> str:
    effective_model = model or settings.openai_blog_model
    reasoning = (
        {"effort": reasoning_effort or settings.openai_blog_reasoning_effort}
        if model_supports_reasoning(effective_model)
        else None
    )
    response = create_response(
        user_id=user_id,
        model=effective_model,
        instructions=system_prompt or SYSTEM_PROMPT,
        input=prompt,
        max_output_tokens=max_output_tokens
        if max_output_tokens is not None
        else settings.openai_blog_max_output_tokens,
        reasoning=reasoning,
    )
    return str(getattr(response, "output_text", "") or "").strip()


def _mime_type_from_format(raw_format: str | None) -> str:
    normalized = (raw_format or "").strip().lower()
    if normalized in {"jpeg", "jpg"}:
        return "image/jpeg"
    if normalized == "webp":
        return "image/webp"
    return "image/png"


def _mime_type_from_url(url: str) -> str:
    lowered = url.lower()
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".webp"):
        return "image/webp"
    return "image/png"


def _generate_blog_image_with_responses_api(
    prompt: str,
    *,
    user_id: str,
    size: str | None = None,
    output_format: str | None = None,
    output_compression: int | None = None,
) -> tuple[bytes, str, str | None]:
    fmt = (output_format or settings.openai_image_output_format or "").strip().lower()
    compression = (
        output_compression
        if output_compression is not None
        else settings.openai_image_output_compression
    )
    output_options: dict = {}
    if fmt:
        output_options["output_format"] = fmt
    if fmt in {"jpeg", "webp"} and compression is not None:
        output_options["output_compression"] = compression

    tools_with_size = [
        {
            "type": "image_generation",
            "size": size or settings.openai_image_size,
            **output_options,
        }
    ]
    tools_without_size = [
        {
            "type": "image_generation",
            **output_options,
        }
    ]
    attempts = [tools_with_size, tools_without_size]
    response = None
    last_error: Exception | None = None

    for tools in attempts:
        try:
            response = create_response(
                user_id=user_id,
                model=settings.openai_image_responses_model,
                input=prompt,
                tools=tools,
                tool_choice={"type": "image_generation"},
            )
            break
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            if "unknown parameter" in message and "size" in message:
                continue
            raise

    if response is None:
        raise ValueError(f"Responses API call mislukt: {last_error}")

    outputs = getattr(response, "output", None) or []
    for output in outputs:
        if getattr(output, "type", None) != "image_generation_call":
            continue

        image_base64 = getattr(output, "result", None)
        if not image_base64:
            continue

        image_bytes = base64.b64decode(image_base64)
        mime_type = _mime_type_from_format(getattr(output, "output_format", None))
        revised_prompt = getattr(output, "revised_prompt", None)
        return image_bytes, mime_type, revised_prompt

    raise ValueError("Responses API gaf geen image_generation output terug.")


def _generate_blog_image_with_images_api(
    prompt: str,
    *,
    user_id: str,
    size: str | None = None,
    model: str | None = None,
    quality: str | None = None,
    output_format: str | None = None,
    output_compression: int | None = None,
) -> tuple[bytes, str, str | None]:
    effective_quality = quality or settings.openai_image_quality
    response = create_image(
        user_id=user_id,
        model=model or settings.openai_image_model,
        prompt=prompt,
        size=size or settings.openai_image_size,
        n=1,
        quality=effective_quality if effective_quality != "auto" else None,
        output_format=output_format or settings.openai_image_output_format,
        output_compression=(
            output_compression
            if output_compression is not None
            else settings.openai_image_output_compression
        ),
    )

    data = response.data or []
    first = data[0] if data else None
    if not first:
        raise ValueError("Images API gaf geen data terug.")

    b64_json = getattr(first, "b64_json", None)
    revised_prompt = getattr(first, "revised_prompt", None)
    output_format = getattr(first, "output_format", None)
    if b64_json:
        return (
            base64.b64decode(b64_json),
            _mime_type_from_format(output_format),
            revised_prompt,
        )

    image_url = getattr(first, "url", None)
    if not image_url:
        raise ValueError("Images API gaf geen b64_json of url terug.")

    image_response = download_binary(str(image_url), timeout=60.0)
    header_content_type = image_response.headers.get("content-type", "")
    mime_type = (
        header_content_type.split(";")[0].strip().lower()
        if header_content_type.startswith("image/")
        else _mime_type_from_url(str(image_url))
    )
    return image_response.content, mime_type, revised_prompt


def generate_blog_image(
    prompt: str,
    *,
    user_id: str,
    size: str | None = None,
    model: str | None = None,
    quality: str | None = None,
    output_format: str | None = None,
    output_compression: int | None = None,
) -> tuple[bytes, str, str | None]:
    errors: list[str] = []

    # Images API is primary so user-configured model/size/quality take effect.
    try:
        return _generate_blog_image_with_images_api(
            prompt,
            user_id=user_id,
            size=size,
            model=model,
            quality=quality,
            output_format=output_format,
            output_compression=output_compression,
        )
    except Exception as exc:
        errors.append(str(exc))

    # Responses API fallback honours size/output format only (no custom model/quality).
    try:
        return _generate_blog_image_with_responses_api(
            prompt,
            user_id=user_id,
            size=size,
            output_format=output_format,
            output_compression=output_compression,
        )
    except Exception as exc:
        errors.append(str(exc))

    raise ValueError(
        "Image generatie mislukt. Images API fout: "
        f"{errors[0] if errors else 'onbekend'}. "
        "Responses API fout: "
        f"{errors[1] if len(errors) > 1 else 'onbekend'}."
    )
