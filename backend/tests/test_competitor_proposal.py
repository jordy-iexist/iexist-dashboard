"""Voorstel voor de wizard van de concurrentieanalyse (features/competitor_analysis/services/proposal).

In-memory SQLite; ProRankTracker (`proposal.organic_rows`), Ahrefs (`is_configured`,
`limits_and_usage`) en Claude (`is_configured`) zijn in elke test vervangen: geen netwerk.
"""
import time
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import require_user_id
from app.db.models import Base, CustomerQuickWins, CustomerWebsite
from app.db.session import get_db
from app.features.competitor_analysis.router import router
from app.features.competitor_analysis.schemas import ProposalResponse
from app.features.competitor_analysis.services import estimate, proposal
from app.features.customers.rankings import STATE_MESSAGES
from app.services.ahrefs.client import AhrefsServiceError

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)


def _prt(name, rank="7", *, volume="100", url="https://klant.nl/seo/", engine="Google.nl"):
    return {
        "name": name, "rank": rank, "monthagorank": "9", "localmonthlysearches": volume,
        "matchedurl": url, "engine": engine, "term_type": "organic", "is_ai_term": 0,
    }


def _qw(keyword, position=8, volume=500, url="https://klant.nl/qw/"):
    return {"keyword": keyword, "position": position, "delta": None, "volume": volume, "kd": 20,
            "url": url, "kans": "hoog"}


USAGE = {
    "units_limit_workspace": 800000, "units_usage_workspace": 74070,
    "units_limit_api_key": None, "units_usage_api_key": 4123,
}


class MergeTest(unittest.TestCase):
    def test_prt_leads_quick_wins_fill_and_deduplicate(self):
        rows = proposal.merge_keywords(
            [
                _prt("SEO bureau", "5", volume="", url="https://www.klant.nl/seo/"),
                _prt("seo  bureau", "9", url="https://klant.nl/oud/", engine="Bing"),  # dubbel: beste positie telt
                _prt("webdesign", "NTH", volume="300", url="None"),
                _prt("extern", "3", volume="50", url="https://ander.nl/x"),
            ],
            [_qw("seo bureau", 12, 900), _qw("Linkbuilding", 6, 400), _qw("webdesign", 4, 10)],
            "klant.nl",
        )
        by_keyword = {r.keyword: r for r in rows}
        self.assertEqual(len(rows), 4)
        seo = by_keyword["SEO bureau"]
        # PRT is leidend voor positie en URL; het volume ontbreekt in PRT en komt uit de quick win.
        self.assertEqual((seo.position, seo.url, seo.volume, seo.source), (5, "https://www.klant.nl/seo/", 900, "prt"))
        # PRT zonder positie blijft leidend (geen positie uit de quick win), volume uit PRT.
        web = by_keyword["webdesign"]
        self.assertEqual((web.position, web.url, web.volume, web.source), (None, None, 300, "prt"))
        self.assertEqual(by_keyword["Linkbuilding"].source, "ahrefs")
        # URL buiten het klantdomein vervalt.
        self.assertIsNone(by_keyword["extern"].url)
        # Volume aflopend.
        self.assertEqual([r.keyword for r in rows], ["SEO bureau", "Linkbuilding", "webdesign", "extern"])
        self.assertEqual(proposal.unique_pages(rows), ["https://klant.nl/qw/", "https://www.klant.nl/seo/"])

    def test_domain_and_url_helpers(self):
        self.assertTrue(proposal.on_domain("https://www.klant.nl/a", "klant.nl"))
        self.assertTrue(proposal.on_domain("shop.klant.nl/a", "klant.nl"))
        self.assertFalse(proposal.on_domain("https://nietklant.nl/a", "klant.nl"))
        self.assertFalse(proposal.on_domain("https://klant.nl.evil.com/a", "klant.nl"))
        self.assertFalse(proposal.on_domain("https://klant.nl/a", ""))
        self.assertEqual(proposal.normalize_url("klant.nl/a"), "https://klant.nl/a")
        self.assertIsNone(proposal.normalize_url("ftp://klant.nl/a"))
        self.assertIsNone(proposal.normalize_url("   "))

    def test_ahrefs_status_shows_remaining_units(self):
        status = proposal.ahrefs_status(USAGE)
        self.assertEqual(status.state, "ok")
        self.assertIn("725.930 van 800.000 units", status.message)
        # Een eigen limiet op de sleutel telt als die kleiner is.
        status = proposal.ahrefs_status({**USAGE, "units_limit_api_key": 5000})
        self.assertIn("877 van 5.000", status.message)
        status = proposal.ahrefs_status({**USAGE, "units_usage_workspace": 800000})
        self.assertEqual(status.state, "error")
        self.assertEqual(proposal.ahrefs_status({}).state, "ok")

    def test_prt_status_mapping(self):
        self.assertEqual(proposal.prt_status("ok", [_prt("a"), _prt("A")], None).message,
                         "1 gevolgde zoekwoord uit ProRankTracker.")
        self.assertEqual(proposal.prt_status("not_tracked", [], None).state, "empty")
        self.assertEqual(proposal.prt_status("not_configured", [], None).message, STATE_MESSAGES["not_configured"])
        self.assertEqual(proposal.prt_status("error", [], "Kapot").model_dump(), {"state": "error", "message": "Kapot"})


class _ProposalBase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.customer_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(id=self.customer_id, name="Klant", base_url="https://www.klant.nl/",
                                   domain="klant.nl", created_by="user-1", created_at=NOW, updated_at=NOW))
            db.commit()

        self.settings = SimpleNamespace(pagespeed_api_key="psi", ahrefs_country="NL",
                                        competitor_analysis_max_keywords=10)
        self._patch(proposal, "settings", self.settings)
        self.organic = self._patch(proposal, "organic_rows", Mock(return_value=("ok", [_prt("seo bureau")], None)))
        self.ahrefs_configured = self._patch(proposal.ahrefs, "is_configured", Mock(return_value=True))
        self.usage = self._patch(proposal.ahrefs, "limits_and_usage", Mock(return_value=USAGE))
        self.claude = self._patch(proposal.anthropic_client, "is_configured", Mock(return_value=True))
        self.organic_keywords = self._patch(proposal.ahrefs, "organic_keywords", Mock())

        app = FastAPI()
        app.include_router(router)

        def override_db():
            with self.Session() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_user_id] = lambda: "user-1"
        self.client = TestClient(app)

    def _patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def store_quick_wins(self, rows, target="klant.nl"):
        with self.Session() as db:
            db.add(CustomerQuickWins(customer_website_id=self.customer_id, target=target, country="nl", rows=rows,
                                     units=24, fetched_at=NOW, created_at=NOW, updated_at=NOW))
            db.commit()

    def get(self):
        return self.client.get(f"/api/competitor-analyses/customers/{self.customer_id}/proposal")


class ProposalEndpointTest(_ProposalBase):
    def test_prt_and_quick_wins_merged(self):
        self.store_quick_wins([_qw("SEO Bureau", 11, 900), _qw("linkbuilding", 6, 400)])
        response = self.get()
        self.assertEqual(response.status_code, 200)
        body = ProposalResponse.model_validate(response.json())
        self.assertEqual([(k.keyword, k.source, k.position) for k in body.keywords],
                         [("linkbuilding", "ahrefs", 6), ("seo bureau", "prt", 7)])
        self.assertEqual(body.pages, ["https://klant.nl/qw/", "https://klant.nl/seo/"])
        self.assertEqual(body.sources.prt.state, "ok")
        self.assertEqual(body.sources.ahrefs.state, "ok")
        self.assertIn("725.930", body.sources.ahrefs.message)
        self.assertEqual(body.sources.pagespeed.state, "ok")
        self.assertEqual(body.sources.claude.state, "ok")
        self.assertEqual(body.sources.google.state, "skipped")
        self.assertEqual(body.defaults.country, "nl")
        self.assertEqual(body.defaults.top_n, 10)
        self.assertEqual(body.max_keywords, 10)
        self.assertEqual(body.rates, estimate.rates())
        # Geen betaalde aanroep: de quick wins komen uit de database.
        self.organic_keywords.assert_not_called()
        self.organic.assert_called_once_with("https://www.klant.nl/")

    def test_quick_wins_of_other_domain_are_ignored(self):
        self.store_quick_wins([_qw("oud domein")], target="oudeklant.nl")
        body = self.get().json()
        self.assertEqual([k["keyword"] for k in body["keywords"]], ["seo bureau"])

    def test_sources_not_configured(self):
        self.ahrefs_configured.return_value = False
        self.claude.return_value = False
        self.settings.pagespeed_api_key = ""
        self.organic.return_value = ("not_configured", [], None)
        self.store_quick_wins([_qw("linkbuilding")])
        body = self.get().json()
        self.assertEqual(body["sources"]["ahrefs"]["state"], "not_configured")
        self.assertEqual(body["sources"]["prt"]["state"], "not_configured")
        self.assertEqual(body["sources"]["pagespeed"]["state"], "not_configured")
        self.assertEqual(body["sources"]["claude"]["state"], "not_configured")
        self.usage.assert_not_called()
        # De bewaarde quick wins blijven bruikbaar.
        self.assertEqual([(k["keyword"], k["source"]) for k in body["keywords"]], [("linkbuilding", "ahrefs")])

    def test_failing_sources_do_not_break_the_proposal(self):
        self.organic.return_value = ("error", [], "Posities niet opgehaald uit ProRankTracker: 500")
        self.usage.side_effect = AhrefsServiceError("Ongeldige sleutel", code="unauthorized")
        self.store_quick_wins([_qw("linkbuilding")])
        response = self.get()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["sources"]["prt"],
                         {"state": "error", "message": "Posities niet opgehaald uit ProRankTracker: 500"})
        self.assertEqual(body["sources"]["ahrefs"]["state"], "error")
        self.assertIn("Ongeldige sleutel", body["sources"]["ahrefs"]["message"])
        self.assertEqual([k["keyword"] for k in body["keywords"]], ["linkbuilding"])

    def test_unexpected_exception_in_source(self):
        self.organic.side_effect = RuntimeError("boem")
        body = self.get().json()
        self.assertEqual(body["sources"]["prt"]["state"], "error")
        self.assertEqual(body["keywords"], [])

    def test_slow_source_times_out(self):
        self._patch(proposal, "SOURCE_TIMEOUT_SECONDS", 0.05)
        self.usage.side_effect = lambda: time.sleep(0.5) or USAGE
        started = time.monotonic()
        body = self.get().json()
        self.assertLess(time.monotonic() - started, 0.4)
        self.assertEqual(body["sources"]["ahrefs"],
                         {"state": "error", "message": proposal.MESSAGES["ahrefs_timeout"]})
        self.assertEqual(body["sources"]["prt"]["state"], "ok")

    def test_unknown_customer_is_404(self):
        response = self.client.get("/api/competitor-analyses/customers/onbekend/proposal")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Klant niet gevonden.")


if __name__ == "__main__":
    unittest.main()
