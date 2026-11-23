import math
import unittest

from app.features.competitor_analysis.schemas import ALL_MODULES
from app.features.competitor_analysis.services import estimate as est
from app.services.ahrefs.client import SERP_EXTRA_POSITIONS

ALL = list(ALL_MODULES)


class EstimateTests(unittest.TestCase):
    def test_full_formula(self):
        result = est.estimate(keywords=2, top_n=10, own_urls=1, modules=ALL, ai_configured=True)
        pages = 2 * 11
        self.assertEqual(result.pages, pages)
        units = 2 * (10 + SERP_EXTRA_POSITIONS) * est.AHREFS_UNITS_PER_SERP_POSITION
        # Zoekwoordgegevens en URL-metrics gaan elk in één aanvraag, met een minimum per aanvraag.
        units += max(est.AHREFS_MIN_UNITS_PER_REQUEST, 2 * est.AHREFS_UNITS_PER_KEYWORD)
        units += max(est.AHREFS_MIN_UNITS_PER_REQUEST, 1 * est.AHREFS_UNITS_PER_URL)
        self.assertEqual(result.ahrefs_units, math.ceil(units))
        usd = pages * (est.CLAUDE_USD_PER_PAGE_CLASSIFY + est.CLAUDE_USD_PER_PAGE_ANALYZE)
        usd += 2 * est.CLAUDE_USD_PER_KEYWORD
        self.assertAlmostEqual(result.ai_cost_eur, round(usd * est.USD_TO_EUR, 2))
        seconds = pages * est.SECONDS_PER_PAGE + 2 * (est.SECONDS_PER_KEYWORD_BASE + est.SECONDS_PER_KEYWORD_ANALYZE)
        self.assertEqual(result.seconds, math.ceil(seconds))

    def test_serp_units_measured_rate(self):
        # Gemeten: top_positions=10 kostte 315 units, dus 31,5 per opgevraagde positie.
        result = est.estimate(keywords=1, top_n=5, own_urls=0, modules=["serp"], ai_configured=False)
        # Eén zoekwoord kost 31 units, maar Ahrefs rekent minimaal 50 per aanvraag.
        self.assertEqual(result.ahrefs_units, math.ceil(10 * 31.5) + 50)

    def test_minimum_units_per_request(self):
        # Gemeten in een echte run: 1 zoekwoord + 1 eigen URL, top 5 = 315 + 50 + 50 units.
        result = est.estimate(keywords=1, top_n=5, own_urls=1, modules=ALL, ai_configured=True)
        self.assertEqual(result.ahrefs_units, 415)
        none = est.estimate(keywords=0, top_n=5, own_urls=0, modules=ALL, ai_configured=True)
        self.assertEqual(none.ahrefs_units, 0)

    def test_without_authority_no_url_units(self):
        with_auth = est.estimate(keywords=1, top_n=10, own_urls=3, modules=ALL, ai_configured=True)
        modules = [m for m in ALL if m != "authority"]
        without = est.estimate(keywords=1, top_n=10, own_urls=3, modules=modules, ai_configured=True)
        self.assertEqual(with_auth.ahrefs_units - without.ahrefs_units, 3 * est.AHREFS_UNITS_PER_URL)

    def test_without_topics_and_eeat_only_classification(self):
        modules = ["serp", "onpage", "authority", "tech"]
        result = est.estimate(keywords=2, top_n=10, own_urls=0, modules=modules, ai_configured=True)
        self.assertAlmostEqual(result.ai_cost_eur, round(22 * est.CLAUDE_USD_PER_PAGE_CLASSIFY * est.USD_TO_EUR, 2))
        self.assertEqual(result.seconds, math.ceil(22 * est.SECONDS_PER_PAGE + 2 * est.SECONDS_PER_KEYWORD_BASE))
        self.assertFalse(est.runs_analysis(modules))
        self.assertTrue(est.runs_analysis(["eeat"]))

    def test_without_claude_key_no_ai_cost(self):
        result = est.estimate(keywords=3, top_n=20, own_urls=3, modules=ALL, ai_configured=False)
        self.assertEqual(result.ai_cost_eur, 0.0)
        self.assertEqual(result.pages, 63)

    def test_rates_match_constants(self):
        rates = est.rates()
        self.assertEqual(rates.serp_extra_positions, SERP_EXTRA_POSITIONS)
        self.assertEqual(rates.ahrefs_units_per_serp_position, 31.5)
        self.assertAlmostEqual(rates.claude_usd_per_page, est.CLAUDE_USD_PER_PAGE_CLASSIFY + est.CLAUDE_USD_PER_PAGE_ANALYZE)
        self.assertAlmostEqual(rates.claude_eur_per_keyword, est.CLAUDE_USD_PER_KEYWORD * est.USD_TO_EUR)
        self.assertEqual(rates.seconds_per_keyword, est.SECONDS_PER_KEYWORD_BASE + est.SECONDS_PER_KEYWORD_ANALYZE)


if __name__ == "__main__":
    unittest.main()
