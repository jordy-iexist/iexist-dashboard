"""Livegang (fase 5): doorzetten naar Monday, CSV-export van de livegangchecklist.

De Monday-client wordt op de grens vervangen door een nep-client; daarnaast faalt
elke echte GraphQL-aanroep hard, zodat geen test het netwerk kan bereiken (ook
niet met een echte token in .env). Database: SQLite met alleen de benodigde tabellen.
"""
import csv
import html
import io
import itertools
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import require_user_id
from app.db.models import (
    CustomerCategory,
    CustomerWebsite,
    LaunchChecklistState,
    LaunchMondayTopic,
    LaunchScan,
    LaunchScanIssue,
)
from app.db.session import get_db
from app.features.launch_checklist.router import router
from app.features.launch_checklist.services import monday_push
from app.features.launch_checklist.services.content_checklist import ITEMS as CONTENT_ITEMS
from app.features.launch_checklist.services.geo_checklist import ITEMS as GEO_ITEMS
from app.features.launch_checklist.services.quarterly_checklist import ITEMS as QUARTERLY_ITEMS
from app.services.monday.client import MondayBoard, MondayFolder, MondayGroup, MondayItem

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
DASHBOARD = "https://dashboard.example"
GOLIVE_SOURCE = "Livegangchecklist – oplevering nieuwe website"
GOLIVE_GROUP = "Livegang – Oplevering nieuwe website"
OLD_GROUPS = {phase: monday_push.GROUP_TITLES[phase] for phase in (1, 2, 3, 4)}


class FakeMonday:
    """Nep-Monday: houdt borden, groepen, items en toelichtingen in het geheugen bij."""

    MondayItem = MondayItem

    def __init__(self):
        self._ids = itertools.count(100)
        self.boards: dict[str, MondayBoard] = {}
        self.groups_created: list[tuple[str, str]] = []
        self.items: list[dict] = []
        self.updates: dict[str, str] = {}

    def _id(self) -> str:
        return str(next(self._ids))

    def add_board(self, groups: dict[str, str]) -> MondayBoard:
        board_id = self._id()
        board = MondayBoard(id=board_id, name="Bord", url=f"https://monday.example/boards/{board_id}",
                            groups=[MondayGroup(id=gid, title=title) for gid, title in groups.items()])
        self.boards[board_id] = board
        return board

    # --- de functies die monday_push gebruikt ---
    def find_folder(self, name):
        return MondayFolder(id="folder-1", name=name, workspace_id="ws-1")

    def get_folder(self, folder_id):
        return MondayFolder(id=folder_id, name="Map", workspace_id="ws-1")

    def create_board(self, name, *, folder_id=None, workspace_id=None):
        return self.add_board({})

    def get_board(self, board_id):
        return self.boards[board_id]

    def create_group(self, board_id, title):
        group = MondayGroup(id=f"group-{self._id()}", title=title)
        board = self.boards[board_id]
        self.boards[board_id] = MondayBoard(id=board.id, name=board.name, url=board.url,
                                            groups=[*board.groups, group])
        self.groups_created.append((board_id, title))
        return group

    def create_item(self, board_id, name, *, group_id=None):
        item = MondayItem(id=self._id(), url=f"https://monday.example/items/{len(self.items) + 1}")
        self.items.append({"id": item.id, "board_id": board_id, "name": name, "group_id": group_id})
        return item

    def create_subitem(self, parent_id, name):
        item = MondayItem(id=self._id(), url=None)
        self.items.append({"id": item.id, "parent_id": parent_id, "name": name, "group_id": None})
        return item

    def create_update(self, item_id, body):
        self.updates[item_id] = body

    def missing_item_ids(self, ids):
        return set()


def _scan(customer_id, phase, *, status="completed", checklist=None, period=None):
    return LaunchScan(
        id=str(uuid.uuid4()), customer_website_id=customer_id, phase=phase, status=status, period=period,
        base_url="https://www.klant.nl/", total_urls=0, inventoried_urls=0, failed_urls=0, max_pages=500,
        vitals_max_pages=0, vitals_total=0, vitals_measured=0, created_by="user-1",
        created_at=NOW, updated_at=NOW, checklist=checklist,
    )


def _result(status, message, evidence=(), details=None):
    return {"status": status, "message": message, "evidence": list(evidence), "details": details}


GOLIVE_RESULTS = {
    "gl_https": _result("ok", "Bereikbaar via HTTPS met een geldig certificaat (https://www.klant.nl/).",
                        ["https://www.klant.nl/ (200)"]),
    "gl_http_redirect": _result(
        "warning", "http:// gaat niet overal met een permanente redirect naar https://.",
        ["http://klant.nl/: tijdelijke redirect (302) in plaats van 301", "http://www.klant.nl/: 301 naar https://www.klant.nl/"],
        {"variants": [
            {"start": "http://klant.nl/", "status": "warning", "note": "tijdelijke redirect (302) in plaats van 301",
             "chain": [{"url": "http://klant.nl/", "status": 302, "location": "https://www.klant.nl/"}],
             "final_url": "https://www.klant.nl/", "final_status": 200, "error": None},
            {"start": "http://www.klant.nl/", "status": "ok", "note": "301 naar https://www.klant.nl/",
             "chain": [{"url": "http://www.klant.nl/", "status": 301, "location": "https://www.klant.nl/"}],
             "final_url": "https://www.klant.nl/", "final_status": 200, "error": None},
        ]},
    ),
    "gl_staging_refs": _result(
        "error", "30 verwijzing(en) naar de testomgeving op 1 host(s).",
        ["staging.klant.nl (testsubdomein, 3 pagina('s))"],
        {"hosts": [{"host": "staging.klant.nl", "level": "error", "reason": "testsubdomein", "pages": 3,
                    "types": ["img", "link"], "refs": 30}],
         "refs": [{"page": f"https://www.klant.nl/p{i}/", "type": "link", "url": f"https://staging.klant.nl/p{i}/",
                   "host": "staging.klant.nl", "level": "error", "reason": "testsubdomein"} for i in range(20)],
         "total": 30, "pages_checked": 3, "site_is_test_host": False},
    ),
}


class _Base(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        for model in (CustomerCategory, CustomerWebsite, LaunchScan, LaunchScanIssue,
                      LaunchChecklistState, LaunchMondayTopic):
            model.__table__.create(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)
        self.customer_id = str(uuid.uuid4())
        self.db.add(CustomerWebsite(
            id=self.customer_id, name="Klant", base_url="https://www.klant.nl/", domain="klant.nl",
            created_by="user-1", created_at=NOW, updated_at=NOW,
        ))
        self.db.commit()

        # Vangnet: een echte Monday-aanroep laat de test falen in plaats van het netwerk op te gaan.
        network = patch("app.services.monday.client._graphql", side_effect=AssertionError("Monday-netwerk aangeroepen"))
        network.start()
        self.addCleanup(network.stop)
        self.fake = FakeMonday()
        for target, value in (
            ("monday", self.fake),
            ("settings", SimpleNamespace(dashboard_public_url=DASHBOARD, monday_folder_id="",
                                         monday_folder_name="Klanten")),
        ):
            patcher = patch.object(monday_push, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def customer(self) -> CustomerWebsite:
        self.db.expire_all()
        return self.db.get(CustomerWebsite, self.customer_id)

    def add_golive_scan(self):
        scan = _scan(self.customer_id, 5, checklist={"items": GOLIVE_RESULTS, "generated_at": NOW.isoformat()})
        self.db.add(scan)
        self.db.commit()
        return scan


class GoLivePushTest(_Base):
    def test_push_creates_items_in_golive_group_with_source_and_link(self):
        self.add_golive_scan()
        result = monday_push.push_checklist_items(
            self.db, self.customer(), ["gl_https", "gl_staging_refs", "gl_redirect_map"], "user-1", phase=5)

        self.assertEqual([o.status for o in result.outcomes], ["pushed"] * 3, result.outcomes)
        customer = self.customer()
        # Nieuw bord: alle vijf groepen, met de livegang als eigen groep.
        self.assertEqual({t for _, t in self.fake.groups_created}, set(monday_push.GROUP_TITLES.values()))
        self.assertIsNotNone(customer.monday_group_fase5_id)
        self.assertEqual({i["group_id"] for i in self.fake.items}, {customer.monday_group_fase5_id})
        self.assertNotIn(customer.monday_group_fase5_id,
                         {getattr(customer, f"monday_group_fase{p}_id") for p in (1, 2, 3, 4)})
        self.assertEqual(self.fake.items[0]["name"], "Site bereikbaar via HTTPS met geldig certificaat")
        for item in self.fake.items:
            body = self.fake.updates[item["id"]]
            self.assertIn(GOLIVE_SOURCE, body)
            self.assertIn(f"{DASHBOARD}/dashboard/livegang/oplevering/{self.customer_id}", body)
            self.assertNotIn("seo-geo", body)
            self.assertNotIn("{", body)  # geen ruwe JSON
        # De koppeling staat op de handmatige status (period leeg).
        states = {s.item_key: s for s in self.db.query(LaunchChecklistState).all()}
        self.assertEqual(set(states), {"gl_https", "gl_staging_refs", "gl_redirect_map"})
        self.assertTrue(all(s.external_provider == "monday" and s.period == "" for s in states.values()))

    def test_body_carries_findings_and_details(self):
        self.add_golive_scan()
        monday_push.push_checklist_items(
            self.db, self.customer(), ["gl_staging_refs", "gl_http_redirect", "gl_https"], "user-1", phase=5)
        bodies = [self.fake.updates[i["id"]] for i in self.fake.items]
        staging, redirect, https = bodies
        self.assertIn("<b>Scanresultaat:</b> 30 verwijzing(en)", staging)
        self.assertIn("staging.klant.nl (testsubdomein, 3 pagina(&#x27;s))", staging)
        self.assertIn("<b>Waar:</b>", staging)
        self.assertIn("https://www.klant.nl/p0/: link https://staging.klant.nl/p0/", staging)
        self.assertIn("/p14/", staging)
        self.assertNotIn("/p15/", staging)  # gecapt op MAX_EVIDENCE (15)
        self.assertIn("… en nog 15", staging)  # 30 in totaal, 15 getoond
        self.assertIn("<b>Redirectketens:</b>", redirect)
        self.assertIn("http://klant.nl/ (302) → https://www.klant.nl/ (200)", redirect)
        # 'ok': geen aanvulling uit details.
        self.assertNotIn("Redirectketens", https)
        self.assertIn("<b>Prioriteit:</b> hoog", https)
        self.assertIn("<b>Sectie:</b> Domein, HTTPS &amp; redirects", https)

    def test_second_push_is_skipped(self):
        customer = self.customer()
        first = monday_push.push_checklist_items(self.db, customer, ["gl_search_console"], "user-1", phase=5)
        self.assertEqual(first.outcomes[0].status, "pushed")
        second = monday_push.push_checklist_items(self.db, self.customer(), ["gl_search_console"], "user-1", phase=5)
        self.assertEqual(second.outcomes[0].status, "skipped")
        self.assertEqual(second.outcomes[0].external_url, first.outcomes[0].external_url)
        self.assertEqual(len(self.fake.items), 1)

    def test_board_from_before_golive_gets_the_group_on_first_use(self):
        old_ids = {phase: f"old-{phase}" for phase in OLD_GROUPS}
        board = self.fake.add_board({old_ids[p]: t for p, t in OLD_GROUPS.items()})
        customer = self.customer()
        customer.monday_board_id = board.id
        customer.monday_board_url = board.url
        for phase, gid in old_ids.items():
            setattr(customer, f"monday_group_fase{phase}_id", gid)
        self.db.commit()

        result = monday_push.push_checklist_items(self.db, self.customer(), ["gl_favicon"], "user-1", phase=5)

        self.assertEqual(result.outcomes[0].status, "pushed", result.outcomes)
        self.assertEqual(self.fake.groups_created, [(board.id, GOLIVE_GROUP)])
        customer = self.customer()
        self.assertEqual({p: getattr(customer, f"monday_group_fase{p}_id") for p in OLD_GROUPS}, old_ids)
        self.assertEqual(self.fake.items[0]["group_id"], customer.monday_group_fase5_id)
        self.assertEqual(self.fake.items[0]["board_id"], board.id)

    def test_unknown_keys_are_reported(self):
        result = monday_push.push_checklist_items(
            self.db, self.customer(), ["gl_onbekend", next(iter(GEO_ITEMS)), "gl_404"], "user-1", phase=5)
        self.assertEqual([(o.ref, o.status) for o in result.outcomes][:2],
                         [("gl_onbekend", "failed"), (next(iter(GEO_ITEMS)), "failed")])
        self.assertEqual(result.outcomes[0].message, "Onbekend checklistpunt.")
        self.assertEqual(result.outcomes[2].status, "pushed")

    def test_phases_2_to_4_keep_their_own_group_and_seo_geo_link(self):
        cases = {2: next(iter(GEO_ITEMS)), 3: next(iter(CONTENT_ITEMS)), 4: next(iter(QUARTERLY_ITEMS))}
        for phase, key in cases.items():
            period = "2026-Q4" if phase == 4 else ""
            result = monday_push.push_checklist_items(self.db, self.customer(), [key], "user-1",
                                                      phase=phase, period=period)
            self.assertEqual(result.outcomes[0].status, "pushed", (phase, result.outcomes))
        customer = self.customer()
        for (phase, _key), item in zip(cases.items(), self.fake.items):
            self.assertEqual(item["group_id"], getattr(customer, f"monday_group_fase{phase}_id"), phase)
            body = self.fake.updates[item["id"]]
            self.assertIn(f"{DASHBOARD}/dashboard/livegang/seo-geo/{self.customer_id}", body)
            self.assertIn(html.escape(monday_push.CHECKLIST_SOURCE[phase]), body)
            self.assertNotIn("oplevering", body)

    def test_unknown_phase_still_refused(self):
        with self.assertRaises(ValueError):
            monday_push.push_checklist_items(self.db, self.customer(), ["gl_https"], "user-1", phase=6)
        self.assertEqual(self.fake.items, [])

    def test_unlink_clears_the_golive_group(self):
        monday_push.ensure_customer_board(self.db, self.customer())
        self.assertIsNotNone(self.customer().monday_group_fase5_id)
        monday_push.unlink_board(self.db, self.customer())
        customer = self.customer()
        self.assertIsNone(customer.monday_board_id)
        self.assertEqual([getattr(customer, f"monday_group_fase{p}_id") for p in range(1, 6)], [None] * 5)

    def test_issues_of_a_golive_scan_are_not_pushed(self):
        scan = self.add_golive_scan()
        issue = LaunchScanIssue(
            id=str(uuid.uuid4()), scan_id=scan.id, issue_type="gl_https", category="livegang", severity="hoog",
            title="Test", description="Test", status="open", created_at=NOW, updated_at=NOW,
        )
        self.db.add(issue)
        self.db.commit()
        result = monday_push.push_issues(self.db, [issue.id], "user-1")
        self.assertEqual(result.outcomes[0].status, "failed")
        self.assertEqual(self.fake.items, [])


class GoLiveDetailsHtmlTest(unittest.TestCase):
    def test_nothing_for_ok_unknown_or_without_details(self):
        variants = GOLIVE_RESULTS["gl_http_redirect"]["details"]
        for status in ("ok", "nvt", "unknown"):
            self.assertEqual(monday_push.golive_details_html("gl_http_redirect", _result(status, "", details=variants)), "")
        self.assertEqual(monday_push.golive_details_html("gl_http_redirect", _result("warning", "")), "")
        self.assertEqual(monday_push.golive_details_html("gl_favicon", _result("warning", "", details={"x": 1})), "")

    def test_variants_without_redirects_add_nothing(self):
        details = {"variants": [{"start": "https://www.klant.nl/", "chain": [], "final_url": "https://www.klant.nl/",
                                 "final_status": 200, "error": None}]}
        self.assertEqual(monday_push.golive_details_html("gl_host_variants", _result("warning", "", details=details)), "")

    def test_sitemap_list_only_when_evidence_is_empty(self):
        details = {"sitemaps": ["https://www.klant.nl/sitemap.xml"]}
        body = monday_push.golive_details_html("gl_sitemap", _result("warning", "", details=details))
        self.assertIn("<b>Gevonden sitemaps:</b></p><ul><li>https://www.klant.nl/sitemap.xml</li></ul>", body)
        self.assertEqual(monday_push.golive_details_html(
            "gl_sitemap", _result("warning", "", ["x"], details=details)), "")


class GoLiveEndpointTest(_Base):
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
        self.base = f"/api/launch-checklist/customers/{self.customer_id}/golive-checklist"

    def rows(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers["content-type"].startswith("text/csv"))
        text = response.content.decode("utf-8")
        self.assertTrue(text.startswith("﻿"))
        return list(csv.reader(io.StringIO(text[1:]), delimiter=";"))

    def test_push_endpoint(self):
        response = self.client.post(f"{self.base}/push-monday", json={"item_keys": ["gl_https", "gl_onbekend"]})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual((data["pushed"], data["skipped"], data["failed"]), (1, 0, 1))
        self.assertTrue(data["board_url"].startswith("https://monday.example/boards/"))
        self.assertEqual(self.fake.items[0]["group_id"], self.customer().monday_group_fase5_id)
        # De checklist toont de Monday-link.
        items = {i["key"]: i for s in self.client.get(self.base).json()["sections"] for i in s["items"]}
        self.assertEqual(items["gl_https"]["external_url"], data["outcomes"][0]["external_url"])

    def test_export_of_a_golive_scan(self):
        scan = self.add_golive_scan()
        self.client.patch(f"{self.base}/gl_forms_tested", json={"manual_status": "afgerond", "note": "Getest"})
        rows = self.rows(self.client.get(f"/api/launch-checklist/scans/{scan.id}/export?kind=checklist"))
        self.assertEqual(rows[0], ["Sectie", "Punt", "Type", "Prioriteit", "Auto-status", "Melding",
                                   "Handmatige status", "Notitie", "Eindstatus", "Evidence"])
        self.assertEqual(len(rows), 21)
        by_label = {r[1]: r for r in rows[1:]}
        https = by_label["Site bereikbaar via HTTPS met geldig certificaat"]
        self.assertEqual(https[0], "Domein, HTTPS & redirects")
        self.assertEqual((https[4], https[8]), ("ok", "Afgerond"))
        forms = by_label["Formulieren getest"]
        self.assertEqual((forms[2], forms[6], forms[7], forms[8]), ("hybrid", "afgerond", "Getest", "Afgerond"))

    def test_export_of_a_running_golive_scan_has_no_results(self):
        scan = _scan(self.customer_id, 5, status="crawling")
        self.db.add(scan)
        self.db.commit()
        rows = self.rows(self.client.get(f"/api/launch-checklist/scans/{scan.id}/export?kind=checklist"))
        self.assertEqual(len(rows), 21)
        self.assertEqual({r[4] for r in rows[1:]}, {""})

    def test_customer_export_without_scan(self):
        self.client.patch(f"{self.base}/gl_redirect_map", json={"manual_status": "nvt", "note": "Geen oude site"})
        response = self.client.get(f"{self.base}/export")
        self.assertIn('filename="livegang-klant.nl-checklist-', response.headers["content-disposition"])
        rows = self.rows(response)
        self.assertEqual(rows[0][:2], ["Sectie", "Punt"])
        self.assertEqual(len(rows), 21)
        redirect_map = next(r for r in rows if r[1] == "Redirects van oude URL's gecontroleerd")
        self.assertEqual(redirect_map[6:9], ["nvt", "Geen oude site", "N.v.t."])
        self.assertEqual({r[8] for r in rows[1:] if r is not redirect_map}, {"Open"})

    def test_customer_export_uses_latest_completed_scan(self):
        self.add_golive_scan()
        rows = self.rows(self.client.get(f"{self.base}/export"))
        https = next(r for r in rows if r[1] == "Site bereikbaar via HTTPS met geldig certificaat")
        self.assertEqual(https[4], "ok")

    def test_customer_export_unknown_customer(self):
        self.assertEqual(
            self.client.get("/api/launch-checklist/customers/onbekend/golive-checklist/export").status_code, 404)


if __name__ == "__main__":
    unittest.main()
