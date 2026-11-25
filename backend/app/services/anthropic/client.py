"""Claude-client (officiële `anthropic`-SDK, 2.x op httpx2), gedeeld door features.

Eén ingang: `parse_structured` stuurt een system- en gebruikersprompt naar Claude en
geeft een gevalideerd Pydantic-object terug, plus het tokenverbruik. Fouten worden
vertaald naar `AnthropicServiceError` met een `code`.

Gekozen aanroep: `client.beta.messages.create` met server-side fallbacks
(`betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`) en het JSON-schema
in `output_config.format`, niet `client.messages.parse`. Waarom:

- Fallbacks gaan wel samen met gestructureerde uitvoer: `client.beta.messages.parse`
  accepteert in SDK 2.12 zowel `fallbacks` als `output_format` (signatuur geïnspecteerd),
  en `fallbacks` werkt op hetzelfde verzoek, inclusief `output_config`.
- Maar `parse` valideert de JSON al binnen de SDK-aanroep. Bij afgekapte uitvoer
  (`stop_reason == "max_tokens"`) of een weigering halverwege gooit hij een kale pydantic-
  `ValidationError`, nog voordat wij `stop_reason` kunnen lezen. De documentatie vraagt
  juist om eerst `stop_reason` te controleren. Daarom bouwen we het schema met de publieke
  helper `anthropic.transform_schema` (precies wat `parse` intern doet), lezen eerst
  `stop_reason` en valideren daarna zelf met `output_model.model_validate_json`.

Met `fallbacks="default"` draait Anthropic een door de veiligheidsclassifier geweigerd
verzoek opnieuw op een aanbevolen model (vanaf Opus 5.5: Opus 5 / Opus 4.8; vanaf Sonnet 5.5
bijvoorbeeld Sonnet 5). `AnthropicResult.model` is dan het model dat werkelijk antwoordde;
reken de kosten met dat model.

Standaardmodel: `settings.anthropic_model`; een feature kan per aanroep een ander model
kiezen met `model=` (de content brief gebruikt `settings.content_brief_model`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import anthropic
import pydantic
from pydantic import BaseModel

from app.core.config import settings

FALLBACK_BETA = "server-side-fallback-2026-07-01"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
MAX_RETRIES = 1

# Tarieven in USD per miljoen tokens. `cache_write` is de prijs van een 5-minuten-cache-
# write; `cache_read` die van een cache-hit. Opus 5 / Opus 4.8 en Sonnet 5 staan erin omdat
# server-side fallbacks daarop kunnen uitkomen.
PRICES_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_write": 5.0, "cache_read": 0.20},
    "claude-opus-5": {"input": 5.0, "output": 25.0, "cache_write": 6.25, "cache_read": 0.50},
    "claude-opus-4-8": {"input": 5.0, "output": 25.0, "cache_write": 6.25, "cache_read": 0.50},
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_write": 2.5, "cache_read": 0.10},
    "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_write": 2.5, "cache_read": 0.20},
}

_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


class AnthropicServiceError(Exception):
    def __init__(self, message: str, code: str = "anthropic_error"):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class AnthropicResult:
    """Antwoord van één aanroep: het gevalideerde object, het verbruik en het model dat antwoordde."""

    parsed: BaseModel
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""
    fallback_used: bool = False


def is_configured() -> bool:
    return bool(settings.anthropic_api_key.strip())


def _make_client(*, timeout: float | None = None, max_retries: int | None = None) -> anthropic.Anthropic:
    """Nieuwe client. Zonder `timeout`/`max_retries`: `settings.anthropic_timeout_seconds` en
    `MAX_RETRIES` (het gedrag van de worker-taken)."""
    # Altijd een expliciete sleutel: een kale `Anthropic()` pakt ook andere credentials op
    # (ANTHROPIC_AUTH_TOKEN, een `ant auth login`-profiel).
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key.strip(),
        timeout=settings.anthropic_timeout_seconds if timeout is None else timeout,
        max_retries=MAX_RETRIES if max_retries is None else max_retries,
    )


def _status_detail(exc: anthropic.APIStatusError) -> str:
    return f"HTTP {exc.status_code}: {str(exc.message)[:300]}"


def _translate_error(exc: anthropic.AnthropicError) -> AnthropicServiceError:
    """Vertaal een SDK-uitzondering naar een `AnthropicServiceError`, van specifiek naar algemeen."""
    if isinstance(exc, anthropic.AuthenticationError):
        return AnthropicServiceError("Anthropic weigert de API-key (ongeldig of ingetrokken).", "unauthorized")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return AnthropicServiceError(
            f"Anthropic staat deze aanvraag niet toe ({_status_detail(exc)}).", "forbidden"
        )
    if isinstance(exc, anthropic.RateLimitError):
        # Ook een bereikte maandlimiet (spend cap) is een 429.
        return AnthropicServiceError(
            f"Anthropic-limiet bereikt, probeer het later opnieuw ({_status_detail(exc)}).", "rate_limited"
        )
    if isinstance(exc, (anthropic.APITimeoutError, anthropic.RequestTimeoutError)):
        return AnthropicServiceError("Timeout bij wachten op Claude.", "timeout")
    if isinstance(exc, anthropic.APIConnectionError):
        return AnthropicServiceError("Kon geen verbinding maken met Anthropic.", "connection_error")
    if isinstance(exc, anthropic.NotFoundError):
        return AnthropicServiceError(
            f"Model of endpoint niet gevonden bij Anthropic ({_status_detail(exc)}).", "anthropic_error"
        )
    if isinstance(exc, anthropic.BadRequestError):
        return AnthropicServiceError(f"Ongeldig verzoek aan Claude ({_status_detail(exc)}).", "anthropic_error")
    if isinstance(exc, anthropic.APIStatusError):
        return AnthropicServiceError(f"Anthropic-fout ({_status_detail(exc)}).", "anthropic_error")
    return AnthropicServiceError(f"Anthropic-fout: {type(exc).__name__}.", "anthropic_error")


def _usage(usage: Any) -> dict[str, int]:
    """Tokentellers van het antwoord; cache-tellers alleen als de API ze meestuurt."""
    result: dict[str, int] = {}
    for name in _USAGE_FIELDS:
        value = getattr(usage, name, None)
        if isinstance(value, int):
            result[name] = value
    return result


def _fallback_used(usage: Any) -> bool:
    return any(getattr(entry, "type", None) == "fallback_message" for entry in getattr(usage, "iterations", None) or [])


def _output_text(content: Any) -> str | None:
    texts = [block.text for block in content or [] if getattr(block, "type", None) == "text" and block.text.strip()]
    return texts[-1] if texts else None


def parse_structured(
    *,
    system: str,
    prompt: str,
    output_model: type[BaseModel],
    effort: str = "medium",
    max_tokens: int = 16000,
    model: str | None = None,
    client: Any = None,
    timeout: float | None = None,
    max_retries: int | None = None,
) -> AnthropicResult:
    """Vraag Claude om een antwoord in de vorm van `output_model` en valideer het.

    `effort` regelt hoe diep het model nadenkt (`low`/`medium`/`high`/`xhigh`/`max`); thinking
    staat op dit model altijd aan en telt mee in `max_tokens`. `model`: None = het
    standaardmodel (`settings.anthropic_model`). `client` is alleen voor tests.

    `timeout` (seconden) en `max_retries`: None = `settings.anthropic_timeout_seconds` en
    `MAX_RETRIES`. Een synchroon endpoint kiest hier een kortere grens en geen herkansing,
    zodat de gebruiker niet minutenlang wacht. Gelden alleen voor een eigen client (niet
    als `client` is meegegeven).

    Eisen aan `output_model` (het schema gaat via `anthropic.transform_schema` naar de API):
    - Elk object krijgt `additionalProperties: false`; extra velden kan Claude dus niet sturen.
    - Velden met een default zijn niet `required`: Claude mag ze weglaten. Wil je een veld
      altijd terug, geef het dan geen default (een nullable veld: `x: str | None`, zonder `= None`).
    - Numerieke grenzen (`ge`/`le`/`gt`/`lt`/`multiple_of`), `min_length`/`max_length`/`pattern`
      op strings en `min_items` groter dan 1 / `max_items` op lijsten worden NIET afgedwongen:
      de SDK verplaatst ze naar de veldbeschrijving. Pydantic controleert ze achteraf wel, dus
      een overschrijding wordt een `invalid_output`-fout. Gebruik ze niet; valideer zelf na afloop.
    - Gebruik `Literal[...]`/`Enum` voor vaste keuzes (wordt een `enum` en wel afgedwongen).
    - Ondersteunde stringformaten: date-time, time, date, duration, email, hostname, uri,
      ipv4, ipv6, uuid; andere formaten worden een hint in de beschrijving.
    - Geneste modellen, lijsten en `X | None` mogen; de root moet een object (BaseModel) zijn.
    - Veldbeschrijvingen (`Field(description=...)`) gaan mee naar het model: gebruik ze als instructie.
    """
    if effort not in EFFORT_LEVELS:
        raise ValueError(f"Onbekend effort-niveau: {effort!r}")
    if not is_configured():
        raise AnthropicServiceError(
            "Claude is niet gekoppeld: ANTHROPIC_API_KEY ontbreekt in de backend-configuratie.",
            code="not_configured",
        )

    chosen_model = model or settings.anthropic_model
    output_format = {"type": "json_schema", "schema": anthropic.transform_schema(output_model)}
    owns_client = client is None
    api = client or _make_client(timeout=timeout, max_retries=max_retries)
    try:
        response = api.beta.messages.create(
            model=chosen_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort, "format": output_format},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.AnthropicError as exc:
        raise _translate_error(exc) from exc
    finally:
        if owns_client:
            api.close()

    # Eerst `stop_reason`, pas daarna de inhoud.
    if response.stop_reason == "refusal":
        category = getattr(getattr(response, "stop_details", None), "category", None)
        detail = f" (categorie: {category})" if category else ""
        raise AnthropicServiceError(f"Claude weigerde dit verzoek{detail}.", code="refusal")
    if response.stop_reason == "max_tokens":
        raise AnthropicServiceError(
            f"Het antwoord van Claude is afgekapt op max_tokens={max_tokens}; verhoog de limiet of verlaag effort.",
            code="max_tokens",
        )

    text = _output_text(response.content)
    if text is None:
        raise AnthropicServiceError("Claude gaf geen tekstantwoord terug.", code="invalid_output")
    try:
        parsed = output_model.model_validate_json(text)
    except pydantic.ValidationError as exc:
        raise AnthropicServiceError(
            f"Het antwoord van Claude past niet in {output_model.__name__} ({exc.error_count()} fout(en)).",
            code="invalid_output",
        ) from exc

    return AnthropicResult(
        parsed=parsed,
        usage=_usage(response.usage),
        model=str(response.model or chosen_model),
        fallback_used=_fallback_used(response.usage),
    )


def cost_usd(usage: dict[str, Any], model: str | None = None) -> float:
    """Kosten in USD van één aanroep; onbekend model geeft 0.0.

    Rekent cache-writes tegen het 5-minutentarief. Bij een server-side fallback telt
    `usage` alleen de poging die antwoordde (geef dan `AnthropicResult.model` mee).
    """
    prices = PRICES_PER_MTOK.get(model or settings.anthropic_model)
    if not prices:
        return 0.0
    total = (
        usage.get("input_tokens", 0) * prices["input"]
        + usage.get("output_tokens", 0) * prices["output"]
        + (usage.get("cache_creation_input_tokens") or 0) * prices["cache_write"]
        + (usage.get("cache_read_input_tokens") or 0) * prices["cache_read"]
    )
    return round(total / 1_000_000, 6)
