"""Kern van de werkvoorraad (features/work_queue/services: sync en cards).

Draait tegen een in-memory SQLite-database met nepgroepen; geen bronnen en geen netwerk. De
sessies hebben `autoflush=False`, net als de app.
"""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, CustomerWebsite, User, WorkItem
from app.features.launch_checklist.services.scan_recovery import as_utc
from app.features.work_queue.services import cards, sync
from app.features.work_queue.services.cards import (
    fingerprint_of,
    position_between,
    position_for_new,
    position_top,
    rebalance,
    week_start_utc,
)
from app.features.work_queue.services.sync import apply_groups, mark_active, mark_done, mark_removed
from app.features.work_queue.services.types import Group, Item

USER = "user-1"
NOW = datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc)


def _item(key, *, suppress_key=None, severity="middel"):
    return Item(key=key, title=f"Punt {key}", url=f"https://klant.nl/{key}", severity=severity,
                ref={"id": key}, suppress_key=suppress_key)


def _group(customer_id, key, item_keys=("a", "b"), *, source="scan", severity="middel", kind="techniek",
           title=None, items=None):
    return Group(customer_id=customer_id, source=source, group_key=key, title=title or f"Groep {key}",
                 kind=kind, severity=severity, items=items if items is not None else [_item(k) for k in item_keys])


class _Base(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, autoflush=False)
        with self.Session() as db:
            db.add(User(id=USER, email="jan@iexist.nl", password_hash="x", created_at=NOW, updated_at=NOW))
            db.commit()
        self.customer = self.add_customer("Klant A")
        self.other = self.add_customer("Klant B")

    def add_customer(self, name):
        customer_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(id=customer_id, name=name, base_url="https://klant.nl/", domain="klant.nl",
                                   created_by=USER, created_at=NOW, updated_at=NOW))
            db.commit()
        return customer_id

    def add_card(self, *, status="todo", position=1000.0, severity="middel", source="scan", group_key=None,
                 customer_id=None, items=None, done_at=None, resolved_by_source=False):
        card_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(WorkItem(
                id=card_id, customer_website_id=customer_id or self.customer, source=source,
                group_key=group_key, active_key=group_key if status in ("todo", "doing", "review") else None,
                status=status, kind="techniek", title="Kaart", severity=severity,
                item_count=len(items or []), items=items, position=position, resolved_by_source=resolved_by_source,
                done_at=done_at, created_at=NOW, updated_at=NOW,
            ))
            db.commit()
        return card_id

    def sync(self, groups, *, sources=("scan",), customer_ids=None, now=NOW):
        with self.Session() as db:
            result = apply_groups(db, groups, sources=set(sources), customer_ids=customer_ids, now=now)
            db.commit()
        return result

    def cards(self, **filters):
        with self.Session() as db:
            query = db.query(WorkItem)
            for name, value in filters.items():
                query = query.filter(getattr(WorkItem, name) == value)
            rows = query.order_by(WorkItem.position).all()
            for row in rows:
                _ = row.items  # deferred: laden zolang de sessie open is
            db.expunge_all()
            return rows


class SyncTests(_Base):
    def test_creates_card_for_new_group(self):
        result = self.sync([_group(self.customer, "missing_alt", ("a", "b", "c"), severity="hoog")])

        self.assertEqual((result.created, result.updated, result.resolved), (1, 0, 0))
        [card] = self.cards()
        self.assertEqual(card.status, "todo")
        self.assertEqual(card.group_key, "missing_alt")
        self.assertEqual(card.active_key, "missing_alt")
        self.assertEqual(card.item_count, 3)
        self.assertEqual(card.severity, "hoog")
        self.assertEqual(card.title, "Groep missing_alt")
        self.assertIsNone(card.assignee_id)
        self.assertIsNone(card.created_by)
        self.assertFalse(card.resolved_by_source)
        self.assertEqual(card.position, 1000.0)
        self.assertEqual([item["key"] for item in card.items], ["a", "b", "c"])
        self.assertEqual(card.items[0], {"key": "a", "title": "Punt a", "url": "https://klant.nl/a",
                                         "severity": "middel", "ref": {"id": "a"}, "suppress_key": None})
        self.assertEqual(card.fingerprint, fingerprint_of(card.items, "hoog"))

    def test_update_keeps_position_status_and_assignment(self):
        self.sync([_group(self.customer, "g", ("a", "b", "c"))])
        [card] = self.cards()
        with self.Session() as db:
            row = db.get(WorkItem, card.id)
            row.status, row.position, row.assignee_id, row.note = "doing", 42.0, USER, "Bezig"
            db.commit()

        later = NOW + timedelta(hours=1)
        result = self.sync([_group(self.customer, "g", ("a",), severity="hoog", title="Nieuwe titel")], now=later)

        self.assertEqual((result.created, result.updated, result.resolved), (0, 1, 0))
        [card] = self.cards()
        self.assertEqual((card.status, card.position, card.assignee_id, card.note), ("doing", 42.0, USER, "Bezig"))
        self.assertEqual(card.item_count, 1)
        self.assertEqual(card.severity, "hoog")
        self.assertEqual(card.title, "Nieuwe titel")
        self.assertEqual([item["key"] for item in card.items], ["a"])
        self.assertEqual(as_utc(card.updated_at), later)

    def test_same_fingerprint_writes_nothing(self):
        self.sync([_group(self.customer, "g", ("a", "b"))])
        later = NOW + timedelta(hours=1)
        # Andere volgorde en titel, zelfde sleutels en ernst: geen schrijfactie.
        with self.Session() as db:
            result = apply_groups(db, [_group(self.customer, "g", ("b", "a"), title="Anders")],
                                  sources={"scan"}, now=later)
            self.assertFalse(db.dirty)
            self.assertFalse(db.new)
        self.assertEqual((result.created, result.updated, result.resolved), (0, 0, 0))
        [card] = self.cards()
        self.assertEqual(as_utc(card.updated_at), NOW)
        self.assertEqual(card.title, "Groep g")

    def test_card_without_group_is_resolved_by_source(self):
        self.add_card(status="done", position=1000.0)
        self.sync([_group(self.customer, "g")])
        later = NOW + timedelta(days=1)

        result = self.sync([], now=later)

        self.assertEqual(result.resolved, 1)
        [card] = self.cards(group_key="g")
        self.assertEqual(card.status, "done")
        self.assertIsNone(card.active_key)
        self.assertTrue(card.resolved_by_source)
        self.assertIsNone(card.done_by)
        self.assertEqual(as_utc(card.done_at), later)
        self.assertLess(card.position, 1000.0)  # bovenaan de Klaar-kolom

    def test_new_card_for_same_group_after_done(self):
        self.sync([_group(self.customer, "g")])
        self.sync([])
        result = self.sync([_group(self.customer, "g", ("c",))], now=NOW + timedelta(days=2))

        self.assertEqual(result.created, 1)
        rows = self.cards(group_key="g")
        self.assertEqual(sorted(row.status for row in rows), ["done", "todo"])
        open_card = next(row for row in rows if row.status == "todo")
        self.assertEqual(open_card.active_key, "g")
        self.assertEqual(open_card.item_count, 1)

    def test_only_assessed_customers_and_sources_are_resolved(self):
        self.sync([_group(self.customer, "g"), _group(self.other, "g")])
        self.sync([_group(self.customer, "ctr", source="search_console", kind="ctr")], sources=("search_console",))

        result = self.sync([], sources=("scan",), customer_ids={self.customer})

        self.assertEqual(result.resolved, 1)
        mine = {row.source: row.status for row in self.cards(customer_website_id=self.customer)}
        self.assertEqual(mine, {"scan": "done", "search_console": "todo"})
        [theirs] = self.cards(customer_website_id=self.other)
        self.assertEqual(theirs.status, "todo")

    def test_groups_outside_scope_are_ignored(self):
        result = self.sync(
            [_group(self.other, "g"), _group(self.customer, "x", source="analysis")],
            sources=("scan",), customer_ids={self.customer},
        )
        self.assertEqual(result.created, 0)
        self.assertEqual(self.cards(), [])

    def test_removed_card_suppresses_its_items(self):
        self.sync([_group(self.customer, "g", ("a", "b"))])
        [card] = self.cards()
        with self.Session() as db:
            mark_removed(db.get(WorkItem, card.id), NOW)
            db.commit()

        # Alleen de oude items: geen nieuwe kaart.
        result = self.sync([_group(self.customer, "g", ("a", "b"))])
        self.assertEqual(result.created, 0)
        # Een nieuw item komt wel terug, zonder de verwijderde.
        result = self.sync([_group(self.customer, "g", ("a", "b", "c"))])
        self.assertEqual(result.created, 1)
        [new] = self.cards(status="todo")
        self.assertEqual([item["key"] for item in new.items], ["c"])
        self.assertEqual(new.item_count, 1)
        # Andere groep met dezelfde itemsleutel wordt niet onderdrukt.
        result = self.sync([_group(self.customer, "g", ("a", "b", "c")), _group(self.customer, "h", ("a",))])
        self.assertEqual(result.created, 1)

    def test_removed_analysis_card_suppresses_whole_group(self):
        groups = [_group(self.customer, "seo bureau", ("x",), source="analysis", kind="content")]
        self.sync(groups, sources=("analysis",))
        [card] = self.cards()
        with self.Session() as db:
            mark_removed(db.get(WorkItem, card.id), NOW)
            db.commit()

        result = self.sync([_group(self.customer, "seo bureau", ("y", "z"), source="analysis", kind="content")],
                           sources=("analysis",))
        self.assertEqual(result.created, 0)
        self.assertEqual(self.cards(status="todo"), [])

    def _sc_group(self, *keys):
        items = [_item(f"{page}|{query}", suppress_key=page) for page, query in keys]
        return _group(self.customer, "ctr", source="search_console", kind="ctr", items=items)

    def test_search_console_rest_after_manual_done(self):
        stored = [_item("/a|oud", suppress_key="/a").as_dict()]
        self.add_card(status="done", source="search_console", group_key="ctr", items=stored,
                      done_at=NOW - timedelta(days=55))
        group = self._sc_group(("/a", "nieuw"), ("/b", "q"))

        # Dag 55: pagina /a rust, /b niet.
        self.sync([group], sources=("search_console",))
        [card] = self.cards(status="todo")
        self.assertEqual([item["key"] for item in card.items], ["/b|q"])

        # Alleen /a open op dag 55: geen kaart (de open kaart gaat vanzelf naar Klaar).
        self.sync([self._sc_group(("/a", "nieuw"))], sources=("search_console",))
        self.assertEqual(self.cards(status="todo"), [])

        # Dag 57: /a telt weer mee.
        result = self.sync([self._sc_group(("/a", "nieuw"))], sources=("search_console",),
                           now=NOW + timedelta(days=2))
        self.assertEqual(result.created, 1)
        [card] = self.cards(status="todo")
        self.assertEqual([item["key"] for item in card.items], ["/a|nieuw"])

    def test_resolved_by_source_gives_no_rest(self):
        stored = [_item("/a|oud", suppress_key="/a").as_dict()]
        self.add_card(status="done", source="search_console", group_key="ctr", items=stored,
                      done_at=NOW - timedelta(days=10), resolved_by_source=True)
        result = self.sync([self._sc_group(("/a", "oud"))], sources=("search_console",))
        self.assertEqual(result.created, 1)

    def test_new_cards_are_placed_by_severity(self):
        self.sync([
            _group(self.customer, "a", severity="laag"),
            _group(self.customer, "b", severity="hoog"),
            _group(self.customer, "c", severity="middel"),
            _group(self.customer, "d", severity="hoog"),
        ])
        self.assertEqual([row.group_key for row in self.cards(status="todo")], ["b", "d", "c", "a"])

    def test_concurrent_create_keeps_one_card(self):
        # Een collega maakte de kaart net aan; deze sync zag hem niet bij het opzoeken.
        existing = self.add_card(status="todo", group_key="g", position=500.0)
        with patch.object(sync, "_load_active", return_value={}):
            with self.assertLogs(sync.logger, level="INFO"):
                result = self.sync([_group(self.customer, "a"), _group(self.customer, "g"),
                                    _group(self.customer, "h")])

        self.assertEqual(result.created, 2)
        rows = self.cards(group_key="g")
        self.assertEqual([row.id for row in rows], [existing])
        # De savepoint draait alleen de mislukte kaart terug: "a" (ervoor) en "h" (erna) blijven.
        self.assertEqual(len(self.cards(group_key="a")), 1)
        self.assertEqual(len(self.cards(group_key="h")), 1)


class TransitionTests(_Base):
    def test_mark_done_active_and_removed(self):
        card_id = self.add_card(status="doing", group_key="g")
        with self.Session() as db:
            card = db.get(WorkItem, card_id)
            mark_done(card, USER, NOW)
            self.assertEqual((card.status, card.active_key, card.done_by), ("done", None, USER))
            self.assertFalse(card.resolved_by_source)
            mark_active(card, "review", now=NOW)
            self.assertEqual((card.status, card.active_key, card.done_at, card.done_by), ("review", "g", None, None))
            with self.assertRaises(ValueError):
                mark_active(card, "done")
            mark_removed(card, NOW)
            self.assertEqual((card.status, card.active_key), ("removed", None))
            db.commit()


class PositionTests(_Base):
    def setUp(self):
        super().setUp()
        self.first = self.add_card(position=1000.0)
        self.second = self.add_card(position=2000.0)
        self.third = self.add_card(position=3000.0)
        self.done = self.add_card(status="done", position=1000.0)

    def test_between_neighbours(self):
        with self.Session() as db:
            self.assertEqual(position_between(db, "todo", self.first, self.second), 1500.0)
            self.assertEqual(position_between(db, "todo", self.first, None), 1500.0)
            self.assertEqual(position_between(db, "todo", self.third, None), 4000.0)
            self.assertEqual(position_between(db, "todo", None, self.first), 0.0)
            self.assertEqual(position_between(db, "todo", None, self.second), 1500.0)
            self.assertEqual(position_between(db, "todo", None, None), 4000.0)
            self.assertEqual(position_between(db, "doing", None, None), 1000.0)
            # De verplaatste kaart telt niet als buur.
            self.assertEqual(position_between(db, "todo", self.first, None, exclude_id=self.second), 2000.0)

    def test_between_rejects_other_column_or_unknown(self):
        with self.Session() as db:
            with self.assertRaises(ValueError):
                position_between(db, "todo", self.done, None)
            with self.assertRaises(ValueError):
                position_between(db, "todo", None, "onbekend")
            with self.assertRaises(ValueError):
                position_between(db, "todo", self.first, self.second, exclude_id=self.second)

    def test_top_and_new(self):
        with self.Session() as db:
            self.assertEqual(position_top(db, "todo"), 0.0)
            self.assertEqual(position_top(db, "review"), 1000.0)
            self.assertEqual(position_for_new(db, "review", "hoog"), 1000.0)

    def test_new_by_severity_against_existing_column(self):
        with self.Session() as db:
            db.get(WorkItem, self.first).severity = "hoog"
            db.get(WorkItem, self.third).severity = "laag"
            db.flush()
            self.assertEqual(position_for_new(db, "todo", "hoog"), 1500.0)
            self.assertEqual(position_for_new(db, "todo", "middel"), 2500.0)
            self.assertEqual(position_for_new(db, "todo", "laag"), 4000.0)
            db.get(WorkItem, self.first).severity = "laag"
            db.flush()
            # Geen kaart met gelijke of hogere ernst: bovenaan.
            db.get(WorkItem, self.second).severity = "laag"
            self.assertEqual(position_for_new(db, "todo", "hoog"), 0.0)

    def test_rebalance_when_gap_too_small(self):
        with self.Session() as db:
            self.assertFalse(rebalance(db, "todo"))
            db.get(WorkItem, self.second).position = 1000.0 + 1e-7
            db.commit()
        with self.Session() as db:
            position = position_between(db, "todo", self.first, self.second)
            db.commit()
        self.assertEqual(position, 1500.0)
        positions = {row.id: row.position for row in self.cards(status="todo")}
        self.assertEqual(positions, {self.first: 1000.0, self.second: 2000.0, self.third: 3000.0})
        self.assertEqual([row.position for row in self.cards(status="done")], [1000.0])


class WeekStartTests(unittest.TestCase):
    def test_week_start_in_amsterdam(self):
        if cards._TZ is timezone.utc:
            self.skipTest("Geen tz-database in deze omgeving")
        utc = timezone.utc
        cases = [
            # Woensdag in de winter → maandag 00:00 CET.
            (datetime(2026, 11, 25, 12, 0, tzinfo=utc), datetime(2026, 11, 22, 23, 0, tzinfo=utc)),
            # Zondag 23:30 UTC is al maandag 00:30 in Amsterdam.
            (datetime(2026, 11, 22, 23, 30, tzinfo=utc), datetime(2026, 11, 22, 23, 0, tzinfo=utc)),
            # Zondag 22:59 UTC is nog zondag 23:59 in Amsterdam.
            (datetime(2026, 11, 22, 22, 59, tzinfo=utc), datetime(2026, 11, 15, 23, 0, tzinfo=utc)),
            # Zomer: maandag 00:00 CEST = 22:00 UTC.
            (datetime(2026, 7, 1, 12, 0, tzinfo=utc), datetime(2026, 6, 28, 22, 0, tzinfo=utc)),
            # Zondag van de overgang naar zomertijd: de week begon nog in wintertijd.
            (datetime(2026, 3, 29, 12, 0, tzinfo=utc), datetime(2026, 3, 22, 23, 0, tzinfo=utc)),
            # De week erna begint in zomertijd.
            (datetime(2026, 4, 1, 12, 0, tzinfo=utc), datetime(2026, 3, 29, 22, 0, tzinfo=utc)),
            # Naïef geldt als UTC.
            (datetime(2026, 11, 25, 12, 0), datetime(2026, 11, 22, 23, 0, tzinfo=utc)),
        ]
        for now, expected in cases:
            with self.subTest(now=now):
                result = week_start_utc(now)
                self.assertEqual(result, expected)
                self.assertEqual(result.utcoffset(), timedelta(0))


class FingerprintTests(unittest.TestCase):
    def test_order_independent_and_sensitive_to_severity(self):
        items = [_item("a"), _item("b")]
        self.assertEqual(fingerprint_of(items, "hoog"), fingerprint_of(list(reversed(items)), "hoog"))
        self.assertEqual(fingerprint_of(items, "hoog"), fingerprint_of([i.as_dict() for i in items], "hoog"))
        self.assertNotEqual(fingerprint_of(items, "hoog"), fingerprint_of(items, "laag"))
        self.assertNotEqual(fingerprint_of(items, "hoog"), fingerprint_of(items[:1], "hoog"))
        self.assertEqual(len(fingerprint_of(items, None)), 40)


if __name__ == "__main__":
    unittest.main()
