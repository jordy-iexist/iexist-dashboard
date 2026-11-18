"""Livegang: ontbrekende JSON-LD per pagina ("Maak schema").

`run_agent` en `fetch_page_html` worden in elke test vervangen, zodat er nooit een
echte modelaanroep of echte HTTP-aanvraag gebeurt. Database: SQLite met alleen de
benodigde tabellen.
"""
import json
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import AGENTS
from app.agents.base import AgentRunResult
from app.core.dependencies import require_user_id
from app.db.models import CustomerCategory, CustomerWebsite, LaunchScan, LaunchScanPage, WordPressSite
from app.db.session import get_db
from app.features.launch_checklist.mappers import to_page_item
from app.features.launch_checklist.schema_markup_router import router
from app.features.launch_checklist.services import schema_markup
from app.features.launch_checklist.services.golive_probes import new_client
from app.features.launch_checklist.services.page_types import EXPECTED_SCHEMA
from app.features.settings.services import MissingUserOpenAIKeyError

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
URL = "https://www.klant.nl/diensten/dakwerk/"
MODULE = "app.features.launch_checklist.services.schema_markup"
RUN_AGENT = f"{MODULE}.run_agent"
FETCH = f"{MODULE}.fetch_page_html"

EXISTING_GRAPH = {
    "@context": "https://schema.org",
    "@graph": [
        {"@type": "Organization", "@id": "https://www.klant.nl/#organization", "name": "Klant BV",
         "url": "https://www.klant.nl/"},
        {"@type": "WebPage", "@id": f"{URL}#webpage", "url": URL, "name": "Dakwerk",
         "description": "x" * 40_000},  # lang veld: wordt in de brief begrensd
    ],
}


def _html(*, extra_jsonld: list[dict] | None = None, faq: bool = True) -> str:
    blocks = [EXISTING_GRAPH, *(extra_jsonld or [])]
    scripts = "".join(f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks)
    questions = (
        "<h2>Veelgestelde vragen</h2>"
        "<h3>Wat kost een nieuw dak?</h3><p>Dat hangt af van de oppervlakte.</p>"
        "<h3>Hoe lang duurt het?</h3><p>Meestal twee dagen.</p>"
        "<h3>Werken jullie in Utrecht?</h3><p>Ja, in de hele provincie.</p>"
    ) if faq else ""
    return (
        f"<html><head><title>Dakwerk | Klant</title>{scripts}</head><body>"
        '<nav><a href="https://www.klant.nl/diensten/">Onze diensten</a></nav>'
        "<main><h1>Dakwerk</h1><p>Wij vernieuwen daken in de regio Utrecht. Bel 030 123 4567.</p>"
        f"{questions}<p>{'Lange tekst over dakwerk. ' * 2000}</p></main></body></html>"
    )


SERVICE_JSONLD = {
    "@context": "https://schema.org",
    "@graph": [
        {"@type": "Service", "@id": f"{URL}#service", "name": "Dakwerk",
         "description": "Een waarde met </script> erin",
         "provider": {"@id": "https://www.klant.nl/#organization"}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://www.klant.nl/"},
            {"@type": "ListItem", "position": 2, "name": "[naam van de dienstenpagina]",
             "item": "https://www.klant.nl/diensten/"},
        ]},
    ],
}


def _result(data: dict | str, incomplete_reason: str | None = None) -> AgentRunResult:
    text = data if isinstance(data, str) else json.dumps(data)
    return AgentRunResult(output=text, model="test", incomplete_reason=incomplete_reason)


def _agent_output(jsonld: dict | str = SERVICE_JSONLD, placeholders=None, notes="Verwijst naar de organisatie.") -> dict:
    return {
        "jsonld": jsonld if isinstance(jsonld, str) else json.dumps(jsonld),
        "types": ["Service", "BreadcrumbList"],
        "placeholders": placeholders if placeholders is not None else ["[naam van de dienstenpagina]"],
        "notes": notes,
    }


class _Base(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        for model in (CustomerCategory, CustomerWebsite, LaunchScan, LaunchScanPage, WordPressSite):
            model.__table__.create(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)

        self.customer_id = str(uuid.uuid4())
        self.db.add(CustomerWebsite(id=self.customer_id, name="Klant BV", base_url="https://www.klant.nl/",
                                    domain="klant.nl", created_by="user-1", created_at=NOW, updated_at=NOW))
        self.scan = self._scan(phase=1)
        self.geo_scan = self._scan(phase=2, source_scan_id=self.scan.id)
        self.page = LaunchScanPage(
            id=str(uuid.uuid4()), scan_id=self.scan.id, url=URL, path="/diensten/dakwerk/", status_code=200,
            title="Dakwerk | Klant", page_type="dienst", jsonld=[{"@type": "Organization"}],
            open_graph={"og:image": "https://www.klant.nl/wp-content/uploads/dak.jpg"}, created_at=NOW,
        )
        self.db.add(self.page)
        self.db.commit()

    def _scan(self, *, phase: int, source_scan_id: str | None = None) -> LaunchScan:
        scan = LaunchScan(
            id=str(uuid.uuid4()), customer_website_id=self.customer_id, phase=phase, status="completed",
            base_url="https://www.klant.nl/", total_urls=0, inventoried_urls=0, failed_urls=0, max_pages=500,
            vitals_max_pages=0, vitals_total=0, vitals_measured=0, created_by="user-1",
            source_scan_id=source_scan_id, created_at=NOW, updated_at=NOW,
        )
        self.db.add(scan)
        return scan

    def fresh_page(self) -> LaunchScanPage:
        self.db.expire_all()
        return self.db.get(LaunchScanPage, self.page.id)

    def store(self, suggestion: dict):
        self.page.schema_suggestion = suggestion
        self.page.schema_suggestion_at = NOW
        self.db.commit()


class TargetTypesTest(unittest.TestCase):
    def test_expected_schema_matches_frontend(self):
        self.assertEqual(EXPECTED_SCHEMA["blog"], ["BlogPosting|Article", "Person", "BreadcrumbList"])
        self.assertEqual(EXPECTED_SCHEMA["product"], ["Product", "Brand", "BreadcrumbList"])
        self.assertNotIn("overig", EXPECTED_SCHEMA)

    def test_present_schema_is_not_requested_again(self):
        self.assertEqual(schema_markup.target_types("dienst", {"Service"}, {}), ["BreadcrumbList"])
        self.assertEqual(schema_markup.target_types("dienst", set(), {}), ["Service", "BreadcrumbList"])

    def test_alternatives_and_subtypes_count_as_present(self):
        # "BlogPosting|Article": Article volstaat; anders wordt het eerste alternatief gevraagd.
        self.assertEqual(schema_markup.target_types("blog", {"Article", "Person"}, {}), ["BreadcrumbList"])
        self.assertEqual(schema_markup.target_types("blog", set(), {})[0], "BlogPosting")
        # Een LocalBusiness-subtype is ook een Organization.
        self.assertEqual(schema_markup.target_types("home", {"RoofingContractor", "WebSite"}, {}), [])

    def test_faq_signal_adds_faqpage(self):
        self.assertEqual(schema_markup.target_types("dienst", {"Service", "BreadcrumbList"}, {"faq": True}),
                         ["FAQPage"])
        self.assertEqual(
            schema_markup.target_types("dienst", {"Service", "BreadcrumbList", "FAQPage"}, {"faq": True}), [])
        self.assertEqual(schema_markup.target_types("overig", set(), {"faq": True}), ["FAQPage"])

    def test_nothing_missing(self):
        self.assertEqual(schema_markup.target_types("overig", set(), {"faq": False}), [])
        self.assertEqual(schema_markup.target_types(None, set(), None), [])


class BriefTest(unittest.TestCase):
    def test_analyze_and_brief(self):
        facts = schema_markup.analyze_page(_html(), URL, "klant.nl")
        self.assertEqual(facts.existing_types, {"Organization", "WebPage"})
        self.assertTrue(facts.signals["faq"])
        targets = schema_markup.target_types("dienst", facts.existing_types, facts.signals)
        self.assertEqual(targets, ["Service", "BreadcrumbList", "FAQPage"])
        brief = schema_markup.page_brief(
            facts, page_type="dienst", targets=targets,
            customer={"name": "Klant BV", "base_url": "https://www.klant.nl/", "domain": "klant.nl"},
            open_graph={"og:image": "https://www.klant.nl/wp-content/uploads/dak.jpg"},
        )
        self.assertIn("Klant: Klant BV", brief)
        self.assertIn(f"Pagina: {URL}", brief)
        self.assertIn("Paginatype: Dienstpagina", brief)
        # Verplichte eigenschappen per gevraagd type.
        self.assertIn("- Service: verplicht: name of serviceType", brief)
        self.assertIn("- BreadcrumbList: verplicht: itemListElement", brief)
        self.assertIn("- FAQPage: verplicht: mainEntity", brief)
        # De hint stuurt op een volledige Service, gekoppeld aan de bestaande WebPage.
        service_line = next(line for line in brief.splitlines() if line.startswith("- Service:"))
        for prop in ("description", "serviceType", "mainEntityOfPage", "provider", "image"):
            self.assertIn(prop, service_line)
        # Bestaande entiteiten om naar te verwijzen.
        self.assertIn("https://www.klant.nl/#organization (Organization): Klant BV", brief)
        # Kruimelpad met linktekst van de pagina.
        self.assertIn("- https://www.klant.nl/diensten/ (linktekst op de pagina: Onze diensten)", brief)
        self.assertIn(f"- {URL}", brief)
        self.assertIn("Wat kost een nieuw dak?", brief)
        self.assertIn("+31301234567", brief)
        self.assertIn("og:image", brief)
        # Begrensd: lange bestaande JSON-LD en lange paginatekst blazen de prompt niet op.
        self.assertIn("…(ingekort)", brief)
        self.assertLess(len(brief), 30_000)

    def test_build_script_escapes_closing_tags(self):
        script = schema_markup.build_script({"@context": "https://schema.org", "name": "a </script> <!-- b"})
        self.assertTrue(script.startswith('<script type="application/ld+json">\n{\n  "@context"'))
        self.assertTrue(script.endswith("\n</script>"))
        body = script[len('<script type="application/ld+json">'):-len("</script>")]
        self.assertNotIn("</", body)
        self.assertNotIn("<!--", body)
        self.assertEqual(json.loads(body)["name"], "a </script> <!-- b")


class FetchPageTest(unittest.TestCase):
    def _fetch(self, handler):
        with patch(f"{MODULE}.new_client", lambda: new_client(httpx.MockTransport(handler))), \
                patch(f"{MODULE}.is_safe_external_url", return_value=True):
            return schema_markup.fetch_page_html("https://klant.nl/dakwerk")

    def test_follows_redirect(self):
        def handler(request):
            if request.url.host == "klant.nl":
                return httpx.Response(301, headers={"location": URL})
            return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text="<h1>Dak</h1>")

        html, final = self._fetch(handler)
        self.assertEqual((html, final), ("<h1>Dak</h1>", URL))

    def test_errors(self):
        with self.assertRaises(schema_markup.SchemaMarkupError):
            self._fetch(lambda request: httpx.Response(404))
        with self.assertRaises(schema_markup.SchemaMarkupError):
            self._fetch(lambda request: httpx.Response(200, headers={"content-type": "application/pdf"}))
        with patch(f"{MODULE}.is_safe_external_url", return_value=False):
            with self.assertRaises(schema_markup.SchemaMarkupError):
                schema_markup.fetch_page_html("http://127.0.0.1/")


class GenerateSchemaMarkupTest(_Base):
    def test_generates_validates_and_stores(self):
        with patch(FETCH, return_value=(_html(), URL)) as fetch, \
                patch(RUN_AGENT, return_value=_result(_agent_output())) as run:
            result = schema_markup.generate_schema_markup(self.db, self.page, user_id="user-1")
        fetch.assert_called_once_with(URL)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0].name, "schema_markup")
        self.assertEqual(run.call_args.kwargs["user_id"], "user-1")
        self.assertIn("Te schrijven types", run.call_args.kwargs["input"])
        self.assertFalse(result.cached)
        self.assertFalse(result.nothing_missing)
        self.assertEqual(result.types, ["Service", "BreadcrumbList"])
        self.assertEqual(result.placeholders, ["[naam van de dienstenpagina]"])
        self.assertEqual(result.notes, "Verwijst naar de organisatie.")
        self.assertEqual(result.problems, [])
        self.assertIn("<\\/script>", result.script)
        stored = self.fresh_page()
        self.assertEqual(stored.schema_suggestion["jsonld"], SERVICE_JSONLD)
        self.assertIsNotNone(stored.schema_suggestion_at)

    def test_existing_types_returned_stored_and_cached(self):
        with patch(FETCH, return_value=(_html(), URL)), \
                patch(RUN_AGENT, return_value=_result(_agent_output())):
            result = schema_markup.generate_schema_markup(self.db, self.page, user_id="user-1")
        self.assertEqual(result.existing_types, ["Organization", "WebPage"])
        self.assertEqual(self.fresh_page().schema_suggestion["existing_types"], ["Organization", "WebPage"])
        with patch(FETCH) as fetch, patch(RUN_AGENT) as run:
            cached = schema_markup.generate_schema_markup(self.db, self.fresh_page(), user_id="user-1")
        fetch.assert_not_called()
        run.assert_not_called()
        self.assertTrue(cached.cached)
        self.assertEqual(cached.existing_types, ["Organization", "WebPage"])

    def test_old_stored_suggestion_without_existing_types(self):
        self.store({"jsonld": SERVICE_JSONLD, "types": ["Service"], "placeholders": [], "notes": "",
                    "problems": [], "existing_nodes": []})
        with patch(FETCH) as fetch, patch(RUN_AGENT) as run:
            result = schema_markup.generate_schema_markup(self.db, self.fresh_page(), user_id="user-1")
        fetch.assert_not_called()
        run.assert_not_called()
        self.assertEqual(result.existing_types, [])

    def test_reuses_stored_without_fetch_or_model_call(self):
        self.store({"jsonld": SERVICE_JSONLD, "types": ["Service"], "placeholders": [], "notes": "",
                    "problems": ["Service: mist name of serviceType"], "existing_nodes": []})
        with patch(FETCH) as fetch, patch(RUN_AGENT) as run:
            result = schema_markup.generate_schema_markup(self.db, self.fresh_page(), user_id="user-1")
        fetch.assert_not_called()
        run.assert_not_called()
        self.assertTrue(result.cached)
        self.assertEqual(result.problems, ["Service: mist name of serviceType"])
        self.assertEqual(result.generated_at.replace(tzinfo=timezone.utc), NOW)
        self.assertIn('"@type": "Service"', result.script)

    def test_outdated_format_is_regenerated_on_open(self):
        # Voorstel van vóór de rijkere generator (zonder bewaarde paginamarkup): bij openen opnieuw maken.
        self.store({"jsonld": SERVICE_JSONLD, "types": ["Service"], "placeholders": [], "notes": "",
                    "problems": []})
        self.assertTrue(schema_markup.is_stale(self.fresh_page().schema_suggestion, None))
        with patch(FETCH, return_value=(_html(), URL)), \
                patch(RUN_AGENT, return_value=_result(_agent_output())) as run:
            result = schema_markup.generate_schema_markup(self.db, self.fresh_page(), user_id="user-1")
        run.assert_called_once()
        self.assertFalse(result.cached)
        self.assertIn("existing_nodes", self.fresh_page().schema_suggestion)
        self.assertFalse(result.stale)

    def test_outdated_format_is_kept_when_reviewed_or_placed(self):
        # Al beoordeeld of geplaatst: niet ongemerkt opnieuw maken.
        for extra in ({"review": {"status": "approved", "jsonld_hash": "x"}}, {"placement": {"post_id": 1}}):
            self.store({"jsonld": SERVICE_JSONLD, "types": ["Service"], "placeholders": [], "notes": "",
                        "problems": [], **extra})
            with patch(FETCH) as fetch, patch(RUN_AGENT) as run:
                result = schema_markup.generate_schema_markup(self.db, self.fresh_page(), user_id="user-1")
            fetch.assert_not_called()
            run.assert_not_called()
            self.assertTrue(result.cached)

    def test_nothing_missing_skips_model_and_stores_nothing(self):
        present = {"@context": "https://schema.org", "@graph": [
            {"@type": "Service", "name": "Dakwerk"},
            {"@type": "BreadcrumbList", "itemListElement": []},
            {"@type": "FAQPage", "mainEntity": []},
        ]}
        with patch(FETCH, return_value=(_html(extra_jsonld=[present]), URL)), patch(RUN_AGENT) as run:
            result = schema_markup.generate_schema_markup(self.db, self.page, user_id="user-1")
        run.assert_not_called()
        self.assertTrue(result.nothing_missing)
        self.assertEqual((result.script, result.types, result.placeholders), ("", [], []))
        self.assertEqual(result.existing_types,
                         ["BreadcrumbList", "FAQPage", "Organization", "Service", "WebPage"])
        self.assertIsNotNone(result.generated_at)
        self.assertIsNone(self.fresh_page().schema_suggestion)
        self.assertIsNone(self.fresh_page().schema_suggestion_at)

    def test_existing_types_come_from_fresh_html_not_stored_jsonld(self):
        # Opgeslagen (ingekorte) jsonld zegt niets; de vers opgehaalde HTML heeft al Service.
        self.page.jsonld = []
        self.db.commit()
        with patch(FETCH, return_value=(_html(extra_jsonld=[{"@type": "Service", "name": "Dakwerk"}], faq=False),
                                        URL)), \
                patch(RUN_AGENT, return_value=_result(_agent_output())) as run:
            schema_markup.generate_schema_markup(self.db, self.fresh_page(), user_id="user-1")
        brief = run.call_args.kwargs["input"]
        self.assertIn("- BreadcrumbList:", brief)
        self.assertNotIn("- Service:", brief)
        self.assertNotIn("- FAQPage:", brief)

    def test_missing_required_fields_end_up_in_problems(self):
        incomplete = {"@context": "https://schema.org", "@graph": [
            {"@type": "Service", "provider": {"@id": "https://www.klant.nl/#organization"}},
            {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": "Wat kost een nieuw dak?"}]},
        ]}
        with patch(FETCH, return_value=(_html(), URL)), \
                patch(RUN_AGENT, return_value=_result(_agent_output(incomplete, placeholders=[]))):
            result = schema_markup.generate_schema_markup(self.db, self.page, user_id="user-1")
        self.assertIn("Service: mist name of serviceType", result.problems)
        self.assertIn("FAQPage: vraag 1 mist name of acceptedAnswer.text", result.problems)
        self.assertEqual(self.fresh_page().schema_suggestion["problems"], result.problems)

    def test_placeholders_found_in_jsonld_and_unknown_ones_dropped(self):
        jsonld = {"@context": "https://schema.org", "@graph": [
            {"@type": "Service", "name": "Dakwerk", "areaServed": "[werkgebied]"}]}
        with patch(FETCH, return_value=(_html(), URL)), \
                patch(RUN_AGENT, return_value=_result(_agent_output(jsonld, placeholders=["[bestaat niet]"]))):
            result = schema_markup.generate_schema_markup(self.db, self.page, user_id="user-1")
        self.assertEqual(result.placeholders, ["[werkgebied]"])

    def test_invalid_json_raises_and_keeps_old(self):
        self.store({"jsonld": {"@type": "Service"}, "types": ["Service"], "placeholders": [], "notes": "oud",
                    "problems": []})
        for output in (_result(_agent_output('{"@context": "https://schema.org", "@graph": [')),
                       _result("geen json"),
                       _result(_agent_output("[1, 2]"))):
            with patch(FETCH, return_value=(_html(), URL)), patch(RUN_AGENT, return_value=output):
                with self.assertRaises(schema_markup.SchemaMarkupError):
                    schema_markup.generate_schema_markup(self.db, self.fresh_page(), user_id="user-1",
                                                         regenerate=True)
            self.assertEqual(self.fresh_page().schema_suggestion["notes"], "oud")

    def test_truncated_output_raises(self):
        with patch(FETCH, return_value=(_html(), URL)), \
                patch(RUN_AGENT, return_value=_result('{"jsonld": "{', incomplete_reason="max_output_tokens")):
            with self.assertRaises(schema_markup.SchemaMarkupError) as ctx:
                schema_markup.generate_schema_markup(self.db, self.page, user_id="user-1")
        self.assertIn("niet afgemaakt", str(ctx.exception))
        self.assertIsNone(self.fresh_page().schema_suggestion)

    def test_connection_released_during_fetch_and_model_call(self):
        seen = {}

        def fake_fetch(url):
            seen["fetch"] = self.db.in_transaction()
            return _html(), URL

        def fake_run(*args, **kwargs):
            seen["run"] = self.db.in_transaction()
            return _result(_agent_output())

        with patch(FETCH, side_effect=fake_fetch), patch(RUN_AGENT, side_effect=fake_run):
            schema_markup.generate_schema_markup(self.db, self.fresh_page(), user_id="user-1")
        self.assertEqual(seen, {"fetch": False, "run": False})
        self.assertIsNotNone(self.fresh_page().schema_suggestion)

    def test_page_deleted_during_model_call(self):
        page_id = self.page.id

        def fake_run(*args, **kwargs):
            with self.Session() as other:
                other.delete(other.get(LaunchScanPage, page_id))
                other.commit()
            return _result(_agent_output())

        with patch(FETCH, return_value=(_html(), URL)), patch(RUN_AGENT, side_effect=fake_run):
            with self.assertRaises(schema_markup.SchemaMarkupPageGoneError):
                schema_markup.generate_schema_markup(self.db, self.fresh_page(), user_id="user-1")

    def test_agent_is_registered(self):
        agent = AGENTS["schema_markup"]()
        self.assertEqual((agent.tools, agent.max_steps, agent.reasoning_effort), ([], 1, "high"))
        # Ruim, omdat reasoning-tokens bij effort "high" meetellen en een afgekapt antwoord wordt geweigerd.
        self.assertEqual(agent.max_output_tokens, 20000)
        schema = agent.output_schema
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertEqual(set(schema["required"]), {"jsonld", "types", "placeholders", "omitted", "notes"})
        self.assertFalse(schema["additionalProperties"])

    def test_page_list_item_has_timestamp_but_not_content(self):
        self.store({"jsonld": SERVICE_JSONLD, "types": [], "placeholders": [], "notes": "", "problems": []})
        item = to_page_item(self.fresh_page()).model_dump()
        self.assertEqual(item["schema_suggestion_at"].replace(tzinfo=timezone.utc), NOW)
        self.assertNotIn("schema_suggestion", item)


class SchemaMarkupEndpointTest(_Base):
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
        self.path = f"/api/launch-checklist/scans/{self.scan.id}/pages/{self.page.id}/schema-markup"

    def test_generate_then_cached(self):
        with patch(FETCH, return_value=(_html(), URL)), \
                patch(RUN_AGENT, return_value=_result(_agent_output())) as run:
            first = self.client.post(self.path)
            second = self.client.post(self.path, json={"regenerate": False})
        self.assertEqual(first.status_code, 200, first.text)
        body = first.json()
        self.assertEqual(set(body), {"script", "types", "placeholders", "notes", "problems", "generated_at",
                                     "cached", "nothing_missing", "existing_types", "placement", "can_place",
                                     "place_blocked_reason", "replaces_default_types", "review_status",
                                     "reviewed_at", "target_types", "target_types_source", "stale", "omitted",
                                     "page_graph", "full_script"})
        self.assertEqual((body["target_types"], body["target_types_source"], body["stale"]),
                         (["Service", "BreadcrumbList", "FAQPage"], "auto", False))
        self.assertEqual((body["review_status"], body["reviewed_at"]), ("pending", None))
        self.assertTrue(body["script"].startswith('<script type="application/ld+json">'))
        self.assertFalse(body["cached"])
        self.assertFalse(body["nothing_missing"])
        self.assertEqual(body["existing_types"], ["Organization", "WebPage"])
        self.assertTrue(second.json()["cached"])
        self.assertEqual(second.json()["script"], body["script"])
        self.assertEqual(second.json()["existing_types"], ["Organization", "WebPage"])
        self.assertEqual(run.call_count, 1)

    def test_old_stored_suggestion_gives_empty_existing_types(self):
        self.store({"jsonld": SERVICE_JSONLD, "types": ["Service"], "placeholders": [], "notes": "",
                    "problems": [], "existing_nodes": []})
        with patch(FETCH) as fetch, patch(RUN_AGENT) as run:
            response = self.client.post(self.path, json={})
        fetch.assert_not_called()
        run.assert_not_called()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["cached"])
        self.assertEqual(response.json()["existing_types"], [])

    def test_geo_scan_id_is_accepted(self):
        path = f"/api/launch-checklist/scans/{self.geo_scan.id}/pages/{self.page.id}/schema-markup"
        with patch(FETCH, return_value=(_html(), URL)), patch(RUN_AGENT, return_value=_result(_agent_output())):
            response = self.client.post(path, json={})
        self.assertEqual(response.status_code, 200, response.text)

    def test_nothing_missing(self):
        with patch(FETCH, return_value=(_html(faq=False), URL)), patch(RUN_AGENT) as run:
            self.page.page_type = "overig"
            self.db.commit()
            response = self.client.post(self.path, json={})
        run.assert_not_called()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["nothing_missing"])
        self.assertEqual(response.json()["script"], "")
        self.assertEqual(response.json()["existing_types"], ["Organization", "WebPage"])

    def test_errors(self):
        other_scan = self._scan(phase=1)
        self.db.commit()
        for path in (f"/api/launch-checklist/scans/{self.scan.id}/pages/onbekend/schema-markup",
                     f"/api/launch-checklist/scans/{other_scan.id}/pages/{self.page.id}/schema-markup",
                     f"/api/launch-checklist/scans/onbekend/pages/{self.page.id}/schema-markup"):
            self.assertEqual(self.client.post(path, json={}).status_code, 404, path)
        with patch(FETCH, return_value=(_html(), URL)):
            with patch(RUN_AGENT, side_effect=MissingUserOpenAIKeyError("user-1")):
                response = self.client.post(self.path, json={"regenerate": True})
            self.assertEqual(response.status_code, 400)
            self.assertIn("OpenAI", response.json()["detail"])
            with patch(RUN_AGENT, side_effect=RuntimeError("time-out")):
                response = self.client.post(self.path, json={"regenerate": True})
            self.assertEqual(response.status_code, 502)
            self.assertIn("time-out", response.json()["detail"])
            with patch(RUN_AGENT, return_value=_result(_agent_output("{kapot"))):
                response = self.client.post(self.path, json={"regenerate": True})
            self.assertEqual(response.status_code, 502)
            self.assertIn("geen geldige JSON", response.json()["detail"])
            with patch(RUN_AGENT, return_value=_result("half", incomplete_reason="max_output_tokens")):
                response = self.client.post(self.path, json={"regenerate": True})
            self.assertEqual(response.status_code, 502)
            self.assertIn("niet afgemaakt", response.json()["detail"])
        with patch(FETCH, side_effect=schema_markup.SchemaMarkupError("De pagina kon niet worden opgehaald "
                                                                      "(status 503).")):
            response = self.client.post(self.path, json={"regenerate": True})
        self.assertEqual(response.status_code, 502)
        self.assertIn("status 503", response.json()["detail"])

    def test_page_deleted_during_model_call_gives_404(self):
        page_id = self.page.id

        def fake_run(*args, **kwargs):
            with self.Session() as other:
                other.delete(other.get(LaunchScanPage, page_id))
                other.commit()
            return _result(_agent_output())

        with patch(FETCH, return_value=(_html(), URL)), patch(RUN_AGENT, side_effect=fake_run):
            response = self.client.post(self.path, json={})
        self.assertEqual(response.status_code, 404, response.text)
        self.assertIn("verwijderd", response.json()["detail"])


# --- rijkere entiteiten -----------------------------------------------------------------------

BLOG_URL = "https://www.klant.nl/blog/nieuw-dak/"
BLOG_META = (
    '<meta property="article:published_time" content="2025-03-01T10:00:00+01:00" />'
    '<meta property="article:modified_time" content="2025-04-02T08:30:00+01:00" />'
    '<meta property="og:image" content="https://www.klant.nl/wp-content/uploads/dak-groot.jpg" />'
    '<meta name="author" content="Jan Jansen" />'
    '<meta name="twitter:label1" content="Geschreven door" /><meta name="twitter:data1" content="Jan Jansen" />'
    '<meta name="twitter:label2" content="Leestijd" /><meta name="twitter:data2" content="3 minuten" />'
)


def _blog_html(*, organization: bool = False) -> str:
    graph = [{"@type": "WebPage", "@id": f"{BLOG_URL}#webpage", "url": BLOG_URL, "name": "Nieuw dak"}]
    if organization:
        graph.insert(0, {"@type": "Organization", "@id": "https://www.klant.nl/#organization", "name": "Klant BV"})
    script = f'<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@graph": graph})}</script>'
    return (f"<html><head><title>Nieuw dak</title>{BLOG_META}{script}</head><body><main><h1>Nieuw dak</h1>"
            '<p>Geplaatst op <time datetime="2025-03-01">1 maart 2025</time>. Een nieuw dak gaat lang mee.</p>'
            "</main></body></html>")


BLOG_JSONLD = {"@context": "https://schema.org", "@graph": [
    {"@type": "BlogPosting", "@id": f"{BLOG_URL}#blogposting", "headline": "Nieuw dak",
     "datePublished": "2025-03-01T10:00:00+01:00", "author": {"@type": "Person", "name": "Jan Jansen"},
     "publisher": {"@id": "https://www.klant.nl/#organization"}},
    {"@type": "Organization", "@id": "https://www.klant.nl/#organization", "name": "Klant BV"},
]}


class RicherEntitiesTest(_Base):
    def setUp(self):
        super().setUp()
        self.page.url = BLOG_URL
        self.page.path = "/blog/nieuw-dak/"
        self.page.page_type = "blog"
        self.home = LaunchScanPage(
            id=str(uuid.uuid4()), scan_id=self.scan.id, url="https://www.klant.nl/", path="/", status_code=200,
            page_type="home", created_at=NOW,
            jsonld=[{"@type": "WebSite", "@id": "https://www.klant.nl/#website"},
                    {"@type": "Organization", "@id": "https://www.klant.nl/#organization", "name": "Klant BV",
                     "url": "https://www.klant.nl/",
                     "logo": {"@type": "ImageObject", "url": "https://www.klant.nl/logo.png"}}],
        )
        self.db.add(self.home)
        self.db.commit()

    def _generate(self, html: str, output: dict | None = None):
        output = output or {**_agent_output(BLOG_JSONLD, placeholders=[]), "omitted": []}
        with patch(FETCH, return_value=(html, BLOG_URL)), patch(RUN_AGENT, return_value=_result(output)) as run:
            result = schema_markup.generate_schema_markup(self.db, self.fresh_page(), user_id="user-1",
                                                          regenerate=True)
        return result, run.call_args.kwargs["input"]

    def test_publication_facts_from_html_in_brief(self):
        _, brief = self._generate(_blog_html())
        self.assertIn("Publicatiegegevens uit de HTML:", brief)
        self.assertIn("- Gepubliceerd (article:published_time): 2025-03-01T10:00:00+01:00", brief)
        self.assertIn("- Gewijzigd (article:modified_time): 2025-04-02T08:30:00+01:00", brief)
        self.assertIn("- Hoofdafbeelding (og:image): https://www.klant.nl/wp-content/uploads/dak-groot.jpg", brief)
        self.assertIn("- Auteur (meta author): Jan Jansen", brief)
        self.assertIn('- Auteur (twitter:data1, "Geschreven door"): Jan Jansen', brief)
        self.assertNotIn("3 minuten", brief.split("Publicatiegegevens uit de HTML:")[1].split("\n\n")[0])
        self.assertIn("- Datums in <time datetime>: 2025-03-01", brief)
        # Geen gekoppelde WordPress-site: geen WordPress-feiten.
        self.assertNotIn("uit WordPress", brief)

    def test_without_facts_no_section(self):
        facts = schema_markup.analyze_page(_html(), URL, "klant.nl")
        self.assertEqual(facts.publication, [])
        brief = schema_markup.page_brief(facts, page_type="dienst", targets=["Service"], customer=None)
        self.assertNotIn("Publicatiegegevens", brief)
        self.assertNotIn("Organisatie van de site", brief)

    def test_home_organization_when_page_has_none(self):
        _, brief = self._generate(_blog_html())
        section = brief.split("Organisatie van de site (van de homepage; staat NIET op deze pagina):")[1]
        self.assertIn("- @id: https://www.klant.nl/#organization", section)
        self.assertIn("- name: Klant BV", section)
        self.assertIn("- url: https://www.klant.nl/", section)
        self.assertIn("- logo: https://www.klant.nl/logo.png", section)
        self.assertIn("publisher of provider", section)

    def test_home_organization_from_root_of_same_host(self):
        # De hoofdpagina van het eigen domein is als "landing" ingedeeld; de "home"-rij is een ander
        # subdomein zonder organisatie. De organisatie komt dan van de hoofdpagina van het eigen domein.
        self.home.page_type = "landing"
        self.db.add(LaunchScanPage(id=str(uuid.uuid4()), scan_id=self.scan.id, url="https://app.klant.nl/",
                                   path="/", status_code=200, page_type="home", created_at=NOW, jsonld=[]))
        self.db.commit()
        _, brief = self._generate(_blog_html())
        self.assertIn("- @id: https://www.klant.nl/#organization", brief)

    def test_no_home_organization_when_page_has_one(self):
        _, brief = self._generate(_blog_html(organization=True))
        self.assertNotIn("Organisatie van de site", brief)

    def test_no_home_organization_without_home_row(self):
        self.db.delete(self.db.get(LaunchScanPage, self.home.id))
        self.db.commit()
        _, brief = self._generate(_blog_html())
        self.assertNotIn("Organisatie van de site", brief)

    def test_omitted_stored_and_returned(self):
        output = {**_agent_output(BLOG_JSONLD, placeholders=[]),
                  "omitted": ["BlogPosting.dateModified", "BlogPosting.image", "geen eigenschap",
                              "BlogPosting.dateModified"]}
        result, _ = self._generate(_blog_html(), output)
        self.assertEqual(result.omitted, ["BlogPosting.dateModified", "BlogPosting.image"])
        self.assertEqual(self.fresh_page().schema_suggestion["omitted"], result.omitted)
        self.assertEqual(schema_markup.stored_result(self.fresh_page()).omitted, result.omitted)

    def test_requirements_for_types_without_rules(self):
        line = schema_markup._requirements("TouristAttraction")
        self.assertIn("door Google gedocumenteerde verplichte en aanbevolen eigenschappen", line)
        self.assertNotIn("verplicht: name", line)
        # Nieuwe profielen en een LocalBusiness-subtype krijgen het LocalBusiness-profiel.
        for type_name in ("LocalBusiness", "HowTo", "Event", "VideoObject", "Review", "Course",
                          "SoftwareApplication", "Recipe"):
            self.assertIn(type_name, schema_markup._TYPE_HINTS)
        self.assertIn("openingHoursSpecification", schema_markup._requirements("Plumber"))
        self.assertIn("datePublished", schema_markup._requirements("NewsArticle"))
        # Bestaande regels blijven.
        self.assertTrue(schema_markup._requirements("Service").startswith("verplicht: name of serviceType"))
        self.assertTrue(schema_markup._requirements("Brand").startswith("verplicht: name (geen vaste regels)"))

    def test_html_extract_meta_facts(self):
        from app.features.launch_checklist.services.html_extract import extract_page
        page = extract_page(_blog_html())
        self.assertEqual(page.meta_facts["article:published_time"], "2025-03-01T10:00:00+01:00")
        self.assertEqual(page.meta_facts["twitter:data1"], "Jan Jansen")
        self.assertEqual(page.time_datetimes, ["2025-03-01"])


if __name__ == "__main__":
    unittest.main()
