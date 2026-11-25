"""Endpoints van Zoekwoorden › Concurrenten (features/keywords/router.py) en de mappers.

In-memory SQLite; de taak (`refresh_keyword_competitors_task.delay`) en `is_configured` van
Ahrefs zijn vervangen: geen netwerk en geen Celery.
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
from app.db.models import Base, CustomerCompetitorOverview as Row, CustomerWebsite
from app.db.session import get_db
from app.features.keywords import mappers
from app.features.keywords import router as router_module
from app.features.keywords.router import router
from app.features.keywords.schemas import (
    MAX_MANUAL_COMPETITORS,
    CompetitorOverview,
    Heatmap,
    Overrides,
    Raw,
    Snapshot,
    SnapshotCompetitor,
    SourceInfo,
    Sources,
    Summary,
)
from app.worker.tasks import refresh_keyword_competitors_task

USER = "user-1"
PROFILE = {"company_type": "Dakdekkersbedrijf", "service_area": "Utrecht",
           "services": [{"name": "Dakreparatie"}, {"name": "Dakisolatie"}]}


def _now():
    return datetime.now(timezone.utc)


def competitor(domain, overlap=10.0, origin="ahrefs", ai_type="regio", aggregator=False, in_top5=True):
    return SnapshotCompetitor(domain=domain, origin=origin, ai_type=ai_type, ai_is_aggregator=aggregator,
                              in_top5=in_top5, shared=int(overlap * 10), overlap_pct=overlap, domain_rating=30)


def snapshot(*competitors, warnings=()):
    ok = SourceInfo(state="ok")
    return Snapshot(
        warnings=list(warnings), sources=Sources(ahrefs=ok, prt=ok, claude=ok, profile=ok),
        competitors=list(competitors), heatmap=Heatmap(state="ok"),
        summary=Summary(state="ok", paragraph="Kansen.", points=["a", "b", "c"]),
    ).model_dump(mode="json")


def overrides(manual=(), domains=None):
    return Overrides.model_validate({
        "manual": [{"domain": d, "added_by": USER, "added_at": _now().isoformat()} for d in manual],
        "domains": domains or {},
    }).model_dump(mode="json")


class _Base(unittest.TestCase):
    base_url = "https://www.klant.nl/"

    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.customer_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(id=self.customer_id, name="Klant", base_url=self.base_url, domain="klant.nl",
                                   profile=PROFILE, created_by=USER, created_at=_now(), updated_at=_now()))
            db.commit()

        self.ahrefs = self._patch(mappers.ahrefs, "is_configured", Mock(return_value=True))
        self.delay = self._patch(refresh_keyword_competitors_task, "delay", Mock())

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

    def add_row(self, status="completed", *, updated_at=None, completed_at="now", started_at="now", **fields):
        now = _now()
        values = dict(target="klant.nl", country="nl")
        values.update(fields)
        with self.Session() as db:
            db.add(Row(customer_website_id=self.customer_id, status=status, created_by=USER, created_at=now,
                       updated_at=updated_at or now,
                       completed_at=now if completed_at == "now" else completed_at,
                       started_at=now - timedelta(minutes=2) if started_at == "now" else started_at,
                       **values))
            db.commit()

    def row(self):
        with self.Session() as db:
            return db.get(Row, self.customer_id)

    def url(self, suffix="", customer_id=None):
        return f"/api/keywords/customers/{customer_id or self.customer_id}/competitors{suffix}"

    def get(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200, response.text)
        return CompetitorOverview.model_validate(response.json())

    def assert_error(self, response, status, key):
        self.assertEqual((response.status_code, response.json()["detail"]),
                         (status, router_module.MESSAGES[key]))


class GetTest(_Base):
    def test_idle_without_row(self):
        body = self.get()
        self.assertEqual((body.status, body.customer_id, body.domain, body.country),
                         ("idle", self.customer_id, "klant.nl", "nl"))
        self.assertEqual((body.competitors.state, body.competitors.rows, body.competitors.message),
                         ("empty", [], None))
        self.assertEqual((body.heatmap.state, body.heatmap.message), ("no_keywords", None))
        self.assertEqual((body.summary.state, body.summary.message), ("skipped", None))
        self.assertEqual((body.kpis, body.sources, body.fetched_at, body.expires_at, body.dirty),
                         (None, None, None, None, False))
        self.assertEqual((body.units, body.unit_cap), (0, 5000))
        self.assertGreater(body.unit_estimate, 0)
        self.assertIsNone(body.blocked_reason)
        self.assertIsNone(self.row())
        self.delay.assert_not_called()

    def test_unknown_customer(self):
        self.assert_error(self.client.get(self.url(customer_id="onbekend")), 404, "customer")
        self.assert_error(self.client.post(self.url("/refresh", customer_id="onbekend"), json={}), 404, "customer")
        self.assert_error(self.client.post(self.url("/manual", customer_id="onbekend"), json={"domain": "a.nl"}),
                          404, "customer")
        self.assert_error(self.client.patch(self.url("/choice", customer_id="onbekend"), json={"domain": "a.nl"}),
                          404, "customer")

    def test_snapshot_fields(self):
        completed = _now() - timedelta(days=2)
        self.add_row(data=snapshot(competitor("a.nl"), warnings=["Let op."]), completed_at=completed,
                     ahrefs_units=2345, model="claude-sonnet-5-5",
                     ai_usage={"calls": 3, "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.01})
        body = self.get()
        self.assertEqual(body.status, "completed")
        self.assertEqual(body.fetched_at, completed)
        self.assertEqual(body.expires_at, completed + timedelta(days=30))
        self.assertEqual((body.units, body.model, body.ai_usage.calls), (2345, "claude-sonnet-5-5", 3))
        self.assertEqual((body.warnings, body.summary.points), (["Let op."], ["a", "b", "c"]))
        self.assertEqual(body.sources.ahrefs.state, "ok")
        self.delay.assert_not_called()

    def test_recovers_stale_run(self):
        self.add_row("collecting", updated_at=_now() - timedelta(minutes=16), data=snapshot(competitor("a.nl")))
        body = self.get()
        self.assertEqual((body.status, body.error_message), ("failed", router_module.MESSAGES["stale"]))
        self.assertEqual([r.domain for r in body.competitors.rows], ["a.nl"])  # oude momentopname blijft
        self.delay.assert_not_called()

    def test_recent_run_is_not_stale(self):
        self.add_row("classifying", updated_at=_now() - timedelta(minutes=5))
        self.assertEqual(self.get().status, "classifying")


class AutoRefreshTest(_Base):
    def test_expired_snapshot_is_refreshed(self):
        self.add_row(data=snapshot(competitor("a.nl")), completed_at=_now() - timedelta(days=31))
        body = self.get()
        self.assertEqual(body.status, "pending")
        self.delay.assert_called_once_with(self.customer_id, "full")
        self.assertEqual([r.domain for r in body.competitors.rows], ["a.nl"])

    def test_other_domain_is_refreshed(self):
        self.add_row(data=snapshot(competitor("a.nl")), target="oud-domein.nl")
        self.assertEqual(self.get().status, "pending")
        self.delay.assert_called_once_with(self.customer_id, "full")

    def test_fresh_snapshot_is_not_refreshed(self):
        self.add_row(data=snapshot(competitor("a.nl")), completed_at=_now() - timedelta(days=29))
        self.assertEqual(self.get().status, "completed")
        self.delay.assert_not_called()

    def test_never_from_idle_or_failed(self):
        old = _now() - timedelta(days=60)
        self.add_row("failed", data=snapshot(competitor("a.nl")), completed_at=old, error_message="Fout.")
        self.assertEqual(self.get().status, "failed")
        with self.Session() as db:
            db.query(Row).update({"status": "idle", "data": None})
            db.commit()
        self.assertEqual(self.get().status, "idle")
        self.delay.assert_not_called()

    def test_not_when_blocked(self):
        self.ahrefs.return_value = False
        self.add_row(data=snapshot(competitor("a.nl")), completed_at=_now() - timedelta(days=31))
        self.assertEqual(self.get().status, "completed")
        self.delay.assert_not_called()

    def test_queue_failure_keeps_old_snapshot(self):
        self.delay.side_effect = RuntimeError("redis weg")
        self.add_row(data=snapshot(competitor("a.nl")), completed_at=_now() - timedelta(days=31))
        body = self.get()
        self.assertEqual((body.status, body.error_message), ("completed", None))
        self.assertEqual([r.domain for r in body.competitors.rows], ["a.nl"])


class RefreshTest(_Base):
    def test_creates_row_and_enqueues(self):
        response = self.client.post(self.url("/refresh"), json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "pending")
        self.delay.assert_called_once_with(self.customer_id, "full")
        row = self.row()
        self.assertEqual((row.status, row.created_by), ("pending", USER))

    def test_blocked(self):
        self.ahrefs.return_value = False
        response = self.client.post(self.url("/refresh"), json={})
        self.assertEqual((response.status_code, response.json()["detail"]),
                         (400, mappers.BLOCKED_MESSAGES["ahrefs_not_configured"]))
        self.assertEqual(self.get().blocked_reason, "ahrefs_not_configured")
        self.assertIsNone(self.row())
        self.delay.assert_not_called()

    def test_conflict_while_running(self):
        self.add_row("collecting")
        self.assert_error(self.client.post(self.url("/refresh"), json={"mode": "full"}), 409, "running")
        self.delay.assert_not_called()

    def test_stale_run_can_be_restarted(self):
        self.add_row("summarizing", updated_at=_now() - timedelta(minutes=20))
        self.assertEqual(self.client.post(self.url("/refresh"), json={}).status_code, 200)
        self.delay.assert_called_once()

    def test_without_queue_gives_503_and_failed(self):
        self.delay.side_effect = RuntimeError("redis weg")
        self.assert_error(self.client.post(self.url("/refresh"), json={}), 503, "not_queued")
        row = self.row()
        self.assertEqual((row.status, row.error_message), ("failed", router_module.MESSAGES["not_queued"]))

    def test_restart_from_failed_and_idle(self):
        self.add_row("failed", error_message="Fout.")
        self.assertEqual(self.client.post(self.url("/refresh"), json={}).json()["status"], "pending")
        self.assertIsNone(self.row().error_message)
        with self.Session() as db:
            db.query(Row).update({"status": "idle"})
            db.commit()
        self.assertEqual(self.client.post(self.url("/refresh"), json={}).json()["status"], "pending")

    def test_reuse_with_fresh_raw(self):
        raw = Raw(fetched_at=_now() - timedelta(days=3)).model_dump(mode="json")
        self.add_row(data=snapshot(competitor("a.nl")), raw=raw)
        self.client.post(self.url("/refresh"), json={"mode": "reuse"})
        self.delay.assert_called_once_with(self.customer_id, "reuse")

    def test_reuse_without_usable_raw_becomes_full(self):
        cases = [
            dict(raw=None),
            dict(raw=Raw(fetched_at=_now() - timedelta(days=31)).model_dump(mode="json")),
            dict(raw=Raw(fetched_at=_now()).model_dump(mode="json"), target="oud-domein.nl"),
            dict(raw=Raw(fetched_at=_now()).model_dump(mode="json"), country="be"),
        ]
        for fields in cases:
            with self.subTest(fields=fields):
                with self.Session() as db:
                    db.query(Row).delete()
                    db.commit()
                self.delay.reset_mock()
                self.add_row(data=snapshot(competitor("a.nl")), **fields)
                self.client.post(self.url("/refresh"), json={"mode": "reuse"})
                self.delay.assert_called_once_with(self.customer_id, "full")


class NoWebsiteTest(_Base):
    base_url = ""

    def test_blocked_without_website(self):
        response = self.client.post(self.url("/refresh"), json={})
        self.assertEqual((response.status_code, response.json()["detail"]),
                         (400, mappers.BLOCKED_MESSAGES["no_website"]))
        body = self.get()
        self.assertEqual((body.blocked_reason, body.domain), ("no_website", None))


class ManualTest(_Base):
    def add(self, domain):
        return self.client.post(self.url("/manual"), json={"domain": domain})

    def test_add_normalizes_and_creates_idle_row(self):
        response = self.add("https://www.Voorbeeld.nl/pad?x=1")
        self.assertEqual(response.status_code, 200, response.text)
        body = CompetitorOverview.model_validate(response.json())
        self.assertEqual(body.status, "idle")
        self.assertEqual([(r.domain, r.origin, r.pending) for r in body.competitors.rows],
                         [("voorbeeld.nl", "manual", True)])
        row = self.row()
        self.assertEqual(row.status, "idle")
        self.assertEqual([m["domain"] for m in row.overrides["manual"]], ["voorbeeld.nl"])
        self.assertEqual(row.overrides["manual"][0]["added_by"], USER)
        self.assertIsNotNone(row.overrides_changed_at)

    def test_invalid_domains(self):
        for domain in ("geen domein", "localhost", "http://", "a..nl", "-a.nl", "x.1"):
            with self.subTest(domain=domain):
                self.assert_error(self.add(domain), 400, "invalid_domain")
        self.assertIsNone(self.row())

    def test_own_domain_and_subdomain(self):
        for domain in ("klant.nl", "https://www.klant.nl/over", "shop.klant.nl"):
            with self.subTest(domain=domain):
                self.assert_error(self.add(domain), 400, "own_domain")

    def test_duplicate(self):
        self.add("voorbeeld.nl")
        self.assert_error(self.add("www.voorbeeld.nl"), 400, "duplicate")
        self.assertEqual(len(self.row().overrides["manual"]), 1)

    def test_maximum(self):
        for index in range(MAX_MANUAL_COMPETITORS):
            self.assertEqual(self.add(f"concurrent{index}.nl").status_code, 200)
        self.assert_error(self.add("nog-een.nl"), 400, "too_many")
        self.assertEqual(len(self.row().overrides["manual"]), MAX_MANUAL_COMPETITORS)

    def test_during_run_leaves_status_and_heartbeat(self):
        heartbeat = _now() - timedelta(minutes=3)
        self.add_row("collecting", updated_at=heartbeat)
        self.assertEqual(self.add("voorbeeld.nl").json()["status"], "collecting")
        row = self.row()
        self.assertEqual(row.status, "collecting")
        self.assertEqual(mappers.as_utc(row.updated_at), heartbeat)

    def test_remove(self):
        self.add_row(data=snapshot(competitor("a.nl")), overrides_changed_at=None,
                     overrides=overrides(["voorbeeld.nl", "ander.nl"],
                                         {"voorbeeld.nl": {"type": "lokaal", "excluded": None}}))
        response = self.client.post(self.url("/manual/remove"), json={"domain": "https://voorbeeld.nl"})
        self.assertEqual(response.status_code, 200, response.text)
        row = self.row()
        self.assertEqual([m["domain"] for m in row.overrides["manual"]], ["ander.nl"])
        self.assertEqual(row.overrides["domains"], {})
        self.assertIsNotNone(row.overrides_changed_at)

    def test_remove_unknown_is_no_error(self):
        self.add_row(overrides=overrides(["ander.nl"]), overrides_changed_at=None)
        self.assertEqual(self.client.post(self.url("/manual/remove"), json={"domain": "onbekend.nl"}).status_code,
                         200)
        self.assertIsNone(self.row().overrides_changed_at)
        self.assertEqual(len(self.row().overrides["manual"]), 1)
        with self.Session() as db:
            db.query(Row).delete()
            db.commit()
        self.assertEqual(self.client.post(self.url("/manual/remove"), json={"domain": "a.nl"}).status_code, 200)
        self.assertIsNone(self.row())


class ChoiceTest(_Base):
    def setUp(self):
        super().setUp()
        self.add_row(data=snapshot(competitor("a.nl"), competitor("gids.nl", aggregator=True, in_top5=False)),
                     overrides_changed_at=None)

    def choose(self, domain, **fields):
        response = self.client.patch(self.url("/choice"), json={"domain": domain, **fields})
        self.assertEqual(response.status_code, 200, response.text)
        return {r["domain"]: r for r in response.json()["competitors"]["rows"]}

    def test_type_change_does_not_mark_changed(self):
        rows = self.choose("a.nl", type="landelijk")
        self.assertEqual((rows["a.nl"]["type"], rows["a.nl"]["type_source"]), ("landelijk", "manual"))
        self.assertIsNone(self.row().overrides_changed_at)
        self.assertFalse(self.get().dirty)

    def test_exclude_marks_changed(self):
        rows = self.choose("a.nl", excluded=True)
        self.assertEqual((rows["a.nl"]["excluded"], rows["a.nl"]["excluded_source"], rows["a.nl"]["exclude_reason"]),
                         (True, "manual", "handmatig uitgesloten"))
        self.assertIsNotNone(self.row().overrides_changed_at)
        self.assertTrue(self.get().dirty)

    def test_excluding_an_aggregator_again_changes_nothing(self):
        self.choose("gids.nl", excluded=True)
        self.assertIsNone(self.row().overrides_changed_at)
        rows = self.choose("gids.nl", excluded=False)
        self.assertEqual((rows["gids.nl"]["excluded"], rows["gids.nl"]["excluded_source"]), (False, "manual"))
        self.assertIsNotNone(self.row().overrides_changed_at)

    def test_both_none_removes_the_choice(self):
        self.choose("a.nl", type="lokaal", excluded=True)
        rows = self.choose("a.nl", type=None, excluded=None)
        self.assertEqual(self.row().overrides["domains"], {})
        self.assertEqual((rows["a.nl"]["type"], rows["a.nl"]["type_source"], rows["a.nl"]["excluded"]),
                         ("regio", "ai", False))

    def test_invalid_domain(self):
        response = self.client.patch(self.url("/choice"), json={"domain": "geen domein"})
        self.assert_error(response, 400, "invalid_domain")


class DirtyTest(_Base):
    def test_dirty_rules(self):
        started = _now() - timedelta(hours=1)
        cases = [
            ("completed", started + timedelta(minutes=5), True, True),
            ("completed", started - timedelta(minutes=5), True, False),
            ("completed", None, True, False),
            ("collecting", started + timedelta(minutes=5), True, False),
            ("failed", started + timedelta(minutes=5), True, True),
            ("idle", started + timedelta(minutes=5), False, False),
        ]
        for status, changed_at, with_data, expected in cases:
            with self.subTest(status=status, changed_at=changed_at):
                with self.Session() as db:
                    db.query(Row).delete()
                    db.commit()
                self.add_row(status, started_at=started, overrides_changed_at=changed_at,
                             data=snapshot(competitor("a.nl")) if with_data else None)
                self.assertEqual(self.get().dirty, expected)


class RowsTest(_Base):
    def test_overrides_applied_to_rows(self):
        data = snapshot(
            competitor("a.nl", overlap=10.0, ai_type="regio"),
            competitor("gids.nl", overlap=30.0, aggregator=True, ai_type="landelijk", in_top5=False),
            competitor("c.nl", overlap=20.0, ai_type="lokaal"),
            competitor("d.nl", overlap=15.0, ai_type=None),
            competitor("m.nl", overlap=5.0, origin="manual"),
            competitor("weg.nl", overlap=40.0, origin="manual"),
        )
        self.add_row(data=data, overrides=overrides(
            ["m.nl", "nieuw.nl"],
            {"a.nl": {"type": "landelijk", "excluded": None}, "c.nl": {"type": None, "excluded": True}},
        ))
        rows = self.get().competitors.rows
        self.assertEqual([r.domain for r in rows], ["d.nl", "a.nl", "m.nl", "nieuw.nl", "gids.nl", "c.nl"])
        by = {r.domain: r for r in rows}
        self.assertEqual((by["a.nl"].type, by["a.nl"].type_source, by["a.nl"].excluded), ("landelijk", "manual", False))
        self.assertEqual((by["d.nl"].type, by["d.nl"].type_source), (None, None))
        self.assertEqual((by["gids.nl"].excluded, by["gids.nl"].excluded_source, by["gids.nl"].exclude_reason,
                          by["gids.nl"].type_source), (True, "ai", "vergelijkingssite", "ai"))
        self.assertEqual((by["c.nl"].excluded, by["c.nl"].excluded_source, by["c.nl"].exclude_reason,
                          by["c.nl"].type, by["c.nl"].type_source),
                         (True, "manual", "handmatig uitgesloten", "lokaal", "ai"))
        self.assertEqual((by["nieuw.nl"].origin, by["nieuw.nl"].pending, by["nieuw.nl"].domain_rating),
                         ("manual", True, None))
        self.assertEqual((by["m.nl"].pending, by["m.nl"].in_top5, by["gids.nl"].in_top5), (False, True, False))
        self.assertNotIn("weg.nl", by)


if __name__ == "__main__":
    unittest.main()
