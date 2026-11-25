"""Endpoints van het maandrapport (features/monthly_report/router.py) en de mappers.

In-memory SQLite; de taak (`run_monthly_report_task.delay`) en `is_configured` van Claude zijn
vervangen: geen netwerk en geen Celery. "Vandaag" staat vast op 25 november 2026.
"""
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import require_user_id
from app.db.models import Base, CustomerWebsite, MonthlyReport as Row
from app.db.session import get_db
from app.features.monthly_report import mappers
from app.features.monthly_report import router as router_module
from app.features.monthly_report.router import router
from app.features.monthly_report.schemas import Leads, MonthlyReport
from app.worker.tasks import run_monthly_report_task

USER = "user-1"
MONTH = "2026-11"
TODAY = date(2026, 11, 25)


def _now():
    return datetime.now(timezone.utc)


def data(leads=None, leads_previous=None, month=MONTH):
    leads_metric = {"state": "manual" if leads is not None else "not_connected", "value": leads,
                    "previous": leads_previous}
    return {
        "month": month, "collected_at": "2026-11-25T10:00:00+00:00",
        "period": {"start": "2026-11-01", "end": "2026-11-22", "days": 22, "complete": False},
        "metrics": {"clicks": {"state": "ok", "value": 1240, "previous": 1105},
                    "top10": {"state": "ok", "value": 18}, "leads": leads_metric,
                    "ai_mentions": {"state": "not_tracked"}},
    }


REPORT = {"version": 1, "summary": ["Goede maand."], "work_done": [], "next_month": [], "review_notes": []}


class _Base(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.customer_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(id=self.customer_id, name="Klant", base_url="https://klant.nl/",
                                   domain="klant.nl", created_by=USER, created_at=_now(), updated_at=_now()))
            db.commit()

        self.configured = self._patch(router_module.anthropic_client, "is_configured", Mock(return_value=True))
        self.delay = self._patch(run_monthly_report_task, "delay", Mock())
        self._patch(router_module, "today_local", Mock(return_value=TODAY))

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

    def add_row(self, status="completed", month=MONTH, updated_at=None, **fields):
        row_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(Row(id=row_id, customer_website_id=self.customer_id, month=month, status=status,
                       created_by=USER, created_at=_now(), updated_at=updated_at or _now(),
                       completed_at=_now() if status == "completed" else None, **fields))
            db.commit()
        return row_id

    def url(self, suffix="", month=MONTH, customer_id=None):
        return f"/api/monthly-reports/customers/{customer_id or self.customer_id}/reports/{month}{suffix}"

    def row(self, month=MONTH):
        with self.Session() as db:
            return db.query(Row).filter(Row.customer_website_id == self.customer_id, Row.month == month).one_or_none()

    def assert_error(self, response, status, key):
        self.assertEqual((response.status_code, response.json()["detail"]), (status, router_module.MESSAGES[key]))


class MonthValidationTest(_Base):
    def test_unknown_customer(self):
        for method, suffix in (("get", ""), ("post", ""), ("post", "/regenerate")):
            self.assert_error(getattr(self.client, method)(self.url(suffix, customer_id="onbekend")), 404, "customer")
        self.assert_error(self.client.patch(self.url("/manual", customer_id="onbekend"), json={"leads": 1}),
                          404, "customer")

    def test_invalid_future_and_too_old(self):
        for month in ("2026-13", "2026-1", "november"):
            self.assert_error(self.client.get(self.url(month=month)), 422, "invalid_month")
        self.assert_error(self.client.get(self.url(month="2026-12")), 400, "future_month")
        self.assert_error(self.client.post(self.url(month="2027-01")), 400, "future_month")
        self.assert_error(self.client.get(self.url(month="2025-06")), 400, "too_old")
        self.assertEqual(self.client.get(self.url(month="2025-07")).status_code, 200)
        self.assert_error(self.client.patch(self.url("/manual", month="2026-12"), json={"leads": 1}),
                          400, "future_month")


class GetTest(_Base):
    def test_without_row_gives_empty_draft(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200, response.text)
        body = MonthlyReport.model_validate(response.json())
        self.assertEqual((body.id, body.status, body.customer_website_id, body.month),
                         (None, "draft", self.customer_id, MONTH))
        self.assertEqual((body.data, body.report, body.text_outdated), (None, None, False))
        self.assertEqual(body.leads, Leads())
        self.assertEqual(body.ai_usage.calls, 0)
        self.assertIsNone(self.row())

    def test_without_row_takes_previous_leads_from_previous_report(self):
        self.add_row(month="2026-10", manual={"leads": 10})
        body = self.client.get(self.url()).json()
        self.assertEqual((body["leads"]["value"], body["leads"]["previous"], body["leads"]["previous_source"]),
                         (None, 10, "previous_report"))

    def test_full_report(self):
        row_id = self.add_row(data=data(14, 10), report=REPORT, manual={"leads": 14, "leads_previous": 10},
                              model="claude-sonnet-5-5",
                              ai_usage={"calls": 1, "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.01})
        body = MonthlyReport.model_validate(self.client.get(self.url()).json())
        self.assertEqual((body.id, body.status, body.model, body.ai_usage.calls), (row_id, "completed",
                                                                                 "claude-sonnet-5-5", 1))
        self.assertEqual((body.leads.value, body.leads.previous, body.leads.previous_source), (14, 10, "manual"))
        self.assertFalse(body.text_outdated)
        self.assertEqual(body.data.metrics.clicks.value, 1240)
        self.assertEqual(body.report.summary, ["Goede maand."])

    def test_broken_json_columns_become_none(self):
        self.add_row(data={"kapot": True}, report=["x"], manual="kapot", ai_usage=5)
        body = self.client.get(self.url()).json()
        self.assertEqual((body["data"], body["report"], body["leads"]["value"]), (None, None, None))

    def test_stale_active_report_becomes_failed(self):
        self.add_row(status="writing", updated_at=_now() - timedelta(minutes=16))
        body = self.client.get(self.url()).json()
        self.assertEqual((body["status"], body["error_message"]), ("failed", router_module.MESSAGES["stale"]))

    def test_recent_active_report_stays(self):
        self.add_row(status="collecting", updated_at=_now() - timedelta(minutes=14))
        self.assertEqual(self.client.get(self.url()).json()["status"], "collecting")


class TextOutdatedTest(unittest.TestCase):
    def row(self, **fields):
        return Row(id="r", customer_website_id="c", month=MONTH, status="completed", **fields)

    def test_text_outdated(self):
        row = self.row(data=data(14, 10), report=REPORT, manual={"leads": 14, "leads_previous": 10})
        self.assertFalse(mappers.text_outdated(row, Leads(value=14, previous=10)))
        self.assertTrue(mappers.text_outdated(row, Leads(value=15, previous=10)))
        self.assertTrue(mappers.text_outdated(row, Leads(value=14, previous=None)))
        # Zonder tekst is er niets verouderd.
        self.assertFalse(mappers.text_outdated(self.row(data=data(14, 10)), Leads(value=99)))
        self.assertFalse(mappers.text_outdated(None, Leads(value=99)))
        # Tekst zonder aanvragen; daarna een cijfer ingevuld.
        row = self.row(data=data(), report=REPORT)
        self.assertFalse(mappers.text_outdated(row, Leads()))
        self.assertTrue(mappers.text_outdated(row, Leads(value=3)))

    def test_effective_leads(self):
        previous = self.row(manual={"leads": 10})
        self.assertEqual(mappers.effective_leads(self.row(manual={"leads": 14}), previous),
                         Leads(value=14, previous=10, previous_source="previous_report"))
        self.assertEqual(mappers.effective_leads(self.row(manual={"leads": 14, "leads_previous": 12}), previous),
                         Leads(value=14, previous=12, previous_source="manual"))
        self.assertEqual(mappers.effective_leads(None, None), Leads())
        self.assertEqual(mappers.effective_leads(None, self.row(manual={"leads": None})), Leads())


class StartTest(_Base):
    def test_start_creates_pending_row_and_task(self):
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        row = self.row()
        self.assertEqual((body["id"], body["status"], row.status, row.created_by), (row.id, "pending", "pending", USER))
        self.delay.assert_called_once_with(row.id)

    def test_start_from_draft_keeps_manual(self):
        self.add_row(status="draft", manual={"leads": 5})
        body = self.client.post(self.url()).json()
        self.assertEqual((body["status"], body["leads"]["value"]), ("pending", 5))
        self.delay.assert_called_once()

    def test_start_after_failure(self):
        self.add_row(status="failed", error_message="mis", updated_at=_now() - timedelta(hours=2))
        body = self.client.post(self.url()).json()
        self.assertEqual((body["status"], body["error_message"]), ("pending", None))
        # Het oude `updated_at` is ververst: de herstelcontrole zet hem niet meteen terug.
        self.assertEqual(self.client.get(self.url()).json()["status"], "pending")

    def test_409_when_running_or_completed(self):
        self.add_row(status="collecting")
        self.assert_error(self.client.post(self.url()), 409, "running")
        with self.Session() as db:
            db.query(Row).update({"status": "completed"})
            db.commit()
        self.assert_error(self.client.post(self.url()), 409, "exists")
        self.delay.assert_not_called()

    def test_stale_run_is_recovered_and_restarted(self):
        self.add_row(status="writing", updated_at=_now() - timedelta(minutes=20))
        self.assertEqual(self.client.post(self.url()).json()["status"], "pending")
        self.delay.assert_called_once()

    def test_atomic_update_lost_gives_409(self):
        self.add_row(status="failed")
        real_restart = router_module._restart

        def concurrent(db, row, allowed):
            db.query(Row).filter(Row.id == row.id).update({"status": "pending"})
            db.commit()
            return real_restart(db, row, allowed)

        with patch.object(router_module, "_restart", concurrent):
            self.assert_error(self.client.post(self.url()), 409, "running")
        self.delay.assert_not_called()

    def test_503_without_claude(self):
        self.configured.return_value = False
        self.assert_error(self.client.post(self.url()), 503, "not_configured")
        self.assertIsNone(self.row())

    def test_503_when_queue_unreachable(self):
        self.delay.side_effect = ConnectionError("redis weg")
        with self.assertLogs(router_module.logger, "ERROR"):
            self.assert_error(self.client.post(self.url()), 503, "not_queued")
        row = self.row()
        self.assertEqual((row.status, row.error_message), ("failed", router_module.MESSAGES["not_queued"]))


class RegenerateTest(_Base):
    def test_regenerate_keeps_previous_data_report_and_manual(self):
        self.add_row(data=data(14), report=REPORT, manual={"leads": 14})
        body = self.client.post(self.url("/regenerate")).json()
        self.assertEqual(body["status"], "pending")
        self.assertEqual((body["report"]["summary"], body["data"]["metrics"]["clicks"]["value"], body["leads"]["value"]),
                         (["Goede maand."], 1240, 14))
        self.delay.assert_called_once_with(self.row().id)

    def test_regenerate_after_failure(self):
        self.add_row(status="failed", report=REPORT)
        self.assertEqual(self.client.post(self.url("/regenerate")).json()["status"], "pending")

    def test_409_without_report_or_while_running(self):
        self.assert_error(self.client.post(self.url("/regenerate")), 409, "no_report")
        self.add_row(status="draft")
        self.assert_error(self.client.post(self.url("/regenerate")), 409, "no_report")
        with self.Session() as db:
            db.query(Row).update({"status": "pending"})
            db.commit()
        self.assert_error(self.client.post(self.url("/regenerate")), 409, "running")
        self.delay.assert_not_called()

    def test_503_without_claude_leaves_row(self):
        self.add_row()
        self.configured.return_value = False
        self.assert_error(self.client.post(self.url("/regenerate")), 503, "not_configured")
        self.assertEqual(self.row().status, "completed")

    def test_queue_unreachable_keeps_report(self):
        self.add_row(data=data(), report=REPORT)
        self.delay.side_effect = ConnectionError("redis weg")
        with self.assertLogs(router_module.logger, "ERROR"):
            self.assert_error(self.client.post(self.url("/regenerate")), 503, "not_queued")
        row = self.row()
        self.assertEqual((row.status, row.report), ("failed", REPORT))


class ManualTest(_Base):
    def test_without_row_creates_draft(self):
        response = self.client.patch(self.url("/manual"), json={"leads": 14, "leads_previous": 10})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["status"], body["leads"]["value"], body["leads"]["previous"],
                          body["leads"]["previous_source"]), ("draft", 14, 10, "manual"))
        self.assertIsNotNone(body["leads"]["updated_at"])
        row = self.row()
        self.assertEqual((row.status, row.manual["leads"], row.manual["updated_by"]), ("draft", 14, USER))
        self.delay.assert_not_called()

    def test_during_run_only_manual_changes(self):
        stamp = _now() - timedelta(minutes=5)
        self.add_row(status="writing", updated_at=stamp, data=data(1), report=REPORT)
        body = self.client.patch(self.url("/manual"), json={"leads": 7}).json()
        self.assertEqual((body["status"], body["leads"]["value"]), ("writing", 7))
        row = self.row()
        self.assertEqual(row.updated_at.replace(tzinfo=None), stamp.replace(tzinfo=None))
        self.assertEqual((row.status, row.manual["leads"], row.report), ("writing", 7, REPORT))

    def test_null_clears_and_marks_text_outdated(self):
        self.add_row(data=data(14), report=REPORT, manual={"leads": 14})
        self.assertFalse(self.client.get(self.url()).json()["text_outdated"])
        body = self.client.patch(self.url("/manual"), json={"leads": None, "leads_previous": None}).json()
        self.assertEqual((body["leads"]["value"], body["leads"]["previous"]), (None, None))
        self.assertTrue(body["text_outdated"])
        self.assertEqual(self.row().manual["leads"], None)

    def test_changed_leads_mark_text_outdated(self):
        self.add_row(data=data(14), report=REPORT, manual={"leads": 14})
        body = self.client.patch(self.url("/manual"), json={"leads": 15}).json()
        self.assertTrue(body["text_outdated"])

    def test_previous_from_previous_report(self):
        self.add_row(month="2026-10", manual={"leads": 9})
        body = self.client.patch(self.url("/manual"), json={"leads": 12}).json()
        self.assertEqual((body["leads"]["previous"], body["leads"]["previous_source"]), (9, "previous_report"))

    def test_validation(self):
        for payload in ({"leads": -1}, {"leads_previous": 2_000_000}, {"leads": "veel"}):
            self.assertEqual(self.client.patch(self.url("/manual"), json=payload).status_code, 422)
        self.assertIsNone(self.row())

    def test_integrity_error_updates_existing_row(self):
        existing = self.add_row(status="draft", manual={"leads": 1})
        real_find = router_module._find
        calls = []

        def find(db, customer_id, month):
            calls.append(month)
            return None if len(calls) == 1 else real_find(db, customer_id, month)

        with patch.object(router_module, "_find", find):
            body = self.client.patch(self.url("/manual"), json={"leads": 3}).json()
        self.assertEqual((body["id"], body["leads"]["value"]), (existing, 3))


class RecoverTest(_Base):
    def test_recover_stale_report(self):
        now = _now()
        with self.Session() as db:
            row = Row(id="r", customer_website_id=self.customer_id, month=MONTH, status="pending", created_by=USER,
                      created_at=now, updated_at=now - timedelta(minutes=15))
            db.add(row)
            db.commit()
            self.assertFalse(router_module.recover_stale_report(db, None))
            self.assertTrue(router_module.recover_stale_report(db, row, now=now))
            self.assertEqual(row.status, "failed")
            self.assertFalse(router_module.recover_stale_report(db, row, now=now))
            row.status = "completed"
            row.updated_at = now - timedelta(days=1)
            db.commit()
            self.assertFalse(router_module.recover_stale_report(db, row, now=now))


class AppRegistrationTest(unittest.TestCase):
    def test_router_is_registered(self):
        from app.main import app

        paths = set(app.openapi()["paths"])
        self.assertIn("/api/monthly-reports/customers/{customer_id}/reports/{month}", paths)
        self.assertIn("/api/monthly-reports/customers/{customer_id}/reports/{month}/manual", paths)
        self.assertIn("/api/monthly-reports/customers/{customer_id}/reports/{month}/regenerate", paths)


if __name__ == "__main__":
    unittest.main()
