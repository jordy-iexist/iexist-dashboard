"""Livegang: een schema-voorstel met de hand bewerken, en de bedrijfsgegevens van de site in de brief.

Bewerken (`PUT …/schema-markup/content`) is alleen database: geen modelaanroep en geen HTTP. Elke echte
netwerkverbinding via httpx laat de test falen; WordPress en het ophalen van de pagina zijn nagebootst
(`FakeWordPress` uit `test_rankmath_schema`). Database: SQLite.
"""
import json
import unittest
import uuid
from unittest.mock import patch

from app.agents.base import AgentRunResult
from app.db.models import LaunchScan, LaunchScanPage
from app.features.launch_checklist.services import schema_markup
from tests import test_schema_markup as tsm
from tests.test_rankmath_schema import BASE, BREADCRUMB, NOW, RUN_AGENT, SERVICE, URL, _Endpoint, _graph, _suggestion

LOCAL = {"@type": "LocalBusiness", "@id": f"{URL}#localbusiness", "name": "Klant BV", "url": f"{BASE}/"}
ADDRESS = {"@type": "PostalAddress", "streetAddress": "Hoofdstraat 1", "postalCode": "3511 AB",
           "addressLocality": "Utrecht", "addressCountry": "NL"}


def _agent(jsonld) -> AgentRunResult:
    return AgentRunResult(output=json.dumps({"jsonld": json.dumps(jsonld), "types": [], "placeholders": [],
                                             "notes": "", "omitted": []}), model="test", incomplete_reason=None)


class _EditBase(_Endpoint):
    def setUp(self):
        super().setUp()
        real_http = patch("httpx.HTTPTransport.handle_request",
                          side_effect=AssertionError("echte HTTP-aanroep in een test"))
        real_http.start()
        self.addCleanup(real_http.stop)

    def edit(self, text, page_id: str | None = None, scan_id: str | None = None):
        path = (f"/api/launch-checklist/scans/{scan_id or self.scan.id}/pages/{page_id or self.page.id}"
                "/schema-markup/content")
        return self.client.put(path, json={"jsonld": text})

    def stored(self) -> dict:
        return self.fresh_page().schema_suggestion

    def local_suggestion(self, **extra) -> dict:
        return _suggestion(_graph(LOCAL), types=["LocalBusiness"], target_types=["LocalBusiness"],
                           target_types_source="manual", target_choice=["LocalBusiness"],
                           problems=["LocalBusiness: mist address"],
                           omitted=["LocalBusiness.telephone", "LocalBusiness.openingHoursSpecification",
                                    "LocalBusiness.address.postalCode"],
                           existing_nodes=[{"@type": "WebPage", "@id": f"{URL}#webpage"}], lapse_ids=[],
                           **extra)

    def assert_no_site_traffic(self):
        self.assertEqual(self.wp.calls, [])
        self.fetch_mock.assert_not_called()


# --- bewerken ------------------------------------------------------------------------------------

class EditContentTest(_EditBase):
    def test_valid_edit_recomputes_and_stores(self):
        self.page.schema_target_types = ["LocalBusiness"]
        self.store(self.local_suggestion())
        edited = {**LOCAL, "address": ADDRESS, "telephone": "030 123 4567",
                  "openingHoursSpecification": "[openingstijden]"}
        with patch(RUN_AGENT) as run:
            response = self.edit(json.dumps(_graph(edited), indent=2))
        run.assert_not_called()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["types"], ["LocalBusiness"])
        self.assertEqual(body["placeholders"], ["[openingstijden]"])
        self.assertFalse(any("mist address" in p for p in body["problems"]))
        self.assertEqual(body["problems"], [])
        # telephone en address.postalCode zijn nu ingevuld; openingstijden met een plaatshouder ook.
        self.assertEqual(body["omitted"], [])
        self.assertTrue(body["edited"])
        self.assertIsNotNone(body["edited_at"])
        self.assertTrue(body["cached"])
        self.assertFalse(body["stale"])
        self.assertTrue(body["generated_at"].startswith("2026-11-16T12:00:00"))
        self.assertIn('"streetAddress": "Hoofdstraat 1"', body["script"])
        self.assertEqual([row["status"] for row in body["page_graph"]], ["existing", "new"])
        self.assertIn("Hoofdstraat 1", body["full_script"])
        # Plaatshouder: plaatsen kan nog niet.
        self.assertFalse(body["can_place"])

        stored = self.stored()
        self.assertEqual(stored["jsonld"], _graph(edited))
        self.assertEqual(stored["edited"]["user_id"], "user-1")
        self.assertTrue(stored["edited"]["edited_at"])
        # De rest van het voorstel blijft staan.
        self.assertEqual(stored["target_types"], ["LocalBusiness"])
        self.assertEqual(stored["target_choice"], ["LocalBusiness"])
        self.assertEqual(stored["existing_nodes"], [{"@type": "WebPage", "@id": f"{URL}#webpage"}])
        self.assertEqual(self.fresh_page().schema_suggestion_at.replace(tzinfo=None), NOW.replace(tzinfo=None))
        self.assert_no_site_traffic()

    def test_omitted_keeps_what_is_still_missing(self):
        self.store(self.local_suggestion())
        body = self.edit(json.dumps(_graph({**LOCAL, "telephone": "030 123 4567"}))).json()
        self.assertEqual(body["omitted"], ["LocalBusiness.openingHoursSpecification",
                                           "LocalBusiness.address.postalCode"])
        self.assertEqual(body["problems"], ["LocalBusiness: mist address"])

    def test_script_wrapper_is_stripped(self):
        self.store(self.local_suggestion())
        edited = {**LOCAL, "address": ADDRESS, "description": "Tekst met </script> erin"}
        script = schema_markup.build_script(_graph(edited))
        self.assertIn("<\\/script>", script)
        response = self.edit("\n  " + script + "\n")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.stored()["jsonld"], _graph(edited))
        self.assertTrue(response.json()["edited"])
        # Script-omhulsel met een ander type wordt geweigerd.
        response = self.edit('<script type="text/javascript">{"@type": "Thing"}</script>')
        self.assertEqual(response.status_code, 400)

    def test_invalid_json_reports_line_and_column(self):
        self.store(self.local_suggestion())
        before = self.stored()
        text = '{\n  "@type": "LocalBusiness",\n  "name": "Klant BV"\n  "url": "https://www.klant.nl/"\n}'
        response = self.edit(text)
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertIn("geen geldige JSON", detail)
        self.assertIn("komma verwacht", detail)
        self.assertIn("regel 4, kolom 3", detail)
        # Met een script-omhulsel tellen regel en kolom in de tekst zoals gestuurd.
        response = self.edit('<script type="application/ld+json">\n{\n  "@type": "Thing",\n}\n</script>')
        self.assertEqual(response.status_code, 400)
        self.assertIn("regel 4, kolom 1", response.json()["detail"])
        self.assertEqual(self.stored(), before)
        self.assert_no_site_traffic()

    def test_object_without_types_is_refused(self):
        self.store(self.local_suggestion())
        before = self.stored()
        cases = {
            '{"name": "Klant BV"}': "geen @type en geen @graph",
            '[{"@type": "LocalBusiness", "name": "x"}]': "één object",
            '"tekst"': "één object",
            '{"@context": "https://schema.org", "@graph": [{"name": "x"}, "y"]}': "geen entiteiten met een @type",
            '{"@graph": "x"}': "lijst met entiteiten",
            "   ": "leeg",
            '{"@type": "Thing", "x": NaN}': "NaN",
        }
        for text, reason in cases.items():
            response = self.edit(text)
            self.assertEqual(response.status_code, 400, text)
            self.assertIn(reason, response.json()["detail"], text)
        self.assertEqual(self.stored(), before)

    def test_too_large_is_refused(self):
        self.store(self.local_suggestion())
        text = json.dumps(_graph({**LOCAL, "description": "x" * schema_markup.MAX_EDIT_BYTES}))
        response = self.edit(text)
        self.assertEqual(response.status_code, 400)
        self.assertIn("te groot", response.json()["detail"])
        self.assertIn("100 kB", response.json()["detail"])

    def test_normalized_and_split_after_edit(self):
        product_url = URL
        self.store(_suggestion(_graph({"@type": "Product", "@id": f"{product_url}#product", "name": "Dakpan"}),
                               target_types=["Product", "Brand"]))
        # Kaal object zonder @context en @graph, met een geneste Brand.
        text = json.dumps({"@type": "Product", "@id": f"{product_url}#product", "name": "Dakpan",
                           "brand": {"@type": "Brand", "name": "Merk X"},
                           "offers": {"@type": "Offer", "price": "10", "priceCurrency": "EUR"}})
        response = self.edit(text)
        self.assertEqual(response.status_code, 200, response.text)
        jsonld = self.stored()["jsonld"]
        self.assertEqual(jsonld["@context"], "https://schema.org")
        graph = jsonld["@graph"]
        self.assertEqual([n["@type"] for n in graph], ["Product", "Brand"])
        self.assertEqual(graph[0]["brand"], {"@id": f"{URL}#brand"})
        self.assertEqual(graph[1], {"@type": "Brand", "@id": f"{URL}#brand", "name": "Merk X"})
        # Offer is niet gevraagd en blijft genest.
        self.assertEqual(graph[0]["offers"]["@type"], "Offer")
        self.assertEqual(response.json()["types"], ["Product", "Brand"])
        self.assertFalse(response.json()["stale"])

    def test_custom_context_is_kept(self):
        self.store(self.local_suggestion())
        self.edit(json.dumps({"@context": "http://schema.org", "@type": "LocalBusiness", "name": "Klant BV",
                              "address": ADDRESS}))
        self.assertEqual(self.stored()["jsonld"]["@context"], "http://schema.org")

    def test_not_found(self):
        self.assertEqual(self.edit(json.dumps(_graph(LOCAL))).status_code, 404)  # nog geen voorstel
        self.store(self.local_suggestion())
        self.assertEqual(self.edit(json.dumps(_graph(LOCAL)), page_id="onbekend").status_code, 404)
        other = LaunchScan(
            id=str(uuid.uuid4()), customer_website_id=self.customer_id, phase=1, status="completed",
            base_url=f"{BASE}/", total_urls=0, inventoried_urls=0, failed_urls=0, max_pages=500,
            vitals_max_pages=0, vitals_total=0, vitals_measured=0, created_by="user-1", created_at=NOW,
            updated_at=NOW,
        )
        self.db.add(other)
        self.db.commit()
        self.assertEqual(self.edit(json.dumps(_graph(LOCAL)), scan_id=other.id).status_code, 404)
        self.assertNotIn("edited", self.stored())
        # Fase 2-scan ziet de pagina's van de bronscan.
        phase2 = LaunchScan(
            id=str(uuid.uuid4()), customer_website_id=self.customer_id, phase=2, status="completed",
            base_url=f"{BASE}/", total_urls=0, inventoried_urls=0, failed_urls=0, max_pages=500,
            vitals_max_pages=0, vitals_total=0, vitals_measured=0, created_by="user-1", created_at=NOW,
            updated_at=NOW, source_scan_id=self.scan.id,
        )
        self.db.add(phase2)
        self.db.commit()
        self.assertEqual(self.edit(json.dumps(_graph(LOCAL)), scan_id=phase2.id).status_code, 200)
        self.assertEqual(self.client.put(f"{self.path}/content", json={}).status_code, 422)


class EditReviewAndPlacementTest(_EditBase):
    def test_edit_resets_review_and_placement_current_but_keeps_placement(self):
        self.store(_suggestion())
        self.assertEqual(self.client.put(f"{self.path}/review", json={"status": "approved"}).status_code, 200)
        placed = self.place()
        self.assertEqual(placed.status_code, 200, placed.text)
        self.assertTrue(placed.json()["placement"]["current"])
        placement = self.placement()
        self.wp.calls.clear()
        self.fetch_mock.reset_mock()

        # Dezelfde JSON-LD opnieuw opslaan: goedkeuring en plaatsing blijven gelden.
        body = self.edit(json.dumps(_graph(SERVICE, BREADCRUMB))).json()
        self.assertEqual(body["review_status"], "approved")
        self.assertTrue(body["placement"]["current"])
        self.assertTrue(body["edited"])

        body = self.edit(json.dumps(_graph({**SERVICE, "name": "Dakwerk Utrecht"}, BREADCRUMB))).json()
        self.assertEqual((body["review_status"], body["reviewed_at"]), ("pending", None))
        self.assertIsNotNone(body["placement"])
        self.assertFalse(body["placement"]["current"])
        self.assertEqual(body["placement"]["post_id"], 42)
        self.assertEqual(self.placement(), placement)
        self.assertEqual(self.stored()["review"]["status"], "approved")  # bewaard, maar geldt niet meer
        # Bulkplaatsen weigert het niet-goedgekeurde, bewerkte voorstel zonder iets te versturen.
        self.assertEqual(self.client.post(f"{self.path}/place", json={"require_approved": True}).status_code, 400)
        self.assert_no_site_traffic()

    def test_edited_flag_in_all_responses(self):
        self.store(_suggestion())
        self.assertFalse(self.client.post(self.path, json={}).json()["edited"])
        edited = self.edit(json.dumps(_graph({**SERVICE, "name": "Dakwerk Utrecht"}, BREADCRUMB))).json()
        edited_at = edited["edited_at"]
        responses = {
            "openen": self.client.post(self.path, json={}),
            "beoordelen": self.client.put(f"{self.path}/review", json={"status": "approved"}),
            "plaatsen": self.place(),
            "verwijderen": self.remove(),
        }
        for name, response in responses.items():
            self.assertEqual(response.status_code, 200, f"{name}: {response.text}")
            self.assertTrue(response.json()["edited"], name)
            self.assertEqual(response.json()["edited_at"], edited_at, name)
        overview = self.client.post(f"/api/launch-checklist/scans/{self.scan.id}/schema-markup/overview",
                                    json={"page_ids": [self.page.id]}).json()
        self.assertTrue(overview["items"][0]["result"]["edited"])
        self.assertEqual(overview["items"][0]["result"]["edited_at"], edited_at)


class EditRegenerateTest(_EditBase):
    def test_edited_suggestion_is_not_regenerated_on_open(self):
        # Voorstel in een verouderde vorm (zonder bewaarde paginamarkup) wordt normaal bij openen opnieuw gemaakt.
        old = {k: v for k, v in _suggestion().items() if k != "existing_nodes"}
        self.store(old)
        self.assertTrue(schema_markup.outdated_format(old))
        self.edit(json.dumps(_graph({**SERVICE, "name": "Eigen naam"}, BREADCRUMB)))
        self.assertFalse(schema_markup.outdated_format(self.stored()))
        with patch(RUN_AGENT) as run:
            body = self.client.post(self.path, json={}).json()
        run.assert_not_called()
        self.fetch_mock.assert_not_called()
        self.assertTrue(body["cached"])
        self.assertTrue(body["edited"])
        self.assertIn("Eigen naam", body["script"])
        self.assertFalse(body["stale"])

    def test_regenerate_overwrites_and_clears_edited(self):
        self.store(_suggestion())
        self.edit(json.dumps(_graph({**SERVICE, "name": "Eigen naam"}, BREADCRUMB)))
        with patch(RUN_AGENT, return_value=_agent(_graph(SERVICE, BREADCRUMB))) as run:
            body = self.client.post(self.path, json={"regenerate": True}).json()
        run.assert_called_once()
        self.assertFalse(body["cached"])
        self.assertEqual((body["edited"], body["edited_at"]), (False, None))
        self.assertNotIn("edited", self.stored())
        self.assertNotIn("Eigen naam", body["script"])


# --- bedrijfsgegevens van de site in de brief ------------------------------------------------------

PAGE_URL = "https://www.klant.nl/diensten/dakwerk/"
ORG_ID = "https://www.klant.nl/#organization"


def _page_html(*nodes) -> str:
    script = f'<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@graph": list(nodes)})}</script>'
    return (f"<html><head><title>Dakwerk</title>{script}</head><body><main><h1>Dakwerk</h1>"
            "<p>Wij vernieuwen daken.</p></main></body></html>")


def _section(brief: str) -> str:
    return brief.split("Bedrijfsgegevens van de site", 1)[1].split("\n\n", 1)[0]


def _brief(html: str, home=None, targets=("LocalBusiness",)) -> str:
    facts = schema_markup.analyze_page(html, PAGE_URL, "klant.nl")
    return schema_markup.page_brief(facts, page_type="dienst", targets=list(targets), customer=None, home=home)


class BusinessFactsTest(unittest.TestCase):
    def test_address_from_long_jsonld_survives_truncation(self):
        org = {"@type": "Organization", "@id": ORG_ID, "name": "Klant BV", "url": "https://www.klant.nl/",
               "description": "Lang verhaal. " * 1000, "address": ADDRESS, "telephone": "+31301234567",
               "email": "info@klant.nl", "sameAs": ["https://www.facebook.com/klant"]}
        brief = _brief(_page_html(org))
        existing = brief.split("Bestaande JSON-LD", 1)[1].split("Paginagegevens:", 1)[0]
        self.assertIn("…(ingekort)", existing)
        self.assertNotIn("Hoofdstraat 1", existing)  # in de begrensde JSON-LD valt het adres weg
        section = _section(brief)
        self.assertIn('- address: {"@type":"PostalAddress","streetAddress":"Hoofdstraat 1","postalCode":"3511 AB",'
                      '"addressLocality":"Utrecht","addressCountry":"NL"} (bron: deze pagina)', section)
        self.assertIn("- telephone: +31301234567 (bron: deze pagina)", section)
        self.assertIn("- email: info@klant.nl (bron: deze pagina)", section)
        self.assertIn("- sameAs: https://www.facebook.com/klant (bron: deze pagina)", section)
        self.assertIn(f"- @id: {ORG_ID} (bron: deze pagina)", section)
        self.assertIn("volledige PostalAddress", section)
        self.assertIn("provider en publisher", section)
        self.assertNotIn("Lang verhaal", section)
        self.assertNotIn("Organisatie van de site (van de homepage", brief)

    def test_address_on_place_entity(self):
        # Zoals Rank Math een lokaal bedrijf schrijft: adres en coördinaten op de Place.
        org = {"@type": ["ProfessionalService", "Organization"], "@id": ORG_ID, "name": "Klant BV",
               "location": {"@id": "https://www.klant.nl/#place"},
               "logo": {"@id": "https://www.klant.nl/#logo"}}
        place = {"@type": "Place", "@id": "https://www.klant.nl/#place", "address": ADDRESS,
                 "geo": {"@type": "GeoCoordinates", "latitude": "52.09", "longitude": "5.12"},
                 "openingHoursSpecification": [{"@type": "OpeningHoursSpecification", "dayOfWeek": ["Monday"],
                                                "opens": "08:00", "closes": "17:00"}]}
        logo = {"@type": "ImageObject", "@id": "https://www.klant.nl/#logo", "url": "https://www.klant.nl/logo.png"}
        section = _section(_brief(_page_html(org, place, logo)))
        self.assertIn('"streetAddress":"Hoofdstraat 1"', section)
        self.assertIn('- geo: {"@type":"GeoCoordinates","latitude":"52.09","longitude":"5.12"}', section)
        self.assertIn('"opens":"08:00"', section)
        self.assertIn("- logo: https://www.klant.nl/logo.png (bron: deze pagina)", section)
        self.assertIn("- type: ProfessionalService, Organization (bron: deze pagina)", section)

    def test_address_only_on_homepage(self):
        org = {"@type": "Organization", "@id": ORG_ID, "name": "Klant BV"}
        home = [{"@type": "WebSite", "@id": "https://www.klant.nl/#website"},
                {"@type": "Organization", "@id": ORG_ID, "name": "Klant BV", "url": "https://www.klant.nl/",
                 "address": ADDRESS, "telephone": "+31301234567"}]
        section = _section(_brief(_page_html(org), home=home))
        self.assertIn("- name: Klant BV (bron: deze pagina)", section)
        self.assertIn('"streetAddress":"Hoofdstraat 1"', section)
        self.assertIn("(bron: homepage)", section.split("- address:", 1)[1].split("\n", 1)[0])
        self.assertIn("- telephone: +31301234567 (bron: homepage)", section)
        self.assertIn("- url: https://www.klant.nl/ (bron: homepage)", section)

    def test_other_organization_on_homepage_is_not_merged(self):
        org = {"@type": "Organization", "@id": "https://partner.nl/#org", "name": "Partner BV"}
        home = [{"@type": "Organization", "@id": ORG_ID, "name": "Klant BV", "address": ADDRESS}]
        section = _section(_brief(_page_html(org), home=home))
        self.assertNotIn("Hoofdstraat", section)

    def test_no_address_anywhere_invents_nothing(self):
        org = {"@type": "Organization", "@id": ORG_ID, "name": "Klant BV", "url": "https://www.klant.nl/"}
        home = [{"@type": "Organization", "@id": ORG_ID, "name": "Klant BV"}]
        brief = _brief(_page_html(org), home=home)
        section = _section(brief)
        self.assertNotIn("- address:", section)
        self.assertNotIn("PostalAddress", section.replace("volledige PostalAddress", ""))
        self.assertIn("Er staat geen adres bij de organisatie: verzin er geen", section)
        for key in ("telephone", "email", "geo", "openingHours", "sameAs", "logo"):
            self.assertNotIn(f"- {key}:", section)
        # Zonder organisatie op pagina en homepage: geen sectie.
        brief = _brief(_page_html({"@type": "WebPage", "@id": f"{PAGE_URL}#webpage"}), home=[])
        self.assertNotIn("Bedrijfsgegevens van de site", brief)

    def test_section_is_bounded(self):
        org = {"@type": "Organization", "@id": ORG_ID, "name": "Klant BV", "address": ADDRESS,
               "sameAs": [f"https://profiel{i}.nl/" + "x" * 500 for i in range(40)],
               "openingHours": ["Mo-Fr 08:00-17:00 " + "y" * 2000]}
        section = _section(_brief(_page_html(org)))
        self.assertLess(len(section), schema_markup.MAX_BUSINESS_CHARS + 2_000)
        self.assertIn('"streetAddress":"Hoofdstraat 1"', section)


class BusinessFactsGenerateTest(tsm._Base):
    """Via `generate_schema_markup`: de homepage-rij uit dezelfde scan vult aan."""

    def setUp(self):
        super().setUp()
        self.home = LaunchScanPage(
            id=str(uuid.uuid4()), scan_id=self.scan.id, url="https://www.klant.nl/", path="/", status_code=200,
            page_type="home", created_at=NOW,
            jsonld=[{"@type": "WebSite", "@id": "https://www.klant.nl/#website"},
                    {"@type": "Organization", "@id": ORG_ID, "name": "Klant BV", "url": "https://www.klant.nl/",
                     "address": ADDRESS, "telephone": "+31301234567"}],
        )
        self.db.add(self.home)
        self.page.schema_target_types = ["LocalBusiness"]
        self.db.commit()

    def _generate(self, html: str) -> str:
        output = {**tsm._agent_output(_graph({**LOCAL, "@id": f"{tsm.URL}#localbusiness", "address": ADDRESS}),
                                      placeholders=[]), "omitted": []}
        with patch(tsm.FETCH, return_value=(html, tsm.URL)), \
                patch(tsm.RUN_AGENT, return_value=tsm._result(output)) as run:
            schema_markup.generate_schema_markup(self.db, self.fresh_page(), user_id="user-1", regenerate=True)
        return run.call_args.kwargs["input"]

    def test_homepage_address_when_page_org_has_none(self):
        brief = self._generate(_page_html({"@type": "Organization", "@id": ORG_ID, "name": "Klant BV"}))
        section = _section(brief)
        self.assertIn('"streetAddress":"Hoofdstraat 1"', section)
        self.assertIn("- telephone: +31301234567 (bron: homepage)", section)
        self.assertNotIn("Organisatie van de site (van de homepage", brief)

    def test_homepage_organization_when_page_has_none(self):
        brief = self._generate(_page_html({"@type": "WebPage", "@id": f"{tsm.URL}#webpage"}))
        section = _section(brief)
        self.assertIn("Organisatie van de site (van de homepage; staat NIET op deze pagina):", section)
        self.assertIn(f"- @id: {ORG_ID} (bron: homepage)", section)
        self.assertIn('"postalCode":"3511 AB"', section)
        self.assertIn("publisher of provider", section)


if __name__ == "__main__":
    unittest.main()
