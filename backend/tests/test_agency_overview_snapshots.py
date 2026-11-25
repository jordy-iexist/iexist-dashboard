"""Momentopname van de posities voor het bureau-overzicht (features/agency_overview/services/rank_snapshots).

`snapshot_from_rows` is puur; `refresh_all` draait tegen een in-memory SQLite-database met een
vervangen `organic_rows` (geen netwerk).
"""
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, CustomerRankSnapshot, CustomerWebsite
from app.features.agency_overview.services import rank_snapshots
from app.features.agency_overview.services.rank_snapshots import (
    is_token_error,
    refresh_all,
    snapshot_from_rows,
)
from app.features.customers.rankings import summarize

NOW = datetime(2026, 11, 25, 6, 0, tzinfo=timezone.utc)


def _term(name, rank, month="NTH", *, url="https://klant.nl/pagina/", ai=0, term_type="organic", engine="Google.nl"):
    return {
        "name": name, "rank": rank, "monthagorank": month, "matchedurl": url, "engine": engine,
        "term_type": term_type, "is_ai_term": ai, "localmonthlysearches": "100",
    }


class SnapshotFromRowsTest(unittest.TestCase):
    def test_counts_match_summarize(self):
        rows = [
            _term("een", "1", "2"), _term("twee", 8, 12), _term("drie", "11", "9"),
            _term("vier", "NTH", "5"), _term("vijf", "40", "NTH"),
        ]
        snap = snapshot_from_rows(rows)
        self.assertEqual(snap["keywords"], summarize(rows)["keywords"])
        self.assertEqual(snap["keywords"], 5)
        self.assertEqual(snap["top10"], 2)  # 1 en 8
        self.assertEqual(snap["top10_month_ago"], 3)  # 2, 9 en 5

    def test_ai_terms_do_not_count(self):
        snap = snapshot_from_rows([_term("een", 1, 1), _term("ai", 1, 1, ai=1), _term("x", 1, 1, term_type="ai")])
        self.assertEqual((snap["keywords"], snap["top10"]), (1, 1))

    def test_drop_of_five_or_more_places(self):
        snap = snapshot_from_rows([
            _term("gezakt", "18", "12"),   # 6 plekken, binnen de top 20 → daling
            _term("klein", "16", "12"),    # 4 plekken → geen daling
            _term("ver", "40", "25"),      # een maand geleden buiten de top 20 → geen daling
            _term("gestegen", "3", "9"),
        ])
        self.assertEqual(snap["drops"], [
            {"keyword": "gezakt", "rank": 18, "month_ago_rank": 12, "url": "https://klant.nl/pagina/"},
        ])

    def test_out_of_top10_counts_even_when_small(self):
        snap = snapshot_from_rows([_term("rand", "11", "10"), _term("binnen", "10", "7")])
        self.assertEqual([d["keyword"] for d in snap["drops"]], ["rand"])

    def test_nth_counts_as_101(self):
        snap = snapshot_from_rows([_term("weg", "NTH", "15", url="None"), _term("nooit", "NTH", "NTH")])
        self.assertEqual(snap["drops"], [{"keyword": "weg", "rank": None, "month_ago_rank": 15, "url": None}])
        self.assertEqual(snap["top10"], 0)

    def test_sorted_by_largest_drop(self):
        snap = snapshot_from_rows([
            _term("a", "11", "4"),   # 7
            _term("b", "NTH", "20"),  # 81
            _term("c", "19", "8"),   # 11
        ])
        self.assertEqual([d["keyword"] for d in snap["drops"]], ["b", "c", "a"])

    def test_duplicate_keywords_count_once_with_largest_drop(self):
        snap = snapshot_from_rows([
            _term("Advocaat  Arbeidsrecht", "11", "4", engine="Google.nl"),
            _term("advocaat arbeidsrecht", "30", "6", engine="Google.be"),
            _term("advocaat arbeidsrecht", "5", "5", engine="Mobile"),
        ])
        self.assertEqual(len(snap["drops"]), 1)
        self.assertEqual((snap["drops"][0]["rank"], snap["drops"][0]["month_ago_rank"]), (30, 6))
        # Tellen gaat per rij, zoals het klantdashboard.
        self.assertEqual(snap["keywords"], 3)

    def test_no_month_ago_rank(self):
        rows = [{"name": "nieuw", "rank": "3", "term_type": "organic", "is_ai_term": 0},
                {"name": "leeg", "rank": "12", "monthagorank": "", "term_type": "organic", "is_ai_term": 0}]
        snap = snapshot_from_rows(rows)
        self.assertIsNone(snap["top10_month_ago"])
        self.assertEqual(snap["top10"], 1)
        self.assertEqual(snap["drops"], [])

    def test_all_nth_month_ago_is_zero_not_none(self):
        snap = snapshot_from_rows([_term("a", "3", "NTH")])
        self.assertEqual(snap["top10_month_ago"], 0)

    def test_empty(self):
        self.assertEqual(snapshot_from_rows([]),
                         {"keywords": 0, "top10": 0, "top10_month_ago": None, "drops": []})

    def test_token_error(self):
        self.assertTrue(is_token_error(
            "Posities niet opgehaald uit ProRankTracker: ProRankTracker weigert het API-token (ongeldig of verlopen)."))
        self.assertFalse(is_token_error("Posities niet opgehaald uit ProRankTracker: Timeout bij verbinden."))
        self.assertFalse(is_token_error(None))


class RefreshAllTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, autoflush=False)
        self.ids = {}
        with self.Session() as db:
            for name, url in (("Ok", "https://ok.nl/"), ("Fout", "https://fout.nl/"),
                              ("Niet gevolgd", "https://leeg.nl/"), ("Kapot", "https://kapot.nl/")):
                cid = str(uuid.uuid4())
                self.ids[name] = cid
                db.add(CustomerWebsite(id=cid, name=name, base_url=url, domain=url, created_by="u",
                                       created_at=NOW, updated_at=NOW))
            db.commit()

    def fake_rows(self, base_url):
        self.threads.add(threading.current_thread().name)
        if "ok.nl" in base_url:
            return "ok", [_term("a", "3", "2"), _term("b", "NTH", "8")], None
        if "fout.nl" in base_url:
            return "error", [], "Posities niet opgehaald uit ProRankTracker: Timeout."
        if "kapot.nl" in base_url:
            raise RuntimeError("onverwacht")
        return "not_tracked", [], None

    def run_refresh(self, now=NOW):
        self.threads = set()
        with patch.object(rank_snapshots, "organic_rows", side_effect=self.fake_rows), self.Session() as db, \
                self.assertLogs(rank_snapshots.logger, "ERROR") as logs:
            counts = refresh_all(db, now=now)
        self.assertIn("kapot.nl", logs.output[0])
        return counts

    def snapshots(self):
        with self.Session() as db:
            return {s.customer_website_id: s for s in db.query(CustomerRankSnapshot).all()}

    def test_stores_one_snapshot_per_customer(self):
        counts = self.run_refresh()
        self.assertEqual(counts, {"ok": 1, "not_configured": 0, "not_tracked": 1, "error": 2})
        snaps = self.snapshots()
        ok = snaps[self.ids["Ok"]]
        self.assertEqual((ok.state, ok.keywords, ok.top10, ok.top10_month_ago), ("ok", 2, 1, 2))
        self.assertEqual(ok.drops[0]["keyword"], "b")
        self.assertIsNotNone(ok.fetched_at)
        self.assertEqual(snaps[self.ids["Fout"]].state, "error")
        self.assertIn("Timeout", snaps[self.ids["Fout"]].message)
        self.assertIsNone(snaps[self.ids["Fout"]].keywords)
        # Een fout bij één klant stopt de rest niet.
        self.assertEqual(snaps[self.ids["Kapot"]].state, "error")
        self.assertEqual(snaps[self.ids["Niet gevolgd"]].state, "not_tracked")
        # De aanroepen lopen in threads, niet in de hoofdthread.
        self.assertNotIn(threading.current_thread().name, self.threads)

    def test_second_refresh_updates_in_place(self):
        self.run_refresh()
        later = NOW + timedelta(days=1)
        self.run_refresh(now=later)
        snaps = self.snapshots()
        self.assertEqual(len(snaps), 4)
        fetched = snaps[self.ids["Ok"]].fetched_at.replace(tzinfo=timezone.utc)
        self.assertEqual(fetched, later)


if __name__ == "__main__":
    unittest.main()
