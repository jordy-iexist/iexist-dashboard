"""Endpoints van de concurrentieanalyse (features/competitor_analysis/router).

Draait tegen een in-memory SQLite-database. De taak (`run_competitor_analysis_task.delay`),
ProRankTracker (`proposal.organic_rows`), Ahrefs en Claude zijn in elke test vervangen:
geen netwerk en geen Celery.
"""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.dependencies import require_user_id
from app.db.models import (
    Base,
    CompetitorAnalysis,
    CompetitorAnalysisAction,
    CompetitorAnalysisKeyword,
    CompetitorAnalysisPage,
    CustomerQuickWins,
    CustomerWebsite,
    User,
)
from app.db.session import get_db
from app.features.competitor_analysis import router as router_module
from app.features.competitor_analysis.router import router
from app.features.competitor_analysis.schemas import (
    FLAG_METRICS,
    AnalysisDetail,
    Estimate,
    KeywordDetail,
    Sources,
)
from app.features.competitor_analysis.services import estimate, proposal, recovery
from app.worker.tasks import run_competitor_analysis_task

USER = "user-1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _prt(name, rank="7", *, volume="100", url="https://klant.nl/seo/"):
    return {
        "name": name, "rank": rank, "monthagorank": "9", "localmonthlysearches": volume,
        "matchedurl": url, "engine": "Google.nl", "term_type": "organic", "is_ai_term": 0,
    }


def _onpage(words, h2=3, *, faq=False, schema=()):
    return {"title": "T", "h1": "H", "h2_count": h2, "h3_count": 1, "headings": [{"level": 1, "text": "H"}],
            "word_count": words, "internal_links": 10, "images": 2, "has_faq": faq,
            "schema_types": list(schema)}


class _Base(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.customer_id = self.add_customer("https://www.klant.nl/")
        with self.Session() as db:
            db.add(User(id=USER, email="jan@iexist.nl", password_hash="x", created_at=_now(), updated_at=_now()))
            db.commit()

        self.ahrefs_configured = self._patch(router_module.ahrefs, "is_configured", Mock(return_value=True))
        self.claude_configured = self._patch(router_module.anthropic_client, "is_configured", Mock(return_value=True))
        self.organic = self._patch(proposal, "organic_rows", Mock(return_value=(
            "ok", [_prt("seo bureau", "6", volume="900", url="https://klant.nl/seo/")], None)))
        self.usage = self._patch(proposal.ahrefs, "limits_and_usage", Mock(return_value={}))
        self.paid = self._patch(proposal.ahrefs, "serp_overview", Mock())
        self.delay = self._patch(run_competitor_analysis_task, "delay", Mock())

        app = FastAPI()
        app.include_router(router)

        def override_db():
            with self.Session() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_user_id] = lambda: USER
        self.client = TestClient(app)

    def _patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def add_customer(self, base_url):
        customer_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(id=customer_id, name="Klant", base_url=base_url, domain="klant.nl",
                                   created_by=USER, created_at=_now(), updated_at=_now()))
            db.commit()
        return customer_id

    def add_analysis(self, *, status="completed", created_at=None, updated_at=None, keywords=("seo bureau",),
                     customer_id=None, **fields):
        created_at = created_at or _now()
        analysis_id = str(uuid.uuid4())
        keyword_ids = []
        with self.Session() as db:
            db.add(CompetitorAnalysis(
                id=analysis_id, customer_website_id=customer_id or self.customer_id, created_by=USER,
                status=status, country="nl", top_n=10, modules=["serp", "onpage"], total_keywords=len(keywords),
                created_at=created_at, updated_at=updated_at or created_at, **fields,
            ))
            for index, keyword in enumerate(keywords):
                keyword_id = str(uuid.uuid4())
                keyword_ids.append(keyword_id)
                db.add(CompetitorAnalysisKeyword(
                    id=keyword_id, analysis_id=analysis_id, sort_order=index, keyword=keyword,
                    keyword_key=keyword.casefold(), target_url="https://klant.nl/seo/", status="pending",
                    created_at=created_at, updated_at=created_at,
                ))
            db.commit()
        return analysis_id, keyword_ids

    def add_page(self, analysis_id, keyword_id, url, **fields):
        page_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CompetitorAnalysisPage(
                id=page_id, keyword_id=keyword_id, analysis_id=analysis_id, url=url, url_key=url,
                created_at=_now(), updated_at=_now(), **fields,
            ))
            db.commit()
        return page_id

    def add_action(self, analysis_id, keyword_id, title, sort_order=0, **fields):
        action_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CompetitorAnalysisAction(
                id=action_id, keyword_id=keyword_id, analysis_id=analysis_id, title=title, sort_order=sort_order,
                created_at=_now(), updated_at=_now(), **fields,
            ))
            db.commit()
        return action_id

    def get_analysis(self, analysis_id):
        with self.Session() as db:
            return db.get(CompetitorAnalysis, analysis_id)


# --- starten -----------------------------------------------------------------------------

class StartAnalysisTest(_Base):
    def url(self, customer_id=None):
        return f"/api/competitor-analyses/customers/{customer_id or self.customer_id}/analyses"

    def payload(self, **overrides):
        body = {
            "keywords": [
                {"keyword": "  SEO   bureau ", "target_url": "www.klant.nl/seo/"},
                {"keyword": "linkbuilding", "target_url": ""},
                {"keyword": "webdesign", "target_url": "https://klant.nl/webdesign/"},
            ],
            "country": "NL",
            "top_n": 5,
            "exclude_aggregators": True,
            "modules": ["onpage", "serp", "authority", "topics"],
        }
        body.update(overrides)
        return body

    def test_start_creates_rows_stores_estimate_and_starts_task(self):
        with self.Session() as db:
            db.add(CustomerQuickWins(customer_website_id=self.customer_id, target="klant.nl", country="nl",
                                     rows=[{"keyword": "linkbuilding", "position": 12, "volume": 300,
                                            "url": "https://klant.nl/links/"}],
                                     units=24, fetched_at=_now(), created_at=_now(), updated_at=_now()))
            db.commit()
        response = self.client.post(self.url(), json=self.payload())
        self.assertEqual(response.status_code, 200, response.text)
        body = AnalysisDetail.model_validate(response.json())
        self.assertEqual(body.status, "pending")
        self.assertEqual((body.country, body.top_n, body.total_keywords), ("nl", 5, 3))
        self.assertEqual(body.modules, ["serp", "onpage", "topics", "authority"])
        self.assertEqual(body.created_by, USER)
        self.delay.assert_called_once_with(body.id)

        expected = estimate.estimate(keywords=3, top_n=5, own_urls=2,
                                     modules=["serp", "onpage", "topics", "authority"], ai_configured=True)
        self.assertEqual(body.estimate, expected)
        self.assertEqual(body.sources.ahrefs.state, "ok")
        self.assertEqual(body.sources.prt.state, "ok")
        self.assertEqual(body.sources.google.state, "skipped")
        # Geen betaalde Ahrefs-aanroep bij het starten (ook geen limits_and_usage).
        self.paid.assert_not_called()
        self.usage.assert_not_called()

        self.assertEqual([k.keyword for k in body.keywords], ["SEO bureau", "linkbuilding", "webdesign"])
        seo, links, web = body.keywords
        self.assertEqual((seo.target_url, seo.own_position, seo.volume, seo.status),
                         ("https://www.klant.nl/seo/", 6, 900, "pending"))
        self.assertEqual((links.target_url, links.own_position, links.volume), (None, 12, 300))
        self.assertEqual((web.own_position, web.volume), (None, None))

        with self.Session() as db:
            analysis = db.get(CompetitorAnalysis, body.id)
            self.assertEqual(Estimate.model_validate(analysis.estimate), expected)
            self.assertEqual(Sources.model_validate(analysis.sources).pagespeed.state,
                             "ok" if str(settings.pagespeed_api_key or "").strip() else "not_configured")
            rows = db.query(CompetitorAnalysisKeyword).order_by(CompetitorAnalysisKeyword.sort_order).all()
            self.assertEqual([(r.sort_order, r.keyword_key, r.own_position_source) for r in rows],
                             [(0, "seo bureau", "prt"), (1, "linkbuilding", "ahrefs"), (2, "webdesign", None)])

    def test_estimate_without_claude(self):
        self.claude_configured.return_value = False
        body = self.client.post(self.url(), json=self.payload()).json()
        self.assertEqual(body["estimate"]["ai_cost_eur"], 0.0)

    def test_prt_failure_does_not_block_start(self):
        self.organic.return_value = ("error", [], "Kapot")
        response = self.client.post(self.url(), json=self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sources"]["prt"], {"state": "error", "message": "Kapot"})
        self.assertIsNone(response.json()["keywords"][0]["own_position"])

    def assert_400(self, payload, detail, customer_id=None):
        response = self.client.post(self.url(customer_id), json=payload)
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], detail)
        self.delay.assert_not_called()

    def test_400_without_ahrefs(self):
        self.ahrefs_configured.return_value = False
        self.assert_400(self.payload(), router_module.MESSAGES["ahrefs"])

    def test_400_too_many_keywords(self):
        maximum = settings.competitor_analysis_max_keywords
        keywords = [{"keyword": f"zoekwoord {i}"} for i in range(maximum + 1)]
        self.assert_400(self.payload(keywords=keywords),
                        f"Kies maximaal {maximum} zoekwoorden per analyse (nu {maximum + 1}).")

    def test_400_duplicate_keywords(self):
        keywords = [{"keyword": "SEO bureau"}, {"keyword": "seo  BUREAU"}]
        self.assert_400(self.payload(keywords=keywords), 'Het zoekwoord "seo BUREAU" staat er meer dan één keer in.')

    def test_400_target_off_domain(self):
        keywords = [{"keyword": "seo", "target_url": "https://concurrent.nl/seo/"}]
        self.assert_400(self.payload(keywords=keywords),
                        'De doelpagina "https://concurrent.nl/seo/" ligt niet op het domein van de klant (klant.nl).')
        keywords = [{"keyword": "seo", "target_url": "mailto:jan@klant.nl"}]
        self.assert_400(self.payload(keywords=keywords), 'De doelpagina "mailto:jan@klant.nl" is geen geldig webadres.')

    def test_400_target_for_customer_without_site(self):
        customer_id = self.add_customer("")
        keywords = [{"keyword": "seo", "target_url": "https://klant.nl/seo/"}]
        self.assert_400(self.payload(keywords=keywords), router_module.MESSAGES["no_site"], customer_id)
        # Zonder doelpagina kan het wel.
        response = self.client.post(self.url(customer_id), json=self.payload(keywords=[{"keyword": "seo"}]))
        self.assertEqual(response.status_code, 200)

    def test_422_on_invalid_request(self):
        for payload in (self.payload(keywords=[]), self.payload(top_n=7), self.payload(country="n1"),
                        self.payload(modules=[])):
            self.assertEqual(self.client.post(self.url(), json=payload).status_code, 422)

    def test_409_while_another_analysis_runs(self):
        self.add_analysis(status="fetching", updated_at=_now() - timedelta(minutes=5))
        response = self.client.post(self.url(), json=self.payload())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], router_module.MESSAGES["running"])
        self.delay.assert_not_called()

    def test_running_analysis_of_other_customer_does_not_block(self):
        self.add_analysis(status="serp", customer_id=self.add_customer("https://ander.nl"))
        self.assertEqual(self.client.post(self.url(), json=self.payload()).status_code, 200)

    def test_stale_run_is_recovered_before_starting(self):
        stale_id, _ = self.add_analysis(status="fetching", updated_at=_now() - timedelta(minutes=45))
        response = self.client.post(self.url(), json=self.payload())
        self.assertEqual(response.status_code, 200)
        stale = self.get_analysis(stale_id)
        self.assertEqual((stale.status, stale.error_message), ("failed", recovery.INTERRUPTED_RUN_MESSAGE))

    def test_queue_unreachable_marks_run_failed(self):
        self.delay.side_effect = ConnectionError("redis weg")
        with self.assertLogs(router_module.logger, "ERROR"):
            response = self.client.post(self.url(), json=self.payload())
        self.assertEqual(response.status_code, 503)
        with self.Session() as db:
            analysis = db.query(CompetitorAnalysis).one()
            self.assertEqual(analysis.status, "failed")
        # De mislukte run blokkeert een volgende poging niet.
        self.delay.side_effect = None
        self.assertEqual(self.client.post(self.url(), json=self.payload()).status_code, 200)

    def test_unknown_customer_is_404(self):
        response = self.client.post(self.url("onbekend"), json=self.payload())
        self.assertEqual(response.status_code, 404)


# --- lijst, volgen en herstel ------------------------------------------------------------

class ListAndDetailTest(_Base):
    def test_list_newest_first_with_limit(self):
        old_id, _ = self.add_analysis(created_at=_now() - timedelta(days=2), keywords=("a", "b"),
                                      completed_at=_now() - timedelta(days=2))
        new_id, _ = self.add_analysis(status="serp", created_at=_now() - timedelta(minutes=1))
        self.add_analysis(customer_id=self.add_customer("https://ander.nl"))
        url = f"/api/competitor-analyses/customers/{self.customer_id}/analyses"
        items = self.client.get(url).json()["items"]
        self.assertEqual([i["id"] for i in items], [new_id, old_id])
        self.assertEqual(items[1]["keywords"], ["a", "b"])
        self.assertEqual(items[1]["total_keywords"], 2)
        self.assertIsNotNone(items[1]["completed_at"])
        self.assertEqual([i["id"] for i in self.client.get(url, params={"limit": 1}).json()["items"]], [new_id])
        self.assertEqual(self.client.get(url, params={"limit": 0}).status_code, 422)
        self.assertEqual(self.client.get("/api/competitor-analyses/customers/onbekend/analyses").status_code, 404)

    def test_list_recovers_stale_runs(self):
        stale_id, _ = self.add_analysis(status="pending", created_at=_now() - timedelta(minutes=70))
        items = self.client.get(f"/api/competitor-analyses/customers/{self.customer_id}/analyses").json()["items"]
        self.assertEqual(items[0]["status"], "failed")

    def test_detail_during_run(self):
        analysis_id, _ = self.add_analysis(
            status="fetching", total_pages=12, fetched_pages=4, failed_pages=1, done_keywords=0,
            sources={"ahrefs": {"state": "ok"}}, estimate=None, ai_usage=None,
        )
        response = self.client.get(f"/api/competitor-analyses/analyses/{analysis_id}")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["status"], body["total_pages"], body["fetched_pages"], body["failed_pages"]),
                         ("fetching", 12, 4, 1))
        self.assertEqual(body["sources"]["ahrefs"]["state"], "ok")
        self.assertEqual(body["sources"]["claude"]["state"], "skipped")
        self.assertIsNone(body["estimate"])
        self.assertEqual(body["warnings"], [])
        self.assertEqual(body["keywords"][0]["status"], "pending")

    def test_detail_after_run(self):
        analysis_id, _ = self.add_analysis(
            status="completed", completed_at=_now(), ahrefs_units=420, done_keywords=1,
            ai_usage={"calls": 2, "input_tokens": 1000, "output_tokens": 500, "cost_usd": 0.12},
            estimate={"pages": 11, "seconds": 120, "ahrefs_units": 500, "ai_cost_eur": 0.3},
            warnings=["PageSpeed niet op tijd"], sources="kapot",
        )
        body = self.client.get(f"/api/competitor-analyses/analyses/{analysis_id}").json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["ai_usage"]["calls"], 2)
        self.assertEqual(body["estimate"]["pages"], 11)
        self.assertEqual(body["warnings"], ["PageSpeed niet op tijd"])
        self.assertEqual(body["sources"]["ahrefs"]["state"], "skipped")  # ongeldige kolom: standaardwaarden

    def test_detail_recovers_stale_run(self):
        analysis_id, _ = self.add_analysis(status="analyzing", updated_at=_now() - timedelta(minutes=31))
        body = self.client.get(f"/api/competitor-analyses/analyses/{analysis_id}").json()
        self.assertEqual((body["status"], body["error_message"]), ("failed", recovery.INTERRUPTED_RUN_MESSAGE))
        self.assertEqual(self.get_analysis(analysis_id).status, "failed")

    def test_unknown_analysis_is_404(self):
        self.assertEqual(self.client.get("/api/competitor-analyses/analyses/onbekend").status_code, 404)


class RecoveryTest(_Base):
    def test_rules(self):
        now = _now()
        cases = [
            ("pending", now - timedelta(minutes=64), now - timedelta(minutes=64), False),
            ("pending", now - timedelta(minutes=66), now, True),
            ("serp", now - timedelta(hours=3), now - timedelta(minutes=29), False),
            ("serp", now, now - timedelta(minutes=31), True),
            ("completed", now - timedelta(days=3), now - timedelta(days=3), False),
            ("canceled", now - timedelta(days=3), now - timedelta(days=3), False),
        ]
        for status, created_at, updated_at, stale in cases:
            analysis_id, _ = self.add_analysis(status=status, created_at=created_at, updated_at=updated_at)
            with self.Session() as db:
                analysis = db.get(CompetitorAnalysis, analysis_id)
                self.assertEqual(recovery.recover_stale_run(db, analysis, now=now), stale, status)
            self.assertEqual(self.get_analysis(analysis_id).status, "failed" if stale else status)

    def test_naive_timestamps_count_as_utc(self):
        analysis_id, _ = self.add_analysis(status="fetching")
        with self.Session() as db:
            analysis = db.get(CompetitorAnalysis, analysis_id)
            analysis.updated_at = datetime(2026, 1, 1, 12, 0)  # SQLite levert naïeve tijden
            self.assertTrue(recovery.is_stale(analysis, now=datetime(2026, 1, 1, 12, 31, tzinfo=timezone.utc)))


# --- resultaat per zoekwoord -------------------------------------------------------------

class KeywordDetailTest(_Base):
    def setUp(self):
        super().setUp()
        self.analysis_id, (self.keyword_id,) = self.add_analysis(status="analyzing")

    def url(self, keyword_id=None, analysis_id=None):
        return (f"/api/competitor-analyses/analyses/{analysis_id or self.analysis_id}"
                f"/keywords/{keyword_id or self.keyword_id}")

    def fill(self):
        a, k = self.analysis_id, self.keyword_id
        with self.Session() as db:
            keyword = db.get(CompetitorAnalysisKeyword, k)
            keyword.status = "completed"
            keyword.own_position = 14
            keyword.own_position_source = "prt"
            keyword.volume, keyword.kd = 900, 31
            keyword.intents = ["commercial"]
            keyword.serp_features = ["ai_overview", "question"]
            keyword.serp_date = "2026-11-20T00:00:00Z"
            keyword.ai_state = "ok"
            keyword.serp_summary = "Vooral dienstpagina's."
            keyword.paa = {"state": "ok", "questions": ["Wat kost een SEO-bureau?"]}
            keyword.ai_overview = {"state": "ok", "sources": [{"domain": "a.nl", "url": "https://a.nl/x"}],
                                   "own_cited": False}
            keyword.missing_topics = [{"topic": "prijzen", "covered": 2, "total": 3}, {"onzin": True}, "tekst"]
            db.commit()
        self.add_page(a, k, "https://a.nl/seo", position=3, domain="a.nl", page_type="dienst", fetch_status="ok",
                      onpage=_onpage(800, 5), refdomains=20, domain_rating=40, lcp_ms=3000)
        self.add_page(a, k, "https://b.nl/seo", position=1, domain="b.nl", page_type="dienst", fetch_status="ok",
                      onpage=_onpage(1200, 8, faq=True, schema=["Service"]), refdomains=40, domain_rating=50,
                      lcp_ms=2000, eeat={"team": True, "reviews": True})
        self.add_page(a, k, "https://c.nl/seo", position=2, fetch_status="ok",
                      onpage=_onpage(1000, 6, faq=True, schema=["FAQPage", "WebPage"]), refdomains=30,
                      domain_rating=45, cwv={"lcp_ms": 2400, "source": "lab"})
        self.excluded = self.add_page(
            a, k, "https://vergelijk.nl/seo", position=4, page_type="vergelijker", is_excluded=True,
            exclude_reason="aggregator", fetch_status="ok", onpage=_onpage(5000, 30), refdomains=900,
            domain_rating=90, lcp_ms=1000)
        self.unreadable = self.add_page(
            a, k, "https://js.nl/seo", position=5, fetch_status="ok", onpage=_onpage(20, 0), refdomains=10,
            domain_rating=30, lcp_ms=1500)
        self.blocked = self.add_page(
            a, k, "https://blok.nl/seo", position=6, fetch_status="blocked", fetch_error="403",
            refdomains=25, domain_rating=35, cwv={"error": "niet op tijd gemeten"}, onpage={"word_count": "veel"})
        self.own = self.add_page(
            a, k, "https://klant.nl/seo/", is_own=True, fetch_status="ok",
            onpage=_onpage(400, 2, schema=["WebPage"]), refdomains=5, domain_rating=38, lcp_ms=4000)
        self.add_action(a, k, "Tweede", sort_order=1, impact="middel", effort="laag", category="onpage")
        self.add_action(a, k, "Eerste", sort_order=0, impact="hoog", effort="vreemd", category="onbekend",
                        done=True, done_by=USER, done_at=_now())

    def test_full_result_with_median_and_flags(self):
        self.fill()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200, response.text)
        body = KeywordDetail.model_validate(response.json())
        self.assertEqual((body.status, body.own_position, body.own_position_source, body.volume, body.kd),
                         ("completed", 14, "prt", 900, 31))
        self.assertEqual(body.intents, ["commercial"])
        self.assertEqual(body.serp_features, ["ai_overview", "question"])

        # Concurrenten op positie, zonder de eigen pagina.
        self.assertEqual([p.position for p in body.pages], [1, 2, 3, 4, 5, 6])
        by_id = {p.id: p for p in body.pages}
        self.assertTrue(by_id[self.excluded].is_excluded)
        self.assertEqual(by_id[self.excluded].exclude_reason, "aggregator")
        self.assertTrue(by_id[self.unreadable].unreadable)
        self.assertEqual(by_id[self.unreadable].words, 20)
        blocked = by_id[self.blocked]
        self.assertEqual((blocked.fetch_status, blocked.fetch_error, blocked.words, blocked.lcp_ms, blocked.lcp_error),
                         ("blocked", "403", None, None, "niet op tijd gemeten"))
        self.assertFalse(blocked.unreadable)
        first = body.pages[0]
        self.assertEqual((first.domain, first.page_type, first.words, first.h2_count, first.has_faq),
                         ("b.nl", "dienst", 1200, 8, True))
        self.assertEqual(first.schema_types, ["Service"])
        self.assertTrue(first.eeat.team and first.eeat.reviews and not first.eeat.cases)
        self.assertEqual(body.pages[1].domain, "c.nl")  # uit de URL
        self.assertEqual(body.pages[1].lcp_ms, 2400)  # uit `cwv`

        # Mediaan: on-page over de drie leesbare, niet-uitgesloten concurrenten; DR/RD/LCP over alle
        # niet-uitgesloten concurrenten met een waarde.
        median = body.median
        self.assertEqual((median.words, median.h2_count, median.total), (1000, 6, 3))
        self.assertEqual((median.faq_count, median.schema_count), (2, 2))
        self.assertEqual((median.refdomains, median.domain_rating, median.lcp_ms), (25, 40, 2200))

        own = body.own
        self.assertEqual((own.id, own.url, own.words, own.position), (self.own, "https://klant.nl/seo/", 400, None))
        self.assertEqual(set(own.flags), set(FLAG_METRICS))
        self.assertEqual({m for m, red in own.flags.items() if red},
                         {"words", "h2_count", "faq", "schema", "refdomains", "lcp_ms"})
        self.assertFalse(own.flags["domain_rating"])

        # Verbeterpunten op sort_order; onbekende waarden worden leeg; naam van de afvinker.
        self.assertEqual([a.title for a in body.actions], ["Eerste", "Tweede"])
        first_action = body.actions[0]
        self.assertEqual((first_action.impact, first_action.effort, first_action.category), ("hoog", None, None))
        self.assertEqual((first_action.done, first_action.done_by_name), (True, "jan"))
        self.assertEqual(body.actions[1].category, "onpage")

        self.assertEqual([(t.topic, t.covered, t.total) for t in body.missing_topics], [("prijzen", 2, 3)])
        self.assertEqual(body.paa.questions, ["Wat kost een SEO-bureau?"])
        self.assertEqual(body.ai_overview.sources[0].domain, "a.nl")
        self.assertIs(body.ai_overview.own_cited, False)

    def test_empty_run_gives_valid_answer(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "pending")
        self.assertEqual((body["pages"], body["own"], body["actions"], body["missing_topics"]), ([], None, [], []))
        self.assertEqual((body["paa"], body["ai_overview"], body["ai_state"]), (None, None, None))
        self.assertEqual(body["median"]["total"], 0)
        self.assertIsNone(body["median"]["words"])
        self.assertEqual((body["intents"], body["serp_features"]), ([], []))

    def test_halfway_run_without_onpage_and_page_type(self):
        a, k = self.analysis_id, self.keyword_id
        self.add_page(a, k, "https://a.nl/", position=1, refdomains=10, domain_rating=20)
        self.add_page(a, k, "https://klant.nl/seo/", is_own=True)
        body = self.client.get(self.url()).json()
        page = body["pages"][0]
        self.assertEqual((page["fetch_status"], page["words"], page["page_type"], page["unreadable"]),
                         (None, None, None, False))
        self.assertEqual(body["own"]["flags"], {m: False for m in FLAG_METRICS})

    def test_new_page_has_no_own_row(self):
        with self.Session() as db:
            db.get(CompetitorAnalysisKeyword, self.keyword_id).target_url = None
            db.commit()
        body = self.client.get(self.url()).json()
        self.assertIsNone(body["target_url"])
        self.assertIsNone(body["own"])

    def test_keyword_of_other_analysis_is_404(self):
        other_id, (other_keyword,) = self.add_analysis()
        response = self.client.get(self.url(keyword_id=other_keyword))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], router_module.NOT_FOUND_KEYWORD)
        self.assertEqual(self.client.get(self.url(keyword_id="onbekend")).status_code, 404)
        self.assertEqual(self.client.get(self.url(analysis_id="onbekend")).status_code, 404)
        self.assertEqual(self.client.get(self.url(keyword_id=other_keyword, analysis_id=other_id)).status_code, 200)


# --- annuleren en afvinken ---------------------------------------------------------------

class CancelTest(_Base):
    def test_cancel_active_run(self):
        analysis_id, _ = self.add_analysis(status="serp")
        response = self.client.post(f"/api/competitor-analyses/analyses/{analysis_id}/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "canceled")
        self.assertEqual(self.get_analysis(analysis_id).status, "canceled")

    def test_cancel_finished_run_is_409_and_unchanged(self):
        for status in ("completed", "failed", "canceled"):
            analysis_id, _ = self.add_analysis(status=status)
            response = self.client.post(f"/api/competitor-analyses/analyses/{analysis_id}/cancel")
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"], router_module.MESSAGES["cancel_final"].format(status=status))
            self.assertEqual(self.get_analysis(analysis_id).status, status)

    def test_cancel_unknown_is_404(self):
        self.assertEqual(self.client.post("/api/competitor-analyses/analyses/onbekend/cancel").status_code, 404)


class ActionTest(_Base):
    def test_check_and_uncheck(self):
        analysis_id, (keyword_id,) = self.add_analysis()
        action_id = self.add_action(analysis_id, keyword_id, "Voeg een FAQ toe", impact="hoog", effort="laag",
                                    category="onpage", description="Vijf vragen.")
        url = f"/api/competitor-analyses/actions/{action_id}"

        response = self.client.patch(url, json={"done": True})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual((body["id"], body["done"], body["done_by_name"], body["title"], body["impact"]),
                         (action_id, True, "jan", "Voeg een FAQ toe", "hoog"))
        self.assertIsNotNone(body["done_at"])
        with self.Session() as db:
            action = db.get(CompetitorAnalysisAction, action_id)
            self.assertEqual((action.done, action.done_by), (True, USER))
            first_done_at = action.done_at

        # Nogmaals afvinken laat het oorspronkelijke tijdstip staan.
        self.client.patch(url, json={"done": True})
        with self.Session() as db:
            self.assertEqual(db.get(CompetitorAnalysisAction, action_id).done_at, first_done_at)

        body = self.client.patch(url, json={"done": False}).json()
        self.assertEqual((body["done"], body["done_by_name"], body["done_at"]), (False, None, None))
        with self.Session() as db:
            action = db.get(CompetitorAnalysisAction, action_id)
            self.assertEqual((action.done, action.done_by, action.done_at), (False, None, None))

    def test_unknown_action_and_invalid_body(self):
        self.assertEqual(self.client.patch("/api/competitor-analyses/actions/onbekend", json={"done": True}).status_code,
                         404)
        analysis_id, (keyword_id,) = self.add_analysis()
        action_id = self.add_action(analysis_id, keyword_id, "X")
        self.assertEqual(self.client.patch(f"/api/competitor-analyses/actions/{action_id}", json={}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
