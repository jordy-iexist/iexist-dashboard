"""Livegang (fase 5): doorzetten naar Monday, CSV-export van de livegangchecklist.

De Monday-client wordt op de grens vervangen door een nep-client; daarnaast faalt
elke echte GraphQL-aanroep hard, zodat geen test het netwerk kan bereiken (ook
niet met een echte token in .env). Database: SQLite met alleen de benodigde tabellen.
"""
import csv
import html
import io
import itertools
import json
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
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
from app.services.monday import client as monday_client
from app.services.monday.client import MondayBoard, MondayFolder, MondayGroup, MondayItem

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
DASHBOARD = "https://dashboard.example"
GOLIVE_SOURCE = "Livegangchecklist – oplevering nieuwe website"
GOLIVE_GROUP = "Livegang – Oplevering nieuwe website"
MONITOR_GROUP = "Monitor – Nieuwe & gewijzigde pagina's"
OLD_GROUPS = {phase: monday_push.GROUP_TITLES[phase] for phase in (1, 2, 3, 4)}


class FakeMonday:
    """Nep-Monday: houdt borden, groepen, items en toelichtingen in het geheugen bij."""

    MondayItem = MondayItem

    def __init__(self):
        self._ids = itertools.count(100)
        self.boards: dict[str, MondayBoard] = {}
        self.groups_created: list[tuple[str, str]] = []
        self.groups_after: dict[str, str | None] = {}  # titel -> after_group_id
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

    def create_group(self, board_id, title, *, after_group_id=None):
        group = MondayGroup(id=f"group-{self._id()}", title=title)
        board = self.boards[board_id]
        groups = list(board.groups)
        # Zoals Monday: zonder positie bovenaan, met after_group_id direct eronder.
        ids = [g.id for g in groups]
        groups.insert(ids.index(after_group_id) + 1 if after_group_id in ids else 0, group)
        self.boards[board_id] = MondayBoard(id=board.id, name=board.name, url=board.url, groups=groups)
        self.groups_created.append((board_id, title))
        self.groups_after[title] = after_group_id
        return group

    def remove_group(self, board_id, group_id):
        board = self.boards[board_id]
        self.boards[board_id] = MondayBoard(id=board.id, name=board.name, url=board.url,
                                            groups=[g for g in board.groups if g.id != group_id])

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
        # server_default now() (bijv. LaunchMondayTopic.created_at) kent SQLite niet.
        event.listen(engine, "connect", lambda conn, _: conn.create_function("now", 0, NOW.isoformat))
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
        # Nieuw bord: de vijf fasegroepen, met de livegang als eigen groep; de monitorgroep nog niet.
        self.assertEqual({t for _, t in self.fake.groups_created},
                         set(monday_push.GROUP_TITLES.values()) - {MONITOR_GROUP})
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
        # Alleen de livegang erbij; de monitorgroep komt pas bij het eerste monitorpunt.
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
        self.assertEqual([getattr(customer, f"monday_group_fase{p}_id") for p in range(1, 7)], [None] * 6)

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


class MonitorMondayTest(_Base):
    """Sitemap-monitor (fase 6): eigen groep, eigen hoofditems, bron 'Sitemap-monitor'."""

    def add_issue(self, phase, issue_type="missing_meta_description", url="https://www.klant.nl/nieuw/"):
        scan = _scan(self.customer_id, phase)
        self.db.add(scan)
        issue = LaunchScanIssue(
            id=str(uuid.uuid4()), scan_id=scan.id, issue_type=issue_type, category="onpage", severity="middel",
            title=f"Meta description ontbreekt: {url}", description="Geen meta description.",
            recommendation="Schrijf een meta description.", url=url, status="open", created_at=NOW, updated_at=NOW,
        )
        self.db.add(issue)
        self.db.commit()
        return issue

    def test_constants(self):
        self.assertEqual(monday_push.MONITOR_PHASE, 6)
        self.assertEqual(monday_push.GROUP_TITLES[6], MONITOR_GROUP)
        self.assertIn(6, monday_push.ISSUE_PHASES)
        self.assertNotIn(5, monday_push.ISSUE_PHASES)
        self.assertIn(6, monday_push.GROUPED_PHASES)
        self.assertEqual(monday_push._group_attr(6), "monday_group_fase6_id")
        self.assertNotIn(6, monday_push.CHECKLIST_SOURCE)

    def monitor_groups(self):
        return [t for _, t in self.fake.groups_created if t == MONITOR_GROUP]

    def test_new_board_gets_five_groups_without_monitor(self):
        monday_push.ensure_customer_board(self.db, self.customer())
        self.assertEqual(len(self.fake.groups_created), 5)
        self.assertEqual(self.monitor_groups(), [])
        customer = self.customer()
        ids = [getattr(customer, f"monday_group_fase{p}_id") for p in range(1, 6)]
        self.assertTrue(all(ids))
        self.assertEqual(len(set(ids)), 5)
        self.assertIsNone(customer.monday_group_fase6_id)

    def test_linking_a_board_creates_no_monitor_group(self):
        board = self.fake.add_board({})
        monday_push.link_board(self.db, self.customer(), board)
        self.assertEqual(len(self.fake.groups_created), 5)
        self.assertEqual(self.monitor_groups(), [])
        self.assertIsNone(self.customer().monday_group_fase6_id)

    def test_phase_1_push_creates_no_monitor_group(self):
        result = monday_push.push_issues(self.db, [self.add_issue(1).id], "user-1")
        self.assertEqual(result.outcomes[0].status, "pushed", result.outcomes)
        self.assertEqual(self.monitor_groups(), [])
        self.assertIsNone(self.customer().monday_group_fase6_id)

    def test_first_monitor_issue_creates_group_below_last_phase_group_second_reuses_it(self):
        monday_push.push_issues(self.db, [self.add_issue(1, url="https://www.klant.nl/oud/").id], "user-1")
        before = len(self.fake.groups_created)

        first = monday_push.push_issues(self.db, [self.add_issue(6).id], "user-1")
        self.assertEqual(first.outcomes[0].status, "pushed", first.outcomes)
        self.assertEqual(self.fake.groups_created[before:], [(self.customer().monday_board_id, MONITOR_GROUP)])
        customer = self.customer()
        self.assertIsNotNone(customer.monday_group_fase6_id)
        # Onder de livegangsgroep (de onderste fasegroep), niet bovenaan het bord.
        self.assertEqual(self.fake.groups_after[MONITOR_GROUP], customer.monday_group_fase5_id)
        board = self.fake.boards[customer.monday_board_id]
        self.assertEqual([g.title for g in board.groups],
                         [*(monday_push.GROUP_TITLES[p] for p in range(1, 6)), MONITOR_GROUP])

        second = monday_push.push_issues(
            self.db, [self.add_issue(6, issue_type="missing_title", url="https://www.klant.nl/ander/").id], "user-1")
        self.assertEqual(second.outcomes[0].status, "pushed", second.outcomes)
        self.assertEqual(self.monitor_groups(), [MONITOR_GROUP])
        self.assertEqual(self.customer().monday_group_fase6_id, customer.monday_group_fase6_id)
        monitor_parents = [i for i in self.fake.items if "parent_id" not in i][1:]
        self.assertEqual(len(monitor_parents), 2)
        self.assertEqual({p["group_id"] for p in monitor_parents}, {customer.monday_group_fase6_id})

    def test_existing_group_with_the_same_title_is_reused(self):
        groups = {f"g{p}": t for p, t in monday_push.GROUP_TITLES.items()}
        groups["g6"] = MONITOR_GROUP.upper()  # titel hoofdletterongevoelig herkend
        board = self.fake.add_board(groups)
        monday_push.link_board(self.db, self.customer(), board)
        self.assertEqual(self.customer().monday_group_fase6_id, "g6")

        result = monday_push.push_issues(self.db, [self.add_issue(6).id], "user-1")
        self.assertEqual(result.outcomes[0].status, "pushed", result.outcomes)
        self.assertEqual(self.fake.groups_created, [])
        self.assertEqual(self.fake.items[0]["group_id"], "g6")

    def test_deleted_monitor_group_does_not_break_other_phases_and_is_recreated(self):
        monday_push.push_issues(self.db, [self.add_issue(6).id], "user-1")
        customer = self.customer()
        old = customer.monday_group_fase6_id
        self.fake.remove_group(customer.monday_board_id, old)

        result = monday_push.push_issues(self.db, [self.add_issue(1).id], "user-1")
        self.assertEqual(result.outcomes[0].status, "pushed", result.outcomes)
        self.assertIsNone(self.customer().monday_group_fase6_id)
        self.assertEqual(self.monitor_groups(), [MONITOR_GROUP])

        result = monday_push.push_issues(
            self.db, [self.add_issue(6, url="https://www.klant.nl/ander/").id], "user-1")
        self.assertEqual(result.outcomes[0].status, "pushed", result.outcomes)
        new = self.customer().monday_group_fase6_id
        self.assertNotIn(new, (None, old))
        self.assertEqual(self.monitor_groups(), [MONITOR_GROUP, MONITOR_GROUP])

    def test_unlink_clears_the_monitor_group(self):
        monday_push.push_issues(self.db, [self.add_issue(6).id], "user-1")
        self.assertIsNotNone(self.customer().monday_group_fase6_id)
        monday_push.unlink_board(self.db, self.customer())
        self.assertIsNone(self.customer().monday_group_fase6_id)

    def test_monitor_issue_goes_under_own_topic_in_monitor_group(self):
        # Fase 1 heeft al een hoofditem voor hetzelfde onderwerp.
        first = monday_push.push_issues(self.db, [self.add_issue(1, url="https://www.klant.nl/oud/").id], "user-1")
        self.assertEqual(first.outcomes[0].status, "pushed", first.outcomes)
        monitor_issue = self.add_issue(6)
        result = monday_push.push_issues(self.db, [monitor_issue.id], "user-1")

        self.assertEqual(result.outcomes[0].status, "pushed", result.outcomes)
        customer = self.customer()
        parents = [i for i in self.fake.items if "parent_id" not in i]
        self.assertEqual([p["group_id"] for p in parents],
                         [customer.monday_group_fase1_id, customer.monday_group_fase6_id])
        self.assertEqual(parents[0]["name"], parents[1]["name"])  # zelfde onderwerp, eigen hoofditem
        sub = self.fake.items[-1]
        self.assertEqual(sub["parent_id"], parents[1]["id"])
        body = self.fake.updates[sub["id"]]
        self.assertIn("<b>Bron:</b> Sitemap-monitor", body)
        self.assertNotIn("Livegang-scan fase", body)
        self.assertIn(f"{DASHBOARD}/dashboard/livegang/seo-geo/{self.customer_id}", body)
        self.assertIn("<b>Bron:</b> Sitemap-monitor", self.fake.updates[parents[1]["id"]])
        topics = {t.issue_type for t in self.db.query(LaunchMondayTopic).all()}
        self.assertEqual(topics, {"missing_meta_description", "monitor:missing_meta_description"})
        self.db.expire_all()
        self.assertEqual(self.db.get(LaunchScanIssue, monitor_issue.id).status, "doorgezet")

    def test_second_monitor_issue_reuses_monitor_topic(self):
        monday_push.push_issues(self.db, [self.add_issue(6).id], "user-1")
        monday_push.push_issues(self.db, [self.add_issue(6, url="https://www.klant.nl/ander/").id], "user-1")
        parents = [i for i in self.fake.items if "parent_id" not in i]
        self.assertEqual(len(parents), 1)
        self.assertEqual(len([i for i in self.fake.items if "parent_id" in i]), 2)

    def test_source_label(self):
        self.assertEqual(monday_push.source_label(6), "Sitemap-monitor")
        self.assertEqual(monday_push.source_label(1), "Livegang-scan fase 1")
        self.assertEqual(monday_push.topic_key("x", 6), "monitor:x")
        self.assertEqual(monday_push.topic_key("x", 1), "x")


class CreateGroupPositionTest(unittest.TestCase):
    """Monday-client: de positie van een nieuwe groep (relative_to + position_relative_method)."""

    def setUp(self):
        patcher = patch.object(monday_client, "settings", SimpleNamespace(
            monday_api_token="test-token", monday_api_version="2026-10", monday_request_timeout_seconds=5.0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def send(self, **kwargs):
        seen = {}

        def handler(request):
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"data": {"create_group": {"id": "g9", "title": "T"}}})

        http = httpx.Client(transport=httpx.MockTransport(handler))
        group = monday_client.create_group("1", "T", client=http, **kwargs)
        self.assertEqual(group.id, "g9")
        return seen["body"]

    def test_without_position(self):
        body = self.send()
        self.assertNotIn("relative_to", body["query"])
        self.assertEqual(body["variables"], {"board": "1", "name": "T"})

    def test_below_a_group(self):
        body = self.send(after_group_id="g5")
        self.assertIn("relative_to: $after", body["query"])
        self.assertIn("position_relative_method: after_at", body["query"])
        self.assertEqual(body["variables"], {"board": "1", "name": "T", "after": "g5"})


class IssueSuggestionsTest(unittest.TestCase):
    def setUp(self):
        from app.db.models import LaunchContentPage, LaunchContentSuggestion

        self.Page, self.Suggestion = LaunchContentPage, LaunchContentSuggestion
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        for model in (CustomerCategory, CustomerWebsite, LaunchScan, LaunchScanIssue,
                      LaunchContentPage, LaunchContentSuggestion):
            model.__table__.create(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.customer_id = str(uuid.uuid4())
        self.db.add(CustomerWebsite(id=self.customer_id, name="Klant", base_url="https://www.klant.nl/",
                                    domain="klant.nl", created_by="user-1", created_at=NOW, updated_at=NOW))
        self.scan = _scan(self.customer_id, 3)
        self.db.add(self.scan)
        self.db.commit()

    def page(self, url):
        page = self.Page(id=str(uuid.uuid4()), scan_id=self.scan.id, url=url, path="/", created_at=NOW)
        self.db.add(page)
        return page

    def suggestion(self, page, item_key, value, status="open", minute=0):
        at = NOW.replace(minute=minute)
        self.db.add(self.Suggestion(
            id=str(uuid.uuid4()), scan_id=self.scan.id, customer_website_id=self.customer_id,
            content_page_id=page.id, item_key=item_key, agent="content_meta", title=f"Titel {value}",
            proposed_value=value, status=status, created_at=at, updated_at=at,
        ))

    def test_filters_and_order(self):
        url = "https://www.klant.nl/a/"
        page, other = self.page(url), self.page("https://www.klant.nl/b/")
        self.suggestion(page, "c3_meta_description", "tweede", minute=2)
        self.suggestion(page, "c3_meta_description", "eerste", minute=1)
        self.suggestion(page, "c3_meta_description", "afgewezen", status="afgewezen")
        self.suggestion(page, "c3_title", "ander punt")
        self.suggestion(other, "c3_meta_description", "andere pagina")
        issue = LaunchScanIssue(
            id=str(uuid.uuid4()), scan_id=self.scan.id, issue_type="c3_meta_description", category="content",
            severity="middel", title="t", description="d", url=url, status="open", created_at=NOW, updated_at=NOW,
        )
        self.db.add(issue)
        self.db.commit()

        rows = monday_push.issue_suggestions(self.db, issue)
        self.assertEqual([r.proposed_value for r in rows], ["eerste", "tweede"])
        body = monday_push.suggestions_html(self.db, issue)
        self.assertIn("<b>Voorstel:</b> eerste", body)
        self.assertNotIn("afgewezen", body)

        issue.url = None
        self.assertEqual(monday_push.issue_suggestions(self.db, issue), [])
        self.assertEqual(monday_push.suggestions_html(self.db, issue), "")


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
