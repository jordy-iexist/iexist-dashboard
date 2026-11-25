"""Rekenregels van Zoekwoorden › Content gap (features/keywords/services/gap_compute.py)."""
import unittest

from app.features.competitor_analysis.services.pipeline import KeywordFacts
from app.features.keywords.gap_schemas import UNITS_PER_GAP_KEYWORD, GapCandidate, PositionCheck
from app.features.keywords.services import gap_compute

COMPETITORS = ["a.nl", "b.nl", "c.nl", "d.nl", "e.nl"]


def item(keyword, *domains, first_index=0):
    return GapCandidate(keyword=keyword, key=keyword.casefold(), domains=list(domains), first_index=first_index)


def check(positions, checked=None):
    return PositionCheck(checked=set(checked if checked is not None else positions), positions=positions)


class MaxKeywordsTest(unittest.TestCase):
    def test_units_per_keyword(self):
        self.assertEqual(UNITS_PER_GAP_KEYWORD, 39)
        self.assertEqual(gap_compute.max_keywords(5000), 128)
        self.assertEqual(gap_compute.max_keywords(15000), 384)
        self.assertEqual(gap_compute.max_keywords(38), 0)
        self.assertEqual(gap_compute.max_keywords(-10), 0)


class CandidatesTest(unittest.TestCase):
    def test_boundary_of_two_competitors(self):
        lists = {
            "klant.nl": [],
            "a.nl": ["twee", "een"],
            "b.nl": ["twee"],
        }
        result = gap_compute.candidates(lists, customer_domain="https://www.klant.nl/", competitors=COMPETITORS)
        self.assertEqual([(c.keyword, c.domains) for c in result], [("twee", ["a.nl", "b.nl"])])

    def test_customer_list_excludes_with_keyword_key(self):
        lists = {
            "klant.nl": ["Dak  Lekt"],
            "a.nl": ["dak lekt", "dakgoot"],
            "b.nl": ["DAK LEKT", "Dakgoot"],
        }
        result = gap_compute.candidates(lists, customer_domain="klant.nl", competitors=COMPETITORS)
        self.assertEqual([(c.keyword, c.key, c.domains) for c in result], [("dakgoot", "dakgoot", ["a.nl", "b.nl"])])

    def test_order_most_competitors_then_earliest_place(self):
        lists = {
            "a.nl": ["laat", "vroeg", "drie", "x"],
            "b.nl": ["vroeg", "laat", "drie"],
            "c.nl": ["drie"],
            "d.nl": ["x"],
        }
        result = gap_compute.candidates(lists, customer_domain="klant.nl", competitors=COMPETITORS)
        self.assertEqual([c.keyword for c in result], ["drie", "laat", "vroeg", "x"])
        self.assertEqual([c.first_index for c in result], [0, 0, 0, 0])
        self.assertEqual(result[0].domains, ["a.nl", "b.nl", "c.nl"])

    def test_missing_list_counts_as_empty(self):
        lists = {"a.nl": ["seo"], "b.nl": ["seo"]}  # geen lijst van de klant of van c/d/e
        result = gap_compute.candidates(lists, customer_domain="klant.nl", competitors=COMPETITORS)
        self.assertEqual([c.keyword for c in result], ["seo"])


class BuildSnapshotTest(unittest.TestCase):
    def build(self, items, *, limit=10, checks=None, facts=None, competitors=("a.nl", "b.nl", "c.nl")):
        return gap_compute.build_snapshot(
            items, limit=limit, customer_domain="www.klant.nl", competitors=list(competitors),
            checks=checks or {}, facts=facts or {}, warnings=["w"],
        )

    def test_customer_in_top10_after_check_is_dropped(self):
        items = [item("drop", "a.nl", "b.nl"), item("houd", "a.nl", "b.nl")]
        checks = {
            "klant.nl": check({"drop": 7, "houd": 14}),
            "a.nl": check({"drop": 2, "houd": 3}),
            "b.nl": check({"drop": 4, "houd": 9}),
        }
        snap = self.build(items, checks=checks)
        self.assertEqual([k.keyword for k in snap.keywords], ["houd"])
        keyword = snap.keywords[0]
        self.assertEqual(keyword.own_position, 14)
        self.assertEqual(keyword.positions, {"a.nl": 3, "b.nl": 9, "c.nl": None})
        self.assertEqual(keyword.competitors_count, 2)
        self.assertEqual(snap.found, 1)  # het vervallen zoekwoord telt niet mee
        self.assertEqual((snap.customer_domain, snap.competitors, snap.warnings),
                         ("klant.nl", ["a.nl", "b.nl", "c.nl"], ["w"]))

    def test_cut_at_limit_and_found_counts_all(self):
        items = [item(f"kw{i}", "a.nl", "b.nl") for i in range(5)]
        snap = self.build(items, limit=2)
        self.assertEqual([k.keyword for k in snap.keywords], ["kw0", "kw1"])
        self.assertEqual(snap.found, 5)

    def test_unchecked_positions_fall_back_to_the_lists(self):
        snap = self.build([item("seo", "a.nl", "b.nl")])
        keyword = snap.keywords[0]
        self.assertEqual(keyword.competitors_count, 2)
        self.assertEqual(keyword.positions, {"a.nl": None, "b.nl": None, "c.nl": None})
        self.assertIsNone(keyword.own_position)

    def test_check_decides_for_competitors(self):
        items = [item("weg", "a.nl", "b.nl"), item("erbij", "a.nl", "b.nl")]
        checks = {
            # b.nl staat volgens de navraag niet (meer) in de top 10 voor "weg"; c.nl wel voor
            # "erbij" (zijn lijst was afgekapt).
            "a.nl": check({"weg": 1, "erbij": 2}),
            "b.nl": check({"erbij": 5}, checked={"weg", "erbij"}),
            "c.nl": check({"erbij": 8}, checked={"weg", "erbij"}),
        }
        snap = self.build(items, checks=checks)
        self.assertEqual([k.keyword for k in snap.keywords], ["erbij"])
        self.assertEqual(snap.keywords[0].competitors_count, 3)
        self.assertEqual(snap.found, 1)

    def test_sorted_on_volume_unknown_last(self):
        items = [item("geen", "a.nl", "b.nl"), item("klein", "a.nl", "b.nl"), item("groot", "a.nl", "b.nl")]
        facts = {
            "klein": KeywordFacts(volume=10, kd=3, intents=["informational"]),
            "groot": KeywordFacts(volume=900, kd=40, intents=["commercial", "local"]),
        }
        snap = self.build(items, facts=facts)
        self.assertEqual([k.keyword for k in snap.keywords], ["groot", "klein", "geen"])
        self.assertEqual((snap.keywords[0].kd, snap.keywords[0].intents), (40, ["commercial", "local"]))
        self.assertEqual((snap.keywords[2].volume, snap.keywords[2].kd, snap.keywords[2].intents), (None, None, []))


if __name__ == "__main__":
    unittest.main()
