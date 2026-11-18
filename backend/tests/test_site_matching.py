"""Klant en WordPress-koppeling bij elkaar zoeken op hostnaam (`app.services.site_matching`).

Alleen de pure matching; er is geen database nodig.
"""
import unittest

from app.services.site_matching import match_customer_ids, normalize_host


class NormalizeHostTests(unittest.TestCase):
    def test_www_is_ignored(self):
        self.assertEqual(normalize_host("https://www.example.nl/pad/"), "example.nl")

    def test_without_scheme(self):
        self.assertEqual(normalize_host("www.Example.nl"), "example.nl")
        self.assertEqual(normalize_host("example.nl/pad"), "example.nl")

    def test_empty_or_none(self):
        self.assertEqual(normalize_host(None), "")
        self.assertEqual(normalize_host(""), "")
        self.assertEqual(normalize_host("   "), "")

    def test_other_subdomain_is_kept(self):
        self.assertEqual(normalize_host("https://blog.example.nl"), "blog.example.nl")


class MatchCustomerIdsTests(unittest.TestCase):
    def test_match_via_domain(self):
        result = match_customer_ids([("s1", "https://www.example.nl/")], [("c1", "example.nl", "")])
        self.assertEqual(result, {"s1": ["c1"]})

    def test_match_via_base_url(self):
        result = match_customer_ids([("s1", "example.nl")], [("c1", "", "https://www.example.nl/home")])
        self.assertEqual(result, {"s1": ["c1"]})

    def test_domain_and_base_url_give_no_duplicate_id(self):
        result = match_customer_ids([("s1", "https://example.nl")],
                                    [("c1", "example.nl", "https://www.example.nl/")])
        self.assertEqual(result, {"s1": ["c1"]})

    def test_multiple_customers_on_same_host(self):
        result = match_customer_ids([("s1", "https://example.nl")],
                                    [("c1", "example.nl", None), ("c2", None, "https://www.example.nl")])
        self.assertEqual(result, {"s1": ["c1", "c2"]})

    def test_other_subdomain_does_not_match(self):
        result = match_customer_ids([("s1", "https://blog.example.nl")], [("c1", "example.nl", "https://example.nl")])
        self.assertEqual(result, {"s1": []})

    def test_empty_or_none_input_does_not_match(self):
        result = match_customer_ids([("s1", None), ("s2", "")], [("c1", None, None), ("c2", "", "  ")])
        self.assertEqual(result, {"s1": [], "s2": []})

    def test_site_without_match_gets_empty_list(self):
        result = match_customer_ids([("s1", "https://example.nl"), ("s2", "https://ander.nl")],
                                    [("c1", "example.nl", "https://example.nl")])
        self.assertEqual(result, {"s1": ["c1"], "s2": []})

    def test_ids_are_strings(self):
        result = match_customer_ids([(1, "example.nl")], [(2, "example.nl", None)])
        self.assertEqual(result, {"1": ["2"]})


if __name__ == "__main__":
    unittest.main()
