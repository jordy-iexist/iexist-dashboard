import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.services.ahrefs import client as ahrefs
from app.services.ahrefs.client import AhrefsServiceError

SETTINGS = SimpleNamespace(ahrefs_api_key="test-key", ahrefs_request_timeout_seconds=5.0)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class AhrefsClientTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(ahrefs, "settings", SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = patch.object(ahrefs.time, "sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_top_pages_sends_bearer_and_params_and_reads_units(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers["Authorization"]
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            return httpx.Response(
                200,
                json={"pages": [{"url": "https://klant.nl/a", "sum_traffic": 120}]},
                headers={"x-api-units-cost-total-actual": "4800", "x-api-cache": "miss"},
            )

        result = ahrefs.top_pages(
            "klant.nl", country="nl", limit=200, on_date=date(2026, 11, 11), client=_client(handler)
        )

        self.assertEqual(seen["auth"], "Bearer test-key")
        self.assertEqual(seen["path"], "/v3/site-explorer/top-pages")
        self.assertEqual(seen["params"]["target"], "klant.nl")
        self.assertEqual(seen["params"]["mode"], "subdomains")
        self.assertEqual(seen["params"]["date"], "2026-11-11")
        self.assertEqual(seen["params"]["country"], "nl")
        self.assertEqual(seen["params"]["limit"], "200")
        self.assertEqual(seen["params"]["order_by"], "sum_traffic:desc")
        self.assertIn("top_keyword_best_position", seen["params"]["select"])
        self.assertEqual(result.rows, [{"url": "https://klant.nl/a", "sum_traffic": 120}])
        self.assertEqual(result.units, 4800)
        self.assertFalse(result.cached)

    def test_domain_overview_posts_single_target(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"targets": [{"domain_rating": 34.0, "refdomains": 210, "org_traffic": 1800, "extra": 1}]},
                headers={"x-api-units-cost-total-actual": "50"},
            )

        result = ahrefs.domain_overview("klant.nl", country="nl", client=_client(handler))

        self.assertEqual((seen["method"], seen["path"]), ("POST", "/v3/batch-analysis/batch-analysis"))
        self.assertEqual(seen["body"]["targets"], [{"url": "klant.nl", "mode": "subdomains", "protocol": "both"}])
        self.assertEqual(seen["body"]["country"], "nl")
        self.assertEqual(result.data["domain_rating"], 34.0)
        self.assertEqual(result.data["refdomains"], 210)
        self.assertNotIn("extra", result.data)
        self.assertEqual(result.units, 50)

    def test_broken_backlinks_and_pages_by_backlinks_use_their_own_keys(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/broken-backlinks"):
                self.assertEqual(request.url.params["aggregation"], "1_per_domain")
                return httpx.Response(200, json={"backlinks": [{"url_to": "https://klant.nl/oud"}]})
            self.assertEqual(request.url.params["history"], "live")
            return httpx.Response(200, json={"pages": [{"url_to": "https://klant.nl/a"}]})

        client = _client(handler)
        self.assertEqual(ahrefs.broken_backlinks("klant.nl", client=client).rows, [{"url_to": "https://klant.nl/oud"}])
        self.assertEqual(ahrefs.pages_by_backlinks("klant.nl", client=client).rows, [{"url_to": "https://klant.nl/a"}])

    def test_rate_limit_retries_then_succeeds(self):
        calls = []

        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "2"})
            return httpx.Response(200, json={"pages": []})

        result = ahrefs.pages_by_backlinks("klant.nl", client=_client(handler))

        self.assertEqual(result.rows, [])
        self.assertEqual(len(calls), 2)
        self.sleep.assert_called_once_with(2.0)

    def test_rate_limit_gives_up_after_max_attempts(self):
        with self.assertRaises(AhrefsServiceError) as ctx:
            ahrefs.pages_by_backlinks("klant.nl", client=_client(lambda r: httpx.Response(429)))
        self.assertEqual(ctx.exception.code, "rate_limited")
        self.assertEqual(self.sleep.call_count, ahrefs.MAX_ATTEMPTS - 1)

    def test_error_statuses_map_to_codes(self):
        cases = {401: "unauthorized", 403: "forbidden", 400: "ahrefs_error"}
        for status, code in cases.items():
            with self.assertRaises(AhrefsServiceError) as ctx:
                ahrefs.limits_and_usage(
                    client=_client(lambda r, s=status: httpx.Response(s, json={"error": "nope"}))
                )
            self.assertEqual(ctx.exception.code, code)
        self.assertIn("nope", str(ctx.exception))

    def test_missing_key_is_not_configured(self):
        with patch.object(ahrefs, "settings", SimpleNamespace(ahrefs_api_key=" ", ahrefs_request_timeout_seconds=5.0)):
            self.assertFalse(ahrefs.is_configured())
            with self.assertRaises(AhrefsServiceError) as ctx:
                ahrefs.limits_and_usage(client=_client(lambda r: httpx.Response(200, json={})))
        self.assertEqual(ctx.exception.code, "not_configured")

    def test_limits_and_usage_unwraps_payload(self):
        payload = {"limits_and_usage": {"subscription": "Standard", "units_usage_workspace": 1200}}
        data = ahrefs.limits_and_usage(client=_client(lambda r: httpx.Response(200, json=payload)))
        self.assertEqual(data["subscription"], "Standard")


if __name__ == "__main__":
    unittest.main()
