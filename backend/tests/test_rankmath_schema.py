"""Livegang: het schema-voorstel in Rank Math plaatsen ("Plaats in Rank Math").

Er gebeurt nooit een echte HTTP-aanvraag: `wordpress_service._request` gaat naar een
`httpx.MockTransport` met een kleine nabootsing van WordPress + Rank Math (`FakeWordPress`),
en `fetch_page_html` geeft de HTML die die nabootsing op dat moment zou tonen. Het gedrag
volgt de proef op een echte site (zie `services/rankmath_schema.py`). Database: SQLite.
"""
import json
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import require_user_id
from app.db.models import CustomerCategory, CustomerWebsite, LaunchScan, LaunchScanPage, WordPressSite
from app.db.session import get_db
from app.features.blogs.services.crypto_service import encrypt_secret
from app.features.launch_checklist.mappers import to_page_item
from app.features.launch_checklist.schema_markup_router import router
from app.features.launch_checklist.services import rankmath_schema, schema_markup

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
BASE = "https://www.klant.nl"
URL = f"{BASE}/diensten/dakwerk/"
SM = "app.features.launch_checklist.services.schema_markup"
FETCH = f"{SM}.fetch_page_html"
RUN_AGENT = f"{SM}.run_agent"
WP_REQUEST = "app.features.blogs.services.wordpress_service._request"

SERVICE = {"@type": "Service", "@id": f"{URL}#service", "name": "Dakwerk",
           "provider": {"@id": f"{BASE}/#organization"}}
BREADCRUMB = {"@type": "BreadcrumbList", "itemListElement": [
    {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{BASE}/"},
    {"@type": "ListItem", "position": 2, "name": "Dakwerk", "item": URL},
]}
FAQ = {"@type": "FAQPage", "mainEntity": [
    {"@type": "Question", "name": "Wat kost een dak?", "acceptedAnswer": {"@type": "Answer", "text": "Dat hangt ervan af."}},
]}


def _graph(*nodes) -> dict:
    return {"@context": "https://schema.org", "@graph": list(nodes)}


def _suggestion(jsonld=None, **extra) -> dict:
    return {"jsonld": jsonld or _graph(SERVICE, BREADCRUMB), "types": ["Service", "BreadcrumbList"],
            "placeholders": [], "notes": "", "problems": [], "existing_nodes": [], **extra}


class FakeWordPress:
    """WordPress met Rank Math, zoals vastgesteld in de proef."""

    def __init__(self, *, rank_math: bool = True, default_type: str = "Article"):
        self.rank_math = rank_math
        self.default_type = default_type
        self.pages = [{"id": 42, "link": URL}]
        self.posts: list[dict] = []
        self.products: list[dict] = []
        self.page_on_front = 7
        self.schemas: dict[int, dict] = {}
        self.next_id = 500
        self.rich_snippet = ""
        self.calls: list[tuple[str, str, dict | None]] = []
        self.fail: dict[str, httpx.Response] = {}

    # --- REST ---
    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Basic "), "zonder Basic-auth"
        route = request.url.path.split("/wp-json/", 1)[1]
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, route, body))
        if route in self.fail:
            return self.fail[route]
        query = parse_qs(request.url.query.decode())
        slug = (query.get("slug") or [""])[0]
        if request.method == "GET" and route == "wp/v2/settings":
            return httpx.Response(200, json={"page_on_front": self.page_on_front})
        if request.method == "GET" and route == "wp/v2/types":
            return httpx.Response(200, json={
                "post": {"rest_base": "posts", "rest_namespace": "wp/v2"},
                "page": {"rest_base": "pages", "rest_namespace": "wp/v2"},
                "attachment": {"rest_base": "media", "rest_namespace": "wp/v2"},
                "wp_block": {"rest_base": "blocks", "rest_namespace": "wp/v2"},
                "product": {"rest_base": "products", "rest_namespace": "wp/v2"},
            })
        lists = {"wp/v2/pages": self.pages, "wp/v2/posts": self.posts, "wp/v2/products": self.products}
        if request.method == "GET" and route in lists:
            return httpx.Response(200, json=[i for i in lists[route] if i["link"].rstrip("/").endswith("/" + slug)])
        if request.method == "POST" and route == "rankmath/v1/updateSchemas":
            new_ids = {}
            for key, schema in body["schemas"].items():
                if key.startswith("new-"):
                    self.schemas[self.next_id] = schema
                    new_ids[key] = self.next_id
                    self.next_id += 1
                else:
                    self.schemas[int(key.removeprefix("schema-"))] = schema
            return httpx.Response(200, json=new_ids or [])
        if request.method == "POST" and route == "rankmath/v1/updateMeta":
            deleted = False
            for key in body["meta"]:
                if key.startswith("rank_math_delete_schema-"):
                    self.schemas.pop(int(key.rsplit("-", 1)[1]), None)
                    self.rich_snippet = "off"
                    deleted = True
                elif key == "rank_math_rich_snippet":
                    self.rich_snippet = body["meta"][key]
            if not deleted:
                return httpx.Response(200, json={"slug": True})
            remaining = {f"schema-{i}": s for i, s in self.schemas.items()}
            return httpx.Response(200, json={"slug": True, "schemas": remaining or []})
        return httpx.Response(404, json={"code": "rest_no_route", "message": "Geen route gevonden."})

    def request(self, method, url, *, headers=None, json_payload=None, raw_payload=None, follow_redirects=True):
        with httpx.Client(transport=httpx.MockTransport(self.handle)) as client:
            return client.request(method, url, headers=headers, json=json_payload)

    def writes(self) -> list[tuple[str, str, dict | None]]:
        return [c for c in self.calls if c[0] == "POST"]

    # --- HTML ---
    def html(self, url: str = URL) -> str:
        webpage = {"@type": "WebPage", "@id": f"{URL}#webpage", "url": URL, "name": "Dakwerk"}
        graph = [{"@type": "Organization", "@id": f"{BASE}/#organization", "name": "Klant BV"},
                 {"@type": "WebSite", "@id": f"{BASE}/#website", "url": f"{BASE}/"}, webpage]
        if self.schemas:
            for meta_id, schema in self.schemas.items():
                node = {k: v for k, v in schema.items() if k != "metadata"}
                node.setdefault("@id", f"{URL}#schema-{meta_id}")
                if node["@type"] == "FAQPage":  # Rank Math voegt een FAQPage samen met de WebPage
                    webpage["@type"] = ["WebPage", "FAQPage"]
                    webpage["mainEntity"] = node["mainEntity"]
                    continue
                graph.append(node)
        elif self.rich_snippet == "off":
            graph = [BREADCRUMB]
        else:
            author = f"{BASE}/author/jan/"
            graph += [{"@type": self.default_type, "@id": f"{URL}#richSnippet", "headline": "Dakwerk",
                       "author": {"@id": author, "name": "Jan"}, "isPartOf": {"@id": f"{URL}#webpage"}},
                      {"@type": "Person", "@id": author, "name": "Jan"}]
        css = ' class="rank-math-schema"' if self.rank_math else ""
        script = f'<script type="application/ld+json"{css}>{json.dumps(_graph(*graph))}</script>'
        return f"<html><head><title>Dakwerk</title>{script}</head><body><main><h1>Dakwerk</h1></main></body></html>"

    def fetch(self, url: str):
        return self.html(url), url.split("?", 1)[0]


class _Base(unittest.TestCase):
    page_type = "dienst"
    page_url = URL

    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        for model in (CustomerCategory, CustomerWebsite, LaunchScan, LaunchScanPage, WordPressSite):
            model.__table__.create(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)

        self.customer_id = str(uuid.uuid4())
        self.db.add(CustomerWebsite(id=self.customer_id, name="Klant BV", base_url="https://klant.nl/",
                                    domain="klant.nl", created_by="user-1", created_at=NOW, updated_at=NOW))
        self.site = WordPressSite(id=str(uuid.uuid4()), name="Klant WP", base_url=BASE, wp_login="admin",
                                  app_password_encrypted=encrypt_secret("abcd efgh"), is_active=True,
                                  created_by="user-1", created_at=NOW, updated_at=NOW)
        self.db.add(self.site)
        self.scan = LaunchScan(
            id=str(uuid.uuid4()), customer_website_id=self.customer_id, phase=1, status="completed",
            base_url=f"{BASE}/", total_urls=0, inventoried_urls=0, failed_urls=0, max_pages=500,
            vitals_max_pages=0, vitals_total=0, vitals_measured=0, created_by="user-1", created_at=NOW,
            updated_at=NOW,
        )
        self.db.add(self.scan)
        self.page = LaunchScanPage(id=str(uuid.uuid4()), scan_id=self.scan.id, url=self.page_url,
                                   path=urlparse(self.page_url).path, status_code=200, title="Dakwerk",
                                   page_type=self.page_type, created_at=NOW)
        self.db.add(self.page)
        self.db.commit()

        self.wp = FakeWordPress()
        request_patch = patch(WP_REQUEST, side_effect=self.wp.request)
        fetch_patch = patch(FETCH, side_effect=self.wp.fetch)
        request_patch.start()
        self.fetch_mock = fetch_patch.start()
        self.addCleanup(request_patch.stop)
        self.addCleanup(fetch_patch.stop)

    def store(self, suggestion: dict):
        self.page.schema_suggestion = suggestion
        self.page.schema_suggestion_at = NOW
        self.db.commit()

    def fresh_page(self) -> LaunchScanPage:
        self.db.expire_all()
        return self.db.get(LaunchScanPage, self.page.id)

    def placement(self) -> dict | None:
        return (self.fresh_page().schema_suggestion or {}).get("placement")


class _Endpoint(_Base):
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

    def place(self):
        return self.client.post(f"{self.path}/place")

    def remove(self):
        return self.client.delete(f"{self.path}/place")


# --- pure logica -------------------------------------------------------------------------------

class ConversionTest(unittest.TestCase):
    def test_graph_items_become_custom_schemas(self):
        schemas = rankmath_schema.to_rankmath_schemas(_graph(SERVICE, BREADCRUMB))
        self.assertEqual([(k, t) for k, t, _ in schemas], [("Service", "Service"), ("BreadcrumbList", "BreadcrumbList")])
        service = schemas[0][2]
        self.assertEqual(service["metadata"], {"title": "Service", "type": "custom", "isPrimary": False})
        # Eigen @id en verwijzingen blijven staan; @context niet.
        self.assertEqual(service["@id"], f"{URL}#service")
        self.assertEqual(service["provider"], {"@id": f"{BASE}/#organization"})
        self.assertNotIn("@context", service)
        self.assertNotIn("@id", schemas[1][2])

    def test_same_type_twice_and_single_node(self):
        two = rankmath_schema.to_rankmath_schemas(_graph({"@type": "Person", "name": "A"},
                                                         {"@type": ["Person"], "name": "B"}))
        self.assertEqual([k for k, _, _ in two], ["Person", "Person 2"])
        single = rankmath_schema.to_rankmath_schemas({"@context": "https://schema.org", **SERVICE})
        self.assertEqual(len(single), 1)
        self.assertNotIn("@context", single[0][2])


class RankMathFactsTest(unittest.TestCase):
    def test_default_schema_and_graph(self):
        facts = schema_markup.rank_math_facts(FakeWordPress().html())
        self.assertTrue(facts.detected)
        self.assertEqual(facts.default_types, ["Article", "Person"])
        self.assertTrue(facts.had_graph)
        self.assertEqual(facts.kept_types, {"Organization", "WebSite", "WebPage"})

    def test_without_rank_math(self):
        facts = schema_markup.rank_math_facts(FakeWordPress(rank_math=False).html())
        self.assertFalse(facts.detected)
        self.assertEqual(facts.default_types, [])
        self.assertFalse(facts.had_graph)

    def test_placed_nodes_are_stripped(self):
        wp = FakeWordPress()
        wp.schemas = {500: {**SERVICE, "metadata": {}}, 501: {**BREADCRUMB, "metadata": {}}, 502: {**FAQ, "metadata": {}}}
        placement = {"items": [{"key": "Service", "type": "Service", "meta_id": 500, "node_id": f"{URL}#service"},
                               {"key": "BreadcrumbList", "type": "BreadcrumbList", "meta_id": 501, "node_id": None},
                               {"key": "FAQPage", "type": "FAQPage", "meta_id": 502, "node_id": None}]}
        facts = schema_markup.analyze_page(wp.html(), URL, "klant.nl", placement=placement)
        self.assertEqual(facts.existing_types, {"Organization", "WebSite", "WebPage"})
        self.assertNotIn("#service", "\n".join(facts.blocks))
        self.assertEqual(schema_markup.analyze_page(wp.html(), URL, "klant.nl").existing_types,
                         {"Organization", "WebSite", "WebPage", "Service", "BreadcrumbList", "ListItem",
                          "FAQPage", "Question", "Answer"})


class PlacementCheckTest(unittest.TestCase):
    def test_reasons(self):
        check = rankmath_schema.placement_check
        self.assertEqual(check(None, "dienst")[0], rankmath_schema.NO_SUGGESTION)
        reason, _ = check(_suggestion(placeholders=["[prijs]"]), "dienst")
        self.assertIn("plaatshouders ([prijs])", reason)
        self.assertEqual(check(_suggestion(), "dienst", site_problem=rankmath_schema.NO_SITE)[0],
                         rankmath_schema.NO_SITE)
        self.assertEqual(check(_suggestion(rank_math_detected=False), "dienst")[0], rankmath_schema.NO_RANK_MATH)

    def test_unknown_fields_allow_with_empty_replaces(self):
        self.assertEqual(rankmath_schema.placement_check(_suggestion(), "dienst"), ("", []))

    def test_unexpected_default_type_is_replaced(self):
        suggestion = _suggestion(rank_math_detected=True, default_types=["Article", "Person"], had_graph=True,
                                 kept_types=["Organization", "WebPage", "WebSite"])
        self.assertEqual(rankmath_schema.placement_check(suggestion, "dienst"), ("", ["Article", "Person"]))

    def test_expected_default_type_blocks(self):
        suggestion = _suggestion(_graph(BREADCRUMB), rank_math_detected=True, default_types=["BlogPosting", "Person"],
                                 had_graph=True, kept_types=["Organization", "WebPage"])
        reason, replaces = rankmath_schema.placement_check(suggestion, "blog")
        self.assertIn("BlogPosting of Article, Person", reason)
        self.assertEqual(replaces, [])
        # Zet het voorstel zelf een Article neer, dan vervalt er niets wat verwacht wordt
        # (het standaard-BlogPosting wel, en dat wordt gemeld).
        suggestion["jsonld"] = _graph({"@type": "Article", "author": {"@type": "Person", "name": "Jan"}}, BREADCRUMB)
        self.assertEqual(rankmath_schema.placement_check(suggestion, "blog"), ("", ["BlogPosting"]))


# --- plaatsen en verwijderen ----------------------------------------------------------------

class PlaceEndpointTest(_Endpoint):
    def test_first_place_adds_new_schemas_and_verifies(self):
        self.store(_suggestion())
        response = self.place()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        # Opzoeken op slug, één schrijfactie met twee nieuwe schema's.
        self.assertIn(("GET", "wp/v2/pages", None), [(m, r, b) for m, r, b in self.wp.calls])
        writes = self.wp.writes()
        self.assertEqual(len(writes), 1)
        _, route, payload = writes[0]
        self.assertEqual(route, "rankmath/v1/updateSchemas")
        self.assertEqual((payload["objectType"], payload["objectID"]), ("post", 42))
        self.assertTrue(all(k.startswith("new-") for k in payload["schemas"]))
        self.assertEqual([s["metadata"]["type"] for s in payload["schemas"].values()], ["custom", "custom"])
        self.assertEqual(set(self.wp.schemas), {500, 501})

        placement = self.placement()
        self.assertEqual([(i["type"], i["meta_id"]) for i in placement["items"]],
                         [("Service", 500), ("BreadcrumbList", 501)])
        self.assertEqual((placement["post_id"], placement["site_id"], placement["had_graph"]), (42, self.site.id, True))
        self.assertEqual(placement["default_types"], ["Article", "Person"])
        self.assertTrue(placement["verified"])

        self.assertEqual(body["placement"]["site_name"], "Klant WP")
        self.assertEqual(body["placement"]["post_id"], 42)
        self.assertTrue(body["placement"]["verified"])
        self.assertTrue(body["placement"]["current"])
        self.assertTrue(body["can_place"])
        self.assertEqual(body["place_blocked_reason"], "")
        self.assertEqual(body["replaces_default_types"], ["Article", "Person"])
        self.assertTrue(body["cached"])
        self.assertIn('"@type": "Service"', body["script"])
        # De controle na het plaatsen omzeilt de cache.
        self.assertIn(f"?{rankmath_schema.CACHE_BUSTER}=", self.fetch_mock.call_args_list[-1].args[0])

    def test_second_place_updates_without_duplicates(self):
        self.store(_suggestion())
        self.assertEqual(self.place().status_code, 200)
        self.wp.calls.clear()
        response = self.place()
        self.assertEqual(response.status_code, 200, response.text)
        writes = self.wp.writes()
        self.assertEqual(len(writes), 1)
        self.assertEqual(set(writes[0][2]["schemas"]), {"schema-500", "schema-501"})
        self.assertEqual(set(self.wp.schemas), {500, 501})
        # Geen nieuwe opzoeking: het post-ID komt uit de plaatsing.
        self.assertFalse([c for c in self.wp.calls if c[1].startswith("wp/v2/")])
        self.assertTrue(response.json()["placement"]["verified"])

    def test_dropped_type_is_removed(self):
        self.store(_suggestion())
        self.assertEqual(self.place().status_code, 200)
        suggestion = dict(self.fresh_page().schema_suggestion)
        suggestion["jsonld"] = _graph(SERVICE)
        self.store(suggestion)
        self.wp.calls.clear()
        response = self.place()
        self.assertEqual(response.status_code, 200, response.text)
        writes = self.wp.writes()
        self.assertEqual([w[1] for w in writes], ["rankmath/v1/updateSchemas", "rankmath/v1/updateMeta"])
        self.assertEqual(set(writes[0][2]["schemas"]), {"schema-500"})
        self.assertEqual(writes[1][2]["meta"], {"rank_math_delete_schema-501": ""})
        self.assertEqual(set(self.wp.schemas), {500})
        self.assertEqual([i["meta_id"] for i in self.placement()["items"]], [500])
        self.assertTrue(response.json()["placement"]["current"])

    def test_failed_removal_of_dropped_type_is_retried(self):
        self.store(_suggestion())
        self.assertEqual(self.place().status_code, 200)
        suggestion = dict(self.fresh_page().schema_suggestion)
        suggestion["jsonld"] = _graph(SERVICE)
        self.store(suggestion)
        self.wp.fail["rankmath/v1/updateMeta"] = httpx.Response(500, json={"message": "Databasefout."})
        response = self.place()
        self.assertEqual(response.status_code, 502)
        self.assertIn("Databasefout.", response.json()["detail"])
        # Het vervallen item blijft vastgelegd, zodat een volgende poging het alsnog verwijdert.
        self.assertEqual([i["meta_id"] for i in self.placement()["items"]], [500, 501])
        del self.wp.fail["rankmath/v1/updateMeta"]
        self.assertEqual(self.place().status_code, 200)
        self.assertEqual(set(self.wp.schemas), {500})
        self.assertEqual([i["meta_id"] for i in self.placement()["items"]], [500])

    def test_faqpage_merged_into_webpage_counts_as_verified(self):
        self.store(_suggestion(_graph(SERVICE, FAQ)))
        response = self.place()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["placement"]["verified"])

    def test_not_verified_when_types_missing_from_html(self):
        self.store(_suggestion())
        with patch.object(self.wp, "html", return_value=FakeWordPress().html()):
            response = self.place()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["placement"]["verified"])

    def test_post_type_lookup_and_homepage(self):
        self.store(_suggestion())
        self.wp.pages = []
        self.wp.products = [{"id": 77, "link": "https://klant.nl/diensten/dakwerk"}]  # zonder www en slash
        self.assertEqual(self.place().status_code, 200)
        self.assertEqual(self.placement()["post_id"], 77)

        wp = rankmath_schema._WordPress(site_id="s", name="n", base_url=BASE, headers={"Authorization": "Basic x"})
        self.assertEqual(rankmath_schema.resolve_post_id(wp, "https://klant.nl/"), 7)
        self.wp.page_on_front = 0
        with self.assertRaises(rankmath_schema.RankMathPlacementBlocked) as ctx:
            rankmath_schema.resolve_post_id(wp, f"{BASE}/")
        self.assertIn("homepage", str(ctx.exception))

    def test_post_id_not_found(self):
        self.store(_suggestion())
        self.wp.pages = [{"id": 9, "link": f"{BASE}/andere-map/dakwerk/"}]  # zelfde slug, andere URL
        response = self.place()
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("niet als bericht of pagina", response.json()["detail"])
        self.assertEqual(self.wp.writes(), [])
        self.assertIsNone(self.placement())

    def test_no_linked_site(self):
        self.store(_suggestion())
        for change in ({"base_url": "https://andere-klant.nl"}, {"created_by": "user-2"}, {"is_active": False}):
            site = self.db.get(WordPressSite, self.site.id)
            original = {k: getattr(site, k) for k in change}
            for k, v in change.items():
                setattr(site, k, v)
            self.db.commit()
            response = self.place()
            self.assertEqual(response.status_code, 400, change)
            self.assertIn("Koppel de site bij Instellingen > WordPress", response.json()["detail"])
            generated = self.client.post(self.path, json={}).json()
            self.assertFalse(generated["can_place"])
            self.assertIn("Koppel de site bij Instellingen > WordPress", generated["place_blocked_reason"])
            for k, v in original.items():
                setattr(site, k, v)
            self.db.commit()
        self.assertEqual(self.wp.calls, [])

    def test_www_in_site_url_is_ignored(self):
        self.store(_suggestion())
        site = self.db.get(WordPressSite, self.site.id)
        site.base_url = "https://klant.nl"
        self.db.commit()
        self.assertEqual(self.place().status_code, 200)

    def test_placeholders_block_without_any_request(self):
        self.store(_suggestion(placeholders=["[naam van de dienstenpagina]"]))
        response = self.place()
        self.assertEqual(response.status_code, 400)
        self.assertIn("plaatshouders", response.json()["detail"])
        self.assertEqual(self.wp.calls, [])
        self.fetch_mock.assert_not_called()

    def test_expected_default_type_blocks_on_fresh_page(self):
        self.page.page_type = "blog"
        self.db.commit()
        self.store(_suggestion(_graph(BREADCRUMB)))  # oud voorstel: Rank Math-velden onbekend
        self.wp.default_type = "BlogPosting"
        generated = self.client.post(self.path, json={}).json()
        self.assertTrue(generated["can_place"])  # onbekend → het plaats-endpoint beslist
        self.assertEqual(generated["replaces_default_types"], [])
        response = self.place()
        self.assertEqual(response.status_code, 400)
        self.assertIn("BlogPosting of Article", response.json()["detail"])
        self.assertEqual(self.wp.writes(), [])

    def test_rank_math_not_detected(self):
        self.store(_suggestion())
        self.wp.rank_math = False
        response = self.place()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], rankmath_schema.NO_RANK_MATH)
        self.assertEqual(self.wp.calls, [])

    def test_wordpress_error_gives_502(self):
        self.store(_suggestion())
        self.wp.fail["rankmath/v1/updateSchemas"] = httpx.Response(
            403, json={"code": "rest_forbidden", "message": "Sorry, je mag dit niet doen."})
        response = self.place()
        self.assertEqual(response.status_code, 502)
        self.assertIn("Sorry, je mag dit niet doen.", response.json()["detail"])
        self.assertIsNone(self.placement())
        self.wp.fail["rankmath/v1/updateSchemas"] = httpx.Response(500, text="<html>kapot</html>")
        response = self.place()
        self.assertEqual(response.status_code, 502)
        self.assertIn("status 500", response.json()["detail"])

    def test_page_fetch_error_gives_502(self):
        self.store(_suggestion())
        self.fetch_mock.side_effect = schema_markup.SchemaMarkupError("De pagina kon niet worden opgehaald (status 503).")
        response = self.place()
        self.assertEqual(response.status_code, 502)
        self.assertIn("status 503", response.json()["detail"])

    def test_unknown_page_and_no_suggestion(self):
        self.assertEqual(self.client.post(
            f"/api/launch-checklist/scans/{self.scan.id}/pages/onbekend/schema-markup/place").status_code, 404)
        response = self.place()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], rankmath_schema.NO_SUGGESTION)


class RemoveEndpointTest(_Endpoint):
    def test_remove_last_schemas_restores_graph(self):
        self.store(_suggestion())
        self.assertEqual(self.place().status_code, 200)
        self.wp.calls.clear()
        response = self.remove()
        self.assertEqual(response.status_code, 200, response.text)
        writes = self.wp.writes()
        self.assertEqual([w[1] for w in writes], ["rankmath/v1/updateMeta", "rankmath/v1/updateMeta"])
        self.assertEqual(writes[0][2]["meta"], {"rank_math_delete_schema-500": "", "rank_math_delete_schema-501": ""})
        self.assertEqual(writes[1][2]["meta"], {"rank_math_rich_snippet": ""})
        self.assertEqual((self.wp.schemas, self.wp.rich_snippet), ({}, ""))
        self.assertIn("#richSnippet", self.wp.html())
        body = response.json()
        self.assertIsNone(body["placement"])
        self.assertTrue(body["can_place"])
        self.assertIsNone(self.placement())
        self.assertEqual(self.remove().status_code, 404)

    def test_remove_keeps_off_when_other_schemas_remain(self):
        self.wp.schemas[300] = {"@type": "Event", "name": "Open dag", "metadata": {}}
        self.wp.next_id = 500
        self.store(_suggestion())
        self.assertEqual(self.place().status_code, 200)
        self.wp.calls.clear()
        self.assertEqual(self.remove().status_code, 200)
        self.assertEqual(len(self.wp.writes()), 1)
        self.assertEqual(set(self.wp.schemas), {300})

    def test_remove_without_graph_before_does_not_restore(self):
        self.store(_suggestion())
        self.assertEqual(self.place().status_code, 200)
        suggestion = dict(self.fresh_page().schema_suggestion)
        suggestion["placement"] = {**suggestion["placement"], "had_graph": False}
        self.store(suggestion)
        self.wp.calls.clear()
        self.assertEqual(self.remove().status_code, 200)
        self.assertEqual(len(self.wp.writes()), 1)
        self.assertEqual(self.wp.rich_snippet, "off")

    def test_remove_error_keeps_placement(self):
        self.store(_suggestion())
        self.assertEqual(self.place().status_code, 200)
        self.wp.fail["rankmath/v1/updateMeta"] = httpx.Response(401, json={"message": "Ongeldig wachtwoord."})
        response = self.remove()
        self.assertEqual(response.status_code, 502)
        self.assertIn("Ongeldig wachtwoord.", response.json()["detail"])
        self.assertIsNotNone(self.placement())

    def test_remove_without_placement(self):
        self.store(_suggestion())
        self.assertEqual(self.remove().status_code, 404)
        self.assertEqual(self.wp.calls, [])


class GenerateWithPlacementTest(_Endpoint):
    def _agent(self, jsonld):
        from app.agents.base import AgentRunResult
        return AgentRunResult(output=json.dumps({"jsonld": json.dumps(jsonld), "types": [], "placeholders": [],
                                                 "notes": ""}), model="test", incomplete_reason=None)

    def test_generate_stores_rank_math_fields(self):
        with patch(RUN_AGENT, return_value=self._agent(_graph(SERVICE, BREADCRUMB))):
            body = self.client.post(self.path, json={}).json()
        stored = self.fresh_page().schema_suggestion
        self.assertEqual((stored["rank_math_detected"], stored["default_types"], stored["had_graph"]),
                         (True, ["Article", "Person"], True))
        self.assertEqual(stored["kept_types"], ["Organization", "WebPage", "WebSite"])
        self.assertIsNone(body["placement"])
        self.assertTrue(body["can_place"])
        self.assertEqual(body["replaces_default_types"], ["Article", "Person"])

    def test_regenerate_keeps_placement_and_ignores_placed_nodes(self):
        self.store(_suggestion())
        self.assertEqual(self.place().status_code, 200)
        new = _graph({**SERVICE, "name": "Dakwerk Utrecht"}, BREADCRUMB)
        with patch(RUN_AGENT, return_value=self._agent(new)) as run:
            body = self.client.post(self.path, json={"regenerate": True}).json()
        # De geplaatste nodes tellen niet als aanwezig: Service en BreadcrumbList worden opnieuw gevraagd.
        brief = run.call_args.kwargs["input"]
        self.assertIn("- Service:", brief)
        self.assertIn("- BreadcrumbList:", brief)
        self.assertFalse(body["nothing_missing"])
        self.assertFalse(body["placement"]["current"])
        stored = self.fresh_page().schema_suggestion
        self.assertEqual([i["meta_id"] for i in stored["placement"]["items"]], [500, 501])
        # Het standaardschema is na plaatsen weg; de waarden van vóór het plaatsen blijven gelden.
        self.assertEqual(stored["default_types"], ["Article", "Person"])
        # Opnieuw plaatsen werkt bij, zonder duplicaten.
        self.wp.calls.clear()
        self.assertEqual(self.place().status_code, 200)
        self.assertEqual(set(self.wp.writes()[0][2]["schemas"]), {"schema-500", "schema-501"})
        self.assertEqual(self.wp.schemas[500]["name"], "Dakwerk Utrecht")
        self.assertTrue(self.placement()["verified"])

    def test_nothing_missing_still_returns_placement(self):
        self.page.page_type = "overig"
        self.db.commit()
        self.store(_suggestion())
        self.assertEqual(self.place().status_code, 200)
        with patch(RUN_AGENT) as run:
            body = self.client.post(self.path, json={"regenerate": True}).json()
        run.assert_not_called()
        self.assertTrue(body["nothing_missing"])
        self.assertIsNotNone(body["placement"])
        self.assertFalse(body["can_place"])
        self.assertEqual(body["place_blocked_reason"], rankmath_schema.NOTHING_MISSING)

    def test_page_list_has_placed_at_but_not_content(self):
        self.store(_suggestion())
        self.assertIsNone(to_page_item(self.fresh_page()).schema_placed_at)
        self.assertEqual(self.place().status_code, 200)
        item = to_page_item(self.fresh_page()).model_dump()
        self.assertIsNotNone(item["schema_placed_at"])
        self.assertEqual(item["schema_placed_at"].tzinfo, timezone.utc)
        self.assertNotIn("schema_suggestion", item)
        self.assertNotIn("placement", item)


# --- WordPress-feiten en complete markup ---------------------------------------------------------

class WordPressFactsTest(_Endpoint):
    def _agent(self, jsonld):
        from app.agents.base import AgentRunResult
        return AgentRunResult(output=json.dumps({"jsonld": json.dumps(jsonld), "types": [], "placeholders": [],
                                                 "omitted": [], "notes": ""}), model="test", incomplete_reason=None)

    def _generate(self):
        with patch(RUN_AGENT, return_value=self._agent(_graph(SERVICE, BREADCRUMB))) as run:
            response = self.client.post(self.path, json={"regenerate": True})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), run.call_args.kwargs["input"]

    def test_wordpress_facts_in_brief(self):
        self.wp.pages = [{
            "id": 42, "link": URL, "date": "2025-03-01T10:00:00", "date_gmt": "2025-03-01T09:00:00",
            "modified": "2025-04-02T10:30:00", "modified_gmt": "2025-04-02T08:30:00",
            "_embedded": {
                "author": [{"id": 3, "name": "Jan Jansen", "link": f"{BASE}/author/jan/"}],
                "wp:featuredmedia": [{"source_url": f"{BASE}/wp-content/uploads/dak.jpg",
                                      "media_details": {"width": 1200, "height": 630}}],
            },
        }]
        _, brief = self._generate()
        section = brief.split("Publicatiegegevens uit WordPress (gekoppelde site):")[1]
        self.assertIn("- Publicatiedatum: 2025-03-01T09:00:00+00:00", section)
        self.assertIn("- Wijzigingsdatum: 2025-04-02T08:30:00+00:00", section)
        self.assertIn(f"- Auteur: Jan Jansen ({BASE}/author/jan/)", section)
        self.assertIn(f"- Uitgelichte afbeelding: {BASE}/wp-content/uploads/dak.jpg (1200x630)", section)
        # Alleen lezen, met _embed; niets geschreven.
        self.assertEqual(self.wp.writes(), [])
        self.assertIn(("GET", "wp/v2/pages"), [(m, r) for m, r, _ in self.wp.calls])

    def test_find_post_returns_item_and_homepage(self):
        wp = rankmath_schema._WordPress(site_id="s", name="n", base_url=BASE, headers={"Authorization": "Basic x"})
        self.wp.pages = [{"id": 42, "link": URL, "date_gmt": "2025-03-01T09:00:00"}]
        self.assertEqual(rankmath_schema.find_post(wp, URL, embed=True)["date_gmt"], "2025-03-01T09:00:00")
        self.assertEqual(rankmath_schema.resolve_post_id(wp, URL), 42)
        self.assertEqual(rankmath_schema.find_post(wp, f"{BASE}/"), {"id": 7})

    def test_wordpress_error_does_not_break_generation(self):
        self.wp.fail["wp/v2/pages"] = httpx.Response(500, json={"message": "Databasefout."})
        body, brief = self._generate()
        self.assertFalse(body["nothing_missing"])
        self.assertNotIn("uit WordPress", brief)
        self.assertIsNotNone(self.fresh_page().schema_suggestion)
        # Pagina niet gevonden in WordPress: ook gewoon door.
        del self.wp.fail["wp/v2/pages"]
        self.wp.pages = []
        body, brief = self._generate()
        self.assertNotIn("uit WordPress", brief)
        # Onverwacht antwoord (geen lijst/JSON).
        self.wp.fail["wp/v2/pages"] = httpx.Response(200, text="<html>geen json</html>")
        body, brief = self._generate()
        self.assertNotIn("uit WordPress", brief)

    def test_unusable_connection_does_not_break_generation(self):
        site = self.db.get(WordPressSite, self.site.id)
        site.app_password_encrypted = "kapot"
        self.db.commit()
        body, brief = self._generate()
        self.assertNotIn("uit WordPress", brief)
        self.assertFalse(body["nothing_missing"])

    def test_page_graph_and_full_script(self):
        body, brief = self._generate()
        # Het standaardschema van Rank Math is in de brief gemarkeerd als vervallend.
        self.assertIn(f"{URL}#richSnippet (Article) [standaardschema van Rank Math", brief)
        self.assertIn(f"{BASE}/author/jan/ (Person): Jan [standaardschema van Rank Math", brief)
        self.assertNotIn(f"{BASE}/#organization (Organization): Klant BV [", brief)
        rows = [(r["types"], r["id"], r["status"]) for r in body["page_graph"]]
        self.assertEqual(rows, [
            (["Organization"], f"{BASE}/#organization", "existing"),
            (["WebSite"], f"{BASE}/#website", "existing"),
            (["WebPage"], f"{URL}#webpage", "existing"),
            (["Article"], f"{URL}#richSnippet", "lapses"),
            (["Person"], f"{BASE}/author/jan/", "lapses"),
            (["Service"], f"{URL}#service", "new"),
            (["BreadcrumbList"], None, "new"),
        ])
        self.assertEqual(body["page_graph"][0]["properties"], ["name"])
        self.assertEqual(body["page_graph"][5]["properties"], ["name", "provider"])
        script = body["full_script"]
        self.assertTrue(script.startswith('<script type="application/ld+json">\n'))
        self.assertTrue(script.endswith("\n</script>"))
        data = json.loads(script[len('<script type="application/ld+json">'):-len("</script>")])
        self.assertEqual(data["@context"], "https://schema.org")
        self.assertEqual([n["@type"] for n in data["@graph"]],
                         ["Organization", "WebSite", "WebPage", "Service", "BreadcrumbList"])
        self.assertNotIn("richSnippet", script)
        self.assertFalse(any("@context" in n for n in data["@graph"]))
        # Het nieuwe blok zelf (dat geplaatst wordt) is ongewijzigd.
        self.assertNotIn("WebSite", body["script"])
        # Ook bij opvragen uit de opslag.
        cached = self.client.post(self.path, json={}).json()
        self.assertEqual((cached["page_graph"], cached["full_script"]), (body["page_graph"], script))

    def test_after_placement_nothing_lapses_and_placed_nodes_are_new(self):
        self._generate()
        self.assertEqual(self.place().status_code, 200)
        body, _ = self._generate()
        statuses = [(r["types"][0], r["status"]) for r in body["page_graph"]]
        self.assertNotIn("lapses", [s for _, s in statuses])
        # De geplaatste Service staat niet dubbel: alleen als "new".
        self.assertEqual([s for t, s in statuses if t == "Service"], ["new"])
        data = json.loads(body["full_script"][len('<script type="application/ld+json">'):-len("</script>")])
        self.assertEqual([n["@type"] for n in data["@graph"]].count("Service"), 1)

    def test_old_suggestion_without_stored_markup(self):
        # Voorstel van vóór de rijkere generator dat al beoordeeld is: blijft staan (niet opnieuw gemaakt).
        old = {k: v for k, v in _suggestion().items() if k != "existing_nodes"}
        self.store({**old, "review": {"status": "rejected", "jsonld_hash": "oud"}})
        body = self.client.post(self.path, json={}).json()
        self.assertTrue(body["cached"])
        self.assertEqual([(r["types"], r["status"]) for r in body["page_graph"]],
                         [(["Service"], "new"), (["BreadcrumbList"], "new")])
        self.assertEqual(body["full_script"], "")
        self.assertEqual((body["target_types"], body["target_types_source"], body["stale"], body["omitted"]),
                         (["Service", "BreadcrumbList"], "auto", False, []))

    def test_existing_markup_is_capped_by_dropping_largest_nodes(self):
        nodes = [{"@type": "Thing", "@id": f"#n{i}", "name": "x" * size} for i, size in enumerate((100, 50_000, 20_000))]
        kept, dropped = schema_markup.capped_nodes([{"@context": "https://schema.org", "@graph": nodes}],
                                                   limit=60_000)
        self.assertEqual(([n["@id"] for n in kept], dropped), (["#n0", "#n2"], 1))
        kept, dropped = schema_markup.capped_nodes(nodes, limit=1_000)
        self.assertEqual(([n["@id"] for n in kept], dropped), (["#n0"], 2))


if __name__ == "__main__":
    unittest.main()
