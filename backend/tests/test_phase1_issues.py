"""Fase 1-regels: robots.txt, hreflang, Open Graph en paginagewicht."""
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.features.launch_checklist.services import ai_checks as ai_checks_module
from app.features.launch_checklist.services import issues as issues_module
from app.features.launch_checklist.services.issues import (
    ISSUE_TYPE_SINCE,
    ISSUE_TYPES,
    PAGE_WEIGHT_POOR_BYTES,
    PAGE_WEIGHT_WARN_BYTES,
    RULESET_VERSION,
    THIN_CONTENT_WORDS,
    THIN_MAIN_WORDS,
    generate_issues,
    is_valid_hreflang,
    rule_hreflang,
    rule_onpage,
    rule_open_graph,
    rule_robots,
    rule_vitals,
    thin_content_check,
)

SITE = "https://www.klant.nl"
OG_FULL = {"og:title": "T", "og:description": "D", "og:image": f"{SITE}/img.jpg"}


def page(path, **kw):
    url = SITE + path
    base = dict(
        id=url, url=url, path=path, status_code=200, final_url=url, redirect_chain=None, error=None,
        content_type="text/html", indexable=True, indexability_reason=None, canonical=None, in_sitemap=True,
        title="Een prima title van ruim dertig tekens", title_length=40,
        meta_description="m" * 100, meta_description_length=100, h1=["Kop"], h1_count=1, word_count=500,
        images_missing_alt=0, images_total=0, broken_links=None, response_time_ms=100, cwv=None,
        lang="nl", hreflang=None, open_graph=dict(OG_FULL), refdomains=None, org_traffic=None, ahrefs=None,
        schema_types=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


def types(issues):
    return [i["issue_type"] for i in issues]


def robots_ctx(*rows, total=None):
    return {"ai_checks": {"robots_pages": {"total": total if total is not None else len(rows), "pages": list(rows)}}}


class RobotsRuleTest(unittest.TestCase):
    ROW = {"url": f"{SITE}/blog/a/", "blocked_for": ["Googlebot", "Bingbot"], "rule": "Disallow: /blog/"}

    def test_blocked_sitemap_page(self):
        issues = list(rule_robots([page("/blog/a/")], robots_ctx(self.ROW)))
        self.assertEqual(types(issues), ["robots_blocked_in_sitemap"])
        self.assertEqual(issues[0]["severity"], "hoog")
        self.assertEqual(issues[0]["details"], {"blocked_for": ["Googlebot", "Bingbot"], "rule": "Disallow: /blog/"})
        self.assertIn("Disallow: /blog/", issues[0]["description"])

    def test_url_key_matches_trailing_slash(self):
        row = {**self.ROW, "url": f"{SITE}/blog/a"}
        self.assertEqual(len(list(rule_robots([page("/blog/a/")], robots_ctx(row)))), 1)

    def test_not_in_sitemap_is_ignored(self):
        # Zonder sitemap (gecrawlde site) bewust niets: winkelwagen/filters zijn vaak met opzet geblokkeerd.
        self.assertEqual(list(rule_robots([page("/blog/a/", in_sitemap=False)], robots_ctx(self.ROW))), [])

    def test_only_final_status_200(self):
        self.assertEqual(list(rule_robots([page("/blog/a/", status_code=404)], robots_ctx(self.ROW))), [])

    def test_no_robots_data(self):
        for ctx in ({"ai_checks": {}}, {"ai_checks": None}, {}, robots_ctx()):
            self.assertEqual(list(rule_robots([page("/blog/a/")], ctx)), [])


class HreflangCodeTest(unittest.TestCase):
    def test_valid(self):
        for code in ("nl", "nl-NL", "en-GB", "EN-us", "x-default", "zh-Hant", "zh-Hant-TW", "fy-NL"):
            self.assertTrue(is_valid_hreflang(code), code)

    def test_invalid(self):
        for code in ("en-UK", "nl_NL", "eng", "xx", "nl-XX", "nl-", "", "default", "nl-NL-x"):
            self.assertFalse(is_valid_hreflang(code), code)

    def test_code_lists_are_complete(self):
        self.assertEqual(len(issues_module._ISO_639_1), 183)
        self.assertEqual(len(issues_module._ISO_3166_1), 249)


def hl(*pairs):
    return [{"lang": lang, "href": href} for lang, href in pairs]


NL, EN = f"{SITE}/", f"{SITE}/en/"


class HreflangRuleTest(unittest.TestCase):
    def pair(self, nl_kw=None, en_kw=None):
        links = hl(("nl-NL", NL), ("en-GB", EN), ("x-default", NL))
        return [page("/", **{"hreflang": links, **(nl_kw or {})}), page("/en/", **{"hreflang": links, **(en_kw or {})})]

    def test_site_without_hreflang_produces_nothing(self):
        self.assertEqual(list(rule_hreflang([page("/"), page("/en/")], {})), [])

    def test_correct_reciprocal_pair_produces_nothing(self):
        self.assertEqual(list(rule_hreflang(self.pair(), {})), [])

    def test_invalid_codes_duplicates_relative_and_no_self(self):
        p = page("/", hreflang=hl(("en-UK", EN), ("nl_NL", "/nl/"), ("de", f"{SITE}/de/"), ("de", f"{SITE}/de2/")))
        issues = [i for i in rule_hreflang([p], {}) if i["issue_type"] == "hreflang_invalid"]
        self.assertEqual(len(issues), 1)
        problems = issues[0]["details"]["problems"]
        by_problem = {}
        for row in problems:
            by_problem.setdefault(row["problem"], []).append(row["lang"])
        self.assertEqual(by_problem["ongeldige taal-/regiocode"], ["en-UK", "nl_NL"])
        self.assertEqual(by_problem["relatieve URL (moet volledig zijn, met https://)"], ["nl_NL"])
        self.assertEqual(by_problem["dezelfde code verwijst naar meerdere URL's"], ["de", "de"])
        self.assertEqual(by_problem["geen hreflang naar de pagina zelf"], [None])
        self.assertEqual(issues[0]["severity"], "middel")

    def test_no_return_link(self):
        nl, en = self.pair(en_kw={"hreflang": hl(("en-GB", EN))})
        issues = list(rule_hreflang([nl, en], {}))
        self.assertEqual(types(issues), ["hreflang_no_return"])
        self.assertEqual(issues[0]["url"], NL)
        self.assertEqual(issues[0]["details"], {"missing": [{"lang": "en-GB", "url": EN}]})

    def test_target_not_in_crawl_is_skipped(self):
        p = page("/", hreflang=hl(("nl-NL", NL), ("de-DE", f"{SITE}/de/")))
        self.assertEqual(list(rule_hreflang([p], {})), [])

    def test_broken_targets(self):
        cases = [
            ({"status_code": 404, "hreflang": None}, "statuscode 404"),
            ({"redirect_chain": [{"url": EN, "status": 301}, {"url": f"{SITE}/en-gb/", "status": 200, "final": True}],
              "final_url": f"{SITE}/en-gb/"}, "redirect naar"),
            ({"indexable": False, "indexability_reason": "noindex (meta robots)"}, "noindex"),
            ({"indexable": False, "indexability_reason": "Canonical naar andere URL", "canonical": NL}, "canonical naar"),
        ]
        for en_kw, reason in cases:
            with self.subTest(reason=reason):
                issues = list(rule_hreflang(self.pair(en_kw=en_kw), {}))
                broken = [i for i in issues if i["issue_type"] == "hreflang_target_broken" and i["url"] == NL]
                self.assertEqual(len(broken), 1, issues)
                target = broken[0]["details"]["targets"][0]
                self.assertEqual((target["lang"], target["url"]), ("en-GB", EN))
                self.assertTrue(target["reason"].startswith(reason), target)
                self.assertEqual(broken[0]["severity"], "hoog")
                # Een kapot doel krijgt niet ook nog 'geen terugverwijzing'.
                self.assertNotIn("hreflang_no_return", types(i for i in issues if i["url"] == NL))

    def test_inconclusive_target_status_is_skipped(self):
        for status in (401, 403, 429, 503):
            issues = list(rule_hreflang(self.pair(en_kw={"status_code": status, "hreflang": None}), {}))
            self.assertEqual([i for i in issues if i["url"] == NL], [], status)


class OpenGraphRuleTest(unittest.TestCase):
    def test_complete_site_produces_nothing(self):
        self.assertEqual(list(rule_open_graph([page("/"), page("/a/")], {})), [])

    def test_minor_gaps_are_low(self):
        pages = [page("/"), page("/a/"), page("/b/"), page("/c/", open_graph={"og:title": "T", "og:image": f"{SITE}/i.jpg"})]
        issues = list(rule_open_graph(pages, {}))
        self.assertEqual(types(issues), ["og_incomplete"])
        issue = issues[0]
        self.assertEqual(issue["severity"], "laag")
        self.assertIsNone(issue["page_id"])
        self.assertEqual(issue["details"]["total"], 4)
        self.assertEqual(issue["details"]["missing"], {"og:title": 0, "og:description": 1, "og:image": 0})
        self.assertEqual(issue["details"]["urls"], [f"{SITE}/c/"])
        self.assertEqual(issue["details"]["relative_image"], [])

    def test_homepage_without_image_is_middel(self):
        pages = [page("/", open_graph={"og:title": "T", "og:description": "D"}), page("/a/"), page("/b/"), page("/c/")]
        self.assertEqual(list(rule_open_graph(pages, {}))[0]["severity"], "middel")

    def test_half_of_pages_without_title_is_middel(self):
        pages = [page("/"), page("/a/"), page("/b/", open_graph={}), page("/c/", open_graph=None)]
        issue = list(rule_open_graph(pages, {}))[0]
        self.assertEqual(issue["severity"], "middel")
        self.assertEqual(issue["details"]["missing"]["og:title"], 2)

    def test_relative_image_only(self):
        pages = [page("/"), page("/a/", open_graph={**OG_FULL, "og:image": "/img.jpg"})]
        issue = list(rule_open_graph(pages, {}))[0]
        self.assertEqual(issue["details"]["relative_image"], [f"{SITE}/a/"])
        self.assertEqual(issue["details"]["urls"], [])
        self.assertEqual(issue["severity"], "laag")

    def test_non_indexable_pages_are_ignored(self):
        pages = [page("/"), page("/x/", open_graph=None, indexable=False, indexability_reason="noindex (meta robots)")]
        self.assertEqual(list(rule_open_graph(pages, {})), [])


class PageWeightRuleTest(unittest.TestCase):
    def weight_issues(self, weight):
        cwv = {"lab": {"lcp": 1000, "cls": 0.01, "tbt": 50, "total_byte_weight": weight}, "field": None}
        return [i for i in rule_vitals([page("/", cwv=cwv)], {}) if i["issue_type"] == "cwv_page_weight"]

    def test_thresholds(self):
        self.assertEqual(self.weight_issues(PAGE_WEIGHT_WARN_BYTES), [])
        middel = self.weight_issues(PAGE_WEIGHT_WARN_BYTES + 1)
        self.assertEqual([i["severity"] for i in middel], ["middel"])
        self.assertEqual(middel[0]["details"], {"bytes": PAGE_WEIGHT_WARN_BYTES + 1, "source": "pagespeed"})
        self.assertEqual([i["severity"] for i in self.weight_issues(PAGE_WEIGHT_POOR_BYTES + 1)], ["hoog"])

    def test_measurement_without_weight_produces_nothing(self):
        self.assertEqual(self.weight_issues(None), [])
        cwv = {"lab": {"lcp": 1000, "cls": 0.01, "tbt": 50}, "field": None}
        self.assertEqual([i for i in rule_vitals([page("/", cwv=cwv)], {}) if i["issue_type"] == "cwv_page_weight"], [])


class ThinContentTest(unittest.TestCase):
    def thin(self, **kw):
        return [i for i in rule_onpage([page("/dienst/", **kw)], {}) if i["issue_type"] == "thin_content"]

    def test_main_content_under_threshold(self):
        # Groot menu: het totaal haalt de drempel, de hoofdinhoud niet.
        issues = self.thin(word_count=900, main_word_count=THIN_MAIN_WORDS - 1)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["details"], {"word_count": THIN_MAIN_WORDS - 1, "measure": "main"})
        self.assertIn("hoofdinhoud", issues[0]["title"])
        self.assertIn("900", issues[0]["description"])
        self.assertEqual(thin_content_check(page("/x/", word_count=900, main_word_count=199)), (True, 199, "main"))

    def test_no_structure_falls_back_to_total(self):
        issues = self.thin(word_count=THIN_CONTENT_WORDS - 1, main_word_count=None)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["details"], {"word_count": THIN_CONTENT_WORDS - 1, "measure": "total"})
        self.assertIn("in de HTML", issues[0]["title"])
        self.assertEqual(self.thin(word_count=THIN_CONTENT_WORDS, main_word_count=None), [])
        # Pagina-objecten zonder het veld vallen ook terug op het totaal.
        self.assertEqual(thin_content_check(page("/x/", word_count=10)), (True, 10, "total"))

    def test_enough_main_content(self):
        # Hoofdinhoud op de drempel is genoeg, ook al is het totaal veel groter.
        self.assertEqual(self.thin(word_count=1500, main_word_count=THIN_MAIN_WORDS), [])
        # Totaal onder 300 maar hoofdinhoud boven 200: niet dun (de hoofdinhoud is leidend).
        self.assertEqual(self.thin(word_count=250, main_word_count=220), [])


class CatalogTest(unittest.TestCase):
    """Elk type dat een fase 1-regel kan opleveren, heeft een label en categorie."""

    def emitted_literal_types(self):
        source = Path(issues_module.__file__).read_text(encoding="utf-8")
        rules = source.split("RULES: list[Rule]")[0]
        literal = set(re.findall(r'_issue\(\s*"([a-z0-9_]+)"', rules))
        # rule_duplicates geeft het type door via een tabel: ("title_duplicate", "middel", ...).
        table = set(re.findall(r'\("([a-z0-9_]+)", "(?:laag|middel|hoog)"', rules))
        return literal | table

    def ai_check_types(self):
        source = Path(ai_checks_module.__file__).read_text(encoding="utf-8")
        return {f"ai_{key}" for key in re.findall(r'_check\(\s*"([a-z0-9_]+)"', source)}

    def test_every_rule_type_is_in_issue_types(self):
        emitted = self.emitted_literal_types() | self.ai_check_types()
        self.assertTrue({"robots_blocked_in_sitemap", "hreflang_invalid", "og_incomplete", "cwv_page_weight",
                         "ai_robots_txt", "ai_page_access"} <= emitted)
        self.assertEqual(sorted(emitted - set(ISSUE_TYPES)), [])

    def test_issues_from_a_full_run_are_known(self):
        links = hl(("en-UK", f"{SITE}/en/"), ("nl-NL", "/"))
        pages = [
            page("/", hreflang=links, open_graph=None, title=None, cwv={"lab": {"lcp": 9000, "cls": 0.5, "tbt": 900,
                                                                               "total_byte_weight": 9e6}}),
            page("/en/", hreflang=hl(("en-GB", f"{SITE}/en/"))),
            page("/stuk/", status_code=404),
        ]
        ai = {"checks": [{"key": "llms_txt", "label": "llms.txt", "status": "warning", "message": "x"}],
              "robots_pages": {"total": 1, "pages": [{"url": f"{SITE}/en/", "blocked_for": ["Bingbot"], "rule": "Disallow: /en/"}]}}
        emitted = set(types(generate_issues(pages, ai)))
        self.assertTrue({"robots_blocked_in_sitemap", "hreflang_invalid", "og_incomplete", "cwv_page_weight"} <= emitted)
        self.assertEqual(sorted(emitted - set(ISSUE_TYPES)), [])

    def test_since_types_exist_and_are_current(self):
        self.assertEqual(sorted(set(ISSUE_TYPE_SINCE) - set(ISSUE_TYPES)), [])
        self.assertTrue(all(1 < v <= RULESET_VERSION for v in ISSUE_TYPE_SINCE.values()))


if __name__ == "__main__":
    unittest.main()
