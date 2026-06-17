import re

import httpx
from openai import OpenAI

from app.features.settings.services import require_personal_openai_api_key_for_user


def model_supports_reasoning(model: str) -> bool:
    """Reasoning-effort wordt alleen ondersteund door gpt-5* en o-serie modellen."""
    normalized = (model or "").strip().lower()
    return normalized.startswith("gpt-5") or bool(re.match(r"^o\d", normalized))


def _build_openai_client(user_id: str) -> OpenAI:
    api_key = require_personal_openai_api_key_for_user(user_id)
    return OpenAI(api_key=api_key)


def create_response(
    *,
    user_id: str,
    model: str,
    input: str,
    instructions: str | None = None,
    max_output_tokens: int | None = None,
    tools: list[dict[str, object]] | None = None,
    tool_choice: dict[str, object] | None = None,
    reasoning: dict[str, object] | None = None,
):
    payload: dict[str, object] = {
        "model": model,
        "input": input,
    }
    if instructions is not None:
        payload["instructions"] = instructions
    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens
    if tools is not None:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if reasoning is not None:
        payload["reasoning"] = reasoning
    client = _build_openai_client(user_id)
    return client.responses.create(**payload)


def create_image(
    *,
    user_id: str,
    model: str,
    prompt: str,
    size: str,
    n: int = 1,
    quality: str | None = None,
    output_format: str | None = None,
    output_compression: int | None = None,
):
    client = _build_openai_client(user_id)
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "n": n,
    }
    if quality:
        payload["quality"] = quality
    normalized_format = (output_format or "").strip().lower()
    if normalized_format:
        payload["output_format"] = normalized_format
    # output_compression only applies to jpeg/webp, not png.
    if output_compression is not None and normalized_format in {"jpeg", "webp"}:
        payload["output_compression"] = output_compression
    return client.images.generate(**payload)


def response_output_text(response) -> str:
    return response.output_text


def download_binary(url: str, *, timeout: float = 60.0) -> httpx.Response:
    response = httpx.get(str(url), timeout=timeout)
    response.raise_for_status()
    return response
