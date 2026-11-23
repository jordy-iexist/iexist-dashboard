import unittest
from types import SimpleNamespace

from app.features.competitor_analysis.schemas import MedianRow
from app.features.competitor_analysis.services import comparison
from app.features.competitor_analysis.services.page_facts import is_unreadable, onpage_from_extract
from app.features.launch_checklist.services.content_extract import ContentExtract


def page(
    pid,
    position=None,
    *,
    words=1000,
    h2=8,
    faq=False,
    schema=("WebPage", "Organization"),
    rd=None,
    dr=None,
    lcp=None,
    fetch="ok",
    excluded=False,
    own=False,
    page_type="dienst",
    url=None,
):
    onpage = {"word_count": words, "h2_count": h2, "has_faq": faq, "schema_types": list(schema)}
    return SimpleNamespace(
        id=pid, is_own=own, position=position, url=url or f"https://{pid}.nl/seo/", domain=None,
        page_type=page_type, is_excluded=excluded, exclude_reason="aggregator" if excluded else None,
        fetch_status=fetch, onpage=onpage if fetch == "ok" else None,
        refdomains=rd, domain_rating=dr, lcp_ms=lcp,
    )


def comps(**values):
    """Drie concurrenten met per metriek de gegeven waarden (lijsten van drie)."""
    rows = []
    for index in range(3):
        kwargs = {key: value[index] for key, value in values.items()}
        rows.append(page(f"c{index}", index + 1, **kwargs))
    return rows


class PageFactsTests(unittest.TestCase):
    def test_onpage_from_extract(self):
        extract = ContentExtract(
            title="SEO bureau", meta_description="Meta",
            headings=[{"level": 1, "text": "SEO bureau"}, {"level": 2, "text": "Wat doen we"},
                      {"level": 3, "text": "Techniek"}, {"level": 2, "text": "Prijzen"}],
            body_text="# SEO bureau\nTekst", word_count=420,
            images=[{"src": "a.jpg"}, {"src": "b.jpg"}],
            links=[{"url": "https://x.nl/a"}, {"url": "https://x.nl/a"}, {"url": "https://x.nl/b"}],
            signals={"schema_types": ["FAQPage", "WebPage"], "has_faq_schema": True},
        )
        onpage = onpage_from_extract(extract)
        self.assertEqual(onpage.h1, "SEO bureau")
        self.assertEqual((onpage.h2_count, onpage.h3_count), (2, 1))
        self.assertEqual(onpage.internal_links, 2)
        self.assertEqual(onpage.images, 2)
        self.assertTrue(onpage.has_faq)
        self.assertEqual(onpage.word_count, 420)

    def test_faq_rule_like_geo_extract(self):
        def faq(signals, text=""):
            return onpage_from_extract(ContentExtract(body_text=text, signals=signals)).has_faq

        self.assertTrue(faq({"details_count": 2}))
        self.assertTrue(faq({"question_headings": 3}))
        self.assertFalse(faq({"question_headings": 2}))
        self.assertTrue(faq({"question_headings": 1}, "## Veelgestelde vragen"))
        self.assertFalse(faq({"question_headings": 0}, "## Veelgestelde vragen"))

    def test_unreadable_below_50_words(self):
        self.assertTrue(is_unreadable({"word_count": 49}))
        self.assertFalse(is_unreadable({"word_count": 50}))
        self.assertFalse(is_unreadable(None))


class MedianTests(unittest.TestCase):
    def test_median_needs_three_values(self):
        two = comps(words=[1000, 2000, 3000], dr=[10, 20, None])
        median = comparison.median_row(two)
        self.assertEqual(median.words, 2000)
        self.assertIsNone(median.domain_rating)  # maar twee waarden
        self.assertEqual(median.total, 3)

    def test_excluded_own_and_failed_pages_do_not_count_on_page(self):
        rows = comps(words=[1000, 2000, 3000], rd=[10, 20, 30])
        rows += [
            page("agg", 4, words=9000, rd=9000, excluded=True),
            page("eigen", None, words=10, own=True, rd=1),
            page("kapot", 5, fetch="blocked", rd=40),
        ]
        median = comparison.median_row(rows)
        self.assertEqual(median.words, 2000)
        self.assertEqual(median.total, 3)
        # DR/RD tellen ook mee bij een mislukte ophaalpoging, maar niet bij uitgesloten/eigen.
        self.assertEqual(median.refdomains, 25)

    def test_unreadable_pages_do_not_count(self):
        rows = comps(words=[1000, 2000, 3000]) + [page("js", 4, words=12, lcp=1000)]
        median = comparison.median_row(rows)
        self.assertEqual(median.words, 2000)
        self.assertEqual(median.total, 3)

    def test_unreadable_leaves_too_few_values(self):
        rows = comps(words=[1000, 2000, 30])
        median = comparison.median_row(rows)
        self.assertIsNone(median.words)
        self.assertEqual(median.total, 2)

    def test_faq_and_schema_counts(self):
        rows = comps(
            faq=[True, True, False],
            schema=[("WebPage", "Service"), ("Service", "FAQPage"), ("WebPage", "Organization")],
        )
        median = comparison.median_row(rows)
        self.assertEqual(median.faq_count, 2)
        self.assertEqual(median.schema_count, 2)  # alleen generieke types telt niet
        self.assertEqual(median.schema_top, "Service")

    def test_metrics_unknown_when_not_fetched(self):
        values = comparison.metrics(page("x", 1, fetch="error", dr=30))
        self.assertIsNone(values["words"])
        self.assertIsNone(values["faq"])
        self.assertEqual(values["domain_rating"], 30)


class FlagTests(unittest.TestCase):
    def flag(self, metric, own_value, median_value, **own_kwargs):
        median = MedianRow(**{metric: median_value, "total": 3})
        key = {"words": "words", "h2_count": "h2", "refdomains": "rd", "domain_rating": "dr", "lcp_ms": "lcp"}[metric]
        own = page("eigen", own=True, **{key: own_value}, **own_kwargs)
        return comparison.flags(own, median)[metric]

    def test_words_ratio_boundary(self):
        self.assertFalse(self.flag("words", 750, 1000))  # precies 75%
        self.assertTrue(self.flag("words", 749, 1000))

    def test_words_gap_boundary(self):
        self.assertTrue(self.flag("words", 250, 400))  # verschil precies 150
        self.assertFalse(self.flag("words", 251, 400))  # verschil 149

    def test_h2(self):
        self.assertFalse(self.flag("h2_count", 6, 8))
        self.assertTrue(self.flag("h2_count", 5, 8))
        self.assertFalse(self.flag("h2_count", 2, 3))  # onder 75%, maar verschil 1

    def test_refdomains(self):
        self.assertTrue(self.flag("refdomains", 7, 10))
        self.assertFalse(self.flag("refdomains", 2, 4))  # verschil 2 < 3

    def test_domain_rating(self):
        self.assertFalse(self.flag("domain_rating", 15, 20))
        self.assertTrue(self.flag("domain_rating", 14, 20))
        self.assertFalse(self.flag("domain_rating", 8, 12))  # verschil 4
        self.assertTrue(self.flag("domain_rating", 7, 12))

    def test_lcp(self):
        self.assertFalse(self.flag("lcp_ms", 3000, 2400))  # precies 125%
        self.assertTrue(self.flag("lcp_ms", 3001, 2400))
        self.assertFalse(self.flag("lcp_ms", 2500, 1600))  # niet boven 2,5 s
        self.assertTrue(self.flag("lcp_ms", 2501, 1600))

    def test_no_median_or_no_own_value_is_never_red(self):
        self.assertFalse(self.flag("words", 10, None))
        median = MedianRow(domain_rating=50, total=3)
        self.assertFalse(comparison.flags(page("eigen", own=True, dr=None), median)["domain_rating"])

    def test_faq_rule(self):
        own = page("eigen", own=True, faq=False)
        self.assertTrue(comparison.flags(own, MedianRow(faq_count=2, total=4))["faq"])
        self.assertFalse(comparison.flags(own, MedianRow(faq_count=1, total=4))["faq"])
        self.assertFalse(comparison.flags(own, MedianRow(faq_count=2, total=2))["faq"])  # te weinig
        has = page("eigen", own=True, faq=True)
        self.assertFalse(comparison.flags(has, MedianRow(faq_count=4, total=4))["faq"])

    def test_schema_rule_ignores_generic_types(self):
        own = page("eigen", own=True, schema=("WebPage", "Organization", "BreadcrumbList"))
        self.assertTrue(comparison.flags(own, MedianRow(schema_count=3, total=5))["schema"])
        own = page("eigen", own=True, schema=("Service",))
        self.assertFalse(comparison.flags(own, MedianRow(schema_count=5, total=5))["schema"])

    def test_unreadable_or_failed_own_page_has_no_onpage_flags(self):
        median = MedianRow(words=2000, faq_count=3, total=3, domain_rating=40)
        js = page("eigen", own=True, words=20, dr=10)
        result = comparison.flags(js, median)
        self.assertFalse(result["words"])
        self.assertFalse(result["faq"])
        self.assertTrue(result["domain_rating"])
        failed = page("eigen", own=True, fetch="blocked")
        self.assertFalse(comparison.flags(failed, median)["words"])

    def test_no_own_page(self):
        self.assertEqual(set(comparison.flags(None, MedianRow(words=1000, total=3)).values()), {False})


class TableTests(unittest.TestCase):
    def test_table_contains_rows_median_and_red_own_row(self):
        rows = comps(words=[2000, 2500, 3000], dr=[30, 40, 50], faq=[True, True, True])
        rows.append(page("agg", 4, excluded=True, page_type="vergelijker"))
        rows.append(page("eigen", None, own=True, words=500, dr=10, url="https://klant.nl/seo/"))
        table = comparison.metrics_table(rows)
        self.assertIn("P1 | 1 | c0.nl", table)
        self.assertIn("P4 | 4 | agg.nl", table)
        self.assertIn("uitgesloten: vergelijkingssite/gids", table)
        self.assertIn("MEDIAAN over 3 meegetelde concurrenten", table)
        self.assertIn("woorden 2500", table)
        self.assertIn("EIGEN | — | klant.nl | https://klant.nl/seo/ | dienst | 500 [ROOD]", table)
        self.assertIn("nee [ROOD]", table)  # FAQ
        self.assertIn("Rode vlaggen eigen pagina (duidelijk slechter dan de mediaan): woorden, FAQ, DR", table)
        self.assertIn("3 dienstpagina's, 1 vergelijkingssites/gidsen", table)

    def test_table_without_own_page(self):
        table = comparison.metrics_table(comps(words=[1, 2, 3]))
        self.assertIn("geen eigen pagina", table)
        self.assertNotIn("[ROOD]", table)

    def test_short_ids_follow_serp_order(self):
        rows = [page("b", 2), page("a", 1), page("eigen", own=True)]
        self.assertEqual(comparison.short_ids(rows), {"a": "P1", "b": "P2", "eigen": "EIGEN"})


if __name__ == "__main__":
    unittest.main()
