"""De taak van het maandrapport (features/monthly_report/worker/report.py).

SQLite in een tijdelijke map; `SessionLocal` is vervangen, en `collect` en de agent
(`report_agent.write_report`) ook: geen netwerk en niets naar Anthropic. De taak draait direct
via `.run(...)`.
"""
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, CustomerWebsite, MonthlyReport
from app.features.monthly_report.schemas import Metric, Metrics, ReportData, ReportItem, ReportText
from app.features.monthly_report.services import report_agent as agent
from app.features.monthly_report.worker import report as worker
from app.services.anthropic.client import AnthropicServiceError

USER = "user-1"
USAGE = {"input_tokens": 10_000, "output_tokens": 2_000}


def _now():
    return datetime.now(timezone.utc)


def report_data(month="2026-11", clicks=1240):
    return ReportData(
        month=month, collected_at=_now(),
        metrics=Metrics(clicks=Metric(state="ok", value=clicks), top10=Metric(state="out_of_window"),
                        leads=Metric(state="not_connected"), ai_mentions=Metric(state="not_configured")),
    )


def report_text(version=1, summary="Goede maand."):
    return ReportText(version=version, summary=[summary],
                      work_done=[ReportItem(text="Meta descriptions verbeterd.", refs=["W1"])])


def result(version=1, **overrides):
    values = dict(state="ok", report=report_text(version), usage=USAGE, model="claude-sonnet-5-5")
    values.update(overrides)
    return agent.ReportResult(**values)


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        engine = create_engine(f"sqlite:///{self.tmp.name}/test.db", connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self._patch(worker, "SessionLocal", self.Session)
        self.collect = self._patch(worker, "collect", Mock(return_value=report_data()))
        self.write = self._patch(agent, "write_report", Mock(return_value=result()))

        self.customer_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(id=self.customer_id, name="Klant BV", base_url="https://www.klant.nl/",
                                   domain="klant.nl", seo_goals="Meer aanvragen", tone_of_voice="Nuchter.",
                                   form_of_address="je", profile={"company": {"description": "Bureau."}},
                                   created_by=USER, created_at=_now(), updated_at=_now()))
            db.commit()

    def _patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def add_report(self, status="pending", month="2026-11", **fields):
        report_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(MonthlyReport(id=report_id, customer_website_id=self.customer_id, month=month, status=status,
                                 created_by=USER, created_at=_now(), updated_at=_now(), **fields))
            db.commit()
        return report_id

    def get(self, report_id):
        with self.Session() as db:
            return db.get(MonthlyReport, report_id)


class RunTest(_Base):
    def test_pending_to_completed(self):
        report_id = self.add_report(manual={"leads": 14})
        statuses = []
        self.write.side_effect = lambda *a, **k: statuses.append(self.get(report_id).status) or result()

        self.assertEqual(worker.run_monthly_report_task.run(report_id), report_id)
        row = self.get(report_id)
        self.assertEqual((row.status, row.error_message, row.model), ("completed", None, "claude-sonnet-5-5"))
        self.assertEqual(statuses, ["writing"])
        self.assertIsNotNone(row.completed_at)
        self.assertEqual(ReportData.model_validate(row.data).metrics.clicks.value, 1240)
        self.assertEqual(ReportText.model_validate(row.report).version, 1)
        self.assertEqual((row.ai_usage["calls"], row.ai_usage["input_tokens"], row.ai_usage["output_tokens"]),
                         (1, 10_000, 2_000))
        self.assertGreater(row.ai_usage["cost_usd"], 0)
        self.assertEqual(row.manual, {"leads": 14})

        db_arg, customer, month = self.collect.call_args.args
        self.assertEqual((customer.id, month), (self.customer_id, "2026-11"))
        kwargs = self.collect.call_args.kwargs
        self.assertEqual((kwargs["previous_data"], kwargs["previous_month_row"]), (None, None))
        self.assertEqual(kwargs["manual"].leads, 14)

        data, report_customer = self.write.call_args.args
        self.assertIsInstance(data, ReportData)
        self.assertEqual((report_customer.name, report_customer.domain, report_customer.form_of_address,
                          report_customer.tone_of_voice, report_customer.seo_goals),
                         ("Klant BV", "klant.nl", "je", "Nuchter.", "Meer aanvragen"))
        self.assertIsNotNone(report_customer.profile)
        self.assertEqual(self.write.call_args.kwargs, {"version": 1})

    def test_collecting_status_while_collecting(self):
        report_id = self.add_report()
        seen = []
        self.collect.side_effect = lambda *a, **k: seen.append(self.get(report_id).status) or report_data()
        worker.run_monthly_report_task.run(report_id)
        self.assertEqual(seen, ["collecting"])

    def test_regenerate_passes_previous_data_and_increments_version(self):
        old = report_data(clicks=900).model_dump(mode="json")
        report_id = self.add_report(data=old, report=report_text(2, "Oud.").model_dump(mode="json"),
                                    ai_usage={"calls": 1, "input_tokens": 5, "output_tokens": 5, "cost_usd": 0.5})
        previous_id = self.add_report(status="completed", month="2026-10", manual={"leads": 10})
        self.add_report(status="completed", month="2026-09")
        self.write.return_value = result(3)

        worker.run_monthly_report_task.run(report_id)
        kwargs = self.collect.call_args.kwargs
        self.assertEqual(kwargs["previous_data"], old)
        self.assertEqual(kwargs["previous_month_row"].id, previous_id)
        self.assertEqual(self.write.call_args.kwargs, {"version": 3})
        row = self.get(report_id)
        self.assertEqual((row.status, row.report["version"], row.data["metrics"]["clicks"]["value"]),
                         ("completed", 3, 1240))
        self.assertEqual(row.ai_usage["calls"], 2)
        self.assertGreater(row.ai_usage["cost_usd"], 0.5)

    def test_not_pending_does_nothing(self):
        for status in ("draft", "collecting", "completed", "failed"):
            report_id = self.add_report(status=status, month=f"2025-{len(status):02d}")
            worker.run_monthly_report_task.run(report_id)
            self.assertEqual(self.get(report_id).status, status)
        worker.run_monthly_report_task.run("onbekend")
        self.collect.assert_not_called()
        self.write.assert_not_called()

    def test_manual_written_during_run_is_kept(self):
        report_id = self.add_report(manual={"leads": 1})

        def write(*_a, **_k):
            with self.Session() as db:
                db.query(MonthlyReport).filter(MonthlyReport.id == report_id).update({"manual": {"leads": 99}})
                db.commit()
            return result()

        self.write.side_effect = write
        worker.run_monthly_report_task.run(report_id)
        self.assertEqual(self.get(report_id).manual, {"leads": 99})

    def test_recovered_row_is_not_overwritten(self):
        report_id = self.add_report()

        def write(*_a, **_k):
            with self.Session() as db:
                db.query(MonthlyReport).filter(MonthlyReport.id == report_id).update(
                    {"status": "failed", "error_message": "onderbroken"})
                db.commit()
            return result()

        self.write.side_effect = write
        worker.run_monthly_report_task.run(report_id)
        row = self.get(report_id)
        self.assertEqual((row.status, row.error_message, row.report), ("failed", "onderbroken", None))


class FailureTest(_Base):
    def setUp(self):
        super().setUp()
        self.old_data = report_data(clicks=900).model_dump(mode="json")
        self.old_report = report_text(1, "Oud.").model_dump(mode="json")

    def run_failing(self):
        report_id = self.add_report(data=self.old_data, report=self.old_report)
        worker.run_monthly_report_task.run(report_id)
        row = self.get(report_id)
        # Het vorige paar blijft staan.
        self.assertEqual((row.data, row.report), (self.old_data, self.old_report))
        self.assertIsNone(row.completed_at)
        return row

    def test_not_configured(self):
        self.write.return_value = agent.ReportResult(state="not_configured", message="Claude is niet ingesteld.")
        row = self.run_failing()
        self.assertEqual((row.status, row.error_message), ("failed", "Claude is niet ingesteld."))

    def test_anthropic_error(self):
        self.write.side_effect = AnthropicServiceError("Overbelast.", code="overloaded")
        row = self.run_failing()
        self.assertEqual((row.status, row.error_message), ("failed", "Claude gaf een fout: Overbelast."))

    def test_soft_time_limit(self):
        self.collect.side_effect = SoftTimeLimitExceeded()
        row = self.run_failing()
        self.assertEqual((row.status, row.error_message), ("failed", worker.TIMEOUT_MESSAGE))

    def test_unexpected_error(self):
        self.write.side_effect = RuntimeError("geheim")
        row = self.run_failing()
        self.assertEqual(row.status, "failed")
        self.assertIn("RuntimeError", row.error_message)
        self.assertNotIn("geheim", row.error_message)

    def test_customer_gone(self):
        report_id = self.add_report()
        with self.Session() as db:
            db.query(CustomerWebsite).delete()
            db.commit()
        worker.run_monthly_report_task.run(report_id)
        self.assertEqual((self.get(report_id).status, self.get(report_id).error_message),
                         ("failed", worker.GONE_MESSAGE))


class RegistrationTest(unittest.TestCase):
    def test_task_registration(self):
        task = worker.run_monthly_report_task
        self.assertEqual(task.name, "app.worker.tasks.run_monthly_report_task")
        self.assertEqual((task.soft_time_limit, task.time_limit), (540, 600))
        from app.worker import tasks
        from app.worker.celery_app import celery_app

        self.assertIs(tasks.run_monthly_report_task, task)
        self.assertIn("run_monthly_report_task", tasks.__all__)
        self.assertEqual(celery_app.conf.task_routes["app.worker.tasks.run_monthly_report_task"], {"queue": "default"})


if __name__ == "__main__":
    unittest.main()
