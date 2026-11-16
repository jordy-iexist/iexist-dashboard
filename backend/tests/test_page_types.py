"""Paginatype 'landing' (dienst + plaats) en de bijbehorende schema-check."""
import unittest
from types import SimpleNamespace
from unittest import mock

from app.features.launch_checklist.services import geo_rebuild
from app.features.launch_checklist.services.geo_checks import _local_service_result
from app.features.launch_checklist.services.page_types import find_landing_series

BASE = "https://www.iexist.nl"
PLACES = {
    "almere": "Almere", "zeewolde": "Zeewolde", "utrecht": "Utrecht", "arnhem": "Arnhem",
    "voorthuizen": "Voorthuizen", "gelderland": "Gelderland", "overijssel": "Overijssel",
    "het-harde": "Het Harde", "vaassen": "Vaassen", "wijk-bij-duurstede": "Wijk bij Duurstede",
    "naarden": "Naarden", "deventer": "Deventer", "de-bilt": "De Bilt", "amerongen": "Amerongen",
    "oldebroek": "Oldebroek",
}


def page(path: str, title: str = "", **kw):
    base = dict(
        id=path, url=BASE + path, path=path, title=title, h1=[title], signals={}, jsonld=[],
        page_type=None, page_type_source=None, status_code=200, redirect_chain=None,
        content_type="text/html", indexable=True, final_url=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def landing_pages():
    return [page(f"/website-laten-maken-{slug}/", f"Website laten maken {name} | iExist")
            for slug, name in PLACES.items()]


def apply(pages, overrides=None):
    with mock.patch.object(geo_rebuild, "load_overrides", return_value=overrides or {}):
        geo_rebuild.apply_page_types(None, pages, customer_id="c", base_url=BASE, user_id=None, use_llm=False)
    return {p.path: p.page_type for p in pages}


class LandingSeriesTest(unittest.TestCase):
    def test_reported_urls_become_landing(self):
        types = apply([page("/", "Home")] + landing_pages())
        for slug in PLACES:
            self.assertEqual(types[f"/website-laten-maken-{slug}/"], "landing", slug)
        self.assertEqual(types["/"], "home")

    def test_previous_ai_label_is_corrected(self):
        pages = [page("/", "Home")] + landing_pages()
        for p in pages[1:]:
            p.page_type, p.page_type_source = "dienst", "ai"
        types = apply(pages)
        self.assertEqual(set(types[p.path] for p in pages[1:]), {"landing"})

    def test_other_types_stay(self):
        pages = [page("/", "Home"), page("/diensten/seo/", "SEO"),
                 page("/blog/seo-in-almere/", "SEO in Almere")] + landing_pages()
        types = apply(pages)
        self.assertEqual(types["/diensten/seo/"], "dienst")
        self.assertEqual(types["/blog/seo-in-almere/"], "blog")

    def test_series_without_known_place_is_not_landing(self):
        pages = [page(f"/seo-{s}/", f"SEO {s}") for s in ("tips", "kosten", "uitleg")]
        self.assertEqual(find_landing_series(pages), [])

    def test_small_group_is_not_a_series(self):
        pages = [page("/seo-almere/", "SEO Almere"), page("/seo-utrecht/", "SEO Utrecht")]
        self.assertEqual(find_landing_series(pages), [])

    def test_manual_override_wins(self):
        pages = landing_pages()
        types = apply(pages, overrides={"/website-laten-maken-almere/": "dienst"})
        self.assertEqual(types["/website-laten-maken-almere/"], "dienst")
        self.assertEqual(types["/website-laten-maken-utrecht/"], "landing")


class LocalServiceSchemaTest(unittest.TestCase):
    def test_statuses(self):
        service_area = [{"@type": "Service", "name": "Website", "areaServed": {"@type": "City", "name": "Almere"}}]
        service = [{"@type": "Service", "name": "Website"}]
        self.assertEqual(_local_service_result([], None)["status"], "nvt")
        self.assertEqual(_local_service_result([page("/a/", jsonld=service_area)], None)["status"], "ok")
        self.assertEqual(_local_service_result([page("/a/", jsonld=service)], None)["status"], "warning")
        self.assertEqual(_local_service_result([page("/a/")], None)["status"], "error")

    def test_nested_service_counts(self):
        nested = [{"@type": "WebPage", "mainEntity": {"@type": "Service", "areaServed": "Almere"}}]
        self.assertEqual(_local_service_result([page("/a/", jsonld=nested)], None)["status"], "ok")

    def test_site_wide_local_business_does_not_count(self):
        org = {"@type": "LocalBusiness", "name": "iExist", "areaServed": "Nederland"}
        home = page("/", jsonld=[org])
        self.assertEqual(_local_service_result([page("/a/", jsonld=[org])], home)["status"], "error")
        own = {"@type": "LocalBusiness", "name": "iExist Almere", "areaServed": "Almere"}
        self.assertEqual(_local_service_result([page("/a/", jsonld=[own])], home)["status"], "ok")


if __name__ == "__main__":
    unittest.main()
