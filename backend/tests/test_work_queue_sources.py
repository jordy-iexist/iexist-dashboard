"""Bronnen van de werkvoorraad: scan, concurrentieanalyse en aanpassingen (de database-adapters).

Draait tegen een in-memory SQLite-database; geen netwerk. De sessies hebben `autoflush=False`,
net als de app.
"""
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    CompetitorAnalysis,
    CompetitorAnalysisAction,
    CompetitorAnalysisKeyword,
    CustomerWebsite,
    LaunchChecklistState,
    LaunchContentPage,
    LaunchContentSuggestion,
    LaunchScan,
    LaunchScanIssue,
    SiteChange,
    User,
    WorkItem,
)
from app.features.launch_checklist.services.discovery import url_key
from app.features.site_changes.services.sources import suggestion_entries
from app.features.work_queue.services.sources_analysis import analysis_adapter
from app.features.work_queue.services.sources_scan import SITE_KEY, scan_adapter
from app.features.work_queue.services.sources_site_changes import site_changes_adapter
from app.features.work_queue.services.sync import apply_groups, mark_removed
from app.features.work_queue.services.types import Adapter, WorkQueueConflict

USER = "user-1"
NOW = datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc)
BASE = "https://klant.nl/"


def _at(days):
    return NOW - timedelta(days=days)


class _Base(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, autoflush=False)
        with self.Session() as db:
            db.add(User(id=USER, email="jan@iexist.nl", password_hash="x", created_at=NOW, updated_at=NOW))
            db.commit()
        self.customer = self.add_customer("Klant A")
        self.other = self.add_customer("Klant B")

    def add(self, *rows):
        with self.Session() as db:
            db.add_all(rows)
            db.commit()

    def add_customer(self, name):
        customer_id = str(uuid.uuid4())
        self.add(CustomerWebsite(id=customer_id, name=name, base_url=BASE, domain="klant.nl",
                                 created_by=USER, created_at=NOW, updated_at=NOW))
        return customer_id

    # --- scans ---

    def add_scan(self, phase, *, days=10, status="completed", customer=None, period=None, completed=True):
        scan_id = str(uuid.uuid4())
        self.add(LaunchScan(
            id=scan_id, customer_website_id=customer or self.customer, phase=phase, status=status, base_url=BASE,
            period=period, created_by=USER, created_at=_at(days), updated_at=_at(days),
            completed_at=_at(days) if completed else None,
        ))
        return scan_id

    def add_issue(self, scan_id, issue_type, url, *, status="open", item_id=None, severity="middel",
                  category="techniek", details=None, days=10, title=None):
        issue_id = str(uuid.uuid4())
        self.add(LaunchScanIssue(
            id=issue_id, scan_id=scan_id, issue_type=issue_type, category=category, severity=severity,
            title=title or f"{issue_type} {url}", description="-", url=url, details=details, status=status,
            external_provider="monday" if item_id else None, external_item_id=item_id,
            created_at=_at(days), updated_at=_at(days),
        ))
        return issue_id

    def issue_status(self, issue_id):
        with self.Session() as db:
            row = db.get(LaunchScanIssue, issue_id)
            return row.status, row.updated_at

    # --- kaarten ---

    def collect(self, adapter, customer_ids=None):
        with self.Session() as db:
            return adapter.collect(db, customer_ids)

    def sync(self, adapter, customer_ids=None, now=NOW):
        with self.Session() as db:
            groups = adapter.collect(db, customer_ids)
            result = apply_groups(db, groups, sources={adapter.source}, customer_ids=customer_ids, now=now)
            db.commit()
        return result

    def card_id(self, **filters):
        with self.Session() as db:
            query = db.query(WorkItem.id)
            for name, value in filters.items():
                query = query.filter(getattr(WorkItem, name) == value)
            return query.one()[0]

    def card(self, card_id):
        with self.Session() as db:
            row = db.get(WorkItem, card_id)
            _ = row.items
            db.expunge_all()
            return row

    def act(self, adapter, action, card_id, now=NOW):
        with self.Session() as db:
            card = db.get(WorkItem, card_id)
            getattr(adapter, action)(db, card, USER, now)
            db.commit()


def _by_key(groups):
    return {(g.customer_id, g.group_key): g for g in groups}


class AdapterShapeTests(unittest.TestCase):
    def test_protocol(self):
        for adapter, source in ((scan_adapter, "scan"), (analysis_adapter, "analysis"),
                                (site_changes_adapter, "site_changes")):
            with self.subTest(source=source):
                self.assertIsInstance(adapter, Adapter)
                self.assertEqual(adapter.source, source)


# --- scan --------------------------------------------------------------------------------


class ScanCollectTests(_Base):
    def test_bundles_per_issue_type_over_phase_1_and_monitor(self):
        phase1 = self.add_scan(1, days=20)
        monitor = self.add_scan(6, days=30, status="inventory")  # loopt nu, eerder voltooid
        old = self.add_issue(phase1, "title_too_long", "https://klant.nl/a/", days=20, category="on-page")
        new = self.add_issue(monitor, "title_too_long", "https://klant.nl/a", days=1, severity="hoog",
                             category="on-page")
        self.add_issue(phase1, "title_too_long", "https://klant.nl/b", days=20, severity="laag", category="on-page")
        # Pad i.p.v. URL (fase 4/monitor kan een pad opslaan).
        self.add_issue(monitor, "title_too_long", "/c?x=1", days=1, category="on-page")

        [group] = self.collect(scan_adapter)

        self.assertEqual((group.customer_id, group.source, group.group_key), (self.customer, "scan", "title_too_long"))
        self.assertEqual(group.title, "Title te lang")
        self.assertEqual(group.kind, "content")
        self.assertEqual(group.severity, "hoog")
        self.assertEqual([item.key for item in group.items],
                         ["klant.nl/a", "klant.nl/b", "klant.nl/c?x=1"])
        first = group.items[0]
        self.assertEqual((first.title, first.url, first.severity), ("/a", "https://klant.nl/a", "hoog"))
        self.assertEqual(sorted(first.ref["issue_ids"]), sorted([old, new]))
        self.assertEqual((first.ref["phase"], first.ref["scan_id"]), (6, monitor))
        self.assertEqual(group.items[2].url, "https://klant.nl/c?x=1")

    def test_site_wide_phase_2_issue_counts(self):
        geo = self.add_scan(2)
        self.add_issue(geo, "geo_llms_txt", None, category="ai", severity="hoog")
        [group] = self.collect(scan_adapter)
        [item] = group.items
        self.assertEqual((item.key, item.title, item.url), (SITE_KEY, "Hele site", None))
        self.assertEqual(group.kind, "techniek")
        self.assertEqual(item.ref["phase"], 2)

    def test_forwarded_in_other_scan_excludes_key(self):
        phase1 = self.add_scan(1, days=20)
        phase4 = self.add_scan(4, days=5, period="2026-Q4")
        monitor = self.add_scan(6, days=30)
        self.add_issue(phase1, "status_4xx", "https://klant.nl/a", status="doorgezet", item_id="m1", days=20)
        self.add_issue(monitor, "status_4xx", "https://klant.nl/a", days=1)
        self.add_issue(phase1, "status_4xx", "https://klant.nl/b", status="opgelost", item_id="m2", days=20)
        self.add_issue(phase4, "status_4xx", "https://klant.nl/b", days=2)
        self.add_issue(monitor, "status_4xx", "https://klant.nl/c", days=1)

        [group] = self.collect(scan_adapter)
        self.assertEqual([item.key for item in group.items], ["klant.nl/c"])

    def test_ignored_and_resolved_do_not_count(self):
        phase1 = self.add_scan(1, days=20)
        monitor = self.add_scan(6, days=30)
        self.add_issue(phase1, "h1_missing", "https://klant.nl/a", status="genegeerd")
        self.add_issue(phase1, "h1_missing", "https://klant.nl/b", status="opgelost")
        # Nieuwste rij wint: eerder open, nu opgelost → dicht; eerder opgelost, nu open → open.
        self.add_issue(phase1, "h1_missing", "https://klant.nl/c", days=20)
        self.add_issue(monitor, "h1_missing", "https://klant.nl/c", status="opgelost", days=1)
        self.add_issue(phase1, "h1_missing", "https://klant.nl/d", status="opgelost", days=20)
        self.add_issue(monitor, "h1_missing", "https://klant.nl/d", days=1)

        [group] = self.collect(scan_adapter)
        self.assertEqual([item.key for item in group.items], ["klant.nl/d"])

    def test_ai_mirrors_do_not_count(self):
        content = self.add_scan(3)
        self.add_issue(content, "c3_meta_title", "https://klant.nl/a", details={"source": "ai", "evidence": []},
                       category="content")
        self.add_issue(content, "c3_faq", "https://klant.nl/a", details={"evidence": []}, category="content")
        self.add_issue(content, "c3_faq", "https://klant.nl/b", details=["lijst"], category="content")
        groups = self.collect(scan_adapter)
        self.assertEqual([g.group_key for g in groups], ["c3_faq"])
        self.assertEqual(len(groups[0].items), 2)

    def test_only_completed_scans(self):
        done = self.add_scan(1, days=20)
        self.add_scan(1, days=1, status="analyzing", completed=False)
        running = self.add_scan(1, days=0, status="failed", completed=False)
        never_done_monitor = self.add_scan(6, days=1, status="inventory", completed=False)
        self.add_issue(done, "lang_missing", "https://klant.nl/a")
        self.add_issue(running, "lang_missing", "https://klant.nl/b")
        self.add_issue(never_done_monitor, "lang_missing", "https://klant.nl/c")
        # Een oudere voltooide scan van dezelfde fase telt niet: alleen de laatste.
        older = self.add_scan(1, days=40)
        self.add_issue(older, "lang_missing", "https://klant.nl/d", days=40)

        [group] = self.collect(scan_adapter)
        self.assertEqual([item.key for item in group.items], ["klant.nl/a"])

    def test_kind_per_category_and_fallback_title(self):
        scan = self.add_scan(1)
        cases = {
            "slow_response": ("performance", "techniek"),
            "ai_llms_txt": ("ai", "techniek"),
            "meta_missing": ("on-page", "content"),
            "thin_content": ("content", "content"),
            "onbekend_type": ("iets", "techniek"),
        }
        for issue_type, (category, _kind) in cases.items():
            self.add_issue(scan, issue_type, "https://klant.nl/a", category=category, title="Eigen titel")
        groups = {g.group_key: g for g in self.collect(scan_adapter)}
        for issue_type, (_category, kind) in cases.items():
            with self.subTest(issue_type=issue_type):
                self.assertEqual(groups[issue_type].kind, kind)
        self.assertEqual(groups["onbekend_type"].title, "Eigen titel")
        self.assertEqual(groups["slow_response"].title, "Trage serverrespons")

    def test_checklist_push_hides_site_wide_issue(self):
        geo = self.add_scan(2)
        content = self.add_scan(3)
        quarterly = self.add_scan(4, period="2026-Q4")
        self.add_issue(geo, "geo_llms_txt", None)
        self.add_issue(geo, "geo_faq_schema", None)
        self.add_issue(content, "c3_landing_pages", None, category="content")
        self.add_issue(content, "c3_faq", "https://klant.nl/a", category="content")  # per pagina: blijft
        self.add_issue(quarterly, "c4_ai_scan", None, category="ai")
        self.add_issue(quarterly, "c4_search_console", None)
        self.add(
            LaunchChecklistState(id=str(uuid.uuid4()), customer_website_id=self.customer, item_key="llms_txt",
                                 period="", external_item_id="m1", updated_at=NOW),
            LaunchChecklistState(id=str(uuid.uuid4()), customer_website_id=self.customer, item_key="c3_landing_pages",
                                 period="", external_item_id="m2", updated_at=NOW),
            LaunchChecklistState(id=str(uuid.uuid4()), customer_website_id=self.customer, item_key="c3_faq",
                                 period="", external_item_id="m3", updated_at=NOW),
            LaunchChecklistState(id=str(uuid.uuid4()), customer_website_id=self.customer, item_key="c4_ai_scan",
                                 period="2026-Q4", external_item_id="m4", updated_at=NOW),
            # Andere ronde: telt niet.
            LaunchChecklistState(id=str(uuid.uuid4()), customer_website_id=self.customer,
                                 item_key="c4_search_console", period="2026-Q3", external_item_id="m5",
                                 updated_at=NOW),
            # Andere klant: telt niet.
            LaunchChecklistState(id=str(uuid.uuid4()), customer_website_id=self.other, item_key="faq_schema",
                                 period="", external_item_id="m6", updated_at=NOW),
        )
        groups = sorted(g.group_key for g in self.collect(scan_adapter))
        self.assertEqual(groups, ["c3_faq", "c4_search_console", "geo_faq_schema"])

    def test_two_customers_in_one_collect(self):
        mine = self.add_scan(1)
        theirs = self.add_scan(1, customer=self.other)
        self.add_issue(mine, "h1_missing", "https://klant.nl/a")
        self.add_issue(theirs, "h1_missing", "https://klant.nl/a", severity="hoog")
        self.add_issue(theirs, "lang_missing", "https://klant.nl/a")

        groups = _by_key(self.collect(scan_adapter))
        self.assertEqual(sorted(groups), sorted([(self.customer, "h1_missing"), (self.other, "h1_missing"),
                                                 (self.other, "lang_missing")]))
        self.assertEqual(groups[(self.other, "h1_missing")].severity, "hoog")
        self.assertEqual(groups[(self.customer, "h1_missing")].severity, "middel")
        only = self.collect(scan_adapter, {self.other})
        self.assertEqual({g.customer_id for g in only}, {self.other})
        self.assertEqual(self.collect(scan_adapter, set()), [])


class ScanWriteTests(_Base):
    def setUp(self):
        super().setUp()
        self.phase1 = self.add_scan(1, days=20)
        self.monitor = self.add_scan(6, days=30)
        self.a_old = self.add_issue(self.phase1, "h1_missing", "https://klant.nl/a", days=20)
        self.a_new = self.add_issue(self.monitor, "h1_missing", "https://klant.nl/a", days=1)
        self.b = self.add_issue(self.phase1, "h1_missing", "https://klant.nl/b", days=20)
        self.c_resolved = self.add_issue(self.phase1, "h1_missing", "https://klant.nl/c", status="opgelost")
        self.c_open = self.add_issue(self.monitor, "h1_missing", "https://klant.nl/c", days=1)
        self.other_type = self.add_issue(self.phase1, "lang_missing", "https://klant.nl/a")
        self.sync(scan_adapter)
        self.card_key = self.card_id(group_key="h1_missing")

    def test_complete_resolves_open_rows_and_updates_snapshot(self):
        # Na de laatste sync kwam er een pagina bij: die wordt ook afgerond.
        d = self.add_issue(self.monitor, "h1_missing", "https://klant.nl/d", days=0)
        later = NOW + timedelta(hours=1)
        self.act(scan_adapter, "complete", self.card_key, now=later)

        for issue_id in (self.a_old, self.a_new, self.b, self.c_open, d):
            status, updated_at = self.issue_status(issue_id)
            self.assertEqual(status, "opgelost")
            self.assertEqual(updated_at.replace(tzinfo=timezone.utc), later)
        self.assertEqual(self.issue_status(self.other_type)[0], "open")
        self.assertEqual(self.issue_status(self.c_resolved)[1].replace(tzinfo=timezone.utc), _at(10))

        card = self.card(self.card_key)
        self.assertEqual(card.item_count, 4)
        self.assertEqual([item["key"] for item in card.items], ["klant.nl/a", "klant.nl/b", "klant.nl/c", "klant.nl/d"])
        self.assertEqual(sorted(card.items[2]["ref"]["completed_ids"]), [self.c_open])
        self.assertEqual(self.collect(scan_adapter, {self.customer})[0].group_key, "lang_missing")

    def test_reopen_restores_open_or_forwarded(self):
        self.act(scan_adapter, "complete", self.card_key)
        with self.Session() as db:  # tussendoor naar Monday gezet
            db.get(LaunchScanIssue, self.b).external_item_id = "m9"
            db.commit()

        self.act(scan_adapter, "reopen", self.card_key)

        self.assertEqual(self.issue_status(self.a_new)[0], "open")
        self.assertEqual(self.issue_status(self.c_open)[0], "open")
        self.assertEqual(self.issue_status(self.b)[0], "doorgezet")
        # Was al opgelost vóór Klaar: blijft opgelost.
        self.assertEqual(self.issue_status(self.c_resolved)[0], "opgelost")

    def test_reopen_without_completed_ids_uses_issue_ids(self):
        with self.Session() as db:
            for issue_id in (self.a_old, self.a_new):
                db.get(LaunchScanIssue, issue_id).status = "opgelost"
            db.commit()
        self.act(scan_adapter, "reopen", self.card_key)
        self.assertEqual(self.issue_status(self.a_new)[0], "open")
        self.assertEqual(self.issue_status(self.a_old)[0], "open")

    def test_dismiss_ignores_open_rows_of_items(self):
        e = self.add_issue(self.monitor, "h1_missing", "https://klant.nl/e", days=0)  # niet op de kaart
        self.act(scan_adapter, "dismiss", self.card_key)
        for issue_id in (self.a_old, self.a_new, self.b, self.c_open):
            self.assertEqual(self.issue_status(issue_id)[0], "genegeerd")
        self.assertEqual(self.issue_status(self.c_resolved)[0], "opgelost")
        self.assertEqual(self.issue_status(e)[0], "open")


# --- concurrentieanalyse ---------------------------------------------------------------


class AnalysisTests(_Base):
    def add_analysis(self, *, days=10, customer=None, status="completed"):
        analysis_id = str(uuid.uuid4())
        self.add(CompetitorAnalysis(id=analysis_id, customer_website_id=customer or self.customer, created_by=USER,
                                    status=status, country="nl", warnings=[], modules=[],
                                    created_at=_at(days), updated_at=_at(days)))
        return analysis_id

    def add_keyword(self, analysis_id, keyword, *, status="completed", ai_state="ok", days=10):
        keyword_id = str(uuid.uuid4())
        self.add(CompetitorAnalysisKeyword(
            id=keyword_id, analysis_id=analysis_id, keyword=keyword, keyword_key=" ".join(keyword.split()).casefold(),
            status=status, ai_state=ai_state, created_at=_at(days), updated_at=_at(days)))
        return keyword_id

    def add_action(self, analysis_id, keyword_id, title, *, impact="middel", done=False, order=0):
        action_id = str(uuid.uuid4())
        self.add(CompetitorAnalysisAction(
            id=action_id, keyword_id=keyword_id, analysis_id=analysis_id, sort_order=order, title=title,
            impact=impact, done=done, created_at=NOW, updated_at=NOW))
        return action_id

    def action(self, action_id):
        with self.Session() as db:
            row = db.get(CompetitorAnalysisAction, action_id)
            db.expunge(row)
            return row

    def test_newest_successful_keyword_row_wins(self):
        first = self.add_analysis(days=20)
        kw1 = self.add_keyword(first, "SEO bureau", days=20)
        self.add_action(first, kw1, "Oud punt")
        second = self.add_analysis(days=5)
        kw2 = self.add_keyword(second, "seo  bureau", days=5)
        a1 = self.add_action(second, kw2, "Titel aanpassen", impact="laag", order=1)
        a2 = self.add_action(second, kw2, "FAQ toevoegen", impact="hoog", order=0)
        self.add_action(second, kw2, "Al gedaan", done=True)
        # Nieuwer maar mislukt, lopend of zonder AI: verdringt niet.
        failed = self.add_analysis(days=2, status="failed")
        self.add_keyword(failed, "seo bureau", status="failed", ai_state=None, days=2)
        running = self.add_analysis(days=1, status="analyzing")
        self.add_keyword(running, "seo bureau", status="pending", ai_state=None, days=1)
        no_ai = self.add_analysis(days=0)
        self.add_keyword(no_ai, "seo bureau", ai_state="error", days=0)

        [group] = self.collect(analysis_adapter)

        self.assertEqual((group.source, group.group_key, group.kind), ("analysis", "seo bureau", "content"))
        self.assertEqual(group.title, "Verbeterpunten “seo  bureau”")
        self.assertEqual(group.severity, "hoog")
        self.assertEqual([item.key for item in group.items], [a2, a1])
        item = group.items[0]
        self.assertEqual((item.title, item.url, item.severity), ("FAQ toevoegen", None, "hoog"))
        self.assertEqual(item.ref, {"analysis_id": second, "keyword_id": kw2, "action_id": a2})

    def test_same_group_key_after_new_analysis(self):
        first = self.add_analysis(days=20)
        kw1 = self.add_keyword(first, "seo bureau", days=20)
        self.add_action(first, kw1, "Punt 1")
        self.sync(analysis_adapter)
        card = self.card_id(source="analysis")

        second = self.add_analysis(days=1)
        kw2 = self.add_keyword(second, "SEO Bureau", days=1)
        new = self.add_action(second, kw2, "Punt 2")
        result = self.sync(analysis_adapter)

        self.assertEqual((result.created, result.updated), (0, 1))
        self.assertEqual([item["key"] for item in self.card(card).items], [new])

    def test_complete_reopen_and_all_done(self):
        analysis = self.add_analysis()
        kw = self.add_keyword(analysis, "seo bureau")
        a1 = self.add_action(analysis, kw, "Punt 1")
        a2 = self.add_action(analysis, kw, "Punt 2", order=1)
        self.sync(analysis_adapter)
        card = self.card_id(source="analysis")
        a3 = self.add_action(analysis, kw, "Punt 3", order=2)  # na de sync bijgekomen

        self.act(analysis_adapter, "complete", card)

        for action_id in (a1, a2, a3):
            row = self.action(action_id)
            self.assertTrue(row.done)
            self.assertEqual(row.done_by, USER)
            self.assertEqual(row.done_at.replace(tzinfo=timezone.utc), NOW)
        snapshot = self.card(card)
        self.assertEqual((snapshot.item_count, [i["key"] for i in snapshot.items]), (3, [a1, a2, a3]))
        self.assertEqual(self.collect(analysis_adapter), [])

        self.act(analysis_adapter, "reopen", card)
        for action_id in (a1, a2, a3):
            row = self.action(action_id)
            self.assertEqual((row.done, row.done_by, row.done_at), (False, None, None))
        self.assertEqual(len(self.collect(analysis_adapter)[0].items), 3)

    def test_dismiss_writes_nothing(self):
        analysis = self.add_analysis()
        kw = self.add_keyword(analysis, "seo bureau")
        a1 = self.add_action(analysis, kw, "Punt 1")
        self.sync(analysis_adapter)
        self.act(analysis_adapter, "dismiss", self.card_id(source="analysis"))
        self.assertFalse(self.action(a1).done)

    def test_two_customers(self):
        mine = self.add_analysis()
        theirs = self.add_analysis(customer=self.other)
        self.add_action(mine, self.add_keyword(mine, "seo bureau"), "Punt")
        self.add_action(theirs, self.add_keyword(theirs, "seo bureau"), "Punt")
        groups = self.collect(analysis_adapter)
        self.assertEqual(sorted(g.customer_id for g in groups), sorted([self.customer, self.other]))
        self.assertEqual([g.customer_id for g in self.collect(analysis_adapter, {self.other})], [self.other])


# --- aanpassingen ------------------------------------------------------------------------


PAGE_A = "https://klant.nl/diensten/seo/"
PAGE_B = "https://klant.nl/over-ons/"


class SiteChangesTests(_Base):
    def setUp(self):
        super().setUp()
        self.content_scan = self.add_scan(3)
        self.page_a = self.add_page(PAGE_A, "/diensten/seo/")
        self.page_b = self.add_page(PAGE_B, "/over-ons/")

    def add_page(self, url, path, scan_id=None):
        page_id = str(uuid.uuid4())
        self.add(LaunchContentPage(id=page_id, scan_id=scan_id or self.content_scan, url=url, path=path,
                                   title=f"Titel {path}", created_at=_at(10)))
        return page_id

    def add_suggestion(self, page_id, item_key, current, proposed, *, status="open", title=None, scan_id=None,
                       customer=None):
        suggestion_id = str(uuid.uuid4())
        self.add(LaunchContentSuggestion(
            id=suggestion_id, scan_id=scan_id or self.content_scan, customer_website_id=customer or self.customer,
            content_page_id=page_id, item_key=item_key, agent="content", title=title, current_value=current,
            proposed_value=proposed, status=status, created_at=_at(10), updated_at=_at(10)))
        return suggestion_id

    def decide(self, entry, status):
        self.add(SiteChange(
            id=str(uuid.uuid4()), customer_website_id=self.customer, page_url=entry.page_url, url_key=entry.url_key,
            topic=entry.topic, source_kind=entry.kind, source_key=entry.key,
            source_ref=dict(entry.source.source_ref) if entry.source else {}, title=entry.field("title") or "t",
            status=status, edited=False, created_at=NOW, updated_at=NOW))

    def entries(self):
        with self.Session() as db:
            return suggestion_entries(db, self.customer)[1]

    def test_only_text_suggestions_per_page(self):
        self.add_suggestion(self.page_a, "c3_meta_title", "Oud", "Nieuw", title="Meta title herschrijven")
        self.add_suggestion(self.page_a, "c3_faq", "", "FAQ-blok")
        self.add_suggestion(self.page_b, "c3_meta_description", "Oud", "Nieuw")
        # Scan-actiepunt op dezelfde pagina: niet op deze kaart.
        phase1 = self.add_scan(1)
        self.add_issue(phase1, "title_too_long", PAGE_A)
        # Voorstel op siteniveau (geen pagina): telt niet.
        self.add_suggestion(None, "c3_blogs", "", "Blog over SEO")

        groups = _by_key(self.collect(site_changes_adapter))

        self.assertEqual(sorted(groups), sorted([(self.customer, url_key(PAGE_A)), (self.customer, url_key(PAGE_B))]))
        group = groups[(self.customer, url_key(PAGE_A))]
        self.assertEqual((group.source, group.kind, group.severity), ("site_changes", "content", "middel"))
        self.assertEqual(group.title, "Teksten aanpassen /diensten/seo/")
        self.assertEqual(len(group.items), 2)
        self.assertIn("Meta title herschrijven", [item.title for item in group.items])
        for item in group.items:
            self.assertEqual((item.url, item.severity, item.ref), (PAGE_A, None, {"page_url": PAGE_A}))
        self.assertEqual({item.key for item in group.items},
                         {e.key for e in self.entries() if e.url_key == url_key(PAGE_A)})

    def test_approved_counts_also_without_source_and_done_or_rejected_do_not(self):
        self.add_suggestion(self.page_a, "c3_meta_title", "Oud", "Nieuw")
        self.add_suggestion(self.page_a, "c3_meta_description", "Oud", "Nieuw")
        self.add_suggestion(self.page_b, "c3_meta_title", "Oud", "Nieuw")
        self.add_suggestion(self.page_b, "c3_faq", "", "FAQ")
        entries = {(e.url_key, e.source.type_key): e for e in self.entries()}
        self.decide(entries[(url_key(PAGE_A), "c3_meta_title")], "goedgekeurd")
        self.decide(entries[(url_key(PAGE_A), "c3_meta_description")], "doorgevoerd")
        self.decide(entries[(url_key(PAGE_B), "c3_meta_title")], "afgewezen")
        self.decide(entries[(url_key(PAGE_B), "c3_faq")], "doorgevoerd")
        # Goedgekeurde beslissing waarvan de bron weg is (oude scan): telt mee.
        gone = "https://klant.nl/weg/"
        self.add(SiteChange(
            id=str(uuid.uuid4()), customer_website_id=self.customer, page_url=gone, url_key=url_key(gone),
            topic="meta_title", source_kind="content_suggestion", source_key="oude-sleutel", source_ref={},
            title="Oud voorstel", status="goedgekeurd", edited=False, created_at=NOW, updated_at=NOW))

        groups = _by_key(self.collect(site_changes_adapter))

        self.assertEqual(sorted(groups), sorted([(self.customer, url_key(PAGE_A)), (self.customer, url_key(gone))]))
        self.assertEqual(len(groups[(self.customer, url_key(PAGE_A))].items), 1)
        self.assertEqual(groups[(self.customer, url_key(gone))].title, "Teksten aanpassen /weg/")
        self.assertEqual(groups[(self.customer, url_key(gone))].items[0].title, "Oud voorstel")

    def test_customer_without_phase_3_or_decisions_is_skipped(self):
        other_scan = self.add_scan(3, customer=self.other)
        page = self.add_page("https://ander.nl/", "/", scan_id=other_scan)
        self.add_suggestion(page, "c3_meta_title", "Oud", "Nieuw", scan_id=other_scan, status="overgenomen",
                            customer=self.other)
        self.add_suggestion(self.page_a, "c3_meta_title", "Oud", "Nieuw")
        groups = self.collect(site_changes_adapter)
        self.assertEqual({g.customer_id for g in groups}, {self.customer})
        self.assertEqual(self.collect(site_changes_adapter, {self.other}), [])

    def test_complete_refuses_with_open_items_and_reopen_always(self):
        self.add_suggestion(self.page_a, "c3_meta_title", "Oud", "Nieuw")
        self.add_suggestion(self.page_a, "c3_faq", "", "FAQ")
        self.sync(site_changes_adapter)
        card = self.card_id(source="site_changes")

        with self.assertRaises(WorkQueueConflict) as caught:
            self.act(site_changes_adapter, "complete", card)
        self.assertEqual(str(caught.exception),
                         "Op deze pagina staan nog 2 voorstellen open in Aanpassingen. Rond ze daar af; "
                         "de kaart gaat dan vanzelf naar Klaar.")
        with self.assertRaises(WorkQueueConflict) as caught:
            self.act(site_changes_adapter, "reopen", card)
        self.assertIn("Heropenen gebeurt in Aanpassingen", str(caught.exception))

        for entry in self.entries():
            self.decide(entry, "doorgevoerd")
        self.act(site_changes_adapter, "complete", card)  # niets open: geen fout
        self.act(site_changes_adapter, "dismiss", card)  # schrijft niets terug


# --- samenspel met de kern ---------------------------------------------------------------


class SyncIntegrationTests(_Base):
    def test_scan_card_created_then_resolved_by_source(self):
        phase1 = self.add_scan(1)
        a = self.add_issue(phase1, "h1_missing", "https://klant.nl/a", severity="hoog")
        self.add_issue(phase1, "lang_missing", None)

        result = self.sync(scan_adapter)
        self.assertEqual(result.created, 2)
        card = self.card(self.card_id(group_key="h1_missing"))
        self.assertEqual((card.status, card.source, card.kind, card.severity, card.item_count),
                         ("todo", "scan", "content", "hoog", 1))
        self.assertEqual(card.items[0]["ref"]["issue_ids"], [a])

        with self.Session() as db:  # opgelost in de bron (bijv. in de Actiepunten-tab)
            db.get(LaunchScanIssue, a).status = "opgelost"
            db.commit()
        result = self.sync(scan_adapter, now=NOW + timedelta(hours=1))

        self.assertEqual(result.resolved, 1)
        card = self.card(card.id)
        self.assertEqual(card.status, "done")
        self.assertTrue(card.resolved_by_source)

    def test_dismissed_site_wide_scan_card_stays_away(self):
        phase1 = self.add_scan(1)
        self.add_issue(phase1, "lang_missing", None)
        self.sync(scan_adapter)
        card = self.card_id(group_key="lang_missing")
        with self.Session() as db:
            row = db.get(WorkItem, card)
            scan_adapter.dismiss(db, row, USER, NOW)
            mark_removed(row, NOW)
            db.commit()
        # Ook als het actiepunt (bijv. na een nieuwe scan) weer open zou staan, komt de kaart niet terug.
        with self.Session() as db:
            db.query(LaunchScanIssue).update({"status": "open"})
            db.commit()
        result = self.sync(scan_adapter)
        self.assertEqual(result.created, 0)

    def test_site_changes_card_resolves_when_all_done(self):
        scan = self.add_scan(3)
        page = str(uuid.uuid4())
        self.add(LaunchContentPage(id=page, scan_id=scan, url=PAGE_A, path="/diensten/seo/", created_at=_at(10)))
        suggestion = str(uuid.uuid4())
        self.add(LaunchContentSuggestion(
            id=suggestion, scan_id=scan, customer_website_id=self.customer, content_page_id=page,
            item_key="c3_meta_title", agent="content", current_value="Oud", proposed_value="Nieuw", status="open",
            created_at=_at(10), updated_at=_at(10)))
        self.assertEqual(self.sync(site_changes_adapter).created, 1)

        with self.Session() as db:
            db.get(LaunchContentSuggestion, suggestion).status = "overgenomen"
            db.commit()
        self.assertEqual(self.sync(site_changes_adapter).resolved, 1)


if __name__ == "__main__":
    unittest.main()
