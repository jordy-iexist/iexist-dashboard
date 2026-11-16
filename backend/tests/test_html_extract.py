"""Fase 1-extractie: woorden (totaal en hoofdinhoud), hreflang en Open Graph."""
import unittest

from app.features.launch_checklist.services.html_extract import extract_page

# skip-link 3, header 5 + nav 7, hoofdinhoud 13, zijbalk 5, voet 6 = 39 in totaal.
WITH_CHROME = """<!doctype html>
<html lang="nl"><head><title>Pagina</title>
<script>var veel = "woorden die niet tellen";</script></head>
<body>
<a class="skip-link" href="#main">Ga naar inhoud</a>
<header><div class="logo">Bedrijf Utrecht</div>
  <nav><ul><li><a href="/">Home</a></li><li><a href="/diensten/">Diensten</a></li>
  <li><a href="/over/">Over ons</a></li><li><a href="/blog/">Blog</a></li>
  <li><a href="/contact/">Contact opnemen</a></li></ul></nav>
  <span>Bel ons nu</span>
</header>
<main id="main">
  <h1>Dakgoot reinigen</h1>
  <p>Wij reinigen uw dakgoot snel, veilig en voor een vaste prijs.</p>
</main>
<aside>Lees ook onze andere artikelen</aside>
<footer>Copyright 2026 Bedrijf Utrecht alle rechten</footer>
</body></html>"""

# Header in <article> hoort bij de inhoud; <aside> en role="navigation" in <main> niet.
NESTED = """<html><body>
<main>
  <article>
    <header><h1>Titel van het artikel</h1></header>
    <p>Een twee drie vier vijf.</p>
    <aside>Gerelateerd: zes zeven acht</aside>
    <div role="navigation"><a href="/vorige/">Vorige</a> <a href="/volgende/">Volgende</a></div>
    <footer>Geschreven door Jan</footer>
  </article>
</main>
</body></html>"""

NO_STRUCTURE = """<html><body>
<div class="menu"><a href="/">Home</a> <a href="/diensten/">Diensten</a></div>
<div class="content"><h1>Welkom</h1><p>Dit is de tekst van de pagina.</p></div>
<div class="footer">Copyright 2026</div>
</body></html>"""


class WordCountTest(unittest.TestCase):
    def test_main_content_excludes_chrome(self):
        page = extract_page(WITH_CHROME)
        # Totaal blijft alle tekst in de body (incl. skip-link), zonder script/head.
        self.assertEqual(page.word_count, 3 + 2 + 7 + 3 + 2 + 11 + 5 + 6)
        # Alleen H1 + alinea; skip-link, header, nav, aside en footer tellen niet.
        self.assertEqual(page.main_word_count, 2 + 11)

    def test_nested_chrome_inside_main_content(self):
        page = extract_page(NESTED)
        self.assertEqual(page.word_count, 4 + 5 + 4 + 2 + 3)
        # header en footer binnen <article> tellen mee; aside en role=navigation niet.
        self.assertEqual(page.main_word_count, 4 + 5 + 3)

    def test_no_structure_is_none(self):
        page = extract_page(NO_STRUCTURE)
        self.assertEqual(page.word_count, 2 + 1 + 7 + 2)
        self.assertIsNone(page.main_word_count)

    def test_header_inside_article_only_is_not_structure(self):
        page = extract_page("<html><body><article><header>Kop</header><p>Tekst hier</p></article></body></html>")
        self.assertEqual(page.word_count, 3)
        self.assertIsNone(page.main_word_count)

    def test_skip_link_alone_is_not_structure(self):
        page = extract_page('<html><body><a class="sr-only" href="#c">Naar inhoud</a><p>Een twee drie</p></body></html>')
        self.assertEqual(page.word_count, 5)
        self.assertIsNone(page.main_word_count)

    def test_empty_document(self):
        page = extract_page("")
        self.assertEqual(page.word_count, 0)
        self.assertIsNone(page.main_word_count)


class HeadMetadataTest(unittest.TestCase):
    HTML = """<html lang="nl-NL"><head>
<link rel="alternate" hreflang="nl" href="https://x.nl/">
<link rel="alternate" hreflang="en" href="https://x.nl/en/">
<link rel="alternate" hreflang="x-default" href="https://x.nl/">
<link rel="alternate" type="application/rss+xml" href="https://x.nl/feed/">
<link rel="alternate" hreflang="de">
<meta property="og:title" content="  Eerste   titel ">
<meta property="og:title" content="Tweede titel">
<meta property="og:image" content="https://x.nl/og.jpg">
<meta property="og:description" content="">
<meta name="twitter:card" content="summary">
</head><body><p>Tekst</p></body></html>"""

    def test_hreflang(self):
        page = extract_page(self.HTML)
        self.assertEqual(page.lang, "nl-NL")
        # Alleen alternates mét hreflang én href.
        self.assertEqual(page.hreflang, [
            {"lang": "nl", "href": "https://x.nl/"},
            {"lang": "en", "href": "https://x.nl/en/"},
            {"lang": "x-default", "href": "https://x.nl/"},
        ])

    def test_open_graph(self):
        page = extract_page(self.HTML)
        # Eerste waarde wint, witruimte opgeschoond, lege waarden en niet-og: overgeslagen.
        self.assertEqual(page.open_graph, {"og:title": "Eerste titel", "og:image": "https://x.nl/og.jpg"})

    def test_no_head_metadata(self):
        page = extract_page("<html><body><p>Tekst</p></body></html>")
        self.assertEqual((page.hreflang, page.open_graph, page.lang), ([], {}, None))


if __name__ == "__main__":
    unittest.main()
