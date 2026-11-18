"""Analytics (livegang): extractor, trend, scan A/B, benchmark en compare_rankings(until=).

De endpoint-tests draaien tegen een SQLite-database met alleen de benodigde tabellen,
nooit tegen de echte Postgres. SQLite controleert ook de JSON-subpad-projectie.
"""
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import require_user_id
from app.db.models import (
    CustomerCategory,
    CustomerWebsite,
    LaunchChecklistState,
    LaunchScan,
    LaunchScanPage,
    LaunchSitemapSnapshot,
    SerpScanResult,
    WebsiteKeyword,
)
from app.db.session import get_db
from app.features.launch_checklist import analytics_router as analytics_router_module
from app.features.launch_checklist.analytics_router import router as analytics_router
from app.features.launch_checklist.services import quarterly_compare
from app.features.launch_checklist.router import router as main_router
from app.features.launch_checklist.services import analytics
from app.features.launch_checklist.services.analytics import ScanSnapshot, extract_metrics
from app.features.launch_checklist.services.geo_checklist import ITEMS as GEO_ITEMS
from app.features.launch_checklist.services.issues import ISSUE_TYPES
from app.features.launch_checklist.services.quarterly_compare import (
    compare_ai,
    compare_issues,
    compare_rankings,
    count_issue_types,
    count_issues_by_type,
)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def stats(by_type=None, *, ruleset=None, cwv_measured=10, total_urls=20):
    out = {
        "total_urls": total_urls,
        "html_pages": 10,
        "indexable": 8,
        "missing_title": 1,
        "missing_meta": 2,
        "missing_h1": 0,
        "broken_link_pages": 3,
        "images_missing_alt": 4,
        "avg_response_ms": 450,
        "redirects": 2,
        "final_4xx": 1,
        "cwv": {
            "measured": cwv_measured,
            "good": 4 if cwv_measured else 0,
            "needs_improvement": 0,
            "poor": 6 if cwv_measured else 0,
            "avg_performance_score": 71 if cwv_measured else None,
        },
        "issues": {"total": sum((by_type or {}).values()), "by_type": by_type or {}},
    }
    if ruleset is not None:
        out["ruleset"] = ruleset
    if by_type is None:
        del out["issues"]["by_type"]
    return out


AI = {"score": 75, "checks": [
    {"key": "robots_txt", "label": "robots.txt", "status": "ok", "message": "", "details": None},
    {"key": "llms_txt", "label": "llms.txt", "status": "warning", "message": "", "details": None},
    {"key": "sitemap", "label": "Sitemap", "status": "error", "message": "", "details": None},
]}
AI_LATER = {"score": 100, "checks": [
    {"key": "robots_txt", "label": "robots.txt", "status": "ok", "message": "", "details": None},
    {"key": "llms_txt", "label": "llms.txt", "status": "ok", "message": "", "details": None},
    {"key": "sitemap", "label": "Sitemap", "status": "ok", "message": "", "details": None},
]}
AHREFS = {"fetched_at": "2026-10-01T10:00:00+00:00", "reused_from": None, "errors": [],
          "domain": {"domain_rating": 40, "refdomains": 100, "backlinks": 1000, "org_traffic": 50,
                     "org_keywords": 30, "org_keywords_1_3": 3}, "lost_value_urls": 2}
GSC = {"property": "sc-domain:klant.nl", "fetched_at": "2026-11-15T10:00:00+00:00",
       "period": {"start": "2026-08-15", "end": "2026-11-12", "days": 90},
       "totals": {"clicks": 120, "impressions": 4000, "ctr": 0.03, "position": 12.5},
       "errors": [], "queries": [{"query": "zwaar", "clicks": 1}],
       "inspection": {"requested": 10, "eligible": 10, "checked": 8, "indexed": 6, "rows": [{"url": "x"}]}}
BING = {"state": "ok", "period": {"start": "2026-08-15", "end": "2026-11-12"},
        "totals": {"clicks": 7, "impressions": 300, "ctr": 0.0233}, "crawl": {"in_index": 55, "date": "2026-11-12"},
        "queries": [{"query": "zwaar"}]}
# Zoals `snapshot_from_row` de Bing-kolom projecteert (crawl.in_index -> in_index).
BING_PROJECTED = {"state": "ok", "period": BING["period"], "totals": BING["totals"], "in_index": 55}


def _prt_platform(visibility, tracked=3, shown=2):
    return {"visibility": visibility, "appearances": shown, "mentions": shown, "links": 1, "links_avg": 2.0,
            "prompts_tracked": tracked, "prompts_shown": shown}


PRT = {"state": "ok", "message": None, "fetched_at": "2026-09-01T10:00:00+00:00", "url_id": 7,
       "url": "http://klant.nl",
       "totals": {"visibility": 58.3, "appearances": 40, "mentions": 25, "links": 12, "links_avg": 3.1,
                  "prompts": 20},
       "platforms": {"aio": _prt_platform(70), "aim": _prt_platform(45.5), "chatgpt": _prt_platform(60),
                     "gemini": _prt_platform(30), "copilot": _prt_platform(None, tracked=0, shown=0),
                     "perplexity": _prt_platform(80)},
       "prompts": [{"prompt_id": 1, "prompt": "beste koffiekar", "platforms": {}, "trend": [50, 60]}],
       "errors": []}
# Zoals `snapshot_from_row` de kolom projecteert: zonder promptlijst.
PRT_PROJECTED = {"state": "ok", "totals": PRT["totals"], "platforms": PRT["platforms"]}


def snapshot(**kw):
    base = dict(
        id=str(uuid.uuid4()), customer_id="c1", phase=1, status="completed", period=None,
        created_at=NOW, completed_at=NOW, summary_stats=stats({"title_missing": 1}),
        ai_checks=None, ahrefs=None, search_console=None, bing_webmaster=None,
    )
    base.update(kw)
    return ScanSnapshot(**base)


class ExtractorTest(unittest.TestCase):
    def test_phase4_cwv_is_none_not_zero(self):
        s4 = snapshot(phase=4, period="2026-Q4", summary_stats=stats({}, cwv_measured=0))
        values = extract_metrics(s4)
        for key in ("cwv_good_pct", "cwv_poor", "cwv_performance_score"):
            self.assertIsNone(values[key])
        self.assertEqual(analytics.scan_sources(s4)["cwv"], "not_measured")

        s1 = snapshot(phase=1, summary_stats=stats({}, cwv_measured=10))
        values = extract_metrics(s1)
        self.assertEqual(values["cwv_good_pct"], 40.0)
        self.assertEqual(values["cwv_poor"], 6)
        self.assertEqual(values["cwv_performance_score"], 71)
        self.assertEqual(analytics.scan_sources(s1)["cwv"], "ok")

    def test_issue_counts_exclude_c4_and_cwv(self):
        by_type = {"title_missing": 2, "slow_response": 1, "c4_ai_scan": 1, "c4_search_console": 1,
                   "cwv_lcp": 3, "cwv_page_weight": 2}
        values = extract_metrics(snapshot(phase=4, period="2026-Q4", summary_stats=stats(by_type, cwv_measured=0)))
        self.assertEqual(values["issues_comparable"], 3)
        self.assertEqual(values["issues_new_checks"], 0)
        self.assertEqual(values["issues_cat_on-page"], 2)
        self.assertEqual(values["issues_cat_performance"], 1)
        # zelfde regel als de opgeslagen fase 4-vergelijking
        issue_list = [t for t, n in by_type.items() for _ in range(n)]
        self.assertEqual(count_issues_by_type(by_type), count_issue_types(issue_list))

    def test_ruleset_floor_moves_newer_types_to_new_checks(self):
        s = snapshot(summary_stats=stats({"thin_content": 4, "title_missing": 2}, ruleset=2))
        self.assertEqual(
            (extract_metrics(s)["issues_comparable"], extract_metrics(s)["issues_new_checks"]), (6, 0))
        floor1 = extract_metrics(s, ruleset_floor=1)
        self.assertEqual((floor1["issues_comparable"], floor1["issues_new_checks"]), (2, 4))
        self.assertEqual(floor1["issues_cat_content"], 0)  # categorieën tellen alleen vergelijkbare types
        floor2 = extract_metrics(s, ruleset_floor=2)
        self.assertEqual((floor2["issues_comparable"], floor2["issues_new_checks"]), (6, 0))
        self.assertEqual(analytics.ruleset_floor([s, snapshot()]), 1)  # zonder stempel = 1

    def test_missing_by_type_gives_none(self):
        values = extract_metrics(snapshot(summary_stats=stats(None)))
        self.assertIsNone(values["issues_comparable"])
        self.assertIsNone(values["issues_new_checks"])
        self.assertTrue(all(values[f"issues_cat_{c}"] is None for c in analytics.ISSUE_CATEGORIES))
        self.assertEqual(values["pages_total"], 20)  # de rest blijft gewoon gevuld
        self.assertIsNone(extract_metrics(snapshot(summary_stats=None))["pages_total"])

    def test_category_metrics_cover_issue_types(self):
        categories = {meta["category"] for meta in ISSUE_TYPES.values()}
        self.assertEqual({f"issues_cat_{c}" for c in categories},
                         {k for k, m in analytics.METRICS.items() if m.group == "issues_category"})

    def test_sources_and_percentages(self):
        s = snapshot(phase=4, period="2026-Q4", summary_stats=stats({}, cwv_measured=0), ai_checks=AI,
                     ahrefs={**AHREFS, "reused_from": "older"}, search_console=GSC, bing_webmaster=BING_PROJECTED)
        values = extract_metrics(s)
        self.assertEqual(values["gsc_ctr"], 3.0)  # fractie 0.03 -> 3 %
        self.assertEqual(values["gsc_indexed_pct"], 75.0)
        self.assertEqual(values["gsc_position"], 12.5)
        self.assertEqual(values["bing_in_index"], 55)
        self.assertEqual(values["indexable_pct"], 80.0)
        self.assertEqual((values["ai_checks_ok"], values["ai_checks_warning"], values["ai_checks_error"]), (1, 1, 1))
        self.assertEqual(values["domain_rating"], 40)
        self.assertEqual(analytics.scan_sources(s),
                         {"ahrefs": "reused", "search_console": "ok", "bing": "ok",
                          "proranktracker": "not_measured", "cwv": "not_measured"})

        s1 = snapshot(phase=1, ahrefs=AHREFS, search_console=GSC)
        self.assertIsNone(extract_metrics(s1)["gsc_clicks"])  # fase 1 meet geen GSC
        self.assertEqual(analytics.scan_sources(s1)["search_console"], "not_measured")
        self.assertEqual(analytics.scan_sources(s1)["ahrefs"], "ok")

        bare = snapshot(phase=4, period="2026-Q4", bing_webmaster={"state": "site_not_linked"})
        self.assertEqual(analytics.scan_sources(bare),
                         {"ahrefs": "not_connected", "search_console": "not_connected",
                          "bing": "not_connected", "proranktracker": "not_measured", "cwv": "ok"})
        self.assertIsNone(extract_metrics(bare)["bing_clicks"])
        broken = snapshot(phase=4, period="2026-Q4", bing_webmaster={"state": "token_expired"},
                          search_console={"property": "x", "totals": None, "errors": ["fout"]},
                          ahrefs={"domain": {}, "errors": ["unauthorized"]},
                          proranktracker={"state": "error", "totals": None, "platforms": None})
        self.assertEqual({k: v for k, v in analytics.scan_sources(broken).items() if k != "cwv"},
                         {"ahrefs": "error", "search_console": "error", "bing": "error",
                          "proranktracker": "error"})

    def test_proranktracker_metrics(self):
        prt_keys = {k for k, m in analytics.METRICS.items() if m.group == "prt"}
        platforms = ("aio", "aim", "chatgpt", "gemini", "copilot", "perplexity")
        self.assertEqual(prt_keys, {"prt_visibility", "prt_appearances", "prt_mentions", "prt_links",
                                    "prt_prompts"} | {f"prt_visibility_{p}" for p in platforms})
        self.assertTrue(all(analytics.METRICS[k].phases == (1, 4) for k in prt_keys))
        self.assertIsNone(analytics.METRICS["prt_prompts"].higher_is_better)
        self.assertEqual(analytics.METRICS["prt_visibility_chatgpt"].label, "AI-zichtbaarheid ChatGPT")
        self.assertEqual(analytics.METRICS["prt_visibility"].as_dict()["group_label"],
                         "AI-zichtbaarheid (ProRankTracker)")

        for phase, period in ((1, None), (4, "2026-Q4")):
            s = snapshot(phase=phase, period=period, proranktracker=PRT_PROJECTED)
            values = extract_metrics(s)
            self.assertEqual(values["prt_visibility"], 58.3)
            self.assertEqual((values["prt_appearances"], values["prt_mentions"], values["prt_links"],
                              values["prt_prompts"]), (40, 25, 12, 20))
            self.assertEqual(values["prt_visibility_aim"], 45.5)
            self.assertIsNone(values["prt_visibility_copilot"])  # geen getrackte prompts: None, niet 0
            self.assertEqual(analytics.scan_sources(s)["proranktracker"], "ok")

        for state in ("not_configured", "not_tracked"):
            s = snapshot(proranktracker={"state": state, "totals": None, "platforms": None})
            self.assertEqual(analytics.scan_sources(s)["proranktracker"], "not_connected")
            self.assertTrue(all(extract_metrics(s)[k] is None for k in prt_keys))

        old = snapshot()  # scan van vóór de koppeling
        self.assertEqual(analytics.scan_sources(old)["proranktracker"], "not_measured")
        self.assertTrue(all(extract_metrics(old)[k] is None for k in prt_keys))
        # Fase 2 hoort niet op de tijdlijn, ook niet met een snapshot.
        self.assertIsNone(extract_metrics(snapshot(phase=2, proranktracker=PRT_PROJECTED))["prt_visibility"])

    def test_is_primary_per_phase_and_period(self):
        q4_old = snapshot(phase=4, period="2026-Q4", created_at=NOW - timedelta(days=3))
        q4_new = snapshot(phase=4, period="2026-Q4", created_at=NOW - timedelta(days=1))
        q3 = snapshot(phase=4, period="2026-Q3", created_at=NOW - timedelta(days=60))
        p1_old = snapshot(phase=1, created_at=datetime(2026, 10, 2, tzinfo=timezone.utc))
        p1_new = snapshot(phase=1, created_at=datetime(2026, 11, 2, tzinfo=timezone.utc))
        p1_q3 = snapshot(phase=1, created_at=datetime(2026, 8, 2, tzinfo=timezone.utc))
        primary = analytics.primary_scan_ids([q4_old, q4_new, q3, p1_old, p1_new, p1_q3])
        self.assertEqual(primary, {q4_new.id, q3.id, p1_new.id, p1_q3.id})
        self.assertEqual(analytics.scan_period(p1_q3), "2026-Q3")
        self.assertEqual(analytics.scan_label(p1_old), "Nulmeting okt 2026")
        self.assertEqual(analytics.scan_label(q3), "Q3 2026")

    def test_summarize(self):
        self.assertEqual(analytics.summarize([None, 10, 0, 20, 30]),
                         {"median": 15.0, "p25": 7.5, "p75": 22.5, "min": 0, "max": 30, "n": 4})
        self.assertEqual(analytics.summarize([None])["n"], 0)
        self.assertEqual(analytics.summarize([5])["median"], 5)


class _DbTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        for model in (CustomerCategory, CustomerWebsite, LaunchScan, LaunchScanPage, LaunchChecklistState,
                      WebsiteKeyword, SerpScanResult, LaunchSitemapSnapshot):
            model.__table__.create(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)

        app = FastAPI()
        app.include_router(main_router)
        app.include_router(analytics_router)

        def override_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_user_id] = lambda: "user-1"
        self.client = TestClient(app)

    def customer(self, name="Klant"):
        cid = str(uuid.uuid4())
        self.db.add(CustomerWebsite(id=cid, name=name, base_url=f"https://www.{name.lower()}.nl/",
                                    domain=f"{name.lower()}.nl", created_by="user-1", created_at=NOW, updated_at=NOW))
        self.db.commit()
        return cid

    def scan(self, customer_id, *, phase, at, status="completed", period=None, **kw):
        scan = LaunchScan(id=str(uuid.uuid4()), customer_website_id=customer_id, phase=phase, status=status,
                          base_url="https://www.klant.nl/", period=period, created_by="user-1",
                          created_at=at, updated_at=at, completed_at=at + timedelta(minutes=5), **kw)
        self.db.add(scan)
        self.db.commit()
        return scan.id

    def page(self, scan_id, url, status_code=200, **kw):
        self.db.add(LaunchScanPage(id=str(uuid.uuid4()), scan_id=scan_id, url=url, path="/", status_code=status_code,
                                   created_at=NOW, **kw))
        self.db.commit()


class TrendEndpointTest(_DbTest):
    def test_trend(self):
        cid = self.customer()
        p1 = self.scan(cid, phase=1, at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                       summary_stats=stats({"title_missing": 3, "thin_content": 2, "cwv_lcp": 5}), ai_checks=AI,
                       ahrefs=AHREFS)
        q3 = self.scan(cid, phase=4, period="2026-Q3", at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                       summary_stats=stats({"title_missing": 2, "thin_content": 2, "c4_ai_scan": 1}, cwv_measured=0),
                       ai_checks=AI_LATER, ahrefs={**AHREFS, "reused_from": p1}, search_console=GSC,
                       bing_webmaster=BING, proranktracker=PRT)
        q4a = self.scan(cid, phase=4, period="2026-Q4", at=datetime(2026, 10, 5, tzinfo=timezone.utc),
                        summary_stats=stats({"title_missing": 1}, ruleset=2, cwv_measured=0))
        q4b = self.scan(cid, phase=4, period="2026-Q4", at=datetime(2026, 11, 5, tzinfo=timezone.utc),
                        summary_stats=stats({"title_missing": 1, "thin_content": 1}, ruleset=2, cwv_measured=0))
        self.scan(cid, phase=4, period="2026-Q4", at=datetime(2026, 11, 6, tzinfo=timezone.utc), status="failed")
        self.scan(cid, phase=2, at=datetime(2026, 7, 2, tzinfo=timezone.utc))

        r = self.client.get(f"/api/launch-checklist/analytics/customers/{cid}/trend")
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["customer"], {"id": cid, "name": "Klant", "domain": "klant.nl"})
        self.assertNotIn("checklist", {m["group"] for m in data["metrics"]})
        self.assertEqual({m["key"] for m in data["metrics"]}, set(analytics.SCAN_METRIC_KEYS))
        points = data["points"]
        self.assertEqual([p["scan_id"] for p in points], [p1, q3, q4a, q4b])
        self.assertEqual([p["is_primary"] for p in points], [True, True, False, True])
        self.assertEqual([p["ruleset"] for p in points], [1, 1, 2, 2])
        self.assertEqual(data["breaks"], [{"after_scan_id": q3, "from": 1, "to": 2}])
        self.assertEqual(points[0]["label"], "Nulmeting jul 2026")
        self.assertEqual(points[0]["period"], "2026-Q3")
        self.assertEqual(points[1]["label"], "Q3 2026")
        self.assertTrue(points[0]["date"].startswith("2026-07-01T09:05"))

        first, second = points[0]["values"], points[1]["values"]
        # floor = 1: thin_content (sinds regelset 2) telt als nieuwe controle; cwv_/c4_ tellen niet mee
        self.assertEqual((first["issues_comparable"], first["issues_new_checks"]), (3, 2))
        self.assertEqual((second["issues_comparable"], second["issues_new_checks"]), (2, 2))
        self.assertEqual(first["cwv_good_pct"], 40.0)
        self.assertIsNone(second["cwv_good_pct"])
        self.assertIsNone(first["gsc_clicks"])
        # JSON-subpaden (ook geneste: inspection.checked/indexed, crawl.in_index) via SQLite
        self.assertEqual(second["gsc_clicks"], 120)
        self.assertEqual(second["gsc_ctr"], 3.0)
        self.assertEqual(second["gsc_indexed_pct"], 75.0)
        self.assertEqual(second["bing_in_index"], 55)
        self.assertEqual(second["ai_score"], 100)
        self.assertEqual(second["domain_rating"], 40)
        self.assertEqual(points[1]["sources"],
                         {"ahrefs": "reused", "search_console": "ok", "bing": "ok",
                          "proranktracker": "ok", "cwv": "not_measured"})
        self.assertEqual(points[2]["sources"]["ahrefs"], "not_connected")
        # ProRankTracker via JSON-subpaden (state, totals, platforms); oude scans: niet gemeten
        self.assertEqual(second["prt_visibility"], 58.3)
        self.assertEqual(second["prt_visibility_perplexity"], 80)
        self.assertIsNone(second["prt_visibility_copilot"])
        self.assertIsNone(first["prt_visibility"])
        self.assertEqual(points[0]["sources"]["proranktracker"], "not_measured")
        projected = analytics.load_snapshots(self.db, LaunchScan.id == q3)[0].proranktracker
        self.assertEqual(projected, PRT_PROJECTED)  # zonder promptlijst

        r = self.client.get(f"/api/launch-checklist/analytics/customers/{cid}/trend",
                            params={"start": "2026-09-01", "end": "2026-10-31"})
        self.assertEqual([p["scan_id"] for p in r.json()["points"]], [q3, q4a])
        self.assertEqual(r.json()["points"][1]["is_primary"], False)  # datumfilter verandert is_primary niet

    def test_unknown_customer_and_empty(self):
        r = self.client.get("/api/launch-checklist/analytics/customers/bestaat-niet/trend")
        self.assertEqual(r.status_code, 404)
        cid = self.customer()
        r = self.client.get(f"/api/launch-checklist/analytics/customers/{cid}/trend")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["points"], r.json()["breaks"]), ([], []))


class CompareEndpointTest(_DbTest):
    def setUp(self):
        super().setUp()
        self.cid = self.customer()
        by_a = {"title_missing": 3, "meta_missing": 1, "cwv_lcp": 4}
        by_b = {"title_missing": 1, "thin_content": 2, "c4_ai_scan": 1}
        self.by_a, self.by_b = by_a, by_b
        self.a = self.scan(self.cid, phase=1, at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                           summary_stats=stats(by_a), ai_checks=AI, ahrefs=AHREFS)
        self.b = self.scan(self.cid, phase=4, period="2026-Q4", at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                           summary_stats=stats(by_b, ruleset=2, cwv_measured=0), ai_checks=AI_LATER,
                           ahrefs={**AHREFS, "reused_from": self.a}, search_console=GSC, bing_webmaster=BING)
        for url in ("https://www.klant.nl/", "https://www.klant.nl/oud", "https://www.klant.nl/stuk"):
            self.page(self.a, url)
        self.page(self.a, "https://www.klant.nl/alleen-ahrefs", ahrefs={"source": "ahrefs"})
        self.page(self.b, "https://www.klant.nl/")
        self.page(self.b, "https://www.klant.nl/stuk/", status_code=404)
        self.page(self.b, "https://www.klant.nl/nieuw")

    def get(self, a, b):
        return self.client.get("/api/launch-checklist/analytics/compare", params={"a": a, "b": b})

    def test_compare_is_chronological_and_reuses_quarterly_compare(self):
        r = self.get(self.b, self.a)  # omgekeerd aangeleverd
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual((data["a"]["scan_id"], data["b"]["scan_id"]), (self.a, self.b))
        self.assertEqual(data["a"]["label"], "Nulmeting jul 2026")
        self.assertEqual(data["b"]["label"], "Q4 2026")
        self.assertEqual(data["ai"], compare_ai(AI, AI_LATER))
        self.assertEqual(
            data["issues"],
            compare_issues(count_issue_types([t for t, n in self.by_a.items() for _ in range(n)]),
                           count_issue_types([t for t, n in self.by_b.items() for _ in range(n)]),
                           base_ruleset=1))
        self.assertEqual(data["issues"]["not_compared"], 2)
        self.assertEqual(data["pages"], {"before": 3, "after": 3, "new": 1, "removed": 1, "broken": 1,
                                         "new_examples": ["https://www.klant.nl/nieuw"]})
        self.assertTrue(data["ahrefs"]["same_snapshot"])
        self.assertIsNone(data["rankings"])

        metrics = {m["key"]: m for m in data["metrics"]}
        self.assertNotIn("checklist_geo_pct", metrics)
        self.assertEqual({k: metrics["issues_comparable"][k] for k in ("before", "after", "delta", "pct")},
                         {"before": 4, "after": 1, "delta": -3, "pct": -75.0})
        self.assertEqual({k: metrics["cwv_good_pct"][k] for k in ("before", "after", "delta", "pct")},
                         {"before": 40.0, "after": None, "delta": None, "pct": None})
        self.assertEqual(metrics["gsc_clicks"]["after"], 120)
        self.assertEqual(metrics["issues_comparable"]["group_label"], "Actiepunten")
        notes = " ".join(data["notes"])
        self.assertIn("A is een nulmeting", notes)
        self.assertIn("regelset 1", notes)
        self.assertIn("dezelfde Ahrefs-meting", notes)

    def test_compare_passes_scan_dates_to_rankings(self):
        with patch.object(analytics_router_module, "compare_rankings", return_value={"keywords": 1}) as mocked:
            data = self.get(self.b, self.a).json()
        self.assertEqual(data["rankings"], {"keywords": 1})
        args, kwargs = mocked.call_args
        self.assertEqual(args[1], self.cid)
        self.assertEqual(args[2], datetime(2026, 7, 1, 0, 5))  # completed_at van A (SQLite: zonder tijdzone)
        self.assertEqual(kwargs["until"], datetime(2026, 10, 1, 0, 5))  # completed_at van B

    def test_gsc_overlap_note(self):
        later = self.scan(self.cid, phase=4, period="2027-Q1", at=datetime(2027, 1, 5, tzinfo=timezone.utc),
                          summary_stats=stats({}, ruleset=2, cwv_measured=0),
                          search_console={**GSC, "period": {"start": "2026-10-01", "end": "2026-12-29"}})
        data = self.get(self.b, later).json()
        self.assertTrue(any("Search Console-meetperiodes overlappen" in n for n in data["notes"]), data["notes"])

    def test_errors(self):
        other = self.customer("Ander")
        other_scan = self.scan(other, phase=1, at=NOW, summary_stats=stats({}))
        geo = self.scan(self.cid, phase=2, at=NOW)
        failed = self.scan(self.cid, phase=4, period="2026-Q4", at=NOW, status="failed")
        self.assertEqual(self.get(self.a, self.a).status_code, 400)
        self.assertEqual(self.get(self.a, other_scan).status_code, 400)
        self.assertEqual(self.get(self.a, geo).status_code, 400)
        self.assertEqual(self.get(self.a, failed).status_code, 400)
        self.assertEqual(self.get(self.a, "bestaat-niet").status_code, 404)
        self.assertEqual(self.get("bestaat-niet", self.b).status_code, 404)
        self.assertEqual(self.client.get("/api/launch-checklist/analytics/compare", params={"a": self.a}).status_code,
                         422)

    def test_missing_by_type(self):
        old = self.scan(self.cid, phase=4, period="2026-Q3", at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                        summary_stats=stats(None, cwv_measured=0))
        data = self.get(self.a, old).json()
        self.assertIsNone(data["issues"])
        self.assertIsNone({m["key"]: m for m in data["metrics"]}["issues_comparable"]["after"])


class BenchmarkEndpointTest(_DbTest):
    def test_benchmark(self):
        full = self.customer("Volledig")
        self.scan(full, phase=1, at=datetime(2026, 7, 1, tzinfo=timezone.utc), summary_stats=stats({"title_missing": 9}))
        latest = self.scan(full, phase=4, period="2026-Q4", at=datetime(2026, 11, 1, tzinfo=timezone.utc),
                           summary_stats=stats({"title_missing": 2, "thin_content": 1}, ruleset=2, cwv_measured=0),
                           ai_checks=AI)
        self.scan(full, phase=4, period="2026-Q4", at=datetime(2026, 11, 10, tzinfo=timezone.utc), status="failed")
        geo_only = self.customer("Fasetwee")
        geo_key = next(iter(GEO_ITEMS))
        self.scan(geo_only, phase=2, at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                  checklist={"items": {}, "webshop_detected": False})
        self.db.add(LaunchChecklistState(id=str(uuid.uuid4()), customer_website_id=geo_only, item_key=geo_key,
                                         period="", manual_status="afgerond", updated_at=NOW))
        old = self.customer("Oud")
        self.scan(old, phase=1, at=datetime(2025, 1, 1, tzinfo=timezone.utc), summary_stats=stats({"title_missing": 5}))
        nothing = self.customer("Niets")
        self.scan(nothing, phase=1, at=NOW, status="failed")
        self.db.commit()

        r = self.client.get("/api/launch-checklist/analytics/benchmark")
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertIn("checklist", {m["group"] for m in data["metrics"]})
        rows = {row["customer"]["name"]: row for row in data["rows"]}
        self.assertEqual(set(rows), {"Volledig", "Fasetwee", "Oud"})  # zonder voltooide scan: niet
        self.assertEqual(rows["Volledig"]["scan"]["scan_id"], latest)
        # floor over de set = 1 (Oud heeft geen stempel): thin_content telt als nieuwe controle
        self.assertEqual(rows["Volledig"]["values"]["issues_comparable"], 2)
        self.assertEqual(rows["Volledig"]["values"]["issues_new_checks"], 1)
        self.assertIsNone(rows["Volledig"]["values"]["cwv_good_pct"])
        self.assertIsNone(rows["Fasetwee"]["scan"])
        self.assertIsNone(rows["Fasetwee"]["values"]["issues_comparable"])

        customers = {c["id"]: c for c in self.client.get("/api/launch-checklist/customers").json()["customers"]}
        for row in data["rows"]:
            c = customers[row["customer"]["id"]]
            self.assertEqual(row["values"]["checklist_geo_pct"], (c["checklist_progress"] or {}).get("percent"))
            self.assertEqual(row["values"]["checklist_content_pct"], (c["content_progress"] or {}).get("percent"))
            self.assertEqual(row["values"]["checklist_golive_pct"], (c["golive_progress"] or {}).get("percent"))
        self.assertIsNotNone(rows["Fasetwee"]["values"]["checklist_geo_pct"])

        self.assertEqual(data["summary"]["issues_comparable"]["n"], 2)
        self.assertEqual(data["summary"]["issues_comparable"]["median"], 3.5)
        self.assertEqual(data["summary"]["gsc_clicks"]["n"], 0)
        self.assertEqual(data["summary"]["checklist_geo_pct"]["n"], 1)

        # Ruim genoeg voor de scan van Volledig (nov 2026), te kort voor die van Oud (jan 2025).
        max_age = (datetime.now(timezone.utc) - datetime(2026, 11, 1, tzinfo=timezone.utc)).days + 30
        r = self.client.get("/api/launch-checklist/analytics/benchmark", params={"max_age_days": max_age})
        rows = {row["customer"]["name"]: row for row in r.json()["rows"]}
        self.assertIsNone(rows["Oud"]["scan"])
        self.assertIsNotNone(rows["Volledig"]["scan"])


class _SerpBase(DeclarativeBase):
    pass


class _SerpResult(_SerpBase):
    """`serp_scan_results` zoals de tabel in de database staat, mét de tekstkolom `keyword`.

    In `app.db.models.SerpScanResult` overschaduwt de relatie `keyword` die kolom (de kolom
    is niet gemapt), waardoor compare_rankings met echte metingen niet kan draaien. Deze
    test toetst de logica van compare_rankings tegen de bedoelde mapping.
    """

    __tablename__ = "serp_scan_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    website_id: Mapped[str] = mapped_column(String(36))
    keyword_id: Mapped[str] = mapped_column(String(36))
    keyword: Mapped[str] = mapped_column(Text)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CompareRankingsTest(unittest.TestCase):
    """`until` is nieuw; zonder `until` moet het resultaat gelijk blijven."""

    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        _SerpBase.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        patcher = patch.object(quarterly_compare, "SerpScanResult", _SerpResult)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cid = "klant-1"
        # SQLite geeft tijden zonder tijdzone terug: hier dus ook naïeve UTC-tijden.
        measurements = [("k1", "fietsen", 1, 10), ("k1", "fietsen", 5, 5), ("k1", "fietsen", 9, 3),
                        ("k2", "e-bike", 1, 8), ("k2", "e-bike", 5, None), ("k2", "e-bike", 9, 12),
                        ("k3", "bakfiets", 9, 2)]
        for kid, keyword, day, position in measurements:
            self.db.add(_SerpResult(id=str(uuid.uuid4()), website_id=self.cid, keyword_id=kid, keyword=keyword,
                                    position=position, result_url="https://www.klant.nl/x",
                                    created_at=datetime(2026, 10, day, 12)))
        self.db.add(_SerpResult(id=str(uuid.uuid4()), website_id=self.cid, keyword_id="k1", keyword="fietsen",
                                position=1, error_message="quota", created_at=datetime(2026, 10, 10, 12)))
        self.db.commit()

    def rows(self, result):
        return {r["keyword"]: (r["before"], r["after"], r["delta"]) for r in result["rows"]}

    def test_without_until_unchanged(self):
        since = datetime(2026, 10, 2)
        result = compare_rankings(self.db, self.cid, since)
        self.assertEqual(result, compare_rankings(self.db, self.cid, since, until=None))
        self.assertEqual(self.rows(result), {
            "fietsen": (10, 3, 7),
            "e-bike": (8, 12, -4),
            "bakfiets": (None, 2, None),  # geen meting rond de basisdatum
        })
        self.assertEqual(
            {k: result[k] for k in ("keywords", "top3", "top10", "improved", "declined", "compared")},
            {"keywords": 3, "top3": 2, "top10": 2, "improved": 1, "declined": 1, "compared": 2})
        self.assertTrue(result["last_checked_at"].startswith("2026-10-09"))
        self.assertEqual([r["keyword"] for r in result["rows"]], ["bakfiets", "fietsen", "e-bike"])
        self.assertIsNone(compare_rankings(self.db, "andere-klant", since))
        self.assertEqual(self.rows(compare_rankings(self.db, self.cid, None))["fietsen"], (None, 3, None))

    def test_until_ignores_later_measurements(self):
        result = compare_rankings(self.db, self.cid, datetime(2026, 10, 2), until=datetime(2026, 10, 6))
        self.assertEqual(self.rows(result), {"fietsen": (10, 5, 5), "e-bike": (8, None, -93)})
        self.assertTrue(result["last_checked_at"].startswith("2026-10-05"))
        self.assertIsNone(compare_rankings(self.db, self.cid, None, until=datetime(2026, 9, 1)))


if __name__ == "__main__":
    unittest.main()
