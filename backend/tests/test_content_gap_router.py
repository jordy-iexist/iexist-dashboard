"""Endpoints van Zoekwoorden › Content gap (features/keywords/gap_router.py) en de mappers.

In-memory SQLite; de taak (`run_content_gap_task.delay`) en `is_configured` van Ahrefs zijn
vervangen: geen netwerk en geen Celery.
"""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import require_user_id
from app.db.models import Base, CustomerCompetitorOverview as Scan, CustomerKeywordGap as Row, CustomerWebsite
from app.db.session import get_db
from app.features.keywords import gap_mappers
from app.features.keywords import gap_router as router_module
from app.features.keywords.gap_router import router
from app.features.keywords.gap_schemas import ContentGapOverview, GapKeyword, GapSnapshot
from app.features.keywords.schemas import Heatmap, Snapshot, SnapshotCompetitor, SourceInfo, Sources, Summary
from app.worker.tasks import run_content_gap_task

USER = "user-1"
TOP5 = ["a.nl", "b.nl", "c.nl", "d.nl", "e.nl"]


def _now():
    return datetime.now(timezone.utc)


def scan_snapshot(top5, others=("weg.nl",)):
    ok = SourceInfo(state="ok")
    competitors = [SnapshotCompetitor(domain=d, origin="ahrefs", in_top5=True) for d in top5]
    competitors += [SnapshotCompetitor(domain=d, origin="ahrefs", in_top5=False) for d in others]
    return Snapshot(sources=Sources(ahrefs=ok, prt=ok, claude=ok, profile=ok), competitors=competitors,
                    heatmap=Heatmap(state="ok"), summary=Summary(state="skipped")).model_dump(mode="json")


def gap_snapshot(competitors=("a.nl", "b.nl")):
    return GapSnapshot(
        customer_domain="klant.nl", competitors=list(competitors), found=7, warnings=["Let op."],
        keywords=[GapKeyword(keyword="dak lekt", volume=900, kd=12, intents=["local"], competitors_count=2,
                             positions={"a.nl": 3, "b.nl": 8}, own_position=14)],
    ).model_dump(mode="json")


class _Base(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.customer_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(id=self.customer_id, name="Klant", base_url="https://www.klant.nl/",
                                   domain="klant.nl", created_by=USER, created_at=_now(), updated_at=_now()))
            db.commit()

        self.ahrefs = self._patch(gap_mappers.ahrefs, "is_configured", Mock(return_value=True))
        self.delay = self._patch(run_content_gap_task, "delay", Mock())

        app = FastAPI()
        app.include_router(router)

        def override_db():
            with self.Session() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_user_id] = lambda: USER
        self.client = TestClient(app)

    def _patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def add_scan(self, top5=TOP5, *, completed_at="now", target="klant.nl", status="completed"):
        now = _now()
        with self.Session() as db:
            db.add(Scan(customer_website_id=self.customer_id, status=status, target=target, country="nl",
                        data=scan_snapshot(top5), created_by=USER, created_at=now, updated_at=now,
                        completed_at=now if completed_at == "now" else completed_at))
            db.commit()

    def add_row(self, status="completed", *, updated_at=None, data="default", **fields):
        now = _now()
        with self.Session() as db:
            db.add(Row(customer_website_id=self.customer_id, status=status, created_by=USER, created_at=now,
                       updated_at=updated_at or now, data=gap_snapshot() if data == "default" else data,
                       **fields))
            db.commit()

    def row(self):
        with self.Session() as db:
            return db.get(Row, self.customer_id)

    def url(self, suffix="", customer_id=None):
        return f"/api/keywords/customers/{customer_id or self.customer_id}/content-gap{suffix}"

    def get(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200, response.text)
        return ContentGapOverview.model_validate(response.json())

    def start(self):
        return self.client.post(self.url("/start"))

    def assert_error(self, response, status, detail):
        self.assertEqual((response.status_code, response.json()["detail"]), (status, detail))


class GetTest(_Base):
    def test_idle_without_scan(self):
        body = self.get()
        self.assertEqual((body.status, body.blocked, body.has_result, body.customer_domain),
                         ("idle", "no_scan", False, "klant.nl"))
        self.assertEqual((body.competitors, body.keywords, body.found, body.units, body.max_units),
                         ([], [], 0, 0, 5000))
        self.assertEqual((body.error, body.started_at, body.completed_at, body.stale, body.warnings),
                         (None, None, None, False, []))

    def test_idle_with_scan_shows_current_top5(self):
        self.add_scan()
        body = self.get()
        self.assertEqual((body.status, body.blocked, body.competitors), ("idle", None, TOP5))

    def test_blocked_order(self):
        self.add_scan(top5=["a.nl"])
        self.assertEqual(self.get().blocked, "too_few_competitors")
        self.ahrefs.return_value = False
        self.assertEqual(self.get().blocked, "ahrefs_not_configured")

    def test_scan_for_other_domain_does_not_count(self):
        self.add_scan(target="oud.nl")
        self.assertEqual(self.get().blocked, "no_scan")

    def test_with_result(self):
        scan_done = _now() - timedelta(days=1)
        self.add_scan(completed_at=scan_done)
        self.add_row(ahrefs_units=4321, source_completed_at=scan_done, completed_at=_now(), started_at=_now())
        body = self.get()
        self.assertEqual((body.status, body.has_result, body.found, body.units, body.stale),
                         ("completed", True, 7, 4321, False))
        self.assertEqual(body.competitors, ["a.nl", "b.nl"])  # van het resultaat, niet de huidige vijf
        self.assertEqual(body.keywords[0].positions, {"a.nl": 3, "b.nl": 8})
        self.assertEqual((body.keywords[0].own_position, body.warnings), (14, ["Let op."]))
        self.assertIsNotNone(body.completed_at.tzinfo)

    def test_stale_when_scan_is_newer(self):
        self.add_scan(completed_at=_now())
        self.add_row(source_completed_at=_now() - timedelta(days=2), completed_at=_now() - timedelta(days=2))
        self.assertTrue(self.get().stale)

    def test_stuck_run_becomes_failed_and_keeps_result(self):
        self.add_scan()
        self.add_row(status="enriching", updated_at=_now() - timedelta(minutes=16))
        body = self.get()
        self.assertEqual((body.status, body.error, body.has_result),
                         ("failed", router_module.MESSAGES["stale"], True))

    def test_running_recently_stays(self):
        self.add_scan()
        self.add_row(status="collecting", updated_at=_now() - timedelta(minutes=5), data=None)
        body = self.get()
        self.assertEqual((body.status, body.has_result), ("collecting", False))

    def test_unknown_customer(self):
        response = self.client.get(self.url(customer_id="bestaat-niet"))
        self.assert_error(response, 404, router_module.MESSAGES["customer"])


class StartTest(_Base):
    def test_start_creates_pending_row(self):
        self.add_scan()
        response = self.start()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "pending")
        self.delay.assert_called_once_with(self.customer_id)
        row = self.row()
        self.assertEqual((row.status, row.created_by), ("pending", USER))

    def test_restart_after_failed_keeps_result(self):
        self.add_scan()
        self.add_row(status="failed", error_message="Kapot.")
        body = ContentGapOverview.model_validate(self.start().json())
        self.assertEqual((body.status, body.error, body.has_result), ("pending", None, True))
        self.delay.assert_called_once()

    def test_400_when_blocked(self):
        self.assert_error(self.start(), 400, gap_mappers.BLOCKED_MESSAGES["no_scan"])
        self.add_scan(top5=["a.nl"])
        self.assert_error(self.start(), 400, gap_mappers.BLOCKED_MESSAGES["too_few_competitors"])
        self.ahrefs.return_value = False
        self.assert_error(self.start(), 400, gap_mappers.BLOCKED_MESSAGES["ahrefs_not_configured"])
        self.delay.assert_not_called()
        self.assertIsNone(self.row())

    def test_409_while_running(self):
        self.add_scan()
        self.add_row(status="collecting")
        self.assert_error(self.start(), 409, router_module.MESSAGES["running"])
        self.delay.assert_not_called()
        self.assertEqual(self.row().status, "collecting")

    def test_stuck_run_can_be_restarted(self):
        self.add_scan()
        self.add_row(status="pending", updated_at=_now() - timedelta(minutes=20))
        self.assertEqual(self.start().status_code, 200)
        self.assertEqual(self.row().status, "pending")
        self.delay.assert_called_once()

    def test_503_without_queue(self):
        self.add_scan()
        self.add_row(status="completed")
        self.delay.side_effect = ConnectionError("redis weg")
        self.assert_error(self.start(), 503, router_module.MESSAGES["not_queued"])
        row = self.row()
        self.assertEqual((row.status, row.error_message), ("failed", router_module.MESSAGES["not_queued"]))
        self.assertIsNotNone(row.data)  # het vorige resultaat blijft staan


if __name__ == "__main__":
    unittest.main()
