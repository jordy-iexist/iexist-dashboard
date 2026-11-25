"""De taak van Zoekwoorden › Concurrenten (features/keywords/worker/refresh.py).

SQLite in een tijdelijke map; `SessionLocal` is vervangen. De ophaler (`collect`) en Claude
(`ai`) zijn vervangen door nepfuncties met realistische `Raw`-gegevens; de rekenregels
(`compute`) zijn echt. Geen netwerk. De taak draait direct via `.run(...)`.
"""
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, CustomerCompetitorOverview as Row, CustomerWebsite
from app.features.keywords.schemas import (
    DomainClass,
    Overrides,
    Raw,
    RawCompetitor,
    RawMetrics,
    RawPrt,
    RawTop10,
    Snapshot,
    Summary,
    TopicAssignment,
    TrackedKeyword,
    TrafficPoint,
)
from app.features.keywords import mappers
from app.features.keywords.services import ai, collect
from app.features.keywords.worker import refresh as worker
from app.services.ahrefs import AhrefsServiceError
from app.services.anthropic.client import AnthropicServiceError

USER = "user-1"
USAGE = {"input_tokens": 1000, "output_tokens": 200}
MODEL = "claude-sonnet-5-5"
PROFILE = {"company_type": "Dakdekkersbedrijf", "service_area": "Utrecht en omgeving",
           "services": [{"name": "Dakreparatie"}, {"name": "Dakisolatie"}]}

# (domein, DR, gedeelde zoekwoorden, share); klein.nl valt onder MIN_SHARED_KEYWORDS.
COMPETITORS = [
    ("dakwerk.nl", 31, 120, 12.5), ("werkspot.nl", 70, 300, 20.0), ("dakmeester.nl", 25, 80, 8.0),
    ("utrechtdak.nl", 18, 60, 6.5), ("daklekkage.nl", 22, 40, 4.0), ("dakpro.nl", 28, 30, 3.0),
    ("klein.nl", 10, 3, 0.4),
]
REPAIR = ["dakreparatie utrecht", "dak repareren", "daklekkage verhelpen", "dakpannen vervangen",
          "dak lekt", "dakgoot repareren"]
INSULATION = ["dakisolatie kosten", "dakisolatie subsidie", "dak isoleren binnenkant", "platdak isoleren",
              "dakisolatie zeist"]
LOCAL = ["dakreparatie utrecht", "dakisolatie zeist", "dakdekker in de buurt"]
CLAIMED_UNITS = 120
METRICS_UNITS = 200
TOP10_UNITS = 300


def _now():
    return datetime.now(timezone.utc)


def base_raw():
    return Raw(
        fetched_at=_now(),
        prt=RawPrt(state="ok", rows=[TrackedKeyword(keyword="dakreparatie utrecht", rank=3, volume=900),
                                     TrackedKeyword(keyword="dak lekt", rank=None, volume=500),
                                     TrackedKeyword(keyword="dakdekker in de buurt", rank=8, volume=300)]),
        competitors=[RawCompetitor(domain=d, domain_rating=dr, keywords_common=c, keywords_competitor=c * 8,
                                   keywords_target=400, share=s) for d, dr, c, s in COMPETITORS],
    )


def fake_candidates(*, base_url, country, manual_domains, previous, budget):
    budget.add(0 if previous is not None else CLAIMED_UNITS)
    return previous.model_copy(deep=True) if previous is not None else base_raw()


def fake_metrics(raw, *, base_url, country, domains, keyword_domains, budget):
    raw = raw.model_copy(deep=True)
    budget.add(METRICS_UNITS)
    for index, domain in enumerate(["klant.nl", *domains]):
        raw.metrics.setdefault(domain, RawMetrics(domain_rating=20 + index, org_keywords=1000 + index,
                                                  org_keywords_1_3=20, org_keywords_4_10=60, org_traffic=5000))
    raw.traffic_history = [TrafficPoint(date="2026-09-01", org_traffic=5000),
                           TrafficPoint(date="2026-10-01", org_traffic=5400)]
    if keyword_domains:
        for domain in ["klant.nl", *keyword_domains]:
            if domain not in raw.top10:
                budget.add(TOP10_UNITS)
                words = REPAIR[:3] if domain == "klant.nl" else REPAIR + INSULATION
                raw.top10[domain] = RawTop10(keywords=list(words), truncated=domain == "dakwerk.nl")
    return raw


def fake_classify(items, *, customer_domain, company_type, service_area):
    classes = {i.domain: DomainClass(type="landelijk" if i.domain == "werkspot.nl" else "regio",
                                     is_aggregator=i.domain == "werkspot.nl", reason="test") for i in items}
    return classes, USAGE, MODEL


def fake_assign(keywords, topics, *, company_type, service_area):
    keys = set(keywords)
    return TopicAssignment(services={"Dakreparatie": [k for k in REPAIR if k in keys],
                                     "Dakisolatie": [k for k in INSULATION if k in keys]},
                           local=[k for k in LOCAL if k in keys]), USAGE, MODEL


def fake_summarize(snapshot, *, customer_name):
    return Summary(state="ok", paragraph="Klant BV wint op dakreparatie.", points=["Een.", "Twee.", "Drie."]), \
        USAGE, MODEL


class _Base(unittest.TestCase):
    profile = PROFILE

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        engine = create_engine(f"sqlite:///{self.tmp.name}/test.db", connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self._patch(worker, "SessionLocal", self.Session)
        self.claude_ready = self._patch(worker.claude, "is_configured", Mock(return_value=True))
        self._patch(mappers.ahrefs, "is_configured", Mock(return_value=True))
        self.statuses: list[tuple[str, str]] = []
        self.candidates = self._patch(collect, "collect_candidates", Mock(side_effect=self._seen("candidates", fake_candidates)))
        self.metrics = self._patch(collect, "collect_metrics", Mock(side_effect=self._seen("metrics", fake_metrics)))
        self.checks = self._patch(collect, "collect_keyword_checks",
                                  Mock(side_effect=self._seen("checks", lambda raw, **kw: raw)))
        self.classify = self._patch(ai, "classify_domains", Mock(side_effect=self._seen("classify", fake_classify)))
        self.assign = self._patch(ai, "assign_keywords", Mock(side_effect=self._seen("assign", fake_assign)))
        self.summarize = self._patch(ai, "summarize", Mock(side_effect=self._seen("summarize", fake_summarize)))

        self.customer_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(id=self.customer_id, name="Klant BV", base_url="https://www.klant.nl/",
                                   domain="klant.nl", profile=self.profile, created_by=USER, created_at=_now(),
                                   updated_at=_now()))
            db.commit()

    def _patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def _seen(self, step, func):
        def wrapper(*args, **kwargs):
            self.statuses.append((step, self.get().status))
            return func(*args, **kwargs)
        return wrapper

    def add_row(self, status="pending", **fields):
        with self.Session() as db:
            db.add(Row(customer_website_id=self.customer_id, status=status, created_by=USER, created_at=_now(),
                       updated_at=_now(), **fields))
            db.commit()

    def get(self):
        with self.Session() as db:
            return db.get(Row, self.customer_id)

    def set_pending(self):
        with self.Session() as db:
            db.query(Row).update({"status": "pending"})
            db.commit()

    def run_task(self, mode="full"):
        self.assertEqual(worker.refresh_keyword_competitors_task.run(self.customer_id, mode), self.customer_id)
        return self.get()

    def snapshot(self):
        return Snapshot.model_validate(self.get().data)


class RunTest(_Base):
    def test_successful_run(self):
        overrides = Overrides.model_validate({
            "manual": [{"domain": "handmatig.nl", "added_by": USER, "added_at": _now().isoformat()}],
            "domains": {"dakwerk.nl": {"type": "landelijk", "excluded": None}},
        }).model_dump(mode="json")
        changed_at = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.add_row(overrides=overrides, overrides_changed_at=changed_at)

        # De router schrijft tijdens de run een nieuwe keuze; de taak mag die niet overschrijven.
        written = Overrides.model_validate({**overrides, "domains": {"dakpro.nl": {"excluded": True}}}).model_dump(
            mode="json")

        def metrics_and_router_write(raw, **kwargs):
            with self.Session() as db:
                db.query(Row).update({"overrides": written})
                db.commit()
            return fake_metrics(raw, **kwargs)

        self.metrics.side_effect = self._seen("metrics", metrics_and_router_write)
        row = self.run_task()

        self.assertEqual((row.status, row.error_message, row.target, row.country), ("completed", None, "klant.nl", "nl"))
        self.assertIsNotNone(row.started_at)
        self.assertIsNotNone(row.completed_at)
        self.assertEqual(row.overrides, written)
        self.assertEqual(row.overrides_changed_at.replace(tzinfo=timezone.utc), changed_at)
        self.assertEqual(row.ahrefs_units, CLAIMED_UNITS + METRICS_UNITS + 6 * TOP10_UNITS)
        self.assertEqual((row.ai_usage["calls"], row.ai_usage["input_tokens"], row.model), (3, 3000, MODEL))
        self.assertGreater(row.ai_usage["cost_usd"], 0)
        self.assertEqual(self.statuses, [("candidates", "collecting"), ("classify", "classifying"),
                                         ("metrics", "collecting"), ("assign", "classifying"),
                                         ("checks", "collecting"), ("summarize", "summarizing")])

        raw = Raw.model_validate(row.raw)
        self.assertIn("dakwerk.nl", raw.top10)
        self.assertIsNone(self.candidates.call_args.kwargs["previous"])
        self.assertEqual(self.candidates.call_args.kwargs["manual_domains"], ["handmatig.nl"])

        top5 = ["handmatig.nl", "dakwerk.nl", "dakmeester.nl", "utrechtdak.nl", "daklekkage.nl"]
        metrics_kwargs = self.metrics.call_args.kwargs
        self.assertEqual(metrics_kwargs["keyword_domains"], top5)
        self.assertEqual(metrics_kwargs["domains"], top5 + ["werkspot.nl"])
        self.assertEqual(self.classify.call_args.kwargs,
                         {"customer_domain": "klant.nl", "company_type": "Dakdekkersbedrijf",
                          "service_area": "Utrecht en omgeving"})
        self.assertEqual(self.assign.call_args.args[1], ["Dakreparatie", "Dakisolatie"])
        self.assertEqual(set(self.checks.call_args.kwargs["keywords"]), set(REPAIR + INSULATION + LOCAL))
        self.assertEqual(self.summarize.call_args.kwargs, {"customer_name": "Klant BV"})

        snapshot = self.snapshot()
        self.assertEqual([c.domain for c in snapshot.competitors if c.in_top5], top5)
        werkspot = next(c for c in snapshot.competitors if c.domain == "werkspot.nl")
        self.assertEqual((werkspot.ai_is_aggregator, werkspot.in_top5), (True, False))
        self.assertEqual(snapshot.heatmap.state, "ok")
        self.assertEqual([r.topic for r in snapshot.heatmap.rows], ["Dakreparatie", "Dakisolatie", "Lokaal"])
        self.assertEqual([c.domain for c in snapshot.heatmap.columns], ["klant.nl", *top5])
        self.assertEqual((snapshot.summary.state, snapshot.summary.points), ("ok", ["Een.", "Twee.", "Drie."]))
        self.assertEqual({k: v.state for k, v in snapshot.sources}, {"ahrefs": "ok", "prt": "ok", "claude": "ok",
                                                                    "profile": "ok"})
        self.assertEqual(snapshot.kpis.organic_traffic.change_pct, 8.0)
        self.assertEqual(snapshot.warnings, [])

    def test_only_pending_is_claimed(self):
        self.add_row("completed")
        self.run_task()
        self.candidates.assert_not_called()
        self.assertEqual(self.get().status, "completed")

    def test_budget_and_prt_warnings(self):
        self.add_row()

        def candidates(**kwargs):
            raw = fake_candidates(**kwargs)
            raw.prt = RawPrt(state="not_tracked", message="Niet in PRT.")
            return raw

        def metrics(raw, **kwargs):
            kwargs["budget"].skipped += ["top 10-zoekwoorden van dakpro.nl", "cijfers per domein (HTTP 500)"]
            return fake_metrics(raw, **kwargs)

        self.candidates.side_effect = candidates
        self.metrics.side_effect = metrics
        self.run_task()
        snapshot = self.snapshot()
        self.assertEqual(snapshot.warnings, [
            "Unit-plafond bereikt: top 10-zoekwoorden van dakpro.nl overgeslagen.",
            "Ahrefs gaf een fout: cijfers per domein overgeslagen (HTTP 500).",
            worker.PRT_NOT_TRACKED_WARNING,
        ])
        self.assertEqual((snapshot.sources.prt.state, snapshot.sources.prt.message), ("not_tracked", "Niet in PRT."))


class FailureTest(_Base):
    def add_completed_row(self):
        self.add_row()
        self.run_task()
        old = self.get()
        self.set_pending()
        return old

    def test_ahrefs_error_keeps_old_data(self):
        old = self.add_completed_row()
        self.candidates.side_effect = AhrefsServiceError("Ahrefs-limiet bereikt.", "rate_limited")
        row = self.run_task()
        self.assertEqual(row.status, "failed")
        self.assertIn("Ahrefs-limiet bereikt.", row.error_message)
        self.assertEqual((row.data, row.raw, row.ahrefs_units), (old.data, old.raw, old.ahrefs_units))
        self.assertEqual(row.completed_at, old.completed_at)

    def test_timeout_and_unexpected_error(self):
        old = self.add_completed_row()
        self.metrics.side_effect = SoftTimeLimitExceeded()
        row = self.run_task()
        self.assertEqual((row.status, row.error_message, row.data), ("failed", worker.TIMEOUT_MESSAGE, old.data))

        self.set_pending()
        self.metrics.side_effect = KeyError("x")
        row = self.run_task()
        self.assertEqual(row.status, "failed")
        self.assertIn("KeyError", row.error_message)
        self.assertEqual(row.raw, old.raw)


class ClaudeTest(_Base):
    def test_classify_error_only_hits_the_judgements(self):
        self.add_row()
        self.classify.side_effect = AnthropicServiceError("Timeout bij wachten op Claude.", "timeout")
        row = self.run_task()
        self.assertEqual(row.status, "completed")
        snapshot = self.snapshot()
        self.assertTrue(all(c.ai_type is None for c in snapshot.competitors))
        self.assertIn("werkspot.nl", [c.domain for c in snapshot.competitors if c.in_top5])
        self.assertEqual(snapshot.sources.claude.state, "error")
        self.assertIn(worker.CLASSIFY_FAILED_WARNING, snapshot.warnings)
        self.assertEqual((snapshot.heatmap.state, snapshot.summary.state), ("ok", "ok"))
        self.assertEqual(row.ai_usage["calls"], 2)

    def test_assign_error_only_hits_the_heatmap(self):
        self.add_row()
        self.assign.side_effect = AnthropicServiceError("Claude weigerde dit verzoek.", "refusal")
        self.assertEqual(self.run_task().status, "completed")
        snapshot = self.snapshot()
        self.assertEqual(snapshot.heatmap.state, "error")
        self.assertIn("Claude weigerde dit verzoek.", snapshot.heatmap.message)
        self.checks.assert_not_called()
        self.assertEqual((snapshot.summary.state, snapshot.sources.claude.state), ("ok", "ok"))
        self.assertIsNotNone(snapshot.competitors[0].ai_type)

    def test_summary_error_only_hits_the_summary(self):
        self.add_row()
        self.summarize.side_effect = AnthropicServiceError("Claude gaf 2 aanbevelingen terug in plaats van 3.",
                                                           "invalid_output")
        self.assertEqual(self.run_task().status, "completed")
        snapshot = self.snapshot()
        self.assertEqual(snapshot.summary.state, "error")
        self.assertIn("2 aanbevelingen", snapshot.summary.message)
        self.assertEqual(snapshot.heatmap.state, "ok")

    def test_not_configured(self):
        self.claude_ready.return_value = False
        self.add_row()
        self.assertEqual(self.run_task().status, "completed")
        for mock in (self.classify, self.assign, self.summarize, self.checks):
            mock.assert_not_called()
        self.assertEqual(self.metrics.call_args.kwargs["keyword_domains"], [])
        snapshot = self.snapshot()
        self.assertEqual((snapshot.sources.claude.state, snapshot.heatmap.state, snapshot.summary.state),
                         ("not_configured", "not_configured", "not_configured"))
        self.assertIsNone(self.get().model)

    def test_reuse_keeps_previous_judgements(self):
        self.add_row()
        self.run_task()
        self.assertEqual(self.classify.call_count, 1)

        # Bijwerken met een nieuw domein: alleen dat gaat naar Claude.
        self.set_pending()
        previous = Raw.model_validate(self.get().raw)

        def candidates(**kwargs):
            raw = fake_candidates(**kwargs)
            raw.competitors.append(RawCompetitor(domain="nieuw.nl", domain_rating=12, keywords_common=50, share=7.0))
            return raw

        self.candidates.side_effect = candidates
        self.run_task("reuse")
        self.assertEqual(self.candidates.call_args.kwargs["previous"], previous)
        self.assertEqual([i.domain for i in self.classify.call_args.args[0]], ["nieuw.nl"])
        snapshot = self.snapshot()
        types = {c.domain: c.ai_type for c in snapshot.competitors}
        self.assertEqual((types["dakwerk.nl"], types["nieuw.nl"]), ("regio", "regio"))
        werkspot = next(c for c in snapshot.competitors if c.domain == "werkspot.nl")
        self.assertTrue(werkspot.ai_is_aggregator)

        # Geen nieuwe domeinen: alleen wat niet in de momentopname stond (dakpro.nl viel door
        # nieuw.nl buiten de vijf en heeft dus geen bewaard oordeel) gaat opnieuw naar Claude.
        self.set_pending()
        self.classify.reset_mock()
        self.run_task("reuse")
        self.assertEqual([i.domain for i in self.classify.call_args.args[0]], ["dakpro.nl"])

        # Alles heeft een oordeel in de momentopname: geen aanroep.
        self.set_pending()
        snapshot = self.snapshot()
        judged = {c.domain for c in snapshot.competitors if c.ai_type is not None}

        def only_judged(**kwargs):
            raw = candidates(**kwargs)
            raw.competitors = [c for c in raw.competitors if c.domain in judged]
            return raw

        self.candidates.side_effect = only_judged
        self.classify.reset_mock()
        self.run_task("reuse")
        self.classify.assert_not_called()
        self.assertTrue(next(c for c in self.snapshot().competitors if c.domain == "werkspot.nl").ai_is_aggregator)


class EmptyProfileTest(_Base):
    profile = {"company_type": "Dakdekker"}

    def test_empty_profile_skips_keywords_and_assignment(self):
        self.add_row()
        self.assertEqual(self.run_task().status, "completed")
        self.assertEqual(self.metrics.call_args.kwargs["keyword_domains"], [])
        self.assign.assert_not_called()
        self.checks.assert_not_called()
        snapshot = self.snapshot()
        self.assertEqual(snapshot.heatmap.state, "no_profile")
        self.assertEqual(snapshot.sources.profile.state, "empty")
        self.assertEqual(snapshot.summary.state, "ok")
        self.assertEqual(self.get().ahrefs_units, CLAIMED_UNITS + METRICS_UNITS)


if __name__ == "__main__":
    unittest.main()
