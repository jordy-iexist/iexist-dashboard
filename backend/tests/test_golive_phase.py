"""Livegang (fase 5): catalogus, samenvoegen, endpoints en de evaluatie van de livegangscan.

De endpoint-test draait tegen een SQLite-database met alleen de benodigde tabellen,
nooit tegen de echte Postgres.
"""
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import require_user_id
from app.db.models import (
    CustomerCategory,
    CustomerWebsite,
    LaunchChecklistState,
    LaunchScan,
    LaunchSitemapSnapshot,
)
from app.db.session import get_db
from app.features.launch_checklist.router import router
from app.features.launch_checklist.services import golive_checklist
from app.features.launch_checklist import router as router_module
from app.features.launch_checklist.services.content_checklist import ITEMS as CONTENT_ITEMS
from app.features.launch_checklist.services.discovery import DiscoveryResult
from app.features.launch_checklist.services.geo_checklist import ITEMS as GEO_ITEMS
from app.features.launch_checklist.services.golive_checks import evaluate_golive
from app.features.launch_checklist.services.golive_extract import (
    GoLiveSite,
    classify_host,
    extract_golive,
    find_consent,
    find_tracking,
)
from app.features.launch_checklist.services.inventory import PageRecord
from app.features.launch_checklist.services.quarterly_checklist import ITEMS as QUARTERLY_ITEMS

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def state(manual_status=None, note=None):
    return SimpleNamespace(manual_status=manual_status, note=note, updated_at=None, external_url=None, pushed_at=None)


def auto(status):
    return {"status": status, "message": "", "evidence": [], "details": None}


def effective(merged):
    return {i["key"]: i["effective"] for s in merged["sections"] for i in s["items"]}


class CatalogTest(unittest.TestCase):
    def test_twenty_items_in_four_sections(self):
        self.assertEqual(len(golive_checklist.ITEMS), 20)
        self.assertEqual([k for k, _ in golive_checklist.SECTIONS], ["domein", "indexatie", "meting", "basis"])
        sections = {k for k, _ in golive_checklist.SECTIONS}
        self.assertTrue(all(i.section in sections for i in golive_checklist.ITEMS.values()))
        merged = golive_checklist.merge_golive_checklist(None, {})
        self.assertEqual([len(s["items"]) for s in merged["sections"]], [5, 8, 3, 4])

    def test_keys_prefixed_and_unique_across_catalogues(self):
        keys = set(golive_checklist.ITEMS)
        self.assertTrue(all(k.startswith("gl_") for k in keys))
        self.assertFalse(keys & set(GEO_ITEMS))
        self.assertFalse(keys & set(CONTENT_ITEMS))
        self.assertFalse(keys & set(QUARTERLY_ITEMS))

    def test_every_item_has_a_description(self):
        self.assertTrue(all(i.description for i in golive_checklist.ITEMS.values()))

    def test_modes(self):
        modes = {k: i.mode for k, i in golive_checklist.ITEMS.items()}
        self.assertEqual(
            {k for k, m in modes.items() if m == "manual"},
            {"gl_redirect_map", "gl_search_console", "gl_tracking_verified"},
        )
        self.assertEqual(
            {k for k, m in modes.items() if m == "hybrid"},
            {"gl_staging_shielded", "gl_consent_banner", "gl_forms_tested"},
        )


class MergeTest(unittest.TestCase):
    def test_without_auto_results_everything_is_open(self):
        merged = golive_checklist.merge_golive_checklist(None, {})
        self.assertEqual(set(effective(merged).values()), {"open"})
        self.assertEqual((merged["done"], merged["total"], merged["percent"]), (0, 20, 0))
        self.assertTrue(all(i["auto"] is None for s in merged["sections"] for i in s["items"]))

    def test_manual_statuses(self):
        merged = golive_checklist.merge_golive_checklist(
            {"gl_https": auto("ok")},
            {
                "gl_redirect_map": state("afgerond"),
                "gl_favicon": state("nvt"),
                "gl_https": state("open"),  # handmatig open gaat voor op auto ok
            },
        )
        eff = effective(merged)
        self.assertEqual(eff["gl_redirect_map"], "done")
        self.assertEqual(eff["gl_favicon"], "nvt")
        self.assertEqual(eff["gl_https"], "open")
        # n.v.t. telt niet mee in het totaal.
        self.assertEqual((merged["done"], merged["total"]), (1, 19))

    def test_auto_results(self):
        merged = golive_checklist.merge_golive_checklist(
            {
                "gl_consent_banner": auto("info"),     # hybrid: hint, blijft open
                "gl_http_redirect": auto("ok"),        # auto: afgerond
                "gl_tracking_verified": auto("ok"),    # manual: negeert auto
                "gl_noindex": auto("error"),
                "gl_forms_tested": auto("ok"),         # hybrid met ok: afgerond (zoals in fase 2)
            },
            {},
        )
        eff = effective(merged)
        self.assertEqual(eff["gl_consent_banner"], "open")
        self.assertEqual(eff["gl_http_redirect"], "done")
        self.assertEqual(eff["gl_tracking_verified"], "open")
        self.assertEqual(eff["gl_noindex"], "open")
        self.assertEqual(eff["gl_forms_tested"], "done")
        self.assertEqual((merged["done"], merged["total"]), (2, 20))

    def test_states_of_other_catalogues_are_ignored(self):
        merged = golive_checklist.merge_golive_checklist(None, {"sitemap_xml": state("afgerond")})
        self.assertEqual(merged["done"], 0)


class GoLiveEndpointTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        # LaunchSitemapSnapshot: het klantoverzicht toont ook de sitemap-monitor.
        for model in (CustomerCategory, CustomerWebsite, LaunchScan, LaunchChecklistState, LaunchSitemapSnapshot):
            model.__table__.create(engine)
        Session = sessionmaker(bind=engine)
        self.db = Session()
        self.addCleanup(self.db.close)
        self.customer_id = str(uuid.uuid4())
        self.db.add(CustomerWebsite(
            id=self.customer_id, name="Klant", base_url="https://www.klant.nl/", domain="klant.nl",
            created_by="user-1", created_at=NOW, updated_at=NOW,
        ))
        self.db.commit()

        app = FastAPI()
        app.include_router(router)

        def override_db():
            db = Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_user_id] = lambda: "user-1"
        self.client = TestClient(app)
        self.base = f"/api/launch-checklist/customers/{self.customer_id}/golive-checklist"

    def test_get_without_any_scan(self):
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertIsNone(data["scan"])
        self.assertEqual(sum(len(s["items"]) for s in data["sections"]), 20)
        self.assertEqual((data["done"], data["total"], data["percent"]), (0, 20, 0))

    def test_patch_is_reflected_in_next_get(self):
        response = self.client.patch(
            f"{self.base}/gl_forms_tested", json={"manual_status": "afgerond", "note": "  Contactformulier getest  "})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["effective"], "done")

        data = self.client.get(self.base).json()
        items = {i["key"]: i for s in data["sections"] for i in s["items"]}
        self.assertEqual(items["gl_forms_tested"]["manual_status"], "afgerond")
        self.assertEqual(items["gl_forms_tested"]["note"], "Contactformulier getest")
        self.assertEqual(data["done"], 1)

        # Alleen de notitie wijzigen laat de status staan; leeg maken zet hem op null.
        self.client.patch(f"{self.base}/gl_forms_tested", json={"note": ""})
        row = self.db.query(LaunchChecklistState).one()
        self.db.refresh(row)
        self.assertEqual((row.manual_status, row.note, row.period), ("afgerond", None, ""))

    def test_unknown_item_key_is_rejected(self):
        for key in ("gl_onbekend", "sitemap_xml", "c3_blogs"):
            response = self.client.patch(f"{self.base}/{key}", json={"manual_status": "afgerond"})
            self.assertEqual(response.status_code, 404, key)
        self.assertEqual(self.db.query(LaunchChecklistState).count(), 0)

    def test_unknown_customer(self):
        self.assertEqual(self.client.get("/api/launch-checklist/customers/onbekend/golive-checklist").status_code, 404)

    def test_overview_progress(self):
        def customer():
            data = self.client.get("/api/launch-checklist/customers").json()
            return data["customers"][0]

        before = customer()
        self.assertIsNone(before["golive_progress"])
        self.assertIsNone(before["latest_golive_scan"])
        self.client.patch(f"{self.base}/gl_https", json={"manual_status": "afgerond"})
        after = customer()
        self.assertEqual(after["golive_progress"], {"done": 1, "total": 20, "percent": 5})
        # Een afgevinkt livegangpunt start fase 2 van de SEO/GEO-scan niet.
        self.assertIsNone(after["checklist_progress"])

    def test_start_golive_scan_creates_phase_5_and_refuses_second(self):
        url = f"/api/launch-checklist/customers/{self.customer_id}/golive-scans"
        with patch.object(router_module, "validate_external_url", return_value=None), \
                patch("app.worker.tasks.run_golive_scan_task.delay") as delay:
            first = self.client.post(url)
            self.assertEqual(first.status_code, 200, first.text)
            data = first.json()
            self.assertEqual((data["phase"], data["status"], data["max_pages"]), (5, "pending", 500))
            delay.assert_called_once_with(data["id"])
            second = self.client.post(url, json={"max_pages": 50})
            self.assertEqual(second.status_code, 409, second.text)
        # Een actieve scan van een andere fase blokkeert ook (één actieve scan per klant).
        self.db.query(LaunchScan).update({"status": "completed"})
        self.db.add(LaunchScan(
            id=str(uuid.uuid4()), customer_website_id=self.customer_id, phase=1, status="inventory",
            base_url="https://www.klant.nl/", total_urls=0, inventoried_urls=0, failed_urls=0, max_pages=500,
            vitals_max_pages=0, vitals_total=0, vitals_measured=0, created_by="user-1",
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ))
        self.db.commit()
        with patch.object(router_module, "validate_external_url", return_value=None), \
                patch("app.worker.tasks.run_golive_scan_task.delay") as delay:
            self.assertEqual(self.client.post(url).status_code, 409)
            delay.assert_not_called()

    def test_completed_golive_scan_feeds_the_checklist(self):
        scan_id = str(uuid.uuid4())
        self.db.add(LaunchScan(
            id=scan_id, customer_website_id=self.customer_id, phase=5, status="completed",
            base_url="https://www.klant.nl/", total_urls=0, inventoried_urls=0, failed_urls=0, max_pages=500,
            vitals_max_pages=0, vitals_total=0, vitals_measured=0, created_by="user-1",
            created_at=NOW, updated_at=NOW,
            checklist={"items": {"gl_https": auto("ok"), "gl_consent_banner": auto("info")},
                       "generated_at": NOW.isoformat()},
        ))
        self.db.commit()
        data = self.client.get(self.base).json()
        self.assertEqual(data["scan"]["id"], scan_id)
        items = {i["key"]: i for s in data["sections"] for i in s["items"]}
        self.assertEqual(items["gl_https"]["effective"], "done")
        self.assertEqual(items["gl_consent_banner"]["effective"], "open")
        self.assertEqual(data["done"], 1)

    def test_scan_list_accepts_phase_5(self):
        response = self.client.get(f"/api/launch-checklist/scans?customer_website_id={self.customer_id}&phase=5")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 0)
        # 6 is de sitemap-monitor; daarboven bestaat geen fase.
        self.assertEqual(self.client.get("/api/launch-checklist/scans?phase=7").status_code, 422)


# --- automatische scan: extractie en evaluatie -------------------------------------

SITE = GoLiveSite.from_base_url("https://www.klant.nl/")
ORIGIN = "https://www.klant.nl"

GOOD_HTML = """<html lang="nl"><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="{url}">
<link rel="icon" href="/favicon.png">
<script async src="https://www.googletagmanager.com/gtm.js?id=GTM-ABC1234"></script>
<script src="https://consent.cookiebot.com/uc.js" data-cbid="x"></script>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter">
<script src="https://cdn.jsdelivr.net/npm/x@1/x.js"></script>
</head><body>
<a href="/contact/">Contact</a> <a href="https://shop.klant.nl/">Winkel</a>
<img src="/a.jpg" srcset="/a.jpg 1x, /a@2x.jpg 2x">
<form action="/contact/" method="post"><input name="naam"><textarea name="bericht"></textarea></form>
<form role="search" action="/"><input name="s"></form>
<form action="/cart/add"><input type="number" name="qty"></form>
</body></html>"""


def page(url, html=GOOD_HTML, *, status=200, in_sitemap=True, reason=None, broken=None, error=None, **fmt):
    rec = PageRecord(url=url, path=urlparse(url).path or "/", in_sitemap=in_sitemap,
                     status_code=None if error else status, final_url=None if error else url,
                     final_status=None if error else status, content_type="text/html", error=error)
    rec.indexability_reason = reason
    rec.broken_links = broken or []
    if html is not None and status == 200 and not error:
        rec.extra["golive"] = extract_golive(html.format(url=url, **fmt), url, SITE)
    return rec


def variant(start, chain=(), final_url=None, final_status=200, error=None):
    parsed = urlparse(start)
    return {
        "start": start, "scheme": parsed.scheme, "host": parsed.hostname,
        "chain": [{"url": u, "status": s, "location": loc} for u, s, loc in chain],
        "final_url": None if error else (final_url or start), "final_status": None if error else final_status,
        "content_type": "text/html", "hsts": None, "error": error, "cert_error": False,
    }


def clean_variants():
    home = f"{ORIGIN}/"
    return [
        variant("http://klant.nl/", [("http://klant.nl/", 301, home)], home),
        variant("http://www.klant.nl/", [("http://www.klant.nl/", 301, home)], home),
        variant("https://klant.nl/", [("https://klant.nl/", 301, home)], home),
        variant(home),
    ]


def probes(variants=None, not_found=None, favicon=None):
    variants = variants or clean_variants()
    https = next(v for v in variants if v["scheme"] == "https" and v["host"] == SITE.host)
    slug = f"{ORIGIN}/livegang-404-controle-x"
    return {
        "variants": variants, "https": https, "origin": ORIGIN,
        "not_found": not_found if not_found is not None else [
            {**variant(slug, final_status=404)}, {**variant(slug + "/", final_status=404)}],
        "favicon": favicon if favicon is not None else [
            {"url": f"{ORIGIN}/favicon.png", "final_url": f"{ORIGIN}/favicon.png", "status": 200,
             "content_type": "image/png", "error": None, "ok": True}],
    }


def discovery(urls=None, **kw):
    urls = urls if urls is not None else [f"{ORIGIN}/", f"{ORIGIN}/contact/"]
    values = dict(urls=urls, sitemaps=[f"{ORIGIN}/sitemap.xml"],
                  robots_txt=f"User-agent: *\nDisallow: /wp-admin/\nSitemap: {ORIGIN}/sitemap.xml\n", robots_status=200)
    values.update(kw)
    return DiscoveryResult(**values)


def clean_records():
    return [page(f"{ORIGIN}/"), page(f"{ORIGIN}/contact/")]


def evaluate(records=None, disc=None, prb=None, site=SITE):
    return evaluate_golive(base_url=f"{ORIGIN}/", site=site, records=clean_records() if records is None else records,
                           discovery=disc or discovery(), probes=prb or probes())


def status(items, key):
    return items[key]["status"]


class EvaluateCoverageTest(unittest.TestCase):
    def test_clean_site(self):
        items = evaluate()
        auto_keys = {k for k, i in golive_checklist.ITEMS.items() if i.mode != "manual"}
        self.assertEqual(set(items), auto_keys)
        for key in auto_keys:
            self.assertIn(set(items[key]), [{"status", "message", "evidence", "details"}], key)
        for key, item in golive_checklist.ITEMS.items():
            if item.mode == "auto":
                self.assertEqual(status(items, key), "ok", (key, items[key]["message"]))
        self.assertEqual(status(items, "gl_staging_shielded"), "info")
        self.assertEqual(status(items, "gl_consent_banner"), "info")
        self.assertEqual(status(items, "gl_forms_tested"), "info")
        self.assertIn("Cookiebot", items["gl_consent_banner"]["message"])

    def test_hybrid_items_never_ok(self):
        hybrids = [k for k, i in golive_checklist.ITEMS.items() if i.mode == "hybrid"]
        blocked = [page(f"{ORIGIN}/p{i}/", status=403) for i in range(5)] + clean_records()
        bare = [page(f"{ORIGIN}/", "<html><body>Hallo</body></html>")]
        for records in (None, [], blocked, bare):
            items = evaluate(records)
            for key in hybrids:
                self.assertNotEqual(status(items, key), "ok", (key, records))

    def test_blocked_scanner_gives_unknown_not_all_clear(self):
        blocked = [page(f"{ORIGIN}/p{i}/", status=403) for i in range(5)] + clean_records()
        items = evaluate(blocked)
        for key in ("gl_mixed_content", "gl_noindex", "gl_staging_refs", "gl_pages_ok", "gl_tracking_installed",
                    "gl_viewport", "gl_consent_banner", "gl_forms_tested", "gl_internal_urls"):
            self.assertEqual(status(items, key), "unknown", key)
            self.assertIn("geblokkeerd", items[key]["message"])
        self.assertEqual(status(items, "gl_https"), "ok")  # probes staan los van de pagina's

    def test_no_pages(self):
        items = evaluate([])
        self.assertEqual(status(items, "gl_pages_ok"), "unknown")
        self.assertEqual(status(items, "gl_tracking_installed"), "unknown")


class DomainChecksTest(unittest.TestCase):
    def test_https(self):
        self.assertEqual(status(evaluate(), "gl_https"), "ok")
        bad = clean_variants()
        bad[3] = variant(f"{ORIGIN}/", error="Certificaatfout: certificate has expired")
        items = evaluate(prb=probes(bad))
        self.assertEqual(status(items, "gl_https"), "error")
        self.assertIn("certificate has expired", items["gl_https"]["message"])
        to_http = clean_variants()
        to_http[3] = variant(f"{ORIGIN}/", [(f"{ORIGIN}/", 301, "http://www.klant.nl/")], "http://www.klant.nl/")
        self.assertEqual(status(evaluate(prb=probes(to_http)), "gl_https"), "error")
        server_error = clean_variants()
        server_error[3] = variant(f"{ORIGIN}/", final_status=500)
        self.assertEqual(status(evaluate(prb=probes(server_error)), "gl_https"), "error")

    def test_http_redirect(self):
        self.assertEqual(status(evaluate(), "gl_http_redirect"), "ok")
        temporary = clean_variants()
        temporary[1] = variant("http://www.klant.nl/", [("http://www.klant.nl/", 302, f"{ORIGIN}/")], f"{ORIGIN}/")
        self.assertEqual(status(evaluate(prb=probes(temporary)), "gl_http_redirect"), "warning")
        own_page = clean_variants()
        own_page[1] = variant("http://www.klant.nl/")
        self.assertEqual(status(evaluate(prb=probes(own_page)), "gl_http_redirect"), "error")
        permanent_308 = clean_variants()
        permanent_308[0] = variant("http://klant.nl/", [("http://klant.nl/", 308, f"{ORIGIN}/")], f"{ORIGIN}/")
        self.assertEqual(status(evaluate(prb=probes(permanent_308)), "gl_http_redirect"), "ok")

    def test_host_variants(self):
        self.assertEqual(status(evaluate(), "gl_host_variants"), "ok")
        own = clean_variants()
        own[2] = variant("https://klant.nl/")  # apex geeft een eigen 200
        items = evaluate(prb=probes(own))
        self.assertEqual(status(items, "gl_host_variants"), "error")
        long_chain = clean_variants()
        long_chain[0] = variant("http://klant.nl/", [
            ("http://klant.nl/", 301, "https://klant.nl/"), ("https://klant.nl/", 301, "http://www.klant.nl/"),
            ("http://www.klant.nl/", 301, f"{ORIGIN}/")], f"{ORIGIN}/")
        self.assertEqual(status(evaluate(prb=probes(long_chain)), "gl_host_variants"), "warning")

    def test_host_variants_nvt_on_subdomain(self):
        sub = GoLiveSite.from_base_url("https://shop.klant.nl/")
        self.assertFalse(sub.has_host_pair)
        variants = [variant("http://shop.klant.nl/", [("http://shop.klant.nl/", 301, "https://shop.klant.nl/")],
                            "https://shop.klant.nl/"), variant("https://shop.klant.nl/")]
        prb = {"variants": variants, "https": variants[1], "origin": "https://shop.klant.nl",
               "not_found": [], "favicon": []}
        items = evaluate_golive(base_url="https://shop.klant.nl/", site=sub, records=[], discovery=discovery(urls=[]),
                                probes=prb)
        self.assertEqual(status(items, "gl_host_variants"), "nvt")

    def test_mixed_content(self):
        active = GOOD_HTML.replace("</head>", '<script src="http://cdn.voorbeeld.nl/x.js"></script></head>')
        passive = GOOD_HTML.replace("</body>", '<img src="http://cdn.voorbeeld.nl/a.jpg"></body>')
        self.assertEqual(status(evaluate([page(f"{ORIGIN}/", active)]), "gl_mixed_content"), "error")
        items = evaluate([page(f"{ORIGIN}/", passive)])
        self.assertEqual(status(items, "gl_mixed_content"), "warning")
        self.assertEqual(items["gl_mixed_content"]["details"]["passive_total"], 1)
        form = GOOD_HTML.replace("</body>", '<form action="http://www.klant.nl/x"><input name="a"></form></body>')
        self.assertEqual(status(evaluate([page(f"{ORIGIN}/", form)]), "gl_mixed_content"), "error")

    def test_internal_urls(self):
        http_link = GOOD_HTML.replace("</body>", '<a href="http://www.klant.nl/over/">Over</a></body>')
        items = evaluate([page(f"{ORIGIN}/", http_link)])
        self.assertEqual(status(items, "gl_internal_urls"), "warning")
        apex_canonical = GOOD_HTML.replace('href="{url}"', 'href="https://klant.nl/"')
        items = evaluate([page(f"{ORIGIN}/", apex_canonical)])
        self.assertEqual(status(items, "gl_internal_urls"), "warning")
        self.assertEqual(items["gl_internal_urls"]["details"]["canonicals"], 1)
        # Een ander subdomein (shop.klant.nl) is geen hostvariant.
        self.assertEqual(status(evaluate(), "gl_internal_urls"), "ok")


class IndexationChecksTest(unittest.TestCase):
    def test_robots(self):
        self.assertEqual(status(evaluate(), "gl_robots_open"), "ok")
        items = evaluate(disc=discovery(robots_txt="User-agent: *\nDisallow: /\n"))
        self.assertEqual(status(items, "gl_robots_open"), "error")
        some = [page(f"{ORIGIN}/"), page(f"{ORIGIN}/contact/"), page(f"{ORIGIN}/a/"), page(f"{ORIGIN}/prive/")]
        items = evaluate(some, disc=discovery(robots_txt="User-agent: *\nDisallow: /prive/\n"))
        self.assertEqual(status(items, "gl_robots_open"), "warning")
        half = [page(f"{ORIGIN}/"), page(f"{ORIGIN}/x/a/"), page(f"{ORIGIN}/x/b/")]
        self.assertEqual(status(evaluate(half, disc=discovery(robots_txt="User-agent: *\nDisallow: /x/\n")),
                                "gl_robots_open"), "error")
        self.assertEqual(status(evaluate(disc=discovery(robots_status=None, robots_txt=None)), "gl_robots_open"),
                         "unknown")
        # Googlebot-groep gaat voor op de *-groep.
        google_ok = "User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nAllow: /\n"
        self.assertEqual(status(evaluate(disc=discovery(robots_txt=google_ok)), "gl_robots_open"), "ok")

    def test_noindex(self):
        self.assertEqual(status(evaluate(), "gl_noindex"), "ok")
        home = [page(f"{ORIGIN}/", reason="noindex (meta robots)"), page(f"{ORIGIN}/contact/"),
                page(f"{ORIGIN}/a/"), page(f"{ORIGIN}/b/")]
        self.assertEqual(status(evaluate(home), "gl_noindex"), "error")
        sitemap = [page(f"{ORIGIN}/"), page(f"{ORIGIN}/a/"), page(f"{ORIGIN}/b/"),
                   page(f"{ORIGIN}/bedankt/", reason="noindex (meta robots)")]
        self.assertEqual(status(evaluate(sitemap), "gl_noindex"), "warning")
        outside = [page(f"{ORIGIN}/"), page(f"{ORIGIN}/a/"), page(f"{ORIGIN}/b/"),
                   page(f"{ORIGIN}/bedankt/", reason="noindex (X-Robots-Tag)", in_sitemap=False)]
        items = evaluate(outside)
        self.assertEqual(status(items, "gl_noindex"), "ok")
        self.assertEqual(len(items["gl_noindex"]["evidence"]), 1)

    def test_sitemap(self):
        self.assertEqual(status(evaluate(), "gl_sitemap"), "ok")
        self.assertEqual(status(evaluate(disc=discovery(urls=[], sitemaps=[])), "gl_sitemap"), "error")
        not_in_robots = discovery(robots_txt="User-agent: *\nDisallow:\n")
        self.assertEqual(status(evaluate(disc=not_in_robots), "gl_sitemap"), "warning")
        foreign = discovery(foreign_total=3, foreign_sample=["https://staging.bureau.nl/a/"])
        items = evaluate(disc=foreign)
        self.assertEqual(status(items, "gl_sitemap"), "warning")
        self.assertIn("ander domein", items["gl_sitemap"]["message"])
        http_urls = discovery(urls=["http://www.klant.nl/", f"{ORIGIN}/contact/"])
        self.assertEqual(status(evaluate(disc=http_urls), "gl_sitemap"), "warning")
        broken = clean_records() + [page(f"{ORIGIN}/weg/", status=404)]
        self.assertEqual(status(evaluate(broken), "gl_sitemap"), "warning")

    def test_staging_refs(self):
        self.assertEqual(status(evaluate(), "gl_staging_refs"), "ok")
        strong = GOOD_HTML.replace("</body>", '<a href="https://staging.klant.nl/over/">Over</a></body>')
        items = evaluate([page(f"{ORIGIN}/", strong)])
        self.assertEqual(status(items, "gl_staging_refs"), "error")
        self.assertEqual(items["gl_staging_refs"]["details"]["hosts"][0]["host"], "staging.klant.nl")
        self.assertIn("staging.klant.nl", items["gl_staging_shielded"]["message"])
        self.assertEqual(status(items, "gl_staging_shielded"), "info")
        demo = GOOD_HTML.replace("</body>", '<a href="https://demo.klant.nl/">Demo</a></body>')
        self.assertEqual(status(evaluate([page(f"{ORIGIN}/", demo)]), "gl_staging_refs"), "warning")
        inline = GOOD_HTML.replace("</body>", '<script>var cfg={{"url":"https:\\/\\/klant.wpengine.com\\/x"}}</script></body>')
        items = evaluate([page(f"{ORIGIN}/", inline)])
        self.assertEqual(status(items, "gl_staging_refs"), "error")
        self.assertEqual(items["gl_staging_refs"]["details"]["refs"][0]["type"], "inline")
        in_sitemap = discovery(urls=[f"{ORIGIN}/", "https://acc.klant.nl/contact/"])
        self.assertEqual(status(evaluate(disc=in_sitemap), "gl_staging_refs"), "error")

    def test_staging_refs_on_test_host_itself(self):
        own = GoLiveSite.from_base_url("https://klant.netlify.app/")
        items = evaluate_golive(base_url="https://klant.netlify.app/", site=own, records=[],
                                discovery=discovery(urls=[]), probes=probes())
        # Zonder pagina's: inhoud onbekend, maar ...
        self.assertEqual(status(items, "gl_staging_refs"), "unknown")
        rec = PageRecord(url="https://klant.netlify.app/", path="/", in_sitemap=False, status_code=200,
                         final_url="https://klant.netlify.app/", final_status=200, content_type="text/html")
        rec.extra["golive"] = extract_golive(GOOD_HTML.format(url="https://klant.netlify.app/"),
                                             "https://klant.netlify.app/", own)
        items = evaluate_golive(base_url="https://klant.netlify.app/", site=own, records=[rec],
                                discovery=discovery(urls=[]), probes=probes())
        self.assertEqual(status(items, "gl_staging_refs"), "error")
        self.assertTrue(items["gl_staging_refs"]["details"]["site_is_test_host"])

    def test_pages_ok(self):
        self.assertEqual(status(evaluate(), "gl_pages_ok"), "ok")
        failing = clean_records() + [page(f"{ORIGIN}/weg/", status=404)]
        self.assertEqual(status(evaluate(failing), "gl_pages_ok"), "error")
        unreachable = clean_records() + [page(f"{ORIGIN}/traag/", error="Timeout")]
        self.assertEqual(status(evaluate(unreachable), "gl_pages_ok"), "error")
        broken = [page(f"{ORIGIN}/", broken=[{"url": f"{ORIGIN}/oud/", "status": 404}]), page(f"{ORIGIN}/contact/")]
        items = evaluate(broken)
        self.assertEqual(status(items, "gl_pages_ok"), "error")
        self.assertEqual(items["gl_pages_ok"]["details"]["broken_total"], 1)


class TrackingAndBasicsTest(unittest.TestCase):
    def test_tracking(self):
        self.assertEqual(status(evaluate(), "gl_tracking_installed"), "ok")
        none = GOOD_HTML.replace("GTM-ABC1234", "")
        items = evaluate([page(f"{ORIGIN}/", none)])
        self.assertEqual(status(items, "gl_tracking_installed"), "error")
        self.assertIn("niet gevonden in de HTML", items["gl_tracking_installed"]["message"])
        missing = [page(f"{ORIGIN}/"), page(f"{ORIGIN}/contact/", none)]
        self.assertEqual(status(evaluate(missing), "gl_tracking_installed"), "warning")
        two = GOOD_HTML.replace("</head>", '<script src="https://www.googletagmanager.com/gtm.js?id=GTM-ZZZ9999"></script></head>')
        self.assertEqual(status(evaluate([page(f"{ORIGIN}/", two)]), "gl_tracking_installed"), "warning")
        ua = none.replace("</head>", "<script>ga('create', 'UA-1234567-1', 'auto');</script></head>")
        items = evaluate([page(f"{ORIGIN}/", ua)])
        self.assertEqual(status(items, "gl_tracking_installed"), "warning")
        self.assertIn("UA-1234567-1", items["gl_tracking_installed"]["message"])

    def test_consent(self):
        none = GOOD_HTML.replace('<script src="https://consent.cookiebot.com/uc.js" data-cbid="x"></script>', "")
        items = evaluate([page(f"{ORIGIN}/", none)])
        self.assertEqual(status(items, "gl_consent_banner"), "warning")
        self.assertIn("tagmanager", items["gl_consent_banner"]["message"])

    def test_forms(self):
        items = evaluate()
        self.assertEqual(status(items, "gl_forms_tested"), "info")
        # Zoek- en winkelwagenformulieren tellen niet: één formulier per pagina.
        self.assertEqual([p["forms"] for p in items["gl_forms_tested"]["details"]["pages"]], [1, 1])

    def test_not_found(self):
        self.assertEqual(status(evaluate(), "gl_404"), "ok")
        slug = f"{ORIGIN}/livegang-404-controle-x"
        soft = [variant(slug), variant(slug + "/")]
        self.assertEqual(status(evaluate(prb=probes(not_found=soft)), "gl_404"), "error")
        to_home = [variant(slug, [(slug, 301, f"{ORIGIN}/")], f"{ORIGIN}/"), variant(slug + "/", final_status=404)]
        self.assertEqual(status(evaluate(prb=probes(not_found=to_home)), "gl_404"), "error")
        blocked = [variant(slug, final_status=403), variant(slug + "/", final_status=403)]
        self.assertEqual(status(evaluate(prb=probes(not_found=blocked)), "gl_404"), "unknown")
        gone = [variant(slug, final_status=410), variant(slug + "/", final_status=404)]
        self.assertEqual(status(evaluate(prb=probes(not_found=gone)), "gl_404"), "ok")

    def test_viewport(self):
        self.assertEqual(status(evaluate(), "gl_viewport"), "ok")
        none = GOOD_HTML.replace('<meta name="viewport" content="width=device-width, initial-scale=1">', "")
        self.assertEqual(status(evaluate([page(f"{ORIGIN}/", none), page(f"{ORIGIN}/contact/")]), "gl_viewport"),
                         "error")
        some = [page(f"{ORIGIN}/"), page(f"{ORIGIN}/a/"), page(f"{ORIGIN}/b/"), page(f"{ORIGIN}/c/", none)]
        self.assertEqual(status(evaluate(some), "gl_viewport"), "warning")
        fixed = GOOD_HTML.replace("width=device-width, initial-scale=1", "width=1024")
        self.assertEqual(status(evaluate([page(f"{ORIGIN}/", fixed)]), "gl_viewport"), "error")

    def test_favicon(self):
        self.assertEqual(status(evaluate(), "gl_favicon"), "ok")
        html_page = [{"url": f"{ORIGIN}/favicon.ico", "final_url": f"{ORIGIN}/", "status": 200,
                      "content_type": "text/html", "error": None, "ok": False}]
        self.assertEqual(status(evaluate(prb=probes(favicon=html_page)), "gl_favicon"), "warning")


class TestHostClassificationTest(unittest.TestCase):
    def verdict(self, host, site=SITE):
        result = classify_host(host, site)
        return result[0] if result else None

    def test_strong_labels_on_own_domain(self):
        for host in ("staging.klant.nl", "test.klant.nl", "dev.klant.nl", "acc.klant.nl", "acceptatie.klant.nl",
                     "uat.klant.nl", "staging2.klant.nl", "test-shop.klant.nl", "sandbox.klant.nl"):
            self.assertEqual(self.verdict(host), "error", host)

    def test_ambiguous_labels_warn(self):
        for host in ("demo.klant.nl", "nieuw.klant.nl", "old.klant.nl", "beta.klant.nl", "preview.klant.nl"):
            self.assertEqual(self.verdict(host), "warning", host)

    def test_platform_and_local(self):
        for host in ("klant.wpengine.com", "klant.kinsta.cloud", "klant-shop.myshopify.com", "klant.webflow.io",
                     "klant.vercel.app", "klant.netlify.app", "abc.pages.dev", "wordpress-123.cloudwaysapps.com",
                     "klant.sg-host.com", "klant.wpcomstaging.com", "dev-klant.pantheonsite.io", "klant.transurl.nl",
                     "localhost", "192.168.1.10", "10.0.0.1", "klant.local", "klant.test", "www.klant.nl:8080"):
            self.assertEqual(self.verdict(host), "error", host)

    def test_agency_test_domains_setting(self):
        site = GoLiveSite.from_base_url("https://www.klant.nl/", ["iexist-dev.nl"])
        self.assertEqual(self.verdict("klant.iexist-dev.nl", site), "error")
        self.assertEqual(self.verdict("iexist-dev.nl", site), "error")
        self.assertIsNone(self.verdict("iexist.nl", site))

    def test_counter_examples(self):
        for host in ("cdn.shopify.com", "fonts.googleapis.com", "cdn.jsdelivr.net", "www.klant.nl", "klant.nl",
                     "shop.klant.nl", "www.klant.nl:443", "devices.klant.nl", "contest.klant.nl", "wpengine.com",
                     "myshopify.com", "staging.anderbedrijf.nl", "www.googletagmanager.com", "latest.klant.nl"):
            self.assertIsNone(self.verdict(host), host)

    def test_shopify_store(self):
        shop = GoLiveSite.from_base_url("https://www.winkel.nl/")
        html = """<html><head><link rel="canonical" href="https://www.winkel.nl/">
        <script src="https://cdn.shopify.com/s/files/theme.js"></script>
        <script>Shopify.shop = "winkel.myshopify.com"; var u = "https://winkel.myshopify.com/api";</script>
        </head><body><a href="https://winkel.myshopify.com/cart">Winkelwagen</a>
        <a href="https://winkel.myshopify.com/checkouts/abc">Afrekenen</a>
        <form action="https://winkel.myshopify.com/cart/add"><input name="id"></form></body></html>"""
        data = extract_golive(html, "https://www.winkel.nl/", shop)
        self.assertEqual(data["test_refs_total"], 0, data["test_refs"])
        leftover = html.replace("</body>", '<a href="https://winkel.myshopify.com/collections/alles">Alles</a></body>')
        data = extract_golive(leftover, "https://www.winkel.nl/", shop)
        self.assertEqual([r["type"] for r in data["test_refs"]], ["link"])
        canonical = html.replace('href="https://www.winkel.nl/"', 'href="https://winkel.myshopify.com/"')
        data = extract_golive(canonical, "https://www.winkel.nl/", shop)
        self.assertIn("canonical", [r["type"] for r in data["test_refs"]])

    def test_js_comment_is_not_a_host(self):
        html = "<html><body><script>//foo.test(x); //staging.klant.nl comment</script></body></html>"
        self.assertEqual(extract_golive(html, f"{ORIGIN}/", SITE)["test_refs_total"], 0)


class TrackingPatternTest(unittest.TestCase):
    def test_gtm(self):
        self.assertEqual(find_tracking('<script>(window,"GTM-ABC1234")</script>')["gtm"], ["GTM-ABC1234"])
        self.assertEqual(find_tracking('<noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-K9X2PQ"></iframe>')["gtm"], ["GTM-K9X2PQ"])
        for miss in ("GTM-XXXXXX", "gtm-abc1234", "GTM-AB", "XGTM-ABC1234", "GTM-ABC1234-extra"):
            self.assertEqual(find_tracking(miss)["gtm"], [], miss)

    def test_ga4_only_in_gtag_context(self):
        self.assertEqual(find_tracking('<script src="https://www.googletagmanager.com/gtag/js?id=G-AB12CD34EF"></script>')["ga4"],
                         ["G-AB12CD34EF"])
        self.assertEqual(find_tracking("gtag('config', 'G-ZY98XW76VU');")["ga4"], ["G-ZY98XW76VU"])
        self.assertEqual(find_tracking('gtag("config","G-ZY98XW76VU")')["ga4"], ["G-ZY98XW76VU"])
        for miss in ('<div class="G-AB12CD34EF">', "G-AB12CD34EF", "gtag('config', 'G-SHORT')", "gtag('event', 'G-AB12CD34EF')"):
            self.assertEqual(find_tracking(miss)["ga4"], [], miss)

    def test_ua_and_others(self):
        self.assertEqual(find_tracking("ga('create', 'UA-123456-2')")["ua"], ["UA-123456-2"])
        self.assertEqual(find_tracking("UA-12-1")["ua"], [])
        found = find_tracking('<script src="https://connect.facebook.net/en_US/fbevents.js"></script>'
                              '<script src="https://www.clarity.ms/tag/abc"></script>'
                              '<script src="https://static.hotjar.com/c/hotjar-1.js"></script>'
                              '<script>var _paq = window._paq || []; _paq.push(["trackPageView"]);</script>'
                              '<script defer data-domain="x.nl" src="https://plausible.io/js/script.js"></script>')
        self.assertEqual(set(found["other"]), {"Meta-pixel", "Microsoft Clarity", "Hotjar", "Matomo", "Plausible"})
        self.assertEqual(find_tracking("<p>Wij gebruiken geen hotjar of matomo.</p>")["other"], [])

    def test_consent_signatures(self):
        cases = {
            '<script data-src="https://consent.cookiebot.com/uc.js"></script>': "Cookiebot",
            '<script src="https://cdn-cookieyes.com/client_data/x/script.js"></script>': "CookieYes",
            '<div id="cookie-law-info-bar"></div>': "CookieYes",
            '<div id="cmplz-cookiebanner-container"></div>': "Complianz",
            '<script src="https://cdn.cookielaw.org/scripttemplates/otSDKStub.js"></script>': "OneTrust",
            '<div id="BorlabsCookieBox"></div>': "Borlabs Cookie",
            '<script id="usercentrics-cmp" src="https://app.usercentrics.eu/browser-ui/latest/loader.js"></script>': "Usercentrics",
            '<script src="https://cdn.iubenda.com/cs/iubenda_cs.js"></script>': "iubenda",
            '<div id="cookie-notice" role="dialog"></div>': "Cookie Notice",
            '<div class="real-cookie-banner"></div>': "Real Cookie Banner",
            '<div id="moove_gdpr_cookie_info_bar"></div>': "Moove GDPR",
            '<script src="https://consent.cookiefirst.com/x.js"></script>': "CookieFirst",
            '<script>window.didomiConfig = {}</script>': "Didomi",
            '<script src="https://static.axept.io/sdk.js"></script><script>window.axeptioSettings={}</script>': "Axeptio",
            '<script src="/js/klaro.js"></script>': "Klaro",
            '<script src="/tarteaucitron/tarteaucitron.js"></script>': "tarteaucitron",
            '<script src="https://cdn.cookie-script.com/s/x.js"></script>': "CookieScript",
            '<script src="https://js.hs-banner.com/123.js"></script>': "HubSpot-cookiebanner",
            '<div class="shopify-pc__banner"></div>': "Shopify-cookiebanner",
            "<script>gtag('consent', 'default', {ad_storage: 'denied'});</script>": "Google Consent Mode (standaard)",
        }
        for html, name in cases.items():
            self.assertIn(name, find_consent(html), html)
        for miss in ("<p>Lees onze cookieverklaring.</p>", "<p>Klarinet</p>", "gtag('consent', 'update', {})"):
            self.assertEqual(find_consent(miss), [], miss)



if __name__ == "__main__":
    unittest.main()
