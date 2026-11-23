import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.features.customers import rankings
from app.features.customers.rankings import (
    content_gaps, customer_rankings, host_of, is_organic, organic_rows, position, summarize,
)
from app.services.proranktracker import client as prt
from app.services.proranktracker.client import ProRankTrackerServiceError

SETTINGS = SimpleNamespace(proranktracker_api_token="test-token", proranktracker_request_timeout_seconds=5.0)


def _term(name, rank, month="NTH", *, volume="100", url="https://klant.nl/pagina/", ai=0, term_type="organic"):
    return {
        "name": name, "rank": rank, "yesterdayrank": rank, "weekagorank": rank, "monthagorank": month,
        "top_rank": 1, "matchedurl": url, "localmonthlysearches": volume, "globalmonthlysearches": "1000",
        "engine": "Google.nl", "location": "Netherlands", "lang": "nl", "term_type": term_type,
        "is_ai_term": ai, "url_id": 1, "term_id": 2, "url_term_id": 3,
    }


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok(terms) -> httpx.Response:
    return httpx.Response(200, json={"result": "success", "data": {"url_terms": terms, "count": len(terms)},
                                     "error_message": None})


class PositionTest(unittest.TestCase):
    def test_conversion(self):
        cases = [
            (5, 5), ("5", 5), ("12.0", 12), (1, 1), (100, 100), ("100", 100),
            ("NTH", None), ("", None), (None, None), ("abc", None), (0, None), ("-3", None),
            (101, None), ("150", None), (True, None),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(position(value), expected)

    def test_host(self):
        self.assertEqual(host_of("https://www.klant.nl/"), "klant.nl")
        self.assertEqual(host_of("http://Klant.NL/pad"), "klant.nl")
        self.assertEqual(host_of("klant.nl"), "klant.nl")
        self.assertEqual(host_of(""), "")

    def test_only_organic_non_ai_terms(self):
        self.assertTrue(is_organic(_term("a", 3)))
        self.assertTrue(is_organic(_term("a", 3, ai="0")))
        self.assertFalse(is_organic(_term("a", 3, ai=1)))
        self.assertFalse(is_organic(_term("a", 3, ai="1")))
        self.assertFalse(is_organic(_term("a", 3, term_type="ai")))
        self.assertFalse(is_organic({**_term("a", 3), "is_ai_term": None}))


class SummarizeTest(unittest.TestCase):
    def test_counts_averages_and_deltas(self):
        rows = [
            _term("top een", "1", "2"),        # top 3 nu en toen
            _term("top drie", 3, "8"),         # nieuw in top 3
            _term("gezakt", "6", "2"),         # uit de top 3 gezakt
            _term("quick", "12", "15", volume="40"),
            _term("nieuw", "20", "NTH", volume=None, url="None"),
            _term("ver weg", "45", "40"),
            _term("weg", "NTH", "30"),
        ]
        s = summarize(rows)
        self.assertEqual(s["state"], "ok")
        self.assertIsNone(s["message"])
        self.assertIsNotNone(s["fetched_at"])
        self.assertEqual(s["keywords"], 7)
        self.assertEqual(s["ranked"], 6)
        # (1 + 3 + 6 + 12 + 20 + 45) / 6 = 14.5
        self.assertEqual(s["avg_position"], 14.5)
        # Beide momenten: rank 1,3,6,12,45 = 67/5 = 13.4; maand 2,8,2,15,40 = 67/5 = 13.4
        self.assertEqual(s["avg_position_delta"], 0.0)
        self.assertEqual(s["top3"], 2)
        self.assertEqual(s["top3_delta"], 0)  # nu 2 (1, 3), toen 2 (2, 2)
        self.assertNotIn("quick_wins", s)
        self.assertNotIn("rows", s)

    def test_avg_delta_positive_when_improved(self):
        s = summarize([_term("a", "4", "10"), _term("b", "6", "9"), _term("c", "3", "NTH")])
        # Alleen a en b: maand (10 + 9) / 2 = 9.5, nu (4 + 6) / 2 = 5.0
        self.assertEqual(s["avg_position_delta"], 4.5)
        self.assertEqual(s["avg_position"], 4.3)
        self.assertEqual(s["top3_delta"], 1)

    def test_no_month_data(self):
        rows = [_term("a", "5"), _term("b", "8")]
        for row in rows:
            del row["monthagorank"]
        s = summarize(rows)
        self.assertIsNone(s["avg_position_delta"])
        self.assertIsNone(s["top3_delta"])

        # Veld aanwezig maar overal "NTH": wel een top3-verschil, geen gemiddeld verschil.
        s = summarize([_term("a", "2", "NTH")])
        self.assertIsNone(s["avg_position_delta"])
        self.assertEqual(s["top3_delta"], 1)

    def test_content_gaps_in_summary(self):
        s = summarize([_term("gerankt", "5", volume="900"), _term("kans", "NTH", volume="300")])
        self.assertEqual(s["content_gaps"], [{"keyword": "kans", "volume": 300}])
        self.assertEqual(s["content_gaps_total"], 1)

    def test_nothing_ranked(self):
        s = summarize([_term("a", "NTH", "NTH"), _term("b", "NTH", "4")])
        self.assertEqual((s["keywords"], s["ranked"], s["top3"]), (2, 0, 0))
        self.assertIsNone(s["avg_position"])
        self.assertIsNone(s["avg_position_delta"])
        self.assertEqual(s["top3_delta"], 0)


class ContentGapsTest(unittest.TestCase):
    def test_which_keywords_count(self):
        gaps, total = content_gaps([
            _term("geen positie", "NTH", volume="120"),
            _term("leeg", "", volume="80"),
            _term("zonder volume", "NTH", volume=None),
            _term("volume nul", "NTH", volume="0"),
            _term("tekst volume", "NTH", volume="abc"),
            _term("met positie", "40", volume="500"),
            _term("", "NTH", volume="999"),
        ])
        self.assertEqual(gaps, [{"keyword": "geen positie", "volume": 120}, {"keyword": "leeg", "volume": 80}])
        self.assertEqual(total, 2)

    def test_duplicates_use_same_key(self):
        gaps, total = content_gaps([
            # Eén rij met positie: geen contentkans.
            _term("Webdesign  Ermelo", "NTH", volume="300"), _term("webdesign ermelo", "18", volume="10"),
            # Alle rijen zonder positie: het hoogste volume telt.
            _term("SEO Ermelo", "NTH", volume="20"), _term(" seo ermelo", "NTH", volume="90"),
            _term("seo  ermelo", "NTH", volume="0"),
        ])
        self.assertEqual(gaps, [{"keyword": "seo ermelo", "volume": 90}])
        self.assertEqual(total, 1)

    def test_sorting_and_limit(self):
        rows = [_term(name, "NTH", volume=volume) for name, volume in [
            ("f", "10"), ("b", "50"), ("a", "50"), ("g", "5"), ("c", "40"), ("d", "30"), ("e", "20"),
        ]]
        gaps, total = content_gaps(rows)
        self.assertEqual(rankings.CONTENT_GAPS_LIMIT, 5)
        self.assertEqual([(g["keyword"], g["volume"]) for g in gaps],
                         [("a", 50), ("b", 50), ("c", 40), ("d", 30), ("e", 20)])
        self.assertEqual(total, 7)
        self.assertEqual(summarize(rows)["content_gaps_total"], 7)


class CustomerRankingsTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(prt, "settings", SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = patch.object(prt.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def _assert_empty(self, s):
        self.assertEqual((s["keywords"], s["ranked"], s["top3"]), (0, 0, 0))
        self.assertIsNone(s["avg_position"])
        self.assertIsNone(s["avg_position_delta"])
        self.assertIsNone(s["top3_delta"])
        self.assertEqual((s["content_gaps"], s["content_gaps_total"]), ([], 0))
        self.assertNotIn("rows", s)

    def test_organic_rows_helper(self):
        terms = [_term("organisch", "5"), _term("ai", "2", ai=1)]
        state, rows, message = organic_rows("https://www.klant.nl/", client=_client(lambda r: _ok(terms)))
        self.assertEqual((state, [r["name"] for r in rows], message), ("ok", ["organisch"], None))
        state, rows, message = organic_rows("https://klant.nl", client=_client(lambda r: _ok([])))
        self.assertEqual((state, rows, message), ("not_tracked", [], None))
        error = lambda r: httpx.Response(200, json={"result": "error", "data": None, "error_message": "Kapot"})
        state, rows, message = organic_rows("https://klant.nl", client=_client(error))
        self.assertEqual((state, rows), ("error", []))
        self.assertIn("Kapot", message)

    def test_filters_ai_terms_and_uses_host_without_www(self):
        hosts = []

        def handler(request: httpx.Request) -> httpx.Response:
            hosts.append(request.url.params["bulk_urls"])
            return _ok([_term("organisch", "5", "9"), _term("ai prompt", "2", "2", ai=1),
                        _term("ai type", "1", "1", term_type="ai")])

        s = customer_rankings("https://www.klant.nl/", client=_client(handler))
        self.assertEqual(hosts, ["klant.nl"])
        self.assertEqual(s["state"], "ok")
        self.assertEqual((s["keywords"], s["ranked"], s["top3"]), (1, 1, 0))
        self.assertEqual(s["avg_position"], 5.0)

    def test_falls_back_to_www(self):
        hosts = []

        def handler(request: httpx.Request) -> httpx.Response:
            host = request.url.params["bulk_urls"]
            hosts.append(host)
            return _ok([_term("a", "5")] if host == "www.klant.nl" else [])

        s = customer_rankings("https://klant.nl", client=_client(handler))
        self.assertEqual(hosts, ["klant.nl", "www.klant.nl"])
        self.assertEqual((s["state"], s["keywords"]), ("ok", 1))

    def test_not_tracked_after_www_fallback(self):
        hosts = []

        def handler(request: httpx.Request) -> httpx.Response:
            hosts.append(request.url.params["bulk_urls"])
            return _ok([])

        s = customer_rankings("https://klant.nl", client=_client(handler))
        self.assertEqual(hosts, ["klant.nl", "www.klant.nl"])
        self.assertEqual(s["state"], "not_tracked")
        self.assertIn("niet in ProRankTracker", s["message"])
        self.assertIsNotNone(s["fetched_at"])
        self._assert_empty(s)

    def test_only_ai_terms_is_not_tracked(self):
        s = customer_rankings("klant.nl", client=_client(lambda r: _ok([_term("ai", "1", ai=1)])))
        self.assertEqual(s["state"], "not_tracked")
        self._assert_empty(s)

    def test_not_configured_makes_no_request(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("geen request zonder token")

        with patch.object(prt, "settings", SimpleNamespace(proranktracker_api_token=" ",
                                                           proranktracker_request_timeout_seconds=5.0)):
            s = customer_rankings("https://klant.nl", client=_client(handler))
        self.assertEqual(s["state"], "not_configured")
        self.assertIn("PRORANKTRACKER_API_X_TOKEN", s["message"])
        self.assertIsNone(s["fetched_at"])
        self._assert_empty(s)

    def test_prt_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"result": "error", "data": None, "error_message": "Kapot"})

        s = customer_rankings("https://klant.nl", client=_client(handler))
        self.assertEqual(s["state"], "error")
        self.assertIn("Posities niet opgehaald uit ProRankTracker", s["message"])
        self.assertIn("Kapot", s["message"])
        self.assertIsNone(s["fetched_at"])
        self._assert_empty(s)

    def test_service_error_from_client(self):
        with patch.object(rankings.prt, "rank_overview",
                          side_effect=ProRankTrackerServiceError("weigert", code="unauthorized")):
            s = customer_rankings("https://klant.nl")
        self.assertEqual(s["state"], "error")
        self.assertIn("weigert", s["message"])

    def test_empty_base_url_is_not_tracked(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("geen request zonder host")

        self.assertEqual(customer_rankings("", client=_client(handler))["state"], "not_tracked")


if __name__ == "__main__":
    unittest.main()
