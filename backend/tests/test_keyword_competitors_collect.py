import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.features.keywords.schemas import (
    Raw,
    RawCompetitor,
    RawMetrics,
    RawPrt,
    RawTop10,
    TrackedKeyword,
    TrafficPoint,
)
from app.features.keywords.services import collect
from app.features.keywords.services.collect import UnitBudget
from app.services.ahrefs.client import AhrefsResult, AhrefsServiceError

SETTINGS = SimpleNamespace(ahrefs_competitors_keywords_per_domain=150)


def prt_row(name, rank, volume):
    return {"name": name, "rank": rank, "localmonthlysearches": volume, "monthagorank": None,
            "matchedurl": None, "term_type": "organic", "is_ai_term": 0}


def comp_row(domain, common, share=1.0, dr=30.0):
    return {"competitor_domain": domain, "domain_rating": dr, "keywords_common": common,
            "keywords_competitor": 100, "keywords_target": 50, "share": share}


def serp(*urls):
    rows = [{"position": i + 1, "url": url, "type": ["organic"], "title": f"Titel {url}"}
            for i, url in enumerate(urls)]
    rows.append({"position": 1, "url": None, "type": ["ai_overview"], "title": None})
    return AhrefsResult(rows=rows, units=100)


TWELVE_TRACKED = [prt_row(f"zoekwoord {i}", i + 1, 1000 - i * 10) for i in range(12)]


class CollectTestCase(unittest.TestCase):
    def setUp(self):
        self.calls: dict[str, list] = {}
        patches = {
            "organic_rows": patch.object(collect.rankings, "organic_rows"),
            "organic_competitors": patch.object(collect.ahrefs, "organic_competitors"),
            "serp_overview": patch.object(collect.ahrefs, "serp_overview"),
            "domains_metrics": patch.object(collect.ahrefs, "domains_metrics"),
            "metrics_history": patch.object(collect.ahrefs, "metrics_history"),
            "top10_keywords": patch.object(collect.ahrefs, "top10_keywords"),
        }
        self.mocks = {}
        for name, patcher in patches.items():
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        settings_patch = patch.object(collect, "settings", SETTINGS)
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        self.mocks["organic_rows"].return_value = ("ok", TWELVE_TRACKED, None)
        self.mocks["serp_overview"].side_effect = lambda kw, **kw_args: serp(
            "https://www.klant.nl/a", "https://blog.klant.nl/b", "https://rivaal.nl/x", "https://www.ander.nl/"
        )


class CollectCandidatesTests(CollectTestCase):
    def test_prt_dedupes_on_keyword_and_best_rank_wins(self):
        self.mocks["organic_rows"].return_value = ("ok", [
            prt_row("SEO Bureau", 14, 900), prt_row("seo  bureau", 6, 880), prt_row("lokaal seo", "NTH", 50),
        ], None)
        self.mocks["organic_competitors"].return_value = AhrefsResult(
            rows=[comp_row(f"c{i}.nl", 20) for i in range(5)], units=120
        )
        raw = collect.collect_candidates(
            base_url="https://www.klant.nl", country="nl", manual_domains=[], previous=None,
            budget=UnitBudget(5000),
        )
        rows = {r.keyword.casefold(): r for r in raw.prt.rows}
        self.assertEqual(len(raw.prt.rows), 2)
        self.assertEqual(raw.prt.state, "ok")
        self.assertEqual((rows["seo  bureau"].rank, rows["seo  bureau"].volume), (6, 880))
        self.assertIsNone(rows["lokaal seo"].rank)
        self.assertEqual(rows["lokaal seo"].volume, 50)

    def test_prt_state_without_raising(self):
        self.mocks["organic_rows"].return_value = ("error", [], "Posities niet opgehaald")
        self.mocks["organic_competitors"].return_value = AhrefsResult(rows=[], units=50)
        raw = collect.collect_candidates(
            base_url="klant.nl", country="nl", manual_domains=[], previous=None, budget=UnitBudget(5000)
        )
        self.assertEqual((raw.prt.state, raw.prt.message), ("error", "Posities niet opgehaald"))
        self.assertIsNone(raw.serps)  # geen aanvulling zonder PRT

    def test_enough_competitors_skips_sample(self):
        self.mocks["organic_competitors"].return_value = AhrefsResult(rows=[
            comp_row("www.klant.nl", 999), comp_row("shop.klant.nl", 500),
            *[comp_row(f"WWW.C{i}.nl", 5 + i, share=4.5) for i in range(5)], comp_row("klein.nl", 2),
        ], units=120)
        budget = UnitBudget(5000)
        raw = collect.collect_candidates(
            base_url="https://klant.nl/", country="nl", manual_domains=[], previous=None, budget=budget
        )
        self.assertEqual([c.domain for c in raw.competitors], ["c0.nl", "c1.nl", "c2.nl", "c3.nl", "c4.nl", "klein.nl"])
        self.assertEqual(raw.competitors[0].share, 4.5)
        self.assertIsNone(raw.serps)
        self.mocks["serp_overview"].assert_not_called()
        self.assertEqual(budget.spent, 120)
        self.assertIsNotNone(raw.fetched_at.tzinfo)
        args, kwargs = self.mocks["organic_competitors"].call_args
        self.assertEqual(args, ("klant.nl",))
        self.assertEqual(kwargs, {"country": "nl", "limit": 20})

    def test_too_few_competitors_samples_top_volume_serps(self):
        self.mocks["organic_competitors"].return_value = AhrefsResult(rows=[
            *[comp_row(f"c{i}.nl", 10) for i in range(4)], comp_row("klein.nl", 4),
        ], units=120)
        budget = UnitBudget(5000)
        raw = collect.collect_candidates(
            base_url="klant.nl", country="nl", manual_domains=[], previous=None, budget=budget
        )
        self.assertEqual(self.mocks["serp_overview"].call_count, 10)
        sampled = [c.args[0] for c in self.mocks["serp_overview"].call_args_list]
        self.assertEqual(sampled, [f"zoekwoord {i}" for i in range(10)])  # hoogste volume eerst
        kwargs = self.mocks["serp_overview"].call_args.kwargs
        self.assertEqual(kwargs["top_positions"], 10)
        self.assertEqual(kwargs["fields"], ("position", "url", "type", "title"))
        self.assertEqual(kwargs["country"], "nl")
        hits = raw.serps["zoekwoord 0"]
        self.assertEqual([(h.domain, h.position) for h in hits], [("rivaal.nl", 3), ("ander.nl", 4)])
        self.assertEqual(hits[0].title, "Titel https://rivaal.nl/x")
        self.assertEqual(budget.spent, 120 + 10 * 100)

    def test_sample_needs_minimum_tracked_keywords(self):
        self.mocks["organic_rows"].return_value = ("ok", TWELVE_TRACKED[:2], None)
        self.mocks["organic_competitors"].return_value = AhrefsResult(rows=[], units=50)
        raw = collect.collect_candidates(
            base_url="klant.nl", country="nl", manual_domains=[], previous=None, budget=UnitBudget(5000)
        )
        self.assertIsNone(raw.serps)
        self.mocks["serp_overview"].assert_not_called()

    def test_sample_stops_at_budget(self):
        self.mocks["organic_competitors"].return_value = AhrefsResult(rows=[], units=120)
        budget = UnitBudget(120 + 2 * 100 + 50)
        raw = collect.collect_candidates(
            base_url="klant.nl", country="nl", manual_domains=[], previous=None, budget=budget
        )
        self.assertEqual(self.mocks["serp_overview"].call_count, 2)
        self.assertEqual(len(raw.serps), 2)
        self.assertEqual(budget.spent, 320)
        self.assertEqual(budget.skipped, ["8 van 10 SERP's voor de aanvulling via gevolgde zoekwoorden"])

    def test_failed_serp_skips_only_that_keyword(self):
        self.mocks["organic_competitors"].return_value = AhrefsResult(rows=[], units=50)

        def flaky(keyword, **kwargs):
            if keyword == "zoekwoord 1":
                raise AhrefsServiceError("stuk", code="ahrefs_error")
            return serp("https://rivaal.nl/")

        self.mocks["serp_overview"].side_effect = flaky
        raw = collect.collect_candidates(
            base_url="klant.nl", country="nl", manual_domains=[], previous=None, budget=UnitBudget(5000)
        )
        self.assertEqual(len(raw.serps), 9)
        self.assertNotIn("zoekwoord 1", raw.serps)

    def test_step_a_error_propagates(self):
        self.mocks["organic_competitors"].side_effect = AhrefsServiceError("nope", code="forbidden")
        with self.assertRaises(AhrefsServiceError):
            collect.collect_candidates(
                base_url="klant.nl", country="nl", manual_domains=[], previous=None, budget=UnitBudget(5000)
            )

    def test_manual_domains_outside_a_fetched_in_one_call(self):
        def competitors(target, **kwargs):
            if kwargs.get("domains"):
                return AhrefsResult(rows=[comp_row("nieuw.nl", 3, share=0.4)], units=50)
            return AhrefsResult(rows=[comp_row(f"c{i}.nl", 10) for i in range(5)], units=120)

        self.mocks["organic_competitors"].side_effect = competitors
        budget = UnitBudget(5000)
        raw = collect.collect_candidates(
            base_url="klant.nl", country="nl",
            manual_domains=["https://www.nieuw.nl/", "c1.nl", "onbekend.nl", "klant.nl"],
            previous=None, budget=budget,
        )
        second = self.mocks["organic_competitors"].call_args_list[1]
        self.assertEqual(second.kwargs["domains"], ["nieuw.nl", "onbekend.nl"])
        by_domain = {c.domain: c for c in raw.competitors}
        self.assertEqual(by_domain["nieuw.nl"].keywords_common, 3)
        self.assertEqual(by_domain["onbekend.nl"].keywords_common, 0)  # bewaard als 0/0
        self.assertEqual(budget.spent, 170)

    def test_reuse_fetches_only_missing_parts(self):
        stamp = datetime(2026, 11, 1, tzinfo=timezone.utc)
        previous = Raw(
            fetched_at=stamp,
            prt=RawPrt(state="ok", rows=[TrackedKeyword(keyword="seo", rank=3, volume=100)]),
            competitors=[RawCompetitor(domain="c0.nl", keywords_common=10)],
            serps={},
        )
        self.mocks["organic_competitors"].return_value = AhrefsResult(
            rows=[comp_row("nieuw.nl", 7)], units=50
        )
        raw = collect.collect_candidates(
            base_url="klant.nl", country="nl", manual_domains=["nieuw.nl", "c0.nl"],
            previous=previous, budget=UnitBudget(5000),
        )
        self.mocks["organic_rows"].assert_not_called()
        self.mocks["serp_overview"].assert_not_called()
        self.mocks["organic_competitors"].assert_called_once()
        self.assertEqual(self.mocks["organic_competitors"].call_args.kwargs["domains"], ["nieuw.nl"])
        self.assertEqual([c.domain for c in raw.competitors], ["c0.nl", "nieuw.nl"])
        self.assertEqual(raw.fetched_at, stamp)
        self.assertEqual(raw.serps, {})
        self.assertEqual(len(previous.competitors), 1)  # invoer ongewijzigd

    def test_budget_rules(self):
        budget = UnitBudget(100)
        self.assertTrue(budget.allows(100))
        budget.add(60)
        self.assertFalse(budget.allows(50))
        self.assertTrue(budget.allows(40))
        budget.add(None)
        self.assertEqual(budget.spent, 60)


class CollectMetricsTests(CollectTestCase):
    def setUp(self):
        super().setUp()
        self.mocks["domains_metrics"].side_effect = lambda domains, **kw: AhrefsResult(rows=[
            {"index": i, "url": f"{d}/", "target": d, "domain_rating": 40.0, "org_keywords": 500,
             "org_keywords_1_3": 20, "org_keywords_4_10": 30, "org_traffic": 900}
            for i, d in enumerate(domains) if d != "leeg.nl"
        ], units=50)
        self.mocks["metrics_history"].return_value = AhrefsResult(rows=[
            {"date": "2026-11-01T00:00:00Z", "org_traffic": 1100},
            {"date": "2026-10-01T00:00:00Z", "org_traffic": 1000},
        ], units=50)
        self.mocks["top10_keywords"].side_effect = lambda d, **kw: AhrefsResult(
            rows=[{"keyword": f"{d} kw {i}", "best_position": 3} for i in range(150 if d == "groot.nl" else 20)],
            units=40,
        )

    def test_fetches_d_e_f_and_skips_existing(self):
        raw = Raw(metrics={"a.nl": RawMetrics(org_keywords=1)}, top10={"a.nl": RawTop10(keywords=["x"])})
        budget = UnitBudget(5000)
        out = collect.collect_metrics(
            raw, base_url="https://www.klant.nl", country="nl", domains=["a.nl", "groot.nl", "leeg.nl"],
            keyword_domains=["a.nl", "groot.nl"], budget=budget,
        )
        self.assertEqual(self.mocks["domains_metrics"].call_args.args[0], ["klant.nl", "groot.nl", "leeg.nl"])
        self.assertEqual(out.metrics["klant.nl"].org_keywords_4_10, 30)
        self.assertEqual(out.metrics["leeg.nl"], RawMetrics())
        self.assertEqual(out.metrics["a.nl"].org_keywords, 1)
        self.assertEqual([p.date for p in out.traffic_history], ["2026-10-01", "2026-11-01"])
        self.assertEqual(
            self.mocks["metrics_history"].call_args.kwargs["date_from"], collect._months_back(date.today(), 2)
        )
        called = [c.args[0] for c in self.mocks["top10_keywords"].call_args_list]
        self.assertEqual(called, ["klant.nl", "groot.nl"])
        self.assertEqual(self.mocks["top10_keywords"].call_args.kwargs["limit"], 150)
        self.assertTrue(out.top10["groot.nl"].truncated)
        self.assertFalse(out.top10["klant.nl"].truncated)
        self.assertEqual(budget.spent, 50 + 50 + 2 * 40)
        self.assertEqual(budget.skipped, [])
        self.assertEqual(raw.metrics.keys(), {"a.nl"})  # invoer ongewijzigd

    def test_empty_keyword_domains_skips_f_entirely(self):
        out = collect.collect_metrics(
            Raw(), base_url="klant.nl", country="nl", domains=["a.nl"], keyword_domains=[],
            budget=UnitBudget(5000),
        )
        self.mocks["top10_keywords"].assert_not_called()
        self.assertEqual(out.top10, {})

    def test_existing_history_not_refetched(self):
        raw = Raw(traffic_history=[TrafficPoint(date="2026-10-01", org_traffic=5)])
        collect.collect_metrics(
            raw, base_url="klant.nl", country="nl", domains=[], keyword_domains=[], budget=UnitBudget(5000)
        )
        self.mocks["metrics_history"].assert_not_called()

    def test_errors_and_budget_skip_steps(self):
        self.mocks["domains_metrics"].side_effect = AhrefsServiceError("kapot", code="ahrefs_error")
        # E (schatting 50, kost 50) past, de eerste top 10-lijst (schatting 300, kost 40) ook;
        # daarna 90 + 300 > 380, dus de tweede niet.
        budget = UnitBudget(380)
        out = collect.collect_metrics(
            Raw(), base_url="klant.nl", country="nl", domains=["a.nl"], keyword_domains=["b.nl"],
            budget=budget,
        )
        self.assertEqual(out.metrics, {})
        self.assertEqual(budget.skipped[0], "cijfers per domein (kapot)")
        self.assertIn("klant.nl", out.top10)
        self.assertNotIn("b.nl", out.top10)
        self.assertEqual(budget.skipped[1], "top 10-zoekwoorden van b.nl")

    def test_months_back(self):
        self.assertEqual(collect._months_back(date(2026, 11, 25), 2), date(2026, 9, 1))
        self.assertEqual(collect._months_back(date(2026, 1, 31), 2), date(2025, 11, 1))


class KeywordCheckTests(CollectTestCase):
    def test_checks_in_chunks_with_max_requests(self):
        chunk, most = collect.CHECK_CHUNK, collect.CHECK_MAX_REQUESTS
        raw = Raw(top10={
            "groot.nl": RawTop10(keywords=["al bekend"], truncated=True, checked=["al nagevraagd"]),
            "klein.nl": RawTop10(keywords=["x"], truncated=False),
        })
        keywords = ["Al Bekend", "al nagevraagd"] + [f"kw {i}" for i in range(chunk * most + 30)] + ["kw 0"]

        def found(domain, **kwargs):
            return AhrefsResult(
                rows=[{"keyword": k.upper(), "best_position": 5} for k in kwargs["keywords"] if k.endswith("0")],
                units=80,
            )

        self.mocks["top10_keywords"].side_effect = found
        budget = UnitBudget(5000)
        out = collect.collect_keyword_checks(raw, base_url="klant.nl", country="nl", keywords=keywords, budget=budget)

        calls = self.mocks["top10_keywords"].call_args_list
        self.assertEqual(len(calls), most)
        self.assertTrue(all(c.args[0] == "groot.nl" for c in calls))
        self.assertEqual([len(c.kwargs["keywords"]) for c in calls], [chunk] * most)
        self.assertEqual(calls[0].kwargs["limit"], chunk)
        self.assertEqual(calls[0].kwargs["keywords"][0], "kw 0")
        entry = out.top10["groot.nl"]
        self.assertEqual(len(entry.checked), 1 + chunk * most)
        self.assertEqual(entry.keywords, ["al bekend"] + [f"kw {i}" for i in range(chunk * most) if i % 10 == 0])
        self.assertEqual(out.top10["klein.nl"].checked, [])
        self.assertEqual(budget.spent, 80 * most)

    def test_check_stops_at_budget(self):
        raw = Raw(top10={"groot.nl": RawTop10(keywords=[], truncated=True)})
        self.mocks["top10_keywords"].return_value = AhrefsResult(rows=[], units=80)
        chunk = collect.CHECK_CHUNK
        # Ruimte voor de schatting van één deel (2 units per zoekwoord), niet voor een tweede.
        budget = UnitBudget(chunk * 2 + 30)
        out = collect.collect_keyword_checks(
            raw, base_url="klant.nl", country="nl", keywords=[f"kw {i}" for i in range(chunk * 2)], budget=budget
        )
        self.assertEqual(self.mocks["top10_keywords"].call_count, 1)
        self.assertEqual(len(out.top10["groot.nl"].checked), chunk)
        self.assertEqual(budget.skipped, ["nacontrole van de zoekwoorden van groot.nl"])


if __name__ == "__main__":
    unittest.main()
