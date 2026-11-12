"""Fase 4 (kwartaal GEO-werkzaamheden): pure functies — rondes, schema-validatie, vergelijking, checks."""
import unittest
from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace

from app.features.launch_checklist.services import quarterly_checklist
from app.features.launch_checklist.services.content_checklist import ITEMS as CONTENT_ITEMS
from app.features.launch_checklist.services.geo_checklist import ITEMS as GEO_ITEMS
from app.features.launch_checklist.services.issues import ISSUE_TYPES, generate_quarterly_issues
from app.features.launch_checklist.services.quarterly_checks import (
    evaluate_ai_scan,
    evaluate_new_pages,
    evaluate_report,
    evaluate_schema,
    evaluate_search_console,
)
from app.features.launch_checklist.services.quarterly_compare import (
    compare_ahrefs,
    compare_ai,
    compare_issues,
    compare_pages,
    compare_search_console,
    count_issue_types,
    lost_schema_types,
)
from app.features.launch_checklist.services.schema_validate import (
    extract_jsonld_blocks,
    validate_blocks,
    validate_html,
)


def page(url, **kw):
    base = dict(
        id=url, url=url, path=url.split(".nl", 1)[-1] or "/", status_code=200, final_url=None,
        redirect_chain=None, error=None, content_type="text/html", indexable=True,
        indexability_reason=None, canonical=None, in_sitemap=True, schema_types=[], signals=None,
        ahrefs=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class PeriodTest(unittest.TestCase):
    def test_period_of_uses_amsterdam_quarters(self):
        # 31 dec 23:30 UTC is 1 januari in Amsterdam: volgend kwartaal.
        self.assertEqual(quarterly_checklist.period_of(datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc)), "2027-Q1")
        self.assertEqual(quarterly_checklist.period_of(datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)), "2026-Q4")
        self.assertEqual(quarterly_checklist.period_of(datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc)), "2026-Q2")

    def test_period_validation_and_label(self):
        self.assertTrue(quarterly_checklist.is_period("2026-Q4"))
        for value in ("2026-Q5", "2026Q4", "", None, "2026-Q4; drop"):
            self.assertFalse(quarterly_checklist.is_period(value))
        self.assertEqual(quarterly_checklist.period_label("2026-Q4"), "Q4 2026")


class SchemaValidateTest(unittest.TestCase):
    def test_extracts_blocks_and_counts_invalid_json(self):
        html = (
            '<script type="application/ld+json">{"@type":"Organization","name":"X","url":"https://x.nl","logo":"l"}</script>'
            "<script type='application/ld+json'>{kapot</script>"
        )
        self.assertEqual(len(extract_jsonld_blocks(html)), 2)
        result = validate_html(html)
        self.assertEqual(result["blocks"], 2)
        self.assertEqual(result["invalid_blocks"], 1)
        self.assertEqual(result["types"], ["Organization"])
        self.assertEqual(result["problems"], [])

    def test_missing_required_is_error_recommended_is_warning(self):
        result = validate_blocks([
            '{"@graph":[{"@type":"LocalBusiness","name":"X"},{"@type":"BlogPosting","headline":"Kop"}]}'
        ])
        by_type = {p["type"]: p for p in result["problems"]}
        self.assertEqual(by_type["LocalBusiness"]["severity"], "error")
        self.assertIn("address", by_type["LocalBusiness"]["missing"])
        self.assertEqual(by_type["BlogPosting"]["severity"], "warning")
        self.assertIn("author", by_type["BlogPosting"]["missing"])

    def test_faq_and_breadcrumb_content_and_nested_rating(self):
        result = validate_blocks([
            '{"@type":"FAQPage","mainEntity":[{"@type":"Question","name":"Vraag?"}]}',
            '{"@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,"item":{"name":"Home"}}]}',
            '{"@type":"Product","name":"P","image":"i","offers":{"price":1},"aggregateRating":{"ratingValue":4}}',
        ])
        types = {p["type"] for p in result["problems"]}
        self.assertIn("FAQPage", types)
        self.assertNotIn("BreadcrumbList", types)
        self.assertIn("AggregateRating", types)
        self.assertNotIn("Product", types)

    def test_alternatives_and_unknown_types(self):
        result = validate_blocks([
            '{"@type":"Service","serviceType":"Dakgoot reinigen"}',
            '{"@type":"OnbekendType"}',
        ])
        self.assertEqual(result["problems"], [])


class CompareTest(unittest.TestCase):
    def test_compare_pages(self):
        base = [
            page("https://x.nl/"),
            page("https://x.nl/oud/"),
            page("https://x.nl/stuk/"),
        ]
        current = [
            page("https://x.nl/"),
            page("https://x.nl/stuk/", status_code=404),
            page("https://x.nl/nieuw/"),
            page("https://x.nl/ahrefs-only/", status_code=404, ahrefs={"source": "ahrefs"}),
        ]
        diff = compare_pages(base, current)
        self.assertEqual([p.url for p in diff["new"]], ["https://x.nl/nieuw/"])
        self.assertEqual([p.url for p in diff["removed"]], ["https://x.nl/oud/"])
        self.assertEqual([p.url for _, p in diff["broken"]], ["https://x.nl/stuk/"])
        self.assertEqual((diff["before"], diff["after"]), (3, 3))

    def test_inconclusive_status_is_not_broken(self):
        diff = compare_pages([page("https://x.nl/a/")], [page("https://x.nl/a/", status_code=403)])
        self.assertEqual(diff["broken"], [])

    def test_compare_ai(self):
        before = {"score": 60, "checks": [
            {"key": "llms_txt", "label": "llms.txt", "status": "warning"},
            {"key": "sitemap", "label": "XML-sitemap", "status": "ok"},
        ]}
        after = {"score": 70, "checks": [
            {"key": "llms_txt", "label": "llms.txt", "status": "ok"},
            {"key": "sitemap", "label": "XML-sitemap", "status": "error"},
            {"key": "website_schema", "label": "WebSite-schema", "status": "ok"},
        ]}
        result = compare_ai(before, after)
        changes = {r["key"]: r["change"] for r in result["checks"]}
        self.assertEqual(changes, {"llms_txt": "better", "sitemap": "worse", "website_schema": "new"})
        self.assertEqual((result["improved"], result["worsened"]), (1, 1))

        check = evaluate_ai_scan(result, "Nulmeting (fase 1)")
        self.assertEqual(check["status"], "error")
        self.assertIn("60 → 70 (+10)", check["message"])

    def test_issue_counts_skip_phase4_items(self):
        before = count_issue_types(["title_missing", "title_missing", "c4_new_pages", "cwv_lcp", "cwv_inp"])
        after = count_issue_types(["title_missing", "status_4xx"])
        self.assertEqual(before, Counter({"title_missing": 2}))
        result = compare_issues(before, after)
        self.assertEqual((result["before"], result["after"]), (2, 2))
        rows = {r["issue_type"]: r["delta"] for r in result["rows"]}
        self.assertEqual(rows, {"title_missing": -1, "status_4xx": 1})

    def test_compare_ahrefs(self):
        self.assertIsNone(compare_ahrefs(None, {"domain": {}}))
        result = compare_ahrefs({"domain": {"domain_rating": 20}}, {"domain": {"domain_rating": 23.5}})
        dr = next(m for m in result["metrics"] if m["key"] == "domain_rating")
        self.assertEqual(dr["delta"], 3.5)
        self.assertFalse(result["same_snapshot"])
        same = {"fetched_at": "2026-11-11T10:00:00+00:00", "domain": {"domain_rating": 20}}
        self.assertTrue(compare_ahrefs(same, dict(same))["same_snapshot"])

    def test_lost_schema_types(self):
        lost = lost_schema_types(
            [page("https://x.nl/a/", schema_types=["FAQPage", "Article"])],
            [page("https://x.nl/a/", schema_types=["Article"])],
        )
        self.assertEqual(lost, [{"url": "https://x.nl/a/", "lost": ["FAQPage"]}])


class ChecksTest(unittest.TestCase):
    def test_new_pages(self):
        base = [page("https://x.nl/"), page("https://x.nl/stuk/")]
        current = [
            page("https://x.nl/"),
            page("https://x.nl/stuk/", status_code=404),
            page("https://x.nl/goed/"),
            page("https://x.nl/noindex/", indexable=False, indexability_reason="noindex"),
            page("https://x.nl/los/", in_sitemap=False),
            page("https://x.nl/weg/", status_code=404),
            page("https://x.nl/canon/", canonical="https://x.nl/"),
        ]
        result = evaluate_new_pages(compare_pages(base, current), "sitemap", "Ronde Q3 2026")
        self.assertEqual(result["status"], "error")
        rows = {r["url"]: r for r in result["details"]["new"]}
        self.assertEqual(rows["https://x.nl/goed/"]["result"], "ok")
        self.assertEqual(rows["https://x.nl/weg/"]["result"], "error")
        self.assertEqual(rows["https://x.nl/noindex/"]["result"], "warning")
        self.assertIn("staat niet in de sitemap", rows["https://x.nl/los/"]["problems"])
        self.assertTrue(any("canonical" in p for p in rows["https://x.nl/canon/"]["problems"]))
        self.assertEqual(result["details"]["broken_total"], 1)

        clean = evaluate_new_pages(compare_pages(base, base), "sitemap", "Ronde Q3 2026")
        self.assertEqual(clean["status"], "ok")
        self.assertIn("Geen nieuwe pagina's", clean["message"])

    def test_schema(self):
        good = {"blocks": 1, "invalid_blocks": 0, "types": ["Organization"], "problems": []}
        bad = {"blocks": 1, "invalid_blocks": 1, "types": [], "problems": []}
        pages = [
            page("https://x.nl/", signals={"schema_validation": good}),
            page("https://x.nl/b/", signals={"schema_validation": bad}),
            page("https://x.nl/c/", signals=None),
        ]
        result = evaluate_schema(pages, [{"url": "https://x.nl/", "lost": ["WebSite"]}])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["details"]["checked"], 2)
        by_url = {r["url"]: r for r in result["details"]["pages"]}
        self.assertEqual(by_url["https://x.nl/"]["result"], "warning")
        self.assertEqual(by_url["https://x.nl/b/"]["result"], "error")
        self.assertEqual(evaluate_schema([page("https://x.nl/")], [])["status"], "unknown")

    def test_report(self):
        self.assertEqual(evaluate_report(True)["status"], "info")
        self.assertEqual(evaluate_report(False)["status"], "unknown")


class CatalogAndIssuesTest(unittest.TestCase):
    def test_catalog(self):
        keys = set(quarterly_checklist.ITEMS)
        self.assertEqual(len(keys), 6)
        self.assertTrue(all(k.startswith("c4_") for k in keys))
        self.assertFalse(keys & set(GEO_ITEMS))
        self.assertFalse(keys & set(CONTENT_ITEMS))
        self.assertTrue(all(k in ISSUE_TYPES for k in keys))
        sections = {s for s, _ in quarterly_checklist.SECTIONS}
        self.assertTrue(all(i.section in sections for i in quarterly_checklist.ITEMS.values()))

    def test_merge_manual_items_stay_open(self):
        merged = quarterly_checklist.merge_quarterly_checklist(
            {"c4_new_pages": {"status": "ok", "message": "", "evidence": [], "details": None},
             "c4_monthly_report": {"status": "info", "message": "", "evidence": [], "details": None}},
            {},
        )
        effective = {i["key"]: i["effective"] for s in merged["sections"] for i in s["items"]}
        self.assertEqual(effective["c4_new_pages"], "done")
        self.assertEqual(effective["c4_monthly_report"], "open")
        self.assertEqual(effective["c4_proranktracker"], "open")
        # Zonder koppeling geen auto-resultaat: het Search Console-punt blijft handmatig open.
        self.assertEqual(effective["c4_search_console"], "open")
        self.assertEqual(merged["total"], 6)

    def test_issues(self):
        items = {
            "c4_ai_scan": {"status": "warning", "message": "AI-score 70 → 65", "evidence": []},
            "c4_new_pages": {"status": "error", "details": {"new": [
                {"page_id": "p1", "url": "https://x.nl/a/", "path": "/a/", "result": "error", "problems": ["geeft 404"]},
                {"page_id": "p2", "url": "https://x.nl/b/", "path": "/b/", "result": "ok", "problems": []},
            ]}},
            "c4_schema_validation": {"status": "error", "details": {"pages": [
                {"page_id": "p3", "url": "https://x.nl/c/", "path": "/c/", "result": "error", "invalid_blocks": 1,
                 "problems": [], "lost_types": []},
            ]}},
        }
        issues = generate_quarterly_issues(items, {})
        self.assertEqual([i["issue_type"] for i in issues], ["c4_ai_scan", "c4_new_pages", "c4_schema_validation"])
        self.assertEqual(issues[1]["url"], "https://x.nl/a/")
        self.assertEqual(issues[2]["category"], "schema")
        skipped = generate_quarterly_issues(items, {"c4_new_pages": "afgerond", "c4_ai_scan": "nvt"})
        self.assertEqual([i["issue_type"] for i in skipped], ["c4_schema_validation"])


def gsc_snapshot(**kw):
    base = {
        "property": "sc-domain:x.nl",
        "property_source": "auto",
        "period": {"start": "2026-08-12", "end": "2026-11-09", "days": 90},
        "previous": {"start": "2026-05-14", "end": "2026-08-11", "days": 90},
        "last_year": {"start": "2025-08-13", "end": "2025-11-10", "days": 90},
        "totals": {"clicks": 900, "impressions": 30000, "ctr": 0.03, "position": 12.4},
        "totals_previous": {"clicks": 1000, "impressions": 28000, "ctr": 0.0357, "position": 13.0},
        "totals_last_year": {"clicks": 600, "impressions": 20000, "ctr": 0.03, "position": 15.0},
        "queries": [
            {"key": "schoenen", "clicks": 300, "impressions": 4000, "ctr": 0.075, "position": 3.1,
             "clicks_prev": 200, "impressions_prev": 3500, "position_prev": 4.0},
            {"key": "laarzen", "clicks": 50, "impressions": 2000, "ctr": 0.025, "position": 9.0,
             "clicks_prev": 180, "impressions_prev": 2500, "position_prev": 6.0},
            {"key": "nieuw woord", "clicks": 20, "impressions": 300, "ctr": 0.067, "position": 8.0,
             "clicks_prev": None, "impressions_prev": None, "position_prev": None},
        ],
        "pages": [],
        "sitemaps": [{"path": "https://x.nl/sitemap.xml", "errors": 0, "warnings": 0, "submitted": 120}],
        "inspection": None,
        "errors": [],
        "fetched_at": "2026-11-12T09:00:00+00:00",
    }
    base.update(kw)
    return base


class SearchConsoleTest(unittest.TestCase):
    def test_compare(self):
        self.assertIsNone(compare_search_console(None))
        self.assertIsNone(compare_search_console(gsc_snapshot(totals=None, sitemaps=None)))
        result = compare_search_console(gsc_snapshot())
        clicks = result["metrics"][0]
        self.assertEqual((clicks["before"], clicks["after"], clicks["delta"], clicks["pct"]), (1000, 900, -100, -10.0))
        self.assertEqual(clicks["pct_last_year"], 50.0)
        self.assertEqual([r["key"] for r in result["queries"]["risers"]], ["schoenen"])
        self.assertEqual([r["key"] for r in result["queries"]["fallers"]], ["laarzen"])
        self.assertEqual(result["queries"]["fallers"][0]["delta"], -130)
        self.assertEqual(result["queries"]["total"], 3)
        self.assertEqual(result["sitemaps"]["with_errors"], 0)
        self.assertIsNone(result["inspection"])

    def test_clean_result_is_info_never_ok(self):
        result = evaluate_search_console(compare_search_console(gsc_snapshot()), 20)
        self.assertEqual(result["status"], "info")
        self.assertIn("Klikken 1.000 → 900 (-10%) in 90 dagen", result["message"])
        self.assertIn("Pagina-indexering", result["message"])
        merged = quarterly_checklist.merge_quarterly_checklist({"c4_search_console": result}, {})
        effective = {i["key"]: i["effective"] for s in merged["sections"] for i in s["items"]}
        self.assertEqual(effective["c4_search_console"], "open")
        self.assertEqual(evaluate_search_console(None)["status"], "unknown")

    def test_problems_and_issues(self):
        snapshot = gsc_snapshot(
            totals={"clicks": 700, "impressions": 30000, "ctr": 0.023, "position": 14.0},
            sitemaps=[
                {"path": "https://x.nl/sitemap.xml", "errors": 3, "warnings": 0},
                {"path": "https://x.nl/news.xml", "errors": 0, "warnings": 1},
            ],
            inspection={"requested": 3, "checked": 3, "indexed": 1, "errors": [], "rows": [
                {"url": "https://x.nl/", "state": "indexed", "reason": "Ingediend en geïndexeerd"},
                {"url": "https://x.nl/a/", "state": "blocked", "reason": "noindex in de meta-tag"},
                {"url": "https://x.nl/b/", "state": "not_indexed", "reason": "Gevonden - momenteel niet geïndexeerd"},
            ]},
        )
        result = evaluate_search_console(compare_search_console(snapshot), 20)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["details"]["clicks_drop_pct"], -30.0)
        self.assertEqual(len(result["details"]["not_indexed"]), 2)
        self.assertIn("3 URL's geïnspecteerd, 1 geïndexeerd", result["message"])

        issues = generate_quarterly_issues({"c4_search_console": result}, {})
        self.assertEqual({i["issue_type"] for i in issues}, {"c4_search_console"})
        self.assertEqual([i["severity"] for i in issues], ["hoog", "middel", "hoog", "laag", "middel"])
        self.assertEqual(issues[0]["url"], "https://x.nl/a/")
        self.assertIn("30% gedaald", issues[-1]["title"])
        self.assertEqual(generate_quarterly_issues({"c4_search_console": result}, {"c4_search_console": "afgerond"}), [])

    def test_only_warnings(self):
        snapshot = gsc_snapshot(sitemaps=[])
        result = evaluate_search_console(compare_search_console(snapshot), 20)
        self.assertEqual(result["status"], "warning")
        self.assertIn("geen sitemap ingediend", result["message"])

    def test_new_pages_show_google_status(self):
        diff = compare_pages([page("https://x.nl/")], [page("https://x.nl/"), page("https://x.nl/nieuw/")])
        inspection = {"rows": [{"url": "https://x.nl/nieuw", "state": "not_indexed", "reason": "onbekend bij Google"}]}
        result = evaluate_new_pages(diff, "sitemap", "Nulmeting (fase 1)", inspection)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["details"]["new"][0]["google"], {"state": "not_indexed", "reason": "onbekend bij Google"})
        self.assertIsNone(evaluate_new_pages(diff, "sitemap", "Nulmeting (fase 1)")["details"]["new"][0]["google"])

    def test_report_message_follows_search_console(self):
        self.assertIn("Vul Search Console en GA4 aan", evaluate_report(True)["message"])
        self.assertIn("Vul GA4 aan", evaluate_report(True, True)["message"])


if __name__ == "__main__":
    unittest.main()
