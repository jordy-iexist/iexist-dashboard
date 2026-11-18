"""Actiepunten: opdracht voor Claude Code ("Maak prompt").

`run_agent` wordt in elke test vervangen, zodat er nooit een echte modelaanroep
gebeurt. Database: SQLite met alleen de benodigde tabellen.
"""
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import AGENTS
from app.agents.base import Agent, AgentRunResult, run_agent
from app.core.dependencies import require_user_id
from app.db.models import (
    CustomerCategory,
    CustomerWebsite,
    LaunchContentPage,
    LaunchContentSuggestion,
    LaunchScan,
    LaunchScanIssue,
    LaunchScanPage,
)
from app.db.session import get_db
from app.features.launch_checklist.fix_prompt_router import router
from app.features.launch_checklist.services import fix_prompt
from app.features.settings.services import MissingUserOpenAIKeyError

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
URL = "https://www.klant.nl/diensten/"
RUN_AGENT = "app.features.launch_checklist.services.fix_prompt.run_agent"


def _result(text: str, incomplete_reason: str | None = None) -> AgentRunResult:
    return AgentRunResult(output=text, model="test", incomplete_reason=incomplete_reason)


class _Base(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        for model in (CustomerCategory, CustomerWebsite, LaunchScan, LaunchScanPage, LaunchScanIssue,
                      LaunchContentPage, LaunchContentSuggestion):
            model.__table__.create(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)

        self.customer_id = str(uuid.uuid4())
        self.db.add(CustomerWebsite(id=self.customer_id, name="Klant BV", base_url="https://www.klant.nl/",
                                    domain="klant.nl", created_by="user-1", created_at=NOW, updated_at=NOW))
        self.scan = LaunchScan(
            id=str(uuid.uuid4()), customer_website_id=self.customer_id, phase=3, status="completed",
            base_url="https://www.klant.nl/", total_urls=0, inventoried_urls=0, failed_urls=0, max_pages=500,
            vitals_max_pages=0, vitals_total=0, vitals_measured=0, created_by="user-1",
            created_at=NOW, updated_at=NOW,
        )
        self.db.add(self.scan)
        self.page = LaunchScanPage(
            id=str(uuid.uuid4()), scan_id=self.scan.id, url=URL, path="/diensten/", status_code=200,
            title="Diensten | Klant", title_length=17, meta_description=None, h1=["Onze diensten"], h1_count=1,
            images_total=4, images_missing_alt=2, created_at=NOW,
        )
        self.db.add(self.page)
        content_page = LaunchContentPage(
            id=str(uuid.uuid4()), scan_id=self.scan.id, url=URL, path="/diensten/", focus_keyword="dakdekker",
            headings=[{"level": 1, "text": "Onze diensten"}, {"level": 2, "text": "Werkwijze"}], created_at=NOW,
        )
        self.db.add(content_page)
        self.db.add(LaunchContentSuggestion(
            id=str(uuid.uuid4()), scan_id=self.scan.id, customer_website_id=self.customer_id,
            content_page_id=content_page.id, item_key="c3_images", agent="content_text", title="Alt hero",
            current_value="1.png", proposed_value="Dakdekker legt dakpannen op een rijtjeshuis",
            rationale="Beschrijft de afbeelding.", status="open", created_at=NOW, updated_at=NOW,
        ))
        images = [{"src": f"https://www.klant.nl/wp-content/uploads/{n}.png", "filename": f"{n}.png",
                   "alt": "", "missing_alt": True} for n in range(1, 81)]
        self.issue = LaunchScanIssue(
            id=str(uuid.uuid4()), scan_id=self.scan.id, page_id=self.page.id, issue_type="c3_images",
            category="content", severity="middel", title="Afbeeldingen zonder alt – /diensten/",
            description="Afbeeldingen: 2 zonder alt-tekst.",
            recommendation="Geef elke inhoudsafbeelding een beschrijvende alt-tekst en bestandsnaam.",
            url=URL, details={"evidence": ["hero.png zonder alt"], "data": {"images": images},
                              "value_boost": {"refdomains": 3}},
            status="open", created_at=NOW, updated_at=NOW,
        )
        self.db.add(self.issue)
        self.db.commit()

    def fresh_issue(self) -> LaunchScanIssue:
        self.db.expire_all()
        return self.db.get(LaunchScanIssue, self.issue.id)


class IssueBriefTest(_Base):
    def test_contains_facts_from_scan(self):
        brief = fix_prompt.issue_brief(self.db, self.issue, self.db.get(CustomerWebsite, self.customer_id))
        self.assertIn("Klant: Klant BV", brief)
        self.assertIn("domein: klant.nl", brief)
        self.assertIn(f"Pagina: {URL}", brief)
        self.assertIn("Fase 3", brief)
        self.assertIn("Aanpak: Geef elke inhoudsafbeelding een beschrijvende alt-tekst", brief)
        self.assertIn("- hero.png zonder alt", brief)
        # Paginafeiten en contentanalyse.
        self.assertIn('H1: "Onze diensten"', brief)
        self.assertIn("4 totaal, 2 zonder alt", brief)
        self.assertIn("Focuszoekwoord: dakdekker", brief)
        # AI-voorstel letterlijk.
        self.assertIn("Voorstel: Dakdekker legt dakpannen op een rijtjeshuis", brief)
        self.assertIn("Huidig: 1.png", brief)
        # Geen prioriteitsdata; lijst begrensd maar niet weggeknipt.
        self.assertNotIn("refdomains", brief)
        self.assertIn("60.png", brief)
        self.assertNotIn("61.png", brief)
        self.assertIn("… en nog 20", brief)

    def test_flat_details_and_sitewide_issue(self):
        self.issue.url = None
        self.issue.page_id = None
        self.issue.details = {"status": 404, "value_boost": {"refdomains": 9}}
        brief = fix_prompt.issue_brief(self.db, self.issue, None)
        self.assertIn("sitebreed", brief)
        self.assertIn('"status": 404', brief)
        self.assertNotIn("refdomains", brief)
        self.assertNotIn("AI-voorstellen", brief)


class GenerateFixPromptTest(_Base):
    def test_generates_and_stores(self):
        with patch(RUN_AGENT, return_value=_result("## Context\nopdracht")) as run:
            prompt, at, cached = fix_prompt.generate_fix_prompt(self.db, self.issue, user_id="user-1")
        self.assertEqual(prompt, "## Context\nopdracht")
        self.assertFalse(cached)
        run.assert_called_once()
        agent = run.call_args.args[0]
        self.assertEqual(agent.name, "fix_prompt")
        self.assertEqual(run.call_args.kwargs["user_id"], "user-1")
        self.assertIn(URL, run.call_args.kwargs["input"])
        stored = self.fresh_issue()
        self.assertEqual(stored.fix_prompt, "## Context\nopdracht")
        self.assertIsNotNone(stored.fix_prompt_at)

    def test_reuses_stored_prompt_without_model_call(self):
        self.issue.fix_prompt = "opgeslagen"
        self.issue.fix_prompt_at = NOW
        self.db.commit()
        with patch(RUN_AGENT) as run:
            prompt, at, cached = fix_prompt.generate_fix_prompt(self.db, self.fresh_issue(), user_id="user-1")
        run.assert_not_called()
        self.assertEqual((prompt, cached), ("opgeslagen", True))
        self.assertEqual(at.replace(tzinfo=timezone.utc), NOW)

    def test_regenerate_calls_agent_and_overwrites(self):
        self.issue.fix_prompt = "oud"
        self.issue.fix_prompt_at = NOW
        self.db.commit()
        with patch(RUN_AGENT, return_value=_result("nieuw")) as run:
            prompt, at, cached = fix_prompt.generate_fix_prompt(
                self.db, self.fresh_issue(), user_id="user-1", regenerate=True)
        run.assert_called_once()
        self.assertEqual((prompt, cached), ("nieuw", False))
        stored = self.fresh_issue()
        self.assertEqual(stored.fix_prompt, "nieuw")
        self.assertNotEqual(stored.fix_prompt_at.replace(tzinfo=timezone.utc), NOW)

    def test_empty_output_raises_and_keeps_old_prompt(self):
        self.issue.fix_prompt = "oud"
        self.issue.fix_prompt_at = NOW
        self.db.commit()
        with patch(RUN_AGENT, return_value=_result("  ")):
            with self.assertRaises(fix_prompt.FixPromptError):
                fix_prompt.generate_fix_prompt(self.db, self.fresh_issue(), user_id="user-1", regenerate=True)
        self.assertEqual(self.fresh_issue().fix_prompt, "oud")

    def test_truncated_output_raises_and_keeps_old_prompt(self):
        self.issue.fix_prompt = "oud"
        self.issue.fix_prompt_at = NOW
        self.db.commit()
        with patch(RUN_AGENT, return_value=_result("## Context\nhalve opd", incomplete_reason="max_output_tokens")):
            with self.assertRaises(fix_prompt.FixPromptError) as ctx:
                fix_prompt.generate_fix_prompt(self.db, self.fresh_issue(), user_id="user-1", regenerate=True)
        self.assertIn("niet afgemaakt", str(ctx.exception))
        self.assertIn("maximale lengte", str(ctx.exception))
        self.assertEqual(self.fresh_issue().fix_prompt, "oud")

    def test_connection_released_during_model_call(self):
        seen = {}

        def fake_run(*args, **kwargs):
            seen["in_transaction"] = self.db.in_transaction()
            return _result("opdracht")

        with patch(RUN_AGENT, side_effect=fake_run):
            fix_prompt.generate_fix_prompt(self.db, self.fresh_issue(), user_id="user-1")
        self.assertEqual(seen, {"in_transaction": False})
        self.assertEqual(self.fresh_issue().fix_prompt, "opdracht")

    def test_issue_deleted_during_model_call(self):
        issue_id = self.issue.id

        def fake_run(*args, **kwargs):
            # Bv. een monitor-run die het punt vervangt terwijl het model schrijft.
            with self.Session() as other:
                other.delete(other.get(LaunchScanIssue, issue_id))
                other.commit()
            return _result("opdracht")

        with patch(RUN_AGENT, side_effect=fake_run):
            with self.assertRaises(fix_prompt.FixPromptIssueGoneError):
                fix_prompt.generate_fix_prompt(self.db, self.fresh_issue(), user_id="user-1")
        self.db.expire_all()
        self.assertIsNone(self.db.get(LaunchScanIssue, issue_id))

    def test_agent_is_registered(self):
        agent = AGENTS["fix_prompt"]()
        self.assertEqual((agent.tools, agent.max_steps, agent.output_schema), ([], 1, None))


class FixPromptEndpointTest(_Base):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        app.include_router(router)

        def override_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_user_id] = lambda: "user-1"
        self.client = TestClient(app)
        self.path = f"/api/launch-checklist/issues/{self.issue.id}/fix-prompt"

    def test_generate_then_cached(self):
        with patch(RUN_AGENT, return_value=_result("opdracht")) as run:
            first = self.client.post(self.path, json={})
            second = self.client.post(self.path, json={"regenerate": False})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["prompt"], "opdracht")
        self.assertFalse(first.json()["cached"])
        self.assertTrue(second.json()["cached"])
        self.assertEqual(run.call_count, 1)

    def test_errors(self):
        self.assertEqual(self.client.post("/api/launch-checklist/issues/onbekend/fix-prompt", json={}).status_code,
                         404)
        with patch(RUN_AGENT, side_effect=MissingUserOpenAIKeyError("user-1")):
            response = self.client.post(self.path, json={"regenerate": True})
        self.assertEqual(response.status_code, 400)
        self.assertIn("OpenAI", response.json()["detail"])
        with patch(RUN_AGENT, side_effect=RuntimeError("time-out")):
            response = self.client.post(self.path, json={"regenerate": True})
        self.assertEqual(response.status_code, 502)
        self.assertIn("time-out", response.json()["detail"])
        with patch(RUN_AGENT, return_value=_result("half", incomplete_reason="max_output_tokens")):
            response = self.client.post(self.path, json={"regenerate": True})
        self.assertEqual(response.status_code, 502)
        self.assertIn("niet afgemaakt", response.json()["detail"])

    def test_issue_deleted_during_model_call_gives_404(self):
        issue_id = self.issue.id

        def fake_run(*args, **kwargs):
            with self.Session() as other:
                other.delete(other.get(LaunchScanIssue, issue_id))
                other.commit()
            return _result("opdracht")

        with patch(RUN_AGENT, side_effect=fake_run):
            response = self.client.post(self.path, json={})
        self.assertEqual(response.status_code, 404, response.text)
        self.assertIn("verwijderd", response.json()["detail"])


class RunAgentIncompleteTest(unittest.TestCase):
    """`run_agent` meldt een afgekapt eindantwoord via `incomplete_reason`, zonder ander gedrag."""

    def _run(self, response):
        client = MagicMock()
        client.with_options.return_value = client
        client.responses.create.return_value = response
        agent = Agent(name="t", instructions="i", tools=[], model="gpt-test", max_steps=1)
        with patch("app.agents.base._build_openai_client", return_value=client):
            return run_agent(agent, user_id="user-1", input="x", context=None)

    def test_incomplete_response_is_flagged(self):
        result = self._run(SimpleNamespace(
            status="incomplete", incomplete_details=SimpleNamespace(reason="max_output_tokens"),
            output=[], output_text="half", usage=None,
        ))
        self.assertEqual(result.output, "half")
        self.assertEqual(result.stopped_reason, "completed")
        self.assertEqual(result.incomplete_reason, "max_output_tokens")

    def test_completed_response_is_not_flagged(self):
        result = self._run(SimpleNamespace(status="completed", incomplete_details=None, output=[],
                                           output_text="klaar", usage=None))
        self.assertEqual(result.output, "klaar")
        self.assertIsNone(result.incomplete_reason)


if __name__ == "__main__":
    unittest.main()
