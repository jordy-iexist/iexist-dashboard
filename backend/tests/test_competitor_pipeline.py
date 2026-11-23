"""De taak van de concurrentieanalyse (features/competitor_analysis/worker/analysis.py).

Draait tegen een SQLite-database in een tijdelijke map: de PageSpeed-thread schrijft met een
eigen sessie, net als in productie, en een eigen verbinding per sessie voorkomt dat threads
elkaars transactie delen (bij een in-memory database met `StaticPool` delen ze er één).
Alle bronnen zijn vervangen: Ahrefs, `fetch_page`, `measure_vitals`, `classify_pages`,
`analyze_keyword` en `BrowserSession`. Geen netwerk.
"""
import asyncio
import json
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.models import (
    Base,
    CompetitorAnalysis,
    CompetitorAnalysisAction,
    CompetitorAnalysisKeyword,
    CompetitorAnalysisPage,
    CustomerWebsite,
)
from app.features.competitor_analysis.mappers import to_analysis_detail, to_keyword_detail
from app.features.competitor_analysis.schemas import ALL_MODULES, Eeat, MissingTopic, Sources, SourceStatus
from app.features.competitor_analysis.services import pipeline
from app.features.competitor_analysis.services.insights import (
    ActionDraft,
    ClassifyResult,
    KeywordInsights,
    PageClassification,
    page_key,
)
from app.features.competitor_analysis.worker import analysis
from app.features.launch_checklist.services.schema_markup import FetchedPage, SchemaMarkupError
from app.services.ahrefs import client as ahrefs_client
from app.services.ahrefs.client import AhrefsResult, AhrefsServiceError
from app.services.anthropic import client as anthropic_client
from app.services.anthropic.client import AnthropicServiceError

USER = "user-1"
TARGET_SEO = "https://klant.nl/seo/"
TARGET_SPECIALIST = "https://klant.nl/specialist/"


def _now():
    return datetime.now(timezone.utc)


def _row(position, types, url=None, title=None, *, page_type=None, dr=None, rd=None):
    return {"position": position, "type": types, "url": url, "title": title, "page_type": page_type,
            "domain_rating": dr, "url_rating": None, "refdomains": rd, "backlinks": None, "keywords": None,
            "update_date": "2026-11-20T08:00:00Z" if url else None}


# "seo bureau": doelpagina staat in de top 5 (organisch 3); een andere klantpagina ook (4).
SERP_SEO_BUREAU = [
    _row(1, ["organic"], "https://a.nl/seo/", "SEO bij A", page_type="/Landing_Page/Service_Page", dr=40.4, rd=20),
    _row(1, ["sitelink"], "https://a.nl/contact", "Contact"),
    _row(2, ["ai_overview"]),
    _row(2, ["ai_overview_sitelink"], "https://b.nl/gids", "Gids"),
    _row(2, ["ai_overview_sitelink"], "https://klant.nl/blog/seo", "Blog klant"),
    _row(3, ["question"], None, "Wat kost een SEO-bureau?"),
    _row(3, ["question"], None, "Hoe kies je een SEO-bureau?"),
    _row(4, ["organic"], "https://vergelijk.nl/seo-bureaus", "186 bureaus", page_type="/Listing_Collection", dr=70, rd=900),
    _row(5, ["organic"], TARGET_SEO, "SEO klant", page_type="/Landing_Page/Service_Page", dr=30, rd=10),
    _row(6, ["organic"], "https://blog.klant.nl/seo-tips", "Tips", page_type="/Article", dr=30, rd=2),
    _row(7, ["organic"], "https://c.nl/seo", "SEO bij C", dr=35, rd=15),
    _row(8, ["organic"], "https://d.nl/seo-diensten", "SEO bij D", dr=20, rd=5),
]
# "seo specialist": doelpagina buiten de top 5 (organisch 7).
SERP_SPECIALIST = [
    _row(1, ["organic"], "https://a.nl/specialist", "Specialist A", dr=40, rd=20),
    _row(2, ["organic"], "https://c.nl/seo", "SEO bij C", dr=35, rd=15),
    _row(3, ["organic"], "https://e.nl/specialist", "E", dr=25, rd=8),
    _row(4, ["organic"], "https://f.nl/specialist", "F", dr=22, rd=7),
    _row(5, ["organic"], "https://g.nl/specialist", "G", dr=21, rd=6),
    _row(6, ["organic"], "https://h.nl/specialist", "H", dr=20, rd=5),
    _row(7, ["organic"], TARGET_SPECIALIST, "Specialist klant", dr=30, rd=12),
]
# "seo amsterdam": geen doelpagina (nieuwe pagina).
SERP_AMSTERDAM = [
    _row(1, ["organic"], "https://a.nl/amsterdam", "A Amsterdam", dr=40, rd=20),
    _row(2, ["organic"], "https://b.nl/amsterdam", "B Amsterdam", dr=33, rd=11),
    _row(3, ["organic"], "https://c.nl/seo", "SEO bij C", dr=35, rd=15),
    _row(4, ["organic"], "https://i.nl/amsterdam", "I", dr=18, rd=4),
    _row(5, ["organic"], "https://j.nl/amsterdam", "J", dr=17, rd=3),
]
SERPS = {"seo bureau": SERP_SEO_BUREAU, "seo specialist": SERP_SPECIALIST, "seo amsterdam": SERP_AMSTERDAM}


def html_page(words=400, h2=4, schema=("WebPage",), faq=False):
    headings = "".join(f"<h2>Kop {i}</h2><p>{' '.join(['tekst'] * (words // max(h2, 1)))}</p>" for i in range(h2))
    jsonld = json.dumps({"@context": "https://schema.org", "@graph": [{"@type": t} for t in schema]})
    faq_html = "<h2>Veelgestelde vragen</h2><details><summary>Wat?</summary>Dit.</details>" \
               "<details><summary>Hoe?</summary>Zo.</details>" if faq else ""
    return (f"<html><head><title>Pagina</title><meta name='description' content='Omschrijving'>"
            f"<script type='application/ld+json'>{jsonld}</script></head>"
            f"<body><main><h1>Hoofdkop</h1>{headings}{faq_html}</main></body></html>")


class PipelineTestBase(unittest.TestCase):
    keywords = (("seo bureau", TARGET_SEO), ("seo specialist", TARGET_SPECIALIST), ("seo amsterdam", None))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        engine = create_engine(f"sqlite:///{self.tmp.name}/test.db", connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.customer_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(id=self.customer_id, name="Klant", base_url="https://www.klant.nl/",
                                   domain="klant.nl", created_by=USER, created_at=_now(), updated_at=_now()))
            db.commit()

        self._patch(analysis, "SessionLocal", self.Session)
        self._patch(analysis, "POLL_SECONDS", 0.05)
        self._patch(settings, "pagespeed_api_key", "psi-test")
        self._patch(settings, "competitor_analysis_vitals_budget_seconds", 10)
        self._patch(settings, "launch_scan_http_concurrency", 4)
        self.claude_configured = self._patch(anthropic_client, "is_configured", Mock(return_value=True))

        self.serp = self._patch(ahrefs_client, "serp_overview", Mock(side_effect=self.fake_serp))
        self.kw_overview = self._patch(ahrefs_client, "keywords_overview", Mock(side_effect=self.fake_kw_overview))
        self.url_metrics = self._patch(ahrefs_client, "url_metrics", Mock(side_effect=self.fake_url_metrics))
        self.fetch = self._patch(pipeline, "fetch_page", Mock(side_effect=self.fake_fetch))
        self.vitals = self._patch(pipeline, "measure_vitals", Mock(side_effect=self.fake_vitals))
        self.classify = self._patch(analysis, "classify_pages", Mock(side_effect=self.fake_classify))
        self.analyze = self._patch(analysis, "analyze_keyword", Mock(side_effect=self.fake_analyze))
        self.browser_html: dict[str, str] = {}
        self.browser_calls: list[str] = []
        self._patch(analysis, "BrowserSession", self.fake_browser_class())

        self.fetch_errors: dict[str, Exception] = {}

    def _patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    # --- nepbronnen ---------------------------------------------------------------------

    def fake_serp(self, keyword, *, country=None, top_positions=10):
        return AhrefsResult(rows=[dict(r) for r in SERPS[keyword]], units=150)

    def fake_kw_overview(self, keywords, *, country=None):
        rows = [{"keyword": k.upper(), "volume": 1000 + i, "difficulty": 40.6 + i,
                 "intents": {"commercial": True, "informational": i == 0, "local": False}}
                for i, k in enumerate(keywords)]
        return AhrefsResult(rows=list(reversed(rows)), units=31 * len(keywords))

    def fake_url_metrics(self, urls):
        return AhrefsResult(rows=[{"index": i, "url": u.split("://", 1)[1], "domain_rating": 31.2, "refdomains": 12,
                                   "target": u} for i, u in enumerate(urls)], units=50)

    def fake_fetch(self, url):
        if url in self.fetch_errors:
            raise self.fetch_errors[url]
        if url.startswith("https://a.nl/"):
            return FetchedPage(html=html_page(1200, 8, schema=("WebPage", "Service"), faq=True), final_url=url)
        return FetchedPage(html=html_page(), final_url=url)

    async def _vitals_all(self, urls, *, api_key, concurrency, on_result):
        for url in urls:
            if not on_result(url, {"lab": {"lcp": 2100.4}}, None):
                return

    def fake_vitals(self, urls, *, api_key, concurrency, on_result):
        self.vitals_urls = list(urls)
        return self._vitals_all(urls, api_key=api_key, concurrency=concurrency, on_result=on_result)

    def fake_classify(self, pages):
        by_key = {}
        for page in pages:
            aggregator = "vergelijk.nl" in page.url
            by_key[page_key(page)] = PageClassification(
                page_type="vergelijker" if aggregator else "dienst", is_aggregator=aggregator,
                reason="Vergelijkt bureaus" if aggregator else "Dienstpagina")
        return ClassifyResult(state="ok", by_key=by_key, usage={"input_tokens": 1000, "output_tokens": 100},
                              model="claude-opus-5-5")

    def fake_analyze(self, **kwargs):
        competitors = [p for p in kwargs["pages"] if not p.is_own and not p.is_excluded]
        eeat = {competitors[0].id: Eeat(team=True, note="Team zichtbaar")} if competitors else {}
        return KeywordInsights(
            state="ok", serp_summary=f"Samenvatting {kwargs['keyword']}", search_intent="Bureau vinden",
            missing_topics=[MissingTopic(topic="Prijzen", kind="topic", covered=2, total=3)], eeat=eeat,
            actions=[
                ActionDraft(title="Voeg prijzen toe", description="Concurrenten noemen prijzen.",
                            impact="hoog", effort="laag", category="topics"),
                ActionDraft(title="Meer H2's", description="Mediaan 8.", impact="middel", effort="laag",
                            category="onpage"),
            ],
            usage={"input_tokens": 20000, "output_tokens": 3000}, model="claude-opus-5-5",
        )

    def fake_browser_class(self):
        test = self

        class FakeBrowser:
            available = True
            start_error = None

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

            def page_html(self, url, *, timeout=20):
                test.browser_calls.append(url)
                return test.browser_html.get(url)

        return FakeBrowser

    # --- hulpjes ------------------------------------------------------------------------

    def add_analysis(self, *, status="pending", modules=ALL_MODULES, top_n=5, exclude_aggregators=True,
                     keywords=None, positions=None):
        analysis_id = str(uuid.uuid4())
        now = _now()
        sources = Sources(prt=SourceStatus(state="ok")).model_dump(mode="json")
        keywords = keywords or self.keywords
        with self.Session() as db:
            db.add(CompetitorAnalysis(
                id=analysis_id, customer_website_id=self.customer_id, created_by=USER, status=status,
                warnings=[], country="nl", top_n=top_n, exclude_aggregators=exclude_aggregators,
                modules=list(modules), total_keywords=len(keywords), done_keywords=0, total_pages=0,
                fetched_pages=0, failed_pages=0, vitals_total=0, vitals_measured=0, ahrefs_units=0,
                sources=sources, created_at=now, updated_at=now,
            ))
            for index, (keyword, target) in enumerate(keywords):
                position = (positions or {}).get(keyword)
                db.add(CompetitorAnalysisKeyword(
                    id=str(uuid.uuid4()), analysis_id=analysis_id, sort_order=index, keyword=keyword,
                    keyword_key=keyword, target_url=target, own_position=position,
                    own_position_source="prt" if position else None, volume=None, status="pending",
                    created_at=now, updated_at=now,
                ))
            db.commit()
        return analysis_id

    def run_task(self, analysis_id):
        return analysis.run_competitor_analysis_task.run(analysis_id)

    def analysis(self, analysis_id):
        with self.Session() as db:
            row = db.get(CompetitorAnalysis, analysis_id)
            db.expunge(row)
            return row

    def keyword(self, analysis_id, name):
        with self.Session() as db:
            row = db.query(CompetitorAnalysisKeyword).filter_by(analysis_id=analysis_id, keyword=name).one()
            db.expunge(row)
            return row

    def pages(self, keyword_id):
        with self.Session() as db:
            rows = db.query(CompetitorAnalysisPage).filter_by(keyword_id=keyword_id).all()
            for row in rows:
                db.expunge(row)
            return sorted(rows, key=lambda p: (p.position is None, p.position or 0))

    def detail(self, analysis_id, name):
        keyword = self.keyword(analysis_id, name)
        with self.Session() as db:
            pages = db.query(CompetitorAnalysisPage).filter_by(keyword_id=keyword.id).all()
            actions = db.query(CompetitorAnalysisAction).filter_by(keyword_id=keyword.id).all()
            return to_keyword_detail(keyword, pages, actions, {})


class FullRunTest(PipelineTestBase):
    def test_successful_run_end_to_end(self):
        analysis_id = self.add_analysis(positions={"seo specialist": 9})
        self.assertEqual(self.run_task(analysis_id), analysis_id)

        run = self.analysis(analysis_id)
        self.assertEqual(run.status, "completed", run.error_message)
        self.assertIsNotNone(run.completed_at)
        self.assertIsNone(run.error_message)
        self.assertEqual(run.warnings, [])
        # 3 × SERP (150) + keywords_overview (3 × 31) + url_metrics (50) voor de eigen pagina buiten de top.
        self.assertEqual(run.ahrefs_units, 450 + 93 + 50)
        self.assertEqual(run.ai_usage["calls"], 4)  # 1 × indeling + 3 × inhoudsanalyse
        self.assertEqual(run.ai_usage["input_tokens"], 61000)
        self.assertGreater(run.ai_usage["cost_usd"], 0)
        # Paginarijen: 5 + (5 + eigen) + 5.
        self.assertEqual((run.total_pages, run.fetched_pages, run.failed_pages), (16, 16, 0))
        self.assertEqual((run.done_keywords, run.total_keywords), (3, 3))
        self.assertEqual(run.vitals_total, len(set(self.vitals_urls)))
        self.assertEqual(run.vitals_measured, run.vitals_total)
        sources = Sources.model_validate(run.sources)
        self.assertEqual((sources.ahrefs.state, sources.claude.state, sources.pagespeed.state, sources.google.state,
                          sources.prt.state), ("ok", "ok", "ok", "skipped", "ok"))
        # Elke unieke URL één keer opgehaald (c.nl/seo staat bij alle drie de zoekwoorden).
        fetched = [c.args[0] for c in self.fetch.call_args_list]
        self.assertEqual(len(fetched), len(set(fetched)))
        self.assertEqual(fetched.count("https://c.nl/seo"), 1)
        self.assertEqual(self.browser_calls, [])

        # Zoekwoord 1: doelpagina in de top 5.
        kw = self.keyword(analysis_id, "seo bureau")
        self.assertEqual((kw.status, kw.ai_state, kw.own_position, kw.own_position_source), ("completed", "ok", 3, "ahrefs"))
        self.assertEqual((kw.kd, kw.volume, kw.intents), (41, 1000, ["commercial", "informational"]))
        self.assertEqual(kw.serp_features, ["ai_overview", "question"])
        self.assertEqual(kw.serp_date, "2026-11-20T08:00:00Z")
        self.assertEqual(kw.paa, {"state": "ok", "questions": ["Wat kost een SEO-bureau?", "Hoe kies je een SEO-bureau?"]})
        self.assertEqual(kw.ai_overview["state"], "ok")
        self.assertEqual([s["domain"] for s in kw.ai_overview["sources"]], ["b.nl", "klant.nl"])
        self.assertIs(kw.ai_overview["own_cited"], True)
        self.assertEqual(kw.serp_summary, "Samenvatting seo bureau")
        self.assertEqual(kw.missing_topics, [{"topic": "Prijzen", "kind": "topic", "covered": 2, "total": 3}])

        pages = self.pages(kw.id)
        self.assertEqual([(p.position, p.url, p.is_own, p.is_excluded, p.exclude_reason) for p in pages], [
            (1, "https://a.nl/seo/", False, False, None),
            (2, "https://vergelijk.nl/seo-bureaus", False, True, "aggregator"),
            (3, TARGET_SEO, True, False, None),
            (4, "https://blog.klant.nl/seo-tips", False, True, "own_site"),
            (5, "https://c.nl/seo", False, False, None),
        ])
        first = pages[0]
        self.assertEqual((first.domain, first.domain_rating, first.refdomains, first.page_type, first.is_aggregator),
                         ("a.nl", 40, 20, "dienst", False))
        self.assertEqual(first.ahrefs["classify_reason"], "Dienstpagina")
        self.assertEqual(first.ahrefs["serp_position"], 1)
        self.assertEqual((first.fetch_status, first.final_url, first.lcp_ms), ("ok", "https://a.nl/seo/", 2100))
        self.assertEqual(first.cwv, {"lcp_ms": 2100, "source": "lab", "error": None})
        self.assertEqual(first.onpage["h2_count"], 9)  # 8 + "Veelgestelde vragen"
        self.assertTrue(first.onpage["has_faq"])
        self.assertEqual(first.eeat["team"], True)
        self.assertEqual(pages[1].page_type, "vergelijker")
        self.assertTrue(pages[1].is_aggregator)

        # Aanroep B kreeg de pagina's ná het uitsluiten en de tekst per pagina-id.
        call = next(c.kwargs for c in self.analyze.call_args_list if c.kwargs["keyword"] == "seo bureau")
        excluded = {p.url: p.is_excluded for p in call["pages"]}
        self.assertTrue(excluded["https://vergelijk.nl/seo-bureaus"])
        self.assertEqual(set(call["texts"]), {p.id for p in pages})
        self.assertIn("tekst", call["texts"][first.id])
        self.assertEqual(call["paa"], ["Wat kost een SEO-bureau?", "Hoe kies je een SEO-bureau?"])
        self.assertEqual(call["customer_domain"], "klant.nl")
        self.assertEqual(call["intents"], ["commercial", "informational"])

        # Verbeterpunten op volgorde.
        with self.Session() as db:
            actions = db.query(CompetitorAnalysisAction).filter_by(keyword_id=kw.id).order_by(
                CompetitorAnalysisAction.sort_order).all()
            self.assertEqual([(a.sort_order, a.title, a.impact, a.category) for a in actions],
                             [(0, "Voeg prijzen toe", "hoog", "topics"), (1, "Meer H2's", "middel", "onpage")])

        # Weergave: medianen tellen de aggregator en de eigen-sitepagina niet mee; schema zonder generieke types.
        detail = self.detail(analysis_id, "seo bureau")
        self.assertEqual(detail.pages[0].schema_types, ["Service"])
        self.assertEqual(detail.own.schema_types, [])
        self.assertEqual(detail.own.position, 3)
        self.assertEqual(detail.median.total, 2)  # a.nl en c.nl
        self.assertIsNone(detail.median.words)  # minder dan 3 waarden

        # Zoekwoord 2: doelpagina buiten de top 5; PRT-positie blijft staan.
        kw2 = self.keyword(analysis_id, "seo specialist")
        self.assertEqual((kw2.own_position, kw2.own_position_source), (9, "prt"))
        pages2 = self.pages(kw2.id)
        self.assertEqual(len(pages2), 6)
        own = pages2[-1]
        self.assertEqual((own.url, own.is_own, own.position, own.domain_rating, own.refdomains),
                         (TARGET_SPECIALIST, True, None, 31, 12))
        self.assertEqual(self.url_metrics.call_args.args[0], [TARGET_SPECIALIST])
        self.assertEqual(own.fetch_status, "ok")
        detail2 = self.detail(analysis_id, "seo specialist")
        self.assertEqual(detail2.median.total, 5)
        self.assertIsNotNone(detail2.median.words)
        self.assertEqual(detail2.median.domain_rating, 25)  # 40, 35, 25, 22, 21

        # Zoekwoord 3: geen doelpagina, geen eigen rij.
        kw3 = self.keyword(analysis_id, "seo amsterdam")
        self.assertEqual((kw3.status, kw3.own_position), ("completed", None))
        pages3 = self.pages(kw3.id)
        self.assertEqual(len(pages3), 5)
        self.assertFalse(any(p.is_own for p in pages3))
        self.assertIsNone(self.detail(analysis_id, "seo amsterdam").own)
        self.assertIs(kw3.ai_overview["own_cited"], None)
        self.assertEqual(kw3.ai_overview["state"], "empty")
        self.assertEqual(kw3.paa["state"], "empty")
        # Een lege AI Overview gaat als "ok zonder bronnen" naar de prompt ("geen AI Overview gevonden").
        call3 = next(c.kwargs for c in self.analyze.call_args_list if c.kwargs["keyword"] == "seo amsterdam")
        self.assertEqual((call3["ai_overview"].state, call3["ai_overview"].sources), ("ok", []))

        # Het detail van de run is geldig.
        with self.Session() as db:
            keywords = db.query(CompetitorAnalysisKeyword).filter_by(analysis_id=analysis_id).all()
            row = db.get(CompetitorAnalysis, analysis_id)
            self.assertEqual(to_analysis_detail(row, keywords).status, "completed")

    def test_not_started_unless_pending(self):
        for status in ("serp", "completed", "canceled", "failed"):
            analysis_id = self.add_analysis(status=status)
            self.run_task(analysis_id)
            self.assertEqual(self.analysis(analysis_id).status, status)
        self.run_task("bestaat-niet")
        self.serp.assert_not_called()

    def test_redelivery_after_completion_spends_nothing(self):
        analysis_id = self.add_analysis()
        self.run_task(analysis_id)
        calls = self.serp.call_count
        self.run_task(analysis_id)
        self.assertEqual(self.serp.call_count, calls)


class FetchTest(PipelineTestBase):
    keywords = (("seo bureau", TARGET_SEO),)

    def test_blocked_page_retry_succeeds_and_fails(self):
        self.fetch_errors["https://c.nl/seo"] = SchemaMarkupError("De pagina kon niet worden opgehaald (status 403).")
        self.fetch_errors["https://a.nl/seo/"] = SchemaMarkupError("De pagina kon niet worden opgehaald (status 429).")
        self.browser_html["https://c.nl/seo"] = html_page(600, 5)
        analysis_id = self.add_analysis()
        self.run_task(analysis_id)

        run = self.analysis(analysis_id)
        self.assertEqual(run.status, "completed")
        self.assertEqual((run.total_pages, run.fetched_pages, run.failed_pages), (5, 5, 1))
        self.assertEqual(sorted(self.browser_calls), ["https://a.nl/seo/", "https://c.nl/seo"])
        by_url = {p.url: p for p in self.pages(self.keyword(analysis_id, "seo bureau").id)}
        rescued = by_url["https://c.nl/seo"]
        self.assertEqual((rescued.fetch_status, rescued.fetch_error, rescued.onpage["h2_count"]), ("ok", None, 5))
        blocked = by_url["https://a.nl/seo/"]
        self.assertEqual(blocked.fetch_status, "blocked")
        self.assertEqual(blocked.fetch_error,
                         "Geweigerd door de website (HTTP 429). Ook via de browser niet gelukt.")
        self.assertIsNone(blocked.onpage)
        # Aanroep B kreeg de tekst van de geredde pagina, niet van de geblokkeerde.
        texts = self.analyze.call_args.kwargs["texts"]
        self.assertIn(rescued.id, texts)
        self.assertNotIn(blocked.id, texts)

    def test_thin_page_retried_in_browser(self):
        """Een met JavaScript opgebouwde pagina (bijna geen tekst) krijgt de browser als herkansing."""
        shell = "<html><head><title>App</title></head><body><div id='app'></div></body></html>"
        thin = {"https://c.nl/seo", "https://a.nl/seo/"}

        def fetch(url):
            return FetchedPage(html=shell, final_url=url) if url in thin else self.fake_fetch(url)

        self.fetch.side_effect = fetch
        self.browser_html["https://c.nl/seo"] = html_page(900, 6)
        self.browser_html["https://a.nl/seo/"] = shell  # ook in de browser leeg: eerste uitkomst blijft
        analysis_id = self.add_analysis()
        self.run_task(analysis_id)

        run = self.analysis(analysis_id)
        self.assertEqual((run.status, run.fetched_pages, run.failed_pages), ("completed", 5, 0))
        self.assertEqual(sorted(self.browser_calls), ["https://a.nl/seo/", "https://c.nl/seo"])
        by_url = {p.url: p for p in self.pages(self.keyword(analysis_id, "seo bureau").id)}
        self.assertEqual(by_url["https://c.nl/seo"].onpage["h2_count"], 6)
        self.assertGreater(by_url["https://c.nl/seo"].onpage["word_count"], 800)
        still_thin = by_url["https://a.nl/seo/"]
        self.assertEqual((still_thin.fetch_status, still_thin.onpage["word_count"]), ("ok", 0))
        self.assertTrue(self.detail(analysis_id, "seo bureau").pages[0].unreadable)

    def test_no_browser_without_blocked_pages_and_not_html_and_errors(self):
        self.fetch_errors["https://c.nl/seo"] = SchemaMarkupError("De pagina is geen HTML-pagina.")
        self.fetch_errors["https://a.nl/seo/"] = SchemaMarkupError(
            "De pagina kon niet worden opgehaald (ConnectTimeout). Probeer het later opnieuw.")
        self.fetch_errors[TARGET_SEO] = SchemaMarkupError("De pagina kon niet worden opgehaald (status 404).")
        analysis_id = self.add_analysis()
        self.run_task(analysis_id)

        run = self.analysis(analysis_id)
        self.assertEqual((run.status, run.fetched_pages, run.failed_pages), ("completed", 5, 3))
        self.assertEqual(self.browser_calls, [])
        by_url = {p.url: p for p in self.pages(self.keyword(analysis_id, "seo bureau").id)}
        self.assertEqual((by_url["https://c.nl/seo"].fetch_status, by_url["https://c.nl/seo"].fetch_error),
                         ("not_html", "Geen HTML-pagina."))
        self.assertEqual(by_url["https://a.nl/seo/"].fetch_status, "error")
        self.assertIn("ConnectTimeout", by_url["https://a.nl/seo/"].fetch_error)
        self.assertEqual((by_url[TARGET_SEO].fetch_status, by_url[TARGET_SEO].fetch_error),
                         ("error", "Niet opgehaald (HTTP 404)."))


class AhrefsErrorTest(PipelineTestBase):
    def test_error_on_one_keyword(self):
        def serp(keyword, **kwargs):
            if keyword == "seo specialist":
                raise AhrefsServiceError("Ahrefs-fout: kapot", code="ahrefs_error")
            return self.fake_serp(keyword, **kwargs)

        self.serp.side_effect = serp
        analysis_id = self.add_analysis()
        self.run_task(analysis_id)

        run = self.analysis(analysis_id)
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.done_keywords, 3)
        self.assertEqual(run.ahrefs_units, 300 + 62 + 0)  # geen url_metrics: de eigen pagina zat bij het mislukte zoekwoord
        self.url_metrics.assert_not_called()
        self.assertIn("1 van de 3 zoekwoorden mislukt: seo specialist.", run.warnings)
        self.assertEqual(Sources.model_validate(run.sources).ahrefs.message, "1 van de 3 zoekwoorden mislukt.")
        failed = self.keyword(analysis_id, "seo specialist")
        self.assertEqual((failed.status, failed.error_message), ("failed", "Ahrefs gaf geen zoekresultaten: Ahrefs-fout: kapot"))
        self.assertEqual(self.pages(failed.id), [])
        self.assertEqual(self.analyze.call_count, 2)
        self.assertEqual(self.kw_overview.call_args.args[0], ["seo bureau", "seo amsterdam"])

    def test_error_on_all_keywords_fails_run(self):
        self.serp.side_effect = AhrefsServiceError("Ahrefs is tijdelijk niet beschikbaar (HTTP 503).", code="ahrefs_error")
        analysis_id = self.add_analysis()
        self.run_task(analysis_id)

        run = self.analysis(analysis_id)
        self.assertEqual(run.status, "failed")
        self.assertIn("geen enkel zoekwoord", run.error_message)
        self.assertEqual(self.serp.call_count, 3)
        self.assertEqual(Sources.model_validate(run.sources).ahrefs.state, "error")
        self.fetch.assert_not_called()
        self.classify.assert_not_called()

    def test_unauthorized_fails_run_immediately(self):
        self.serp.side_effect = AhrefsServiceError("Ahrefs weigert de API-key (ongeldig of verlopen).", code="unauthorized")
        analysis_id = self.add_analysis()
        self.run_task(analysis_id)

        run = self.analysis(analysis_id)
        self.assertEqual((run.status, run.error_message), ("failed", "Ahrefs weigert de API-key (ongeldig of verlopen)."))
        self.assertEqual(self.serp.call_count, 1)
        self.kw_overview.assert_not_called()

    def test_keywords_overview_error_is_a_warning(self):
        self.kw_overview.side_effect = AhrefsServiceError("Ahrefs-fout: x", code="ahrefs_error")
        analysis_id = self.add_analysis()
        self.run_task(analysis_id)
        run = self.analysis(analysis_id)
        self.assertEqual(run.status, "completed")
        self.assertIn("Volume, KD en intentie niet opgehaald: Ahrefs-fout: x", run.warnings)
        self.assertIsNone(self.keyword(analysis_id, "seo bureau").kd)


class ClaudeTest(PipelineTestBase):
    def test_without_claude_key(self):
        self.claude_configured.return_value = False
        analysis_id = self.add_analysis()
        self.run_task(analysis_id)

        run = self.analysis(analysis_id)
        self.assertEqual(run.status, "completed")
        self.classify.assert_not_called()
        self.analyze.assert_not_called()
        self.assertIsNone(run.ai_usage)
        self.assertIn(analysis.NO_AGGREGATOR_EXCLUSION_WARNING, run.warnings)
        self.assertEqual(Sources.model_validate(run.sources).claude.state, "not_configured")
        kw = self.keyword(analysis_id, "seo bureau")
        self.assertEqual((kw.status, kw.ai_state), ("completed", "not_configured"))
        by_url = {p.url: p for p in self.pages(kw.id)}
        # Paginatype grofweg uit Ahrefs; niets als aggregator uitgesloten, wel de eigen site.
        self.assertEqual(by_url["https://a.nl/seo/"].page_type, "dienst")
        self.assertEqual(by_url["https://vergelijk.nl/seo-bureaus"].page_type, "categorie")
        self.assertFalse(by_url["https://vergelijk.nl/seo-bureaus"].is_excluded)
        self.assertEqual(by_url["https://blog.klant.nl/seo-tips"].page_type, "blog")
        self.assertEqual(by_url["https://blog.klant.nl/seo-tips"].exclude_reason, "own_site")
        self.assertEqual(by_url["https://c.nl/seo"].page_type, "overig")
        self.assertIsNone(by_url["https://a.nl/seo/"].is_aggregator)

    def test_claude_error_on_one_keyword(self):
        def analyze(**kwargs):
            if kwargs["keyword"] == "seo specialist":
                raise AnthropicServiceError("Timeout bij wachten op Claude.", "timeout")
            return self.fake_analyze(**kwargs)

        self.analyze.side_effect = analyze
        analysis_id = self.add_analysis()
        self.run_task(analysis_id)

        run = self.analysis(analysis_id)
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.ai_usage["calls"], 3)
        claude = Sources.model_validate(run.sources).claude
        self.assertEqual(claude.state, "error")
        self.assertIn("seo specialist", claude.message)
        failed = self.keyword(analysis_id, "seo specialist")
        self.assertEqual((failed.status, failed.ai_state, failed.ai_error),
                         ("completed", "error", "Timeout bij wachten op Claude."))
        self.assertIsNone(failed.serp_summary)
        ok = self.keyword(analysis_id, "seo bureau")
        self.assertEqual(ok.ai_state, "ok")

    def test_classify_error_falls_back_to_ahrefs(self):
        self.classify.side_effect = AnthropicServiceError("Anthropic-fout (HTTP 500: x).", "anthropic_error")
        analysis_id = self.add_analysis(keywords=(("seo bureau", TARGET_SEO),))
        self.run_task(analysis_id)
        run = self.analysis(analysis_id)
        self.assertEqual(run.status, "completed")
        self.assertEqual(Sources.model_validate(run.sources).claude.state, "error")
        self.assertTrue(any("pagina-indeling door Claude is mislukt" in w for w in run.warnings))
        by_url = {p.url: p for p in self.pages(self.keyword(analysis_id, "seo bureau").id)}
        self.assertFalse(by_url["https://vergelijk.nl/seo-bureaus"].is_excluded)
        self.assertEqual(self.keyword(analysis_id, "seo bureau").ai_state, "ok")

    def test_aggregators_kept_when_exclusion_off(self):
        analysis_id = self.add_analysis(exclude_aggregators=False, keywords=(("seo bureau", TARGET_SEO),))
        self.run_task(analysis_id)
        page = next(p for p in self.pages(self.keyword(analysis_id, "seo bureau").id) if "vergelijk" in p.url)
        self.assertEqual((page.is_aggregator, page.is_excluded, page.page_type), (True, False, "vergelijker"))


class VitalsTest(PipelineTestBase):
    keywords = (("seo bureau", TARGET_SEO),)

    def test_pagespeed_too_late(self):
        self._patch(settings, "competitor_analysis_vitals_budget_seconds", 0.3)
        release = threading.Event()
        self.addCleanup(release.set)

        async def slow(urls, *, api_key, concurrency, on_result):
            on_result(urls[0], {"lab": {"lcp": 3000.0}}, None)
            for _ in range(200):  # ruim langer dan het budget; wordt afgebroken
                if release.is_set():
                    return
                await asyncio.sleep(0.05)

        self.vitals.side_effect = lambda urls, **kw: slow(urls, **kw)
        analysis_id = self.add_analysis()
        started = time.monotonic()
        self.run_task(analysis_id)
        self.assertLess(time.monotonic() - started, 5)

        run = self.analysis(analysis_id)
        self.assertEqual(run.status, "completed")
        self.assertEqual((run.vitals_total, run.vitals_measured), (5, 1))
        pages = self.pages(self.keyword(analysis_id, "seo bureau").id)
        measured = [p for p in pages if p.lcp_ms is not None]
        self.assertEqual([p.lcp_ms for p in measured], [3000])
        late = [p for p in pages if p.lcp_ms is None]
        self.assertEqual({p.cwv["error"] for p in late}, {"niet op tijd gemeten"})
        pagespeed = Sources.model_validate(run.sources).pagespeed
        self.assertEqual(pagespeed.state, "ok")
        self.assertIn("4 van de 5 URL's niet op tijd gemeten", pagespeed.message)

    def test_pagespeed_errors(self):
        async def broken(urls, *, api_key, concurrency, on_result):
            on_result(urls[0], None, "PSI 500: interne fout")
            raise RuntimeError("kapot")

        self.vitals.side_effect = lambda urls, **kw: broken(urls, **kw)
        analysis_id = self.add_analysis()
        self.run_task(analysis_id)

        run = self.analysis(analysis_id)
        self.assertEqual(run.status, "completed")
        pages = self.pages(self.keyword(analysis_id, "seo bureau").id)
        errors = sorted(p.cwv["error"] for p in pages)
        self.assertEqual(errors.count("Meting mislukt (PSI 500: interne fout)."), 1)
        self.assertEqual(errors.count("meting mislukt"), 4)
        self.assertTrue(all(p.lcp_ms is None for p in pages))
        pagespeed = Sources.model_validate(run.sources).pagespeed
        self.assertEqual(pagespeed.state, "ok")
        self.assertIn("1 meting(en) mislukt", pagespeed.message)
        self.assertIn("PageSpeed-meting afgebroken (RuntimeError)", pagespeed.message)

    def test_pagespeed_without_key(self):
        self._patch(settings, "pagespeed_api_key", "")
        analysis_id = self.add_analysis()
        self.run_task(analysis_id)
        run = self.analysis(analysis_id)
        self.assertEqual((run.status, run.vitals_total), ("completed", 0))
        self.vitals.assert_not_called()
        self.assertEqual(Sources.model_validate(run.sources).pagespeed.state, "not_configured")


class ModulesTest(PipelineTestBase):
    keywords = (("seo bureau", TARGET_SEO), ("seo specialist", TARGET_SPECIALIST))

    def test_only_serp(self):
        analysis_id = self.add_analysis(modules=["serp"])
        self.run_task(analysis_id)

        run = self.analysis(analysis_id)
        self.assertEqual(run.status, "completed")
        self.fetch.assert_not_called()
        self.vitals.assert_not_called()
        self.analyze.assert_not_called()
        self.url_metrics.assert_not_called()
        self.classify.assert_called_once()  # indeling blijft (uitsluiten van vergelijkingssites)
        self.assertEqual((run.fetched_pages, run.vitals_total), (0, 0))
        self.assertEqual(run.ahrefs_units, 300 + 62)
        sources = Sources.model_validate(run.sources)
        self.assertEqual(sources.pagespeed.state, "skipped")
        kw = self.keyword(analysis_id, "seo bureau")
        self.assertEqual((kw.status, kw.ai_state), ("completed", "skipped"))
        self.assertEqual(kw.paa["state"], "ok")
        pages = self.pages(kw.id)
        self.assertTrue(all(p.domain_rating is None and p.refdomains is None for p in pages))
        self.assertTrue(all(p.fetch_status is None for p in pages))

    def test_without_serp_module(self):
        analysis_id = self.add_analysis(modules=["onpage", "authority"])
        self.run_task(analysis_id)

        kw = self.keyword(analysis_id, "seo bureau")
        self.assertEqual(kw.paa, {"state": "skipped", "questions": []})
        self.assertEqual(kw.ai_overview["state"], "skipped")
        self.assertEqual(kw.serp_features, [])
        self.assertIsNone(kw.intents)
        self.assertEqual(kw.kd, 41)  # volume en KD altijd
        self.assertEqual(kw.ai_state, "skipped")
        self.analyze.assert_not_called()
        self.vitals.assert_not_called()
        self.assertTrue(self.fetch.called)
        self.url_metrics.assert_called_once()


class StopTest(PipelineTestBase):
    keywords = (("seo bureau", TARGET_SEO),)

    def set_status(self, analysis_id, status):
        with self.Session() as db:
            db.get(CompetitorAnalysis, analysis_id).status = status
            db.commit()

    def test_cancel_halfway(self):
        analysis_id = self.add_analysis()

        def fetch(url):
            self.set_status(analysis_id, "canceled")
            return self.fake_fetch(url)

        self.fetch.side_effect = fetch
        self.run_task(analysis_id)

        run = self.analysis(analysis_id)
        self.assertEqual(run.status, "canceled")
        self.assertIsNone(run.error_message)
        self.classify.assert_not_called()
        self.analyze.assert_not_called()
        self.assertEqual(self.keyword(analysis_id, "seo bureau").status, "pending")

    def test_soft_time_limit(self):
        analysis_id = self.add_analysis()
        self.classify.side_effect = SoftTimeLimitExceeded()
        self.run_task(analysis_id)

        run = self.analysis(analysis_id)
        self.assertEqual((run.status, run.error_message), ("failed", analysis.TIMEOUT_MESSAGE))
        self.assertEqual(run.ahrefs_units, 150 + 31)
        self.assertEqual(run.fetched_pages, 5)
        self.analyze.assert_not_called()
        self.assertEqual(self.keyword(analysis_id, "seo bureau").status, "pending")

    def test_unexpected_error_fails_with_short_message(self):
        self._patch(pipeline, "serp_facts", Mock(side_effect=ValueError("geheim detail")))
        analysis_id = self.add_analysis()
        with self.assertLogs(analysis.logger, level="ERROR"):
            self.run_task(analysis_id)
        run = self.analysis(analysis_id)
        self.assertEqual((run.status, run.error_message),
                         ("failed", "De analyse is gestopt door een interne fout (ValueError)."))


class PipelineUnitTest(unittest.TestCase):
    def test_fetch_error_classification(self):
        cases = {
            "De pagina kon niet worden opgehaald (status 403).": ("blocked", "Geweigerd door de website (HTTP 403)."),
            "De pagina kon niet worden opgehaald (status 503).": ("blocked", "Geweigerd door de website (HTTP 503)."),
            "De pagina kon niet worden opgehaald (status 500).": ("error", "Niet opgehaald (HTTP 500)."),
            "De pagina is geen HTML-pagina.": ("not_html", "Geen HTML-pagina."),
            "De pagina-URL wijst niet naar een toegestane externe website.": ("error", "Adres niet toegestaan."),
        }
        for message, expected in cases.items():
            outcome = pipeline.fetch_error_outcome(SchemaMarkupError(message))
            self.assertEqual((outcome.status, outcome.error), expected, message)
        self.assertEqual(pipeline.fetch_error_outcome(OSError("x")).error, "Ophalen mislukt (OSError).")

    def test_page_type_from_ahrefs(self):
        self.assertEqual(pipeline.page_type_from_ahrefs("/Core_Page,/Core_Page/Homepage"), "homepage")
        self.assertEqual(pipeline.page_type_from_ahrefs("/Landing_Page,/Landing_Page/Service_Page"), "dienst")
        self.assertEqual(pipeline.page_type_from_ahrefs("/Article/Blog_Post"), "blog")
        self.assertEqual(pipeline.page_type_from_ahrefs(None), "overig")

    def test_same_page_ignores_www_scheme_and_slash(self):
        self.assertTrue(pipeline.same_page("http://www.klant.nl/seo", "https://klant.nl/seo/"))
        self.assertFalse(pipeline.same_page("https://klant.nl/seo/", "https://klant.nl/seo/?a=1"))
        self.assertFalse(pipeline.same_page(None, "https://klant.nl/"))

    def test_serp_facts_own_rank_beyond_top_n(self):
        facts = pipeline.serp_facts(
            AhrefsResult(rows=SERP_SPECIALIST), top_n=5, target_url=TARGET_SPECIALIST, customer_root="klant.nl",
            with_serp=True, with_authority=True,
        )
        self.assertEqual(facts.own_rank, 7)
        self.assertTrue(facts.own_needs_metrics)
        self.assertEqual([p.position for p in facts.pages], [1, 2, 3, 4, 5, None])

    def test_cwv_from_psi(self):
        self.assertEqual(pipeline.cwv_from_psi({"lab": {"lcp": 1234.6}}, None).lcp_ms, 1235)
        self.assertEqual(pipeline.cwv_from_psi({"lab": {}}, None).error, "Geen LCP in de meting.")
        self.assertEqual(pipeline.cwv_from_psi(None, "PSI 400: x").error, "Meting mislukt (PSI 400: x).")


if __name__ == "__main__":
    unittest.main()
