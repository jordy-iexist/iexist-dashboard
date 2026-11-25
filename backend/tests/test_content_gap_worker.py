"""De taak van Zoekwoorden › Content gap (features/keywords/worker/gap.py).

SQLite in een tijdelijke map; `SessionLocal` is vervangen. De ophaler (`gap_collect`) gebruikt
een nep-Ahrefs-client; de rekenregels (`gap_compute`) zijn echt. Geen netwerk. De taak draait
direct via `.run(...)`.
"""
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, CustomerCompetitorOverview as Scan, CustomerKeywordGap as Row, CustomerWebsite
from app.features.keywords import gap_mappers
from app.features.keywords.gap_schemas import GapSnapshot
from app.features.keywords.schemas import (
    Heatmap,
    Raw,
    RawTop10,
    Snapshot,
    SnapshotCompetitor,
    SourceInfo,
    Sources,
    Summary,
)
from app.features.keywords.services import gap_collect
from app.features.keywords.worker import gap as worker
from app.services.ahrefs.client import AhrefsResult, AhrefsServiceError

USER = "user-1"
TOP5 = ["a.nl", "b.nl", "c.nl", "d.nl", "e.nl"]
SCAN_DONE = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)

# Top 10-lijsten uit de concurrentenscan; e.nl ontbreekt en wordt opgehaald.
LISTS = {
    "klant.nl": ["dak repareren"],
    "a.nl": ["dak lekt", "dakgoot", "dak repareren", "alleen a"],
    "b.nl": ["Dak Lekt", "dakgoot", "dakkapel"],
    "c.nl": ["dakkapel", "dak repareren"],
    "d.nl": ["dakgoot"],
}
E_LIST = [{"keyword": "dakkapel", "best_position": 6}, {"keyword": "zinkwerk", "best_position": 2}]
# Posities bij de navraag (stap 4), per domein.
POSITIONS = {
    "a.nl": {"dak lekt": 2, "dakgoot": 5},
    "b.nl": {"dak lekt": 4, "dakgoot": 7, "dakkapel": 3},
    "c.nl": {"dakkapel": 1},
    "d.nl": {"dakgoot": 9},
    "e.nl": {"dakkapel": 6},
    "klant.nl": {"dakgoot": 14, "dakkapel": 8},  # dakkapel: de klant staat toch in de top 10
}
FACTS = [
    {"keyword": "dak lekt", "volume": 500, "difficulty": 10, "intents": {"informational": True}},
    {"keyword": "dakgoot", "volume": 900, "difficulty": 20, "intents": {"commercial": True, "local": True}},
]


def scan_data():
    ok = SourceInfo(state="ok")
    return Snapshot(
        sources=Sources(ahrefs=ok, prt=ok, claude=ok, profile=ok),
        competitors=[SnapshotCompetitor(domain=d, origin="ahrefs", in_top5=True) for d in TOP5],
        heatmap=Heatmap(state="ok"), summary=Summary(state="skipped"),
    ).model_dump(mode="json")


def scan_raw():
    return Raw(top10={d: RawTop10(keywords=k) for d, k in LISTS.items()}).model_dump(mode="json")


def fake_top10(domain, *, country, limit, keywords=None, max_position=10):
    if keywords is None:
        return AhrefsResult(rows=E_LIST, units=300)
    wanted = {k.casefold() for k in keywords}
    rows = [{"keyword": k, "best_position": p} for k, p in POSITIONS.get(domain, {}).items()
            if k in wanted and (max_position is None or p <= max_position)]
    return AhrefsResult(rows=rows, units=max(50, 2 * len(rows)))


def fake_overview(keywords, *, country):
    wanted = {k.casefold() for k in keywords}
    return AhrefsResult(rows=[r for r in FACTS if r["keyword"] in wanted], units=max(50, 31 * len(keywords)))


class _Base(unittest.TestCase):
    max_units = 5000

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        engine = create_engine(f"sqlite:///{self.tmp.name}/test.db", connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self._patch(worker, "SessionLocal", self.Session)
        self._patch(worker, "settings", SimpleNamespace(ahrefs_content_gap_max_units=self.max_units))
        self._patch(gap_collect, "settings", SimpleNamespace(ahrefs_competitors_keywords_per_domain=150))
        self._patch(gap_mappers.ahrefs, "is_configured", Mock(return_value=True))
        self.statuses: list[str] = []
        self.top10 = self._patch(gap_collect.ahrefs, "top10_keywords", Mock(side_effect=self._seen(fake_top10)))
        self.overview = self._patch(gap_collect.ahrefs, "keywords_overview",
                                    Mock(side_effect=self._seen(fake_overview)))

        self.customer_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        with self.Session() as db:
            db.add(CustomerWebsite(id=self.customer_id, name="Klant BV", base_url="https://www.klant.nl/",
                                   domain="klant.nl", created_by=USER, created_at=now, updated_at=now))
            db.add(Scan(customer_website_id=self.customer_id, status="completed", target="klant.nl", country="nl",
                        data=scan_data(), raw=scan_raw(), created_by=USER, created_at=now, updated_at=now,
                        completed_at=SCAN_DONE))
            db.commit()

    def _patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def _seen(self, func):
        def wrapper(*args, **kwargs):
            self.statuses.append(self.get().status)
            return func(*args, **kwargs)
        return wrapper

    def add_row(self, status="pending", **fields):
        now = datetime.now(timezone.utc)
        with self.Session() as db:
            db.add(Row(customer_website_id=self.customer_id, status=status, created_by=USER, created_at=now,
                       updated_at=now, **fields))
            db.commit()

    def get(self):
        with self.Session() as db:
            return db.get(Row, self.customer_id)

    def run_task(self):
        self.assertEqual(worker.run_content_gap_task.run(self.customer_id), self.customer_id)
        return self.get()


class RunTest(_Base):
    def test_successful_run(self):
        self.add_row()
        row = self.run_task()

        self.assertEqual((row.status, row.error_message, row.target, row.country), ("completed", None, "klant.nl", "nl"))
        self.assertIsNotNone(row.started_at)
        self.assertIsNotNone(row.completed_at)
        self.assertEqual(row.source_completed_at.replace(tzinfo=timezone.utc), SCAN_DONE)
        snapshot = GapSnapshot.model_validate(row.data)
        self.assertEqual(snapshot.competitors, TOP5)
        # Kandidaten: dakgoot (a, b, d), dak lekt (a, b), dakkapel (b, c, e); "dak repareren"
        # staat in de lijst van de klant. dakkapel vervalt na de navraag bij de klant (#8).
        self.assertEqual([k.keyword for k in snapshot.keywords], ["dakgoot", "dak lekt"])
        self.assertEqual(snapshot.found, 2)
        dakgoot = snapshot.keywords[0]
        self.assertEqual((dakgoot.volume, dakgoot.kd, dakgoot.intents, dakgoot.competitors_count, dakgoot.own_position),
                         (900, 20, ["commercial", "local"], 3, 14))
        self.assertEqual(dakgoot.positions, {"a.nl": 5, "b.nl": 7, "c.nl": None, "d.nl": 9, "e.nl": None})
        self.assertEqual(snapshot.warnings, [])

        # Lijst van e.nl opgehaald, daarna posities bij de vijf (grens 10) en de klant (zonder grens).
        calls = self.top10.call_args_list
        self.assertEqual(calls[0].args, ("e.nl",))
        self.assertIsNone(calls[0].kwargs.get("keywords"))
        self.assertEqual([c.args[0] for c in calls[1:]], [*TOP5, "klant.nl"])
        self.assertEqual([c.kwargs["max_position"] for c in calls[1:]], [10] * 5 + [None])
        # Volume, KD en intentie alleen voor wat na de klantcontrole overbleef.
        self.assertEqual(sorted(self.overview.call_args.args[0]), ["dak lekt", "dakgoot"])
        self.assertEqual(row.ahrefs_units, 300 + 4 * 50 + 50 + 50 + 62)
        self.assertEqual(self.statuses, ["collecting"] * 7 + ["enriching"])

    def test_budget_runs_out_halfway_gives_warning(self):
        # 300 (lijst e.nl) + 6 × 50 (posities) = 600; daarna past de schatting van 62 niet meer.
        self._patch(worker, "settings", SimpleNamespace(ahrefs_content_gap_max_units=620))
        self.add_row()
        row = self.run_task()
        self.assertEqual(row.status, "completed")
        snapshot = GapSnapshot.model_validate(row.data)
        self.assertEqual([k.keyword for k in snapshot.keywords], ["dakgoot", "dak lekt"])
        self.assertTrue(all(k.volume is None for k in snapshot.keywords))
        self.assertEqual(snapshot.warnings, ["Unit-plafond bereikt: volume, KD en intentie van 2 van 2 "
                                             "zoekwoorden overgeslagen."])
        self.overview.assert_not_called()
        self.assertLessEqual(row.ahrefs_units, 620)

    def test_ahrefs_error_fails_and_keeps_previous_result(self):
        previous = GapSnapshot(customer_domain="klant.nl", competitors=["a.nl", "b.nl"], found=3).model_dump(mode="json")
        done = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.add_row(data=previous, ahrefs_units=1234, completed_at=done, source_completed_at=done)
        self.top10.side_effect = AhrefsServiceError("Ahrefs staat deze aanvraag niet toe: units op", code="forbidden")

        row = self.run_task()

        self.assertEqual(row.status, "failed")
        self.assertIn("units op", row.error_message)
        self.assertEqual((row.data, row.ahrefs_units), (previous, 1234))
        self.assertEqual(row.completed_at.replace(tzinfo=timezone.utc), done)

    def test_unexpected_error_fails_and_keeps_previous_result(self):
        previous = GapSnapshot(customer_domain="klant.nl", found=3).model_dump(mode="json")
        self.add_row(data=previous)
        self.overview.side_effect = RuntimeError("stuk")
        row = self.run_task()
        self.assertEqual((row.status, row.data), ("failed", previous))
        self.assertIn("RuntimeError", row.error_message)

    def test_too_few_lists_fails(self):
        with self.Session() as db:
            db.query(Scan).update({"raw": Raw().model_dump(mode="json")})
            db.commit()
        self.top10.side_effect = AhrefsServiceError("Ahrefs-fout: kapot")
        self.add_row()
        row = self.run_task()
        self.assertEqual((row.status, row.error_message), ("failed", worker.TOO_FEW_LISTS_MESSAGE))

    def test_blocked_at_start_fails(self):
        with self.Session() as db:
            db.query(Scan).update({"target": "ander.nl"})
            db.commit()
        self.add_row()
        row = self.run_task()
        self.assertEqual((row.status, row.error_message), ("failed", gap_mappers.BLOCKED_MESSAGES["no_scan"]))
        self.top10.assert_not_called()

    def test_second_delivery_does_nothing(self):
        self.add_row(status="completed", completed_at=SCAN_DONE - timedelta(days=1))
        row = self.run_task()
        self.assertEqual(row.status, "completed")
        self.top10.assert_not_called()


if __name__ == "__main__":
    unittest.main()
