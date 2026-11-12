import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from google.auth.exceptions import RefreshError
from googleapiclient.http import HttpMockSequence

from app.services.search_console import client as gsc
from app.services.search_console.client import SearchConsoleServiceError

SETTINGS = SimpleNamespace(
    gsc_client_id="id", gsc_client_secret="secret", gsc_refresh_token="token",
    gsc_request_timeout_seconds=5.0,
)


def _service(*responses):
    """Service op een reeks nep-antwoorden: (status, payload)."""
    http = HttpMockSequence([({"status": str(status)}, json.dumps(payload)) for status, payload in responses])
    return gsc.get_service(http), http


class _RaisingHttp:
    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        raise self.exc


class SearchConsoleClientTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(gsc, "settings", SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = patch("time.sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_list_sites_skips_unverified_and_sorts(self):
        service, http = _service((200, {"siteEntry": [
            {"siteUrl": "sc-domain:klant.nl", "permissionLevel": "siteOwner"},
            {"siteUrl": "https://www.ander.nl/", "permissionLevel": "siteFullUser"},
            {"siteUrl": "https://oud.nl/", "permissionLevel": "siteUnverifiedUser"},
        ]}))
        sites = gsc.list_sites(service=service)
        self.assertEqual([s["site_url"] for s in sites], ["https://www.ander.nl/", "sc-domain:klant.nl"])
        self.assertEqual(sites[1]["permission"], "siteOwner")
        self.assertTrue(http.request_sequence[0][0].endswith("/webmasters/v3/sites?alt=json"))

    def test_search_analytics_sends_body_and_encodes_domain_property(self):
        service, http = _service((200, {"rows": [
            {"keys": ["schoenen kopen"], "clicks": 12, "impressions": 340, "ctr": 0.035, "position": 7.26},
        ]}))
        rows = gsc.search_analytics(
            "sc-domain:klant.nl", date(2026, 8, 12), date(2026, 11, 9),
            dimensions=("query",), row_limit=250, service=service,
        )
        self.assertEqual(rows, [
            {"keys": ["schoenen kopen"], "clicks": 12.0, "impressions": 340.0, "ctr": 0.035, "position": 7.26},
        ])
        uri, method, body, _headers = http.request_sequence[0]
        self.assertEqual(method, "POST")
        self.assertIn("/sites/sc-domain%3Aklant.nl/searchAnalytics/query", uri)
        self.assertEqual(json.loads(body), {
            "startDate": "2026-08-12", "endDate": "2026-11-09", "type": "web",
            "rowLimit": 250, "dimensions": ["query"],
        })

    def test_search_analytics_without_data_is_empty(self):
        service, _ = _service((200, {"responseAggregationType": "byProperty"}))
        self.assertEqual(gsc.search_analytics("sc-domain:klant.nl", date(2026, 1, 1), date(2026, 1, 2),
                                              service=service), [])

    def test_list_sitemaps_converts_counts(self):
        service, _ = _service((200, {"sitemap": [{
            "path": "https://klant.nl/sitemap.xml", "lastSubmitted": "2026-10-01T10:00:00Z",
            "isPending": False, "isSitemapsIndex": True, "errors": "2", "warnings": "0",
            "contents": [{"type": "web", "submitted": "120"}, {"type": "image", "submitted": "30"}],
        }]}))
        sitemaps = gsc.list_sitemaps("sc-domain:klant.nl", service=service)
        self.assertEqual(sitemaps[0]["errors"], 2)
        self.assertEqual(sitemaps[0]["warnings"], 0)
        self.assertEqual(sitemaps[0]["submitted"], 150)
        self.assertTrue(sitemaps[0]["is_index"])

    def test_inspect_url_reads_index_status(self):
        service, http = _service((200, {"inspectionResult": {
            "inspectionResultLink": "https://search.google.com/search-console/inspect?x",
            "indexStatusResult": {
                "verdict": "NEUTRAL", "coverageState": "Gecrawld - momenteel niet geïndexeerd",
                "robotsTxtState": "ALLOWED", "indexingState": "INDEXING_ALLOWED",
                "pageFetchState": "SUCCESSFUL", "lastCrawlTime": "2026-11-01T08:00:00Z",
            },
        }}))
        row = gsc.inspect_url("sc-domain:klant.nl", "https://klant.nl/nieuw/", service=service)
        self.assertEqual(row["verdict"], "NEUTRAL")
        self.assertEqual(row["coverage_state"], "Gecrawld - momenteel niet geïndexeerd")
        self.assertEqual(row["url"], "https://klant.nl/nieuw/")
        uri, _method, body, _headers = http.request_sequence[0]
        self.assertIn("/v1/urlInspection/index:inspect", uri)
        self.assertEqual(json.loads(body), {
            "inspectionUrl": "https://klant.nl/nieuw/", "siteUrl": "sc-domain:klant.nl", "languageCode": "nl-NL",
        })

    def test_forbidden_property(self):
        service, _ = _service((403, {"error": {"code": 403, "message": "User does not have sufficient permission"}}))
        with self.assertRaises(SearchConsoleServiceError) as ctx:
            gsc.list_sitemaps("sc-domain:vreemd.nl", service=service)
        self.assertEqual(ctx.exception.code, "forbidden")
        self.assertIn("sufficient permission", str(ctx.exception))

    def test_rate_limit_after_retries(self):
        error = {"error": {"code": 429, "message": "Quota exceeded"}}
        service, http = _service((429, error), (429, error), (429, error))
        with self.assertRaises(SearchConsoleServiceError) as ctx:
            gsc.list_sites(service=service)
        self.assertEqual(ctx.exception.code, "rate_limited")
        self.assertEqual(len(http.request_sequence), 1 + gsc.NUM_RETRIES)

    def test_server_error_is_retried(self):
        service, http = _service((503, {"error": {"message": "backend"}}), (200, {"siteEntry": []}))
        self.assertEqual(gsc.list_sites(service=service), [])
        self.assertEqual(len(http.request_sequence), 2)

    def test_expired_refresh_token(self):
        service = gsc.get_service(_RaisingHttp(RefreshError("invalid_grant: Token has been expired or revoked.")))
        with self.assertRaises(SearchConsoleServiceError) as ctx:
            gsc.list_sites(service=service)
        self.assertEqual(ctx.exception.code, "token_expired")
        self.assertIn("gsc_authorize.py", str(ctx.exception))

    def test_timeout(self):
        http = _RaisingHttp(TimeoutError("timed out"))
        with self.assertRaises(SearchConsoleServiceError) as ctx:
            gsc.list_sites(service=gsc.get_service(http))
        self.assertEqual(ctx.exception.code, "timeout")
        self.assertEqual(http.calls, 1 + gsc.NUM_RETRIES)

    def test_not_configured(self):
        with patch.object(gsc, "settings", SimpleNamespace(
            gsc_client_id="id", gsc_client_secret="secret", gsc_refresh_token=" ",
            gsc_request_timeout_seconds=5.0,
        )):
            self.assertFalse(gsc.is_configured())
            with self.assertRaises(SearchConsoleServiceError) as ctx:
                gsc.list_sites()
        self.assertEqual(ctx.exception.code, "not_configured")

    def test_credentials_use_refresh_token_and_readonly_scope(self):
        self.assertTrue(gsc.is_configured())
        credentials = gsc._credentials()
        self.assertEqual(credentials.refresh_token, "token")
        self.assertEqual(credentials.client_id, "id")
        self.assertEqual(list(credentials.scopes), ["https://www.googleapis.com/auth/webmasters.readonly"])


if __name__ == "__main__":
    unittest.main()
