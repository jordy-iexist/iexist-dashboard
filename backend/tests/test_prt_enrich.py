"""ProRankTracker (AI-zichtbaarheid): site-match, snapshot, promptdetail en de endpoint."""
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import require_user_id
from app.db.models import CustomerCategory, CustomerWebsite, LaunchScan
from app.db.session import get_db
from app.features.launch_checklist.router import router as main_router
from app.features.launch_checklist.services import prt_enrich
from app.services.proranktracker import client as prt_client
from app.services.proranktracker.client import ProRankTrackerServiceError

SETTINGS = SimpleNamespace(proranktracker_api_token="test-token", proranktracker_request_timeout_seconds=5.0)
NO_TOKEN = SimpleNamespace(proranktracker_api_token="", proranktracker_request_timeout_seconds=5.0)
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)

OVERVIEW = {"count": 60, "urls": [
    {"url_id": 11, "url": "http://vhsverhuur.nl", "prompts": []},
    {"url_id": 12, "url": "http://shop.klant.nl", "prompts": []},
    {"url_id": 13, "url": "http://klant.nl.anders.com", "prompts": []},
    {"url_id": 7, "url": "http://klant.nl", "prompts": []},
]}


def _status(**statuses):
    out = {p: {"status": "", "count": 0} for p in ("aio", "aim", "chatgpt", "copilot", "gemini", "grok", "perplexity")}
    for platform, value in statuses.items():
        status, count = value
        out[platform] = {"status": status, "count": count}
    return out


REPORT = {
    "summary_cards": {
        "appearances": {"value": 40, "platforms": {"aio": 10, "aim": 8, "chatgpt": 12, "copilot": 0, "gemini": 5,
                                                   "perplexity": 5, "grok": 0}},
        "mentions": {"value": 25, "platforms": {"aio": 6, "aim": 4, "chatgpt": 8, "copilot": 0, "gemini": 3,
                                                "perplexity": 4}},
        "links": {"value": 12, "average": 3.1, "platforms": {"aio": {"count": 4, "avg": 2.5},
                                                             "chatgpt": {"count": 3, "avg": 1.0}}},
        "visibility": {"value": 58.3, "platforms": {"aio": 70, "aim": 45, "chatgpt": 60, "copilot": 0,
                                                    "gemini": 30, "perplexity": 80, "grok": 0}},
    },
    "urls": [{
        "url_id": 7, "url": "http://klant.nl",
        "prompts": [
            {"prompt_id": 101, "prompt": "beste koffiekar huren", "location": "Netherlands", "lang": "nl",
             "appearances": 3, "visibility": 75, "mentions": 2, "links": 1,
             "platforms": _status(aio=("shown", 2), aim=("not_shown", 0), chatgpt=("shown", 1)),
             "trend": [50, 60, "x", 75]},
            {"prompt_id": 102, "prompt": "koffie op evenement", "location": None, "lang": "nl",
             "appearances": 1, "visibility": 40, "mentions": 1, "links": 0,
             "platforms": _status(aio=("not_shown", 0), chatgpt=("shown", 1), copilot=("not_added", 0)),
             "trend": []},
        ],
    }],
}


def _router(requests=None, overview=OVERVIEW, report=REPORT):
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        assert request.method == "GET"
        data = report if "url_id" in request.url.params else overview
        return httpx.Response(200, json={"result": "success", "data": data})
    return httpx.Client(transport=httpx.MockTransport(handler))


def _record(engine, ai_type, prompt_id=101, rank=1, **ai):
    return {"engine": engine, "ai_type": ai_type, "rank": rank, "name": "beste koffiekar huren", "url_id": 7,
            "url_term_id": 900, "ai": {"visibility_id": str(prompt_id), **ai}}


RECORDS = [
    _record("AIO", "mentions", rank=2, total=2, count={"Klant": "1", "Concurrent": "2"},
            full=[{"b": "Klant", "s": "Klant verhuurt koffiekarren."}]),
    _record("AIO", "links", rank="1", total=3, answer_text="Volgens AI Overviews ...", full=[
        {"url": "https://www.klant.nl/koffiekar#is_link", "title": "Koffiekar", "rank": "1",
         "checkdatetime": "2026-11-16 00:10:02"},
        {"url": "https://bron.nl/artikel#is_citation", "title": "", "rank": "NTH"},
        {"url": "https://andere.nl/pagina#anker", "rank": "3"},
    ]),
    _record("ChatGPT", "mentions", rank=101, total=0),
    _record("ChatGPT", "links", rank="NTH", ai_type_extra=None),
    _record("Gemini", "mentions", rank="101", total=0),
    # Ander prompt-id met dezelfde tekst: hoort niet bij deze prompt.
    _record("Copilot", "mentions", prompt_id=999, total=5, full=[{"b": "Fout", "s": "Niet tonen."}]),
    _record("Grok", "mentions"),
]


class ResolveUrlTests(unittest.TestCase):
    def test_host_match_ignores_scheme_and_www(self):
        urls = OVERVIEW["urls"]
        for base in ("https://www.klant.nl/", "http://klant.nl", "https://klant.nl/pad", "klant.nl"):
            self.assertEqual(prt_enrich.resolve_url(base, urls)["url_id"], 7, base)
        self.assertEqual(prt_enrich.resolve_url("https://www.vhsverhuur.nl", urls)["url_id"], 11)

    def test_exact_host_not_contains(self):
        urls = [u for u in OVERVIEW["urls"] if u["url_id"] != 7]
        self.assertIsNone(prt_enrich.resolve_url("https://www.klant.nl", urls))  # geen subdomein, geen 'bevat'
        self.assertIsNone(prt_enrich.resolve_url("https://klant.nl", [{"url_id": 1, "url": "http://www.klant.com"}]))
        self.assertIsNone(prt_enrich.resolve_url("", OVERVIEW["urls"]))


class CollectTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(prt_client, "settings", SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = patch.object(prt_client.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_ok_snapshot(self):
        requests = []
        snap = prt_enrich.collect("https://www.klant.nl/", client=_router(requests))

        self.assertEqual([dict(r.url.params) for r in requests],
                         [{"per_page": "10000"}, {"per_page": "10000", "url_id": "7"}])
        self.assertEqual(snap["state"], "ok")
        self.assertIsNone(snap["message"])
        self.assertEqual((snap["url_id"], snap["url"]), (7, "http://klant.nl"))
        self.assertEqual(snap["totals"], {"visibility": 58.3, "appearances": 40, "mentions": 25, "links": 12,
                                          "links_avg": 3.1, "prompts": 2})
        self.assertEqual(set(snap["platforms"]), set(prt_enrich.PLATFORMS))
        self.assertNotIn("grok", snap["platforms"])
        aio = snap["platforms"]["aio"]
        self.assertEqual(aio, {"visibility": 70, "appearances": 10, "mentions": 6, "links": 4, "links_avg": 2.5,
                               "prompts_tracked": 2, "prompts_shown": 1})
        self.assertEqual(snap["platforms"]["chatgpt"]["prompts_shown"], 2)
        # Geen enkele prompt getrackt op Copilot (alleen ""/"not_added"): score None, niet 0.
        copilot = snap["platforms"]["copilot"]
        self.assertIsNone(copilot["visibility"])
        self.assertEqual((copilot["prompts_tracked"], copilot["links"], copilot["links_avg"]), (0, 0, None))
        self.assertIsNone(snap["platforms"]["perplexity"]["visibility"])

        first = snap["prompts"][0]
        self.assertEqual(first["prompt_id"], 101)
        self.assertEqual(first["platforms"]["aio"], {"status": "shown", "count": 2})
        self.assertEqual(first["platforms"]["gemini"], {"status": "not_added", "count": 0})  # "" → not_added
        self.assertNotIn("grok", first["platforms"])
        self.assertEqual(first["trend"], [50, 60, 75])
        self.assertIsNone(snap["prompts"][1]["location"])
        self.assertEqual(snap["errors"], [])

    def test_not_tracked(self):
        snap = prt_enrich.collect("https://www.example-not-tracked.nl", client=_router())
        self.assertEqual(snap["state"], "not_tracked")
        self.assertIn("niet getrackt", snap["message"])
        self.assertIsNone(snap["totals"])
        self.assertIsNone(snap["platforms"])
        self.assertEqual(snap["prompts"], [])

    def test_not_configured_makes_no_request(self):
        def handler(request):
            raise AssertionError("geen request zonder token")

        with patch.object(prt_client, "settings", NO_TOKEN):
            snap = prt_enrich.collect("https://klant.nl", client=httpx.Client(transport=httpx.MockTransport(handler)))
        self.assertEqual(snap["state"], "not_configured")
        self.assertIn("PRORANKTRACKER_API_X_TOKEN", snap["message"])

    def test_api_errors_become_error_state(self):
        unauthorized = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
        snap = prt_enrich.collect("https://klant.nl", client=unauthorized)
        self.assertEqual(snap["state"], "error")
        self.assertIn("ProRankTracker", snap["message"])
        self.assertEqual(len(snap["errors"]), 1)
        self.assertIsNone(snap["platforms"])

        result_error = httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"result": "error", "error_message": "Kapot"})))
        snap = prt_enrich.collect("https://klant.nl", client=result_error)
        self.assertEqual(snap["state"], "error")
        self.assertIn("Kapot", snap["message"])

        weird = httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"result": "success", "data": {"urls": "geen lijst"}})))
        self.assertEqual(prt_enrich.collect("https://klant.nl", client=weird)["state"], "not_tracked")


class PromptDetailTests(unittest.TestCase):
    def setUp(self):
        with patch.object(prt_client, "settings", SETTINGS):
            self.snapshot = prt_enrich.collect("https://klant.nl", client=_router())

    def detail(self, records=RECORDS, prompt_id=101):
        seen = {}

        def fake(url_id, prompt, *, client=None):
            seen["args"] = (url_id, prompt)
            return records

        with patch.object(prt_client, "prompt_records", side_effect=fake):
            result = prt_enrich.prompt_detail(self.snapshot, prompt_id)
        return result, seen

    def test_detail_per_platform(self):
        detail, seen = self.detail()
        self.assertEqual(seen["args"], (7, "beste koffiekar huren"))
        self.assertEqual((detail["prompt_id"], detail["prompt"], detail["url"]),
                         (101, "beste koffiekar huren", "http://klant.nl"))
        self.assertTrue(detail["fetched_at"])
        self.assertEqual([p["platform"] for p in detail["platforms"]],
                         ["aio", "aim", "chatgpt", "gemini", "copilot", "perplexity"])
        self.assertEqual([p["label"] for p in detail["platforms"]],
                         ["AI Overviews", "AI Mode", "ChatGPT", "Gemini", "Copilot", "Perplexity"])
        by = {p["platform"]: p for p in detail["platforms"]}

        aio = by["aio"]
        self.assertTrue(aio["tracked"])
        self.assertEqual(aio["mentions"], {"rank": 2, "total": 2, "counts": {"Klant": 1, "Concurrent": 2},
                                           "items": [{"brand": "Klant", "sentence": "Klant verhuurt koffiekarren."}]})
        self.assertEqual(aio["answer_text"], "Volgens AI Overviews ...")
        self.assertEqual(aio["links"]["rank"], 1)
        self.assertEqual(aio["links"]["total"], 3)
        own, citation, other = aio["links"]["items"]
        self.assertEqual(own, {"url": "https://www.klant.nl/koffiekar", "title": "Koffiekar", "rank": 1,
                               "kind": "link", "checked_at": "2026-11-16 00:10:02", "is_own": True})
        self.assertEqual((citation["url"], citation["kind"], citation["title"], citation["rank"], citation["is_own"]),
                         ("https://bron.nl/artikel", "citation", None, None, False))
        self.assertEqual((other["url"], other["kind"]), ("https://andere.nl/pagina#anker", None))

        # rank 101 / "101" / "NTH" = niet gevonden
        self.assertIsNone(by["chatgpt"]["mentions"]["rank"])
        self.assertIsNone(by["chatgpt"]["links"]["rank"])
        self.assertEqual(by["chatgpt"]["links"]["items"], [])  # ontbrekende ai-velden
        self.assertIsNone(by["chatgpt"]["answer_text"])
        self.assertIsNone(by["gemini"]["mentions"]["rank"])
        self.assertTrue(by["gemini"]["tracked"])

        # Copilot-record met een ander visibility_id telt niet; AI Mode had geen records.
        for platform in ("copilot", "aim", "perplexity"):
            p = by[platform]
            self.assertFalse(p["tracked"], platform)
            self.assertEqual(p["mentions"], {"rank": None, "total": 0, "counts": {}, "items": []})
            self.assertEqual(p["links"], {"rank": None, "total": 0, "items": []})
            self.assertIsNone(p["answer_text"])

    def test_unknown_prompt_or_snapshot(self):
        with patch.object(prt_client, "prompt_records", side_effect=AssertionError("geen call")):
            self.assertIsNone(prt_enrich.prompt_detail(self.snapshot, 555))
            self.assertIsNone(prt_enrich.prompt_detail(prt_enrich.empty_snapshot("not_tracked"), 101))
            self.assertIsNone(prt_enrich.prompt_detail(None, 101))


class PromptEndpointTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        for model in (CustomerCategory, CustomerWebsite, LaunchScan):
            model.__table__.create(engine)
        self.Session = sessionmaker(bind=engine)
        with patch.object(prt_client, "settings", SETTINGS):
            self.snapshot = prt_enrich.collect("https://klant.nl", client=_router())

        app = FastAPI()
        app.include_router(main_router)

        def override_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_user_id] = lambda: "user-1"
        self.client = TestClient(app)

    def scan(self, proranktracker):
        scan_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(LaunchScan(id=scan_id, customer_website_id="c1", phase=1, status="completed",
                              base_url="https://klant.nl/", created_by="user-1", created_at=NOW, updated_at=NOW,
                              proranktracker=proranktracker))
            db.commit()
        return scan_id

    def url(self, scan_id, prompt_id):
        return f"/api/launch-checklist/scans/{scan_id}/proranktracker/prompts/{prompt_id}"

    def test_ok(self):
        scan_id = self.scan(self.snapshot)
        with patch.object(prt_client, "prompt_records", return_value=RECORDS):
            r = self.client.get(self.url(scan_id, 101))
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(len(data["platforms"]), 6)
        self.assertEqual(data["platforms"][0]["links"]["items"][0]["kind"], "link")

        detail = self.client.get(f"/api/launch-checklist/scans/{scan_id}").json()
        self.assertEqual(detail["proranktracker"]["state"], "ok")

    def test_not_found_cases(self):
        self.assertEqual(self.client.get(self.url("bestaat-niet", 101)).status_code, 404)
        old = self.scan(None)
        self.assertEqual(self.client.get(self.url(old, 101)).status_code, 404)
        untracked = self.scan(prt_enrich.empty_snapshot("not_tracked"))
        self.assertEqual(self.client.get(self.url(untracked, 101)).status_code, 404)
        scan_id = self.scan(self.snapshot)
        r = self.client.get(self.url(scan_id, 555))
        self.assertEqual(r.status_code, 404)
        self.assertIn("Prompt niet gevonden", r.json()["detail"])

    def test_prt_failure_is_502(self):
        scan_id = self.scan(self.snapshot)
        error = ProRankTrackerServiceError("ProRankTracker is tijdelijk niet beschikbaar (HTTP 503).")
        with patch.object(prt_client, "prompt_records", side_effect=error):
            r = self.client.get(self.url(scan_id, 101))
        self.assertEqual(r.status_code, 502)
        self.assertIn("ProRankTracker-data niet opgehaald", r.json()["detail"])


class EnrichHookTests(unittest.TestCase):
    def test_only_error_state_warns(self):
        from app.features.launch_checklist.worker import launch_scan

        for state, warns in (("ok", False), ("not_configured", False), ("not_tracked", False), ("error", True)):
            warnings = []
            snap = prt_enrich.empty_snapshot(state, "Kapot" if state == "error" else None)
            with patch.object(prt_enrich, "collect", return_value=snap):
                self.assertIs(launch_scan._enrich_with_proranktracker("https://klant.nl", warnings), snap)
            self.assertEqual(warnings, ["ProRankTracker: Kapot"] if warns else [], state)

    def test_step_never_fails_the_scan_but_passes_timeouts(self):
        from celery.exceptions import SoftTimeLimitExceeded

        from app.features.launch_checklist.worker import launch_scan

        warnings = []
        with patch.object(prt_enrich, "collect", side_effect=RuntimeError("boem")):
            snap = launch_scan._proranktracker_step("scan-1", "https://klant.nl", warnings)
        self.assertEqual(snap["state"], "error")
        self.assertEqual(warnings, ["ProRankTracker-data niet opgehaald: boem"])
        with patch.object(prt_enrich, "collect", side_effect=SoftTimeLimitExceeded()):
            with self.assertRaises(SoftTimeLimitExceeded):
                launch_scan._proranktracker_step("scan-1", "https://klant.nl", [])


if __name__ == "__main__":
    unittest.main()
