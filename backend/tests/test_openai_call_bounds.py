"""Livegang-scans begrenzen één OpenAI-aanroep; de gedeelde client houdt de SDK-standaard."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from openai import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT, OpenAI
from openai.resources.responses import Responses

from app.agents.base import Agent, run_agent
from app.core.config import settings
from app.features.launch_checklist.services import page_types
from app.features.launch_checklist.services.scan_recovery import STALE_SCAN_AFTER
from app.services.openai import client as openai_client


def _fake_client(_user_id: str) -> OpenAI:
    return OpenAI(api_key="test")


class OpenAICallBoundsTest(unittest.TestCase):
    def setUp(self):
        self.seen: list[tuple[object, int]] = []

    def _record(self, output_text: str):
        def create(responses_self, **_kwargs):
            # De client waarop de aanroep echt gebeurt (na with_options).
            self.seen.append((responses_self._client.timeout, responses_self._client.max_retries))
            return SimpleNamespace(output=[], output_text=output_text, usage=None)
        return create

    def test_worst_case_stays_well_under_stale_threshold(self):
        # Eén aanroep (incl. herhaling) blijft ruim onder de grens van de herstelcheck.
        worst = (1 + settings.launch_scan_openai_max_retries) * settings.launch_scan_openai_timeout_seconds
        self.assertLessEqual(worst, 10 * 60)
        self.assertLess(worst * 2, STALE_SCAN_AFTER.total_seconds())

    def test_run_agent_step_is_bounded(self):
        agent = Agent(name="test", instructions="", tools=[], model="gpt-4.1")
        with patch("app.agents.base._build_openai_client", _fake_client), \
                patch.object(Responses, "create", autospec=True, side_effect=self._record("klaar")):
            result = run_agent(agent, user_id="u", input="hoi", context=None)
        self.assertEqual(result.output, "klaar")
        self.assertEqual(self.seen, [(settings.launch_scan_openai_timeout_seconds, settings.launch_scan_openai_max_retries)])

    def test_page_type_classification_is_bounded(self):
        with patch.object(openai_client, "_build_openai_client", _fake_client), \
                patch.object(Responses, "create", autospec=True, side_effect=self._record('{"1": "blog"}')), \
                patch.object(openai_client, "response_output_text", lambda r: r.output_text):
            out = page_types.classify_with_llm([{"id": 1, "url": "https://x.nl/blog/a/"}], user_id="u")
        self.assertEqual(out, {"1": "blog"})
        self.assertEqual(self.seen, [(settings.launch_scan_openai_timeout_seconds, settings.launch_scan_openai_max_retries)])

    def test_shared_client_keeps_sdk_defaults(self):
        # Blog- en landingspaginageneratie gebruiken deze client ongewijzigd.
        with patch.object(openai_client, "resolve_openai_api_key_for_user", return_value="test"):
            shared = openai_client._build_openai_client("u")
        self.assertEqual((shared.timeout, shared.max_retries), (DEFAULT_TIMEOUT, DEFAULT_MAX_RETRIES))


if __name__ == "__main__":
    unittest.main()
