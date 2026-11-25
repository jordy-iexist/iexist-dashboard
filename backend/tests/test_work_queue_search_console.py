"""Werkvoorraad, bron Search Console (services/sources_search_console.py en
worker/search_console.py).

Draait tegen een in-memory SQLite-database; `customer_insights` en `.delay` zijn vervangen,
dus geen aanroepen naar Google en geen taken op de echte worker. De sessies hebben
`autoflush=False`, net als de app.
"""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, CustomerWebsite, User, WorkItem
from app.features.work_queue.services import sources_search_console as source
from app.features.work_queue.services.sources_search_console import (
    group_from,
    search_console_adapter,
    sync_customer,
)
from app.features.work_queue.services.sync import mark_done, mark_removed
from app.features.work_queue.services.types import Adapter
from app.features.work_queue.worker import search_console as worker

USER = "user-1"
NOW = datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)
PAGE_A = "https://www.Klant.nl/diensten/"
PAGE_B = "https://www.klant.nl/over-ons"


def _row(page, query, advice_code="improve_snippet", *, missed=12, position=4.2, impressions=900, clicks=8):
    return {
        "query": query, "page": page, "missed_clicks": missed, "position": position,
        "impressions": impressions, "clicks": clicks, "ctr": 0.01, "expected_ctr": 0.05,
        "other_pages": 0, "advice_code": advice_code, "advice": "Advies",
    }


def _insights(rows=(), *, state="ok", section_state="ok"):
    if state != "ok":
        return {"state": state, "message": "Niet beschikbaar", "opportunities": None}
    section = {"state": section_state, "message": None if section_state == "ok" else "CTR-kansen niet opgehaald",
               "rows": list(rows) if section_state == "ok" else [], "total": len(rows)}
    return {"state": "ok", "message": None, "opportunities": section}


class GroupFromTests(unittest.TestCase):
    def test_filters_on_advice_code_and_builds_keys(self):
        group = group_from("klant-1", [
            _row(PAGE_A, "  Beste  SEO Bureau "),
            _row(PAGE_B, "over ons", "improve_snippet_top", position=2.1),
            _row(PAGE_A, "seo", "improve_position", position=14.0),
            _row(PAGE_B, "contact", "check_intent", clicks=0),
            _row("", "zonder pagina"),
            _row(PAGE_B, "   "),
        ])

        self.assertIsNotNone(group)
        self.assertEqual((group.customer_id, group.source, group.group_key), ("klant-1", "search_console", "ctr"))
        self.assertEqual((group.title, group.kind, group.severity), ("Title & meta herschrijven", "ctr", "middel"))
        self.assertEqual([item.key for item in group.items],
                         ["www.klant.nl/diensten|beste seo bureau", "www.klant.nl/over-ons|over ons"])
        first = group.items[0]
        self.assertEqual(first.title, "Beste  SEO Bureau")
        self.assertEqual(first.url, "https://www.Klant.nl/diensten/")
        self.assertIsNone(first.severity)
        self.assertEqual(first.suppress_key, "www.klant.nl/diensten")
        self.assertEqual(first.ref, {"query": "  Beste  SEO Bureau ", "missed_clicks": 12, "position": 4.2,
                                     "impressions": 900, "clicks": 8, "advice_code": "improve_snippet"})
        self.assertEqual(group.items[1].ref["advice_code"], "improve_snippet_top")

    def test_nothing_left_gives_none(self):
        self.assertIsNone(group_from("klant-1", []))
        self.assertIsNone(group_from("klant-1", [_row(PAGE_A, "seo", "improve_position"),
                                                 _row(PAGE_B, "contact", "check_intent")]))

    def test_adapter_does_nothing(self):
        self.assertIsInstance(search_console_adapter, Adapter)
        self.assertEqual(search_console_adapter.source, "search_console")
        self.assertEqual(search_console_adapter.collect(None, None), [])
        for method in (search_console_adapter.complete, search_console_adapter.reopen,
                       search_console_adapter.dismiss):
            self.assertIsNone(method(None, None, USER, NOW))


class _Base(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, autoflush=False)
        with self.Session() as db:
            db.add(User(id=USER, email="jan@iexist.nl", password_hash="x", created_at=NOW, updated_at=NOW))
            db.commit()
        self.customer = self.add_customer("Klant A")

    def add_customer(self, name):
        customer_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(id=customer_id, name=name, base_url="https://www.klant.nl/", domain="klant.nl",
                                   created_by=USER, created_at=NOW, updated_at=NOW))
            db.commit()
        return customer_id

    def sync(self, insights, *, now=NOW):
        with patch.object(source, "customer_insights", return_value=insights) as fetch:
            with self.Session() as db:
                customer = db.get(CustomerWebsite, self.customer)
                result = sync_customer(db, customer, now=now)
                db.commit()
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[1], 28)
        return result

    def cards(self, **filters):
        with self.Session() as db:
            query = db.query(WorkItem)
            for name, value in filters.items():
                query = query.filter(getattr(WorkItem, name) == value)
            rows = query.order_by(WorkItem.created_at, WorkItem.position).all()
            for row in rows:
                _ = row.items  # deferred: laden zolang de sessie open is
            db.expunge_all()
            return rows

    def finish(self, card_id, *, now=NOW):
        with self.Session() as db:
            mark_done(db.get(WorkItem, card_id), USER, now)
            db.commit()


class SyncCustomerTests(_Base):
    def test_creates_and_updates_card(self):
        result = self.sync(_insights([_row(PAGE_A, "seo bureau"), _row(PAGE_A, "seo", "improve_position")]))

        self.assertEqual(result, {"state": "ok", "changed": True, "created": 1, "updated": 0, "resolved": 0,
                                  "items": 1})
        [card] = self.cards()
        self.assertEqual((card.source, card.group_key, card.status, card.kind, card.severity),
                         ("search_console", "ctr", "todo", "ctr", "middel"))
        self.assertEqual(card.title, "Title & meta herschrijven")
        self.assertEqual(card.item_count, 1)
        self.assertEqual(card.items[0]["suppress_key"], "www.klant.nl/diensten")

        # Zelfde kansen: niets veranderd.
        result = self.sync(_insights([_row(PAGE_A, "seo bureau")]), now=NOW + timedelta(days=7))
        self.assertEqual((result["changed"], result["created"], result["updated"]), (False, 0, 0))

        # Een week later een kans erbij: dezelfde kaart wordt bijgewerkt.
        result = self.sync(_insights([_row(PAGE_A, "seo bureau"), _row(PAGE_B, "over ons")]),
                           now=NOW + timedelta(days=14))
        self.assertEqual((result["changed"], result["created"], result["updated"]), (True, 0, 1))
        [updated] = self.cards()
        self.assertEqual(updated.id, card.id)
        self.assertEqual(updated.item_count, 2)

    def test_rest_of_eight_weeks_after_manual_done(self):
        self.sync(_insights([_row(PAGE_A, "seo bureau")]))
        [card] = self.cards()
        self.finish(card.id)

        # Dag 55: pagina A rust, ook met een andere zoekterm.
        result = self.sync(_insights([_row(PAGE_A, "seo bureau"), _row(PAGE_A, "diensten seo")]),
                           now=NOW + timedelta(days=55))
        self.assertEqual((result["state"], result["changed"], result["created"]), ("ok", False, 0))
        self.assertEqual(self.cards(status="todo"), [])

        # Dag 57: pagina A komt terug.
        result = self.sync(_insights([_row(PAGE_A, "seo bureau")]), now=NOW + timedelta(days=57))
        self.assertEqual(result["created"], 1)
        [new] = self.cards(status="todo")
        self.assertEqual([item["key"] for item in new.items], ["www.klant.nl/diensten|seo bureau"])

    def test_other_page_comes_back_directly(self):
        self.sync(_insights([_row(PAGE_A, "seo bureau")]))
        [card] = self.cards()
        self.finish(card.id)

        result = self.sync(_insights([_row(PAGE_A, "seo bureau"), _row(PAGE_B, "over ons")]),
                           now=NOW + timedelta(days=1))

        self.assertEqual(result["created"], 1)
        [new] = self.cards(status="todo")
        self.assertNotEqual(new.id, card.id)
        self.assertEqual([item["key"] for item in new.items], ["www.klant.nl/over-ons|over ons"])

    def test_removed_card_keeps_pages_away(self):
        self.sync(_insights([_row(PAGE_A, "seo bureau")]))
        [card] = self.cards()
        with self.Session() as db:
            mark_removed(db.get(WorkItem, card.id), NOW)
            db.commit()

        result = self.sync(_insights([_row(PAGE_A, "seo bureau"), _row(PAGE_A, "diensten")]),
                           now=NOW + timedelta(days=400))
        self.assertEqual(result["created"], 0)
        self.assertEqual(self.cards(status="todo"), [])

        result = self.sync(_insights([_row(PAGE_A, "seo bureau"), _row(PAGE_B, "over ons")]),
                           now=NOW + timedelta(days=401))
        self.assertEqual(result["created"], 1)
        [new] = self.cards(status="todo")
        self.assertEqual([item["key"] for item in new.items], ["www.klant.nl/over-ons|over ons"])

    def test_states_other_than_ok_change_nothing(self):
        self.sync(_insights([_row(PAGE_A, "seo bureau")]))
        cases = [
            (_insights(state="not_configured"), "not_configured"),
            (_insights(state="no_property"), "no_property"),
            (_insights(state="token_expired"), "token_expired"),
            (_insights(section_state="unavailable"), "unavailable"),
        ]
        for insights, state in cases:
            with self.subTest(state=state):
                result = self.sync(insights, now=NOW + timedelta(days=7))
                self.assertEqual((result["state"], result["changed"]), (state, False))
                self.assertNotIn("resolved", result)
                [card] = self.cards()
                self.assertEqual((card.status, card.item_count), ("todo", 1))
                self.assertIsNone(card.done_at)

    def test_week_without_opportunities_resolves_without_rest(self):
        self.sync(_insights([_row(PAGE_A, "seo bureau")]))
        [card] = self.cards()

        # Alleen een positie-advies over: geen title- of meta-kansen meer.
        result = self.sync(_insights([_row(PAGE_A, "seo bureau", "improve_position", position=12.0)]),
                           now=NOW + timedelta(days=7))
        self.assertEqual((result["changed"], result["resolved"], result["items"]), (True, 1, 0))
        [done] = self.cards()
        self.assertEqual((done.status, done.resolved_by_source), ("done", True))
        self.assertIsNone(done.done_by)

        # Een week later is de kans terug: direct een nieuwe kaart, geen rust.
        result = self.sync(_insights([_row(PAGE_A, "seo bureau")]), now=NOW + timedelta(days=14))
        self.assertEqual(result["created"], 1)
        [new] = self.cards(status="todo")
        self.assertNotEqual(new.id, card.id)

    def test_given_insights_are_not_fetched_again(self):
        with patch.object(source, "customer_insights") as fetch:
            with self.Session() as db:
                customer = db.get(CustomerWebsite, self.customer)
                result = sync_customer(db, customer, now=NOW, insights=_insights([_row(PAGE_A, "seo")]))
                db.commit()
        fetch.assert_not_called()
        self.assertEqual(result["created"], 1)


class WorkerTests(_Base):
    def setUp(self):
        super().setUp()
        self.second = self.add_customer("Aardbei BV")  # op naam vóór "Klant A"
        patcher = patch.object(worker, "SessionLocal", self.Session)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dispatch_with_switch_off_starts_nothing(self):
        delay = Mock()
        self._patch(worker.run_work_queue_gsc_task, "delay", delay)
        self._patch(worker.settings, "work_queue_gsc_enabled", False)
        self._patch(worker.gsc, "is_configured", Mock(return_value=True))

        self.assertEqual(worker.run_work_queue_gsc_dispatch_task.run(), {"state": "disabled", "queued": []})
        delay.assert_not_called()

    def test_dispatch_without_search_console_starts_nothing(self):
        delay = Mock()
        self._patch(worker.run_work_queue_gsc_task, "delay", delay)
        self._patch(worker.settings, "work_queue_gsc_enabled", True)
        self._patch(worker.gsc, "is_configured", Mock(return_value=False))

        self.assertEqual(worker.run_work_queue_gsc_dispatch_task.run(), {"state": "not_configured", "queued": []})
        delay.assert_not_called()

    def test_dispatch_starts_one_task_per_customer(self):
        delay = Mock()
        self._patch(worker.run_work_queue_gsc_task, "delay", delay)
        self._patch(worker.settings, "work_queue_gsc_enabled", True)
        self._patch(worker.gsc, "is_configured", Mock(return_value=True))

        result = worker.run_work_queue_gsc_dispatch_task.run()

        self.assertEqual(result, {"state": "ok", "queued": [self.second, self.customer]})
        self.assertEqual([call.args for call in delay.call_args_list], [(self.second,), (self.customer,)])

    def test_task_syncs_and_commits(self):
        self._patch(source, "customer_insights", Mock(return_value=_insights([_row(PAGE_A, "seo bureau")])))

        result = worker.run_work_queue_gsc_task.run(self.customer)

        self.assertEqual((result["state"], result["created"]), ("ok", 1))
        [card] = self.cards()
        self.assertEqual(card.customer_website_id, self.customer)

    def test_task_unknown_customer_and_failure(self):
        self.assertEqual(worker.run_work_queue_gsc_task.run("bestaat-niet"),
                         {"state": "unknown_customer", "changed": False})

        self._patch(source, "customer_insights", Mock(side_effect=RuntimeError("stuk")))
        with self.assertLogs(worker.logger, level="ERROR"):
            result = worker.run_work_queue_gsc_task.run(self.customer)
        self.assertEqual(result, {"state": "failed", "changed": False})
        self.assertEqual(self.cards(), [])


class ScheduleTests(unittest.TestCase):
    def test_beat_and_routes(self):
        from app.worker.celery_app import celery_app

        entry = celery_app.conf.beat_schedule["werkvoorraad-search-console-wekelijks"]
        self.assertEqual(entry["task"], "app.worker.tasks.run_work_queue_gsc_dispatch_task")
        self.assertEqual(entry["schedule"].day_of_week, {1})
        self.assertEqual(entry["schedule"].hour, {6})
        self.assertEqual(entry["schedule"].minute, {0})
        routes = celery_app.conf.task_routes
        self.assertEqual(routes["app.worker.tasks.run_work_queue_gsc_dispatch_task"], {"queue": "default"})
        self.assertEqual(routes["app.worker.tasks.run_work_queue_gsc_task"], {"queue": "default"})
        self.assertEqual(worker.run_work_queue_gsc_task.name, "app.worker.tasks.run_work_queue_gsc_task")


if __name__ == "__main__":
    unittest.main()
