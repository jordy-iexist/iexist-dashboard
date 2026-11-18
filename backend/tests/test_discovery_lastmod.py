"""Sitemap-discovery: <lastmod> per pagina en mislukte (expliciet aangewezen) sitemaps.

Het netwerk wordt vervangen door een httpx.MockTransport; de URL-guard (DNS) staat uit.
"""
import gzip
import unittest
from unittest.mock import patch

import httpx

from app.features.launch_checklist.services import discovery
from app.features.launch_checklist.services.discovery import discover_from_sitemaps, url_key

BASE = "https://www.klant.nl/"
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def urlset(*entries: tuple[str, str | None]) -> str:
    rows = []
    for loc, lastmod in entries:
        extra = f"<lastmod>{lastmod}</lastmod>" if lastmod is not None else ""
        rows.append(f"<url><loc>{loc}</loc>{extra}</url>")
    return f'<?xml version="1.0"?><urlset {NS}>{"".join(rows)}</urlset>'


def index(*locs: str) -> str:
    rows = "".join(f"<sitemap><loc>{loc}</loc><lastmod>2026-01-01</lastmod></sitemap>" for loc in locs)
    return f'<?xml version="1.0"?><sitemapindex {NS}>{rows}</sitemapindex>'


class DiscoveryLastmodTest(unittest.TestCase):
    def run_discovery(self, responses: dict[str, tuple[int, str | bytes]], **kwargs):
        """`responses`: URL → (status, body). Onbekende URL's geven 404."""
        self.requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            self.requested.append(url)
            status, body = responses.get(url, (404, "niet gevonden"))
            content = body if isinstance(body, bytes) else body.encode()
            return httpx.Response(status, content=content, headers={"content-type": "text/plain"})

        real_client = httpx.Client

        def client(**options):
            return real_client(transport=httpx.MockTransport(handler), **options)

        with patch.object(discovery, "is_safe_external_url", return_value=True), \
                patch.object(discovery.httpx, "Client", side_effect=client):
            return discover_from_sitemaps(BASE, max_urls=kwargs.pop("max_urls", 1000), **kwargs)

    def test_lastmod_per_url_key_stripped_and_missing_left_out(self):
        result = self.run_discovery({
            "https://www.klant.nl/robots.txt": (200, "Sitemap: https://www.klant.nl/sitemap.xml\n"),
            "https://www.klant.nl/sitemap.xml": (200, urlset(
                ("https://www.klant.nl/", "  2026-11-01T10:00:00+01:00\n "),
                ("https://www.klant.nl/over-ons/", None),
                ("https://www.klant.nl/contact/", "   "),
                ("https://www.klant.nl/diensten/", "2026-10-05"),
            )),
        })
        self.assertEqual(len(result.urls), 4)
        self.assertEqual(result.lastmod, {
            url_key("https://www.klant.nl/"): "2026-11-01T10:00:00+01:00",
            url_key("https://www.klant.nl/diensten/"): "2026-10-05",
        })
        self.assertEqual(result.failed_sitemaps, [])

    def test_sitemapindex_with_failed_child(self):
        result = self.run_discovery({
            "https://www.klant.nl/robots.txt": (200, "Sitemap: https://www.klant.nl/sitemap_index.xml\n"),
            "https://www.klant.nl/sitemap_index.xml": (200, index(
                "https://www.klant.nl/page-sitemap.xml",
                "https://www.klant.nl/post-sitemap.xml",
                "https://www.klant.nl/product-sitemap.xml",
                "https://www.klant.nl/kapot-sitemap.xml",
            )),
            "https://www.klant.nl/page-sitemap.xml": (200, urlset(("https://www.klant.nl/a/", "2026-01-02"))),
            "https://www.klant.nl/post-sitemap.xml": (500, "fout"),
            # Gzip zonder sitemap-header in de URL: wordt herkend aan de magic bytes.
            "https://www.klant.nl/product-sitemap.xml": (
                200, gzip.compress(urlset(("https://www.klant.nl/p/", "2026-03-04")).encode())),
            "https://www.klant.nl/kapot-sitemap.xml": (200, "<urlset><url><loc>"),
        })
        self.assertEqual(result.urls, ["https://www.klant.nl/a/", "https://www.klant.nl/p/"])
        self.assertEqual(result.lastmod, {
            url_key("https://www.klant.nl/a/"): "2026-01-02",
            url_key("https://www.klant.nl/p/"): "2026-03-04",
        })
        # De <lastmod> van de sitemap-entries in de index telt niet als paginalastmod.
        self.assertEqual(set(result.failed_sitemaps), {
            "https://www.klant.nl/post-sitemap.xml",
            "https://www.klant.nl/kapot-sitemap.xml",
        })
        self.assertIn("https://www.klant.nl/sitemap_index.xml", result.sitemaps)

    def test_guessed_default_paths_are_not_failures(self):
        # Geen Sitemap-regel in robots.txt: drie gok-paden, twee daarvan 404.
        result = self.run_discovery({
            "https://www.klant.nl/robots.txt": (200, "User-agent: *\nDisallow:\n"),
            "https://www.klant.nl/wp-sitemap.xml": (200, urlset(("https://www.klant.nl/", None))),
        })
        self.assertEqual(result.urls, ["https://www.klant.nl/"])
        self.assertEqual(result.failed_sitemaps, [])
        self.assertEqual(result.lastmod, {})
        self.assertIn("https://www.klant.nl/sitemap.xml", self.requested)

    def test_children_of_a_guessed_index_do_count(self):
        result = self.run_discovery({
            "https://www.klant.nl/sitemap.xml": (200, index("https://www.klant.nl/weg-sitemap.xml")),
        })
        self.assertEqual(result.failed_sitemaps, ["https://www.klant.nl/weg-sitemap.xml"])

    def test_explicit_robots_sitemap_404_and_wrong_root_fail(self):
        result = self.run_discovery({
            "https://www.klant.nl/robots.txt": (200, "Sitemap: https://www.klant.nl/a.xml\n"
                                                     "Sitemap: https://www.klant.nl/b.xml\n"),
            "https://www.klant.nl/b.xml": (200, "<html><body>geen sitemap</body></html>"),
        })
        self.assertEqual(result.urls, [])
        self.assertEqual(result.failed_sitemaps, ["https://www.klant.nl/a.xml", "https://www.klant.nl/b.xml"])

    def test_sitemaps_left_by_max_sitemaps_count_as_failed(self):
        children = [f"https://www.klant.nl/s{i}.xml" for i in range(3)]
        responses = {
            "https://www.klant.nl/robots.txt": (200, "Sitemap: https://www.klant.nl/index.xml\n"),
            "https://www.klant.nl/index.xml": (200, index(*children)),
        }
        responses.update({c: (200, urlset((f"https://www.klant.nl/p{i}/", None))) for i, c in enumerate(children)})
        result = self.run_discovery(responses, max_sitemaps=2)
        self.assertEqual(result.urls, ["https://www.klant.nl/p0/"])
        self.assertEqual(result.failed_sitemaps, children[1:])

    def test_lastmod_only_for_urls_within_max_urls_and_first_occurrence(self):
        result = self.run_discovery({
            "https://www.klant.nl/robots.txt": (200, "Sitemap: https://www.klant.nl/sitemap.xml\n"),
            "https://www.klant.nl/sitemap.xml": (200, urlset(
                ("https://www.klant.nl/a/", "2026-01-01"),
                ("https://www.klant.nl/a", "2026-09-09"),  # zelfde url_key: eerste wint
                ("https://www.klant.nl/b/", "2026-02-02"),
                ("https://www.klant.nl/c/", "2026-03-03"),
            )),
        }, max_urls=2)
        self.assertEqual(result.urls, ["https://www.klant.nl/a/", "https://www.klant.nl/b/"])
        self.assertEqual(result.skipped_due_to_limit, 1)
        self.assertEqual(result.lastmod, {
            url_key("https://www.klant.nl/a/"): "2026-01-01",
            url_key("https://www.klant.nl/b/"): "2026-02-02",
        })

    def test_existing_fields_have_defaults(self):
        result = discovery.DiscoveryResult(urls=[])
        self.assertEqual((result.lastmod, result.failed_sitemaps), ({}, []))


if __name__ == "__main__":
    unittest.main()
