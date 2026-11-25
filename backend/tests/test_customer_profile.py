"""Het klantprofiel (features/customers/profile.py): opschonen in plaats van weigeren, en
`parse_profile` dat nooit een exception geeft."""
import unittest

from pydantic import ValidationError

from app.features.customers import profile as module
from app.features.customers.profile import CustomerProfile, CustomerService, parse_profile


class CleanupTests(unittest.TestCase):
    def test_empty_profile_has_contract_shape(self):
        self.assertEqual(CustomerProfile().model_dump(), {
            "company_type": "", "service_area": "", "target_audience": "", "specialties": "",
            "services": [], "services_source": "",
            "usps": [], "reviews": "", "certifications": "", "team": "", "cases": [],
            "language_level": "", "fixed_cta": "",
            "example_urls": [], "avoid_words": [], "content_rules": [],
        })

    def test_text_whitespace_none_and_limit(self):
        profile = CustomerProfile(company_type="  SEO-\n  bureau  ", service_area=None, reviews="x" * 400)
        self.assertEqual(profile.company_type, "SEO- bureau")
        self.assertEqual(profile.service_area, "")
        self.assertEqual(len(profile.reviews), module.MAX_TEXT_CHARS)

    def test_lists_cleaned_deduplicated_and_capped(self):
        profile = CustomerProfile(
            usps=["  Snel  ", "", "   ", None, "snel", "Persoonlijk\ncontact", "Snel"],
            avoid_words=[f"woord{i}" for i in range(100)] + ["x" * 100],
            example_urls=[f"https://klant.nl/{i}" for i in range(20)],
            cases=["c" * 500],
        )
        self.assertEqual(profile.usps, ["Snel", "Persoonlijk contact"])
        self.assertEqual(len(profile.avoid_words), module.MAX_AVOID_WORDS)
        self.assertEqual(len(profile.example_urls), module.MAX_EXAMPLE_URLS)
        self.assertEqual(len(profile.cases[0]), module.MAX_LIST_ITEM_CHARS)
        self.assertEqual(CustomerProfile(content_rules=None).content_rules, [])
        many = CustomerProfile(content_rules=[f"Regel {i}" for i in range(50)])
        self.assertEqual(len(many.content_rules), module.MAX_LIST_ITEMS)
        long_word = CustomerProfile(avoid_words=["y" * 100]).avoid_words[0]
        self.assertEqual(len(long_word), module.MAX_AVOID_WORD_CHARS)

    def test_services(self):
        profile = CustomerProfile(services=[
            {"name": "  SEO-traject ", "price": " vanaf € 750  per maand "},
            {"name": "", "price": "€ 100"},
            {"name": "   ", "price": ""},
            {"price": "€ 5"},
            None,
            {"name": "seo-traject", "price": "Vanaf € 750 per maand"},
            {"name": "Audit", "extra": "genegeerd"},
            CustomerService(name="Linkbuilding", price="op aanvraag"),
            {"name": "n" * 200, "price": "p" * 200},
        ])
        self.assertEqual([(s.name, s.price) for s in profile.services[:3]], [
            ("SEO-traject", "vanaf € 750 per maand"), ("Audit", ""), ("Linkbuilding", "op aanvraag"),
        ])
        self.assertEqual(len(profile.services), 4)
        self.assertEqual(len(profile.services[3].name), module.MAX_SERVICE_CHARS)
        self.assertEqual(len(profile.services[3].price), module.MAX_SERVICE_CHARS)
        capped = CustomerProfile(services=[{"name": f"Dienst {i}"} for i in range(60)])
        self.assertEqual(len(capped.services), module.MAX_SERVICES)

    def test_unknown_fields_ignored_and_wrong_types_rejected(self):
        self.assertEqual(CustomerProfile.model_validate({"onbekend": 1, "team": "Jan"}).team, "Jan")
        with self.assertRaises(ValidationError):
            CustomerProfile(usps=5)
        with self.assertRaises(ValidationError):
            CustomerProfile(services="SEO")
        with self.assertRaises(ValidationError):
            CustomerProfile(company_type=["lijst"])


class ParseProfileTests(unittest.TestCase):
    def test_empty_or_garbage_gives_empty_profile(self):
        for raw in (None, {}, [], "kapot", 42, [{"name": "x"}]):
            self.assertEqual(parse_profile(raw), CustomerProfile(), raw)

    def test_valid_storage(self):
        profile = parse_profile({"usps": ["Snel", "snel"], "services": [{"name": "SEO", "price": "€ 1"}]})
        self.assertEqual(profile.usps, ["Snel"])
        self.assertEqual(profile.services[0].price, "€ 1")

    def test_invalid_field_drops_only_that_field(self):
        profile = parse_profile({"usps": 5, "team": "Jan", "services": "kapot", "cases": ["Case A"]})
        self.assertEqual((profile.usps, profile.services), ([], []))
        self.assertEqual((profile.team, profile.cases), ("Jan", ["Case A"]))


if __name__ == "__main__":
    unittest.main()
