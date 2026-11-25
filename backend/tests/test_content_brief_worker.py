"""De taak van de content brief (features/competitor_analysis/worker/brief.py) en het bewaren van
de volledige onderwerpenlijst door de analyse (`_save_insights`).

SQLite in een tijdelijke map; `SessionLocal` is vervangen en `parse_structured` van de agent
ook: er gaat niets naar Anthropic. De taak draait direct via `.run(...)`.
"""
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    CompetitorAnalysis,
    CompetitorAnalysisAction,
    CompetitorAnalysisKeyword,
    CompetitorAnalysisPage,
    ContentBrief,
    CustomerWebsite,
    LaunchSitemapSnapshot,
)
from app.features.competitor_analysis.schemas import AiUsage, Sources, TopicCoverage
from app.features.competitor_analysis.services import brief_agent as agent
from app.features.competitor_analysis.services.insights import KeywordInsights, TopicResult
from app.features.competitor_analysis.worker import analysis
from app.features.competitor_analysis.worker import brief as worker
from app.services.anthropic import client as anthropic_client
from app.services.anthropic.client import AnthropicResult, AnthropicServiceError

USER = "user-1"
USAGE = {"input_tokens": 10_000, "output_tokens": 4_000}


def _now():
    return datetime.now(timezone.utc)


def _onpage(words, headings=("Prijzen", "Werkwijze")):
    return {"title": "T", "meta_description": "M", "h1": "H", "h2_count": len(headings),
            "headings": [{"level": 2, "text": h} for h in headings], "word_count": words, "has_faq": False,
            "schema_types": []}


def brief_out():
    return agent.BriefOut(
        goal_intent=["Bureau kiezen"], title="SEO bureau | Klant", meta_description="Meta.",
        outline=[agent.OutlineOut(level="h1", text="SEO bureau"), agent.OutlineOut(level="h2", text="Werkwijze")],
        word_count=50, internal_links=["L1", "L7"], schema_types=["Service"],
    )


def concept_out(words=50, note=None):
    return agent.ConceptOut(sections=[
        agent.SectionOut(level="h1", heading="SEO bureau", body=" ".join(["woord"] * (words - 2)),
                         covers=["T1", "T2", "V1"], review_note=note),
    ])


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        engine = create_engine(f"sqlite:///{self.tmp.name}/test.db", connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self._patch(worker, "SessionLocal", self.Session)
        self._patch(analysis, "SessionLocal", self.Session)
        self._patch(anthropic_client, "is_configured", Mock(return_value=True))

        self.customer_id = str(uuid.uuid4())
        self.analysis_id = str(uuid.uuid4())
        self.keyword_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(id=self.customer_id, name="Klant BV", base_url="https://www.klant.nl/",
                                   domain="klant.nl", seo_goals="Meer leads", tone_of_voice="Nuchter.",
                                   form_of_address="je", created_by=USER, created_at=_now(), updated_at=_now()))
            db.add(CompetitorAnalysis(id=self.analysis_id, customer_website_id=self.customer_id, created_by=USER,
                                      status="completed", country="nl", top_n=10, modules=["topics"],
                                      created_at=_now(), updated_at=_now(), completed_at=_now()))
            db.add(CompetitorAnalysisKeyword(
                id=self.keyword_id, analysis_id=self.analysis_id, keyword="seo bureau", keyword_key="seo bureau",
                target_url="https://klant.nl/seo/", status="completed", ai_state="ok", volume=900,
                serp_summary="Dienstpagina's.", search_intent="Bureau kiezen.",
                paa={"state": "ok", "questions": ["Wat kost SEO?"]},
                topics=[{"topic": "Prijzen", "kind": "topic", "covered": 3, "total": 3, "own_covers": False},
                        {"topic": "Werkwijze", "kind": "topic", "covered": 2, "total": 3, "own_covers": True}],
                missing_topics=[{"topic": "Prijzen", "covered": 3, "total": 3}],
                created_at=_now(), updated_at=_now()))
            for position, words in ((1, 1200), (2, 1000), (3, 900)):
                db.add(CompetitorAnalysisPage(
                    id=str(uuid.uuid4()), keyword_id=self.keyword_id, analysis_id=self.analysis_id,
                    position=position, url=f"https://c{position}.nl/seo", url_key=f"c{position}.nl/seo",
                    fetch_status="ok", onpage=_onpage(words), created_at=_now(), updated_at=_now()))
            db.add(CompetitorAnalysisPage(
                id=str(uuid.uuid4()), keyword_id=self.keyword_id, analysis_id=self.analysis_id, is_own=True,
                url="https://klant.nl/seo/", url_key="klant.nl/seo", fetch_status="ok",
                onpage={"word_count": "kapot"}, created_at=_now(), updated_at=_now()))
            db.add(CompetitorAnalysisAction(
                id=str(uuid.uuid4()), keyword_id=self.keyword_id, analysis_id=self.analysis_id, sort_order=0,
                title="Voeg prijzen toe", description="Concurrenten tonen prijzen.", created_at=_now(),
                updated_at=_now()))
            db.add(LaunchSitemapSnapshot(customer_website_id=self.customer_id, entries={
                "klant.nl/seo-audit": {"url": "https://klant.nl/seo-audit/", "lastmod": None},
                "klant.nl/seo": {"url": "https://klant.nl/seo/", "lastmod": None},
            }, recent_changes=[], created_at=_now(), updated_at=_now()))
            db.commit()

    def _patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def add_brief(self, status="pending", **fields):
        brief_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(ContentBrief(id=brief_id, keyword_id=self.keyword_id, analysis_id=self.analysis_id,
                                customer_website_id=self.customer_id, status=status, created_by=USER,
                                created_at=_now(), updated_at=_now(), **fields))
            db.commit()
        return brief_id

    def get(self, brief_id):
        with self.Session() as db:
            return db.get(ContentBrief, brief_id)

    def replies(self, *results):
        """`parse_structured` geeft na elkaar deze antwoorden en noteert de status op dat moment."""
        self.seen_status = []
        self.prompts = []
        queue = list(results)

        def fake(**kwargs):
            self.prompts.append(kwargs)
            with self.Session() as db:
                self.seen_status.append(db.query(ContentBrief.status).scalar())
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        return self._patch(agent.claude, "parse_structured", Mock(side_effect=fake))


class FullRunTest(_Base):
    def test_pending_to_completed_with_usage_and_checks(self):
        brief_id = self.add_brief()
        self.replies(AnthropicResult(parsed=brief_out(), usage=USAGE, model="claude-sonnet-5-5"),
                     AnthropicResult(parsed=concept_out(), usage=USAGE, model="claude-sonnet-5-5"))
        worker.run_content_brief_task.run(brief_id)

        self.assertEqual(self.seen_status, ["brief", "concept"])
        row = self.get(brief_id)
        self.assertEqual((row.status, row.error_message, row.model), ("completed", None, "claude-sonnet-5-5"))
        self.assertIsNotNone(row.completed_at)
        usage = AiUsage.model_validate(row.ai_usage)
        # Sonnet 5.5: $2 / $10 per miljoen tokens, twee aanroepen.
        self.assertEqual((usage.calls, usage.input_tokens, usage.output_tokens), (2, 20_000, 8_000))
        self.assertAlmostEqual(usage.cost_usd, 2 * (0.02 + 0.04))

        self.assertEqual(row.brief["internal_links"], ["/seo-audit/"])  # L7 bestaat niet; doelpagina niet
        self.assertEqual((row.brief["tone_of_voice"], row.brief["form_of_address"]), ("Nuchter.", "je"))
        self.assertEqual(row.brief["word_count"], 1000)  # 50 is te laag: mediaan van de concurrenten
        self.assertEqual(row.concept["version"], 1)
        self.assertEqual(row.concept["word_count"], 50)
        checks = {c["key"]: c for c in row.concept["checks"]}
        self.assertEqual(checks["topics"]["label"], "Onderwerpen 2/2")
        self.assertEqual(checks["questions"]["label"], "PAA-vragen 1/1")
        self.assertTrue(checks["keyword"]["ok"])
        self.assertFalse(checks["length"]["ok"])

        # Invoer uit de database: onderwerpen, PAA, klant, sitemap, eigen pagina onleesbaar
        # (ongeldige on-page wordt leeg), en het model van de agent.
        first = self.prompts[0]
        self.assertEqual(first["model"], "claude-sonnet-5-5")
        self.assertIn("- T1 [onderwerp] Prijzen", first["prompt"])
        self.assertIn("- V1: Wat kost SEO?", first["prompt"])
        self.assertIn("SEO-doelen: Meer leads", first["prompt"])
        self.assertIn("L1: /seo-audit/", first["prompt"])
        self.assertIn("- Voeg prijzen toe: Concurrenten tonen prijzen.", first["prompt"])
        self.assertIn("Eigen pagina niet leesbaar", first["system"])
        self.assertIn("Nuchter.", first["system"])
        self.assertIn("SEO bureau | Klant", self.prompts[1]["prompt"])

    def test_old_analysis_without_topics_and_without_sitemap(self):
        with self.Session() as db:
            db.get(CompetitorAnalysisKeyword, self.keyword_id).topics = None
            db.query(LaunchSitemapSnapshot).delete()
            db.commit()
        brief_id = self.add_brief()
        self.replies(AnthropicResult(parsed=brief_out(), usage=USAGE, model="claude-sonnet-5-5"),
                     AnthropicResult(parsed=concept_out(), usage=USAGE, model="claude-sonnet-5-5"))
        worker.run_content_brief_task.run(brief_id)
        row = self.get(brief_id)
        self.assertEqual(row.status, "completed")
        self.assertEqual(row.brief["internal_links"], [])
        self.assertIn("Alleen de onderwerpen die de eigen pagina mist", self.prompts[0]["prompt"])
        self.assertIn("Geen sitemap van de klant bekend", self.prompts[0]["prompt"])
        checks = {c["key"]: c for c in row.concept["checks"]}
        self.assertEqual(checks["topics"]["label"], "Onderwerpen 1/1")

    def test_customer_profile_reaches_both_prompts(self):
        with self.Session() as db:
            db.get(CustomerWebsite, self.customer_id).profile = {
                "usps": ["Maandelijks opzegbaar", "maandelijks opzegbaar"],
                "services": [{"name": "SEO-traject", "price": "vanaf € 750 per maand"}],
                "avoid_words": ["ontzorgen"], "example_urls": ["https://voorbeeld.nl/"], "onbekend": True,
            }
            db.commit()
        brief_id = self.add_brief()
        self.replies(AnthropicResult(parsed=brief_out(), usage=USAGE, model="claude-sonnet-5-5"),
                     AnthropicResult(parsed=concept_out(), usage=USAGE, model="claude-sonnet-5-5"))
        worker.run_content_brief_task.run(brief_id)
        self.assertEqual(self.get(brief_id).status, "completed")
        for call in self.prompts:
            self.assertEqual(call["prompt"].count("- Maandelijks opzegbaar"), 1)
            self.assertIn("- SEO-traject: vanaf € 750 per maand", call["prompt"])
            self.assertIn("Gebruik deze woorden nooit: ontzorgen.", call["system"])
            self.assertIn("Noem alleen bedragen", call["system"])
            self.assertNotIn("voorbeeld.nl", call["prompt"] + call["system"])

    def test_broken_profile_is_ignored(self):
        with self.Session() as db:
            db.get(CustomerWebsite, self.customer_id).profile = ["geen", "object"]
            db.commit()
        brief_id = self.add_brief()
        self.replies(AnthropicResult(parsed=brief_out(), usage=USAGE, model="claude-sonnet-5-5"),
                     AnthropicResult(parsed=concept_out(), usage=USAGE, model="claude-sonnet-5-5"))
        worker.run_content_brief_task.run(brief_id)
        self.assertEqual(self.get(brief_id).status, "completed")
        self.assertNotIn("USP's", self.prompts[0]["prompt"])

    def test_not_pending_does_nothing(self):
        brief_id = self.add_brief(status="completed")
        parse = self.replies()
        worker.run_content_brief_task.run(brief_id)
        parse.assert_not_called()
        self.assertEqual(self.get(brief_id).status, "completed")
        worker.run_content_brief_task.run("bestaat-niet")


class ConceptOnlyTest(_Base):
    def existing(self, status="pending"):
        return self.add_brief(
            status=status,
            brief=agent.Brief(goal_intent=["Doel"], title="SEO bureau | Klant", meta_description="M",
                              outline=[], word_count=50).model_dump(mode="json"),
            concept={"version": 2, "word_count": 10, "sections": [], "checks": []},
            model="claude-sonnet-5-5",
            ai_usage={"calls": 2, "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.5},
        )

    def test_regenerate_increments_version_and_keeps_brief(self):
        brief_id = self.existing()
        self.replies(AnthropicResult(parsed=concept_out(), usage=USAGE, model="claude-sonnet-5"))
        worker.run_content_brief_task.run(brief_id, concept_only=True)
        self.assertEqual(self.seen_status, ["concept"])
        row = self.get(brief_id)
        self.assertEqual((row.status, row.model), ("completed", "claude-sonnet-5"))
        self.assertEqual(row.brief["title"], "SEO bureau | Klant")
        self.assertEqual(row.concept["version"], 3)
        usage = AiUsage.model_validate(row.ai_usage)
        self.assertEqual((usage.calls, usage.input_tokens), (3, 10_100))
        self.assertAlmostEqual(usage.cost_usd, 0.5 + 0.02 + 0.04)
        self.assertTrue({c["key"]: c for c in row.concept["checks"]}["length"]["ok"])

    def test_failed_concept_keeps_previous_concept(self):
        brief_id = self.existing()
        self.replies(AnthropicServiceError("Timeout bij wachten op Claude.", "timeout"))
        worker.run_content_brief_task.run(brief_id, concept_only=True)
        row = self.get(brief_id)
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.error_message, "Claude gaf een fout: Timeout bij wachten op Claude.")
        self.assertEqual(row.concept["version"], 2)
        self.assertEqual(row.ai_usage["calls"], 2)

    def test_pending_with_existing_brief_resumes_at_concept(self):
        brief_id = self.existing()
        self.replies(AnthropicResult(parsed=concept_out(), usage=USAGE, model="claude-sonnet-5-5"))
        worker.run_content_brief_task.run(brief_id)  # zonder concept_only: brief staat er al
        self.assertEqual(self.seen_status, ["concept"])
        self.assertEqual(self.get(brief_id).status, "completed")

    def test_concept_only_without_brief_fails(self):
        brief_id = self.add_brief()
        parse = self.replies()
        worker.run_content_brief_task.run(brief_id, concept_only=True)
        parse.assert_not_called()
        row = self.get(brief_id)
        self.assertEqual((row.status, row.error_message), ("failed", worker.NO_BRIEF_MESSAGE))


class FailureTest(_Base):
    def test_concept_failure_after_brief_keeps_brief_and_usage(self):
        brief_id = self.add_brief()
        self.replies(AnthropicResult(parsed=brief_out(), usage=USAGE, model="claude-sonnet-5-5"),
                     AnthropicServiceError("Claude weigerde dit verzoek.", "refusal"))
        worker.run_content_brief_task.run(brief_id)
        row = self.get(brief_id)
        self.assertEqual(row.status, "failed")
        self.assertIn("Claude weigerde", row.error_message)
        self.assertEqual(row.brief["title"], "SEO bureau | Klant")
        self.assertIsNone(row.concept)
        self.assertEqual(row.ai_usage["calls"], 1)

    def test_not_configured(self):
        self._patch(anthropic_client, "is_configured", Mock(return_value=False))
        brief_id = self.add_brief()
        worker.run_content_brief_task.run(brief_id)
        row = self.get(brief_id)
        self.assertEqual(row.status, "failed")
        self.assertIn("ANTHROPIC_API_KEY", row.error_message)

    def test_unexpected_error_and_timeout(self):
        brief_id = self.add_brief()
        self.replies(ValueError("kapot"))
        with self.assertLogs(worker.logger, "ERROR"):
            worker.run_content_brief_task.run(brief_id)
        self.assertEqual(self.get(brief_id).error_message,
                         "Het schrijven is gestopt door een interne fout (ValueError).")

        from celery.exceptions import SoftTimeLimitExceeded

        brief_id2 = str(uuid.uuid4())
        with self.Session() as db:
            db.query(ContentBrief).delete()
            db.add(ContentBrief(id=brief_id2, keyword_id=self.keyword_id, analysis_id=self.analysis_id,
                                customer_website_id=self.customer_id, status="pending", created_by=USER,
                                created_at=_now(), updated_at=_now()))
            db.commit()
        self.replies(SoftTimeLimitExceeded())
        worker.run_content_brief_task.run(brief_id2)
        self.assertEqual((self.get(brief_id2).status, self.get(brief_id2).error_message),
                         ("failed", worker.TIMEOUT_MESSAGE))

    def test_task_registration(self):
        self.assertEqual(worker.run_content_brief_task.name, "app.worker.tasks.run_content_brief_task")
        self.assertEqual((worker.run_content_brief_task.soft_time_limit, worker.run_content_brief_task.time_limit),
                         (540, 600))
        from app.worker import tasks
        from app.worker.celery_app import celery_app

        self.assertIs(tasks.run_content_brief_task, worker.run_content_brief_task)
        self.assertIn("run_content_brief_task", tasks.__all__)
        self.assertEqual(celery_app.conf.task_routes["app.worker.tasks.run_content_brief_task"], {"queue": "default"})


class SaveTopicsTest(_Base):
    def test_save_insights_stores_full_topic_list(self):
        keyword = analysis._Keyword(id=self.keyword_id, keyword="seo bureau", target_url=None, own_position=None,
                                    volume=None)
        run = analysis._Run(analysis_id=self.analysis_id, country="nl", top_n=10, exclude_aggregators=True,
                            modules=["topics"], customer_root=None, customer_domain=None, keywords=[keyword],
                            sources=Sources(), warnings=[])
        with self.Session() as db:
            db.get(CompetitorAnalysis, self.analysis_id).status = "analyzing"
            db.commit()
        insights = KeywordInsights(state="ok", topics=[
            TopicResult(topic="Prijzen", kind="topic", covered=3, total=3, own_covers=False, page_ids=["p1"]),
            TopicResult(topic="Wat kost SEO?", kind="question", covered=1, total=3, own_covers=True, page_ids=[]),
        ])
        analysis._save_insights(run, keyword, insights)
        with self.Session() as db:
            topics = db.get(CompetitorAnalysisKeyword, self.keyword_id).topics
        self.assertEqual(topics, [
            {"topic": "Prijzen", "kind": "topic", "covered": 3, "total": 3, "own_covers": False},
            {"topic": "Wat kost SEO?", "kind": "question", "covered": 1, "total": 3, "own_covers": True},
        ])
        self.assertEqual([TopicCoverage.model_validate(t).topic for t in topics], ["Prijzen", "Wat kost SEO?"])


if __name__ == "__main__":
    unittest.main()
