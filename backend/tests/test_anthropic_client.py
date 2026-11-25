import unittest
from types import SimpleNamespace
from typing import Literal
from unittest.mock import patch

import anthropic
import httpx2
from pydantic import BaseModel

from app.services.anthropic import client as claude
from app.services.anthropic.client import AnthropicServiceError

SETTINGS = SimpleNamespace(
    anthropic_api_key="test-key", anthropic_model="claude-opus-5-5", anthropic_timeout_seconds=300.0
)
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


class PageKind(BaseModel):
    url: str
    kind: Literal["dienstpagina", "blog", "vergelijker"]


class Classification(BaseModel):
    pages: list[PageKind]


VALID_JSON = '{"pages": [{"url": "https://klant.nl/seo", "kind": "dienstpagina"}]}'


def _usage(**extra):
    base = {"input_tokens": 120, "output_tokens": 40, "cache_creation_input_tokens": None,
            "cache_read_input_tokens": None, "iterations": None}
    return SimpleNamespace(**{**base, **extra})


def _response(text=VALID_JSON, stop_reason="end_turn", usage=None, model="claude-opus-5-5", stop_details=None):
    content = [SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(
        content=content, stop_reason=stop_reason, stop_details=stop_details,
        usage=usage or _usage(), model=model,
    )


class FakeClient:
    """Nepobject met dezelfde vorm als `anthropic.Anthropic`: `.beta.messages.create(...)`."""

    def __init__(self, response=None, error=None):
        self.calls = []
        self._response = response if response is not None else _response()
        self._error = error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def _status_error(cls, status):
    return cls("nope", response=httpx2.Response(status, request=REQUEST), body=None)


def _call(client, **kwargs):
    return claude.parse_structured(
        system="Je classificeert pagina's.", prompt="Classificeer https://klant.nl/seo",
        output_model=Classification, client=client, **kwargs,
    )


class AnthropicClientTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(claude, "settings", SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_is_configured(self):
        self.assertTrue(claude.is_configured())
        with patch.object(claude, "settings", SimpleNamespace(**{**vars(SETTINGS), "anthropic_api_key": "  "})):
            self.assertFalse(claude.is_configured())

    def test_missing_key_is_not_configured_without_call(self):
        fake = FakeClient()
        with patch.object(claude, "settings", SimpleNamespace(**{**vars(SETTINGS), "anthropic_api_key": ""})):
            with self.assertRaises(AnthropicServiceError) as ctx:
                _call(fake)
        self.assertEqual(ctx.exception.code, "not_configured")
        self.assertEqual(fake.calls, [])

    def test_success_returns_parsed_usage_model_and_sends_right_arguments(self):
        fake = FakeClient(_response(usage=_usage(cache_read_input_tokens=10)))

        result = _call(fake, effort="low", max_tokens=8000)

        self.assertIsInstance(result.parsed, Classification)
        self.assertEqual(result.parsed.pages[0].kind, "dienstpagina")
        self.assertEqual(result.usage, {"input_tokens": 120, "output_tokens": 40, "cache_read_input_tokens": 10})
        self.assertEqual(result.model, "claude-opus-5-5")
        self.assertFalse(result.fallback_used)

        (kwargs,) = fake.calls
        self.assertEqual(kwargs["model"], "claude-opus-5-5")
        self.assertEqual(kwargs["max_tokens"], 8000)
        self.assertEqual(kwargs["system"], "Je classificeert pagina's.")
        self.assertEqual(kwargs["messages"], [{"role": "user", "content": "Classificeer https://klant.nl/seo"}])
        self.assertEqual(kwargs["output_config"]["effort"], "low")
        self.assertEqual(
            kwargs["output_config"]["format"],
            {"type": "json_schema", "schema": anthropic.transform_schema(Classification)},
        )
        self.assertFalse(kwargs["output_config"]["format"]["schema"]["additionalProperties"])
        self.assertEqual(kwargs["betas"], [claude.FALLBACK_BETA])
        self.assertEqual(kwargs["fallbacks"], "default")
        for forbidden in ("temperature", "top_p", "thinking", "tool_choice"):
            self.assertNotIn(forbidden, kwargs)

    def test_default_effort_is_explicit_medium(self):
        fake = FakeClient()
        _call(fake)
        self.assertEqual(fake.calls[0]["output_config"]["effort"], "medium")
        self.assertEqual(fake.calls[0]["max_tokens"], 16000)

    def test_model_override(self):
        fake = FakeClient(_response(model=None))
        result = _call(fake, model="claude-sonnet-5-5")
        self.assertEqual(fake.calls[0]["model"], "claude-sonnet-5-5")
        self.assertEqual(result.model, "claude-sonnet-5-5")  # zonder model in het antwoord: het gekozen model
        for forbidden in ("temperature", "top_p", "thinking", "tool_choice"):
            self.assertNotIn(forbidden, fake.calls[0])
        fake = FakeClient()
        _call(fake, model=None)
        self.assertEqual(fake.calls[0]["model"], "claude-opus-5-5")

    def test_cost_usd_sonnet(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 100_000}
        self.assertAlmostEqual(claude.cost_usd(usage, "claude-sonnet-5-5"), 2.0 + 1.0)
        self.assertAlmostEqual(claude.cost_usd(usage, "claude-sonnet-5"), 2.0 + 1.0)
        cached = {"cache_creation_input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}
        self.assertAlmostEqual(claude.cost_usd(cached, "claude-sonnet-5-5"), 2.5 + 0.10)
        self.assertAlmostEqual(claude.cost_usd(cached, "claude-sonnet-5"), 2.5 + 0.20)

    def test_unknown_effort_is_rejected_before_call(self):
        fake = FakeClient()
        with self.assertRaises(ValueError):
            _call(fake, effort="extreme")
        self.assertEqual(fake.calls, [])

    def test_fallback_reports_serving_model(self):
        usage = _usage(iterations=[SimpleNamespace(type="message"), SimpleNamespace(type="fallback_message")])
        result = _call(FakeClient(_response(usage=usage, model="claude-opus-5")))
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.model, "claude-opus-5")

    def test_refusal_is_error_before_content_is_read(self):
        fake = FakeClient(_response(text=None, stop_reason="refusal", stop_details=SimpleNamespace(category="cyber")))
        with self.assertRaises(AnthropicServiceError) as ctx:
            _call(fake)
        self.assertEqual(ctx.exception.code, "refusal")
        self.assertIn("cyber", ctx.exception.message)

    def test_max_tokens_is_error_even_with_truncated_json(self):
        fake = FakeClient(_response(text='{"pages": [{"url": "https://kl', stop_reason="max_tokens"))
        with self.assertRaises(AnthropicServiceError) as ctx:
            _call(fake)
        self.assertEqual(ctx.exception.code, "max_tokens")

    def test_invalid_or_missing_output(self):
        for text in ('{"pages": [{"url": "x", "kind": "webshop"}]}', "geen json", None):
            with self.assertRaises(AnthropicServiceError) as ctx:
                _call(FakeClient(_response(text=text)))
            self.assertEqual(ctx.exception.code, "invalid_output")

    def test_sdk_exceptions_map_to_codes(self):
        cases = [
            (_status_error(anthropic.AuthenticationError, 401), "unauthorized"),
            (_status_error(anthropic.PermissionDeniedError, 403), "forbidden"),
            (_status_error(anthropic.RateLimitError, 429), "rate_limited"),
            (anthropic.APITimeoutError(request=REQUEST), "timeout"),
            (anthropic.APIConnectionError(request=REQUEST), "connection_error"),
            (_status_error(anthropic.NotFoundError, 404), "anthropic_error"),
            (_status_error(anthropic.BadRequestError, 400), "anthropic_error"),
            (_status_error(anthropic.InternalServerError, 500), "anthropic_error"),
            (anthropic.AnthropicError("kapot"), "anthropic_error"),
        ]
        for error, code in cases:
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(AnthropicServiceError) as ctx:
                    _call(FakeClient(error=error))
                self.assertEqual(ctx.exception.code, code)
                self.assertNotIn("test-key", ctx.exception.message)
                self.assertNotIn("Classificeer", ctx.exception.message)

    def test_owned_client_uses_explicit_key_timeout_and_retries(self):
        fake = FakeClient()
        fake.close = lambda: fake.calls.append("closed")
        with patch.object(claude.anthropic, "Anthropic", return_value=fake) as factory:
            _call(None)
        factory.assert_called_once_with(api_key="test-key", timeout=300.0, max_retries=1)
        self.assertEqual(fake.calls[-1], "closed")

    def test_owned_client_timeout_and_retries_override(self):
        fake = FakeClient()
        fake.close = lambda: fake.calls.append("closed")
        with patch.object(claude.anthropic, "Anthropic", return_value=fake) as factory:
            _call(None, timeout=90, max_retries=0)
        factory.assert_called_once_with(api_key="test-key", timeout=90, max_retries=0)
        self.assertEqual(fake.calls[-1], "closed")
        # Alleen de override; de standaard blijft voor de volgende aanroep staan.
        with patch.object(claude.anthropic, "Anthropic", return_value=fake) as factory:
            _call(None, timeout=None, max_retries=None)
        factory.assert_called_once_with(api_key="test-key", timeout=300.0, max_retries=1)

    def test_cost_usd(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 100_000}
        self.assertAlmostEqual(claude.cost_usd(usage, "claude-opus-5-5"), 4.0 + 2.0)
        self.assertAlmostEqual(claude.cost_usd(usage), 6.0)  # standaardmodel uit settings
        self.assertAlmostEqual(claude.cost_usd(usage, "claude-opus-5"), 5.0 + 2.5)
        self.assertEqual(claude.cost_usd(usage, "onbekend-model"), 0.0)
        cached = {"input_tokens": 0, "output_tokens": 0,
                  "cache_creation_input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}
        self.assertAlmostEqual(claude.cost_usd(cached, "claude-opus-5-5"), 5.0 + 0.20)
        self.assertEqual(claude.cost_usd({}, "claude-opus-5-5"), 0.0)


if __name__ == "__main__":
    unittest.main()
