"""Aanpassingen per pagina (features/site_changes).

Unit-tests (sleutels, onderwerpen, statussen, live-controle met voorbeeld-HTML) draaien zonder
database. De API-tests draaien tegen de lokale dev-Postgres binnen één transactie die na elke
test wordt teruggedraaid (de endpoints committen naar een SAVEPOINT), zodat er geen dev-data
verandert of achterblijft. De live pagina wordt nooit echt opgehaald: `schema_markup.fetch_page`
is in elke API-test vervangen.
"""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.db.models import SiteChange
from app.features.launch_checklist.services.discovery import url_key
from app.features.launch_checklist.services.schema_markup import FetchedPage, SchemaMarkupError
from app.features.site_changes.mappers import counts, open_high_count
from app.features.site_changes.services import verify
from app.features.site_changes.services.changes import (
    KIND_ISSUE,
    KIND_SUGGESTION,
    issue_source_key,
    merge_entries,
    suggestion_key,
    topic_for,
)
from app.features.site_changes.services.sources import SourceItem

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
FETCH = "app.features.launch_checklist.services.schema_markup.fetch_page"
PAGE = "https://klant.nl/diensten/seo/"


# --- sleutels en onderwerpen -------------------------------------------------------

class SourceKeyTest(unittest.TestCase):
    def test_suggestion_key_is_stable_over_whitespace_and_case(self):
        a = suggestion_key("meta_title", "klant.nl/seo", "c3_meta_title", "SEO  bureau | Klant", None)
        b = suggestion_key("meta_title", "klant.nl/seo", "c3_meta_title", "seo bureau |\nklant ", "")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)

    def test_suggestion_key_differs_per_ref_item_and_page(self):
        base = suggestion_key("image_alt", "klant.nl/seo", "c3_images", "", "https://klant.nl/a.png")
        self.assertNotEqual(base, suggestion_key("image_alt", "klant.nl/seo", "c3_images", "", "https://klant.nl/b.png"))
        self.assertNotEqual(base, suggestion_key("image_alt", "klant.nl/over", "c3_images", "", "https://klant.nl/a.png"))
        self.assertNotEqual(
            suggestion_key("text", "k/x", "c3_scannable", "", None, "Lijst A"),
            suggestion_key("text", "k/x", "c3_scannable", "", None, "Lijst B"),
        )

    def test_issue_key_uses_type_and_url_key(self):
        self.assertEqual(
            issue_source_key("title_too_long", url_key("https://Klant.nl/seo/")),
            issue_source_key("title_too_long", url_key("https://klant.nl/seo")),
        )
        self.assertNotEqual(issue_source_key("title_too_long", "klant.nl/seo"),
                            issue_source_key("title_missing", "klant.nl/seo"))
        self.assertNotEqual(issue_source_key("c3_meta_title", "klant.nl/seo"),
                            suggestion_key("meta_title", "klant.nl/seo", "c3_meta_title", None, None))


class TopicTest(unittest.TestCase):
    def test_mapping(self):
        cases = {
            "c3_meta_title": "meta_title", "title_too_long": "meta_title", "title_duplicate": "meta_title",
            "c3_meta_description": "meta_description", "meta_missing": "meta_description",
            "c3_headings": "headings", "h1_multiple": "headings",
            "c3_keywords": "text", "c3_eeat": "text", "c3_local": "text", "thin_content": "text",
            "c3_faq": "faq",
            "c3_images": "image_alt", "images_missing_alt": "image_alt",
            "c3_internal_links": "internal_links", "broken_links": "internal_links",
            "status_4xx": "technical", "redirect_chain": "technical", "hreflang_no_return": "technical",
            "canonical_mismatch": "technical", "c4_search_console": "technical", "c3_redirects_404": "technical",
            "c3_meta_fixed": "technical", "og_incomplete": "technical",
            "slow_response": "performance", "cwv_lcp": "performance", "cwv_page_weight": "performance",
            "ai_llms_txt": "other", "geo_faq_schema": "other", "iets_onbekends": "other",
        }
        for key, topic in cases.items():
            with self.subTest(key=key):
                self.assertEqual(topic_for(key), topic)


# --- statussen samenvoegen ---------------------------------------------------------

def _source(kind, status, *, key=None, sid=None, type_key="c3_meta_title", severity=None):
    return SourceItem(
        key=key or uuid.uuid4().hex, source_kind=kind, type_key=type_key, topic=topic_for(type_key),
        page_url=PAGE, url_key=url_key(PAGE), title="t", description=None, current_value="oud",
        proposed_value="nieuw" if kind == KIND_SUGGESTION else None, rationale=None, ref=None,
        severity=severity, item_label=None, status=status,
        source_ref={"suggestion_id": sid or uuid.uuid4().hex} if kind == KIND_SUGGESTION else {"issue_id": "i"},
    )


def _row(key, status, kind=KIND_SUGGESTION, source_ref=None, severity=None):
    return SiteChange(
        id=str(uuid.uuid4()), customer_website_id="c", page_url=PAGE, url_key=url_key(PAGE), topic="meta_title",
        source_kind=kind, source_key=key, source_ref=source_ref or {}, title="t", status=status, severity=severity,
    )


class MergeEntriesTest(unittest.TestCase):
    def test_status_from_source_without_row(self):
        items = [
            _source(KIND_SUGGESTION, "open"), _source(KIND_SUGGESTION, "afgewezen"),
            _source(KIND_SUGGESTION, "overgenomen"),
            _source(KIND_ISSUE, "open"), _source(KIND_ISSUE, "doorgezet"), _source(KIND_ISSUE, "genegeerd"),
            _source(KIND_ISSUE, "opgelost"),
        ]
        entries = merge_entries({i.key: i for i in items}, [])
        self.assertEqual([e.status for e in entries],
                         ["open", "afgewezen", "doorgevoerd", "open", "open", "afgewezen"])

    def test_row_wins_and_survives_without_source(self):
        issue = _source(KIND_ISSUE, "opgelost")
        gone_row = _row("weg", "goedgekeurd")
        entries = merge_entries({issue.key: issue}, [_row(issue.key, "doorgevoerd", KIND_ISSUE), gone_row])
        by_key = {e.key: e for e in entries}
        self.assertEqual(by_key[issue.key].status, "doorgevoerd")
        self.assertIs(by_key[issue.key].source, issue)
        self.assertEqual(by_key["weg"].status, "goedgekeurd")
        self.assertIsNone(by_key["weg"].source)

    def test_row_found_by_suggestion_id_when_key_changed(self):
        source = _source(KIND_SUGGESTION, "open", sid="s-1")
        row = _row("oude-sleutel", "goedgekeurd", source_ref={"suggestion_id": "s-1"})
        entries = merge_entries({source.key: source}, [row])
        self.assertEqual(len(entries), 1)
        self.assertIs(entries[0].source, source)
        self.assertEqual(entries[0].status, "goedgekeurd")


# --- live-controle -------------------------------------------------------------------

LIVE_HTML = """<!doctype html><html lang="nl"><head>
<title>SEO-bureau in Harderwijk | Klant</title>
<meta name="description" content="Wij helpen je hoger in Google &amp; AI-zoekmachines. Vraag vandaag een gratis SEO-scan aan.">
<meta property="og:title" content="SEO"><meta property="og:description" content="SEO"><meta property="og:image" content="https://klant.nl/og.png">
</head><body><header><nav><a href="/">Home</a><a href="/contact/">Contact</a></nav></header>
<main>
<h1>SEO-bureau in Harderwijk</h1>
<p>Wij maken je website beter vindbaar in Google en in AI-zoekmachines zoals ChatGPT en Perplexity.</p>
<h2>Veelgestelde vragen</h2>
<details><summary>Wat kost SEO?</summary><p>Dat hangt af van de omvang van je website en je doelen.</p></details>
<p>Lees meer over onze <a href="/sea/">SEA-diensten</a> of bekijk de <a href="https://klant.nl/oud-404/">oude pagina</a>.</p>
<img src="https://klant.nl/wp-content/uploads/2026/09/team-300x200.jpg" alt="Het team aan het werk" width="300" height="200">
<img src="https://klant.nl/wp-content/uploads/2026/09/kantoor.jpg">
</main><footer>Footer</footer></body></html>"""


def _live(html=LIVE_HTML, url=PAGE, redirects=None, final_url=None, headers=None):
    fetched = FetchedPage(
        html=html, final_url=final_url or verify.with_cache_buster(url), redirects=redirects or [],
        headers=headers or {"content-type": "text/html; charset=utf-8"},
    )
    return verify.parse_live(url, fetched)


class NormalizeTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(verify.normalize("**Wat&nbsp;kost  het?**"), "wat kost het?")
        self.assertEqual(verify.normalize("## Kop – ‘test’"), "kop - 'test'")
        self.assertEqual(verify.normalize("Lees [SEO](https://x.nl/seo/) nu"), "lees seo nu")
        self.assertEqual(verify.normalize("ﬁets"), "fiets")  # NFKC


class VerifyRulesTest(unittest.TestCase):
    def setUp(self):
        self.live = _live()

    def test_meta_title(self):
        self.assertTrue(verify.check_suggestion("meta_title", "SEO-bureau in Harderwijk", None, self.live).found)
        miss = verify.check_suggestion("meta_title", "Online marketing Harderwijk", None, self.live)
        self.assertFalse(miss.found)
        self.assertEqual(miss.live_value, "SEO-bureau in Harderwijk | Klant")
        self.assertIn("Nog niet live", miss.message)

    def test_meta_description(self):
        value = "Wij helpen je hoger in Google & AI-zoekmachines. Vraag vandaag een gratis SEO-scan aan."
        self.assertTrue(verify.check_suggestion("meta_description", value, None, self.live).found)
        miss = verify.check_suggestion("meta_description", "Andere tekst.", None, self.live)
        self.assertFalse(miss.found)
        self.assertTrue(miss.live_value.startswith("Wij helpen je"))

    def test_text_headings_and_faq(self):
        faq = ("## Veelgestelde vragen\n**Wat kost SEO?**\nDat hangt af van de omvang van je website en je doelen.\n"
               "- ok\n")
        self.assertTrue(verify.check_suggestion("faq", faq, None, self.live).found)
        heading = "## SEO-bureau in Harderwijk\nWij maken je website [plaats]beter vindbaar in Google"
        # Plaatshouder: alleen de stukken eromheen moeten er staan.
        self.assertTrue(verify.check_suggestion("headings", heading, None, self.live).found)
        miss = verify.check_suggestion(
            "text", "Wij maken je website beter vindbaar in Google\nDeze zin staat er nog niet.", None, self.live)
        self.assertFalse(miss.found)
        self.assertEqual(miss.missing, ["Deze zin staat er nog niet."])

    def test_image_alt(self):
        ref = "https://klant.nl/wp-content/uploads/2026/09/team.jpg"
        # Bron met WordPress-maat (-300x200) telt als dezelfde afbeelding.
        self.assertTrue(verify.check_suggestion(
            "image_alt", "alt: Het team aan het werk\nbestandsnaam: team-aan-het-werk.jpg", ref, self.live).found)
        miss = verify.check_suggestion("image_alt", "alt: Ons kantoor in Harderwijk",
                                       "https://klant.nl/wp-content/uploads/2026/09/kantoor.jpg", self.live)
        self.assertFalse(miss.found)
        self.assertIn("geen alt-tekst", miss.message)
        gone = verify.check_suggestion("image_alt", "alt: x", "https://klant.nl/elders.png", self.live)
        self.assertFalse(gone.found)
        self.assertEqual(verify.parse_alt('alt: ""\nbestandsnaam: '), ("", None))

    def test_internal_link(self):
        self.assertTrue(verify.check_suggestion("internal_links", "x", "https://klant.nl/sea", self.live).found)
        self.assertFalse(verify.check_suggestion("internal_links", "x", "https://klant.nl/seo-audit/", self.live).found)

    def test_checkable(self):
        self.assertTrue(verify.suggestion_checkable("meta_title", None, "t", PAGE))
        self.assertFalse(verify.suggestion_checkable("image_alt", None, "alt: x", PAGE))
        self.assertTrue(verify.suggestion_checkable(
            "internal_links", "https://klant.nl/sea/", "Zie [SEA](/sea/)", PAGE))
        # "Link hierheen vanaf ...": geen link naar ref in het voorstel zelf.
        self.assertFalse(verify.suggestion_checkable(
            "internal_links", "https://klant.nl/blog/", "Link vanaf de blogpagina hierheen.", PAGE))
        self.assertFalse(verify.suggestion_checkable("technical", None, "x", PAGE))
        self.assertTrue(verify.issue_checkable("title_too_long"))
        self.assertFalse(verify.issue_checkable("title_duplicate"))
        self.assertFalse(verify.issue_checkable("cwv_lcp"))
        self.assertFalse(verify.issue_checkable("slow_response"))


class VerifyIssuesTest(unittest.TestCase):
    def test_page_rules_on_live_page(self):
        live = _live()
        types = verify.live_issue_types(live, [])
        # Titel/meta/H1 in orde; korte tekst en een afbeelding zonder alt.
        self.assertNotIn("h1_missing", types)
        self.assertNotIn("title_missing", types)
        self.assertNotIn("meta_missing", types)
        self.assertNotIn("lang_missing", types)
        self.assertIn("thin_content", types)
        self.assertIn("images_missing_alt", types)
        self.assertNotIn("broken_links", types)
        # Een eerder gemelde kapotte link waar de pagina nog naar linkt, blijft kapot.
        self.assertIn("broken_links", verify.live_issue_types(live, [{"url": "https://klant.nl/oud-404/", "status": 404}]))
        self.assertNotIn("broken_links", verify.live_issue_types(live, [{"url": "https://klant.nl/weg/", "status": 404}]))

    def test_noindex_and_canonical(self):
        html = LIVE_HTML.replace("<head>", '<head><meta name="robots" content="noindex">', 1)
        self.assertIn("noindex_in_sitemap", verify.live_issue_types(_live(html), []))
        self.assertIn("noindex_in_sitemap", verify.live_issue_types(_live(headers={"x-robots-tag": "noindex"}), []))
        html = LIVE_HTML.replace("<head>", '<head><link rel="canonical" href="https://klant.nl/anders/">', 1)
        self.assertIn("canonical_mismatch", verify.live_issue_types(_live(html), []))

    def test_redirect_limits_what_is_determinable(self):
        live = _live(
            url="https://klant.nl/oud/", final_url="https://klant.nl/nieuw/",
            redirects=[{"url": verify.with_cache_buster("https://klant.nl/oud/"), "status": 301,
                        "location": "https://klant.nl/nieuw/"}],
        )
        self.assertTrue(live.redirected)
        self.assertEqual(live.record.redirect_chain[0]["url"], "https://klant.nl/oud/")
        types = verify.live_issue_types(live, [])
        self.assertIn("redirect_in_sitemap", types)
        self.assertNotIn("redirect_chain", types)
        self.assertNotIn("title_too_long", verify.determinable_types(live))
        self.assertIn("status_4xx", verify.determinable_types(live))


class OpenHighCountTest(unittest.TestCase):
    def test_counts_only_open_items_with_high_severity(self):
        items = [
            _source(KIND_ISSUE, "open", severity="hoog"),
            _source(KIND_ISSUE, "doorgezet", severity="hoog"),  # telt als open
            _source(KIND_ISSUE, "open", severity="middel"),
            _source(KIND_ISSUE, "open"),
            _source(KIND_ISSUE, "genegeerd", severity="hoog"),  # afgewezen
            _source(KIND_ISSUE, "opgelost", severity="hoog"),  # valt af zonder rij
        ]
        approved = _source(KIND_ISSUE, "open", severity="hoog")
        done = _source(KIND_ISSUE, "open", severity="hoog")
        reopened = _source(KIND_ISSUE, "open", severity="laag")
        sources = {i.key: i for i in [*items, approved, done, reopened]}
        rows = [
            _row(approved.key, "goedgekeurd", KIND_ISSUE),
            _row(done.key, "doorgevoerd", KIND_ISSUE),
            # De rij (momentopname) wint van de bron.
            _row(reopened.key, "open", KIND_ISSUE, severity="hoog"),
            # Rij zonder bron telt ook mee.
            _row("weg", "open", KIND_ISSUE, severity="hoog"),
        ]
        entries = merge_entries(sources, rows)
        open_count, _, _ = counts(entries)
        self.assertEqual(open_high_count(entries), 4)
        self.assertEqual(open_count, 6)
        self.assertLessEqual(open_high_count(entries), open_count)
        self.assertEqual(open_high_count([]), 0)


# --- API tegen de dev-database (alles in een terug te draaien transactie) ----------

def _dev_db_available() -> bool:
    try:
        from sqlalchemy import text

        from app.db.session import engine
        with engine.connect() as conn:
            conn.execute(text("select 1 from site_changes limit 1"))
        return True
    except Exception:
        return False


@unittest.skipUnless(_dev_db_available(), "dev-database (met migratie 0038) niet bereikbaar")
class SiteChangesApiTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from sqlalchemy.orm import Session

        from app.core.dependencies import require_user_id
        from app.db.models import LaunchContentPage, LaunchScan, User
        from app.db.session import engine, get_db
        from app.main import app

        self.conn = engine.connect()
        self.outer = self.conn.begin()
        self.db = Session(bind=self.conn, join_transaction_mode="create_savepoint")
        scan = (
            self.db.query(LaunchScan)
            .filter(LaunchScan.phase == 3, LaunchScan.status == "completed")
            .order_by(LaunchScan.created_at.desc())
            .first()
        )
        if scan is None:
            self.skipTest("Geen voltooide fase 3-scan in de dev-database.")
        # De nieuwste fase 3-scan van díe klant (die gebruikt de feature).
        self.scan = (
            self.db.query(LaunchScan)
            .filter(LaunchScan.customer_website_id == scan.customer_website_id, LaunchScan.phase == 3,
                    LaunchScan.status == "completed")
            .order_by(LaunchScan.created_at.desc())
            .first()
        )
        self.customer_id = self.scan.customer_website_id
        self.page = (
            self.db.query(LaunchContentPage)
            .filter(LaunchContentPage.scan_id == self.scan.id)
            .order_by(LaunchContentPage.path)
            .first()
        )
        if self.page is None:
            self.skipTest("Fase 3-scan zonder pagina's.")
        user = self.db.query(User).first()
        self.user_id = user.id if user else "test-user"
        self.user_name = user.email.split("@")[0] if user else None
        self.app = app
        app.dependency_overrides[require_user_id] = lambda: self.user_id
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.base = f"/api/site-changes/customers/{self.customer_id}"

    def tearDown(self):
        from app.core.dependencies import require_user_id
        from app.db.session import get_db

        self.app.dependency_overrides.pop(require_user_id, None)
        self.app.dependency_overrides.pop(get_db, None)
        self.db.close()
        self.outer.rollback()
        self.conn.close()

    # --- hulpjes ---

    def _suggestion(self, item_key, proposed, current=None, ref=None):
        from app.db.models import LaunchContentSuggestion

        row = LaunchContentSuggestion(
            id=str(uuid.uuid4()), scan_id=self.scan.id, customer_website_id=self.customer_id,
            content_page_id=self.page.id, item_key=item_key, agent="test", title=f"Test {item_key}",
            current_value=current, proposed_value=proposed, rationale="Omdat het beter is.",
            details={"ref": ref} if ref else None, status="open", created_at=NOW, updated_at=NOW,
        )
        self.db.add(row)
        self.db.commit()  # SAVEPOINT; de buitenste transactie wordt in tearDown teruggedraaid
        return row

    def _issue_scan(self):
        from app.features.site_changes.services.sources import issue_scans

        return issue_scans(self.db, self.customer_id)[0]

    def _issue(self, issue_type, *, scan=None, created_at=None, status="open"):
        from app.db.models import LaunchScanIssue

        scan = scan or self._issue_scan()
        row = LaunchScanIssue(
            id=str(uuid.uuid4()), scan_id=scan.id, issue_type=issue_type, category="on-page", severity="hoog",
            title=f"Test {issue_type}", description="Testpunt.", recommendation="Los het op.", url=self.page.url,
            status=status, created_at=created_at or datetime.now(timezone.utc) + timedelta(seconds=5),
            updated_at=NOW,
        )
        self.db.add(row)
        self.db.commit()  # SAVEPOINT; de buitenste transactie wordt in tearDown teruggedraaid
        return row

    def _free_issue_type(self, candidates):
        from app.features.site_changes.services.sources import collect_sources

        taken = {i.type_key for i in collect_sources(self.db, self.customer_id, url_key(self.page.url)).items.values()}
        for candidate in candidates:
            if candidate not in taken:
                return candidate
        self.skipTest("Geen vrij issue-type voor deze pagina.")

    def _page(self):
        r = self.client.get(f"{self.base}/page", params={"url": self.page.url})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _item(self, page, key):
        for group in page["groups"]:
            for item in group["items"]:
                if item["key"] == key:
                    return item
        for item in page["rejected"] + page["done"]:
            if item["key"] == key:
                return item
        return None

    def _key_for(self, page, source_field, source_id):
        for item in [i for g in page["groups"] for i in g["items"]] + page["rejected"] + page["done"]:
            if item["source_ref"].get(source_field) == source_id:
                return item
        self.fail(f"{source_id} niet op de pagina")

    def _put(self, item, action, **extra):
        body = {"key": item["key"], "source_kind": item["source_kind"], "source_ref": item["source_ref"],
                "action": action, **extra}
        return self.client.put(f"{self.base}/changes", json=body)

    # --- tests ---

    def test_pages_and_page(self):
        suggestion = self._suggestion("c3_meta_title", "Nieuwe titel | Test", current=self.page.title)
        r = self.client.get(f"{self.base}/pages")
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertTrue(data["has_sources"])
        paths = {p["url"]: p for p in data["pages"]}
        self.assertIn(self.page.url, paths)
        self.assertGreaterEqual(paths[self.page.url]["open_count"], 1)
        weights = [p["open_count"] + p["approved_count"] for p in data["pages"]]
        self.assertEqual(weights, sorted(weights, reverse=True))
        self.assertEqual(data["totals"]["open"], sum(p["open_count"] for p in data["pages"]))
        self.assertLessEqual(data["totals"]["open_high"], data["totals"]["open"])

        page = self._page()
        item = self._key_for(page, "suggestion_id", suggestion.id)
        self.assertEqual(item["topic"], "meta_title")
        self.assertEqual(item["status"], "open")
        self.assertTrue(item["checkable"])
        self.assertEqual(item["proposed_value"], "Nieuwe titel | Test")
        topics = [g["topic"] for g in page["groups"]]
        order = ["meta_title", "meta_description", "headings", "text", "faq", "image_alt", "internal_links",
                 "technical", "performance", "other"]
        self.assertEqual(topics, sorted(topics, key=order.index))
        self.assertIn("schema", page)
        self.assertEqual(self.client.get(f"{self.base}/page", params={"url": "https://geen-punten.example/"})
                         .status_code, 404)
        self.assertEqual(self.client.get("/api/site-changes/customers/bestaat-niet/pages").status_code, 404)

    def test_suggestion_flow_approve_edit_reject_reopen_done(self):
        from app.db.models import LaunchScan

        suggestion = self._suggestion("c3_meta_description", "Nieuwe beschrijving voor de test.", current="Oud.")
        item = self._key_for(self._page(), "suggestion_id", suggestion.id)
        checklist_before = self.db.get(LaunchScan, self.scan.id).updated_at

        r = self._put(item, "approve")
        self.assertEqual(r.status_code, 200, r.text)
        approved = r.json()
        self.assertEqual(approved["status"], "goedgekeurd")
        self.assertEqual(approved["approved_value"], "Nieuwe beschrijving voor de test.")
        self.assertFalse(approved["edited"])
        self.assertIsNotNone(approved["change_id"])
        self.assertEqual(approved["reviewed_by"], self.user_name)
        self.db.refresh(suggestion)
        self.assertEqual(suggestion.status, "open")  # goedkeuren verandert de voorstelstatus niet

        r = self._put(item, "approve", value="Bewerkte beschrijving.", note="Klant wil korter.")
        edited = r.json()
        self.assertEqual(edited["approved_value"], "Bewerkte beschrijving.")
        self.assertTrue(edited["edited"])
        self.assertEqual(edited["note"], "Klant wil korter.")
        self.assertEqual(edited["change_id"], approved["change_id"])

        r = self._put(item, "reject")
        self.assertEqual(r.json()["status"], "afgewezen")
        self.db.refresh(suggestion)
        self.assertEqual(suggestion.status, "afgewezen")
        self.assertEqual(suggestion.updated_by, self.user_id)
        self.assertGreater(self.db.get(LaunchScan, self.scan.id).updated_at, checklist_before)  # checklist herberekend
        self.assertIn(item["key"], [i["key"] for i in self._page()["rejected"]])

        r = self._put(item, "reopen")
        reopened = r.json()
        self.assertEqual(reopened["status"], "open")
        self.assertIsNone(reopened["change_id"])
        self.assertEqual(self.db.query(SiteChange).filter(SiteChange.source_key == item["key"]).count(), 0)
        self.db.refresh(suggestion)
        self.assertEqual(suggestion.status, "open")

        self.assertEqual(self._put(item, "done").status_code, 409)  # eerst goedkeuren
        self._put(item, "approve")
        r = self._put(item, "done", note="Handmatig gedaan.")
        done = r.json()
        self.assertEqual(done["status"], "doorgevoerd")
        self.assertIsNone(done["verified"])
        self.assertEqual(done["done_by"], self.user_name)
        self.db.refresh(suggestion)
        self.assertEqual(suggestion.status, "overgenomen")
        self.assertEqual(self._put(item, "approve").status_code, 409)
        self.assertIn(item["key"], [i["key"] for i in self._page()["done"]])

        r = self._put(item, "reopen")
        back = r.json()
        self.assertEqual(back["status"], "goedgekeurd")  # doorgevoerd voorstel -> terug naar goedgekeurd
        self.assertIsNone(back["done_at"])
        self.db.refresh(suggestion)
        self.assertEqual(suggestion.status, "open")

    def test_issue_flow_and_rescan(self):
        issue_type = self._free_issue_type(["h1_multiple", "meta_too_short", "title_too_short", "lang_missing"])
        issue = self._issue(issue_type)
        item = self._key_for(self._page(), "issue_id", issue.id)
        self.assertEqual(item["source_kind"], "scan_issue")
        self.assertIsNone(item["proposed_value"])
        self.assertEqual(item["rationale"], "Los het op.")
        self.assertEqual(self._put(item, "approve").status_code, 422)

        r = self._put(item, "reject")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "afgewezen")
        self.db.refresh(issue)
        self.assertEqual(issue.status, "genegeerd")
        change_id = self.db.query(SiteChange).filter(SiteChange.source_key == item["key"]).one().id

        # Herscan: nieuwe issue-rij met dezelfde (issue_type, url) blijft aan dezelfde rij hangen.
        newer = self._issue(issue_type, created_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        page = self._page()
        again = self._item(page, item["key"])
        self.assertEqual(again["change_id"], change_id)
        self.assertEqual(again["status"], "afgewezen")
        self.assertEqual(again["source_ref"]["issue_id"], newer.id)

        r = self._put(again, "reopen")
        self.assertEqual(r.json()["status"], "open")
        self.db.refresh(newer)
        self.db.refresh(issue)
        self.assertEqual((newer.status, issue.status), ("open", "open"))

        r = self._put(again, "done")
        self.assertEqual(r.json()["status"], "doorgevoerd")
        self.db.refresh(newer)
        self.assertEqual(newer.status, "opgelost")
        r = self._put(again, "reopen")
        self.assertEqual(r.json()["status"], "open")
        self.assertEqual(self.db.query(SiteChange).filter(SiteChange.source_key == item["key"]).count(), 0)

    def test_open_high_in_totals(self):
        def totals():
            r = self.client.get(f"{self.base}/pages")
            self.assertEqual(r.status_code, 200, r.text)
            return r.json()["totals"]

        before = totals()
        issue_type = self._free_issue_type(["h1_multiple", "meta_too_short", "title_too_short", "lang_missing"])
        issue = self._issue(issue_type)  # severity "hoog"
        after = totals()
        self.assertEqual(after["open"], before["open"] + 1)
        self.assertEqual(after["open_high"], before["open_high"] + 1)
        self.assertLessEqual(after["open_high"], after["open"])

        item = self._key_for(self._page(), "issue_id", issue.id)
        self.assertEqual(self._put(item, "reject").status_code, 200)
        self.assertEqual(totals()["open_high"], before["open_high"])

    def test_source_gone_keeps_row(self):
        suggestion = self._suggestion("c3_headings", "## Nieuwe kop\nUitleg bij de kop.", current="Oude kop")
        item = self._key_for(self._page(), "suggestion_id", suggestion.id)
        self._put(item, "approve")
        # Heranalyse: het open voorstel wordt vervangen (hier: verwijderd).
        self.db.delete(suggestion)
        self.db.commit()
        kept = self._item(self._page(), item["key"])
        self.assertIsNotNone(kept)
        self.assertEqual(kept["status"], "goedgekeurd")
        self.assertEqual(kept["proposed_value"], "## Nieuwe kop\nUitleg bij de kop.")
        r = self._put(item, "reject")  # oude suggestion_id: werkt op de bestaande rij
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "afgewezen")
        unknown = dict(item, key="0" * 64, source_ref={"suggestion_id": str(uuid.uuid4())})
        self.assertEqual(self._put(unknown, "approve").status_code, 404)

    def test_unique_conflict_updates_existing_row(self):
        from sqlalchemy.orm import Query

        from app.features.site_changes.services.changes import upsert_row
        from app.features.site_changes.services.sources import collect_entries

        suggestion = self._suggestion("c3_meta_title", "Gelijktijdig | Test", current="Oud | Test")
        item = self._key_for(self._page(), "suggestion_id", suggestion.id)
        first = self._put(item, "approve").json()  # collega was net eerder
        _, entries = collect_entries(self.db, self.customer_id, url_key(self.page.url))
        entry = next(e for e in entries if e.key == item["key"])
        entry.row = None  # deze medewerker zag de rij nog niet
        real_first = Query.first
        calls = {"n": 0}

        def first_without_row(query):
            calls["n"] += 1
            return None if calls["n"] == 1 else real_first(query)

        with patch.object(Query, "first", first_without_row):
            row = upsert_row(self.db, self.customer_id, entry, {"status": "afgewezen"})
        self.assertEqual(calls["n"], 2)  # insert botste op de unieke sleutel, daarna de bestaande rij
        self.assertEqual(row.id, first["change_id"])
        self.assertEqual(self.db.query(SiteChange).filter(SiteChange.source_key == item["key"]).count(), 1)
        self.assertEqual(row.status, "afgewezen")

    def test_page_check(self):
        title = self._suggestion("c3_meta_title", "Live titel test", current="Oud")
        alt = self._suggestion("c3_images", "alt: Testbeeld van het team\nbestandsnaam: testbeeld-team.png",
                               current="", ref="https://www.iexist.nl/wp-content/uploads/2026/09/testbeeld.png")
        link = self._suggestion("c3_internal_links", "Lees meer over [SEA-diensten](https://www.iexist.nl/sea/).",
                                current="Lees meer over SEA.", ref="https://www.iexist.nl/sea/")
        faq = self._suggestion("c3_faq", "## Veelgestelde vragen\n**Wat kost een testpagina?**\nDat hangt af.")
        issue_type = self._free_issue_type(["h1_missing", "h1_multiple", "title_missing"])
        issue = self._issue(issue_type)
        page = self._page()
        items = {s.id: self._key_for(page, "suggestion_id", s.id) for s in (title, alt, link, faq)}
        for item in items.values():
            self.assertTrue(item["checkable"], item)
            self.assertEqual(self._put(item, "approve").status_code, 200)
        issue_item = self._key_for(page, "issue_id", issue.id)
        self.assertTrue(issue_item["checkable"])

        html = """<html lang="nl"><head><title>Live titel test | iExist</title>
        <meta name="description" content="Een meta description die lang genoeg is om niet als te kort gemeld te worden.">
        </head><body><main><h1>Eén kop</h1>
        <p>Lees meer over <a href="/sea/">SEA-diensten</a>.</p>
        <img src="https://www.iexist.nl/wp-content/uploads/2026/09/testbeeld-1024x768.png" alt="Testbeeld van het team">
        </main></body></html>"""
        fetched = FetchedPage(html=html, final_url=self.page.url, redirects=[],
                              headers={"content-type": "text/html"})

        # Mislukte fetch: 502 en niets gewijzigd.
        with patch(FETCH, side_effect=SchemaMarkupError("De pagina kon niet worden opgehaald (status 503).")):
            r = self.client.post(f"{self.base}/page/check", json={"url": self.page.url})
        self.assertEqual(r.status_code, 502)
        self.assertIn("status 503", r.json()["detail"])
        self.assertEqual(self._item(self._page(), items[title.id]["key"])["status"], "goedgekeurd")

        with patch(FETCH, return_value=fetched) as fetch:
            r = self.client.post(f"{self.base}/page/check", json={"url": self.page.url})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(fetch.call_count, 1)
        self.assertIn("iexist_schema_check=", fetch.call_args.args[0])
        body = r.json()
        self.assertEqual(body["verified"], 3)
        self.assertGreaterEqual(body["resolved_issues"], 1)
        self.assertGreaterEqual(body["checked"], 5)
        result = body["page"]
        self.assertIsNotNone(result["last_checked_at"])
        done_keys = {i["key"]: i for i in result["done"]}
        for s in (title, alt, link):
            done = done_keys[items[s.id]["key"]]
            self.assertTrue(done["verified"])
            self.assertEqual(done["done_by"], self.user_name)
            self.db.refresh(s)
            self.assertEqual(s.status, "overgenomen")
        faq_item = self._item(result, items[faq.id]["key"])
        self.assertEqual(faq_item["status"], "goedgekeurd")
        self.assertFalse(faq_item["verified"])
        self.assertIn("Wat kost een testpagina?", faq_item["verify_detail"]["missing"])
        self.db.refresh(faq)
        self.assertEqual(faq.status, "open")
        resolved = done_keys[issue_item["key"]]
        self.assertTrue(resolved["verified"])
        self.db.refresh(issue)
        self.assertEqual(issue.status, "opgelost")
