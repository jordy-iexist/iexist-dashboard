"""Search Console-verrijking (fase 4): property-keuze, periodes, snapshot en URL-inspectie."""
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.features.launch_checklist.services import gsc_enrich
from app.services.search_console.client import SearchConsoleServiceError

SETTINGS = SimpleNamespace(gsc_period_days=90, gsc_data_lag_days=3, gsc_row_limit=3)


def sites(*urls):
    return [{"site_url": u, "permission": "siteOwner"} for u in urls]


def row(key, clicks, impressions=100, position=5.0):
    return {"keys": [key], "clicks": float(clicks), "impressions": float(impressions),
            "ctr": clicks / impressions, "position": position}


class PropertyTest(unittest.TestCase):
    def test_domain_property_of_host_wins(self):
        found = gsc_enrich.match_properties("https://www.klant.nl/", sites(
            "https://www.klant.nl/", "sc-domain:klant.nl", "http://klant.nl/", "sc-domain:ander.nl",
        ))
        self.assertEqual(found, ["sc-domain:klant.nl", "https://www.klant.nl/", "http://klant.nl/"])

    def test_url_prefix_prefers_https_and_same_www_variant(self):
        found = gsc_enrich.match_properties("https://klant.nl", sites(
            "http://klant.nl/", "https://www.klant.nl/", "https://klant.nl/", "https://klant.nl/blog/",
        ))
        self.assertEqual(found, ["https://klant.nl/", "https://www.klant.nl/", "http://klant.nl/"])

    def test_subdomain_prefers_own_property_over_parent_domain(self):
        found = gsc_enrich.match_properties("https://shop.klant.nl/", sites(
            "sc-domain:klant.nl", "https://shop.klant.nl/",
        ))
        self.assertEqual(found, ["https://shop.klant.nl/", "sc-domain:klant.nl"])
        self.assertEqual(gsc_enrich.match_properties("https://nietklant.nl/", sites("sc-domain:klant.nl")), [])

    def test_resolve_manual_auto_and_none(self):
        available = sites("sc-domain:klant.nl")
        self.assertEqual(gsc_enrich.resolve_property(" https://www.klant.nl/ ", "https://klant.nl", available),
                         ("https://www.klant.nl/", "manual"))
        self.assertEqual(gsc_enrich.resolve_property(None, "https://klant.nl", available),
                         ("sc-domain:klant.nl", "auto"))
        self.assertEqual(gsc_enrich.resolve_property("", "https://onbekend.nl", available), (None, None))


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(gsc_enrich, "settings", SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_periods(self):
        spans = gsc_enrich.periods(date(2026, 11, 12))
        self.assertEqual(spans["current"], (date(2026, 8, 12), date(2026, 11, 9)))
        self.assertEqual(spans["previous"], (date(2026, 5, 14), date(2026, 8, 11)))
        self.assertEqual(spans["last_year"], (date(2025, 8, 13), date(2025, 11, 10)))
        self.assertEqual((spans["current"][1] - spans["current"][0]).days + 1, 90)

    def test_merge_rows_marks_unknown_when_truncated(self):
        # Vorige lijst is afgekapt (3 = row_limit): "nieuw" heeft dan geen bekende vorige waarde.
        merged = gsc_enrich._merge_rows(
            [row("a", 10), row("nieuw", 4)],
            [row("a", 6), row("b", 5), row("c", 3)],
            row_limit=3,
        )
        by_key = {r["key"]: r for r in merged}
        self.assertEqual([r["key"] for r in merged][:2], ["a", "nieuw"])
        self.assertEqual((by_key["a"]["clicks"], by_key["a"]["clicks_prev"]), (10, 6))
        self.assertIsNone(by_key["nieuw"]["clicks_prev"])
        # Huidige lijst is compleet (2 < 3): "b" is echt naar nul gegaan.
        self.assertEqual((by_key["b"]["clicks"], by_key["b"]["clicks_prev"]), (0, 5))

    def test_fetch_snapshot_collects_data_and_errors(self):
        def analytics(site_url, start, end, *, dimensions=(), row_limit=1, service=None):
            if dimensions == ("page",):
                raise SearchConsoleServiceError("tijdelijk", code="gsc_error")
            if dimensions == ("query",):
                return [row("schoenen", 8)] if start == date(2026, 8, 12) else [row("schoenen", 5)]
            return [{"keys": [], "clicks": 120.0, "impressions": 4000.0, "ctr": 0.03, "position": 11.24}]

        with patch.object(gsc_enrich.gsc, "search_analytics", side_effect=analytics), \
                patch.object(gsc_enrich.gsc, "list_sitemaps", return_value=[{"path": "s", "errors": 0, "warnings": 0}]):
            snapshot = gsc_enrich.fetch_snapshot("sc-domain:klant.nl", "auto", service=object(),
                                                 today=date(2026, 11, 12))
        self.assertEqual(snapshot["totals"], {"clicks": 120, "impressions": 4000, "ctr": 0.03, "position": 11.2})
        self.assertEqual(snapshot["period"], {"start": "2026-08-12", "end": "2026-11-09", "days": 90})
        self.assertEqual(snapshot["queries"][0]["clicks_prev"], 5)
        self.assertEqual(snapshot["pages"], [])
        self.assertEqual(len(snapshot["sitemaps"]), 1)
        self.assertEqual(len(snapshot["errors"]), 2)  # pagina's nu en vorige periode
        self.assertTrue(gsc_enrich.has_data(snapshot))

    def test_fetch_snapshot_stops_on_fatal_error(self):
        calls = []

        def analytics(*args, **kwargs):
            calls.append(args)
            raise SearchConsoleServiceError("geen toegang", code="forbidden")

        with patch.object(gsc_enrich.gsc, "search_analytics", side_effect=analytics), \
                patch.object(gsc_enrich.gsc, "list_sitemaps") as sitemaps:
            snapshot = gsc_enrich.fetch_snapshot("sc-domain:vreemd.nl", "manual", service=object())
        self.assertEqual(len(calls), 1)
        sitemaps.assert_not_called()
        self.assertEqual(len(snapshot["errors"]), 1)
        self.assertFalse(gsc_enrich.has_data(snapshot))
        self.assertFalse(gsc_enrich.has_data(None))


class InspectionTest(unittest.TestCase):
    def test_classify(self):
        classify = gsc_enrich.classify_inspection
        self.assertEqual(classify({"verdict": "PASS", "coverage_state": "Ingediend en geïndexeerd"})[0], "indexed")
        self.assertEqual(classify({"verdict": "FAIL", "robots_txt_state": "DISALLOWED"}),
                         ("blocked", "geblokkeerd door robots.txt"))
        self.assertEqual(classify({"verdict": "FAIL", "indexing_state": "BLOCKED_BY_META_TAG"}),
                         ("blocked", "noindex in de meta-tag"))
        self.assertEqual(classify({"verdict": "FAIL", "page_fetch_state": "SOFT_404"}), ("blocked", "soft 404"))
        self.assertEqual(
            classify({"verdict": "NEUTRAL", "page_fetch_state": "SUCCESSFUL",
                      "coverage_state": "Gecrawld - momenteel niet geïndexeerd"}),
            ("not_indexed", "Gecrawld - momenteel niet geïndexeerd"),
        )

    def test_inspect_pages_counts_and_stops_on_quota(self):
        def inspect(site_url, url, *, service=None):
            if url.endswith("/c"):
                raise SearchConsoleServiceError("quotum", code="rate_limited")
            return {"url": url, "verdict": "PASS" if url.endswith("/a") else "NEUTRAL",
                    "coverage_state": "URL is onbekend bij Google"}

        with patch.object(gsc_enrich.gsc, "inspect_url", side_effect=inspect) as mocked:
            result = gsc_enrich.inspect_pages(
                "sc-domain:klant.nl",
                ["https://klant.nl/a", "https://klant.nl/b", "https://klant.nl/c", "https://klant.nl/d"],
                service=object(),
            )
        self.assertEqual(mocked.call_count, 3)
        self.assertEqual((result["requested"], result["checked"], result["indexed"]), (4, 2, 1))
        self.assertEqual(result["rows"][1]["state"], "not_indexed")
        self.assertEqual(len(result["errors"]), 1)

    def test_inspect_pages_respects_stop(self):
        with patch.object(gsc_enrich.gsc, "inspect_url") as mocked:
            result = gsc_enrich.inspect_pages("p", ["https://klant.nl/a"], service=object(),
                                              should_continue=lambda: False)
        mocked.assert_not_called()
        self.assertEqual(result["checked"], 0)


if __name__ == "__main__":
    unittest.main()
