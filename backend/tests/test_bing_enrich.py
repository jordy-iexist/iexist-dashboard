"""Bing Webmaster in fase 4: site-keuze, snapshot, vergelijking, checklistpunt, actiepunten en koppeling."""
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import OAuthConnection
from app.features.launch_checklist.services import bing_enrich, gsc_enrich, quarterly_checklist
from app.features.launch_checklist.services.issues import generate_quarterly_issues
from app.features.launch_checklist.services.quarterly_checks import evaluate_bing_webmaster
from app.features.launch_checklist.services.quarterly_compare import bing_feed_state, compare_bing_webmaster
from app.services.bing_webmaster import client as bing_client
from app.services.bing_webmaster import connection
from app.services.bing_webmaster.client import BingWebmasterServiceError

PERIOD_SETTINGS = SimpleNamespace(gsc_period_days=90, gsc_data_lag_days=3, gsc_row_limit=250)
TODAY = date(2026, 11, 12)  # meetperiode 12 aug – 9 nov, vorige 14 mei – 11 aug
SITE = "https://www.klant.nl/"


def site(url, verified=True):
    return {"url": url, "verified": verified}


def crawl_row(day, in_index, crawled=10, **extra):
    base = dict(
        date=day, in_index=in_index, in_links=500, crawled_pages=crawled, crawl_errors=0, code_2xx=in_index,
        code_301=5, code_302=0, code_4xx=0, code_5xx=0, other_codes=0, blocked_by_robots=0, dns_failures=0,
        connection_timeouts=0, contains_malware=0,
    )
    base.update(extra)
    return base


class FakeSession:
    """Zelfde methodes als BingSession, met vaste antwoorden of een fout per methode."""

    mode = "api_key"

    def __init__(self, sites=None, **answers):
        self.sites = sites if sites is not None else [site(SITE)]
        self.answers = answers
        self.calls = []

    def list_sites(self):
        return self._answer("list_sites", self.sites)

    def _answer(self, name, default):
        self.calls.append(name)
        value = self.answers.get(name, default)
        if isinstance(value, Exception):
            raise value
        return value

    def crawl_stats(self, site_url):
        return self._answer("crawl_stats", [])

    def crawl_issues(self, site_url):
        return self._answer("crawl_issues", [])

    def feeds(self, site_url):
        return self._answer("feeds", [])

    def traffic_stats(self, site_url):
        return self._answer("traffic_stats", [])

    def query_stats(self, site_url):
        return self._answer("query_stats", [])

    def page_stats(self, site_url):
        return self._answer("page_stats", [])


class SiteTest(unittest.TestCase):
    def test_https_and_same_www_variant_first(self):
        sites = [site("http://klant.nl/"), site("https://klant.nl/"), site(SITE), site("https://www.klant.nl/blog/"),
                 site("https://ander.nl/")]
        self.assertEqual(bing_enrich.match_sites("https://www.klant.nl", sites),
                         [SITE, "https://klant.nl/", "http://klant.nl/"])

    def test_parent_domain_does_not_cover_subdomain(self):
        self.assertEqual(bing_enrich.match_sites("https://shop.klant.nl/", [site("https://klant.nl/")]), [])

    def test_resolve(self):
        self.assertEqual(bing_enrich.resolve_site("https://klant.nl", [site(SITE)]), (SITE, "linked"))
        self.assertEqual(bing_enrich.resolve_site("https://klant.nl", [site(SITE, verified=False)]),
                         (SITE, "not_verified"))
        self.assertEqual(bing_enrich.resolve_site("https://klant.nl", [site("https://ander.nl/")]),
                         (None, "not_linked"))
        self.assertEqual(bing_enrich.resolve_site("geen-url", [site(SITE)]), (None, "not_linked"))


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(gsc_enrich, "settings", PERIOD_SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def full_session(self, **overrides):
        answers = dict(
            crawl_stats=[
                crawl_row(date(2026, 6, 1), 80),
                crawl_row(date(2026, 8, 12), 97, crawled=20),
                crawl_row(date(2026, 11, 8), 114, crawled=30, code_4xx=2),
            ],
            crawl_issues=[
                {"url": "https://www.klant.nl/oud", "http_code": 301, "in_links": 9,
                 "issues": [{"key": "code_301", "label": "301-redirect"}]},
                {"url": "https://www.klant.nl/weg", "http_code": 404, "in_links": 2,
                 "issues": [{"key": "code_4xx", "label": "4xx-fout"}]},
                {"url": "https://www.klant.nl/stuk", "http_code": 500, "in_links": 1,
                 "issues": [{"key": "code_5xx", "label": "serverfout (5xx)"}]},
            ],
            feeds=[{"url": "https://www.klant.nl/sitemap.xml", "status": "Success", "type": "Sitemap",
                    "url_count": 40, "last_crawled": None, "submitted": None}],
            traffic_stats=[
                {"date": date(2026, 1, 1), "clicks": 1, "impressions": 5},
                {"date": date(2026, 6, 1), "clicks": 30, "impressions": 300},
                {"date": date(2026, 9, 1), "clicks": 12, "impressions": 200},
                {"date": date(2026, 11, 9), "clicks": 3, "impressions": 100},
                {"date": date(2026, 11, 11), "clicks": 99, "impressions": 999},  # na de meetperiode
            ],
            query_stats=[
                {"key": "seo bureau", "date": date(2026, 9, 4), "clicks": 4, "impressions": 40, "position": 3.0},
                {"key": "seo bureau", "date": date(2026, 10, 2), "clicks": 2, "impressions": 60, "position": 8.0},
                {"key": "seo bureau", "date": date(2026, 6, 5), "clicks": 1, "impressions": 10, "position": 9.0},
                {"key": "oud woord", "date": date(2026, 6, 5), "clicks": 5, "impressions": 50, "position": 4.0},
                {"key": "heel oud", "date": date(2026, 2, 6), "clicks": 0, "impressions": 1, "position": 30.0},
            ],
        )
        answers.update(overrides)
        return FakeSession(**answers)

    def test_snapshot_of_linked_site(self):
        snapshot = bing_enrich.collect("https://klant.nl", self.full_session, today=TODAY)

        self.assertEqual(snapshot["state"], "ok")
        self.assertEqual(snapshot["site"], SITE)
        self.assertEqual(snapshot["auth_mode"], "api_key")
        self.assertEqual(snapshot["period"], {"start": "2026-08-12", "end": "2026-11-09", "days": 90})
        self.assertEqual(snapshot["totals"], {"clicks": 15, "impressions": 300, "ctr": 0.05})
        self.assertEqual(snapshot["totals_previous"], {"clicks": 30, "impressions": 300, "ctr": 0.1})
        # Laatste stand, gecrawlde pagina's opgeteld over de meetperiode, index aan het begin van de periode.
        self.assertEqual(snapshot["crawl"]["in_index"], 114)
        self.assertEqual(snapshot["crawl"]["in_index_before"], 97)
        self.assertEqual(snapshot["crawl"]["crawled_pages"], 50)
        self.assertEqual(snapshot["crawl"]["date"], "2026-11-08")
        # Redirects zijn geen crawlfout; de ernstige staat bovenaan.
        self.assertEqual(snapshot["crawl_issues"]["total"], 2)
        self.assertEqual([r["url"] for r in snapshot["crawl_issues"]["rows"]],
                         ["https://www.klant.nl/stuk", "https://www.klant.nl/weg"])
        self.assertTrue(snapshot["crawl_issues"]["rows"][0]["severe"])
        queries = {r["key"]: r for r in snapshot["queries"]}
        self.assertEqual(queries["seo bureau"]["clicks"], 6)
        self.assertEqual(queries["seo bureau"]["clicks_prev"], 1)
        self.assertEqual(queries["seo bureau"]["position"], 6.0)  # gewogen op vertoningen
        self.assertEqual(queries["oud woord"]["clicks"], 0)
        self.assertEqual(queries["oud woord"]["clicks_prev"], 5)
        self.assertNotIn("heel oud", queries)
        self.assertTrue(bing_enrich.has_data(snapshot))
        self.assertEqual(snapshot["errors"], [])

    def test_short_history_leaves_previous_period_unknown(self):
        session = self.full_session(
            traffic_stats=[{"date": date(2026, 10, 1), "clicks": 2, "impressions": 20}],
            query_stats=[{"key": "nieuw", "date": date(2026, 10, 2), "clicks": 2, "impressions": 20, "position": 5.0}],
            crawl_stats=[crawl_row(date(2026, 10, 1), 12)],
        )
        snapshot = bing_enrich.collect("https://klant.nl", lambda: session, today=TODAY)
        self.assertEqual(snapshot["totals"]["clicks"], 2)
        self.assertIsNone(snapshot["totals_previous"])
        self.assertIsNone(snapshot["queries"][0]["clicks_prev"])
        self.assertIsNone(snapshot["crawl"]["in_index_before"])

    def test_site_not_in_account(self):
        session = FakeSession(sites=[site("https://ander.nl/")])
        snapshot = bing_enrich.collect("https://klant.nl", lambda: session, today=TODAY)
        self.assertEqual(snapshot["state"], "site_not_linked")
        self.assertIn("Site niet gekoppeld", snapshot["message"])
        self.assertIn("handmatig", snapshot["message"])
        self.assertEqual(session.calls, ["list_sites"])  # geen calls voor een site die er niet is
        self.assertFalse(bing_enrich.has_data(snapshot))

        unverified = FakeSession(sites=[site(SITE, verified=False)])
        self.assertEqual(
            bing_enrich.collect("https://klant.nl", lambda: unverified, today=TODAY)["state"], "site_not_verified"
        )

    def test_no_connection(self):
        def not_connected():
            raise BingWebmasterServiceError("niet gekoppeld", code="not_connected")

        snapshot = bing_enrich.collect("https://klant.nl", not_connected, today=TODAY)
        self.assertEqual(snapshot["state"], "not_connected")
        self.assertIn("handmatig", snapshot["message"])

        expired = FakeSession(list_sites=BingWebmasterServiceError("verlopen", code="token_expired"))
        self.assertEqual(bing_enrich.collect("https://klant.nl", lambda: expired, today=TODAY)["state"], "token_expired")

        broken = FakeSession(list_sites=BingWebmasterServiceError("Timeout bij verbinden met Bing.", code="timeout"))
        snapshot = bing_enrich.collect("https://klant.nl", lambda: broken, today=TODAY)
        self.assertEqual(snapshot["state"], "error")
        self.assertEqual(snapshot["errors"], ["Timeout bij verbinden met Bing."])

    def test_one_failing_call_keeps_the_rest(self):
        session = self.full_session(feeds=BingWebmasterServiceError("Timeout bij verbinden met Bing.", code="timeout"))
        snapshot = bing_enrich.collect("https://klant.nl", lambda: session, today=TODAY)
        self.assertEqual(snapshot["state"], "ok")
        self.assertIsNone(snapshot["sitemaps"])
        self.assertEqual(snapshot["totals"]["clicks"], 15)
        self.assertEqual(snapshot["errors"], ["sitemaps: Timeout bij verbinden met Bing."])

    def test_revoked_token_stops_the_series(self):
        session = self.full_session(crawl_issues=BingWebmasterServiceError("verlopen", code="token_expired"))
        snapshot = bing_enrich.collect("https://klant.nl", lambda: session, today=TODAY)
        self.assertEqual(snapshot["state"], "token_expired")
        self.assertNotIn("feeds", session.calls)
        self.assertFalse(bing_enrich.has_data(snapshot))


class CompareAndCheckTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(gsc_enrich, "settings", PERIOD_SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def snapshot(self, **answers):
        defaults = dict(
            crawl_stats=[crawl_row(date(2026, 8, 12), 100), crawl_row(date(2026, 11, 8), 110)],
            feeds=[{"url": "https://www.klant.nl/sitemap.xml", "status": "Success", "type": "Sitemap",
                    "url_count": 40, "last_crawled": None, "submitted": None}],
            traffic_stats=[{"date": date(2026, 1, 1), "clicks": 0, "impressions": 1},
                           {"date": date(2026, 6, 1), "clicks": 40, "impressions": 400},
                           {"date": date(2026, 9, 1), "clicks": 44, "impressions": 500}],
        )
        defaults.update(answers)
        return bing_enrich.collect("https://klant.nl", lambda: FakeSession(**defaults), today=TODAY)

    def test_feed_state(self):
        self.assertEqual(bing_feed_state("Success"), "ok")
        self.assertEqual(bing_feed_state("Pending"), "pending")
        self.assertEqual(bing_feed_state("Failed"), "error")

    def test_clean_site_is_ok_and_counts_as_done(self):
        compared = compare_bing_webmaster(self.snapshot())
        self.assertTrue(compared["has_data"])
        clicks = next(m for m in compared["metrics"] if m["key"] == "clicks")
        self.assertEqual((clicks["before"], clicks["after"], clicks["pct"]), (40.0, 44.0, 10.0))
        self.assertEqual(compared["index"]["in_index"]["before"], 100.0)
        self.assertEqual(compared["index"]["in_index"]["before_source"], "bing")
        self.assertEqual(compared["sitemaps"]["total"], 1)

        result = evaluate_bing_webmaster(compared)
        self.assertEqual(result["status"], "ok")
        self.assertIn("110 pagina's in de Bing-index (was 100)", result["message"])
        self.assertIn("geen crawlfouten", result["message"])
        merged = quarterly_checklist.merge_quarterly_checklist({"c4_bing_webmaster": result}, {})
        effective = {i["key"]: i["effective"] for s in merged["sections"] for i in s["items"]}
        self.assertEqual(effective["c4_bing_webmaster"], "done")
        self.assertEqual(generate_quarterly_issues({"c4_bing_webmaster": result}, {}), [])

    def test_site_not_linked_is_info_and_stays_open_without_issues(self):
        snapshot = bing_enrich.collect(
            "https://klant.nl", lambda: FakeSession(sites=[site("https://ander.nl/")]), today=TODAY
        )
        compared = compare_bing_webmaster(snapshot)
        self.assertEqual(compared["state"], "site_not_linked")
        self.assertFalse(compared["has_data"])

        result = evaluate_bing_webmaster(compared)
        self.assertEqual(result["status"], "info")
        self.assertIn("Site niet gekoppeld in Bing Webmaster Tools", result["message"])
        self.assertIn("handmatig", result["message"])
        merged = quarterly_checklist.merge_quarterly_checklist({"c4_bing_webmaster": result}, {})
        effective = {i["key"]: i["effective"] for s in merged["sections"] for i in s["items"]}
        self.assertEqual(effective["c4_bing_webmaster"], "open")
        self.assertEqual(generate_quarterly_issues({"c4_bing_webmaster": result}, {}), [])

    def test_without_snapshot_or_data(self):
        self.assertIsNone(compare_bing_webmaster(None))
        self.assertEqual(evaluate_bing_webmaster(None)["status"], "info")
        empty = compare_bing_webmaster(self.snapshot(crawl_stats=[], feeds=[], traffic_stats=[]))
        self.assertFalse(empty["has_data"])
        result = evaluate_bing_webmaster(empty)
        self.assertEqual(result["status"], "info")
        self.assertIn("nog geen data", result["message"])

    def test_problems_give_issues(self):
        compared = compare_bing_webmaster(self.snapshot(
            crawl_stats=[crawl_row(date(2026, 8, 12), 100), crawl_row(date(2026, 11, 8), 60)],
            crawl_issues=[
                {"url": "https://www.klant.nl/stuk", "http_code": 500, "in_links": 1,
                 "issues": [{"key": "code_5xx", "label": "serverfout (5xx)"}]},
                {"url": "https://www.klant.nl/weg", "http_code": 404, "in_links": 2,
                 "issues": [{"key": "code_4xx", "label": "4xx-fout"}]},
            ],
            feeds=[],
            traffic_stats=[{"date": date(2026, 1, 1), "clicks": 0, "impressions": 1},
                           {"date": date(2026, 6, 1), "clicks": 100, "impressions": 900},
                           {"date": date(2026, 9, 1), "clicks": 50, "impressions": 500}],
        ))
        result = evaluate_bing_webmaster(compared, clicks_drop_warn_pct=20)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["details"]["index_drop_pct"], -40.0)
        self.assertEqual(result["details"]["clicks_drop_pct"], -50.0)
        self.assertTrue(result["details"]["no_sitemap"])

        issues = generate_quarterly_issues({"c4_bing_webmaster": result}, {})
        self.assertEqual({i["issue_type"] for i in issues}, {"c4_bing_webmaster"})
        self.assertEqual(len(issues), 5)  # 2 crawlfouten, geen sitemap, index gedaald, klikken gedaald
        self.assertEqual(issues[0]["severity"], "hoog")
        self.assertEqual(issues[0]["url"], "https://www.klant.nl/stuk")
        self.assertEqual(generate_quarterly_issues({"c4_bing_webmaster": result}, {"c4_bing_webmaster": "afgerond"}), [])

    def test_small_numbers_do_not_warn(self):
        compared = compare_bing_webmaster(self.snapshot(
            crawl_stats=[crawl_row(date(2026, 8, 12), 5), crawl_row(date(2026, 11, 8), 3)],
            traffic_stats=[{"date": date(2026, 1, 1), "clicks": 0, "impressions": 1},
                           {"date": date(2026, 6, 1), "clicks": 4, "impressions": 40},
                           {"date": date(2026, 9, 1), "clicks": 1, "impressions": 30}],
        ))
        self.assertEqual(evaluate_bing_webmaster(compared)["status"], "ok")

    def test_index_falls_back_to_previous_round(self):
        snapshot = self.snapshot(crawl_stats=[crawl_row(date(2026, 11, 8), 60)])
        base = {"state": "ok", "crawl": {"in_index": 50, "date": "2026-08-01"}}
        index = compare_bing_webmaster(snapshot, base)["index"]["in_index"]
        self.assertEqual((index["before"], index["after"], index["before_source"]), (50.0, 60.0, "base"))
        self.assertIsNone(compare_bing_webmaster(snapshot, {"state": "site_not_linked"})["index"]["in_index"]["before"])


class ConnectionTest(unittest.TestCase):
    """Tokens bewaren en verversen, tegen een SQLite-database met alleen `oauth_connections`."""

    def setUp(self):
        engine = create_engine("sqlite://")
        OAuthConnection.__table__.create(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.settings = SimpleNamespace(
            bing_client_id="id", bing_client_secret="secret",
            bing_webmaster_redirect_uri="https://app.iexist.nl/api/bing-webmaster/callback",
            bing_webmaster_api_key="", bing_webmaster_request_timeout_seconds=5.0,
        )
        patcher = patch.object(bing_client, "settings", self.settings)
        patcher.start()
        self.addCleanup(patcher.stop)

    def http(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_status_and_save(self):
        self.assertEqual(connection.status(self.db)["connected"], False)
        self.assertEqual(connection.status(self.db)["mode"], "oauth")
        with self.assertRaises(BingWebmasterServiceError) as ctx:
            connection.get_auth(self.db)
        self.assertEqual(ctx.exception.code, "not_connected")

        connection.save_tokens(self.db, {"access_token": "a1", "refresh_token": "r1", "expires_in": 3599}, "user-1")
        row = self.db.query(OAuthConnection).one()
        self.assertNotIn("r1", row.refresh_token_encrypted)  # versleuteld opgeslagen
        self.assertNotIn("a1", row.access_token_encrypted)
        self.assertEqual(row.connected_by, "user-1")
        self.assertTrue(connection.status(self.db)["connected"])
        self.assertEqual(connection.get_auth(self.db).access_token, "a1")

        self.assertTrue(connection.disconnect(self.db))
        self.assertFalse(connection.status(self.db)["connected"])

    def test_api_key_wins_and_skips_database(self):
        self.settings.bing_webmaster_api_key = "key"
        status = connection.status(self.db)
        self.assertEqual((status["mode"], status["connected"]), ("api_key", True))
        self.assertEqual(connection.get_auth(self.db).api_key, "key")

    def test_expired_access_token_is_refreshed(self):
        connection.save_tokens(self.db, {"access_token": "a1", "refresh_token": "r1", "expires_in": 3599}, None)
        row = self.db.query(OAuthConnection).one()
        row.access_token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.db.commit()
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.content.decode())
            return httpx.Response(200, json={"access_token": "a2", "expires_in": 3599})

        self.assertEqual(connection.get_auth(self.db, http=self.http(handler)).access_token, "a2")
        self.assertIn("refresh_token=r1", seen[0])
        # Het nieuwe token is bewaard: de volgende keer geen call naar Bing.
        self.assertEqual(connection.get_auth(self.db, http=self.http(lambda r: httpx.Response(500))).access_token, "a2")

    def test_revoked_refresh_token_marks_connection(self):
        connection.save_tokens(self.db, {"access_token": "a1", "refresh_token": "r1", "expires_in": 3599}, None)
        revoked = self.http(lambda r: httpx.Response(400, json={"error": "invalid_grant"}))
        with self.assertRaises(BingWebmasterServiceError) as ctx:
            connection.get_auth(self.db, force_refresh=True, http=revoked)
        self.assertEqual(ctx.exception.code, "token_expired")
        status = connection.status(self.db)
        self.assertFalse(status["connected"])
        self.assertIn("opnieuw", status["error"])
        with self.assertRaises(BingWebmasterServiceError) as ctx:
            connection.get_auth(self.db)
        self.assertEqual(ctx.exception.code, "token_expired")
        # Opnieuw koppelen herstelt het.
        connection.save_tokens(self.db, {"access_token": "a3", "refresh_token": "r3", "expires_in": 3599}, None)
        self.assertTrue(connection.status(self.db)["connected"])

    def test_session_refreshes_once_when_bing_rejects_the_token(self):
        connection.save_tokens(self.db, {"access_token": "oud", "refresh_token": "r1", "expires_in": 3599}, None)
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/oauth/token"):
                return httpx.Response(200, json={"access_token": "nieuw", "expires_in": 3599})
            seen.append(request.headers["Authorization"])
            if request.headers["Authorization"] == "Bearer oud":
                return httpx.Response(400, json={"ErrorCode": 18, "Message": "ERROR!!! InvalidToken"})
            return httpx.Response(200, json={"d": [{"Url": SITE, "IsVerified": True}]})

        session = connection.BingSession(self.db, http=self.http(handler))
        self.assertEqual(session.list_sites(), [{"url": SITE, "verified": True}])
        self.assertEqual(seen, ["Bearer oud", "Bearer nieuw"])

    def test_session_marks_connection_when_refresh_does_not_help(self):
        connection.save_tokens(self.db, {"access_token": "oud", "refresh_token": "r1", "expires_in": 3599}, None)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/oauth/token"):
                return httpx.Response(200, json={"access_token": "nieuw", "expires_in": 3599})
            return httpx.Response(400, json={"ErrorCode": 18, "Message": "ERROR!!! InvalidToken"})

        session = connection.BingSession(self.db, http=self.http(handler))
        with self.assertRaises(BingWebmasterServiceError) as ctx:
            session.list_sites()
        self.assertEqual(ctx.exception.code, "token_expired")
        self.assertFalse(connection.status(self.db)["connected"])


if __name__ == "__main__":
    unittest.main()
