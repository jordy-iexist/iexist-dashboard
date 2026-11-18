"""Livegang: eigen keuze van schema-types per pagina ("Maak schema").

`PUT …/scans/{scan_id}/schema-markup/target-types`, het genereren met een eigen keuze en `stale`.
Er gebeurt nooit een echte HTTP-aanvraag of modelaanroep: `fetch_page_html` en `run_agent` zijn
vervangen en elke echte netwerkverbinding via httpx laat de test falen. Database: SQLite.
"""
import json
import unittest
import uuid
from unittest.mock import patch

from app.db.models import LaunchScanPage
from app.features.launch_checklist.mappers import to_page_item
from app.features.launch_checklist.schema_markup_router import MAX_TARGET_TYPE_PAGES
from app.features.launch_checklist.services import schema_markup
from tests import test_schema_markup as base
from tests.test_schema_markup import FETCH, NOW, RUN_AGENT, SERVICE_JSONLD, URL, _agent_output, _html, _result

LOCAL_JSONLD = {"@context": "https://schema.org", "@graph": [
    {"@type": "LocalBusiness", "@id": f"{URL}#localbusiness", "name": "Klant BV",
     "address": {"@type": "PostalAddress", "addressLocality": "Utrecht"}},
    {"@type": "HowTo", "@id": f"{URL}#howto", "name": "Dak vernieuwen",
     "step": [{"@type": "HowToStep", "text": "Oude pannen eraf."}]},
]}


class _TargetBase(base.SchemaMarkupEndpointTest):
    """Hergebruikt de opzet (database, app, client) van de endpointtests; hun tests niet."""

    def setUp(self):
        super().setUp()
        real_http = patch("httpx.HTTPTransport.handle_request",
                          side_effect=AssertionError("echte HTTP-aanroep in een test"))
        real_http.start()
        self.addCleanup(real_http.stop)
        self.types_path = f"/api/launch-checklist/scans/{self.scan.id}/schema-markup/target-types"

    def set_types(self, types, page_ids=None, scan_id=None):
        path = (f"/api/launch-checklist/scans/{scan_id}/schema-markup/target-types"
                if scan_id else self.types_path)
        return self.client.put(path, json={"page_ids": page_ids or [self.page.id], "types": types})

    def generate(self, jsonld=SERVICE_JSONLD, *, regenerate=True, html=None):
        output = {**_agent_output(jsonld, placeholders=[]), "omitted": []}
        with patch(FETCH, return_value=(html or _html(), URL)), \
                patch(RUN_AGENT, return_value=_result(output)) as run:
            response = self.client.post(self.path, json={"regenerate": regenerate})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), (run.call_args.kwargs["input"] if run.called else None)


# Alleen de opzet van SchemaMarkupEndpointTest; zijn tests niet nog eens draaien.
for _name in [n for n in dir(base.SchemaMarkupEndpointTest) if n.startswith("test_")]:
    setattr(_TargetBase, _name, None)


class SetTargetTypesEndpointTest(_TargetBase):
    def test_set_and_reset(self):
        response = self.set_types(["LocalBusiness", "HowTo", "LocalBusiness", " Event "])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"updated": 1, "pages": [
            {"page_id": self.page.id, "schema_target_types": ["LocalBusiness", "HowTo", "Event"]}]})
        self.assertEqual(self.fresh_page().schema_target_types, ["LocalBusiness", "HowTo", "Event"])
        # Lege lijst en null = terug naar automatisch.
        for reset in ([], None):
            self.assertEqual(self.set_types(["HowTo"]).status_code, 200)
            body = self.set_types(reset).json()
            self.assertEqual(body["pages"][0]["schema_target_types"], None)
            self.assertIsNone(self.fresh_page().schema_target_types)

    def test_validation(self):
        for bad in (["localBusiness"], ["Local Business"], ["X"], ["Local-Business"], ["A" + "b" * 61],
                    ["<script>"]):
            response = self.set_types(bad)
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("schema-type", response.json()["detail"])
        nine = [f"Type{i}" for i in range(9)]
        response = self.set_types(nine)
        self.assertEqual(response.status_code, 400)
        self.assertIn("maximaal 8", response.json()["detail"])
        # Acht verschillende (met dubbele) mag.
        self.assertEqual(self.set_types(nine[:8] + nine[:3]).status_code, 200)
        ids = [str(uuid.uuid4()) for _ in range(MAX_TARGET_TYPE_PAGES)]
        self.assertEqual(self.set_types(["HowTo"], page_ids=ids).json()["updated"], 0)
        response = self.set_types(["HowTo"], page_ids=ids + [self.page.id])
        self.assertEqual(response.status_code, 400)
        self.assertIn(str(MAX_TARGET_TYPE_PAGES), response.json()["detail"])
        self.assertEqual(self.fresh_page().schema_target_types, nine[:8])
        # Geen geldige body: 422 van FastAPI.
        self.assertEqual(self.client.put(self.types_path, json={"types": ["HowTo"]}).status_code, 422)

    def test_pages_outside_scan_are_skipped(self):
        other_scan = self._scan(phase=1)
        elsewhere = LaunchScanPage(id=str(uuid.uuid4()), scan_id=other_scan.id, url=URL, path="/x/",
                                   status_code=200, created_at=NOW)
        second = LaunchScanPage(id=str(uuid.uuid4()), scan_id=self.scan.id, url=f"{URL}twee/", path="/twee/",
                                status_code=200, created_at=NOW)
        self.db.add_all([elsewhere, second])
        self.db.commit()
        body = self.set_types(["HowTo"], page_ids=[second.id, "bestaat-niet", elsewhere.id, self.page.id,
                                                   second.id]).json()
        self.assertEqual(body["updated"], 2)
        self.assertEqual([p["page_id"] for p in body["pages"]], [second.id, self.page.id])
        self.db.expire_all()
        self.assertIsNone(self.db.get(LaunchScanPage, elsewhere.id).schema_target_types)
        # Fase 2-scan ziet de pagina's van de bronscan; een onbekende scan niets.
        self.assertEqual(self.set_types(["Event"], scan_id=self.geo_scan.id).json()["updated"], 1)
        self.assertEqual(self.set_types(["Event"], scan_id="onbekend").json()["updated"], 0)

    def test_page_list_has_choice_but_not_suggestion_content(self):
        self.assertIsNone(to_page_item(self.fresh_page()).schema_target_types)
        self.generate()
        self.set_types(["HowTo", "LocalBusiness"])
        item = to_page_item(self.fresh_page()).model_dump()
        self.assertEqual(item["schema_target_types"], ["HowTo", "LocalBusiness"])
        self.assertNotIn("schema_suggestion", item)
        for key in ("page_graph", "full_script", "existing_nodes", "omitted", "target_types"):
            self.assertNotIn(key, item)


class GenerateWithChoiceTest(_TargetBase):
    def test_manual_choice_used_and_present_types_skipped(self):
        self.set_types(["LocalBusiness", "Organization", "HowTo", "TouristAttraction"])
        body, brief = self.generate(LOCAL_JSONLD)
        # Organization staat al op de pagina en wordt overgeslagen.
        self.assertIn("Te schrijven types (alleen deze; gekozen door de collega):", brief)
        for type_name in ("LocalBusiness", "HowTo", "TouristAttraction"):
            self.assertIn(f"- {type_name}:", brief)
        self.assertNotIn("- Organization:", brief)
        self.assertNotIn("- Service:", brief)
        self.assertNotIn("- FAQPage:", brief)
        # Type zonder regels: Google-richtlijnen uit eigen kennis.
        tourist = next(line for line in brief.splitlines() if line.startswith("- TouristAttraction:"))
        self.assertIn("door Google gedocumenteerde", tourist)
        self.assertEqual(body["target_types"], ["LocalBusiness", "HowTo", "TouristAttraction"])
        self.assertEqual(body["target_types_source"], "manual")
        self.assertFalse(body["stale"])
        self.assertIn("Overgeslagen omdat ze al op de pagina staan: Organization.", body["notes"])
        stored = self.fresh_page().schema_suggestion
        self.assertEqual((stored["target_types"], stored["target_types_source"], stored["target_choice"]),
                         (["LocalBusiness", "HowTo", "TouristAttraction"], "manual",
                          ["LocalBusiness", "Organization", "HowTo", "TouristAttraction"]))

    def test_manual_choice_replaces_rank_math_default_schema(self):
        # Het standaard-Article van Rank Math (#richSnippet) vervalt bij plaatsen: bij een eigen keuze
        # telt het niet als aanwezig; de Organization uit dezelfde graph wel.
        graph = {"@context": "https://schema.org", "@graph": [
            {"@type": "Organization", "@id": "https://www.klant.nl/#organization", "name": "Klant BV"},
            {"@type": "WebPage", "@id": f"{URL}#webpage"},
            {"@type": "Person", "@id": "https://www.klant.nl/author/admin/", "name": "admin"},
            {"@type": "Article", "@id": f"{URL}#richSnippet", "headline": "Titel",
             "author": {"@id": "https://www.klant.nl/author/admin/"}},
        ]}
        html = ('<html><head><title>Titel</title><script type="application/ld+json" class="rank-math-schema-pro">'
                f"{json.dumps(graph)}</script></head><body><h1>Titel</h1><p>Tekst van de pagina.</p></body></html>")
        self.set_types(["BlogPosting", "Organization"])
        blog = {"@context": "https://schema.org", "@graph": [
            {"@type": "BlogPosting", "@id": f"{URL}#blogposting", "headline": "Titel"}]}
        body, brief = self.generate(blog, html=html)
        self.assertIn("- BlogPosting:", brief)
        self.assertNotIn("- Organization:", brief)
        self.assertEqual(body["target_types"], ["BlogPosting"])
        self.assertIn("Organization", body["notes"])

    def test_null_is_automatic(self):
        self.set_types(None)
        body, brief = self.generate()
        self.assertIn("Te schrijven types (alleen deze):", brief)
        self.assertEqual(body["target_types"], ["Service", "BreadcrumbList", "FAQPage"])
        self.assertEqual(body["target_types_source"], "auto")
        self.assertIsNone(self.fresh_page().schema_suggestion["target_choice"])

    def test_manual_choice_all_present_is_nothing_missing(self):
        self.set_types(["Organization", "WebPage"])
        with patch(FETCH, return_value=(_html(), URL)), patch(RUN_AGENT) as run:
            body = self.client.post(self.path, json={"regenerate": True}).json()
        run.assert_not_called()
        self.assertTrue(body["nothing_missing"])
        self.assertEqual((body["target_types"], body["target_types_source"]), (["Organization", "WebPage"], "manual"))
        self.assertIn("gekozen schema-types staan al op de pagina", body["notes"])
        self.assertEqual(body["full_script"], "")
        self.assertEqual({r["status"] for r in body["page_graph"]}, {"existing"})
        self.assertIsNone(self.fresh_page().schema_suggestion)

    def test_stale_after_changed_choice_and_cleared_by_regenerate(self):
        self.generate()
        suggestion = dict(self.fresh_page().schema_suggestion)
        suggestion["review"] = {"status": "rejected", "jsonld_hash": "x", "user_id": "user-1",
                                "reviewed_at": NOW.isoformat()}
        self.store(suggestion)
        self.assertFalse(self.client.post(self.path, json={}).json()["stale"])

        self.set_types(["HowTo", "LocalBusiness"])
        body = self.client.post(self.path, json={}).json()
        self.assertTrue(body["cached"])
        self.assertTrue(body["stale"])
        # Voorstel en beoordeling blijven staan; alleen stale verandert.
        self.assertEqual(body["target_types"], ["Service", "BreadcrumbList", "FAQPage"])
        self.assertEqual(body["target_types_source"], "auto")
        self.assertEqual(self.fresh_page().schema_suggestion["review"], suggestion["review"])
        self.assertEqual(self.fresh_page().schema_suggestion["jsonld"], SERVICE_JSONLD)
        overview = self.client.post(f"/api/launch-checklist/scans/{self.scan.id}/schema-markup/overview",
                                    json={"page_ids": [self.page.id]}).json()
        self.assertTrue(overview["items"][0]["result"]["stale"])
        # Dezelfde keuze in andere volgorde maakt niets uit.
        self.set_types(["LocalBusiness", "HowTo"])
        body, _ = self.generate(LOCAL_JSONLD)
        self.assertFalse(body["stale"])
        self.assertEqual(body["target_types_source"], "manual")
        self.set_types(["HowTo", "LocalBusiness"])
        self.assertFalse(self.client.post(self.path, json={}).json()["stale"])
        # Terug naar automatisch: weer stale.
        self.set_types(None)
        self.assertTrue(self.client.post(self.path, json={}).json()["stale"])

    def test_old_suggestion_is_auto(self):
        self.store({"jsonld": SERVICE_JSONLD, "types": ["Service"], "placeholders": [], "notes": "",
                    "problems": [], "existing_nodes": []})
        body = self.client.post(self.path, json={}).json()
        self.assertEqual((body["target_types_source"], body["stale"]), ("auto", False))
        self.assertEqual(body["target_types"], ["Service", "BreadcrumbList"])
        self.set_types(["HowTo"])
        self.assertTrue(self.client.post(self.path, json={}).json()["stale"])


class PureTargetTypesTest(unittest.TestCase):
    def test_plan_targets(self):
        self.assertEqual(schema_markup.plan_targets("dienst", {"Service"}, {"faq": True}, None),
                         (["BreadcrumbList", "FAQPage"], [], "auto"))
        # Eigen keuze: geen FAQ-signaal en geen paginatype; aanwezige types (ook via subtypes) overgeslagen.
        self.assertEqual(schema_markup.plan_targets("dienst", {"RoofingContractor", "Article"}, {"faq": True},
                                                    ["Organization", "BlogPosting", "Event"]),
                         (["Event"], ["Organization", "BlogPosting"], "manual"))
        self.assertEqual(schema_markup.target_types("dienst", set(), {}, ["HowTo"]), ["HowTo"])
        self.assertEqual(schema_markup.plan_targets("dienst", set(), {}, [])[2], "auto")

    def test_requested_types_without_fetch(self):
        self.assertEqual(schema_markup.requested_types("blog", None), ["BlogPosting", "Person", "BreadcrumbList"])
        self.assertEqual(schema_markup.requested_types("overig", None, {"faq": True}), ["FAQPage"])
        self.assertEqual(schema_markup.requested_types("blog", ["HowTo"]), ["HowTo"])

    def test_is_stale(self):
        suggestion = {"jsonld": {"@type": "Service"}, "target_choice": ["A", "B"], "existing_nodes": []}
        self.assertFalse(schema_markup.is_stale(suggestion, ["B", "A"]))
        self.assertTrue(schema_markup.is_stale(suggestion, None))
        current = {"jsonld": {"@type": "Service"}, "existing_nodes": []}
        self.assertTrue(schema_markup.is_stale(current, ["A"]))
        self.assertFalse(schema_markup.is_stale(current, []))
        # Voorstel van vóór de rijkere generator: verouderd, tenzij al beoordeeld of geplaatst.
        self.assertTrue(schema_markup.is_stale({"jsonld": {"@type": "Service"}}, None))
        self.assertFalse(schema_markup.is_stale({"jsonld": {"@type": "Service"}, "review": {"status": "approved"}}, None))
        self.assertFalse(schema_markup.is_stale(None, ["A"]))


if __name__ == "__main__":
    unittest.main()
