"""Endpoints van de werkvoorraad (features/work_queue/router).

Draait tegen een in-memory SQLite-database met echte brondata (scans, analyses, voorstellen);
geen netwerk. De sessies hebben `autoflush=False`, net als de app.
"""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import require_user_id
from app.db.models import (
    Base,
    CompetitorAnalysis,
    CompetitorAnalysisAction,
    CompetitorAnalysisKeyword,
    CustomerWebsite,
    LaunchContentPage,
    LaunchContentSuggestion,
    LaunchScan,
    LaunchScanIssue,
    User,
    WorkItem,
)
from app.db.session import get_db
from app.features.work_queue.router import router
from app.features.work_queue.services import board as board_module
from app.features.work_queue.services.actions import GROUP_ALREADY_OPEN, NOTHING_OPEN, RESOLVED_BY_SOURCE
from app.features.work_queue.services.sources_site_changes import REOPEN_MESSAGE

USER = "user-1"
OTHER_USER = "user-2"
NOW = datetime.now(timezone.utc)
BASE = "https://klant.nl/"
PAGE_A = "https://klant.nl/diensten/seo/"
API = "/api/work-queue"


def _at(days):
    return NOW - timedelta(days=days)


class _Base(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, autoflush=False)
        self.add(
            User(id=USER, email="jan@iexist.nl", password_hash="x", created_at=NOW, updated_at=NOW),
            User(id=OTHER_USER, email="anna@iexist.nl", password_hash="x", created_at=NOW, updated_at=NOW),
        )
        self.customer = self.add_customer("Klant A")
        self.other = self.add_customer("Bakkerij B")

        self.app = FastAPI()
        self.app.include_router(router)

        def override_db():
            with self.Session() as db:
                yield db

        self.app.dependency_overrides[get_db] = override_db
        self.app.dependency_overrides[require_user_id] = lambda: USER
        self.client = TestClient(self.app)

    # --- opzet ---

    def add(self, *rows):
        with self.Session() as db:
            db.add_all(rows)
            db.commit()

    def add_customer(self, name):
        customer_id = str(uuid.uuid4())
        self.add(CustomerWebsite(id=customer_id, name=name, base_url=BASE, domain="klant.nl",
                                 created_by=USER, created_at=NOW, updated_at=NOW))
        return customer_id

    def add_scan(self, phase, *, days=10, customer=None):
        scan_id = str(uuid.uuid4())
        self.add(LaunchScan(
            id=scan_id, customer_website_id=customer or self.customer, phase=phase, status="completed",
            base_url=BASE, created_by=USER, created_at=_at(days), updated_at=_at(days), completed_at=_at(days),
        ))
        return scan_id

    def add_issue(self, scan_id, issue_type, url, *, status="open", severity="middel", category="on-page", days=10):
        issue_id = str(uuid.uuid4())
        self.add(LaunchScanIssue(
            id=issue_id, scan_id=scan_id, issue_type=issue_type, category=category, severity=severity,
            title=f"{issue_type} {url}", description="-", url=url, status=status,
            created_at=_at(days), updated_at=_at(days),
        ))
        return issue_id

    def issue_status(self, issue_id):
        with self.Session() as db:
            return db.get(LaunchScanIssue, issue_id).status

    def set_issue_status(self, status, *ids):
        with self.Session() as db:
            for issue_id in ids:
                db.get(LaunchScanIssue, issue_id).status = status
            db.commit()

    def add_analysis(self, keyword, titles, *, customer=None):
        analysis_id, keyword_id = str(uuid.uuid4()), str(uuid.uuid4())
        self.add(CompetitorAnalysis(id=analysis_id, customer_website_id=customer or self.customer, created_by=USER,
                                    status="completed", country="nl", warnings=[], modules=[],
                                    created_at=_at(10), updated_at=_at(10)))
        self.add(CompetitorAnalysisKeyword(
            id=keyword_id, analysis_id=analysis_id, keyword=keyword, keyword_key=keyword.casefold(),
            status="completed", ai_state="ok", created_at=_at(10), updated_at=_at(10)))
        action_ids = []
        for order, title in enumerate(titles):
            action_id = str(uuid.uuid4())
            action_ids.append(action_id)
            self.add(CompetitorAnalysisAction(
                id=action_id, keyword_id=keyword_id, analysis_id=analysis_id, sort_order=order, title=title,
                impact="middel", done=False, created_at=NOW, updated_at=NOW))
        return analysis_id, keyword_id, action_ids

    def action(self, action_id):
        with self.Session() as db:
            row = db.get(CompetitorAnalysisAction, action_id)
            db.expunge(row)
            return row

    def add_suggestion_page(self):
        scan = self.add_scan(3)
        page = str(uuid.uuid4())
        self.add(LaunchContentPage(id=page, scan_id=scan, url=PAGE_A, path="/diensten/seo/",
                                   title="SEO", created_at=_at(10)))
        suggestion = str(uuid.uuid4())
        self.add(LaunchContentSuggestion(
            id=suggestion, scan_id=scan, customer_website_id=self.customer, content_page_id=page,
            item_key="c3_meta_title", agent="content", title="Meta title herschrijven", current_value="Oud",
            proposed_value="Nieuw", status="open", created_at=_at(10), updated_at=_at(10)))
        return suggestion

    def add_card(self, *, status="todo", source="manual", customer=None, done_at=None, position=1000.0,
                 group_key=None, items=None, resolved=False, **fields):
        card_id = str(uuid.uuid4())
        self.add(WorkItem(
            id=card_id, customer_website_id=customer or self.customer, source=source, group_key=group_key,
            active_key=group_key if status in ("todo", "doing", "review") else None, status=status,
            kind=fields.pop("kind", "content"), title=fields.pop("title", "Kaart"), severity="middel",
            item_count=len(items or []), items=items or [], position=position, resolved_by_source=resolved,
            done_at=done_at, created_at=NOW, updated_at=NOW, **fields,
        ))
        return card_id

    def card_row(self, card_id):
        with self.Session() as db:
            row = db.get(WorkItem, card_id)
            if row is not None:
                _ = row.items
                db.expunge(row)
            return row

    # --- API ---

    def board(self, **params):
        response = self.client.get(f"{API}/board", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def column(self, board, status):
        return next(column for column in board["columns"] if column["status"] == status)

    def ids(self, board, status):
        return [card["id"] for card in self.column(board, status)["cards"]]

    def all_cards(self, board):
        return [card for column in board["columns"] for card in column["cards"]]

    def card_by_source(self, board, source):
        [card] = [card for card in self.all_cards(board) if card["source"] == source]
        return card

    def patch(self, card_id, **body):
        return self.client.patch(f"{API}/cards/{card_id}", json=body)

    def create(self, **body):
        body.setdefault("customer_id", self.customer)
        body.setdefault("kind", "content")
        return self.client.post(f"{API}/cards", json=body)


# --- bord --------------------------------------------------------------------------------


class BoardTests(_Base):
    def test_first_get_fills_board_from_sources(self):
        scan = self.add_scan(1)
        self.add_issue(scan, "title_too_long", "https://klant.nl/a", severity="hoog")
        self.add_issue(scan, "title_too_long", "https://klant.nl/b")
        self.add_analysis("seo bureau", ["FAQ toevoegen"])
        self.add_suggestion_page()

        board = self.board()

        self.assertEqual([(c["status"], c["label"]) for c in board["columns"]],
                         [("todo", "Te doen"), ("doing", "Bezig"), ("review", "Review"), ("done", "Klaar deze week")])
        todo = self.column(board, "todo")
        self.assertEqual(todo["count"], 3)
        self.assertEqual(board["totals"], {"todo": 3, "doing": 0, "review": 0, "done": 0, "unassigned": 3})
        scan_card = self.card_by_source(board, "scan")
        self.assertEqual((scan_card["title"], scan_card["item_count"], scan_card["unit"], scan_card["severity"]),
                         ("Title te lang", 2, "bevindingen", "hoog"))
        self.assertEqual((scan_card["customer_name"], scan_card["kind"]), ("Klant A", "content"))
        self.assertEqual(self.card_by_source(board, "analysis")["unit"], "punt")
        self.assertEqual(self.card_by_source(board, "site_changes")["unit"], "voorstel")
        # Hoogste ernst bovenaan.
        self.assertEqual(todo["cards"][0]["id"], scan_card["id"])
        positions = [card["position"] for card in todo["cards"]]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("week_start", board)

        # Nogmaals ophalen maakt geen nieuwe kaarten.
        self.assertEqual(self.column(self.board(), "todo")["count"], 3)

    def test_unit_singular_and_plural(self):
        scan = self.add_scan(1)
        self.add_issue(scan, "title_too_long", "https://klant.nl/a")
        self.add_analysis("seo bureau", ["FAQ", "Titel"])
        board = self.board()
        self.assertEqual(self.card_by_source(board, "scan")["unit"], "bevinding")
        self.assertEqual(self.card_by_source(board, "analysis")["unit"], "punten")
        self.add_card(source="search_console", group_key="ctr", items=[{"key": "a"}, {"key": "b"}])
        self.add_card(title="Eigen")
        board = self.board()
        self.assertEqual(self.card_by_source(board, "search_console")["unit"], "CTR-kansen")
        self.assertIsNone(self.card_by_source(board, "manual")["unit"])

    def test_filters_and_unfiltered_lists(self):
        a1 = self.create(title="A1", assignee_id=USER).json()["id"]
        a2 = self.create(title="A2").json()["id"]
        b1 = self.create(title="B1", customer_id=self.other, assignee_id=OTHER_USER, status="doing").json()["id"]
        self.create(title="B klaar", customer_id=self.other, assignee_id=USER, status="done")

        board = self.board()
        self.assertEqual(board["totals"], {"todo": 2, "doing": 1, "review": 0, "done": 1, "unassigned": 1})
        # Klanten op naam, met open kaarten.
        self.assertEqual(board["customers"], [
            {"id": self.other, "name": "Bakkerij B", "open_count": 1},
            {"id": self.customer, "name": "Klant A", "open_count": 2},
        ])
        self.assertEqual(board["users"], [
            {"id": OTHER_USER, "name": "anna", "email": "anna@iexist.nl", "open_count": 1},
            {"id": USER, "name": "jan", "email": "jan@iexist.nl", "open_count": 1},
        ])

        filtered = self.board(customer_id=self.customer)
        self.assertEqual(sorted(self.ids(filtered, "todo")), sorted([a1, a2]))
        self.assertEqual(self.ids(filtered, "doing"), [])
        self.assertEqual(filtered["totals"], {"todo": 2, "doing": 0, "review": 0, "done": 0, "unassigned": 1})
        self.assertEqual(len(filtered["customers"]), 2)
        self.assertEqual(len(filtered["users"]), 2)

        mine = self.board(assignee_id=USER)
        self.assertEqual(self.ids(mine, "todo"), [a1])
        self.assertEqual(self.column(mine, "done")["count"], 1)
        self.assertEqual(mine["totals"]["unassigned"], 0)

        nobody = self.board(assignee_id="none")
        self.assertEqual(self.ids(nobody, "todo"), [a2])
        self.assertEqual(nobody["totals"], {"todo": 1, "doing": 0, "review": 0, "done": 0, "unassigned": 1})

        both = self.board(customer_id=self.other, assignee_id=OTHER_USER)
        self.assertEqual(self.ids(both, "doing"), [b1])
        self.assertEqual(self.ids(both, "todo"), [])

    def test_done_this_week_only_and_removed_never(self):
        this_week = self.add_card(status="done", done_at=NOW)
        self.add_card(status="done", done_at=NOW - timedelta(days=8))
        self.add_card(status="removed", source="scan", group_key="h1_missing")
        board = self.board()
        self.assertEqual(self.ids(board, "done"), [this_week])
        self.assertEqual(len(self.all_cards(board)), 1)

    def test_sync_error_still_shows_stored_cards(self):
        stored = self.add_card(title="Opgeslagen")
        scan = self.add_scan(1)
        self.add_issue(scan, "title_too_long", "https://klant.nl/a")
        with patch.object(board_module.scan_adapter, "collect", side_effect=RuntimeError("kapot")), \
                self.assertLogs(board_module.logger, level="ERROR"):
            board = self.board()
        self.assertEqual(self.ids(board, "todo"), [stored])


# --- detail ------------------------------------------------------------------------------


class DetailTests(_Base):
    def test_scan_card_detail(self):
        scan = self.add_scan(1)
        self.add_issue(scan, "title_too_long", "https://klant.nl/a?x=1")
        self.add_issue(scan, "lang_missing", None)
        board = self.board()
        card = next(c for c in self.all_cards(board) if c["title"] == "Title te lang")

        detail = self.client.get(f"{API}/cards/{card['id']}").json()

        self.assertEqual(detail["items"], [{"key": "klant.nl/a?x=1", "title": "/a?x=1", "url": "https://klant.nl/a?x=1",
                                            "path": "/a?x=1", "severity": "middel"}])
        self.assertEqual(detail["source_link"],
                         {"source": "scan", "customer_id": self.customer, "phase": 1, "issue_type": "title_too_long"})
        self.assertIsNone(detail["note"])
        self.assertIsNone(detail["created_by_name"])
        self.assertEqual(detail["customer_name"], "Klant A")

        site_wide = next(c for c in self.all_cards(board) if c["id"] != card["id"])
        item = self.client.get(f"{API}/cards/{site_wide['id']}").json()["items"][0]
        self.assertEqual((item["url"], item["path"]), (None, None))

    def test_source_links_per_source(self):
        analysis_id, keyword_id, _ = self.add_analysis("seo bureau", ["FAQ"])
        self.add_suggestion_page()
        board = self.board()

        analysis = self.client.get(f"{API}/cards/{self.card_by_source(board, 'analysis')['id']}").json()
        self.assertEqual(analysis["source_link"], {"source": "analysis", "customer_id": self.customer,
                                                   "analysis_id": analysis_id, "keyword_id": keyword_id})
        changes = self.client.get(f"{API}/cards/{self.card_by_source(board, 'site_changes')['id']}").json()
        self.assertEqual(changes["source_link"], {"source": "site_changes", "customer_id": self.customer, "url": PAGE_A})
        self.assertEqual(changes["items"][0]["path"], "/diensten/seo/")

        gsc = self.add_card(source="search_console", group_key="ctr",
                            items=[{"key": "k", "title": "seo", "url": PAGE_A, "ref": {}}])
        self.assertEqual(self.client.get(f"{API}/cards/{gsc}").json()["source_link"],
                         {"source": "search_console", "customer_id": self.customer})
        manual = self.create(title="Eigen").json()
        self.assertIsNone(manual["source_link"])

    def test_monitor_phase_link(self):
        monitor = self.add_scan(6)
        self.add_issue(monitor, "title_too_long", "https://klant.nl/a")
        card = self.card_by_source(self.board(), "scan")
        self.assertEqual(self.client.get(f"{API}/cards/{card['id']}").json()["source_link"]["phase"], 6)

    def test_unknown_or_removed_card_is_404(self):
        response = self.client.get(f"{API}/cards/bestaat-niet")
        self.assertEqual(response.status_code, 404)
        self.assertIsInstance(response.json()["detail"], str)
        removed = self.add_card(status="removed", source="scan", group_key="x")
        self.assertEqual(self.client.get(f"{API}/cards/{removed}").status_code, 404)
        self.assertEqual(self.patch(removed, status="todo").status_code, 404)
        self.assertEqual(self.client.delete(f"{API}/cards/{removed}").status_code, 404)


# --- eigen taak ---------------------------------------------------------------------------


class ManualTaskTests(_Base):
    def test_create_edit_delete(self):
        response = self.create(title="  Maandrapport   maken ", kind="rapport", note="Voor vrijdag", assignee_id=OTHER_USER)
        self.assertEqual(response.status_code, 201, response.text)
        card = response.json()
        self.assertEqual((card["source"], card["title"], card["kind"], card["status"], card["severity"]),
                         ("manual", "Maandrapport maken", "rapport", "todo", "middel"))
        self.assertEqual((card["created_by_name"], card["assignee_name"], card["note"], card["has_note"]),
                         ("jan", "anna", "Voor vrijdag", True))
        self.assertEqual((card["item_count"], card["unit"], card["items"]), (0, None, []))

        updated = self.patch(card["id"], title="Kwartaalrapport", kind="update").json()
        self.assertEqual((updated["title"], updated["kind"]), ("Kwartaalrapport", "update"))
        self.assertEqual(updated["assignee_id"], OTHER_USER)  # weggelaten: ongemoeid

        self.assertEqual(self.client.delete(f"{API}/cards/{card['id']}").json(), {"ok": True})
        self.assertIsNone(self.card_row(card["id"]))
        self.assertEqual(self.client.get(f"{API}/cards/{card['id']}").status_code, 404)

    def test_create_done(self):
        card = self.create(title="Al gedaan", status="done").json()
        self.assertEqual(card["status"], "done")
        self.assertIsNotNone(card["done_at"])
        self.assertEqual(card["done_by_name"], "jan")
        self.assertEqual(self.ids(self.board(), "done"), [card["id"]])

    def test_validation(self):
        response = self.create(title="Taak", customer_id="onbekend")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Klant niet gevonden.")
        for body in ({"title": "   "}, {"title": "Taak", "kind": "seo"}, {"title": "Taak", "status": "removed"},
                     {"title": "Taak", "assignee_id": "niemand"}, {"title": "x" * 301}):
            with self.subTest(body=body):
                response = self.create(**body)
                self.assertEqual(response.status_code, 422)
                self.assertIsInstance(response.json()["detail"], str)
        card = self.create(title="Taak").json()["id"]
        self.assertEqual(self.patch(card, title="").status_code, 422)
        self.assertEqual(self.patch(card, kind="seo").status_code, 422)
        self.assertEqual(self.patch(card, status="removed").status_code, 422)
        with self.Session() as db:
            self.assertEqual(db.query(WorkItem).count(), 1)


# --- verplaatsen ---------------------------------------------------------------------------


class MoveTests(_Base):
    def setUp(self):
        super().setUp()
        self.c1, self.c2, self.c3 = (self.create(title=t).json()["id"] for t in ("Een", "Twee", "Drie"))

    def test_reorder_within_column(self):
        self.assertEqual(self.ids(self.board(), "todo"), [self.c1, self.c2, self.c3])
        response = self.patch(self.c3, after_id=self.c1, before_id=self.c2)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.ids(self.board(), "todo"), [self.c1, self.c3, self.c2])
        # Naar boven: alleen een buur eronder.
        self.patch(self.c2, before_id=self.c1)
        self.assertEqual(self.ids(self.board(), "todo"), [self.c2, self.c1, self.c3])

    def test_move_between_columns(self):
        self.patch(self.c1, status="doing")
        self.patch(self.c2, status="doing")  # zonder buren: onderaan
        self.assertEqual(self.ids(self.board(), "doing"), [self.c1, self.c2])
        self.patch(self.c3, status="doing", after_id=self.c1, before_id=self.c2)
        board = self.board()
        self.assertEqual(self.ids(board, "doing"), [self.c1, self.c3, self.c2])
        self.assertEqual(self.ids(board, "todo"), [])

        self.patch(self.c1, status="done")
        self.patch(self.c2, status="done")  # Klaar zonder buren: bovenaan
        board = self.board()
        self.assertEqual(self.ids(board, "done"), [self.c2, self.c1])
        # En weer terug (eigen taak: vrij).
        back = self.patch(self.c1, status="review").json()
        self.assertEqual((back["status"], back["done_at"], back["done_by_name"]), ("review", None, None))

    def test_neighbour_from_other_column_is_422(self):
        self.patch(self.c3, status="doing")
        response = self.patch(self.c1, status="review", after_id=self.c3)
        self.assertEqual(response.status_code, 422)
        self.assertIsInstance(response.json()["detail"], str)
        self.assertEqual(self.card_row(self.c1).status, "todo")


# --- bronnen terugschrijven ---------------------------------------------------------------


class ScanFlowTests(_Base):
    def setUp(self):
        super().setUp()
        scan = self.add_scan(1)
        self.a = self.add_issue(scan, "title_too_long", "https://klant.nl/a")
        self.b = self.add_issue(scan, "title_too_long", "https://klant.nl/b")
        self.card = self.card_by_source(self.board(), "scan")["id"]

    def scan_cards(self):
        with self.Session() as db:
            return db.query(WorkItem).filter(WorkItem.source == "scan").count()

    def test_done_resolves_issues_and_reopen_restores(self):
        done = self.patch(self.card, status="done").json()
        self.assertEqual((done["status"], done["done_by_name"], done["resolved_by_source"]), ("done", "jan", False))
        self.assertEqual([self.issue_status(self.a), self.issue_status(self.b)], ["opgelost", "opgelost"])

        reopened = self.patch(self.card, status="doing")
        self.assertEqual(reopened.status_code, 200, reopened.text)
        self.assertEqual(reopened.json()["status"], "doing")
        self.assertEqual(reopened.json()["item_count"], 2)
        self.assertEqual([self.issue_status(self.a), self.issue_status(self.b)], ["open", "open"])

        board = self.board()
        self.assertEqual(self.ids(board, "doing"), [self.card])
        self.assertEqual(self.scan_cards(), 1)

    def test_resolved_by_source_cannot_reopen(self):
        self.set_issue_status("opgelost", self.a, self.b)
        board = self.board()
        card = self.column(board, "done")["cards"][0]
        self.assertEqual((card["id"], card["resolved_by_source"]), (self.card, True))
        response = self.patch(self.card, status="todo")
        self.assertEqual((response.status_code, response.json()["detail"]), (409, RESOLVED_BY_SOURCE))

    def test_reopen_with_open_card_for_group_is_409(self):
        self.patch(self.card, status="done")
        monitor = self.add_scan(6, days=1)
        self.add_issue(monitor, "title_too_long", "https://klant.nl/c", days=1)
        new_card = self.ids(self.board(), "todo")
        self.assertEqual(len(new_card), 1)
        self.assertNotEqual(new_card[0], self.card)

        response = self.patch(self.card, status="todo")
        self.assertEqual((response.status_code, response.json()["detail"]), (409, GROUP_ALREADY_OPEN))
        self.assertEqual(self.issue_status(self.a), "opgelost")

    def test_reopen_when_source_has_nothing_open_rolls_back(self):
        self.patch(self.card, status="done")
        self.set_issue_status("genegeerd", self.a, self.b)
        response = self.patch(self.card, status="todo", assignee_id=USER)
        self.assertEqual((response.status_code, response.json()["detail"]), (409, NOTHING_OPEN))
        row = self.card_row(self.card)
        self.assertEqual((row.status, row.assignee_id), ("done", None))
        self.assertEqual(self.issue_status(self.a), "genegeerd")

    def test_delete_ignores_issues_and_card_stays_away(self):
        self.assertEqual(self.client.delete(f"{API}/cards/{self.card}").json(), {"ok": True})
        self.assertEqual([self.issue_status(self.a), self.issue_status(self.b)], ["genegeerd", "genegeerd"])
        self.assertEqual(self.card_row(self.card).status, "removed")
        board = self.board()
        self.assertEqual(self.all_cards(board), [])
        self.assertEqual(self.scan_cards(), 1)

    def test_auto_card_title_and_kind_are_fixed(self):
        for body in ({"title": "Anders"}, {"kind": "links"}):
            with self.subTest(body=body):
                response = self.patch(self.card, **body)
                self.assertEqual(response.status_code, 422)
                self.assertIsInstance(response.json()["detail"], str)
        self.assertEqual(self.card_row(self.card).title, "Title te lang")


class AnalysisFlowTests(_Base):
    def setUp(self):
        super().setUp()
        _analysis, _keyword, self.actions = self.add_analysis("seo bureau", ["FAQ", "Titel"])
        self.card = self.card_by_source(self.board(), "analysis")["id"]

    def test_done_checks_actions_and_reopen_unchecks(self):
        self.assertEqual(self.patch(self.card, status="done").status_code, 200)
        for action_id in self.actions:
            action = self.action(action_id)
            self.assertEqual((action.done, action.done_by), (True, USER))
            self.assertIsNotNone(action.done_at)

        response = self.patch(self.card, status="todo")
        self.assertEqual(response.status_code, 200, response.text)
        for action_id in self.actions:
            action = self.action(action_id)
            self.assertEqual((action.done, action.done_by, action.done_at), (False, None, None))
        self.assertEqual(self.ids(self.board(), "todo"), [self.card])

    def test_delete_card_stays_away(self):
        self.assertEqual(self.client.delete(f"{API}/cards/{self.card}").status_code, 200)
        self.assertEqual(self.all_cards(self.board()), [])
        self.assertFalse(self.action(self.actions[0]).done)


class SiteChangesFlowTests(_Base):
    def setUp(self):
        super().setUp()
        self.add_suggestion_page()
        self.card = self.card_by_source(self.board(), "site_changes")["id"]

    def test_done_with_open_suggestions_is_409(self):
        response = self.patch(self.card, status="done")
        self.assertEqual(response.status_code, 409)
        self.assertIn("nog 1 voorstel open in Aanpassingen", response.json()["detail"])
        row = self.card_row(self.card)
        self.assertEqual((row.status, row.done_at), ("todo", None))
        self.assertEqual(self.ids(self.board(), "todo"), [self.card])

    def test_reopen_is_409(self):
        with self.Session() as db:
            row = db.get(WorkItem, self.card)
            row.status, row.active_key, row.done_at = "done", None, NOW
            db.commit()
        response = self.patch(self.card, status="todo")
        self.assertEqual((response.status_code, response.json()["detail"]), (409, REOPEN_MESSAGE))
        self.assertEqual(self.card_row(self.card).status, "done")


# --- toewijzen en notitie -----------------------------------------------------------------


class AssignAndNoteTests(_Base):
    def setUp(self):
        super().setUp()
        scan = self.add_scan(1)
        self.add_issue(scan, "title_too_long", "https://klant.nl/a")
        self.card = self.card_by_source(self.board(), "scan")["id"]

    def test_assign_and_clear(self):
        card = self.patch(self.card, assignee_id=OTHER_USER).json()
        self.assertEqual((card["assignee_id"], card["assignee_name"]), (OTHER_USER, "anna"))
        self.assertEqual(self.board(assignee_id=OTHER_USER)["totals"]["todo"], 1)
        # Notitie wijzigen laat de toewijzing staan.
        card = self.patch(self.card, note="Eerst de homepage").json()
        self.assertEqual((card["assignee_id"], card["note"], card["has_note"]), (OTHER_USER, "Eerst de homepage", True))
        self.assertTrue(self.card_by_source(self.board(), "scan")["has_note"])

        card = self.patch(self.card, assignee_id=None).json()
        self.assertEqual((card["assignee_id"], card["assignee_name"], card["note"]), (None, None, "Eerst de homepage"))
        card = self.patch(self.card, note=None).json()
        self.assertEqual((card["note"], card["has_note"]), (None, False))

    def test_unknown_assignee_is_422(self):
        response = self.patch(self.card, assignee_id="niemand")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Deze medewerker bestaat niet.")
        self.assertIsNone(self.card_row(self.card).assignee_id)


class UsersAndAuthTests(_Base):
    def test_users(self):
        response = self.client.get(f"{API}/users")
        self.assertEqual(response.json(), [
            {"id": OTHER_USER, "name": "anna", "email": "anna@iexist.nl"},
            {"id": USER, "name": "jan", "email": "jan@iexist.nl"},
        ])

    def test_without_login_is_401(self):
        del self.app.dependency_overrides[require_user_id]
        for method, path in (("get", "/board"), ("get", "/users"), ("get", "/cards/x"), ("post", "/cards"),
                             ("patch", "/cards/x"), ("delete", "/cards/x")):
            with self.subTest(path=path, method=method):
                kwargs = {"json": {}} if method in ("post", "patch") else {}
                response = getattr(self.client, method)(f"{API}{path}", **kwargs)
                self.assertEqual(response.status_code, 401)
                self.assertIsInstance(response.json()["detail"], str)


if __name__ == "__main__":
    unittest.main()
