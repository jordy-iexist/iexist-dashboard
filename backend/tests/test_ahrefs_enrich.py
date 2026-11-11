import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.db.models import LaunchScanPage
from app.features.launch_checklist.services import ahrefs_enrich, issues
from app.features.launch_checklist.services.ahrefs_enrich import Snapshot
from app.features.launch_checklist.services.inventory import PageRecord
from app.services.ahrefs import client as ahrefs_client

SETTINGS = SimpleNamespace(
    ahrefs_api_key="test-key",
    ahrefs_request_timeout_seconds=5.0,
    ahrefs_country="nl",
    ahrefs_top_pages_limit=200,
    ahrefs_backlink_pages_limit=200,
    ahrefs_broken_backlinks_limit=100,
    ahrefs_snapshot_ttl_days=7,
    ahrefs_value_min_traffic=50,
    ahrefs_value_min_refdomains=5,
    ahrefs_keyword_max_position=20,
)

TOP_PAGES = [
    {"url": "https://www.klant.nl/diensten/", "sum_traffic": 300, "keywords": 40,
     "top_keyword": "seo bureau", "top_keyword_best_position": 4, "top_keyword_volume": 900},
    # http-variant van dezelfde URL: verkeer telt op, het zoekwoord komt van de grootste.
    {"url": "http://www.klant.nl/diensten/", "sum_traffic": 20, "keywords": 3,
     "top_keyword": "bureau seo", "top_keyword_best_position": 30, "top_keyword_volume": 50},
    {"url": "https://www.klant.nl/oude-pagina", "sum_traffic": 80, "keywords": 5,
     "top_keyword": "oud zoekwoord", "top_keyword_best_position": 9, "top_keyword_volume": 200},
    {"url": "https://anderdomein.nl/x", "sum_traffic": 999},
]
BACKLINK_PAGES = [
    {"url_to": "https://www.klant.nl/", "refdomains_target": 60, "dofollow_to_target": 80},
    {"url_to": "https://www.klant.nl/diensten/", "refdomains_target": 7, "dofollow_to_target": 9},
]
BROKEN = [
    {"url_from": "https://blog.nl/a", "url_to": "https://www.klant.nl/weg", "domain_rating_source": 55,
     "anchor": "klant", "http_code_target": 404},
    {"url_from": "https://nieuws.nl/b", "url_to": "https://www.klant.nl/weg", "domain_rating_source": 41,
     "anchor": "hier", "http_code_target": 404},
]


def _api(fail: dict[str, int] | None = None):
    fail = fail or {}

    def handler(request: httpx.Request) -> httpx.Response:
        report = request.url.path.rsplit("/", 1)[-1]
        if report in fail:
            return httpx.Response(fail[report], json={"error": "geweigerd"})
        payload = {
            "batch-analysis": {"targets": [{"domain_rating": 34.0, "refdomains": 210, "org_traffic": 1800}]},
            "top-pages": {"pages": TOP_PAGES},
            "pages-by-backlinks": {"pages": BACKLINK_PAGES},
            "broken-backlinks": {"backlinks": BROKEN},
        }[report]
        return httpx.Response(200, json=payload, headers={"x-api-units-cost-total-actual": "100"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _record(url: str, status: int | None = 200, **extra) -> PageRecord:
    return PageRecord(url=url, path=url.split("klant.nl", 1)[-1] or "/", in_sitemap=True, status_code=status, **extra)


def _page(pid: str, path: str, **fields) -> LaunchScanPage:
    defaults = dict(
        id=pid, url=f"https://www.klant.nl{path}", path=path, in_sitemap=True, status_code=200,
        content_type="text/html", indexable=True, title="Een prima title van genoeg tekens hier",
        title_length=38, meta_description="x" * 100, meta_description_length=100, h1=["Kop"], h1_count=1,
        word_count=600, images_missing_alt=0, lang="nl",
    )
    return LaunchScanPage(**{**defaults, **fields})


class SettingsPatched(unittest.TestCase):
    def setUp(self):
        for module in (ahrefs_enrich, ahrefs_client, issues):
            patcher = patch.object(module, "settings", SETTINGS)
            patcher.start()
            self.addCleanup(patcher.stop)
        sleeper = patch.object(ahrefs_client.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)


class SnapshotTests(SettingsPatched):
    def test_match_key_ignores_www_scheme_and_trailing_slash(self):
        self.assertEqual(
            ahrefs_enrich.match_key("https://www.klant.nl/diensten/"),
            ahrefs_enrich.match_key("http://klant.nl/diensten"),
        )
        self.assertEqual(ahrefs_enrich.target_of("https://www.klant.nl/"), "klant.nl")

    def test_fetch_snapshot_combines_the_four_reports(self):
        snapshot = ahrefs_enrich.fetch_snapshot("https://www.klant.nl/", client=_api())

        self.assertEqual((snapshot.target, snapshot.country, snapshot.units), ("klant.nl", "nl", 400))
        self.assertEqual(snapshot.domain["domain_rating"], 34.0)
        self.assertEqual(snapshot.errors, [])
        diensten = snapshot.pages["klant.nl/diensten"]
        self.assertEqual(diensten["org_traffic"], 320)
        self.assertEqual(diensten["top_keyword"], "seo bureau")
        self.assertEqual(diensten["top_keyword_position"], 4)
        self.assertEqual(diensten["refdomains"], 7)
        self.assertEqual(diensten["url"], "https://www.klant.nl/diensten/")
        weg = snapshot.pages["klant.nl/weg"]
        self.assertEqual(weg["refdomains"], 2)
        self.assertEqual([b["url_from"] for b in weg["broken_backlinks"]], ["https://blog.nl/a", "https://nieuws.nl/b"])
        self.assertFalse(any("anderdomein" in key for key in snapshot.pages))
        self.assertFalse(any(k.startswith("_") for entry in snapshot.pages.values() for k in entry))

    def test_one_failing_report_does_not_stop_the_others(self):
        snapshot = ahrefs_enrich.fetch_snapshot("https://www.klant.nl/", client=_api({"top-pages": 400}))

        self.assertEqual(len(snapshot.errors), 1)
        self.assertIn("verkeer per pagina", snapshot.errors[0])
        self.assertEqual(snapshot.pages["klant.nl/"]["refdomains"], 60)
        self.assertNotIn("org_traffic", snapshot.pages["klant.nl/diensten"])

    def test_fatal_error_stops_further_calls(self):
        snapshot = ahrefs_enrich.fetch_snapshot("https://www.klant.nl/", client=_api({"batch-analysis": 401}))

        self.assertEqual(len(snapshot.errors), 1)
        self.assertEqual(snapshot.pages, {})


class MergeTests(SettingsPatched):
    def setUp(self):
        super().setUp()
        self.snapshot = ahrefs_enrich.fetch_snapshot("https://www.klant.nl/", client=_api())

    def test_merge_matches_pages_and_returns_unknown_urls(self):
        home = _record("https://www.klant.nl/")
        diensten = _record("https://klant.nl/diensten")
        other = _record("https://www.klant.nl/contact/")
        records = [home, diensten, other]

        unknown = ahrefs_enrich.merge_into_records(records, self.snapshot)

        self.assertEqual((home.refdomains, home.org_traffic), (60, None))
        self.assertEqual((diensten.org_traffic, diensten.refdomains), (320, 7))
        self.assertEqual(diensten.ahrefs["source"], "crawl")
        self.assertEqual(diensten.ahrefs["top_keyword"], "seo bureau")
        self.assertIsNone(other.ahrefs)
        # Meeste waarde eerst: /oude-pagina (80 bezoeken) vóór /weg (2 domeinen).
        self.assertEqual(unknown, ["https://www.klant.nl/oude-pagina", "https://www.klant.nl/weg"])

    def test_page_redirecting_to_a_known_url_gets_its_value(self):
        old = _record("https://www.klant.nl/services", status=301, final_url="https://www.klant.nl/diensten/")

        unknown = ahrefs_enrich.merge_into_records([old], self.snapshot)

        self.assertEqual(old.org_traffic, 320)
        self.assertNotIn("https://www.klant.nl/diensten/", unknown)

    def test_extra_records_lost_pages_and_summary(self):
        records = [_record("https://www.klant.nl/"), _record("https://www.klant.nl/diensten/")]
        ahrefs_enrich.merge_into_records(records, self.snapshot)
        gone = _record("https://www.klant.nl/weg", status=404)
        moved = _record(
            "https://www.klant.nl/oude-pagina", status=301, final_url="https://www.klant.nl/nieuw",
            redirect_chain=[
                {"url": "https://www.klant.nl/oude-pagina", "status": 301, "location": "https://www.klant.nl/nieuw"},
                {"url": "https://www.klant.nl/nieuw", "status": 200, "final": True},
            ],
        )
        ahrefs_enrich.mark_extra_records([gone, moved], self.snapshot)
        records += [gone, moved]

        self.assertEqual(gone.ahrefs["source"], "ahrefs")
        self.assertTrue(ahrefs_enrich.is_lost(gone))
        self.assertFalse(ahrefs_enrich.is_lost(moved))
        blocked = _record("https://www.klant.nl/x", status=403, refdomains=3)
        self.assertFalse(ahrefs_enrich.is_lost(blocked))

        summary = ahrefs_enrich.scan_summary(self.snapshot, records)
        self.assertEqual(summary["pages_with_traffic"], 2)
        self.assertEqual(summary["pages_with_backlinks"], 3)
        self.assertEqual(summary["extra_urls"], 2)
        self.assertEqual(summary["lost_value_urls"], 1)
        self.assertEqual(summary["units"], 400)
        self.assertIsNone(summary["reused_from"])

    def test_empty_snapshot_changes_nothing(self):
        record = _record("https://www.klant.nl/")
        empty = Snapshot(target="klant.nl", country="nl", fetched_at="2026-11-11T10:00:00+00:00")

        self.assertEqual(ahrefs_enrich.merge_into_records([record], empty), [])
        self.assertIsNone(record.ahrefs)


class IssueTests(SettingsPatched):
    def test_broken_page_with_backlinks_becomes_an_issue(self):
        page = _page("p1", "/weg", status_code=404, refdomains=2, org_traffic=30,
                     ahrefs={"source": "ahrefs", "broken_backlinks": [{"url_from": "https://blog.nl/a", "dr": 55}]})
        healthy = _page("p2", "/", refdomains=60)

        found = issues.generate_issues([page, healthy], None)

        backlinks = [i for i in found if i["issue_type"] == "broken_backlinks"]
        self.assertEqual(len(backlinks), 1)
        self.assertEqual(backlinks[0]["severity"], "hoog")
        self.assertEqual(backlinks[0]["page_id"], "p1")
        self.assertEqual(backlinks[0]["details"]["refdomains"], 2)
        self.assertEqual(backlinks[0]["details"]["backlinks"][0]["url_from"], "https://blog.nl/a")
        self.assertIn("status_4xx", [i["issue_type"] for i in found])

    def test_blocked_page_is_not_reported_as_broken_backlink(self):
        page = _page("p1", "/x", status_code=403, refdomains=9)
        self.assertEqual([i for i in issues.rule_backlinks([page], {})], [])

    def test_value_boost_raises_severity_one_step(self):
        valuable = _page("p1", "/diensten", org_traffic=320, refdomains=7, meta_description=None,
                         meta_description_length=None, title="Kort", title_length=4)
        plain = _page("p2", "/contact", org_traffic=10, meta_description=None, meta_description_length=None)

        found = issues.generate_issues([valuable, plain], None)
        by = {(i["page_id"], i["issue_type"]): i for i in found}

        self.assertEqual(by[("p1", "meta_missing")]["severity"], "hoog")
        self.assertEqual(by[("p1", "meta_missing")]["details"]["value_boost"],
                         {"org_traffic": 320, "refdomains": 7, "from": "middel"})
        short = by[("p1", "title_too_short")]
        self.assertEqual(short["severity"], "middel")
        self.assertEqual(short["details"]["value_boost"]["from"], "laag")
        self.assertEqual(short["details"]["title"], "Kort")
        self.assertEqual(by[("p2", "meta_missing")]["severity"], "middel")
        self.assertIsNone(by[("p2", "meta_missing")]["details"])

    def test_issue_that_is_already_high_keeps_severity_but_gets_the_tag(self):
        page = _page("p1", "/diensten", org_traffic=320, h1=[], h1_count=0)

        found = {i["issue_type"]: i for i in issues.generate_issues([page], None)}

        self.assertEqual(found["h1_missing"]["severity"], "hoog")
        self.assertIsNone(found["h1_missing"]["details"]["value_boost"]["from"])


class KeywordTests(SettingsPatched):
    def test_keyword_hint_reads_top_keyword(self):
        page = _page("p1", "/diensten", org_traffic=320,
                     ahrefs={"top_keyword": " seo  bureau ", "top_keyword_position": 4, "top_keyword_volume": 900})
        self.assertEqual(
            ahrefs_enrich.keyword_hint(page),
            {"keyword": "seo bureau", "position": 4, "volume": 900, "traffic": 320, "fixed": False},
        )
        self.assertIsNone(ahrefs_enrich.keyword_hint(_page("p2", "/x")))

    def test_ranking_needs_position_within_limit_and_traffic(self):
        self.assertTrue(ahrefs_enrich.is_ranking_keyword({"keyword": "a", "position": 20, "traffic": 3}))
        self.assertFalse(ahrefs_enrich.is_ranking_keyword({"keyword": "a", "position": 21, "traffic": 3}))
        self.assertFalse(ahrefs_enrich.is_ranking_keyword({"keyword": "a", "position": None, "traffic": 3}))
        # Positie 1 op de merknaam zonder verkeer: geen focuszoekwoord.
        self.assertFalse(ahrefs_enrich.is_ranking_keyword({"keyword": "merk", "position": 1, "traffic": 0}))
        self.assertFalse(ahrefs_enrich.is_ranking_keyword(None))

    def test_one_keyword_is_fixed_for_the_page_with_most_traffic(self):
        home = {"keyword": "Merk", "position": 1, "traffic": 70, "fixed": False}
        about = {"keyword": "merk", "position": 1, "traffic": 4, "fixed": False}
        contact = {"keyword": "merk", "position": 1, "traffic": 0, "fixed": False}
        service = {"keyword": "seo bureau", "position": 6, "traffic": 30, "fixed": False}
        far = {"keyword": "toeval", "position": 80, "traffic": 2, "fixed": False}

        ahrefs_enrich.mark_fixed_keywords([home, None, about, contact, service, far])

        self.assertEqual(
            [h["fixed"] for h in (home, about, contact, service, far)], [True, False, False, True, False]
        )

    def test_choose_keyword_order(self):
        hint = {"keyword": "seo bureau", "position": 4, "volume": 900, "traffic": 30, "fixed": True}
        low = {"keyword": "toeval", "position": 80, "volume": 10, "traffic": 1, "fixed": False}
        manual = {"focus_keyword": "eigen woord", "intent": "commercieel", "keyword_source": "manual"}
        carried = {"focus_keyword": "oud ahrefs", "intent": "informatief", "keyword_source": "ahrefs"}
        same = {"focus_keyword": "seo bureau", "intent": "commercieel", "keyword_source": "ahrefs"}

        # Handmatig wint altijd.
        self.assertEqual(ahrefs_enrich.choose_keyword(manual, hint), manual)
        # Vers Ahrefs gaat voor overgenomen Ahrefs; de intentie hoort bij het oude woord en vervalt.
        self.assertEqual(
            ahrefs_enrich.choose_keyword(carried, hint),
            {"focus_keyword": "seo bureau", "intent": None, "keyword_source": "ahrefs"},
        )
        # Zelfde woord als vorige keer: intentie blijft.
        self.assertEqual(ahrefs_enrich.choose_keyword(same, hint)["intent"], "commercieel")
        # Geen bruikbare ranking: het overgenomen woord blijft, of niets (AI bepaalt).
        self.assertEqual(ahrefs_enrich.choose_keyword(carried, low), carried)
        self.assertEqual(ahrefs_enrich.choose_keyword(None, low), {})
        self.assertEqual(ahrefs_enrich.choose_keyword(None, hint)["keyword_source"], "ahrefs")


if __name__ == "__main__":
    unittest.main()
