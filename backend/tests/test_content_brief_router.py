"""Endpoints van de content brief (features/competitor_analysis/brief_router.py), het veld
`brief_status` in het analysedetail en de schrijfstijlvelden in het klantprofiel.

In-memory SQLite; de taak (`run_content_brief_task.delay`) en `is_configured` van Claude zijn
vervangen: geen netwerk en geen Celery.
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
from app.db.models import (
    Base,
    CompetitorAnalysis,
    CompetitorAnalysisKeyword,
    ContentBrief,
    CustomerWebsite,
    User,
)
from app.db.session import get_db
from app.features.competitor_analysis import brief_router as router_module
from app.features.competitor_analysis.brief_router import router as brief_router
from app.features.competitor_analysis.router import router as analysis_router
from app.features.competitor_analysis.schemas import ContentBrief as ContentBriefSchema
from app.features.customers import router as customers_module
from app.features.customers.profile import CustomerProfile
from app.features.customers.router import router as customers_router
from app.worker.tasks import run_content_brief_task

USER = "user-1"
BRIEF = {"goal_intent": ["Doel"], "title": "SEO bureau | Klant", "meta_description": "Meta",
         "outline": [{"level": "h1", "text": "SEO bureau"}], "word_count": 1200, "tone_of_voice": None,
         "form_of_address": "je", "internal_links": ["/a/"], "schema_types": ["Service"]}
CONCEPT = {"version": 2, "word_count": 1150,
           "sections": [{"level": "h1", "heading": "SEO bureau", "body": "Tekst.", "review_note": None}],
           "checks": [{"key": "review", "label": "Niets te checken", "ok": True}]}


def _now():
    return datetime.now(timezone.utc)


class _Base(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.customer_id = self.add_customer("klant.nl")
        with self.Session() as db:
            db.add(User(id=USER, email="jan@iexist.nl", password_hash="x", created_at=_now(), updated_at=_now()))
            db.commit()
        self.analysis_id, self.keyword_id = self.add_analysis()

        self.configured = self._patch(router_module.anthropic_client, "is_configured", Mock(return_value=True))
        self.delay = self._patch(run_content_brief_task, "delay", Mock())

        app = FastAPI()
        app.include_router(analysis_router)
        app.include_router(brief_router)
        app.include_router(customers_router)

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

    def add_customer(self, domain):
        customer_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(id=customer_id, name="Klant", base_url=f"https://{domain}/", domain=domain,
                                   created_by=USER, created_at=_now(), updated_at=_now()))
            db.commit()
        return customer_id

    def add_analysis(self, *, keyword="seo bureau", keyword_status="completed", customer_id=None):
        analysis_id, keyword_id = str(uuid.uuid4()), str(uuid.uuid4())
        with self.Session() as db:
            db.add(CompetitorAnalysis(
                id=analysis_id, customer_website_id=customer_id or self.customer_id, created_by=USER,
                status="completed", country="nl", top_n=10, modules=["serp"], total_keywords=1,
                created_at=_now() - timedelta(days=1), updated_at=_now(), completed_at=datetime(2026, 11, 20, 12, 0),
            ))
            db.add(CompetitorAnalysisKeyword(
                id=keyword_id, analysis_id=analysis_id, keyword=keyword, keyword_key=keyword,
                target_url="https://klant.nl/seo/", status=keyword_status, created_at=_now(), updated_at=_now(),
            ))
            db.commit()
        return analysis_id, keyword_id

    def add_brief(self, *, status="completed", brief=BRIEF, concept=CONCEPT, updated_at=None, keyword_id=None,
                  analysis_id=None, customer_id=None):
        brief_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(ContentBrief(
                id=brief_id, keyword_id=keyword_id or self.keyword_id, analysis_id=analysis_id or self.analysis_id,
                customer_website_id=customer_id or self.customer_id, status=status, brief=brief, concept=concept,
                model="claude-sonnet-5-5", ai_usage={"calls": 2, "input_tokens": 1000, "output_tokens": 500,
                                                     "cost_usd": 0.007},
                created_by=USER, created_at=_now(), updated_at=updated_at or _now(),
                completed_at=_now() if status == "completed" else None,
            ))
            db.commit()
        return brief_id

    def url(self, suffix="", keyword_id=None, analysis_id=None):
        return (f"/api/competitor-analyses/analyses/{analysis_id or self.analysis_id}"
                f"/keywords/{keyword_id or self.keyword_id}/brief{suffix}")

    def row(self):
        with self.Session() as db:
            return db.query(ContentBrief).filter(ContentBrief.keyword_id == self.keyword_id).one()


class GetBriefTest(_Base):
    def test_404_without_brief_and_for_unknown_ids(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], router_module.MESSAGES["no_brief"])
        self.assertEqual(self.client.get(self.url(keyword_id="onbekend")).status_code, 404)
        self.assertEqual(self.client.get(self.url(analysis_id="onbekend")).status_code, 404)
        other_analysis, other_keyword = self.add_analysis(keyword="ander")
        self.assertEqual(self.client.get(self.url(keyword_id=other_keyword)).status_code, 404)

    def test_full_brief(self):
        brief_id = self.add_brief()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200, response.text)
        body = ContentBriefSchema.model_validate(response.json())
        self.assertEqual((body.id, body.keyword, body.target_url, body.status), (brief_id, "seo bureau",
                                                                                "https://klant.nl/seo/", "completed"))
        self.assertEqual(body.analysis_date.replace(tzinfo=None), datetime(2026, 11, 20, 12, 0))
        self.assertEqual((body.model, body.ai_usage.calls), ("claude-sonnet-5-5", 2))
        self.assertEqual(body.brief.title, "SEO bureau | Klant")
        self.assertEqual(body.brief.form_of_address, "je")
        self.assertEqual((body.concept.version, body.concept.word_count), (2, 1150))
        self.assertEqual(body.concept.checks[0].key, "review")

    def test_pending_brief_has_empty_parts(self):
        self.add_brief(status="pending", brief=None, concept=None)
        body = self.client.get(self.url()).json()
        self.assertEqual((body["status"], body["brief"], body["concept"]), ("pending", None, None))
        self.assertEqual(body["ai_usage"]["calls"], 2)

    def test_stale_active_brief_becomes_failed(self):
        self.add_brief(status="brief", brief=None, concept=None, updated_at=_now() - timedelta(minutes=16))
        body = self.client.get(self.url()).json()
        self.assertEqual((body["status"], body["error_message"]), ("failed", router_module.MESSAGES["stale"]))
        self.assertEqual(self.row().status, "failed")

    def test_recent_active_brief_stays(self):
        self.add_brief(status="concept", updated_at=_now() - timedelta(minutes=14))
        self.assertEqual(self.client.get(self.url()).json()["status"], "concept")


class StartBriefTest(_Base):
    def test_start_creates_row_and_task(self):
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["status"], body["brief"], body["concept"]), ("pending", None, None))
        self.assertEqual(body["ai_usage"], {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        self.delay.assert_called_once_with(body["id"], concept_only=False)
        row = self.row()
        self.assertEqual((row.analysis_id, row.customer_website_id, row.created_by),
                         (self.analysis_id, self.customer_id, USER))

    def test_400_when_keyword_not_completed(self):
        _, keyword_id = self.add_analysis(keyword_status="pending")
        analysis_id = self._analysis_of(keyword_id)
        response = self.client.post(self.url(keyword_id=keyword_id, analysis_id=analysis_id))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], router_module.MESSAGES["not_completed"])
        self.delay.assert_not_called()

    def _analysis_of(self, keyword_id):
        with self.Session() as db:
            return db.get(CompetitorAnalysisKeyword, keyword_id).analysis_id

    def test_409_when_running_or_completed(self):
        self.add_brief(status="brief", brief=None, concept=None)
        response = self.client.post(self.url())
        self.assertEqual((response.status_code, response.json()["detail"]), (409, router_module.MESSAGES["running"]))
        with self.Session() as db:
            db.query(ContentBrief).update({"status": "completed"})
            db.commit()
        response = self.client.post(self.url())
        self.assertEqual((response.status_code, response.json()["detail"]), (409, router_module.MESSAGES["exists"]))
        self.delay.assert_not_called()

    def test_503_without_claude(self):
        self.configured.return_value = False
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], router_module.MESSAGES["not_configured"])
        with self.Session() as db:
            self.assertEqual(db.query(ContentBrief).count(), 0)

    def test_503_when_queue_unreachable(self):
        self.delay.side_effect = ConnectionError("redis weg")
        with self.assertLogs(router_module.logger, "ERROR"):
            response = self.client.post(self.url())
        self.assertEqual(response.status_code, 503)
        row = self.row()
        self.assertEqual((row.status, row.error_message), ("failed", router_module.MESSAGES["not_queued"]))
        # Opnieuw proberen kan daarna wel.
        self.delay.side_effect = None
        self.assertEqual(self.client.post(self.url()).status_code, 200)

    def test_retry_after_failure_resumes_from_failed_step(self):
        self.add_brief(status="failed", brief=None, concept=None)
        body = self.client.post(self.url()).json()
        self.assertEqual((body["status"], body["error_message"]), ("pending", None))
        self.delay.assert_called_once_with(body["id"], concept_only=False)

        self.delay.reset_mock()
        with self.Session() as db:
            db.query(ContentBrief).update({"status": "failed", "brief": BRIEF, "error_message": "Kapot"})
            db.commit()
        body = self.client.post(self.url()).json()
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["brief"]["title"], "SEO bureau | Klant")
        self.delay.assert_called_once_with(body["id"], concept_only=True)

    def test_stale_brief_is_recovered_and_restarted(self):
        self.add_brief(status="concept", updated_at=_now() - timedelta(minutes=30))
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "pending")


class RegenerateConceptTest(_Base):
    def test_409_without_brief_or_while_running(self):
        response = self.client.post(self.url("/concept"))
        self.assertEqual((response.status_code, response.json()["detail"]), (409, router_module.MESSAGES["no_brief"]))
        self.add_brief(status="concept")
        response = self.client.post(self.url("/concept"))
        self.assertEqual((response.status_code, response.json()["detail"]), (409, router_module.MESSAGES["running"]))
        with self.Session() as db:
            db.query(ContentBrief).update({"status": "failed", "brief": None})
            db.commit()
        response = self.client.post(self.url("/concept"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], router_module.MESSAGES["concept_without_brief"])
        self.delay.assert_not_called()

    def test_regenerate_keeps_brief_and_previous_concept(self):
        brief_id = self.add_brief(status="completed")
        response = self.client.post(self.url("/concept"))
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["brief"]["title"], "SEO bureau | Klant")
        self.assertEqual(body["concept"]["version"], 2)
        self.delay.assert_called_once_with(brief_id, concept_only=True)

    def test_regenerate_after_failed_concept(self):
        self.add_brief(status="failed")
        self.assertEqual(self.client.post(self.url("/concept")).status_code, 200)

    def test_queue_unreachable_keeps_concept(self):
        self.add_brief(status="completed")
        self.delay.side_effect = ConnectionError("redis weg")
        with self.assertLogs(router_module.logger, "ERROR"):
            response = self.client.post(self.url("/concept"))
        self.assertEqual(response.status_code, 503)
        row = self.row()
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.concept["version"], 2)


class BriefListTest(_Base):
    def url_list(self, customer_id=None, **params):
        return f"/api/competitor-analyses/customers/{customer_id or self.customer_id}/briefs"

    def test_empty_list_and_unknown_customer(self):
        response = self.client.get(self.url_list())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": []})
        response = self.client.get(self.url_list("onbekend"))
        self.assertEqual((response.status_code, response.json()["detail"]), (404, "Klant niet gevonden."))

    def test_list_sorted_with_summary_fields_and_recovery(self):
        old = self.add_brief(status="completed", updated_at=_now() - timedelta(hours=2))
        analysis2, keyword2 = self.add_analysis(keyword="seo specialist")
        stale = self.add_brief(status="brief", brief=None, concept=None, keyword_id=keyword2, analysis_id=analysis2,
                               updated_at=_now() - timedelta(minutes=20))
        analysis3, keyword3 = self.add_analysis(keyword="linkbuilding")
        new = self.add_brief(status="pending", brief=None, concept=None, keyword_id=keyword3, analysis_id=analysis3)
        other_customer = self.add_customer("ander.nl")
        analysis4, keyword4 = self.add_analysis(keyword="ander", customer_id=other_customer)
        self.add_brief(keyword_id=keyword4, analysis_id=analysis4, customer_id=other_customer)

        items = self.client.get(self.url_list()).json()["items"]
        # De vastgelopen brief is net hersteld (updated_at nu) en staat daardoor bovenaan.
        self.assertEqual([i["id"] for i in items], [stale, new, old])
        by_id = {i["id"]: i for i in items}
        self.assertEqual((by_id[stale]["status"], by_id[stale]["error_message"]),
                         ("failed", router_module.MESSAGES["stale"]))
        self.assertEqual((by_id[stale]["keyword"], by_id[stale]["title"], by_id[stale]["concept_version"],
                          by_id[stale]["word_count"]), ("seo specialist", None, None, None))
        done = by_id[old]
        self.assertEqual((done["title"], done["concept_version"], done["word_count"], done["target_url"]),
                         ("SEO bureau | Klant", 2, 1150, "https://klant.nl/seo/"))
        self.assertTrue(done["analysis_date"].startswith("2026-11-20T12:00"))
        self.assertEqual((done["analysis_id"], done["keyword_id"]), (self.analysis_id, self.keyword_id))

        limited = self.client.get(self.url_list(), params={"limit": 1}).json()["items"]
        self.assertEqual([i["id"] for i in limited], [stale])
        self.assertEqual(self.client.get(self.url_list(), params={"limit": 0}).status_code, 422)
        self.assertEqual(self.client.get(self.url_list(), params={"limit": 201}).status_code, 422)


class AnalysisDetailBriefStatusTest(_Base):
    def test_brief_status_per_keyword(self):
        detail = self.client.get(f"/api/competitor-analyses/analyses/{self.analysis_id}").json()
        self.assertIsNone(detail["keywords"][0]["brief_status"])
        self.add_brief(status="concept")
        detail = self.client.get(f"/api/competitor-analyses/analyses/{self.analysis_id}").json()
        self.assertEqual(detail["keywords"][0]["brief_status"], "concept")


class CustomerProfileStyleTest(_Base):
    def test_create_and_update_tone_and_form(self):
        # De klantrouter schrijft ISO-tekst als tijdstip (Postgres slikt dat, SQLite niet).
        self._patch(customers_module, "utc_now_iso", _now)
        response = self.client.post("/api/customers", json={
            "name": "Nieuw", "base_url": "https://nieuw.nl", "tone_of_voice": "  Nuchter.  ", "form_of_address": "u",
        })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["tone_of_voice"], body["form_of_address"]), ("Nuchter.", "u"))
        customer_id = body["id"]

        body = self.client.patch(f"/api/customers/{customer_id}", json={"form_of_address": ""}).json()
        self.assertEqual((body["tone_of_voice"], body["form_of_address"]), ("Nuchter.", None))
        body = self.client.patch(f"/api/customers/{customer_id}", json={"form_of_address": "je",
                                                                         "tone_of_voice": " "}).json()
        self.assertEqual((body["tone_of_voice"], body["form_of_address"]), (None, "je"))
        self.assertEqual(self.client.patch(f"/api/customers/{customer_id}",
                                           json={"form_of_address": "jij"}).status_code, 422)
        detail = self.client.get(f"/api/customers/{customer_id}").json()
        self.assertEqual(detail["form_of_address"], "je")


class CustomerProfileFieldTest(_Base):
    """Het klantprofiel (`profile`) via GET/PATCH /api/customers/{id}; de lijst heeft het niet."""

    def setUp(self):
        super().setUp()
        self._patch(customers_module, "utc_now_iso", _now)
        self.detail_url = f"/api/customers/{self.customer_id}"

    def test_detail_without_profile_gives_empty_profile(self):
        body = self.client.get(self.detail_url).json()
        self.assertEqual(body["profile"], CustomerProfile().model_dump())
        self.assertEqual(body["profile"]["services"], [])

    def test_save_and_read_back(self):
        response = self.client.patch(self.detail_url, json={"profile": {
            "company_type": "  SEO-bureau ", "usps": ["Snel", "", "snel", "Eerlijk"],
            "services": [{"name": "SEO-traject", "price": "vanaf € 750 per maand"}, {"name": "", "price": "€ 1"}],
            "onbekend": "weg",
        }})
        self.assertEqual(response.status_code, 200, response.text)
        profile = response.json()["profile"]
        self.assertEqual(profile["company_type"], "SEO-bureau")
        self.assertEqual(profile["usps"], ["Snel", "Eerlijk"])
        self.assertEqual(profile["services"], [{"name": "SEO-traject", "price": "vanaf € 750 per maand"}])
        self.assertNotIn("onbekend", profile)
        self.assertEqual(set(profile), set(CustomerProfile.model_fields))

        detail = self.client.get(self.detail_url).json()
        self.assertEqual(detail["profile"], profile)
        with self.Session() as db:
            self.assertEqual(db.get(CustomerWebsite, self.customer_id).profile["usps"], ["Snel", "Eerlijk"])

    def test_patch_without_profile_leaves_it_and_null_clears_it(self):
        self.client.patch(self.detail_url, json={"profile": {"team": "Jan"}})
        body = self.client.patch(self.detail_url, json={"tone_of_voice": "Warm."}).json()
        self.assertEqual((body["tone_of_voice"], body["profile"]["team"]), ("Warm.", "Jan"))
        # Een nieuw object vervangt het hele profiel.
        body = self.client.patch(self.detail_url, json={"profile": {"usps": ["Snel"]}}).json()
        self.assertEqual((body["profile"]["team"], body["profile"]["usps"]), ("", ["Snel"]))

        body = self.client.patch(self.detail_url, json={"profile": None}).json()
        self.assertEqual(body["profile"], CustomerProfile().model_dump())
        with self.Session() as db:
            self.assertIsNone(db.get(CustomerWebsite, self.customer_id).profile)

    def test_wrong_type_is_422(self):
        response = self.client.patch(self.detail_url, json={"profile": {"usps": 5}})
        self.assertEqual(response.status_code, 422)

    def test_create_with_profile_in_one_step(self):
        response = self.client.post("/api/customers", json={
            "name": "Nieuw", "base_url": "https://nieuw-met-profiel.nl", "form_of_address": "je",
            "profile": {"company_type": " Bakkerij ", "usps": ["Vers", "vers", ""],
                        "services": [{"name": "Taart", "price": "vanaf € 25"}]},
        })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["profile"]["company_type"], "Bakkerij")
        self.assertEqual(body["profile"]["usps"], ["Vers"])
        self.assertEqual(body["profile"]["services"], [{"name": "Taart", "price": "vanaf € 25"}])
        detail = self.client.get(f"/api/customers/{body['id']}").json()
        self.assertEqual(detail["profile"], body["profile"])

    def test_create_without_or_with_empty_profile_stores_none(self):
        for index, extra in enumerate(({}, {"profile": {}}, {"profile": {"usps": [" "]}})):
            response = self.client.post("/api/customers", json={
                "name": f"Leeg {index}", "base_url": f"https://leeg-{index}.nl", **extra,
            })
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["profile"], CustomerProfile().model_dump())
            with self.Session() as db:
                self.assertIsNone(db.get(CustomerWebsite, body["id"]).profile)

    def test_list_has_no_profile(self):
        self.client.patch(self.detail_url, json={"profile": {"team": "Jan"}})
        websites = self.client.get("/api/customers").json()["websites"]
        self.assertTrue(websites)
        self.assertTrue(all("profile" not in w for w in websites))


if __name__ == "__main__":
    unittest.main()
