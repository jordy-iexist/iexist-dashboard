"""Fase 3 (content & onpage): pure functies — pixelbreedte, extractie, checks, catalogus."""
import unittest
from types import SimpleNamespace

from app.features.launch_checklist.services import content_checklist
from app.features.launch_checklist.services.content_checks import (
    aggregate_items,
    detect_place,
    evaluate_pages,
    generic_filename,
    own_word_counts,
    problem_count,
    recheck_meta,
    site_wide_blocks,
)
from app.features.launch_checklist.services.content_extract import extract_content
from app.features.launch_checklist.services.geo_checklist import ITEMS as GEO_ITEMS
from app.features.launch_checklist.services.issues import ISSUE_TYPES, generate_content_issues
from app.features.launch_checklist.services.pixel_width import (
    description_width,
    fits_description,
    fits_title,
    title_width,
)

HTML = """<html lang="nl"><head><title>Dakgoot reinigen in Utrecht | Voorbeeld BV</title>
<meta name="description" content="Dakgoot laten reinigen in Utrecht? Vraag een offerte aan.">
<script type="application/ld+json">{"@type":"FAQPage"}</script></head>
<body><header><nav><a href="/">Home</a><a href="/contact/">Contact</a></nav></header>
<main><article><header><h1>Dakgoot reinigen in Utrecht</h1></header>
<p>Wij reinigen uw dakgoot in Utrecht binnen een week, inclusief controle van de afvoer en een foto-rapport achteraf.</p>
<h2>Werkwijze</h2><ul><li>Inspectie</li><li>Reinigen</li></ul>
<h4>Detail</h4>
<p>Lees ook <a href="/diensten/dakinspectie/">dakinspectie</a> of <a href="/blog/x/">klik hier</a>.</p>
<img src="/img/IMG_1234.jpg"><img src="/img/dakgoot-reinigen-utrecht.jpg" alt="Schone dakgoot">
<a class="btn" href="/offerte/">Offerte aanvragen</a>
<table><tr><td>Prijs</td></tr></table></article></main>
<footer><p>Footertekst die niet meetelt</p><img src="/logo.png" alt="logo"></footer></body></html>"""


def page(**kw):
    base = dict(
        id="p1", url="https://voorbeeld.nl/diensten/dakgoot-reinigen-utrecht/", path="/x", page_type="dienst",
        title="Dakgoot reinigen in Utrecht | Voorbeeld BV", meta_description="Kort.",
        headings=[{"level": 1, "text": "Dakgoot reinigen in Utrecht"}], body_text="", first_paragraph=None,
        word_count=50, images=[], links=[], signals={"h1": ["Dakgoot reinigen in Utrecht"]},
        checks=None, analysis_status="none", source_page_id="s1",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class PixelWidthTest(unittest.TestCase):
    def test_wide_letters_take_more_pixels(self):
        self.assertGreater(title_width("WWWWWWWWWW"), title_width("iiiiiiiiii"))

    def test_limits(self):
        self.assertTrue(fits_title("Dakgoot reinigen in Utrecht | Voorbeeld BV"))
        self.assertFalse(fits_title("x" * 61))
        self.assertFalse(fits_title("W" * 40))  # 40 tekens maar te breed
        self.assertTrue(fits_description("a" * 120))
        self.assertFalse(fits_description("a" * 161))
        self.assertGreater(description_width("a" * 160), 0)


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.data = extract_content(HTML, "https://voorbeeld.nl/diensten/dakgoot-reinigen-utrecht/", "voorbeeld.nl")

    def test_main_content_only(self):
        self.assertIn("# Dakgoot reinigen in Utrecht", self.data.body_text)
        self.assertIn("- Inspectie", self.data.body_text)
        self.assertNotIn("Footertekst", self.data.body_text)
        self.assertNotIn("Home", self.data.body_text)

    def test_headings_and_first_paragraph(self):
        self.assertEqual([h["level"] for h in self.data.headings], [1, 2, 4])
        self.assertTrue(self.data.first_paragraph.startswith("Wij reinigen uw dakgoot"))

    def test_images_and_links(self):
        content = [i for i in self.data.images if i["in_content"]]
        self.assertEqual(len(content), 2)
        self.assertIsNone(content[0]["alt"])
        self.assertEqual(content[0]["filename"], "IMG_1234.jpg")
        self.assertFalse([i for i in self.data.images if i["filename"] == "logo.png"][0]["in_content"])
        in_content = {l["text"] for l in self.data.links if l["in_content"]}
        self.assertIn("klik hier", in_content)
        self.assertNotIn("Home", in_content)

    def test_signals(self):
        s = self.data.signals
        self.assertEqual((s["lists"], s["tables"]), (1, 1))
        self.assertTrue(s["has_faq_schema"])
        self.assertIn("Offerte aanvragen", s["cta_texts"])


class ChecksTest(unittest.TestCase):
    def test_filenames(self):
        self.assertTrue(generic_filename("IMG_1234.jpg"))
        self.assertTrue(generic_filename("screenshot-2026.png"))
        self.assertFalse(generic_filename("dakgoot-reinigen-utrecht.jpg"))

    def test_place_needs_url_match(self):
        self.assertEqual(detect_place(page()), "Utrecht")
        self.assertIsNone(detect_place(page(url="https://voorbeeld.nl/diensten/dakgoot/")))
        known = page(url="https://voorbeeld.nl/seo-bureau-den-haag/", title="SEO bureau Den Haag",
                     signals={"h1": ["SEO bureau Den Haag"]})
        self.assertEqual(detect_place(known), "Den Haag")
        self.assertIsNone(detect_place(page(url="https://voorbeeld.nl/diensten/seo/", title="SEO", signals={"h1": ["SEO"]})))

    def test_page_checks(self):
        data = extract_content(HTML, "https://voorbeeld.nl/diensten/dakgoot-reinigen-utrecht/", "voorbeeld.nl")
        p = page(headings=data.headings, body_text=data.body_text, first_paragraph=data.first_paragraph,
                 word_count=data.word_count, images=data.images, links=data.links, signals=data.signals)
        link_status = {"voorbeeld.nl/blog/x": {"status": 404, "broken": True, "redirect": False}}
        checks = evaluate_pages([p], link_status)["p1"]
        self.assertEqual(checks["c3_meta_title"]["status"], "ok")
        self.assertEqual(checks["c3_meta_description"]["status"], "warning")  # te kort
        self.assertEqual(checks["c3_headings"]["status"], "warning")  # h2 → h4
        self.assertEqual(checks["c3_images"]["status"], "error")  # alt ontbreekt
        self.assertEqual(checks["c3_internal_links"]["status"], "warning")  # klik hier
        self.assertEqual(checks["c3_redirects_404"]["status"], "error")
        self.assertNotEqual(checks["c3_local"]["status"], "nvt")
        self.assertGreaterEqual(problem_count(checks), 5)

    def test_nvt_on_legal_pages(self):
        checks = evaluate_pages([page(page_type="juridisch", url="https://voorbeeld.nl/privacy/")])["p1"]
        self.assertEqual(checks["c3_faq"]["status"], "nvt")
        self.assertEqual(checks["c3_local"]["status"], "nvt")

    def test_recheck_meta(self):
        p = page(title="Goede titel van voldoende lengte voor de test", meta_description="")
        result = recheck_meta([("title_missing", p.url), ("meta_missing", p.url), ("h1_missing", p.url)], [p])
        self.assertEqual(result["status"], "warning")
        self.assertEqual(result["details"], {"total": 2, "remaining": 1})

    def test_aggregate_and_issues(self):
        p = page()
        checks = evaluate_pages([p], {})
        meta = recheck_meta([], [p])
        items = aggregate_items([p], checks, open_suggestions={}, meta_fixed=meta, gap_analyzed=False)
        self.assertEqual(set(items), set(content_checklist.ITEMS) - {"c3_unique_expert"})
        self.assertEqual(items["c3_meta_description"]["status"], "warning")
        self.assertEqual(items["c3_blogs"]["status"], "warning")  # geen blogs
        # Zonder regelprobleem blijft een hybride punt 'unknown' tot er een pagina is geanalyseerd.
        ok = page(id="p2", url="https://voorbeeld.nl/a/", signals={"h1": ["A"], "cta_texts": ["Offerte"]})
        c2 = evaluate_pages([ok], {})
        self.assertEqual(aggregate_items([ok], c2, open_suggestions={}, meta_fixed=meta, gap_analyzed=False)
                         ["c3_conversion"]["status"], "unknown")
        ok.analysis_status = "done"
        self.assertEqual(aggregate_items([ok], c2, open_suggestions={}, meta_fixed=meta, gap_analyzed=True)
                         ["c3_conversion"]["status"], "ok")
        self.assertEqual(aggregate_items([ok], c2, open_suggestions={("p2", "c3_conversion"): 2},
                                         meta_fixed=meta, gap_analyzed=True)["c3_conversion"]["status"], "warning")

        issues = generate_content_issues([p], checks, items, {"c3_meta_description": "afgerond"})
        types = {i["issue_type"] for i in issues}
        self.assertNotIn("c3_meta_description", types)
        self.assertIn("c3_blogs", types)
        self.assertTrue(all(i["issue_type"] in ISSUE_TYPES for i in issues))


REVIEW_LINES = [
    "## Wat klanten zeggen",
    "Super geholpen, snelle levering en een echt prachtig resultaat voor ons bedrijf.",  # 12 woorden
    "- Projecten",
]
REVIEW_WORDS = 3 + 12 + 1  # markdown-voorvoegsels tellen niet mee


def site_page(i, page_type, own_text, extra=(), **kw):
    """Pagina met `own_text` (één regel) + de site-brede reviewregels."""
    body = "\n".join([f"# Pagina {i}", own_text, *extra, *REVIEW_LINES, "…(ingekort)", ""])
    own_words = 2 + len(own_text.split()) + sum(len(e.split()) for e in extra)
    return page(id=f"p{i}", url=f"https://voorbeeld.nl/pagina-{i}/", page_type=page_type, body_text=body,
                word_count=own_words + REVIEW_WORDS + kw.pop("extra_words", 0),
                headings=[{"level": 1, "text": f"Pagina {i}"}], **kw)


class SiteWideBlocksTest(unittest.TestCase):
    TYPES = ["dienst", "dienst", "landing", "blog", None, "over_ons"]

    def pages(self, **kw):
        return [site_page(i, t, f"Eigen tekst nummer {i}.", **kw) for i, t in enumerate(self.TYPES)]

    def test_review_lines_are_site_wide(self):
        pages = self.pages()
        self.assertEqual(site_wide_blocks(pages), set(REVIEW_LINES))
        counts = own_word_counts(pages)
        self.assertEqual(counts["p0"], (2 + 4, REVIEW_WORDS))
        # Lege regels en de afkapregel zijn nooit een blok.
        self.assertNotIn("…(ingekort)", site_wide_blocks(pages))
        self.assertNotIn("", site_wide_blocks(pages))

    def test_line_twice_on_one_page_counts_twice(self):
        pages = self.pages()
        pages[0] = site_page(0, "dienst", "Eigen tekst nummer 0.", extra=[REVIEW_LINES[1]], extra_words=0)
        own, site_wide = own_word_counts(pages)["p0"]
        self.assertEqual(site_wide, REVIEW_WORDS + 12)
        self.assertEqual(own, 2 + 4)

    def test_own_never_below_zero(self):
        pages = self.pages()
        pages[0].word_count = 3
        self.assertEqual(own_word_counts(pages)["p0"], (0, REVIEW_WORDS))

    def test_shared_within_one_type_stays_own_text(self):
        shared = "Wij zijn al twintig jaar specialist in dakgoten in de hele regio."
        pages = [site_page(i, "landing", f"Eigen {i}.", extra=[shared]) for i in range(6)]
        pages.append(site_page(6, "blog", "Blogtekst."))
        pages.append(site_page(7, "dienst", "Diensttekst."))
        blocks = site_wide_blocks(pages)
        self.assertNotIn(shared, blocks)
        self.assertEqual(blocks, set(REVIEW_LINES))  # 8 pagina's, 3 types
        own, site_wide = own_word_counts(pages)["p0"]
        self.assertEqual((own, site_wide), (2 + 2 + 12, REVIEW_WORDS))

    def test_fewer_than_five_pages_unchanged(self):
        pages = self.pages()[:4]
        self.assertEqual(site_wide_blocks(pages), set())
        self.assertEqual(own_word_counts(pages)["p0"], (pages[0].word_count, 0))
        big = [site_page(i, t, "woord " * 500) for i, t in enumerate(["dienst", "landing", "blog", "overig"])]
        checks = evaluate_pages(big)["p0"]
        words = big[0].word_count
        self.assertEqual(checks["c3_scannable"], {
            "status": "warning", "message": f"{words} woorden zonder lijsten of tabellen.", "details": None})
        self.assertEqual(checks["c3_keywords"]["details"], None)

    def test_checks_use_own_words(self):
        # 450 eigen woorden + 400 site-brede woorden, zonder lijsten.
        review = " ".join(["review"] * 400)
        pages = [site_page(i, t, "woord " * 448 if i == 0 else f"Eigen {i}.", extra=[review])
                 for i, t in enumerate(self.TYPES)]
        p0 = pages[0]
        own_words, site_wide = own_word_counts(pages)["p0"]
        self.assertEqual(site_wide, 400 + REVIEW_WORDS)
        self.assertEqual(own_words, p0.word_count - site_wide)
        checks = evaluate_pages(pages)["p0"]
        scannable = checks["c3_scannable"]
        self.assertEqual(scannable["status"], "warning")
        self.assertIn(f"{own_words} woorden eigen tekst zonder lijsten of tabellen", scannable["message"])
        self.assertIn(f"{site_wide} woorden in blokken", scannable["message"])
        self.assertEqual(scannable["details"], {"own_words": own_words, "site_wide_words": site_wide})

        # Pagina 1: weinig eigen tekst, maar door de reviews boven de drempels.
        p1_checks = evaluate_pages(pages)["p1"]
        own1, site1 = own_word_counts(pages)["p1"]
        self.assertGreaterEqual(pages[1].word_count, 400)
        self.assertEqual(p1_checks["c3_scannable"]["status"], "ok")
        self.assertIn(f"{own1} woorden eigen tekst", p1_checks["c3_scannable"]["message"])
        self.assertEqual(p1_checks["c3_keywords"]["status"], "warning")
        self.assertIn(f"Weinig eigen tekst ({own1} woorden; {site1} woorden in blokken",
                      p1_checks["c3_keywords"]["message"])
        self.assertEqual(p1_checks["c3_keywords"]["details"], {"own_words": own1, "site_wide_words": site1})
        # Geen H2 en >300 woorden totaal, maar weinig eigen tekst: geen H2-melding.
        self.assertNotIn("H2", p1_checks["c3_headings"]["message"])
        self.assertIn("H2", checks["c3_headings"]["message"])


class CatalogTest(unittest.TestCase):
    def test_keys_unique_across_phases(self):
        self.assertFalse(set(content_checklist.ITEMS) & set(GEO_ITEMS))
        self.assertEqual(len(content_checklist.ITEMS), 18)
        self.assertTrue(all(k.startswith("c3_") for k in content_checklist.ITEMS))

    def test_merge(self):
        state = SimpleNamespace(manual_status="afgerond", note=None, updated_at=None, external_url=None, pushed_at=None)
        merged = content_checklist.merge_content_checklist(
            {"c3_meta_title": {"status": "ok", "message": ""}}, {"c3_unique_expert": state})
        self.assertEqual([s["key"] for s in merged["sections"]], ["technisch", "bestaand", "nieuw"])
        self.assertEqual((merged["done"], merged["total"]), (2, 18))


if __name__ == "__main__":
    unittest.main()
