"""Vastgelopen scans herstellen (scan_recovery), tegen een SQLite-database met alleen `launch_scans`."""
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import CustomerWebsite, LaunchScan
from app.features.launch_checklist.services import scan_recovery
from app.features.launch_checklist.services.discovery import DiscoveryResult
from app.features.launch_checklist.worker import content_scan, launch_scan
from app.features.launch_checklist.services.scan_recovery import (
    INTERRUPTED_SCAN_MESSAGE,
    SCAN_MAX_AGE,
    STALE_SCAN_AFTER,
    heartbeat,
    recover_stale_scan,
)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
CUSTOMER = "klant-1"


class RecoverStaleScanTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        LaunchScan.__table__.create(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)

    def scan(self, *, status="inventory", phase=1, created_ago=timedelta(minutes=5), updated_ago=timedelta(minutes=1)):
        row = LaunchScan(
            id=str(uuid.uuid4()), customer_website_id=CUSTOMER, phase=phase, status=status,
            base_url="https://www.klant.nl/", total_urls=0, inventoried_urls=0, failed_urls=0,
            max_pages=500, vitals_max_pages=0, vitals_total=0, vitals_measured=0, created_by="user-1",
            created_at=NOW - created_ago, updated_at=NOW - updated_ago,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def reloaded(self, scan):
        self.db.expire_all()
        return self.db.get(LaunchScan, scan.id)

    def test_fresh_active_scan_is_left_alone(self):
        scan = self.scan()
        self.assertFalse(recover_stale_scan(self.db, scan, now=NOW))
        self.assertEqual(self.reloaded(scan).status, "inventory")
        self.assertIsNone(self.reloaded(scan).error_message)

    def test_old_updated_at_goes_to_failed(self):
        scan = self.scan(status="fetching", phase=2, created_ago=timedelta(minutes=40),
                         updated_ago=STALE_SCAN_AFTER + timedelta(minutes=1))
        self.assertTrue(recover_stale_scan(self.db, scan, now=NOW))
        row = self.reloaded(scan)
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.error_message, INTERRUPTED_SCAN_MESSAGE)
        self.assertIn("onderbroken", row.error_message)

    def test_old_running_scan_with_recent_update_is_left_alone(self):
        # created_at telt de wachttijd in de rij mee: een scan die 20 min wachtte en 50 min loopt,
        # is ouder dan SCAN_MAX_AGE maar loopt nog (levensteken).
        scan = self.scan(status="checking", phase=4, created_ago=SCAN_MAX_AGE + timedelta(minutes=5),
                         updated_ago=timedelta(seconds=30))
        self.assertFalse(recover_stale_scan(self.db, scan, now=NOW))
        self.assertEqual(self.reloaded(scan).status, "checking")

    def test_old_pending_scan_goes_to_failed_even_with_recent_update(self):
        scan = self.scan(status="pending", created_ago=SCAN_MAX_AGE + timedelta(minutes=1),
                         updated_ago=timedelta(seconds=30))
        self.assertTrue(recover_stale_scan(self.db, scan, now=NOW))
        self.assertEqual(self.reloaded(scan).status, "failed")

    def test_phase_3_analysis_is_not_touched(self):
        scan = self.scan(status="analyzing", phase=3, created_ago=timedelta(days=3), updated_ago=timedelta(hours=2))
        self.assertFalse(recover_stale_scan(self.db, scan, now=NOW))
        self.assertEqual(self.reloaded(scan).status, "analyzing")

    def test_phase_4_report_agent_is_in_scope(self):
        scan = self.scan(status="analyzing", phase=4, created_ago=timedelta(minutes=50),
                         updated_ago=STALE_SCAN_AFTER + timedelta(minutes=1))
        self.assertTrue(recover_stale_scan(self.db, scan, now=NOW))
        self.assertEqual(self.reloaded(scan).status, "failed")

    def test_completed_scan_is_not_touched(self):
        for status in ("completed", "failed", "canceled"):
            scan = self.scan(status=status, created_ago=timedelta(days=2), updated_ago=timedelta(days=2))
            self.assertFalse(recover_stale_scan(self.db, scan, now=NOW))
            self.assertEqual(self.reloaded(scan).status, status)

    def test_pending_scan_only_counts_age(self):
        # Kan in de wachtrij staan achter andere taken: de worker raakt updated_at pas bij de start.
        waiting = self.scan(status="pending", created_ago=timedelta(minutes=40), updated_ago=timedelta(minutes=40))
        self.assertFalse(recover_stale_scan(self.db, waiting, now=NOW))
        self.assertEqual(self.reloaded(waiting).status, "pending")
        lost = self.scan(status="pending", created_ago=SCAN_MAX_AGE + timedelta(minutes=1),
                         updated_ago=SCAN_MAX_AGE + timedelta(minutes=1))
        self.assertTrue(recover_stale_scan(self.db, lost, now=NOW))
        self.assertEqual(self.reloaded(lost).status, "failed")

    def test_naive_timestamps_count_as_utc(self):
        scan = self.scan(updated_ago=STALE_SCAN_AFTER + timedelta(minutes=1), created_ago=timedelta(minutes=45))
        self.assertIsNone(self.reloaded(scan).updated_at.tzinfo)  # SQLite geeft naïeve tijden terug
        self.assertTrue(recover_stale_scan(self.db, self.reloaded(scan), now=NOW))

    def test_router_recovers_all_stale_scans_of_customer(self):
        from app.features.launch_checklist import router

        stale = self.scan(updated_ago=STALE_SCAN_AFTER + timedelta(minutes=5), created_ago=timedelta(minutes=50))
        fresh = self.scan(status="vitals")
        real_recover = scan_recovery.recover_stale_scan
        router.recover_stale_scan = lambda db, scan: real_recover(db, scan, now=NOW)
        try:
            router._recover_stale_scans(self.db, CUSTOMER)
        finally:
            router.recover_stale_scan = real_recover
        self.assertEqual(self.reloaded(stale).status, "failed")
        self.assertEqual(self.reloaded(fresh).status, "vitals")


class SoftTimeLimitTest(unittest.TestCase):
    """Een soft time-out in een verrijkingsstap moet de buitenste handler bereiken."""

    def setUp(self):
        # Eén gedeelde verbinding: de AI-analyse leest de status ook vanuit de pool-threads.
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        LaunchScan.__table__.create(engine)
        CustomerWebsite.__table__.create(engine)
        self.Session = sessionmaker(bind=engine)

    def add_scan(self, **fields):
        now = datetime.now(timezone.utc)
        values = dict(
            id=str(uuid.uuid4()), customer_website_id=CUSTOMER, phase=1, status="pending",
            base_url="https://www.klant.nl/", total_urls=0, inventoried_urls=0, failed_urls=0,
            max_pages=500, vitals_max_pages=0, vitals_total=0, vitals_measured=0, created_by="user-1",
            created_at=now, updated_at=now,
        )
        values.update(fields)
        with self.Session() as db:
            db.add(LaunchScan(**values))
            db.commit()
        return values["id"]

    def status(self, scan_id):
        with self.Session() as db:
            row = db.get(LaunchScan, scan_id)
            return row.status, row.error_message

    def test_launch_scan_timeout_in_ahrefs_marks_failed(self):
        scan_id = self.add_scan()

        async def no_pages(**_kwargs):
            return []

        with patch.object(launch_scan, "SessionLocal", self.Session), \
                patch.object(launch_scan, "discover_from_sitemaps", return_value=DiscoveryResult(urls=[])), \
                patch.object(launch_scan, "run_inventory", side_effect=no_pages), \
                patch.object(launch_scan, "run_ai_checks", return_value={}), \
                patch.object(launch_scan, "_enrich_with_ahrefs", side_effect=SoftTimeLimitExceeded()), \
                patch.object(launch_scan, "run_agent", side_effect=AssertionError("had niet verder mogen gaan")):
            launch_scan.run_launch_scan_task.run(scan_id)
        self.assertEqual(self.status(scan_id), ("failed", "Scan duurde te lang en is afgebroken."))

    def test_task_does_not_start_on_recovered_scan(self):
        scan_id = self.add_scan(status="failed", error_message=INTERRUPTED_SCAN_MESSAGE)
        with patch.object(launch_scan, "SessionLocal", self.Session), \
                patch.object(launch_scan, "discover_from_sitemaps", side_effect=AssertionError("niet starten")):
            launch_scan.run_launch_scan_task.run(scan_id)
        self.assertEqual(self.status(scan_id), ("failed", INTERRUPTED_SCAN_MESSAGE))

    def test_content_analysis_timeout_finishes_without_waiting_for_queued_pages(self):
        """Zoals in productie: de time-out komt in de hoofdthread terwijl een pagina nog bezig is."""
        scan_id = self.add_scan(phase=3, status="analyzing")
        concurrency = 1
        calls = []
        started = threading.Event()   # eerste pagina is begonnen
        release = threading.Event()   # laat de geblokkeerde pagina(s) doorlopen
        finished = threading.Event()  # een pagina is klaar
        # Opruimen (LIFO): eerst vrijgeven, dan wachten tot de worker-thread klaar is.
        self.addCleanup(finished.wait, 10)
        self.addCleanup(release.set)

        def analyse(_scan_id, page_id, **_kwargs):
            calls.append(page_id)
            started.set()
            release.wait(timeout=10)  # timeout: een fout kan de suite niet laten hangen
            finished.set()
            return {"ok": True, "warnings": [], "usage": {}}

        def timeout_in_main_thread(_futures):
            # Het signaal van Celery: SoftTimeLimitExceeded in de hoofdthread, terwijl de worker bezig is.
            started.wait(timeout=10)
            raise SoftTimeLimitExceeded()

        finish = Mock()
        with patch.object(content_scan, "SessionLocal", self.Session), \
                patch.object(content_scan, "analyse_page", side_effect=analyse), \
                patch.object(content_scan, "as_completed", side_effect=timeout_in_main_thread), \
                patch.object(content_scan, "_finish_analysis", finish), \
                patch.object(content_scan, "run_gap", side_effect=AssertionError("had niet verder mogen gaan")), \
                patch.object(content_scan.settings, "launch_content_ai_concurrency", concurrency):
            content_scan.run_content_analysis_task.run(scan_id, [f"p{i}" for i in range(6)], True)

        # De taak is teruggekeerd terwijl de pagina nog geblokkeerd is: er is niet op gewacht.
        self.assertTrue(started.is_set())
        self.assertFalse(finished.is_set(), "de taak wachtte op een lopende pagina")
        finish.assert_called_once()
        self.assertIn("duurde te lang", " ".join(finish.call_args.kwargs["warnings"]))
        self.assertLessEqual(len(calls), concurrency)  # de wachtende pagina's zijn niet gestart


class HeartbeatTest(unittest.TestCase):
    def test_throttles_calls(self):
        calls = []
        beat = heartbeat(lambda: calls.append(1), interval=3600)
        for _ in range(5):
            beat()
        self.assertEqual(calls, [])  # net aangemaakt: de aanroeper heeft zelf net bijgewerkt
        beat = heartbeat(lambda: calls.append(1), interval=0)
        beat()
        beat()
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
