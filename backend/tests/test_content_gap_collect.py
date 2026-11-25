"""Ophalen voor Zoekwoorden › Content gap (features/keywords/services/gap_collect.py).

De Ahrefs-client is vervangen; geen netwerk.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.features.keywords.schemas import Raw, RawTop10
from app.features.keywords.services import gap_collect
from app.features.keywords.services.collect import CHECK_CHUNK, UnitBudget
from app.services.ahrefs.client import AhrefsResult, AhrefsServiceError

SETTINGS = SimpleNamespace(ahrefs_competitors_keywords_per_domain=150)


def rows(*pairs):
    return [{"keyword": k, "best_position": p} for k, p in pairs]


class _Base(unittest.TestCase):
    def setUp(self):
        self.mocks = {}
        for name in ("top10_keywords", "keywords_overview"):
            patcher = patch.object(gap_collect.ahrefs, name)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(gap_collect, "settings", SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)


class CollectListsTest(_Base):
    def test_lists_from_scan_cost_nothing_and_missing_are_fetched(self):
        raw = Raw(top10={"klant.nl": RawTop10(keywords=["eigen"]), "a.nl": RawTop10(keywords=["x", "y"])})
        self.mocks["top10_keywords"].return_value = AhrefsResult(rows=rows(("Z", 3), ("z", 4), ("w", 1)), units=300)
        budget = UnitBudget(5000)

        lists = gap_collect.collect_lists(raw, customer_domain="www.klant.nl", competitors=["a.nl", "b.nl"],
                                          country="nl", budget=budget)

        self.assertEqual(lists, {"klant.nl": ["eigen"], "a.nl": ["x", "y"], "b.nl": ["Z", "w"]})
        self.mocks["top10_keywords"].assert_called_once_with("b.nl", country="nl", limit=150)
        self.assertEqual((budget.spent, budget.skipped), (300, []))

    def test_error_skips_domain_and_fatal_error_raises(self):
        self.mocks["top10_keywords"].side_effect = AhrefsServiceError("Ahrefs-fout: kapot")
        budget = UnitBudget(5000)
        lists = gap_collect.collect_lists(Raw(), customer_domain="klant.nl", competitors=["a.nl"], country="nl",
                                          budget=budget)
        self.assertEqual(lists, {})
        self.assertEqual(budget.skipped, ["top 10-zoekwoorden van klant.nl (Ahrefs-fout: kapot)",
                                          "top 10-zoekwoorden van a.nl (Ahrefs-fout: kapot)"])

        self.mocks["top10_keywords"].side_effect = AhrefsServiceError("geen units", code="forbidden")
        with self.assertRaises(AhrefsServiceError):
            gap_collect.collect_lists(Raw(), customer_domain="klant.nl", competitors=["a.nl"], country="nl",
                                      budget=UnitBudget(5000))

    def test_budget_too_small_skips(self):
        budget = UnitBudget(299)  # één lijst van 150 rijen schat 300 units
        lists = gap_collect.collect_lists(Raw(), customer_domain="klant.nl", competitors=["a.nl"], country="nl",
                                          budget=budget)
        self.assertEqual(lists, {})
        self.mocks["top10_keywords"].assert_not_called()
        self.assertEqual(budget.skipped, ["top 10-zoekwoorden van klant.nl", "top 10-zoekwoorden van a.nl"])


class CollectPositionsTest(_Base):
    def test_chunks_and_max_position(self):
        keywords = [f"kw {i}" for i in range(CHECK_CHUNK + 1)] + ["KW  0"]  # dubbel via keyword_key
        self.mocks["top10_keywords"].side_effect = [
            AhrefsResult(rows=rows(("kw 0", 14), ("KW 0", 12), ("kw 3", 2)), units=60),
            AhrefsResult(rows=[], units=50),
        ]
        budget = UnitBudget(5000)

        result = gap_collect.collect_positions("klant.nl", keywords, country="nl", max_position=None, budget=budget)

        self.assertEqual(self.mocks["top10_keywords"].call_count, 2)
        first, second = self.mocks["top10_keywords"].call_args_list
        self.assertEqual(len(first.kwargs["keywords"]), CHECK_CHUNK)
        self.assertEqual((first.kwargs["limit"], first.kwargs["max_position"]), (CHECK_CHUNK, None))
        self.assertEqual(second.kwargs["keywords"], [f"kw {CHECK_CHUNK}"])
        self.assertEqual(result.positions, {"kw 0": 12, "kw 3": 2})
        self.assertEqual(len(result.checked), CHECK_CHUNK + 1)
        self.assertEqual(budget.spent, 110)

    def test_budget_runs_out_halfway(self):
        keywords = [f"kw {i}" for i in range(CHECK_CHUNK + 10)]
        self.mocks["top10_keywords"].return_value = AhrefsResult(rows=rows(("kw 1", 4)), units=280)
        budget = UnitBudget(320)

        result = gap_collect.collect_positions("a.nl", keywords, country="nl", max_position=10, budget=budget)
        # Eerste deel: schatting 300 past, echt 280. Tweede deel: schatting 50 past niet meer.
        self.assertEqual(self.mocks["top10_keywords"].call_count, 1)
        self.assertEqual(result.positions, {"kw 1": 4})
        self.assertNotIn(f"kw {CHECK_CHUNK}", result.checked)
        self.assertEqual(budget.skipped, [f"posities van 10 van {CHECK_CHUNK + 10} zoekwoorden bij a.nl"])

    def test_error_in_a_chunk_skips_only_that_chunk(self):
        self.mocks["top10_keywords"].side_effect = AhrefsServiceError("Ahrefs-fout: kapot")
        budget = UnitBudget(5000)
        result = gap_collect.collect_positions("a.nl", ["seo"], country="nl", max_position=10, budget=budget)
        self.assertEqual((result.checked, result.positions), (set(), {}))
        self.assertEqual(budget.skipped, ["posities van 1 zoekwoorden bij a.nl (Ahrefs-fout: kapot)"])


class CollectFactsTest(_Base):
    def test_facts_per_keyword_key(self):
        self.mocks["keywords_overview"].return_value = AhrefsResult(rows=[
            {"keyword": "Dak Lekt", "volume": 900, "difficulty": 12,
             "intents": {"informational": True, "local": True, "commercial": False}},
        ], units=62)
        budget = UnitBudget(5000)
        facts = gap_collect.collect_facts(["dak lekt", "dakgoot"], country="nl", budget=budget)
        self.mocks["keywords_overview"].assert_called_once_with(["dak lekt", "dakgoot"], country="nl")
        self.assertEqual((facts["dak lekt"].volume, facts["dak lekt"].kd, facts["dak lekt"].intents),
                         (900, 12, ["informational", "local"]))
        self.assertEqual((budget.spent, budget.skipped), (62, []))

    def test_only_what_fits_in_the_budget(self):
        self.mocks["keywords_overview"].return_value = AhrefsResult(rows=[], units=93)
        budget = UnitBudget(1000)
        budget.spent = 900  # 100 over: drie zoekwoorden van 31 (schatting 93)
        gap_collect.collect_facts(["a", "b", "c", "d", "e"], country="nl", budget=budget)
        self.mocks["keywords_overview"].assert_called_once_with(["a", "b", "c"], country="nl")
        self.assertEqual(budget.skipped, ["volume, KD en intentie van 2 van 5 zoekwoorden"])

    def test_no_room_at_all(self):
        budget = UnitBudget(1000)
        budget.spent = 980
        facts = gap_collect.collect_facts(["a", "b"], country="nl", budget=budget)
        self.assertEqual(facts, {})
        self.mocks["keywords_overview"].assert_not_called()
        self.assertEqual(budget.skipped, ["volume, KD en intentie van 2 van 2 zoekwoorden"])


if __name__ == "__main__":
    unittest.main()
