"""Bing Webmaster-client: aanmelding (API-key of OAuth), foutcodes en het lezen van de responses.

De voorbeeldresponses hebben de vorm van echte antwoorden van Bing (november 2026).
"""
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx

from app.services.bing_webmaster import client as bing
from app.services.bing_webmaster.client import BingAuth, BingWebmasterServiceError

SETTINGS = SimpleNamespace(
    bing_client_id="client-id",
    bing_client_secret="client-secret",
    bing_webmaster_redirect_uri="https://app.iexist.nl/api/bing-webmaster/callback",
    bing_webmaster_api_key="",
    bing_webmaster_request_timeout_seconds=5.0,
)
KEY = BingAuth(api_key="geheime-key")
TOKEN = BingAuth(access_token="access-token")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _d(rows):
    return lambda request: httpx.Response(200, json={"d": rows})


class BingClientTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(bing, "settings", SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = patch.object(bing.time, "sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_api_key_goes_in_query_and_oauth_in_header(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((dict(request.url.params), request.headers.get("Authorization"), request.url.path))
            return httpx.Response(200, json={"d": []})

        bing.feeds(KEY, "https://www.klant.nl/", client=_client(handler))
        bing.feeds(TOKEN, "https://www.klant.nl/", client=_client(handler))

        self.assertEqual(seen[0][0], {"siteUrl": "https://www.klant.nl/", "apikey": "geheime-key"})
        self.assertIsNone(seen[0][1])
        self.assertEqual(seen[0][2], "/webmaster/api.svc/json/GetFeeds")
        self.assertEqual(seen[1][0], {"siteUrl": "https://www.klant.nl/"})
        self.assertEqual(seen[1][1], "Bearer access-token")

    def test_missing_auth_is_not_connected(self):
        with self.assertRaises(BingWebmasterServiceError) as ctx:
            bing.list_sites(BingAuth(), client=_client(_d([])))
        self.assertEqual(ctx.exception.code, "not_connected")

    def test_list_sites_drops_verification_codes(self):
        rows = [
            {"__type": "Site:#Microsoft.Bing.Webmaster.Api", "AuthenticationCode": "ABC", "DnsVerificationCode": "def",
             "IsVerified": True, "Url": "https://www.klant.nl/"},
            {"IsVerified": False, "Url": "https://nieuw.nl/"},
        ]
        sites = bing.list_sites(KEY, client=_client(_d(rows)))
        self.assertEqual(sites, [
            {"url": "https://www.klant.nl/", "verified": True},
            {"url": "https://nieuw.nl/", "verified": False},
        ])

    def test_error_codes(self):
        cases = {
            3: "unauthorized",       # InvalidApiKey
            18: "unauthorized",      # InvalidToken
            14: "site_not_found",    # NotAuthorized: site staat niet in het account
            4: "rate_limited",
            99: "bing_error",
        }
        for error_code, expected in cases.items():
            def handler(request, error_code=error_code):
                return httpx.Response(400, json={"ErrorCode": error_code, "Message": "ERROR!!! Iets"})

            with self.assertRaises(BingWebmasterServiceError) as ctx:
                bing.crawl_stats(KEY, "https://www.klant.nl/", client=_client(handler))
            self.assertEqual(ctx.exception.code, expected, error_code)
            self.assertNotIn("ERROR!!!", str(ctx.exception))

    def test_server_error_is_retried(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"d": []})

        self.assertEqual(bing.feeds(KEY, "https://www.klant.nl/", client=_client(handler)), [])
        self.assertEqual(len(calls), 3)

        with self.assertRaises(BingWebmasterServiceError) as ctx:
            bing.feeds(KEY, "https://www.klant.nl/", client=_client(lambda r: httpx.Response(500)))
        self.assertEqual(ctx.exception.code, "bing_error")

    def test_dates(self):
        self.assertEqual(bing.parse_date("/Date(1778889600000)/"), date(2026, 5, 16))
        self.assertEqual(bing.parse_date("/Date(1778889600000-0700)/"), date(2026, 5, 16))
        self.assertIsNone(bing.parse_date("2026-05-16"))
        self.assertIsNone(bing.parse_date(None))

    def test_crawl_stats_are_sorted_and_mapped(self):
        rows = [
            {"Date": "/Date(1794528000000)/", "InIndex": 114, "InLinks": 27688, "CrawledPages": 62, "CrawlErrors": 2,
             "Code2xx": 155, "Code301": 65, "Code302": 0, "Code4xx": 2, "Code5xx": 0, "AllOtherCodes": 8,
             "BlockedByRobotsTxt": 0, "DnsFailures": 0, "ConnectionTimeout": 0, "ContainsMalware": 0},
            {"Date": "/Date(1778889600000)/", "InIndex": 97, "CrawledPages": 21},
            {"Date": "kapot", "InIndex": 1},
        ]
        stats = bing.crawl_stats(KEY, "https://www.klant.nl/", client=_client(_d(rows)))
        self.assertEqual([r["date"] for r in stats], [date(2026, 5, 16), date(2026, 11, 13)])
        self.assertEqual(stats[1]["in_index"], 114)
        self.assertEqual(stats[1]["code_4xx"], 2)
        self.assertEqual(stats[0]["code_5xx"], 0)

    def test_crawl_issue_flags(self):
        self.assertEqual([i["key"] for i in bing.decode_crawl_issues(4 | 16)], ["code_4xx", "blocked_by_robots"])
        self.assertEqual(bing.decode_crawl_issues(0), [])
        self.assertEqual(bing.decode_crawl_issues("Code5xx"), [{"key": "Code5xx", "label": "Code5xx"}])
        rows = [{"Url": "https://www.klant.nl/weg", "HttpCode": 404, "InLinks": 3, "Issues": 4}]
        issues = bing.crawl_issues(KEY, "https://www.klant.nl/", client=_client(_d(rows)))
        self.assertEqual(issues[0]["http_code"], 404)
        self.assertEqual(issues[0]["issues"], [{"key": "code_4xx", "label": "4xx-fout"}])

    def test_feeds_and_stats(self):
        feed = {"Compressed": False, "FileSize": 1085, "LastCrawled": "/Date(1794816312000)/", "Status": "Success",
                "Submitted": "/Date(1794816311139)/", "Type": "Sitemap Index",
                "Url": "https://www.klant.nl/sitemap_index.xml", "UrlCount": 4}
        feeds = bing.feeds(KEY, "https://www.klant.nl/", client=_client(_d([feed])))
        self.assertEqual(feeds[0]["status"], "Success")
        self.assertEqual(feeds[0]["url_count"], 4)
        self.assertTrue(feeds[0]["last_crawled"].startswith("2026-11-16"))

        traffic = [{"Clicks": 1, "Date": "/Date(1794614400000)/", "Impressions": 7},
                   {"Clicks": 0, "Date": "/Date(1754006400000)/", "Impressions": 3}]
        rows = bing.traffic_stats(KEY, "https://www.klant.nl/", client=_client(_d(traffic)))
        self.assertEqual([(r["date"], r["clicks"], r["impressions"]) for r in rows],
                         [(date(2025, 8, 1), 0, 3), (date(2026, 11, 14), 1, 7)])

        queries = [{"AvgClickPosition": -1, "AvgImpressionPosition": 7, "Clicks": 0, "Date": "/Date(1755216000000)/",
                    "Impressions": 9, "Query": "online marketing bureau"},
                   {"AvgImpressionPosition": -1, "Clicks": 0, "Date": "/Date(1755216000000)/", "Impressions": 1,
                    "Query": "zonder positie"}]
        rows = bing.query_stats(KEY, "https://www.klant.nl/", client=_client(_d(queries)))
        self.assertEqual(rows[0]["key"], "online marketing bureau")
        self.assertEqual(rows[0]["position"], 7.0)
        self.assertIsNone(rows[1]["position"])


class BingOAuthTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(bing, "settings", SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_configured(self):
        self.assertTrue(bing.oauth_configured())
        self.assertTrue(bing.is_configured())
        self.assertIsNone(bing.api_key_auth())
        with patch.object(bing, "settings", SimpleNamespace(**{**vars(SETTINGS), "bing_client_secret": ""})):
            self.assertFalse(bing.is_configured())
            with self.assertRaises(BingWebmasterServiceError) as ctx:
                bing.authorize_url("x" * 20)
            self.assertEqual(ctx.exception.code, "not_configured")
        with patch.object(bing, "settings", SimpleNamespace(**{**vars(SETTINGS), "bing_webmaster_api_key": " k "})):
            self.assertEqual(bing.api_key_auth(), BingAuth(api_key="k"))

    def test_authorize_url(self):
        url = urlparse(bing.authorize_url("nonce-1234567890"))
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", "https://www.bing.com/webmasters/oauth/authorize")
        self.assertEqual({k: v[0] for k, v in parse_qs(url.query).items()}, {
            "response_type": "code",
            "client_id": "client-id",
            "redirect_uri": "https://app.iexist.nl/api/bing-webmaster/callback",
            "scope": "webmaster.read",
            "state": "nonce-1234567890",
        })

    def test_exchange_sends_configured_redirect_uri(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["form"] = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            return httpx.Response(200, json={
                "access_token": "a", "token_type": "bearer", "expires_in": 3599, "refresh_token": "r",
            })

        tokens = bing.exchange_code("de-code", client=_client(handler))
        self.assertEqual(seen["url"], "https://www.bing.com/webmasters/oauth/token")
        self.assertEqual(seen["form"], {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "grant_type": "authorization_code",
            "code": "de-code",
            "redirect_uri": "https://app.iexist.nl/api/bing-webmaster/callback",
        })
        self.assertEqual(tokens["refresh_token"], "r")

    def test_exchange_without_refresh_token_fails(self):
        handler = lambda request: httpx.Response(200, json={"access_token": "a", "expires_in": 3599})  # noqa: E731
        with self.assertRaises(BingWebmasterServiceError) as ctx:
            bing.exchange_code("de-code", client=_client(handler))
        self.assertEqual(ctx.exception.code, "oauth_error")

    def test_refresh(self):
        seen = {}

        def ok(request: httpx.Request) -> httpx.Response:
            seen["form"] = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            return httpx.Response(200, json={"access_token": "nieuw", "expires_in": 3599, "token_type": "Bearer"})

        tokens = bing.refresh_access_token("refresh", client=_client(ok))
        self.assertEqual(seen["form"]["grant_type"], "refresh_token")
        self.assertEqual(seen["form"]["refresh_token"], "refresh")
        self.assertNotIn("redirect_uri", seen["form"])
        self.assertEqual(tokens["access_token"], "nieuw")

        revoked = lambda request: httpx.Response(400, json={"error": "invalid_grant"})  # noqa: E731
        with self.assertRaises(BingWebmasterServiceError) as ctx:
            bing.refresh_access_token("refresh", client=_client(revoked))
        self.assertEqual(ctx.exception.code, "token_expired")

        bad_client = lambda request: httpx.Response(  # noqa: E731
            400, json={"error": "invalid_client", "error_description": "Client authentication failed."}
        )
        with self.assertRaises(BingWebmasterServiceError) as ctx:
            bing.refresh_access_token("refresh", client=_client(bad_client))
        self.assertEqual(ctx.exception.code, "oauth_error")
        self.assertIn("Client authentication failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
