"""Livegang (fase 5): probes met httpx.MockTransport, de page_hook van de inventaris en de worker.

Geen echte netwerkverzoeken (MockTransport) en geen echte database (SQLite).
"""
import asyncio
import unittest
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from unittest.mock import patch

import httpx
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import LaunchScan, LaunchScanPage
from app.features.launch_checklist.services import golive_probes, inventory
from app.features.launch_checklist.services.discovery import DiscoveryResult
from app.features.launch_checklist.services.golive_checks import (
    check_host_variants,
    check_http_redirect,
    check_https,
    check_not_found,
    check_favicon,
)
from app.features.launch_checklist.services.golive_extract import GoLiveSite, make_page_hook
from app.features.launch_checklist.services.inventory import PageRecord, run_inventory
from app.features.launch_checklist.services.scan_recovery import INTERRUPTED_SCAN_MESSAGE
from app.features.launch_checklist.worker import golive_scan

SITE = GoLiveSite.from_base_url("https://www.klant.nl/")
HOME = "https://www.klant.nl/"
HTML = {"content-type": "text/html; charset=utf-8"}


def transport(routes, default=(404, HTML), errors=None):
    """routes: url → (status, headers) of een callable(request) → Response; errors: url → exceptie."""
    errors = errors or {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in errors:
            raise errors[url]
        route = routes.get(url)
        if route is None:
            for prefix, value in routes.items():
                if prefix.endswith("*") and url.startswith(prefix[:-1]):
                    route = value
                    break
        if callable(route):
            return route(request)
        status, headers = route or default
        return httpx.Response(status, headers=headers, text="<html><body>x</body></html>")

    return httpx.MockTransport(handler)


def moved(location, status=301):
    return status, {"location": location}


CLEAN = {
    "http://klant.nl/": moved(HOME),
    "http://www.klant.nl/": moved(HOME),
    "https://klant.nl/": moved(HOME),
    HOME: (200, {**HTML, "strict-transport-security": "max-age=31536000"}),
    "https://www.klant.nl/favicon.ico": (200, {"content-type": "image/x-icon"}),
}


def probe(routes, site=SITE, **kwargs):
    with patch.object(golive_probes, "is_safe_external_url", return_value=True):
        return golive_probes.run_probes(site, transport=transport(routes, **kwargs.pop("transport_kw", {})), **kwargs)


class HostMatrixTest(unittest.TestCase):
    def test_clean_301s(self):
        result = probe(CLEAN)
        self.assertEqual(len(result["variants"]), 4)
        self.assertEqual(result["origin"], "https://www.klant.nl")
        self.assertTrue(all(v["final_url"] == HOME and v["final_status"] == 200 for v in result["variants"]))
        self.assertEqual(result["variants"][0]["chain"], [{"url": "http://klant.nl/", "status": 301, "location": HOME}])
        self.assertEqual(check_http_redirect(result)["status"], "ok")
        self.assertEqual(check_host_variants(result, SITE)["status"], "ok")
        https = check_https(result)
        self.assertEqual(https["status"], "ok")
        self.assertIn("HSTS staat aan", https["message"])

    def test_temporary_redirect(self):
        result = probe({**CLEAN, "http://www.klant.nl/": moved(HOME, 302)})
        self.assertEqual(check_http_redirect(result)["status"], "warning")
        self.assertEqual(check_host_variants(result, SITE)["status"], "warning")

    def test_variant_serving_its_own_page(self):
        result = probe({**CLEAN, "https://klant.nl/": (200, HTML)})
        verdict = check_host_variants(result, SITE)
        self.assertEqual(verdict["status"], "error")
        self.assertIn("eigen pagina", " ".join(verdict["evidence"]))

    def test_http_serving_200(self):
        result = probe({**CLEAN, "http://www.klant.nl/": (200, HTML)})
        self.assertEqual(check_http_redirect(result)["status"], "error")

    def test_subdomain_site(self):
        sub = GoLiveSite.from_base_url("https://shop.klant.nl/")
        result = probe({"http://shop.klant.nl/": moved("https://shop.klant.nl/"), "https://shop.klant.nl/": (200, HTML)},
                       site=sub)
        self.assertEqual([v["start"] for v in result["variants"]], ["http://shop.klant.nl/", "https://shop.klant.nl/"])
        self.assertEqual(check_host_variants(result, sub)["status"], "nvt")
        self.assertEqual(check_http_redirect(result)["status"], "ok")

    def test_certificate_error(self):
        error = httpx.ConnectError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired (_ssl.c:1006)")
        result = probe(CLEAN, transport_kw={"errors": {HOME: error}})
        base = result["https"]
        self.assertTrue(base["cert_error"])
        verdict = check_https(result)
        self.assertEqual(verdict["status"], "error")
        self.assertIn("certificate has expired", verdict["message"])

    def test_redirect_loop_is_capped(self):
        result = probe({**CLEAN, "https://klant.nl/": moved("https://klant.nl/a"),
                        "https://klant.nl/a": moved("https://klant.nl/")})
        apex = next(v for v in result["variants"] if v["start"] == "https://klant.nl/")
        self.assertIn("redirects", apex["error"])
        self.assertEqual(len(apex["chain"]), golive_probes.MAX_HOPS + 1)

    def test_unsafe_url_is_not_requested(self):
        calls = []

        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(200)

        with patch.object(golive_probes, "is_safe_external_url", return_value=False):
            result = golive_probes.run_probes(SITE, transport=httpx.MockTransport(handler))
        self.assertEqual(calls, [])
        self.assertTrue(all("intern" in v["error"] for v in result["variants"]))


class NotFoundProbeTest(unittest.TestCase):
    PREFIX = "https://www.klant.nl/livegang-404-controle-*"

    def test_real_404(self):
        result = probe({**CLEAN, self.PREFIX: (404, HTML)})
        self.assertEqual(len(result["not_found"]), 2)
        self.assertTrue(result["not_found"][1]["start"].endswith("/"))
        self.assertEqual(check_not_found(result)["status"], "ok")

    def test_soft_404(self):
        result = probe({**CLEAN, self.PREFIX: (200, HTML)})
        self.assertEqual(check_not_found(result)["status"], "error")

    def test_redirect_to_home(self):
        result = probe({**CLEAN, self.PREFIX: moved(HOME)})
        verdict = check_not_found(result)
        self.assertEqual(verdict["status"], "error")
        self.assertIn("verwijst door", " ".join(verdict["evidence"]))

    def test_blocked(self):
        result = probe({**CLEAN, self.PREFIX: (403, HTML)})
        self.assertEqual(check_not_found(result)["status"], "unknown")


class FaviconProbeTest(unittest.TestCase):
    def test_link_icon_and_fallback(self):
        result = probe({**CLEAN, "https://www.klant.nl/icon.png": (200, {"content-type": "image/png"})},
                       icon_links=["https://www.klant.nl/icon.png", "https://www.klant.nl/b.png", "https://www.klant.nl/c.png"])
        urls = [c["url"] for c in result["favicon"]]
        self.assertEqual(urls, ["https://www.klant.nl/icon.png", "https://www.klant.nl/b.png",
                                "https://www.klant.nl/favicon.ico"])
        self.assertEqual([c["ok"] for c in result["favicon"]], [True, False, True])
        self.assertEqual(check_favicon(result)["status"], "ok")

    def test_html_instead_of_image(self):
        routes = {**CLEAN, "https://www.klant.nl/favicon.ico": moved(HOME)}
        result = probe(routes)
        self.assertEqual(result["favicon"][0]["content_type"], "text/html")
        self.assertEqual(check_favicon(result)["status"], "warning")


# --- page_hook in de inventaris ------------------------------------------------------

PAGE = """<html><head><title>{title}</title><meta name="viewport" content="width=device-width">
<link rel="canonical" href="{url}"></head><body><h1>{title}</h1>
<a href="/a/">A</a> <a href="/oud/">Oud</a> <a href="/weg/">Weg</a> <a href="/nergens/">Nergens</a>
<img src="/logo.png"></body></html>"""


def site_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    url = str(request.url)
    if path in ("/", "/a/"):
        return httpx.Response(200, headers=HTML, text=PAGE.format(title=path, url=url))
    if path == "/oud/":
        return httpx.Response(301, headers={"location": "https://www.klant.nl/a/"})
    if path == "/plaatje/":
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"png")
    return httpx.Response(404, headers=HTML, text="niet gevonden")


class PageHookTest(unittest.TestCase):
    SEEDS = [HOME, "https://www.klant.nl/a/", "https://www.klant.nl/oud/", "https://www.klant.nl/weg/",
             "https://www.klant.nl/plaatje/"]

    def run_inventory(self, hook=None):
        def client(*_args, **_kwargs):
            return httpx.AsyncClient(transport=httpx.MockTransport(site_handler), follow_redirects=False)

        with patch.object(inventory, "_new_client", side_effect=client), \
                patch.object(inventory, "is_safe_external_url", return_value=True):
            return asyncio.run(run_inventory(
                seed_urls=self.SEEDS, in_sitemap=True, follow_links=False, max_pages=50,
                concurrency=2, on_batch=lambda _batch: True, page_hook=hook,
            ))

    def test_called_once_per_parsed_page(self):
        calls = []

        def hook(rec, html, response):
            calls.append(rec.url)
            self.assertIn("<h1>", html)
            self.assertEqual(response.status_code, 200)

        records = self.run_inventory(hook)
        self.assertEqual(sorted(calls), [HOME, "https://www.klant.nl/a/"])
        self.assertEqual(len(records), 5)

    def test_results_identical_without_hook(self):
        def strip(records):
            return [{k: v for k, v in asdict(r).items() if k not in {"extra", "response_time_ms"}} for r in records]

        plain = self.run_inventory()
        hooked = self.run_inventory(make_page_hook(SITE))
        self.assertEqual(strip(plain), strip(hooked))
        self.assertTrue(all(r.extra == {} for r in plain))
        self.assertIn("golive", hooked[0].extra)
        broken = {b["url"] for b in plain[0].broken_links}
        self.assertEqual(broken, {"https://www.klant.nl/weg/", "https://www.klant.nl/nergens/"})

    def test_record_to_row_ignores_extra(self):
        from app.features.launch_checklist.worker.launch_scan import _record_to_row

        rec = PageRecord(url=HOME, path="/", in_sitemap=True, status_code=200)
        rec.extra["golive"] = {"forms": []}
        row = _record_to_row("scan-1", rec)
        self.assertFalse(hasattr(row, "extra"))
        self.assertEqual(row.url, HOME)


# --- worker -----------------------------------------------------------------------------

def _records():
    hook = make_page_hook(SITE)
    out = []
    for url in (HOME, "https://www.klant.nl/contact/"):
        rec = PageRecord(url=url, path="/", in_sitemap=True, status_code=200, final_url=url, final_status=200,
                         content_type="text/html", indexable=True)
        hook(rec, PAGE.format(title="x", url=url), None)
        out.append(rec)
    return out


class GoLiveWorkerTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        # `launch_scan_pages.created_at` heeft server_default now(); SQLite kent die functie niet.
        @event.listens_for(engine, "connect")
        def _sqlite_now(dbapi_connection, _record):
            dbapi_connection.create_function("now", 0, lambda: datetime.now(timezone.utc).isoformat(" "))

        LaunchScan.__table__.create(engine)
        LaunchScanPage.__table__.create(engine)
        self.Session = sessionmaker(bind=engine)

    def add_scan(self, **fields):
        now = datetime.now(timezone.utc)
        values = dict(
            id=str(uuid.uuid4()), customer_website_id="klant-1", phase=5, status="pending",
            base_url=HOME, total_urls=0, inventoried_urls=0, failed_urls=0, max_pages=500,
            vitals_max_pages=0, vitals_total=0, vitals_measured=0, created_by="user-1",
            created_at=now, updated_at=now,
        )
        values.update(fields)
        with self.Session() as db:
            db.add(LaunchScan(**values))
            db.commit()
        return values["id"]

    def scan(self, scan_id):
        with self.Session() as db:
            return db.get(LaunchScan, scan_id)

    def patches(self, *, probes=None):
        async def inventory_result(**kwargs):
            self.assertIsNotNone(kwargs.get("page_hook"))
            self.assertIsNotNone(kwargs.get("on_progress"))
            records = _records()
            kwargs["on_batch"](records)
            return records

        discovery = DiscoveryResult(urls=[HOME, "https://www.klant.nl/contact/"],
                                    sitemaps=["https://www.klant.nl/sitemap.xml"],
                                    robots_txt="User-agent: *\nSitemap: https://www.klant.nl/sitemap.xml\n",
                                    robots_status=200)
        probe_result = {"variants": [], "https": None, "origin": "https://www.klant.nl", "not_found": [], "favicon": []}
        return (
            patch.object(golive_scan, "SessionLocal", self.Session),
            patch.object(golive_scan, "discover_from_sitemaps", return_value=discovery),
            patch.object(golive_scan, "run_inventory", side_effect=inventory_result),
            patch.object(golive_scan, "run_probes", **({"side_effect": probes} if probes else {"return_value": probe_result})),
        )

    def test_run_completes_with_checklist_and_pages(self):
        scan_id = self.add_scan()
        p1, p2, p3, p4 = self.patches()
        with p1, p2, p3, p4 as run_probes:
            golive_scan.run_golive_scan_task.run(scan_id)
        scan = self.scan(scan_id)
        self.assertEqual(scan.status, "completed", scan.error_message)
        self.assertIsNotNone(scan.completed_at)
        self.assertEqual(scan.discovery_source, "sitemap")
        self.assertEqual(scan.total_urls, 2)
        self.assertIn("gl_viewport", scan.checklist["items"])
        self.assertEqual(scan.checklist["items"]["gl_viewport"]["status"], "ok")
        self.assertNotIn("gl_redirect_map", scan.checklist["items"])
        self.assertEqual(scan.summary_stats["pages"], 2)
        run_probes.assert_called_once()
        with self.Session() as db:
            self.assertEqual(db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == scan_id).count(), 2)

    def test_soft_timeout_marks_failed(self):
        scan_id = self.add_scan()
        p1, p2, p3, p4 = self.patches(probes=SoftTimeLimitExceeded())
        with p1, p2, p3, p4:
            golive_scan.run_golive_scan_task.run(scan_id)
        scan = self.scan(scan_id)
        self.assertEqual((scan.status, scan.error_message), ("failed", "Scan duurde te lang en is afgebroken."))

    def test_unexpected_error_marks_failed(self):
        scan_id = self.add_scan()
        p1, p2, p3, p4 = self.patches(probes=RuntimeError("kapot"))
        with p1, p2, p3, p4:
            golive_scan.run_golive_scan_task.run(scan_id)
        self.assertEqual((self.scan(scan_id).status, self.scan(scan_id).error_message), ("failed", "kapot"))

    def test_failed_scan_is_not_started(self):
        scan_id = self.add_scan(status="failed", error_message=INTERRUPTED_SCAN_MESSAGE)
        with patch.object(golive_scan, "SessionLocal", self.Session), \
                patch.object(golive_scan, "discover_from_sitemaps", side_effect=AssertionError("niet starten")):
            golive_scan.run_golive_scan_task.run(scan_id)
        self.assertEqual(self.scan(scan_id).status, "failed")

    def test_canceled_during_inventory_stops(self):
        scan_id = self.add_scan()
        p1, p2, p3, p4 = self.patches()

        async def cancel_and_return(**kwargs):
            with self.Session() as db:
                db.get(LaunchScan, scan_id).status = "canceled"
                db.commit()
            return _records()

        with p1, p2, patch.object(golive_scan, "run_inventory", side_effect=cancel_and_return), p4 as run_probes:
            golive_scan.run_golive_scan_task.run(scan_id)
        self.assertEqual(self.scan(scan_id).status, "canceled")
        run_probes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
