"""Dagelijkse sitemap-monitor: vergelijking en vangrails (puur), de worker tegen SQLite
in het geheugen (netwerk gepatcht) en de API-endpoints."""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import require_user_id
from app.db.models import (
    Base,
    CustomerWebsite,
    LaunchContentPage,
    LaunchScan,
    LaunchScanIssue,
    LaunchScanPage,
    LaunchSitemapSnapshot,
)
from app.db.session import get_db
from app.features.launch_checklist.router import router
from app.features.launch_checklist.services import discovery as discovery_module
from app.features.launch_checklist.services import geo_rebuild
from app.features.launch_checklist.services import sitemap_monitor as service
from app.features.launch_checklist.services.discovery import DiscoveryResult, discover_from_sitemaps, url_key
from app.features.launch_checklist.services.inventory import PageRecord
from app.features.launch_checklist.services.sitemap_monitor import (
    LOCK_KEY,
    MAX_RECENT_CHANGES,
    acquire_lock,
    change_items,
    diff_sitemap,
    drop_covered_f1_issues,
    merge_recent_changes,
    plan_run,
    release_lock,
    retry_later,
    snapshot_summary,
)
from app.features.launch_checklist.worker import sitemap_monitor as worker

BASE = "https://www.klant.nl/"
SITEMAP = "https://www.klant.nl/sitemap.xml"
NOW = datetime(2026, 11, 18, 5, 0, tzinfo=timezone.utc)
HOME = "https://www.klant.nl/"
OVER = "https://www.klant.nl/over-ons/"
NIEUW = "https://www.klant.nl/diensten/nieuw/"
NIEUW2 = "https://www.klant.nl/diensten/nog-een/"
GOOD_TITLE = "Nieuwe dienst van de klant in de regio Utrecht"  # 30-60 tekens
GOOD_META = (
    "Lees hoe de nieuwe dienst werkt, wat het kost en hoe je binnen een week start. "
    "Vraag direct een offerte aan."
)


def entries(*items):
    """(url, lastmod) → snapshot-entries."""
    return {url_key(url): {"url": url, "lastmod": lastmod} for url, lastmod in items}


def found(*items, failed=None, sitemaps=(SITEMAP,), skipped=0):
    """(url, lastmod) → DiscoveryResult zoals discover_from_sitemaps hem geeft."""
    return DiscoveryResult(
        urls=[url for url, _ in items],
        sitemaps=list(sitemaps),
        lastmod={url_key(url): lastmod for url, lastmod in items if lastmod},
        failed_sitemaps=list(failed or []),
        skipped_due_to_limit=skipped,
    )


class FakeRedis:
    """Genoeg van redis.Redis voor de lock (SET NX EX, GET, EXPIRE, het vrijgeef-script)."""

    def __init__(self):
        self.data: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def get(self, key):
        return self.data.get(key)

    def expire(self, key, _seconds):
        return key in self.data

    def eval(self, _script, _numkeys, key, token):
        if self.data.get(key) == token:
            del self.data[key]
            return 1
        return 0


# --- pure logica ---------------------------------------------------------------------

class DiffSitemapTest(unittest.TestCase):
    def test_new_changed_removed(self):
        before = entries((HOME, "2026-11-01"), (OVER, "2026-10-01"), ("https://www.klant.nl/weg/", None))
        diff = diff_sitemap(
            before,
            [HOME, OVER.rstrip("/"), NIEUW],  # zonder slash: zelfde url_key
            {url_key(HOME): "2026-11-17", url_key(OVER): "2026-10-01", url_key(NIEUW): "2026-11-17"},
        )
        self.assertEqual([i["url"] for i in diff["new"]], [NIEUW])
        self.assertEqual(diff["new"][0]["lastmod"], "2026-11-17")
        self.assertEqual([(i["url"], i["lastmod"], i["previous_lastmod"]) for i in diff["changed"]],
                         [(HOME, "2026-11-17", "2026-11-01")])
        self.assertEqual([i["url"] for i in diff["removed"]], ["https://www.klant.nl/weg/"])

    def test_changed_only_when_both_sides_have_lastmod(self):
        before = entries((HOME, None), (OVER, "2026-10-01"))
        diff = diff_sitemap(before, [HOME, OVER], {url_key(HOME): "2026-11-17"})
        self.assertEqual(diff, {"new": [], "changed": [], "removed": []})


class PlanRunTest(unittest.TestCase):
    def test_first_run_only_records_baseline(self):
        for previous in (None, {}):
            plan = plan_run(previous, found((HOME, "2026-11-01"), (OVER, None)), max_pages=40)
            self.assertEqual(plan.kind, "baseline")
            self.assertEqual(plan.targets, [])
            self.assertEqual(plan.entries, entries((HOME, "2026-11-01"), (OVER, None)))

    def test_empty_or_unreachable_sitemap_keeps_snapshot(self):
        before = entries((HOME, "2026-11-01"))
        unreachable = plan_run(before, DiscoveryResult(urls=[]), max_pages=40)
        self.assertEqual(unreachable.kind, "error")
        self.assertIn("Geen bereikbare sitemap", unreachable.error)
        self.assertEqual(unreachable.entries, before)
        empty = plan_run(before, found(), max_pages=40)
        self.assertEqual(empty.kind, "error")
        self.assertIn("geen pagina's", empty.error)
        self.assertEqual(plan_run(None, found(), max_pages=40).kind, "error")

    def test_changes(self):
        before = entries((HOME, "2026-11-01"), (OVER, "2026-10-01"), ("https://www.klant.nl/weg/", "2026-01-01"))
        plan = plan_run(before, found((HOME, "2026-11-17"), (OVER, "2026-10-01"), (NIEUW, None)), max_pages=40)
        self.assertEqual(plan.kind, "changes")
        self.assertEqual([(t["kind"], t["url"]) for t in plan.targets], [("new", NIEUW), ("changed", HOME)])
        self.assertEqual((plan.new_count, plan.changed_count), (1, 1))
        self.assertEqual([r["url"] for r in plan.removed], ["https://www.klant.nl/weg/"])
        self.assertEqual(plan.entries, entries((HOME, "2026-11-17"), (OVER, "2026-10-01"), (NIEUW, None)))
        self.assertIsNone(plan.sitemap_problem)

    def test_unchanged_still_updates_lastmod_silently(self):
        before = entries((HOME, None))
        plan = plan_run(before, found((HOME, "2026-11-17")), max_pages=40)
        self.assertEqual(plan.kind, "unchanged")
        self.assertEqual(plan.entries, entries((HOME, "2026-11-17")))

    def test_failed_child_sitemap_skips_removals(self):
        before = entries((HOME, "2026-11-01"), (OVER, "2026-10-01"))
        plan = plan_run(
            before, found((HOME, "2026-11-01"), (NIEUW, None), failed=["https://www.klant.nl/page-sitemap.xml"]),
            max_pages=40,
        )
        self.assertEqual(plan.kind, "changes")
        self.assertEqual([t["url"] for t in plan.targets], [NIEUW])  # nieuw wordt wel verwerkt
        self.assertEqual(plan.removed, [])
        self.assertEqual(plan.removals_skipped, 1)
        self.assertIn(url_key(OVER), plan.entries)  # blijft in de stand
        self.assertIn("page-sitemap.xml", plan.sitemap_problem)
        self.assertTrue(any("niet als verwijderd" in w for w in plan.warnings))

    def test_truncated_sitemap_skips_removals(self):
        before = entries((HOME, None), (OVER, None))
        plan = plan_run(before, found((HOME, None), skipped=5), max_pages=40)
        self.assertEqual(plan.kind, "unchanged")
        self.assertEqual(plan.removed, [])
        self.assertIn(url_key(OVER), plan.entries)
        self.assertIn("SITEMAP_MONITOR_MAX_URLS", plan.sitemap_problem)

    def test_cap_defers_the_rest_to_the_next_run(self):
        before = entries((HOME, "2026-11-01"), (OVER, "2026-10-01"))
        plan = plan_run(
            before, found((HOME, "2026-11-17"), (OVER, "2026-11-17"), (NIEUW, None), (NIEUW2, None)), max_pages=2)
        self.assertEqual([t["url"] for t in plan.targets], [NIEUW, NIEUW2])  # nieuw gaat voor gewijzigd
        self.assertEqual([t["url"] for t in plan.deferred], [OVER, HOME])  # oudste lastmod eerst
        # Uitgesteld gewijzigd: oude lastmod blijft, zodat de wijziging morgen weer gezien wordt.
        self.assertEqual(plan.entries[url_key(HOME)]["lastmod"], "2026-11-01")
        self.assertTrue(any("SITEMAP_MONITOR_MAX_PAGES_PER_RUN" in w for w in plan.warnings))

        plan = plan_run(before, found((HOME, None), (OVER, None), (NIEUW, None), (NIEUW2, None)), max_pages=1)
        self.assertEqual([t["url"] for t in plan.targets], [NIEUW])
        self.assertNotIn(url_key(NIEUW2), plan.entries)  # uitgesteld nieuw: morgen weer "nieuw"
        tomorrow = plan_run(plan.entries, found((HOME, None), (OVER, None), (NIEUW, None), (NIEUW2, None)),
                            max_pages=1)
        self.assertEqual([t["url"] for t in tomorrow.targets], [NIEUW2])

    def test_changed_pages_ordered_by_stored_lastmod(self):
        # Sitemaps die lastmod elke dag verschuiven: zonder ordening zouden steeds dezelfde
        # eerste pagina's (sitemapvolgorde) het plafond vullen.
        before = entries((HOME, "2026-11-10"), (OVER, "2026-01-01"), (NIEUW2, "2026-06-01"))
        today = found((HOME, "2026-11-18"), (OVER, "2026-11-18"), (NIEUW2, "2026-11-18"), (NIEUW, None))
        plan = plan_run(before, today, max_pages=2)
        self.assertEqual([t["url"] for t in plan.targets], [NIEUW, OVER])  # nieuw, dan oudste lastmod
        tomorrow = plan_run(plan.entries, found((HOME, "2026-11-19"), (OVER, "2026-11-19"),
                                                (NIEUW2, "2026-11-19"), (NIEUW, None)), max_pages=2)
        # OVER heeft nu de nieuwste opgeslagen lastmod; de uitgestelde schuiven naar voren.
        self.assertEqual([t["url"] for t in tomorrow.targets], [NIEUW2, HOME])

    def test_retry_later_restores_previous_entries(self):
        before = entries((HOME, "2026-11-01"))
        plan = plan_run(before, found((HOME, "2026-11-17"), (NIEUW, None)), max_pages=40)
        retried = retry_later(plan, before, {url_key(HOME), url_key(NIEUW)})
        self.assertEqual(retried.targets, [])
        self.assertEqual(retried.entries, before)  # oude lastmod terug, nieuwe pagina weg
        self.assertEqual(len(retried.deferred), 2)
        self.assertEqual(change_items(retried, NOW), [])
        self.assertIs(retry_later(plan, before, set()), plan)

    def test_lock_per_customer(self):
        fake = FakeRedis()
        with patch.object(service, "get_redis", return_value=fake):
            token = acquire_lock("klant")
            self.assertIsNotNone(token)
            self.assertIsNone(acquire_lock("klant"))  # bezet
            self.assertEqual(acquire_lock("klant", token), token)  # eigen lock (van "Nu controleren")
            self.assertIsNotNone(acquire_lock("andere-klant"))
            release_lock("klant", "iemand-anders")  # niet van ons: blijft staan
            self.assertEqual(fake.data[LOCK_KEY.format(customer_id="klant")], token)
            release_lock("klant", token)
            self.assertNotIn(LOCK_KEY.format(customer_id="klant"), fake.data)

    def test_recent_changes(self):
        before = entries((HOME, "2026-11-01"), ("https://www.klant.nl/weg/", None))
        plan = plan_run(before, found((HOME, "2026-11-17"), (NIEUW, None)), max_pages=40)
        items = change_items(plan, NOW)
        self.assertEqual(
            [(i["kind"], i["url"], i["lastmod"]) for i in items],
            [("new", NIEUW, None), ("changed", HOME, "2026-11-17"), ("removed", "https://www.klant.nl/weg/", None)],
        )
        self.assertEqual({i["detected_at"] for i in items}, {NOW.isoformat()})
        old = [{"kind": "new", "url": f"https://www.klant.nl/{i}/", "lastmod": None, "detected_at": "x"}
               for i in range(MAX_RECENT_CHANGES)]
        merged = merge_recent_changes(old, items)
        self.assertEqual(len(merged), MAX_RECENT_CHANGES)
        self.assertEqual(merged[:3], items)

    def test_snapshot_summary(self):
        self.assertEqual(snapshot_summary(None), {"total_urls": 0, "has_lastmod": False})
        self.assertEqual(snapshot_summary(entries((HOME, None), (OVER, "2026-01-01"))),
                         {"total_urls": 2, "has_lastmod": True})

    def test_c3_meta_points_replace_phase1_points_on_the_same_page(self):
        f1 = [
            {"issue_type": "title_missing", "page_id": "a"},
            {"issue_type": "meta_too_long", "page_id": "a"},
            {"issue_type": "title_missing", "page_id": "b"},
            {"issue_type": "status_4xx", "page_id": "a"},
        ]
        c3 = [{"issue_type": "c3_meta_title", "page_id": "a"}]
        self.assertEqual(
            [(i["issue_type"], i["page_id"]) for i in drop_covered_f1_issues(f1, c3)],
            [("meta_too_long", "a"), ("title_missing", "b"), ("status_4xx", "a")],
        )


class DiscoveryToPlanTest(unittest.TestCase):
    """lastmod uit een echte sitemap-XML (netwerk via MockTransport) komt in de vergelijking."""

    def discover(self, lastmod: str):
        xml = (
            '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<url><loc>{HOME}</loc><lastmod> {lastmod} </lastmod></url>"
            f"<url><loc>{OVER}</loc></url></urlset>"
        )
        responses = {"https://www.klant.nl/robots.txt": f"Sitemap: {SITEMAP}\n", SITEMAP: xml}

        def handler(request: httpx.Request) -> httpx.Response:
            body = responses.get(str(request.url))
            return httpx.Response(200 if body else 404, content=(body or "niet gevonden").encode())

        real_client = httpx.Client
        with patch.object(discovery_module, "is_safe_external_url", return_value=True), \
                patch.object(discovery_module.httpx, "Client",
                             side_effect=lambda **o: real_client(transport=httpx.MockTransport(handler), **o)):
            return discover_from_sitemaps(BASE, max_urls=1000)

    def test_lastmod_change_is_detected(self):
        baseline = plan_run(None, self.discover("2026-11-01"), max_pages=40)
        self.assertEqual(baseline.entries[url_key(HOME)]["lastmod"], "2026-11-01")
        self.assertIsNone(baseline.entries[url_key(OVER)]["lastmod"])
        plan = plan_run(baseline.entries, self.discover("2026-11-17"), max_pages=40)
        self.assertEqual([(t["kind"], t["url"]) for t in plan.targets], [("changed", HOME)])


# --- worker tegen SQLite -------------------------------------------------------------

def record(url, *, title=None, meta=None, status=200):
    path = url.split("klant.nl", 1)[1] or "/"
    return PageRecord(
        url=url, path=path, in_sitemap=True, status_code=status, final_status=status,
        content_type="text/html; charset=utf-8", indexable=status == 200,
        title=title, title_length=len(title) if title else None,
        meta_description=meta, meta_description_length=len(meta) if meta else None,
        h1=["Kop"], h1_count=1, lang="nl", word_count=600, main_word_count=500,
        internal_links=5, external_links=1, images_total=0, images_missing_alt=0,
        open_graph={"og:title": "x", "og:description": "x", "og:image": "x"},
        response_time_ms=200, size_bytes=50_000, http_version="HTTP/2",
    )


def content(*, title=None, meta=None):
    return {
        "title": title, "meta_description": meta,
        "headings": [{"level": 1, "text": "Kop"}, {"level": 2, "text": "Sub"}],
        "body_text": "tekst " * 600, "first_paragraph": "Kort antwoord.", "word_count": 600,
        "images": [], "links": [], "signals": {"lists": 2, "cta_texts": ["Bel ons"]},
    }


class _WorkerBase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.customer_id = self.add_customer("Klant")
        self.nulmeting_id = self.add_scan(phase=1, status="completed")

        # Netwerk en AI vervangen.
        self.discovery = found()
        self.records: dict[str, PageRecord] = {}
        self.contents: dict[str, dict] = {}
        self.inventory_calls: list[list[str]] = []

        async def fake_inventory(**kwargs):
            self.inventory_calls.append(list(kwargs["seed_urls"]))
            assert kwargs["follow_links"] is False
            out = [self.records[url] for url in kwargs["seed_urls"]]
            kwargs["on_batch"](out)
            return out

        async def fake_refetch(targets, _root, _concurrency, on_batch):
            on_batch(len(targets))
            return {}

        async def fake_fetch_content(targets, _root, _concurrency, on_batch):
            on_batch(len(targets))
            return {t["id"]: self.contents[t["url"]] for t in targets if t["url"] in self.contents}

        async def fake_check_links(_urls, _known_ok, _on_progress=None):
            return {}

        self._patch(worker, "SessionLocal", self.Session)
        self._patch(worker, "discover_from_sitemaps", lambda *_a, **_k: self.discovery)
        self._patch(worker, "run_inventory", fake_inventory)
        self._patch(worker, "_refetch", fake_refetch)
        self._patch(worker, "_fetch_content", fake_fetch_content)
        self._patch(worker, "_check_links", fake_check_links)
        self._patch(geo_rebuild, "classify_with_llm", lambda *_a, **_k: {})
        self.redis = FakeRedis()
        self._patch(service, "get_redis", lambda: self.redis)

    def _patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def add_customer(self, name, *, enabled=True):
        customer_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(
                id=customer_id, name=name, base_url=BASE, domain="klant.nl", created_by="user-1",
                sitemap_monitor_enabled=enabled, created_at=NOW, updated_at=NOW,
            ))
            db.commit()
        return customer_id

    def add_scan(self, *, phase, status, customer_id=None, **fields):
        scan_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(LaunchScan(
                id=scan_id, customer_website_id=customer_id or self.customer_id, phase=phase, status=status,
                base_url=BASE, total_urls=0, inventoried_urls=0, failed_urls=0, max_pages=500,
                vitals_max_pages=0, vitals_total=0, vitals_measured=0, created_by="user-1",
                # updated_at = nu: anders herstelt scan_recovery een 'lopende' scan als vastgelopen.
                **{"created_at": NOW - timedelta(days=30), "updated_at": datetime.now(timezone.utc), **fields},
            ))
            db.commit()
        return scan_id

    def set_snapshot(self, *items):
        with self.Session() as db:
            db.merge(LaunchSitemapSnapshot(
                customer_website_id=self.customer_id, entries=entries(*items), recent_changes=[],
                created_at=NOW, updated_at=NOW,
            ))
            db.commit()

    def snapshot(self):
        with self.Session() as db:
            return db.get(LaunchSitemapSnapshot, self.customer_id)

    def monitor(self):
        with self.Session() as db:
            return db.query(LaunchScan).filter(LaunchScan.phase == 6).one_or_none()

    def issues(self, url=None):
        with self.Session() as db:
            rows = db.query(LaunchScanIssue).all()
            return {i.issue_type: i for i in rows if url is None or i.url == url}, rows

    def run_monitor(self):
        return worker.run_sitemap_monitor_task.run(self.customer_id)


class SitemapMonitorWorkerTest(_WorkerBase):
    def test_first_run_records_baseline_without_scanning(self):
        self.discovery = found((HOME, "2026-11-01"), (OVER, None))
        self.assertEqual(self.run_monitor(), "baseline")
        self.assertEqual(self.inventory_calls, [])
        self.assertIsNone(self.monitor())
        snapshot = self.snapshot()
        self.assertEqual(snapshot.entries, entries((HOME, "2026-11-01"), (OVER, None)))
        self.assertIsNotNone(snapshot.checked_at)
        self.assertIsNone(snapshot.changed_at)

    def test_no_changes_only_updates_checked_at(self):
        self.set_snapshot((HOME, "2026-11-01"))
        self.discovery = found((HOME, "2026-11-01"))
        self.assertEqual(self.run_monitor(), "unchanged")
        self.assertEqual(self.inventory_calls, [])
        self.assertIsNotNone(self.snapshot().checked_at)
        self.assertIsNone(self.monitor())

    def test_empty_sitemap_keeps_snapshot(self):
        self.set_snapshot((HOME, "2026-11-01"), (OVER, None))
        self.discovery = found()
        self.assertEqual(self.run_monitor(), "error")
        snapshot = self.snapshot()
        self.assertEqual(len(snapshot.entries), 2)
        self.assertIn("geen pagina's", snapshot.last_error)

    def test_skipped_while_another_scan_runs(self):
        self.set_snapshot((HOME, "2026-11-01"))
        self.add_scan(phase=2, status="fetching")
        self._patch(worker, "discover_from_sitemaps", Mock(side_effect=AssertionError("niet ophalen")))
        self.assertEqual(self.run_monitor(), "skipped")
        snapshot = self.snapshot()
        # Wel gemeld (zodat "Nu controleren" stopt met pollen), de stand blijft staan.
        self.assertIsNotNone(snapshot.checked_at)
        self.assertEqual(snapshot.last_error, worker.SKIPPED_MESSAGE)
        self.assertEqual(snapshot.entries, entries((HOME, "2026-11-01")))
        self.assertEqual(self.redis.data, {})  # lock weer vrij

    def test_stale_active_scan_is_recovered_first(self):
        self.set_snapshot((HOME, "2026-11-01"))
        stale = self.add_scan(phase=2, status="fetching", updated_at=datetime.now(timezone.utc) - timedelta(hours=2))
        self.discovery = found((HOME, "2026-11-01"))
        self.assertEqual(self.run_monitor(), "unchanged")
        with self.Session() as db:
            self.assertEqual(db.get(LaunchScan, stale).status, "failed")
        self.assertIsNone(self.snapshot().last_error)

    def test_second_run_while_locked_does_nothing(self):
        self.set_snapshot((HOME, "2026-11-01"))
        key = LOCK_KEY.format(customer_id=self.customer_id)
        self.redis.data[key] = "andere-run"
        self._patch(worker, "discover_from_sitemaps", Mock(side_effect=AssertionError("niet ophalen")))
        self.assertEqual(self.run_monitor(), "locked")
        self.assertIsNone(self.snapshot().checked_at)  # de lopende run meldt zelf
        self.assertEqual(self.redis.data[key], "andere-run")  # andermans lock niet vrijgegeven
        # Met het token van "Nu controleren" mag de run wel.
        self._patch(worker, "discover_from_sitemaps", lambda *_a, **_k: found((HOME, "2026-11-01")))
        self.assertEqual(worker.run_sitemap_monitor_task.run(self.customer_id, "andere-run"), "unchanged")
        self.assertNotIn(key, self.redis.data)

    def test_skipped_without_nulmeting(self):
        other = self.add_customer("Zonder nulmeting")
        self.assertEqual(worker.run_sitemap_monitor_task.run(other), "skipped")

    def test_new_page_is_scanned_with_phase1_and_content_checks(self):
        self.set_snapshot((HOME, "2026-11-01"))
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, "2026-11-17"))
        self.records[NIEUW] = record(NIEUW)  # geen title, geen meta description
        self.contents[NIEUW] = content()
        self.assertEqual(self.run_monitor(), "completed")

        self.assertEqual(self.inventory_calls, [[NIEUW]])
        scan = self.monitor()
        self.assertEqual((scan.phase, scan.status), (6, "completed"))
        self.assertEqual(scan.created_by, "user-1")
        stats = scan.summary_stats
        self.assertEqual((stats["new"], stats["changed"], stats["removed"], stats["scanned"]), (1, 0, 0, 1))
        self.assertEqual(stats["pages"], 1)
        self.assertEqual(stats["open_issues"], stats["issues"])

        by_type, _ = self.issues(NIEUW)
        # Fase-3-punten vervangen de fase-1-punten voor meta title/description.
        self.assertIn("c3_meta_title", by_type)
        self.assertIn("c3_meta_description", by_type)
        self.assertNotIn("title_missing", by_type)
        self.assertNotIn("meta_missing", by_type)
        with self.Session() as db:
            page = db.query(LaunchScanPage).one()
            self.assertEqual(by_type["c3_meta_title"].page_id, page.id)
            content_page = db.query(LaunchContentPage).one()
            self.assertEqual(content_page.source_page_id, page.id)
            # Zonder fase-3-scan geen oordeel over interne links.
            self.assertNotIn("c3_internal_links", content_page.checks)
            # Eigen woordtelling staat in de signalen (te weinig pagina's voor site-brede blokken).
            self.assertEqual(content_page.signals["own_word_count"], content_page.word_count)
            self.assertEqual(content_page.signals["site_wide_words"], 0)
            self.assertEqual(content_page.signals["lists"], 2)

        snapshot = self.snapshot()
        self.assertIn(url_key(NIEUW), snapshot.entries)
        self.assertEqual(snapshot.recent_changes[0]["kind"], "new")
        self.assertEqual(snapshot.recent_changes[0]["url"], NIEUW)
        self.assertIsNotNone(snapshot.changed_at)
        self.assertIsNone(snapshot.last_error)

    def test_rescan_keeps_status_and_monday_link(self):
        self.set_snapshot((HOME, "2026-11-01"))
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, "2026-11-10"))
        self.records[NIEUW] = record(NIEUW)
        self.contents[NIEUW] = content()
        self.assertEqual(self.run_monitor(), "completed")
        with self.Session() as db:
            for issue in db.query(LaunchScanIssue).all():
                if issue.issue_type == "c3_meta_title":
                    issue.status, issue.external_provider = "doorgezet", "monday"
                    issue.external_item_id, issue.external_url = "m-1", "https://monday.example/items/m-1"
                elif issue.issue_type == "c3_meta_description":
                    issue.status = "genegeerd"
            db.commit()

        # Tweede run: zelfde pagina gewijzigd, zelfde bevindingen.
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, "2026-11-17"))
        self.assertEqual(self.run_monitor(), "completed")
        by_type, rows = self.issues(NIEUW)
        self.assertEqual(len(rows), len({(r.issue_type, r.url) for r in rows}))  # geen dubbele punten
        self.assertEqual(by_type["c3_meta_title"].status, "doorgezet")
        self.assertEqual(by_type["c3_meta_title"].external_item_id, "m-1")
        self.assertEqual(by_type["c3_meta_description"].status, "genegeerd")
        with self.Session() as db:
            self.assertEqual(db.query(LaunchScanPage).count(), 1)  # vervangen, niet erbij
            self.assertEqual(db.query(LaunchContentPage).count(), 1)
            page_id = db.query(LaunchScanPage.id).scalar()
        self.assertEqual(by_type["c3_meta_title"].page_id, page_id)
        self.assertEqual(self.monitor().summary_stats["changed"], 1)
        self.assertEqual(self.snapshot().recent_changes[0]["kind"], "changed")

        # Derde run: de titel is opgelost; het gekoppelde punt blijft staan als 'opgelost'.
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, "2026-11-18"))
        self.records[NIEUW] = record(NIEUW, title=GOOD_TITLE)
        self.contents[NIEUW] = content(title=GOOD_TITLE)
        self.assertEqual(self.run_monitor(), "completed")
        by_type, _ = self.issues(NIEUW)
        self.assertEqual(by_type["c3_meta_title"].status, "opgelost")
        self.assertEqual(by_type["c3_meta_title"].external_item_id, "m-1")
        with self.Session() as db:
            self.assertEqual(by_type["c3_meta_title"].page_id, db.query(LaunchScanPage.id).scalar())

    def test_removed_page_resolves_open_issues(self):
        self.set_snapshot((HOME, "2026-11-01"))
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, "2026-11-10"))
        self.records[NIEUW] = record(NIEUW)
        self.contents[NIEUW] = content()
        self.run_monitor()
        self.inventory_calls.clear()

        self.discovery = found((HOME, "2026-11-01"))
        self.assertEqual(self.run_monitor(), "completed")
        self.assertEqual(self.inventory_calls, [])
        _, rows = self.issues(NIEUW)
        self.assertTrue(rows)
        self.assertEqual({r.status for r in rows}, {"opgelost"})
        snapshot = self.snapshot()
        self.assertNotIn(url_key(NIEUW), snapshot.entries)
        self.assertEqual(snapshot.recent_changes[0]["kind"], "removed")
        self.assertEqual(self.monitor().summary_stats["open_issues"], 0)

    def test_failed_child_sitemap_does_not_remove_pages(self):
        self.set_snapshot((HOME, "2026-11-01"), (OVER, None))
        self.discovery = found((HOME, "2026-11-01"), failed=["https://www.klant.nl/page-sitemap.xml"])
        self.assertEqual(self.run_monitor(), "unchanged")
        snapshot = self.snapshot()
        self.assertIn(url_key(OVER), snapshot.entries)
        self.assertIn("page-sitemap.xml", snapshot.last_error)
        self.assertEqual(snapshot.recent_changes, [])

    def test_cap_per_run(self):
        self.set_snapshot((HOME, "2026-11-01"))
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, None), (NIEUW2, None))
        for url in (NIEUW, NIEUW2):
            self.records[url] = record(url, title=GOOD_TITLE, meta=GOOD_META)
            self.contents[url] = content(title=GOOD_TITLE, meta=GOOD_META)
        self._patch(worker.settings, "sitemap_monitor_max_pages_per_run", 1)
        self.assertEqual(self.run_monitor(), "completed")
        self.assertEqual(self.inventory_calls, [[NIEUW]])
        self.assertNotIn(url_key(NIEUW2), self.snapshot().entries)
        self.assertTrue(any("SITEMAP_MONITOR_MAX_PAGES_PER_RUN" in w for w in self.monitor().warnings))
        self.assertEqual(self.run_monitor(), "completed")
        self.assertEqual(self.inventory_calls[-1], [NIEUW2])

    def test_phase3_content_is_context_for_duplicates_and_links(self):
        phase3 = self.add_scan(phase=3, status="completed", checklist={"items": {}})
        with self.Session() as db:
            db.add(LaunchContentPage(
                id=str(uuid.uuid4()), scan_id=phase3, url=OVER, path="/over-ons/", page_type="over_ons",
                title=GOOD_TITLE, meta_description="Iets anders dan de nieuwe pagina, lang genoeg om mee te tellen.",
                links=[{"url": NIEUW, "text": "nieuwe dienst", "in_content": True}],
                analysis_status="none", problem_count=0, created_at=NOW,
            ))
            db.commit()
        self.set_snapshot((HOME, "2026-11-01"), (OVER, None))
        self.discovery = found((HOME, "2026-11-01"), (OVER, None), (NIEUW, None))
        self.records[NIEUW] = record(NIEUW, title=GOOD_TITLE, meta=GOOD_META)
        self.contents[NIEUW] = content(title=GOOD_TITLE, meta=GOOD_META)
        self.assertEqual(self.run_monitor(), "completed")
        by_type, _ = self.issues(NIEUW)
        self.assertIn("meerdere", by_type["c3_meta_title"].description)  # dubbel met de fase-3-pagina
        with self.Session() as db:
            checks = db.query(LaunchContentPage).filter(LaunchContentPage.scan_id != phase3).one().checks
            # De fase-3-scan blijft ongemoeid.
            self.assertEqual(db.query(LaunchContentPage).filter(LaunchContentPage.scan_id == phase3).count(), 1)
        self.assertIn("c3_internal_links", checks)


class SitemapMonitorRobustnessTest(_WorkerBase):
    def first_run(self):
        """Run met NIEUW (lastmod 10-11): punten c3_meta_title (doorgezet, Monday) en
        c3_meta_description (genegeerd)."""
        self.set_snapshot((HOME, "2026-11-01"))
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, "2026-11-10"))
        self.records[NIEUW] = record(NIEUW)
        self.contents[NIEUW] = content()
        self.assertEqual(self.run_monitor(), "completed")
        with self.Session() as db:
            for issue in db.query(LaunchScanIssue).all():
                if issue.issue_type == "c3_meta_title":
                    issue.status, issue.external_provider = "doorgezet", "monday"
                    issue.external_item_id = "m-1"
                elif issue.issue_type == "c3_meta_description":
                    issue.status = "genegeerd"
            db.commit()
        _, rows = self.issues()
        return {(r.id, r.issue_type, r.status, r.external_item_id) for r in rows}

    def test_content_fetch_failure_on_rescan_keeps_everything(self):
        before = self.first_run()
        with self.Session() as db:
            page_id = db.query(LaunchScanPage.id).scalar()
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, "2026-11-17"))
        del self.contents[NIEUW]  # inhoud ophalen mislukt
        self.assertEqual(self.run_monitor(), "completed")

        _, rows = self.issues()
        self.assertEqual({(r.id, r.issue_type, r.status, r.external_item_id) for r in rows}, before)
        self.assertNotIn("title_missing", {r.issue_type for r in rows})
        with self.Session() as db:
            self.assertEqual(db.query(LaunchScanPage.id).scalar(), page_id)
            self.assertEqual(db.query(LaunchContentPage).count(), 1)
        snapshot = self.snapshot()
        self.assertEqual(snapshot.entries[url_key(NIEUW)]["lastmod"], "2026-11-10")  # volgende run opnieuw
        self.assertIn("niet gescand", snapshot.last_error)
        self.assertIn(NIEUW, snapshot.last_error)
        self.assertEqual([c["kind"] for c in snapshot.recent_changes], ["new"])  # geen "changed" gemeld
        scan = self.monitor()
        self.assertTrue(any("niet gescand" in w for w in scan.warnings))
        self.assertEqual((scan.summary_stats["changed"], scan.summary_stats["not_scanned"]), (0, 1))

        # Volgende run lukt wel: dan pas wordt de wijziging verwerkt.
        self.contents[NIEUW] = content()
        self.assertEqual(self.run_monitor(), "completed")
        by_type, _ = self.issues(NIEUW)
        self.assertEqual(by_type["c3_meta_title"].external_item_id, "m-1")
        self.assertEqual(self.snapshot().entries[url_key(NIEUW)]["lastmod"], "2026-11-17")
        self.assertIsNone(self.snapshot().last_error)

    def test_unreachable_or_blocked_new_page_is_retried_and_reported(self):
        self.set_snapshot((HOME, "2026-11-01"))
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, None), (NIEUW2, None))
        timeout = PageRecord(url=NIEUW, path="/diensten/nieuw/", in_sitemap=True, error="Timeout")
        blocked = record(NIEUW2, status=403)
        self.records.update({NIEUW: timeout, NIEUW2: blocked})
        self.assertEqual(self.run_monitor(), "completed")
        with self.Session() as db:
            self.assertEqual(db.query(LaunchScanPage).count(), 0)
            self.assertEqual(db.query(LaunchScanIssue).count(), 0)  # geen fetch_error/status_4xx
        snapshot = self.snapshot()
        self.assertNotIn(url_key(NIEUW), snapshot.entries)
        self.assertNotIn(url_key(NIEUW2), snapshot.entries)
        self.assertIn("Timeout", snapshot.last_error)
        self.assertIn("HTTP 403", snapshot.last_error)
        self.assertIsNone(snapshot.changed_at)  # er is niets verwerkt
        self.assertEqual(self.run_monitor(), "completed")
        self.assertEqual(self.inventory_calls[-1], [NIEUW, NIEUW2])  # opnieuw geprobeerd

    def test_real_404_is_a_finding(self):
        self.set_snapshot((HOME, "2026-11-01"))
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, None))
        self.records[NIEUW] = record(NIEUW, status=404)
        self.assertEqual(self.run_monitor(), "completed")
        by_type, _ = self.issues(NIEUW)
        self.assertIn("status_4xx", by_type)
        self.assertIn(url_key(NIEUW), self.snapshot().entries)
        self.assertIsNone(self.snapshot().last_error)

    def test_failure_halfway_leaves_snapshot_and_issues(self):
        before = self.first_run()
        entries_before = dict(self.snapshot().entries)
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, "2026-11-17"))

        async def broken(*_args, **_kwargs):
            raise RuntimeError("kapot")

        self._patch(worker, "_check_links", broken)
        self.assertEqual(self.run_monitor(), "failed")
        scan = self.monitor()
        self.assertEqual(scan.status, "failed")
        self.assertIn("kapot", scan.error_message)
        snapshot = self.snapshot()
        self.assertEqual(snapshot.entries, entries_before)
        self.assertIn("kapot", snapshot.last_error)
        _, rows = self.issues()
        self.assertEqual({(r.id, r.issue_type, r.status, r.external_item_id) for r in rows}, before)
        self.assertEqual(self.redis.data, {})

    def test_removed_only_without_monitor_scan(self):
        self.set_snapshot((HOME, "2026-11-01"), (OVER, None))
        self.discovery = found((HOME, "2026-11-01"))
        self.assertEqual(self.run_monitor(), "completed")
        self.assertIsNone(self.monitor())
        self.assertEqual(self.inventory_calls, [])
        snapshot = self.snapshot()
        self.assertEqual(snapshot.entries, entries((HOME, "2026-11-01")))
        self.assertEqual([(c["kind"], c["url"]) for c in snapshot.recent_changes], [("removed", OVER)])
        self.assertIsNotNone(snapshot.changed_at)

    def test_linked_phase1_issue_resolved_and_coming_back(self):
        self.set_snapshot((HOME, "2026-11-01"))
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, "2026-11-10"))
        self.records[NIEUW] = record(NIEUW, status=404)
        self.run_monitor()
        with self.Session() as db:
            issue = db.query(LaunchScanIssue).filter(LaunchScanIssue.issue_type == "status_4xx").one()
            issue.status, issue.external_item_id = "doorgezet", "m-9"
            db.commit()

        # Opgelost: de pagina werkt weer. Het gekoppelde punt blijft als 'opgelost'.
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, "2026-11-12"))
        self.records[NIEUW] = record(NIEUW, title=GOOD_TITLE, meta=GOOD_META)
        self.contents[NIEUW] = content(title=GOOD_TITLE, meta=GOOD_META)
        self.run_monitor()
        by_type, _ = self.issues(NIEUW)
        self.assertEqual((by_type["status_4xx"].status, by_type["status_4xx"].external_item_id), ("opgelost", "m-9"))

        # Komt terug: weer 'doorgezet' met dezelfde koppeling, en maar één rij.
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, "2026-11-15"))
        self.records[NIEUW] = record(NIEUW, status=404)
        self.run_monitor()
        _, rows = self.issues(NIEUW)
        back = [r for r in rows if r.issue_type == "status_4xx"]
        self.assertEqual(len(back), 1)
        self.assertEqual((back[0].status, back[0].external_item_id), ("doorgezet", "m-9"))
        with self.Session() as db:
            self.assertEqual(back[0].page_id, db.query(LaunchScanPage.id).scalar())

    def test_removed_page_is_no_context_for_duplicates(self):
        phase3 = self.add_scan(phase=3, status="completed", checklist={"items": {}})
        with self.Session() as db:
            db.add(LaunchContentPage(
                id=str(uuid.uuid4()), scan_id=phase3, url=OVER, path="/over-ons/", page_type="over_ons",
                title=GOOD_TITLE, analysis_status="none", problem_count=0, created_at=NOW,
            ))
            db.commit()
        self.set_snapshot((HOME, "2026-11-01"), (OVER, None))
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, None))  # OVER is verwijderd
        self.records[NIEUW] = record(NIEUW, title=GOOD_TITLE, meta=GOOD_META)
        self.contents[NIEUW] = content(title=GOOD_TITLE, meta=GOOD_META)
        self.assertEqual(self.run_monitor(), "completed")
        by_type, _ = self.issues(NIEUW)
        self.assertNotIn("c3_meta_title", by_type)  # geen "dubbele titel" met een verwijderde pagina


class DispatchTest(_WorkerBase):
    def test_only_enabled_customers_with_nulmeting(self):
        disabled = self.add_customer("Uit", enabled=False)
        self.add_scan(phase=1, status="completed", customer_id=disabled)
        no_nulmeting = self.add_customer("Geen nulmeting")
        self.add_scan(phase=1, status="failed", customer_id=no_nulmeting)
        delay = Mock()
        self._patch(worker.run_sitemap_monitor_task, "delay", delay)
        self.assertEqual(worker.run_sitemap_monitor_dispatch_task.run(), [self.customer_id])
        delay.assert_called_once_with(self.customer_id)

    def test_global_switch_off(self):
        delay = Mock()
        self._patch(worker.run_sitemap_monitor_task, "delay", delay)
        self._patch(worker.settings, "sitemap_monitor_enabled", False)
        self.assertEqual(worker.run_sitemap_monitor_dispatch_task.run(), [])
        delay.assert_not_called()


class EnableAfterFirstNulmetingTest(_WorkerBase):
    def enabled(self, customer_id):
        with self.Session() as db:
            return db.get(CustomerWebsite, customer_id).sitemap_monitor_enabled

    def enable(self, customer_id, scan_id):
        with self.Session() as db:
            return service.enable_after_first_nulmeting(db, customer_id, scan_id)

    def test_new_customer_starts_disabled(self):
        customer_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(
                id=customer_id, name="Nieuw", base_url=BASE, domain="klant.nl", created_by="user-1",
                created_at=NOW, updated_at=NOW,
            ))
            db.commit()
        self.assertFalse(self.enabled(customer_id))

    def test_first_completed_nulmeting_enables(self):
        customer_id = self.add_customer("Nieuw", enabled=False)
        scan_id = self.add_scan(phase=1, status="completed", customer_id=customer_id)
        self.assertTrue(self.enable(customer_id, scan_id))
        self.assertTrue(self.enabled(customer_id))
        with self.Session() as db:
            self.assertNotEqual(db.get(CustomerWebsite, customer_id).updated_at.replace(tzinfo=None),
                                NOW.replace(tzinfo=None))

    def test_later_nulmeting_keeps_manual_off(self):
        customer_id = self.add_customer("Nieuw", enabled=False)
        first = self.add_scan(phase=1, status="completed", customer_id=customer_id)
        self.assertTrue(self.enable(customer_id, first))
        with self.Session() as db:  # handmatig uitgezet
            db.get(CustomerWebsite, customer_id).sitemap_monitor_enabled = False
            db.commit()
        second = self.add_scan(phase=1, status="completed", customer_id=customer_id)
        self.assertFalse(self.enable(customer_id, second))
        self.assertFalse(self.enabled(customer_id))

    def test_only_completed_phase1_counts(self):
        customer_id = self.add_customer("Nieuw", enabled=False)
        for phase, status in ((1, "failed"), (1, "canceled"), (1, "analyzing"), (2, "completed"), (6, "completed")):
            scan_id = self.add_scan(phase=phase, status=status, customer_id=customer_id)
            self.assertFalse(self.enable(customer_id, scan_id), (phase, status))
            self.assertFalse(self.enabled(customer_id), (phase, status))
        # Mislukte en andere scans tellen niet als "eerdere nulmeting".
        scan_id = self.add_scan(phase=1, status="completed", customer_id=customer_id)
        self.assertTrue(self.enable(customer_id, scan_id))
        self.assertTrue(self.enabled(customer_id))

    def test_scan_of_other_customer_or_unknown_does_nothing(self):
        customer_id = self.add_customer("Nieuw", enabled=False)
        self.assertFalse(self.enable(customer_id, self.nulmeting_id))  # scan van een andere klant
        self.assertFalse(self.enable(customer_id, "onbekend"))
        self.assertFalse(self.enabled(customer_id))


# --- API -----------------------------------------------------------------------------

class SitemapMonitorEndpointTest(_WorkerBase):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        app.include_router(router)

        def override_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_user_id] = lambda: "user-1"
        self.client = TestClient(app)
        self.url = f"/api/launch-checklist/customers/{self.customer_id}/sitemap-monitor"

    def test_status_before_first_run(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["customer_id"], self.customer_id)
        self.assertTrue(data["enabled"])
        self.assertTrue(data["has_nulmeting"])
        self.assertIsNone(data["scan_id"])
        self.assertFalse(data["running"])
        self.assertEqual((data["total_urls"], data["open_issues"], data["recent_changes"]), (0, 0, []))
        self.assertEqual(self.client.get("/api/launch-checklist/customers/onbekend/sitemap-monitor").status_code, 404)

    def test_status_after_run_and_customer_list(self):
        self.set_snapshot((HOME, "2026-11-01"))
        self.discovery = found((HOME, "2026-11-01"), (NIEUW, "2026-11-17"))
        self.records[NIEUW] = record(NIEUW)
        self.contents[NIEUW] = content()
        self.run_monitor()
        data = self.client.get(self.url).json()
        scan = self.monitor()
        self.assertEqual(data["scan_id"], scan.id)
        self.assertEqual(data["scan_status"], "completed")
        self.assertEqual(data["total_urls"], 2)
        self.assertTrue(data["has_lastmod"])
        self.assertGreater(data["open_issues"], 0)
        self.assertEqual(data["recent_changes"][0]["kind"], "new")
        self.assertEqual(data["recent_changes"][0]["url"], NIEUW)
        self.assertEqual(data["recent_changes"][0]["lastmod"], "2026-11-17")
        self.assertIsNotNone(data["changed_at"])

        customers = self.client.get("/api/launch-checklist/customers").json()["customers"]
        item = next(c for c in customers if c["id"] == self.customer_id)
        self.assertEqual(item["monitor_open_issues"], data["open_issues"])
        self.assertIsNotNone(item["monitor_changed_at"])

        scans = self.client.get("/api/launch-checklist/scans", params={"phase": 6}).json()
        self.assertEqual([s["id"] for s in scans["items"]], [scan.id])

    def test_patch_toggle(self):
        response = self.client.patch(self.url, json={"enabled": False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["enabled"])
        with self.Session() as db:
            self.assertFalse(db.get(CustomerWebsite, self.customer_id).sitemap_monitor_enabled)
        self.assertEqual(self.client.patch(self.url, json={}).status_code, 422)

    def test_run_now(self):
        delay = Mock()
        self._patch(worker.run_sitemap_monitor_task, "delay", delay)
        response = self.client.post(f"{self.url}/run")
        self.assertEqual(response.status_code, 200, response.text)
        delay.assert_called_once()
        customer_id, token = delay.call_args.args
        self.assertEqual(customer_id, self.customer_id)
        # De lock staat al vast terwijl de taak in de wachtrij staat: tweede klik → 409.
        self.assertEqual(self.redis.data[LOCK_KEY.format(customer_id=self.customer_id)], token)
        response = self.client.post(f"{self.url}/run")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Er loopt al een scan voor deze klant.")
        self.redis.data.clear()

        running = self.add_scan(phase=2, status="fetching")
        response = self.client.post(f"{self.url}/run")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Er loopt al een scan voor deze klant.")
        with self.Session() as db:
            db.get(LaunchScan, running).status = "completed"
            db.get(LaunchScan, self.nulmeting_id).status = "failed"
            db.commit()
        response = self.client.post(f"{self.url}/run")
        self.assertEqual(response.status_code, 400)
        self.assertIn("nulmeting", response.json()["detail"])
        self.assertEqual(delay.call_count, 1)


if __name__ == "__main__":
    unittest.main()
