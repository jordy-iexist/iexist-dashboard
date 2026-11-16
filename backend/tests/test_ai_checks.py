"""AI-checks (fase 1): een netwerkfout is iets anders dan 'ontbreekt'.

De statussen en de score moeten gelijk blijven aan het gedrag van vóór dit
onderscheid: fase 4 vergelijkt scores tussen scans, dus een andere status zou
als een (valse) achteruitgang verschijnen. Alleen de meldingen verschillen.
"""
import unittest
from unittest.mock import patch

import httpx

from app.features.launch_checklist.services import ai_checks
from app.features.launch_checklist.services.ai_checks import AI_BOTS, run_ai_checks
from app.features.launch_checklist.services.inventory import PageRecord
from app.features.launch_checklist.services.issues import generate_issues

BASE = "https://www.klant.nl/"
SITEMAPS = ["https://www.klant.nl/sitemap.xml"]

# Vastgelegd met de code van vóór deze wijziging (zelfde invoer, zelfde mocks).
EXPECTED_STATUSES = {
    "robots_txt": "warning",
    "ai_bots_blocked": "ok",
    "sitemap": "warning",
    "llms_txt": "warning",
    "schema_coverage": "ok",
    "org_schema": "ok",
    "website_schema": "ok",
    "ssr_content": "ok",
}
EXPECTED_SCORE = 81
ROBOTS = "User-agent: *\nDisallow: /wp-admin/\n"
EXPECTED_STATUSES_WITH_ROBOTS = {**EXPECTED_STATUSES, "robots_txt": "ok"}
EXPECTED_SCORE_WITH_ROBOTS = 88


def home() -> PageRecord:
    return PageRecord(
        url=BASE, path="/", in_sitemap=True, status_code=200, final_url=BASE, final_status=200,
        content_type="text/html", word_count=500, schema_types=["Organization", "WebSite"],
    )


def llms_response(kind: str):
    """Mock voor httpx.get van /llms.txt: 'missing' (404) of 'unreachable' (netwerkfout)."""
    def fake_get(url, **_kwargs):
        if kind == "unreachable":
            raise httpx.ConnectError("verbinding geweigerd")
        return httpx.Response(404, headers={"content-type": "text/html"}, text="Not found",
                              request=httpx.Request("GET", url))
    return fake_get


def page_record(path: str, *, in_sitemap: bool = True) -> PageRecord:
    url = BASE.rstrip("/") + path
    return PageRecord(
        url=url, path=path, in_sitemap=in_sitemap, status_code=200, final_url=url, final_status=200,
        content_type="text/html", word_count=500,
    )


def run(*, robots_txt=None, robots_status=None, llms="missing", records=None):
    with patch.object(ai_checks, "is_safe_external_url", return_value=True), \
            patch.object(ai_checks.httpx, "get", side_effect=llms_response(llms)):
        return run_ai_checks(
            base_url=BASE, robots_txt=robots_txt, robots_status=robots_status,
            sitemaps=SITEMAPS, records=records if records is not None else [home()],
        )


def by_key(result):
    return {c["key"]: c for c in result["checks"]}


def statuses(result):
    return {c["key"]: c["status"] for c in result["checks"]}


class RobotsTxtTest(unittest.TestCase):
    def test_unreachable_and_missing_keep_statuses_and_score(self):
        for result in (run(robots_status=None), run(robots_status=404)):
            self.assertEqual(statuses(result), EXPECTED_STATUSES)
            self.assertEqual(result["score"], EXPECTED_SCORE)

    def test_bots_shape_is_unchanged(self):
        for result in (run(robots_status=None), run(robots_status=404)):
            self.assertEqual(
                result["bots"], [{"bot": b, "label": label, "allowed": True} for b, label in AI_BOTS]
            )

    def test_missing_robots_says_missing(self):
        checks = by_key(run(robots_status=404))
        self.assertEqual(checks["robots_txt"]["message"], "Geen robots.txt gevonden (status 404).")
        self.assertEqual(checks["ai_bots_blocked"]["message"], "Alle AI-bots hebben toegang tot de homepage.")

    def test_unreachable_robots_says_not_verified(self):
        checks = by_key(run(robots_status=None))
        robots = checks["robots_txt"]["message"]
        bots = checks["ai_bots_blocked"]["message"]
        self.assertIn("kon niet worden opgehaald", robots)
        self.assertNotIn("Geen robots.txt gevonden", robots)
        self.assertIn("kon niet worden opgehaald", bots)
        self.assertIn("niet gecontroleerd", bots)
        self.assertNotIn("Alle AI-bots hebben toegang", bots)
        self.assertNotEqual(robots, by_key(run(robots_status=404))["robots_txt"]["message"])

    def test_unreachable_robots_issue_does_not_tell_to_place_robots(self):
        issues = {i["issue_type"]: i for i in generate_issues([], run(robots_status=None))}
        self.assertIn("kon niet worden opgehaald", issues["ai_robots_txt"]["description"])
        self.assertNotIn("Plaats een robots.txt", issues["ai_robots_txt"]["recommendation"])
        missing = {i["issue_type"]: i for i in generate_issues([], run(robots_status=404))}
        self.assertIn("Plaats een robots.txt", missing["ai_robots_txt"]["recommendation"])


class LlmsTxtTest(unittest.TestCase):
    def test_network_error_and_404_keep_statuses_and_score(self):
        for llms in ("missing", "unreachable"):
            result = run(robots_txt=ROBOTS, robots_status=200, llms=llms)
            self.assertEqual(statuses(result), EXPECTED_STATUSES_WITH_ROBOTS)
            self.assertEqual(result["score"], EXPECTED_SCORE_WITH_ROBOTS)

    def test_messages_differ(self):
        missing = by_key(run(robots_txt=ROBOTS, robots_status=200, llms="missing"))["llms_txt"]["message"]
        unreachable = by_key(run(robots_txt=ROBOTS, robots_status=200, llms="unreachable"))["llms_txt"]["message"]
        self.assertTrue(missing.startswith("Geen llms.txt gevonden."))
        self.assertIn("kon niet worden opgehaald", unreachable)
        self.assertNotIn("Geen llms.txt gevonden", unreachable)


class RobotsPagesTest(unittest.TestCase):
    """Per-pagina robots.txt-toets: los van de checks, de bots en de score."""

    BLOCKING = "User-agent: *\nDisallow: /\nAllow: /$\nAllow: /diensten/\n\nUser-agent: Bingbot\nDisallow: /blog/\n"

    def records(self):
        return [home(), page_record("/diensten/a/"), page_record("/blog/b/"), page_record("/winkel?x=1", in_sitemap=False)]

    def test_blocked_pages_are_listed(self):
        result = run(robots_txt=self.BLOCKING, robots_status=200, records=self.records())
        pages = {row["url"]: row for row in result["robots_pages"]["pages"]}
        self.assertEqual(result["robots_pages"]["total"], 2)
        # Homepage en /diensten/ zijn toegestaan voor Googlebot (Allow wint met langere regel); Bingbot heeft eigen groep.
        self.assertEqual(pages["https://www.klant.nl/blog/b/"]["blocked_for"], ["Googlebot", "Bingbot"])
        self.assertEqual(pages["https://www.klant.nl/blog/b/"]["rule"], "Disallow: /")
        self.assertEqual(pages["https://www.klant.nl/winkel?x=1"]["blocked_for"], ["Googlebot"])
        # Sitemap-pagina's eerst.
        self.assertEqual(result["robots_pages"]["pages"][0]["url"], "https://www.klant.nl/blog/b/")

    def test_checks_bots_and_score_are_unchanged(self):
        records = self.records()
        result = run(robots_txt=self.BLOCKING, robots_status=200, records=records)
        with patch.object(ai_checks, "robots_blocked_pages", return_value=None):
            without = run(robots_txt=self.BLOCKING, robots_status=200, records=records)
        self.assertNotIn("robots_pages", without)
        self.assertEqual(result["score"], without["score"])
        self.assertEqual(result["checks"], without["checks"])
        self.assertEqual(result["bots"], without["bots"])

    def test_nothing_without_robots_txt(self):
        for status in (None, 404):
            self.assertNotIn("robots_pages", run(robots_status=status, records=self.records()))

    def test_permissive_robots_lists_nothing(self):
        self.assertEqual(run(robots_txt=ROBOTS, robots_status=200, records=self.records())["robots_pages"],
                         {"total": 0, "pages": []})
        result = run(robots_txt=ROBOTS, robots_status=200)
        self.assertEqual(result["robots_pages"], {"total": 0, "pages": []})
        self.assertEqual(statuses(result), EXPECTED_STATUSES_WITH_ROBOTS)
        self.assertEqual(result["score"], EXPECTED_SCORE_WITH_ROBOTS)

    def test_phase1_rule_reads_robots_pages(self):
        from types import SimpleNamespace

        result = run(robots_txt=self.BLOCKING, robots_status=200, records=self.records())
        pages = [
            SimpleNamespace(id=r.url, url=r.url, path=r.path, in_sitemap=r.in_sitemap, status_code=200,
                            redirect_chain=None)
            for r in self.records()
        ]
        from app.features.launch_checklist.services.issues import rule_robots

        flagged = [i["url"] for i in rule_robots(pages, {"ai_checks": result})]
        self.assertEqual(flagged, ["https://www.klant.nl/blog/b/"])


if __name__ == "__main__":
    unittest.main()
