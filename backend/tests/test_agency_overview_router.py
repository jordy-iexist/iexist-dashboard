"""Endpoints van het bureau-overzicht (features/agency_overview/router).

In-memory SQLite; ProRankTracker (`organic_rows`), Search Console en de koppelingscontroles zijn
vervangen, dus geen netwerk.
"""
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import require_user_id
from app.db.models import Base, CustomerRankSnapshot, CustomerWebsite, WorkItem
from app.db.session import get_db
from app.features.agency_overview.router import router
from app.features.agency_overview.services import overview as overview_module
from app.features.agency_overview.services import rank_snapshots

USER = "user-1"
NOW = datetime.now(timezone.utc)
API = "/api/agency-overview"


def _term(name, rank, month):
    return {"name": name, "rank": rank, "monthagorank": month, "matchedurl": "https://klant.nl/",
            "term_type": "organic", "is_ai_term": 0}


class AgencyOverviewRouterTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, autoflush=False)
        self.customer = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(id=self.customer, name="Klant A", base_url="https://klant.nl/",
                                   domain="klant.nl", created_by=USER, created_at=NOW, updated_at=NOW))
            db.add(WorkItem(id=str(uuid.uuid4()), customer_website_id=self.customer, source="manual",
                            status="todo", kind="update", title="Taak", severity="hoog", position=1.0,
                            created_by=USER, created_at=NOW, updated_at=NOW))
            db.commit()

        patches = [
            patch.object(overview_module.gsc, "is_configured", return_value=True),
            patch.object(overview_module.prt, "is_configured", return_value=True),
            patch.object(overview_module, "cached_sites",
                         return_value=[{"site_url": "sc-domain:klant.nl", "permission": "siteOwner"}]),
            patch.object(rank_snapshots, "organic_rows",
                         return_value=("ok", [_term("advocaat", "11", "4"), _term("b", "2", "3")], None)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        self.app = FastAPI()
        self.app.include_router(router)

        def override_db():
            with self.Session() as db:
                yield db

        self.app.dependency_overrides[get_db] = override_db
        self.app.dependency_overrides[require_user_id] = lambda: USER
        self.client = TestClient(self.app)

    def assert_contract(self, body):
        self.assertEqual(set(body), {"generated_at", "week", "rankings_fetched_at", "kpis", "signals", "customers"})
        self.assertEqual(set(body["kpis"]), {"customers", "customers_attention", "open_tasks", "open_tasks_high"})
        for signal in body["signals"]:
            self.assertEqual(set(signal), {"id", "kind", "severity", "customer_id", "customer_name", "text", "link"})
            self.assertEqual(set(signal["link"]), {"type", "customer_id", "month"})
        for row in body["customers"]:
            self.assertEqual(set(row), {"id", "name", "rank_state", "keywords", "top10", "top10_delta",
                                        "open_tasks", "signal_count"})

    def test_overview_without_snapshots(self):
        response = self.client.get(f"{API}/overview")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assert_contract(body)
        self.assertIsNone(body["rankings_fetched_at"])
        self.assertEqual(body["kpis"]["customers"], 1)
        self.assertEqual(body["kpis"]["open_tasks"], 1)
        self.assertEqual(body["kpis"]["open_tasks_high"], 1)
        self.assertEqual(body["customers"][0]["rank_state"], "missing")
        self.assertIsInstance(body["week"], int)

    def test_refresh_stores_snapshots_and_returns_overview(self):
        response = self.client.post(f"{API}/rankings/refresh")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assert_contract(body)
        self.assertIsNotNone(body["rankings_fetched_at"])
        row = body["customers"][0]
        self.assertEqual((row["rank_state"], row["keywords"], row["top10"], row["top10_delta"]), ("ok", 2, 1, -1))
        drops = [s for s in body["signals"] if s["kind"] == "daling"]
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0]["text"], '"advocaat" gezakt van #4 naar #11')
        self.assertEqual(drops[0]["link"], {"type": "customer_home", "customer_id": self.customer, "month": None})
        with self.Session() as db:
            self.assertEqual(db.query(CustomerRankSnapshot).count(), 1)

        # Daarna geeft GET hetzelfde beeld uit de opgeslagen momentopname.
        again = self.client.get(f"{API}/overview").json()
        self.assertEqual(again["customers"], body["customers"])

    def test_requires_user(self):
        del self.app.dependency_overrides[require_user_id]
        self.assertEqual(self.client.get(f"{API}/overview").status_code, 401)
        self.assertEqual(self.client.post(f"{API}/rankings/refresh").status_code, 401)


if __name__ == "__main__":
    unittest.main()
