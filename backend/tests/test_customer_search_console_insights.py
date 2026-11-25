"""Search Console-inzichten per klant (features/customers/search_console_insights).

Google en ProRankTracker worden nooit echt aangeroepen: `gsc.search_analytics`,
`gsc.search_analytics_all`, `gsc.get_service`, `gsc.is_configured`, `cached_sites` en
`organic_rows` zijn in de tests vervangen. De endpoint-test draait tegen een in-memory
SQLite-database.
"""
import threading
import unittest
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import require_user_id
from app.db.models import Base, CustomerWebsite
from app.db.session import get_db
from app.features.customers import search_console_insights as insights
from app.features.customers.router import router
from app.features.launch_checklist.services import gsc_enrich
from app.services.search_console import sites as gsc_sites
from app.services.search_console.client import SearchConsoleServiceError

TODAY = date(2026, 11, 25)
CURRENT = (date(2026, 10, 26), date(2026, 11, 22))
PREVIOUS = (date(2026, 9, 28), date(2026, 10, 25))
PERIOD_SETTINGS = SimpleNamespace(gsc_period_days=90, gsc_data_lag_days=3, gsc_row_limit=250)
SITE = "sc-domain:klant.nl"


def gsc_row(*keys, clicks=0, impressions=100, position=5.0):
    return {"keys": list(keys), "clicks": float(clicks), "impressions": float(impressions),
            "ctr": clicks / impressions if impressions else 0.0, "position": float(position)}


def sites(*urls):
    return [{"site_url": u, "permission": "siteOwner"} for u in urls]


# --- rekenregels -------------------------------------------------------------------------

class ExpectedCtrTest(unittest.TestCase):
    def test_curve(self):
        cases = [(1, 0.25), (4.5, 0.0575), (20, 0.0045), (0.4, 0.25), (2, 0.13), (10.5, 0.0165)]
        for position, expected in cases:
            with self.subTest(position=position):
                self.assertAlmostEqual(insights.expected_ctr(position), expected, places=6)
        self.assertIsNone(insights.expected_ctr(20.1))
        self.assertIsNone(insights.expected_ctr(None))


class ThresholdTest(unittest.TestCase):
    def test_scaling(self):
        names = ["opportunity_impressions", "opportunity_missed_clicks", "declining_prev_clicks",
                 "declining_drop", "untracked_impressions"]
        expected = {7: [50, 2, 5, 3, 13], 28: [200, 5, 10, 5, 50], 90: [643, 17, 33, 17, 161]}
        for days, values in expected.items():
            with self.subTest(days=days):
                self.assertEqual([insights.thresholds(days)[n] for n in names], values)


class PeriodsTest(unittest.TestCase):
    def test_days_override(self):
        with patch.object(gsc_enrich, "settings", PERIOD_SETTINGS):
            spans = gsc_enrich.periods(TODAY, 28)
            self.assertEqual(spans["current"], CURRENT)
            self.assertEqual(spans["previous"], PREVIOUS)
            # Zonder days blijft het GSC_PERIOD_DAYS.
            self.assertEqual((lambda s: (s[1] - s[0]).days + 1)(gsc_enrich.periods(TODAY)["current"]), 90)


class RoundPotentialTest(unittest.TestCase):
    def test_rounding(self):
        cases = [(4.9, None), (5, 5), (9.4, 9), (12, 10), (13, 15), (99, 100), (123, 120), (125, 130),
                 (1234, 1200), (1250, 1300)]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(insights.round_potential(value), expected)


class OpportunitiesTest(unittest.TestCase):
    def find(self, rows, days=28, **kwargs):
        return insights.opportunities(rows, days, **kwargs)

    def test_boundaries(self):
        # Positie 5 (verwacht 5%), 200 vertoningen: 10 verwachte klikken.
        result = self.find([
            gsc_row("precies", "https://klant.nl/a", clicks=5, impressions=200, position=5),  # gemist 5: ja
            gsc_row("te weinig gemist", "https://klant.nl/a", clicks=6, impressions=200, position=5),
            gsc_row("te weinig vertoningen", "https://klant.nl/a", clicks=0, impressions=199, position=5),
            # 60% van verwacht = 3%: 30 klikken op 1000 is geen kans meer, 29 wel.
            gsc_row("ctr op de grens", "https://klant.nl/a", clicks=30, impressions=1000, position=5),
            gsc_row("ctr net eronder", "https://klant.nl/a", clicks=29, impressions=1000, position=5),
            gsc_row("buiten top 20", "https://klant.nl/a", clicks=0, impressions=5000, position=20.5),
            gsc_row("positie 20", "https://klant.nl/a", clicks=0, impressions=5000, position=20),
        ])
        # Gemiste klikken: positie 20 → 22,5; ctr net eronder → 21; precies → 5.
        self.assertEqual([r["query"] for r in result["rows"]], ["positie 20", "ctr net eronder", "precies"])
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["min_impressions"], 200)
        self.assertEqual(result["rows"][1], {
            "query": "ctr net eronder", "page": "https://klant.nl/a", "impressions": 1000, "clicks": 29,
            "ctr": 0.029, "expected_ctr": 0.05, "position": 5.0, "missed_clicks": 21, "other_pages": 0,
            "advice_code": "improve_snippet", "advice": insights.ADVICE["improve_snippet"],
        })

    def test_one_page_per_query_and_fragments(self):
        result = self.find([
            gsc_row("schoenen", "https://klant.nl/a", clicks=1, impressions=300, position=4),
            gsc_row("schoenen", "https://klant.nl/b#:~:text=schoen", clicks=0, impressions=250, position=4),
            gsc_row("schoenen", "https://klant.nl/b", clicks=0, impressions=250, position=4),
            gsc_row("schoenen", "https://klant.nl/c", clicks=0, impressions=50, position=8),
        ])
        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        # /b (met en zonder fragment) heeft samen 500 vertoningen en wint van /a.
        self.assertEqual((row["page"], row["impressions"], row["other_pages"]), ("https://klant.nl/b", 500, 2))

    def test_advice_codes(self):
        rows = [
            gsc_row("top", "https://klant.nl/a", clicks=10, impressions=1000, position=2),
            gsc_row("midden", "https://klant.nl/a", clicks=10, impressions=1000, position=6),
            gsc_row("tweede pagina", "https://klant.nl/a", clicks=0, impressions=1000, position=14),
            gsc_row("geen klikken", "https://klant.nl/a", clicks=0, impressions=400, position=6),
            gsc_row("net geen intentie", "https://klant.nl/a", clicks=0, impressions=399, position=6),
        ]
        codes = {r["query"]: r["advice_code"] for r in self.find(rows)["rows"]}
        self.assertEqual(codes, {
            "top": "improve_snippet_top", "midden": "improve_snippet", "tweede pagina": "improve_position",
            "geen klikken": "check_intent", "net geen intentie": "improve_snippet",
        })

    def test_sorted_limited_and_potential(self):
        rows = [gsc_row(f"term {i:03d}", "https://klant.nl/a", clicks=0, impressions=200 + i, position=5)
                for i in range(120)]
        result = self.find(rows, truncated=True)
        self.assertEqual(result["total"], 120)
        self.assertEqual(len(result["rows"]), insights.OPPORTUNITIES_LIMIT)
        self.assertEqual(result["rows"][0]["query"], "term 119")
        self.assertTrue(result["truncated"])
        missed = sum((200 + i) * 0.05 for i in range(120))  # 1557 gemist in 28 dagen
        self.assertEqual(result["potential_clicks_per_month"], insights.round_potential(missed * 30 / 28))
        self.assertEqual(result["potential_clicks_per_month"], 1700)

    def test_small_potential_is_hidden(self):
        # 7 dagen: drempels 50 vertoningen / 2 gemiste klikken; 2,5 gemist × 30/7 = 10,7 → 10.
        result = self.find([gsc_row("a", "https://klant.nl/a", clicks=0, impressions=50, position=5)], days=7)
        self.assertEqual(result["potential_clicks_per_month"], 10)
        result = self.find([gsc_row("a", "https://klant.nl/a", clicks=0, impressions=50, position=5)], days=90)
        self.assertEqual((result["total"], result["potential_clicks_per_month"]), (0, None))

    def test_brand_queries_excluded(self):
        is_brand, strict = insights.brand_matcher("Klant Shop B.V.", "klantshop.nl", [
            gsc_row("klant shop openingstijden", impressions=100), gsc_row("schoenen", impressions=900),
        ])
        self.assertFalse(strict)
        rows = [
            gsc_row("klant-shop openingstijden", "https://klant.nl/a", clicks=0, impressions=500, position=3),
            gsc_row("schoenen", "https://klant.nl/a", clicks=0, impressions=500, position=3),
        ]
        result = self.find(rows, is_brand=is_brand)
        self.assertEqual([r["query"] for r in result["rows"]], ["schoenen"])
        self.assertEqual(result["brand_excluded"], 1)


class BrandTest(unittest.TestCase):
    def test_terms(self):
        self.assertEqual(insights.brand_terms("Bakkerij Jansen B.V.", "www.jansen-brood.nl"),
                         (["jansenbrood", "bakkerijjansen"], "jansenbroodnl"))
        # Korter dan 4 tekens telt niet.
        self.assertEqual(insights.brand_terms("ABC bv", "abc.nl"), ([], "abcnl"))
        self.assertEqual(insights.brand_terms("Klant", "klant.nl"), (["klant"], "klantnl"))

    def test_broad_and_strict(self):
        few = [gsc_row("tuin", impressions=900), gsc_row("tuin centrum", impressions=100)]
        matcher, strict = insights.brand_matcher("Tuin", "tuin.nl", few)
        # "tuin" is hier vooral een gewoon woord: > 50% valt onder de ruime regel → strikt.
        self.assertTrue(strict)
        self.assertTrue(matcher("Tuin"))
        self.assertTrue(matcher("tuin.nl openingstijden"))
        self.assertFalse(matcher("tuin centrum"))

        matcher, strict = insights.brand_matcher("Tuin", "tuin.nl", [gsc_row("tuin", impressions=10),
                                                                    gsc_row("bloemen", impressions=990)])
        self.assertFalse(strict)
        self.assertTrue(matcher("tuin centrum"))
        self.assertFalse(matcher("bloemen"))

    def test_without_terms_nothing_is_brand(self):
        matcher, strict = insights.brand_matcher("", "", [gsc_row("iets", impressions=10)])
        self.assertFalse(matcher("iets"))
        self.assertFalse(strict)


class DecliningTest(unittest.TestCase):
    def find(self, current, previous, days=28, row_limit=100):
        return insights.declining(current, previous, days, row_limit=row_limit, drop_pct=20)

    def test_thresholds(self):
        current = [
            gsc_row("https://klant.nl/te-weinig-eerst", clicks=4, impressions=100, position=3),
            gsc_row("https://klant.nl/te-kleine-daling", clicks=6, impressions=100, position=3),
            gsc_row("https://klant.nl/19-procent", clicks=81, impressions=1000, position=3),
            gsc_row("https://klant.nl/20-procent", clicks=80, impressions=1000, position=3),
            gsc_row("https://klant.nl/grens", clicks=5, impressions=100, position=3),
        ]
        previous = [
            gsc_row("https://klant.nl/te-weinig-eerst", clicks=9, impressions=100, position=3),
            gsc_row("https://klant.nl/te-kleine-daling", clicks=10, impressions=100, position=3),
            gsc_row("https://klant.nl/19-procent", clicks=100, impressions=1000, position=3),
            gsc_row("https://klant.nl/20-procent", clicks=100, impressions=1000, position=3),
            gsc_row("https://klant.nl/grens", clicks=10, impressions=100, position=3),
        ]
        result = self.find(current, previous)
        self.assertEqual([r["page"] for r in result["rows"]],
                         ["https://klant.nl/20-procent", "https://klant.nl/grens"])
        row = result["rows"][0]
        self.assertEqual((row["delta"], row["pct"], row["ctr"], row["ctr_prev"]), (-20, -20.0, 0.08, 0.1))
        self.assertEqual(result["total"], 2)

    def test_causes(self):
        current = [
            gsc_row("https://klant.nl/positie", clicks=10, impressions=1000, position=5.2),
            gsc_row("https://klant.nl/vraag", clicks=10, impressions=500, position=3),
            gsc_row("https://klant.nl/ctr", clicks=10, impressions=1000, position=3),
        ]
        previous = [
            gsc_row("https://klant.nl/weg", clicks=50, impressions=600, position=4),
            gsc_row("https://klant.nl/positie", clicks=40, impressions=1000, position=4.2),
            gsc_row("https://klant.nl/vraag", clicks=20, impressions=1000, position=3),
            gsc_row("https://klant.nl/ctr", clicks=20, impressions=1000, position=3.5),
        ]
        rows = {r["page"]: r for r in self.find(current, previous)["rows"]}
        self.assertEqual({p: r["cause_code"] for p, r in rows.items()}, {
            "https://klant.nl/weg": "no_impressions", "https://klant.nl/positie": "position_drop",
            "https://klant.nl/vraag": "less_demand", "https://klant.nl/ctr": "lower_ctr",
        })
        self.assertEqual(rows["https://klant.nl/positie"]["cause"], "Positie gedaald van 4,2 naar 5,2")
        self.assertEqual(rows["https://klant.nl/weg"]["position"], None)
        self.assertEqual(rows["https://klant.nl/weg"]["clicks"], 0)
        self.assertEqual(list(rows)[0], "https://klant.nl/weg")  # grootste daling eerst

    def test_truncated_current_skips_unknown_and_fragments_combine(self):
        current = [gsc_row("https://klant.nl/a", clicks=1, impressions=100, position=3),
                   gsc_row("https://klant.nl/a#deel", clicks=1, impressions=100, position=5),
                   gsc_row("https://klant.nl/b", clicks=1, impressions=100, position=5)]
        previous = [gsc_row("https://klant.nl/a", clicks=20, impressions=200, position=3),
                    gsc_row("https://klant.nl/onbekend", clicks=50, impressions=200, position=3)]
        # row_limit 3: de huidige lijst is afgekapt, dus "onbekend" kan nog bestaan; de vorige niet.
        result = self.find(current, previous, row_limit=3)
        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        self.assertEqual((row["page"], row["clicks"], row["impressions"], row["position"]),
                         ("https://klant.nl/a", 2, 200, 4.0))


class UntrackedTest(unittest.TestCase):
    QUERIES = [
        gsc_row("Schoenen  Kopen", clicks=3, impressions=500, position=8),
        gsc_row("sneakers", clicks=1, impressions=400, position=12),
        gsc_row("laarzen", clicks=0, impressions=49, position=8),   # te weinig vertoningen
        gsc_row("sandalen", clicks=0, impressions=900, position=31),  # buiten top 30
        gsc_row("slippers", clicks=0, impressions=60, position=30),
    ]

    def test_ok_excludes_tracked(self):
        result = insights.untracked(self.QUERIES, 28, "ok", [{"name": "schoenen kopen"}, {"name": "x"},
                                                             {"name": "X "}])
        self.assertEqual(result["state"], "ok")
        self.assertEqual([r["query"] for r in result["rows"]], ["sneakers", "slippers"])
        self.assertEqual(result["tracked_keywords"], 2)
        self.assertEqual(result["rows"][0], {"query": "sneakers", "impressions": 400, "clicks": 1, "position": 12.0})

    def test_not_tracked_shows_top_queries(self):
        result = insights.untracked(self.QUERIES, 28, "not_tracked", [])
        self.assertEqual(result["state"], "prt_not_tracked")
        self.assertEqual([r["query"] for r in result["rows"]], ["Schoenen  Kopen", "sneakers", "slippers"])
        self.assertTrue(result["message"])

    def test_not_configured_and_error_have_no_rows(self):
        result = insights.untracked(self.QUERIES, 28, "not_configured", [])
        self.assertEqual((result["state"], result["rows"], result["total"]), ("prt_not_configured", [], 0))
        result = insights.untracked(self.QUERIES, 28, "error", [], "Posities niet opgehaald: kapot")
        self.assertEqual((result["state"], result["message"], result["rows"]),
                         ("prt_error", "Posities niet opgehaald: kapot", []))


class TotalsTest(unittest.TestCase):
    def test_totals(self):
        self.assertEqual(insights.totals_of([{"keys": [], "clicks": 12.0, "impressions": 340.0,
                                              "ctr": 0.035294, "position": 7.26}]),
                         {"clicks": 12, "impressions": 340, "ctr": 0.0353, "position": 7.3})
        self.assertEqual(insights.totals_of([]), {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": None})


# --- ophalen, toestanden en cache --------------------------------------------------------

class FakeGsc:
    """Nep-Search Console: antwoorden en fouten per aanroep, met een logboek."""

    def __init__(self):
        self.lock = threading.Lock()
        self.calls: list[tuple[str, str]] = []
        self.errors: dict[str, Exception] = {}
        self.forbidden_sites: set[str] = set()
        self.data = {
            "totals": [gsc_row(clicks=120, impressions=4000, position=8.4)],
            "totals_previous": [gsc_row(clicks=150, impressions=4200, position=8.1)],
            "query_page": ([gsc_row("schoenen", "https://klant.nl/a", clicks=0, impressions=1000, position=4)],
                           False),
            "pages": [gsc_row("https://klant.nl/a", clicks=10, impressions=1000, position=4)],
            "pages_previous": [gsc_row("https://klant.nl/a", clicks=40, impressions=1000, position=4)],
            "queries": [gsc_row("schoenen", clicks=0, impressions=1000, position=4)],
        }

    def _answer(self, name, site_url):
        with self.lock:
            self.calls.append((name, site_url))
        if site_url in self.forbidden_sites:
            raise SearchConsoleServiceError("Geen toegang", code="forbidden")
        if name in self.errors:
            raise self.errors[name]
        return self.data[name]

    def analytics(self, site_url, start, end, *, dimensions=(), row_limit=1, service=None):
        assert service is not None
        prev = "_previous" if (start, end) == PREVIOUS else ""
        if not dimensions:
            return self._answer(f"totals{prev}", site_url)
        if dimensions == ("page",):
            return self._answer(f"pages{prev}", site_url)
        assert dimensions == ("query",) and not prev
        return self._answer("queries", site_url)

    def analytics_all(self, site_url, start, end, *, dimensions, page_size, max_rows, service=None):
        assert dimensions == ("query", "page") and service is not None
        return self._answer("query_page", site_url)

    def names(self):
        return sorted(name for name, _ in self.calls)


class InsightsTest(unittest.TestCase):
    def setUp(self):
        insights.clear_cache()
        self.addCleanup(insights.clear_cache)
        self.fake = FakeGsc()
        self.sites = self._patch(insights.gsc_sites, "cached_sites", Mock(return_value=sites(SITE)))
        self.configured = self._patch(insights.gsc, "is_configured", Mock(return_value=True))
        self.services = self._patch(insights.gsc, "get_service", Mock(side_effect=lambda: object()))
        self._patch(insights.gsc, "search_analytics", self.fake.analytics)
        self._patch(insights.gsc, "search_analytics_all", self.fake.analytics_all)
        self.prt = self._patch(insights, "organic_rows",
                               Mock(return_value=("ok", [{"name": "iets anders"}], None)))
        self._patch(gsc_enrich, "settings", PERIOD_SETTINGS)
        self._patch(insights, "settings", SimpleNamespace(gsc_clicks_drop_warn_pct=20))
        self.customer = SimpleNamespace(gsc_property=None, base_url="https://www.klant.nl/", name="Klant B.V.",
                                        domain="klant.nl")

    def _patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def run_insights(self, days=28):
        return insights.customer_insights(self.customer, days, today=TODAY)

    def test_ok(self):
        result = self.run_insights()
        self.assertEqual((result["state"], result["message"]), ("ok", None))
        self.assertEqual((result["property"], result["property_source"]), (SITE, "auto"))
        self.assertEqual(result["period"], {"start": "2026-10-26", "end": "2026-11-22", "days": 28})
        self.assertEqual(result["previous"], {"start": "2026-09-28", "end": "2026-10-25", "days": 28})
        self.assertEqual(result["totals"], {"clicks": 120, "impressions": 4000, "ctr": 0.03, "position": 8.4})
        self.assertEqual(result["totals_previous"]["clicks"], 150)
        self.assertEqual([r["query"] for r in result["opportunities"]["rows"]], ["schoenen"])
        self.assertEqual(result["untracked"]["state"], "ok")
        self.assertEqual([r["query"] for r in result["untracked"]["rows"]], ["schoenen"])
        self.assertEqual([r["page"] for r in result["declining"]["rows"]], ["https://klant.nl/a"])
        self.assertIsNotNone(result["fetched_at"])
        self.assertEqual(self.fake.names(), ["pages", "pages_previous", "queries", "query_page", "totals",
                                             "totals_previous"])
        # ProRankTracker krijgt een eigen client met korte timeout.
        args, kwargs = self.prt.call_args
        self.assertEqual(args, ("https://www.klant.nl/",))
        self.assertEqual(kwargs["client"].timeout.read, insights.PRT_TIMEOUT_SECONDS)
        self.assertTrue(kwargs["client"].is_closed)
        # Response-schema accepteert het antwoord.
        from app.features.customers.schemas import CustomerSearchConsoleInsightsResponse
        CustomerSearchConsoleInsightsResponse(**result)

    def test_manual_property(self):
        self.customer.gsc_property = "https://www.klant.nl/"
        self.sites.return_value = sites(SITE, "https://www.klant.nl/")
        result = self.run_insights()
        self.assertEqual((result["state"], result["property"], result["property_source"]),
                         ("ok", "https://www.klant.nl/", "manual"))

    def test_not_configured(self):
        self.configured.return_value = False
        result = self.run_insights()
        self.assertEqual(result["state"], "not_configured")
        self.assertIsNone(result["totals"])
        self.sites.assert_not_called()

    def test_sites_errors(self):
        for code, state in (("token_expired", "token_expired"), ("gsc_error", "error")):
            with self.subTest(code=code):
                self.sites.side_effect = SearchConsoleServiceError("Kapot", code=code)
                result = self.run_insights()
                self.assertEqual(result["state"], state)
        self.assertEqual(result["message"], "Kapot")

    def test_no_property(self):
        self.sites.return_value = sites("sc-domain:ander.nl")
        result = self.run_insights()
        self.assertEqual((result["state"], result["property"]), ("no_property", None))
        self.assertEqual(self.fake.calls, [])

    def test_token_expired_on_totals(self):
        self.fake.errors["totals"] = SearchConsoleServiceError("verlopen", code="token_expired")
        result = self.run_insights()
        self.assertEqual(result["state"], "token_expired")
        self.assertIn("gsc_authorize.py", result["message"])
        self.assertEqual(self.sites.call_count, 1)  # geen verse lijst bij een verlopen token

    def test_manual_property_gone_after_forbidden(self):
        self.customer.gsc_property = "sc-domain:weg.nl"
        self.fake.forbidden_sites.add("sc-domain:weg.nl")
        result = self.run_insights()
        self.assertEqual((result["state"], result["property"], result["property_source"]),
                         ("property_inaccessible", "sc-domain:weg.nl", "manual"))
        self.sites.assert_called_with(refresh=True)

    def test_manual_property_still_listed_is_error(self):
        self.customer.gsc_property = SITE
        self.fake.forbidden_sites.add(SITE)
        result = self.run_insights()
        self.assertEqual((result["state"], result["message"]), ("error", "Geen toegang"))

    def test_auto_property_gone_after_forbidden(self):
        self.fake.forbidden_sites.add(SITE)
        self.sites.side_effect = [sites(SITE), sites("sc-domain:ander.nl")]
        result = self.run_insights()
        self.assertEqual((result["state"], result["property"]), ("no_property", None))

    def test_auto_property_replaced_after_forbidden(self):
        self.fake.forbidden_sites.add(SITE)
        self.sites.side_effect = [sites(SITE), sites("https://www.klant.nl/")]
        result = self.run_insights()
        self.assertEqual((result["state"], result["property"], result["property_source"]),
                         ("ok", "https://www.klant.nl/", "auto"))

    def test_failed_sections_are_unavailable_and_not_cached(self):
        error = SearchConsoleServiceError("Quotum", code="rate_limited")
        self.fake.errors.update(query_page=error, queries=error, pages_previous=error, totals_previous=error)
        result = self.run_insights()
        self.assertEqual(result["state"], "ok")
        self.assertIsNone(result["totals_previous"])
        for name in ("opportunities", "untracked", "declining"):
            with self.subTest(section=name):
                self.assertEqual(result[name]["state"], "unavailable")
                self.assertIn("Quotum", result[name]["message"])
                self.assertEqual(result[name]["rows"], [])
        from app.features.customers.schemas import CustomerSearchConsoleInsightsResponse
        CustomerSearchConsoleInsightsResponse(**result)
        calls = len(self.fake.calls)
        self.run_insights()
        self.assertGreater(len(self.fake.calls), calls)

    def test_prt_states_pass_through(self):
        self.prt.return_value = ("error", [], "Posities niet opgehaald uit ProRankTracker: kapot")
        result = self.run_insights()
        self.assertEqual(result["untracked"]["state"], "prt_error")
        # Een PRT-fout wordt niet bewaard.
        self.run_insights()
        self.assertEqual(self.prt.call_count, 2)

    def test_cache(self):
        first = self.run_insights()
        calls = len(self.fake.calls)
        second = self.run_insights()
        self.assertEqual(second, first)
        self.assertEqual(len(self.fake.calls), calls)
        self.assertEqual(self.prt.call_count, 1)
        # Een andere periode is een andere sleutel.
        self.run_insights(days=7)
        self.assertGreater(len(self.fake.calls), calls)
        # Het bewaarde antwoord is een kopie: aanpassen raakt de cache niet.
        second["opportunities"]["rows"].clear()
        self.assertEqual(len(self.run_insights()["opportunities"]["rows"]), 1)
        insights.clear_cache()
        calls = len(self.fake.calls)
        self.run_insights()
        self.assertGreater(len(self.fake.calls), calls)

    def test_cache_expires_and_is_bounded(self):
        self.run_insights()
        with patch.object(insights.time, "monotonic", return_value=insights.time.monotonic() + 3601):
            calls = len(self.fake.calls)
            self.run_insights()
            self.assertGreater(len(self.fake.calls), calls)
        for i in range(insights.CACHE_MAX_ITEMS + 5):
            insights._cache_put(("p", i), {"x": i})
        self.assertEqual(len(insights._cache), insights.CACHE_MAX_ITEMS)

    def test_invalid_days(self):
        with self.assertRaises(ValueError):
            self.run_insights(days=30)


class SitesCacheTest(unittest.TestCase):
    def setUp(self):
        gsc_sites.clear_cache()
        self.addCleanup(gsc_sites.clear_cache)

    def test_cached_and_refresh(self):
        with patch.object(gsc_sites.gsc, "list_sites", Mock(side_effect=[sites("a"), sites("b")])) as listing:
            self.assertEqual(gsc_sites.cached_sites(), sites("a"))
            self.assertEqual(gsc_sites.cached_sites(), sites("a"))
            self.assertEqual(gsc_sites.cached_sites(refresh=True), sites("b"))
            self.assertEqual(listing.call_count, 2)


# --- endpoint ----------------------------------------------------------------------------

class EndpointTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.customer_id = str(uuid.uuid4())
        now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
        with self.Session() as db:
            db.add(CustomerWebsite(id=self.customer_id, name="Klant", base_url="https://klant.nl/",
                                   domain="klant.nl", created_by="user-1", created_at=now, updated_at=now))
            db.commit()
        app = FastAPI()
        app.include_router(router)

        def override_db():
            with self.Session() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_user_id] = lambda: "user-1"
        self.client = TestClient(app)
        patcher = patch.object(insights.gsc, "is_configured", Mock(return_value=False))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ok_shape(self):
        response = self.client.get(f"/api/customers/{self.customer_id}/search-console-insights")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {
            "state", "message", "days", "property", "property_source", "fetched_at", "period", "previous",
            "totals", "totals_previous", "opportunities", "untracked", "declining",
        })
        self.assertEqual((body["state"], body["days"], body["period"]["days"]), ("not_configured", 28, 28))

    def test_days(self):
        response = self.client.get(f"/api/customers/{self.customer_id}/search-console-insights?days=90")
        self.assertEqual(response.json()["days"], 90)
        for value in ("30", "abc"):
            with self.subTest(days=value):
                response = self.client.get(f"/api/customers/{self.customer_id}/search-console-insights?days={value}")
                self.assertEqual(response.status_code, 422)

    def test_unknown_customer_is_404(self):
        response = self.client.get("/api/customers/onbekend/search-console-insights")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Klant niet gevonden.")


if __name__ == "__main__":
    unittest.main()
