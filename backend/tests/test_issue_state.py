"""Triage-overdracht: carried_state_from_rows en previous_issue_state (SQLite in het geheugen)."""
import unittest
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import CustomerCategory, CustomerWebsite, LaunchScan, LaunchScanIssue
from app.features.launch_checklist.services.issue_state import (
    carried_state_from_rows,
    issue_key,
    previous_issue_state,
    with_carried_state,
)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
PUSHED = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


def _issue(scan_id, issue_type, url, status="open", item_id=None):
    return LaunchScanIssue(
        id=str(uuid.uuid4()), scan_id=scan_id, issue_type=issue_type, category="techniek", severity="hoog",
        title=issue_type, description="-", url=url, status=status,
        external_provider="monday" if item_id else None, external_item_id=item_id,
        external_url=f"https://monday.example/items/{item_id}" if item_id else None,
        pushed_at=PUSHED if item_id else None, created_at=NOW, updated_at=NOW,
    )


class CarriedStateFromRowsTest(unittest.TestCase):
    def test_rules(self):
        rows = [
            _issue("s", "ignored", "https://a/", status="genegeerd"),
            _issue("s", "linked", "https://a/", status="doorgezet", item_id="1"),
            _issue("s", "solved_linked", "https://a/", status="opgelost", item_id="2"),
            _issue("s", "solved", "https://a/", status="opgelost"),
            _issue("s", "open", "https://a/"),
            _issue("s", "ignored_linked", None, status="genegeerd", item_id="3"),
        ]
        carried = carried_state_from_rows(rows)
        self.assertEqual(set(carried), {
            ("ignored", "https://a/"), ("linked", "https://a/"), ("solved_linked", "https://a/"),
            ("ignored_linked", ""),
        })
        self.assertEqual(carried[("ignored", "https://a/")]["status"], "genegeerd")
        self.assertIsNone(carried[("ignored", "https://a/")]["external_item_id"])
        self.assertEqual(carried[("linked", "https://a/")], {
            "status": "doorgezet", "external_provider": "monday", "external_item_id": "1",
            "external_url": "https://monday.example/items/1", "pushed_at": PUSHED,
        })
        self.assertEqual(carried[("solved_linked", "https://a/")]["status"], "doorgezet")
        # Genegeerd wint van doorgezet, de koppeling blijft wel staan.
        self.assertEqual(carried[("ignored_linked", "")]["status"], "genegeerd")
        self.assertEqual(carried[("ignored_linked", "")]["external_item_id"], "3")

    def test_first_row_wins_and_empty_input(self):
        rows = [
            _issue("s", "dup", "https://a/", status="doorgezet", item_id="1"),
            _issue("s", "dup", "https://a/", status="genegeerd"),
        ]
        self.assertEqual(carried_state_from_rows(rows)[issue_key("dup", "https://a/")]["external_item_id"], "1")
        self.assertEqual(carried_state_from_rows([]), {})
        self.assertEqual(carried_state_from_rows(iter(rows[1:]))[("dup", "https://a/")]["status"], "genegeerd")

    def test_with_carried_state(self):
        carried = carried_state_from_rows([_issue("s", "x", "https://a/", status="doorgezet", item_id="9")])
        merged = with_carried_state({"issue_type": "x", "url": "https://a/", "title": "X"}, carried)
        self.assertEqual((merged["status"], merged["external_item_id"], merged["title"]), ("doorgezet", "9", "X"))
        fresh = with_carried_state({"issue_type": "y", "url": "https://a/"}, carried)
        self.assertEqual(fresh["status"], "open")
        self.assertNotIn("external_item_id", fresh)


class PreviousIssueStateTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        for model in (CustomerCategory, CustomerWebsite, LaunchScan, LaunchScanIssue):
            model.__table__.create(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.customer_id = str(uuid.uuid4())
        self.db.add(CustomerWebsite(id=self.customer_id, name="Klant", base_url="https://www.klant.nl/",
                                    domain="klant.nl", created_by="u", created_at=NOW, updated_at=NOW))
        self.db.commit()

    def scan(self, phase=1, status="completed", created_at=NOW):
        scan = LaunchScan(
            id=str(uuid.uuid4()), customer_website_id=self.customer_id, phase=phase, status=status,
            base_url="https://www.klant.nl/", total_urls=0, inventoried_urls=0, failed_urls=0, max_pages=500,
            vitals_max_pages=0, vitals_total=0, vitals_measured=0, created_by="u",
            created_at=created_at, updated_at=created_at,
        )
        self.db.add(scan)
        self.db.commit()
        return scan

    def test_uses_latest_completed_scan_of_same_phase(self):
        older = self.scan(created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        latest = self.scan(created_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
        other_phase = self.scan(phase=3, created_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
        failed = self.scan(status="failed", created_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
        self.db.add_all([
            _issue(older.id, "old", "https://a/", status="genegeerd"),
            _issue(latest.id, "kept", "https://a/", status="doorgezet", item_id="5"),
            _issue(latest.id, "open", "https://a/"),
            _issue(other_phase.id, "phase3", "https://a/", status="genegeerd"),
            _issue(failed.id, "failed", "https://a/", status="genegeerd"),
        ])
        self.db.commit()
        current = self.scan(status="analyzing", created_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
        carried = previous_issue_state(self.db, current)
        self.assertEqual(set(carried), {("kept", "https://a/")})
        self.assertEqual(carried[("kept", "https://a/")]["external_item_id"], "5")

    def test_no_previous_scan(self):
        self.assertEqual(previous_issue_state(self.db, self.scan()), {})


if __name__ == "__main__":
    unittest.main()
