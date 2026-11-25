"""Signalen en overzicht van het bureau-overzicht (features/agency_overview/services/overview en signals).

Draait tegen een in-memory SQLite-database; Search Console en ProRankTracker zijn vervangen (geen
netwerk). `today` is steeds vast, zodat de datumregels testbaar zijn.
"""
import unittest
import uuid
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    CustomerRankSnapshot,
    CustomerWebsite,
    LaunchScan,
    LaunchSitemapSnapshot,
    MonthlyReport,
    WorkItem,
)
from app.features.agency_overview.services import overview as overview_module
from app.features.agency_overview.services import signals as sig
from app.features.agency_overview.services.overview import build_overview
from app.services.search_console.client import SearchConsoleServiceError

USER = "user-1"
TZ = ZoneInfo("Europe/Amsterdam")
DAY3 = date(2026, 11, 3)
DAY20 = date(2026, 11, 20)


def _noon(day):
    return datetime.combine(day, time(12, 0), tzinfo=TZ).astimezone(timezone.utc)


def _drop(keyword, rank, month):
    return {"keyword": keyword, "rank": rank, "month_ago_rank": month, "url": None}


class _Base(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, autoflush=False)
        self.sites = []
        self.gsc_configured = True
        self.prt_configured = True
        self.sites_error = None
        self.a = self.add_customer("Advocaat A", "advocaat-a.nl")
        self.b = self.add_customer("Bakkerij B", "bakkerij-b.nl")
        patches = [
            patch.object(overview_module.gsc, "is_configured", side_effect=lambda: self.gsc_configured),
            patch.object(overview_module.prt, "is_configured", side_effect=lambda: self.prt_configured),
            patch.object(overview_module, "cached_sites", side_effect=self.fake_sites),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def fake_sites(self, **_kwargs):
        if self.sites_error is not None:
            raise self.sites_error
        return self.sites

    # --- opzet ---

    def add(self, *rows):
        with self.Session() as db:
            db.add_all(rows)
            db.commit()

    def add_customer(self, name, domain, *, monitor=False, gsc_property=None):
        cid = str(uuid.uuid4())
        now = _noon(DAY3) - timedelta(days=200)
        self.add(CustomerWebsite(id=cid, name=name, base_url=f"https://{domain}/", domain=domain,
                                 sitemap_monitor_enabled=monitor, gsc_property=gsc_property,
                                 created_by=USER, created_at=now, updated_at=now))
        # Standaard staat elke klant in Search Console.
        self.sites.append({"site_url": f"sc-domain:{domain}", "permission": "siteOwner"})
        return cid

    def add_snapshot(self, customer, state="ok", *, keywords=10, top10=4, month_ago=5, drops=(), message=None,
                     fetched_at=None):
        ok = state == "ok"
        self.add(CustomerRankSnapshot(
            customer_website_id=customer, state=state, message=message,
            keywords=keywords if ok else None, top10=top10 if ok else None,
            top10_month_ago=month_ago if ok else None, drops=list(drops),
            fetched_at=fetched_at or _noon(DAY3), created_at=_noon(DAY3), updated_at=_noon(DAY3),
        ))

    def add_scan(self, customer, phase, status, at):
        self.add(LaunchScan(id=str(uuid.uuid4()), customer_website_id=customer, phase=phase, status=status,
                            base_url="https://x.nl/", created_by=USER, created_at=at, updated_at=at))

    def add_card(self, customer, status, *, severity="middel", created=None, updated=None, today=DAY3):
        now = _noon(today)
        self.add(WorkItem(
            id=str(uuid.uuid4()), customer_website_id=customer, source="manual", status=status, kind="update",
            title="Taak", severity=severity, position=1.0, created_by=USER,
            created_at=now - timedelta(days=created or 0), updated_at=now - timedelta(days=updated or 0),
        ))

    def add_report(self, customer, month, status):
        self.add(MonthlyReport(id=str(uuid.uuid4()), customer_website_id=customer, month=month, status=status,
                               created_by=USER, created_at=_noon(DAY3), updated_at=_noon(DAY3)))

    def overview(self, today=DAY20):
        with self.Session() as db:
            return build_overview(db, today=today)

    def signals(self, today=DAY20, kind=None, customer="any"):
        found = self.overview(today)["signals"]
        if kind:
            found = [s for s in found if s["kind"] == kind]
        if customer != "any":
            found = [s for s in found if s["customer_id"] == customer]
        return found


class DropSignalTest(_Base):
    def test_largest_drop_with_others(self):
        self.add_snapshot(self.a, drops=[
            _drop("advocaat arbeidsrecht", 11, 4), _drop("ontslag", 20, 9), _drop("x", None, 15)])
        found = self.signals(kind="daling")
        self.assertEqual(len(found), 1)
        s = found[0]
        self.assertEqual(s["text"], '"advocaat arbeidsrecht" gezakt van #4 naar #11 (en 2 andere)')
        self.assertEqual(s["id"], f"daling:{self.a}")
        self.assertEqual((s["severity"], s["customer_name"]), ("hoog", "Advocaat A"))
        self.assertEqual(s["link"], {"type": "customer_home", "customer_id": self.a, "month": None})

    def test_out_of_top_100(self):
        self.add_snapshot(self.a, drops=[_drop("weg", None, 7)])
        self.assertEqual(self.signals(kind="daling")[0]["text"], '"weg" uit de top 100 gezakt (was #7)')

    def test_no_drops_no_signal(self):
        self.add_snapshot(self.a)
        self.assertEqual(self.signals(kind="daling"), [])


class FailureSignalTest(_Base):
    def test_latest_failed_scan(self):
        self.add_scan(self.a, 4, "failed", datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc))
        s = self.signals(kind="storing", customer=self.a)[0]
        self.assertEqual(s["text"], "Kwartaalscan mislukt op 18 nov")
        self.assertEqual(s["link"], {"type": "seo_geo", "customer_id": self.a, "month": None})
        self.assertEqual(s["severity"], "hoog")

    def test_failed_scan_followed_by_newer_scan(self):
        self.add_scan(self.a, 1, "failed", datetime(2026, 11, 1, tzinfo=timezone.utc))
        self.add_scan(self.a, 1, "completed", datetime(2026, 11, 2, tzinfo=timezone.utc))
        self.assertEqual(self.signals(kind="storing"), [])

    def test_sitemap_monitor_error_only_when_enabled(self):
        on = self.add_customer("Monitor aan", "aan.nl", monitor=True)
        off = self.add_customer("Monitor uit", "uit.nl", monitor=False)
        for cid in (on, off):
            self.add(LaunchSitemapSnapshot(customer_website_id=cid, entries={}, recent_changes=[],
                                           checked_at=datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc),
                                           last_error="Sitemap onbereikbaar", created_at=_noon(DAY3),
                                           updated_at=_noon(DAY3)))
        found = self.signals(kind="storing")
        self.assertEqual([s["customer_id"] for s in found], [on])
        self.assertEqual(found[0]["text"], "Sitemap-monitor mislukt op 19 nov")
        self.assertEqual(found[0]["link"]["type"], "seo_geo")

    def test_snapshot_error(self):
        self.add_snapshot(self.a, "error", message="Posities niet opgehaald uit ProRankTracker: Timeout.")
        s = self.signals(kind="storing")[0]
        self.assertEqual(s["text"], "Posities niet opgehaald uit ProRankTracker")
        self.assertEqual(s["link"]["type"], "customer_home")

    def test_not_tracked_is_no_failure(self):
        self.add_snapshot(self.a, "not_tracked")
        self.assertEqual(self.signals(kind="storing"), [])

    def test_search_console_no_property(self):
        self.sites = [site for site in self.sites if "advocaat-a" not in site["site_url"]]
        s = self.signals(kind="storing")[0]
        self.assertEqual((s["customer_id"], s["text"]), (self.a, "Staat niet in Search Console"))
        self.assertEqual(s["link"]["type"], "customer_profile")

    def test_search_console_manual_property_missing(self):
        cid = self.add_customer("Handmatig", "handmatig.nl", gsc_property="https://oud.handmatig.nl/")
        s = self.signals(kind="storing", customer=cid)[0]
        self.assertEqual(s["text"], "Geen toegang (meer) tot de gekozen Search Console-property")

    def test_several_problems_one_signal(self):
        self.add_scan(self.a, 2, "failed", datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc))
        self.add_scan(self.a, 4, "failed", datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc))
        self.sites = [site for site in self.sites if "advocaat-a" not in site["site_url"]]
        found = self.signals(kind="storing")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["text"], "GEO/SEO-scan mislukt op 10 nov (en 2 andere)")
        self.assertEqual(found[0]["link"]["type"], "seo_geo")


class BureauSignalTest(_Base):
    def test_search_console_not_configured(self):
        self.gsc_configured = False
        self.sites = []  # zou anders bij elke klant "niet in Search Console" geven
        found = self.signals(kind="storing")
        self.assertEqual(len(found), 1)
        s = found[0]
        self.assertEqual(s["id"], "storing:bureau:search_console")
        self.assertIsNone(s["customer_id"])
        self.assertIsNone(s["customer_name"])
        self.assertEqual(s["link"], {"type": "none", "customer_id": None, "month": None})
        self.assertIn("Search Console is niet gekoppeld", s["text"])

    def test_search_console_token_expired(self):
        self.sites_error = SearchConsoleServiceError("Het Search Console-token is verlopen.", code="token_expired")
        found = self.signals(kind="storing")
        self.assertEqual([s["id"] for s in found], ["storing:bureau:search_console"])
        self.assertEqual(found[0]["text"], "Het Search Console-token is verlopen")

    def test_search_console_timeout_is_skipped(self):
        self.sites_error = SearchConsoleServiceError("Timeout.", code="timeout")
        with self.assertLogs(overview_module.logger, "WARNING"):
            self.assertEqual(self.signals(kind="storing"), [])

    def test_proranktracker_not_configured(self):
        self.prt_configured = False
        self.add_snapshot(self.a, "not_configured")
        found = self.signals(kind="storing")
        self.assertEqual([s["id"] for s in found], ["storing:bureau:proranktracker"])
        self.assertIn("ProRankTracker is niet gekoppeld", found[0]["text"])

    def test_proranktracker_token_refused(self):
        message = ("Posities niet opgehaald uit ProRankTracker: ProRankTracker weigert het API-token "
                   "(ongeldig of verlopen).")
        self.add_snapshot(self.a, "error", message=message)
        self.add_snapshot(self.b, "error", message=message)
        found = self.signals(kind="storing")
        self.assertEqual([s["id"] for s in found], ["storing:bureau:proranktracker"])
        self.assertEqual(self.overview()["kpis"]["customers_attention"], 0)


class WorkSignalTest(_Base):
    def test_review_older_than_7_days(self):
        self.add_card(self.a, "review", updated=8, created=30, today=DAY20)
        self.add_card(self.a, "review", updated=8, created=30, today=DAY20)
        self.add_card(self.a, "review", updated=6, created=30, today=DAY20)
        s = self.signals(kind="werk")[0]
        self.assertEqual(s["text"], "2 kaarten staan langer dan 7 dagen in Review")
        self.assertEqual((s["severity"], s["link"]["type"]), ("middel", "work_board"))
        self.assertEqual(s["link"]["customer_id"], self.a)

    def test_high_todo_older_than_14_days(self):
        self.add_card(self.a, "todo", severity="hoog", created=15, today=DAY20)
        self.add_card(self.a, "todo", severity="middel", created=40, today=DAY20)
        self.add_card(self.a, "todo", severity="hoog", created=13, today=DAY20)
        self.add_card(self.a, "doing", severity="hoog", created=40, today=DAY20)
        found = self.signals(kind="werk")
        self.assertEqual([s["text"] for s in found],
                         ["1 kaart staat met hoge prioriteit langer dan 14 dagen in Te doen"])

    def test_both_rules_one_signal(self):
        self.add_card(self.a, "review", updated=10, today=DAY20)
        self.add_card(self.a, "todo", severity="hoog", created=20, today=DAY20)
        found = self.signals(kind="werk")
        self.assertEqual([s["text"] for s in found], ["1 kaart staat langer dan 7 dagen in Review (en 1 andere)"])

    def test_open_tasks_counts(self):
        self.add_card(self.a, "todo", severity="hoog")
        self.add_card(self.a, "doing")
        self.add_card(self.b, "review", severity="hoog")
        self.add_card(self.b, "done", severity="hoog")
        data = self.overview(DAY3)
        self.assertEqual(data["kpis"]["open_tasks"], 3)
        self.assertEqual(data["kpis"]["open_tasks_high"], 2)
        tasks = {c["id"]: c["open_tasks"] for c in data["customers"]}
        self.assertEqual(tasks, {self.a: 2, self.b: 1})

    def test_sync_failure_does_not_break_overview(self):
        self.add_card(self.a, "todo")
        with patch("app.features.work_queue.services.board.apply_groups", side_effect=RuntimeError("stuk")), \
                self.assertLogs("app.features.work_queue.services.board", "ERROR"):
            data = self.overview(DAY3)
        self.assertEqual(data["kpis"]["open_tasks"], 1)


class ReportSignalTest(_Base):
    def test_day_3_without_report(self):
        found = self.signals(DAY3, kind="rapport", customer=self.a)
        self.assertEqual(len(found), 1)
        s = found[0]
        self.assertEqual(s["text"], "Maandrapport oktober nog niet gemaakt; de posities gelden t/m 7 november")
        self.assertEqual(s["link"], {"type": "monthly_report", "customer_id": self.a, "month": "2026-10"})
        self.assertEqual(s["id"], f"rapport:{self.a}")

    def test_day_3_completed_report(self):
        self.add_report(self.a, "2026-10", "completed")
        self.assertEqual(self.signals(DAY3, kind="rapport", customer=self.a), [])
        self.assertEqual(len(self.signals(DAY3, kind="rapport", customer=self.b)), 1)

    def test_day_3_report_in_progress(self):
        self.add_report(self.a, "2026-10", "writing")
        self.assertIn("nog niet klaar", self.signals(DAY3, kind="rapport", customer=self.a)[0]["text"])

    def test_day_7_and_day_8(self):
        self.assertEqual(len(self.signals(date(2026, 11, 7), kind="rapport")), 2)
        self.assertEqual(self.signals(date(2026, 11, 8), kind="rapport"), [])

    def test_day_20_without_report(self):
        self.assertEqual(self.signals(DAY20, kind="rapport"), [])

    def test_failed_report_all_month(self):
        self.add_report(self.a, "2026-10", "failed")
        found = self.signals(DAY20, kind="rapport")
        self.assertEqual([s["customer_id"] for s in found], [self.a])
        self.assertEqual(found[0]["text"], "Maandrapport oktober is mislukt; maak het opnieuw")
        self.assertEqual(found[0]["link"]["month"], "2026-10")

    def test_customer_added_this_month_has_no_report_signal(self):
        with self.Session() as db:
            db.get(CustomerWebsite, self.a).created_at = _noon(date(2026, 11, 2))
            db.commit()
        self.assertEqual([s["customer_id"] for s in self.signals(DAY3, kind="rapport")], [self.b])

    def test_older_month_does_not_count(self):
        self.add_report(self.a, "2026-09", "failed")
        self.assertEqual(self.signals(DAY20, kind="rapport"), [])

    def test_january_asks_for_december(self):
        s = self.signals(date(2027, 1, 2), kind="rapport", customer=self.a)[0]
        self.assertEqual(s["link"]["month"], "2026-12")
        self.assertTrue(s["text"].startswith("Maandrapport december nog niet gemaakt; de posities gelden t/m 7 januari"))


class OverviewTest(_Base):
    def test_signal_order(self):
        c = self.add_customer("Cafe C", "cafe-c.nl")
        self.add_snapshot(c, drops=[_drop("koffie", 15, 3)])
        self.add_snapshot(self.a, drops=[_drop("advocaat", 15, 3)])
        self.add_scan(self.b, 1, "failed", datetime(2026, 11, 1, tzinfo=timezone.utc))
        self.add_card(self.b, "review", updated=10, today=DAY3)
        self.gsc_configured = False
        found = self.signals(DAY3)
        order = [(s["kind"], s["customer_name"]) for s in found]
        self.assertEqual(order, [
            ("daling", "Advocaat A"),
            ("daling", "Cafe C"),
            ("storing", None),
            ("storing", "Bakkerij B"),
            ("werk", "Bakkerij B"),
            ("rapport", "Advocaat A"),
            ("rapport", "Bakkerij B"),
            ("rapport", "Cafe C"),
        ])

    def test_sort_key_puts_high_before_medium(self):
        work = sig.work_signal("x", "Aap", 1, 0)
        drop = sig.drop_signal("y", "Zebra", [_drop("k", 30, 4)])
        low = sig.Signal(kind="daling", severity="laag", customer_id="z", customer_name="Aap", text="t",
                         link_type="none")
        self.assertEqual([s.customer_id for s in sig.sort_signals([low, work, drop])], ["y", "x", "z"])

    def test_customers_and_kpis(self):
        c = self.add_customer("Cafe C", "cafe-c.nl")
        d = self.add_customer("Drukkerij D", "drukkerij-d.nl")
        self.add_snapshot(self.a, keywords=60, top10=22, month_ago=17, fetched_at=_noon(DAY20) - timedelta(hours=2))
        self.add_snapshot(self.b, keywords=12, top10=3, month_ago=None, fetched_at=_noon(DAY20) - timedelta(hours=5))
        self.add_snapshot(c, "error", message="Timeout", fetched_at=_noon(DAY20) - timedelta(hours=9))
        self.add_card(self.b, "todo")
        self.add_card(self.b, "todo")
        self.add_card(d, "doing")
        data = self.overview(DAY20)

        self.assertEqual(data["week"], 47)
        self.assertEqual(data["kpis"], {"customers": 4, "customers_attention": 1, "open_tasks": 3,
                                        "open_tasks_high": 0})
        # Oudste fetched_at van de snapshots met state ok (de fout telt niet mee).
        self.assertEqual(datetime.fromisoformat(data["rankings_fetched_at"]),
                         _noon(DAY20) - timedelta(hours=5))
        rows = data["customers"]
        self.assertEqual([r["name"] for r in rows], ["Cafe C", "Bakkerij B", "Drukkerij D", "Advocaat A"])
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(by_name["Advocaat A"], {
            "id": self.a, "name": "Advocaat A", "rank_state": "ok", "keywords": 60, "top10": 22,
            "top10_delta": 5, "open_tasks": 0, "signal_count": 0,
        })
        self.assertEqual((by_name["Bakkerij B"]["top10"], by_name["Bakkerij B"]["top10_delta"]), (3, None))
        self.assertEqual((by_name["Cafe C"]["rank_state"], by_name["Cafe C"]["top10"]), ("error", None))
        self.assertEqual(by_name["Cafe C"]["signal_count"], 1)
        self.assertEqual((by_name["Drukkerij D"]["rank_state"], by_name["Drukkerij D"]["keywords"]),
                         ("missing", None))

    def test_no_snapshots(self):
        data = self.overview(DAY20)
        self.assertIsNone(data["rankings_fetched_at"])
        self.assertEqual(data["signals"], [])
        self.assertEqual(data["kpis"]["customers_attention"], 0)


if __name__ == "__main__":
    unittest.main()
