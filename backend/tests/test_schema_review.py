"""Livegang: schema in bulk doorzetten met menselijke controle.

Goedkeuren/afkeuren van het voorstel (`…/schema-markup/review`), plaatsen met
`require_approved` en het overzicht van meerdere pagina's (`…/schema-markup/overview`).

Er gebeurt nooit een echte HTTP-aanvraag of modelaanroep: WordPress en het ophalen van de
pagina zijn nagebootst (`FakeWordPress` uit `test_rankmath_schema`), `run_agent` is vervangen,
en elke echte netwerkverbinding via httpx laat de test falen. Database: SQLite.
"""
import json
import unittest
import uuid
from unittest.mock import patch

from app.agents.base import AgentRunResult
from app.db.models import LaunchScan, LaunchScanPage, WordPressSite
from app.features.launch_checklist.mappers import to_page_item
from app.features.launch_checklist.schema_markup_router import MAX_OVERVIEW_PAGES
from app.features.launch_checklist.services import rankmath_schema
from tests.test_rankmath_schema import BASE, BREADCRUMB, NOW, RUN_AGENT, SERVICE, URL, _Endpoint, _graph, _suggestion


def _agent(jsonld) -> AgentRunResult:
    return AgentRunResult(output=json.dumps({"jsonld": json.dumps(jsonld), "types": [], "placeholders": [],
                                             "notes": ""}), model="test", incomplete_reason=None)


class _ReviewBase(_Endpoint):
    def setUp(self):
        super().setUp()
        # Vangnet: een echte netwerkverbinding via httpx laat de test falen (MockTransport blijft werken).
        real_http = patch("httpx.HTTPTransport.handle_request",
                          side_effect=AssertionError("echte HTTP-aanroep in een test"))
        real_http.start()
        self.addCleanup(real_http.stop)

    def review(self, status: str, page_id: str | None = None, scan_id: str | None = None):
        path = (f"/api/launch-checklist/scans/{scan_id or self.scan.id}/pages/{page_id or self.page.id}"
                "/schema-markup/review")
        return self.client.put(path, json={"status": status})

    def place_approved(self):
        return self.client.post(f"{self.path}/place", json={"require_approved": True})

    def overview(self, page_ids, scan_id: str | None = None):
        return self.client.post(f"/api/launch-checklist/scans/{scan_id or self.scan.id}/schema-markup/overview",
                                json={"page_ids": page_ids})

    def stored_review(self) -> dict | None:
        return (self.fresh_page().schema_suggestion or {}).get("review")

    def add_scan(self, **extra) -> LaunchScan:
        scan = LaunchScan(
            id=str(uuid.uuid4()), customer_website_id=self.customer_id, phase=1, status="completed",
            base_url=f"{BASE}/", total_urls=0, inventoried_urls=0, failed_urls=0, max_pages=500,
            vitals_max_pages=0, vitals_total=0, vitals_measured=0, created_by="user-1", created_at=NOW,
            updated_at=NOW, **extra,
        )
        self.db.add(scan)
        self.db.commit()
        return scan

    def add_page(self, scan_id: str, path: str, *, suggestion: dict | None = None) -> LaunchScanPage:
        page = LaunchScanPage(id=str(uuid.uuid4()), scan_id=scan_id, url=f"{BASE}{path}", path=path,
                              status_code=200, title=f"Titel {path}", page_type="dienst", created_at=NOW,
                              schema_suggestion=suggestion, schema_suggestion_at=NOW if suggestion else None)
        self.db.add(page)
        self.db.commit()
        return page

    def assert_no_site_traffic(self):
        self.assertEqual(self.wp.calls, [])
        self.fetch_mock.assert_not_called()


# --- goedkeuren en afkeuren ---------------------------------------------------------------------

class ReviewEndpointTest(_ReviewBase):
    def test_approve_reject_and_reset(self):
        self.store(_suggestion())
        initial = self.client.post(self.path, json={}).json()
        self.assertEqual((initial["review_status"], initial["reviewed_at"]), ("pending", None))

        response = self.review("approved")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["review_status"], "approved")
        self.assertIsNotNone(body["reviewed_at"])
        self.assertTrue(body["cached"])
        self.assertTrue(body["can_place"])
        review = self.stored_review()
        self.assertEqual((review["status"], review["user_id"]), ("approved", "user-1"))
        self.assertEqual(review["jsonld_hash"], rankmath_schema.jsonld_hash(_suggestion()["jsonld"]))
        self.assertTrue(review["reviewed_at"])
        # De rest van het voorstel blijft staan.
        self.assertEqual(self.fresh_page().schema_suggestion["jsonld"], _suggestion()["jsonld"])

        body = self.review("rejected").json()
        self.assertEqual(body["review_status"], "rejected")
        self.assertIsNotNone(body["reviewed_at"])

        body = self.review("pending").json()
        self.assertEqual((body["review_status"], body["reviewed_at"]), ("pending", None))
        # Geen modelaanroep en niets naar de klantsite.
        self.assert_no_site_traffic()

    def test_not_found_and_invalid_status(self):
        self.assertEqual(self.review("approved").status_code, 404)  # nog geen voorstel
        self.store(_suggestion())
        self.assertEqual(self.review("approved", page_id="onbekend").status_code, 404)
        other = self.add_scan()
        self.assertEqual(self.review("approved", scan_id=other.id).status_code, 404)
        self.assertEqual(self.review("goedgekeurd").status_code, 422)
        self.assertIsNone(self.stored_review())

    def test_approve_refused_when_placing_is_not_allowed(self):
        self.store(_suggestion(placeholders=["[prijs]"]))
        response = self.review("approved")
        self.assertEqual(response.status_code, 400)
        self.assertIn("plaatshouders ([prijs])", response.json()["detail"])
        self.assertIsNone(self.stored_review())
        # Afkeuren en terugzetten mag altijd.
        self.assertEqual(self.review("rejected").json()["review_status"], "rejected")
        self.assertEqual(self.review("pending").json()["review_status"], "pending")

        self.store(_suggestion())
        site = self.db.get(WordPressSite, self.site.id)
        site.is_active = False
        self.db.commit()
        response = self.review("approved")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], rankmath_schema.NO_SITE)
        self.assert_no_site_traffic()

    def test_regenerate_with_other_jsonld_resets_to_pending(self):
        self.store(_suggestion())
        self.assertEqual(self.review("approved").status_code, 200)
        # Opnieuw genereren met dezelfde JSON-LD: de goedkeuring blijft gelden.
        with patch(RUN_AGENT, return_value=_agent(_graph(SERVICE, BREADCRUMB))):
            body = self.client.post(self.path, json={"regenerate": True}).json()
        self.assertFalse(body["cached"])
        self.assertEqual(body["review_status"], "approved")
        # Andere JSON-LD: weer "pending", ook in de lijst en voor bulkplaatsen.
        with patch(RUN_AGENT, return_value=_agent(_graph({**SERVICE, "name": "Dakwerk Utrecht"}, BREADCRUMB))):
            body = self.client.post(self.path, json={"regenerate": True}).json()
        self.assertEqual((body["review_status"], body["reviewed_at"]), ("pending", None))
        self.assertIsNone(to_page_item(self.fresh_page()).schema_review_status)
        self.wp.calls.clear()
        self.fetch_mock.reset_mock()
        self.assertEqual(self.place_approved().status_code, 400)
        self.assert_no_site_traffic()

    def test_changed_jsonld_invalidates_rejection_too(self):
        self.store(_suggestion())
        self.assertEqual(self.review("rejected").status_code, 200)
        suggestion = dict(self.fresh_page().schema_suggestion)
        suggestion["jsonld"] = _graph(SERVICE)
        self.store(suggestion)
        body = self.client.post(self.path, json={}).json()
        self.assertEqual(body["review_status"], "pending")

    def test_nothing_missing_is_pending(self):
        self.page.page_type = "overig"
        self.db.commit()
        self.store(_suggestion())
        self.assertEqual(self.review("approved").status_code, 200)
        with patch(RUN_AGENT) as run:
            body = self.client.post(self.path, json={"regenerate": True}).json()
        run.assert_not_called()
        self.assertTrue(body["nothing_missing"])
        self.assertEqual((body["review_status"], body["reviewed_at"]), ("pending", None))


# --- plaatsen met require_approved ----------------------------------------------------------------

class PlaceRequireApprovedTest(_ReviewBase):
    def test_refused_without_approval_and_nothing_sent(self):
        self.store(_suggestion())
        for status in (None, "rejected", "pending"):
            if status:
                self.assertEqual(self.review(status).status_code, 200)
            response = self.place_approved()
            self.assertEqual(response.status_code, 400, status)
            self.assertIn("nog niet goedgekeurd", response.json()["detail"])
            self.assertEqual(response.json()["detail"], rankmath_schema.NOT_APPROVED)
            # Geen enkele HTTP-aanroep: niet naar WordPress en de pagina niet opgehaald.
            self.assert_no_site_traffic()
            self.assertIsNone(self.placement())

    def test_refused_without_suggestion(self):
        response = self.place_approved()
        self.assertEqual(response.status_code, 400)
        self.assertIn("nog niet goedgekeurd", response.json()["detail"])
        self.assert_no_site_traffic()

    def test_approval_of_older_suggestion_does_not_count(self):
        self.store(_suggestion())
        self.assertEqual(self.review("approved").status_code, 200)
        suggestion = dict(self.fresh_page().schema_suggestion)
        suggestion["jsonld"] = _graph(SERVICE)  # opnieuw gegenereerd na de goedkeuring
        self.store(suggestion)
        response = self.place_approved()
        self.assertEqual(response.status_code, 400)
        self.assertIn("nog niet goedgekeurd", response.json()["detail"])
        self.assert_no_site_traffic()

    def test_places_with_approval_and_approval_stays(self):
        self.store(_suggestion())
        self.assertEqual(self.review("approved").status_code, 200)
        response = self.place_approved()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["placement"]["current"])
        self.assertEqual(body["review_status"], "approved")
        self.assertEqual(set(self.wp.schemas), {500, 501})
        # Precies de goedgekeurde JSON-LD staat op de site.
        self.assertEqual(self.placement()["jsonld_hash"], self.stored_review()["jsonld_hash"])
        self.assertEqual(to_page_item(self.fresh_page()).schema_review_status, "approved")
        # Na "Verwijder van site" blijft de goedkeuring ook staan.
        removed = self.client.delete(f"{self.path}/place")
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertIsNone(removed.json()["placement"])
        self.assertEqual(removed.json()["review_status"], "approved")
        self.assertEqual(self.stored_review()["status"], "approved")

    def test_without_flag_places_as_before(self):
        self.store(_suggestion())
        self.assertEqual(self.client.post(f"{self.path}/place", json={"require_approved": False}).status_code, 200)
        self.assertEqual(self.place().status_code, 200)  # zonder body
        self.assertEqual(self.place().json()["review_status"], "pending")


# --- overzicht -----------------------------------------------------------------------------------

class OverviewEndpointTest(_ReviewBase):
    def test_with_and_without_suggestion_in_request_order(self):
        self.store(_suggestion())
        self.assertEqual(self.review("approved").status_code, 200)
        without = self.add_page(self.scan.id, "/zonder-voorstel/")
        other_scan = self.add_scan()
        elsewhere = self.add_page(other_scan.id, "/andere-scan/", suggestion=_suggestion())

        response = self.overview([without.id, "bestaat-niet", self.page.id, elsewhere.id])
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        self.assertEqual([i["page_id"] for i in items], [without.id, self.page.id])

        first = items[0]
        self.assertEqual((first["url"], first["path"], first["title"], first["page_type"]),
                         (f"{BASE}/zonder-voorstel/", "/zonder-voorstel/", "Titel /zonder-voorstel/", "dienst"))
        self.assertIsNone(first["result"])

        second = items[1]
        self.assertEqual((second["url"], second["path"], second["title"]), (URL, "/diensten/dakwerk/", "Dakwerk"))
        result = second["result"]
        self.assertTrue(result["cached"])
        self.assertTrue(result["generated_at"].startswith("2026-11-16T12:00:00"))
        self.assertEqual(result["review_status"], "approved")
        self.assertIsNotNone(result["reviewed_at"])
        self.assertTrue(result["can_place"])
        self.assertIsNone(result["placement"])
        self.assertIn('"@type": "Service"', result["script"])
        # Alleen database: geen modelaanroep, niets naar de klantsite.
        self.assert_no_site_traffic()

    def test_phase2_scan_sees_pages_of_source_scan(self):
        self.store(_suggestion())
        phase2 = self.add_scan(source_scan_id=self.scan.id)
        own = self.add_page(phase2.id, "/fase-2/")
        items = self.overview([self.page.id, own.id], scan_id=phase2.id).json()["items"]
        self.assertEqual([i["page_id"] for i in items], [self.page.id, own.id])
        # Andersom niet: de bronscan ziet de pagina's van de fase 2-scan niet.
        items = self.overview([self.page.id, own.id]).json()["items"]
        self.assertEqual([i["page_id"] for i in items], [self.page.id])

    def test_limit_and_empty(self):
        ids = [str(uuid.uuid4()) for _ in range(MAX_OVERVIEW_PAGES)]
        self.assertEqual(self.overview(ids).status_code, 200)
        response = self.overview(ids + [self.page.id])
        self.assertEqual(response.status_code, 400)
        self.assertIn(str(MAX_OVERVIEW_PAGES), response.json()["detail"])
        self.assertEqual(self.overview([]).json(), {"items": []})
        self.assertEqual(self.overview([self.page.id, self.page.id]).json()["items"][0]["page_id"], self.page.id)
        self.assertEqual(len(self.overview([self.page.id, self.page.id]).json()["items"]), 1)


# --- lijstrespons --------------------------------------------------------------------------------

class PageListReviewStatusTest(_ReviewBase):
    def test_schema_review_status_in_list(self):
        self.assertIsNone(to_page_item(self.fresh_page()).schema_review_status)
        self.store(_suggestion())
        self.assertIsNone(to_page_item(self.fresh_page()).schema_review_status)
        self.review("approved")
        item = to_page_item(self.fresh_page()).model_dump()
        self.assertEqual(item["schema_review_status"], "approved")
        self.assertNotIn("schema_suggestion", item)
        self.assertNotIn("review", item)
        self.review("rejected")
        self.assertEqual(to_page_item(self.fresh_page()).schema_review_status, "rejected")
        self.review("pending")
        self.assertIsNone(to_page_item(self.fresh_page()).schema_review_status)
        self.review("approved")
        suggestion = dict(self.fresh_page().schema_suggestion)
        suggestion["jsonld"] = _graph(SERVICE)
        self.store(suggestion)
        self.assertIsNone(to_page_item(self.fresh_page()).schema_review_status)


if __name__ == "__main__":
    unittest.main()
