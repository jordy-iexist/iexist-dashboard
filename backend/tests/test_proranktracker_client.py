import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.services.proranktracker import client as prt
from app.services.proranktracker.client import ProRankTrackerServiceError

SETTINGS = SimpleNamespace(proranktracker_api_token="test-token", proranktracker_request_timeout_seconds=5.0)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok(data) -> httpx.Response:
    return httpx.Response(200, json={"result": "success", "data": data, "error_message": None})


class ProRankTrackerClientTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(prt, "settings", SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = patch.object(prt.time, "sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_visibility_report_sends_token_and_params(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["token"] = request.headers.get("X-TOKEN")
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            return _ok({"urls": [{"url_id": 7, "url": "http://klant.nl"}], "count": 20})

        data = prt.visibility_report(7, client=_client(handler))

        self.assertEqual(seen["method"], "GET")
        self.assertEqual(seen["token"], "test-token")
        self.assertEqual(seen["path"], "/v3/reports/ai/ai-visibility")
        self.assertEqual(seen["params"], {"per_page": "10000", "url_id": "7"})
        self.assertEqual(data["urls"][0]["url_id"], 7)

    def test_overview_without_url_id(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return _ok({"urls": []})

        prt.visibility_report(client=_client(handler))
        self.assertEqual(seen["params"], {"per_page": "10000"})

    def test_prompt_records_params_and_rows(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            return _ok({"url_terms": [{"engine": "AIO", "ai_type": "links"}, "rommel"]})

        rows = prt.prompt_records(7, "beste koffiekar huren", client=_client(handler))

        self.assertEqual((seen["method"], seen["path"]), ("GET", "/v3/ai/urls"))
        self.assertEqual(seen["params"], {
            "url_ids[]": "7", "term_match_type": "exact", "bulk_terms": "beste koffiekar huren", "per_page": "100",
        })
        self.assertEqual(rows, [{"engine": "AIO", "ai_type": "links"}])

    def test_quota(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v3/user/quota")
            return _ok({"package_quota": 3000, "active_terms": 2272, "remaining_terms": 728})

        self.assertEqual(prt.quota(client=_client(handler))["remaining_terms"], 728)

    def test_retries_on_429_then_succeeds(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "2"})
            return _ok({"urls": []})

        prt.visibility_report(client=_client(handler))
        self.assertEqual(len(calls), 2)
        self.sleep.assert_called_once_with(2.0)

    def test_429_until_last_attempt_is_rate_limited(self):
        with self.assertRaises(ProRankTrackerServiceError) as ctx:
            prt.visibility_report(client=_client(lambda r: httpx.Response(429)))
        self.assertEqual(ctx.exception.code, "rate_limited")
        self.assertEqual(self.sleep.call_count, prt.MAX_ATTEMPTS - 1)

    def test_401_is_unauthorized_without_retry(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(401, json={"result": "error", "error_message": "Invalid token"})

        with self.assertRaises(ProRankTrackerServiceError) as ctx:
            prt.visibility_report(client=_client(handler))
        self.assertEqual(ctx.exception.code, "unauthorized")
        self.assertIn(ctx.exception.code, prt.FATAL_CODES)
        self.assertEqual(len(calls), 1)

    def test_error_result_with_http_200(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"result": "error", "data": None, "error_message": "URL not found"})

        with self.assertRaises(ProRankTrackerServiceError) as ctx:
            prt.visibility_report(7, client=_client(handler))
        self.assertEqual(ctx.exception.code, "prt_error")
        self.assertIn("URL not found", str(ctx.exception))

    def test_partial_success_returns_data(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"result": "partial_success", "data": {"urls": [1]}})

        self.assertEqual(prt.visibility_report(client=_client(handler)), {"urls": [1]})

    def test_unreadable_and_timeout(self):
        with self.assertRaises(ProRankTrackerServiceError) as ctx:
            prt.visibility_report(client=_client(lambda r: httpx.Response(200, text="<html>")))
        self.assertEqual(ctx.exception.code, "prt_error")

        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("traag", request=request)

        with self.assertRaises(ProRankTrackerServiceError) as ctx:
            prt.visibility_report(client=_client(timeout))
        self.assertEqual(ctx.exception.code, "timeout")

    def test_not_configured_makes_no_request(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("geen request zonder token")

        with patch.object(prt, "settings", SimpleNamespace(proranktracker_api_token="  ",
                                                           proranktracker_request_timeout_seconds=5.0)):
            self.assertFalse(prt.is_configured())
            with self.assertRaises(ProRankTrackerServiceError) as ctx:
                prt.visibility_report(client=_client(handler))
        self.assertEqual(ctx.exception.code, "not_configured")
        self.assertTrue(prt.is_configured())


if __name__ == "__main__":
    unittest.main()
