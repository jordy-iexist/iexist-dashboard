"""Cijfers en werk voor het maandrapport (features/monthly_report/services/collect.py).

In-memory SQLite. Search Console (`client.search_analytics`, `sites.cached_sites`) en
ProRankTracker (`rankings.organic_rows`, `prt_enrich.collect`) zijn vervangen: geen netwerk.
"""
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.models import (
    Base,
    Blog,
    CompetitorAnalysis,
    CompetitorAnalysisKeyword,
    ContentBrief,
    CustomerQuickWins,
    CustomerWebsite,
    MonthlyReport,
    SiteChange,
)
from app.features.customers import rankings
from app.features.launch_checklist.services import prt_enrich
from app.features.monthly_report.schemas import Manual, Metric, ReportData
from app.features.monthly_report.services import collect as c
from app.services.search_console import client as gsc
from app.services.search_console import sites as gsc_sites
from app.services.search_console.client import SearchConsoleServiceError

USER = "user-1"
MONTH = "2026-11"
TODAY = date(2026, 11, 25)
UTC = timezone.utc


def _now():
    return datetime.now(UTC)


def gsc_row(clicks, impressions=1000):
    return [{"keys": [], "clicks": float(clicks), "impressions": float(impressions), "ctr": 0.01, "position": 8.0}]


def prt_row(name, rank, monthago=None):
    row = {"name": name, "rank": rank, "term_type": "organic", "is_ai_term": 0}
    if monthago is not None:
        row["monthagorank"] = monthago
    return row


def snapshot(mentions):
    prompts = [{"prompt_id": i, "prompt": f"p{i}", "mentions": m} for i, m in enumerate(mentions)]
    return {"state": "ok", "message": None, "fetched_at": "2026-11-25T08:00:00+00:00",
            "totals": {"prompts": len(prompts)}, "prompts": prompts}


class _Base(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)
        self.customer = CustomerWebsite(id=str(uuid.uuid4()), name="Klant", base_url="https://www.klant.nl/",
                                        domain="klant.nl", created_by=USER, created_at=_now(), updated_at=_now())
        self.db.add(self.customer)
        self.db.commit()

        self._patch(settings, "gsc_data_lag_days", 3)
        self.gsc_configured = self._patch(gsc, "is_configured", Mock(return_value=True))
        self.sites = self._patch(gsc_sites, "cached_sites", Mock(return_value=[
            {"site_url": "sc-domain:klant.nl", "permission": "siteOwner"}]))
        self.analytics = self._patch(gsc, "search_analytics", Mock(side_effect=[gsc_row(1240, 48210), gsc_row(1105)]))
        self.organic = self._patch(rankings, "organic_rows", Mock(return_value=("ok", [prt_row("seo", 3, 5)], None)))
        self.prt = self._patch(prt_enrich, "collect", Mock(return_value=snapshot([1, 0])))

    def _patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def run_collect(self, **kwargs):
        kwargs.setdefault("today", TODAY)
        return c.collect(self.db, self.customer, kwargs.pop("month", MONTH), **kwargs)


class ClicksTest(_Base):
    def clicks(self, today=TODAY):
        metric, period, previous = c.clicks_metric(self.customer, MONTH, today)
        return metric, period, previous

    def test_ok_with_same_days_of_previous_month(self):
        metric, period, previous = self.clicks()
        self.assertEqual((metric.state, metric.value, metric.previous, metric.delta, metric.delta_pct),
                         ("ok", 1240, 1105, 135, 12.2))
        self.assertEqual((metric.impressions, metric.property, metric.property_source),
                         (48210, "sc-domain:klant.nl", "auto"))
        self.assertEqual((period.start, period.end, period.days, period.complete),
                         ("2026-11-01", "2026-11-22", 22, False))
        self.assertEqual((previous.start, previous.end, previous.days), ("2026-10-01", "2026-10-22", 22))
        calls = self.analytics.call_args_list
        self.assertEqual(calls[0].args, ("sc-domain:klant.nl", date(2026, 11, 1), date(2026, 11, 22)))
        self.assertEqual(calls[1].args, ("sc-domain:klant.nl", date(2026, 10, 1), date(2026, 10, 22)))
        self.assertEqual(calls[0].kwargs, {})

    def test_previous_zero_has_no_percentage(self):
        self.analytics.side_effect = [gsc_row(10), gsc_row(0)]
        metric, _, _ = self.clicks()
        self.assertEqual((metric.value, metric.previous, metric.delta, metric.delta_pct), (10, 0, 10, None))

    def test_previous_without_rows_is_unknown(self):
        # Property die pas deze maand data heeft: geen rijen over de vorige periode is geen 0.
        self.analytics.side_effect = [gsc_row(35), []]
        metric, _, _ = self.clicks()
        self.assertEqual((metric.state, metric.value, metric.previous, metric.delta, metric.delta_pct),
                         ("ok", 35, None, None, None))

    def test_previous_failure_keeps_ok(self):
        self.analytics.side_effect = [gsc_row(10), SearchConsoleServiceError("x", code="rate_limited")]
        metric, _, _ = self.clicks()
        self.assertEqual((metric.state, metric.value, metric.previous, metric.delta), ("ok", 10, None, None))

    def test_no_data_in_first_days(self):
        for day in (1, 2, 3):
            metric, period, previous = c.clicks_metric(self.customer, "2026-12", date(2026, 12, day))
            self.assertEqual((metric.state, period, previous), ("no_data", None, None))
        self.analytics.assert_not_called()

    def test_not_configured(self):
        self.gsc_configured.return_value = False
        metric, period, _ = self.clicks()
        self.assertEqual(metric.state, "not_configured")
        self.assertIsNotNone(metric.message)
        self.assertIsNotNone(period)

    def test_token_expired(self):
        self.sites.side_effect = SearchConsoleServiceError("verlopen", code="token_expired")
        self.assertEqual(self.clicks()[0].state, "token_expired")

    def test_no_property(self):
        self.sites.return_value = [{"site_url": "sc-domain:ander.nl", "permission": "siteOwner"}]
        self.assertEqual(self.clicks()[0].state, "no_property")

    def test_manual_property_inaccessible(self):
        self.customer.gsc_property = "https://www.klant.nl/"
        self.analytics.side_effect = SearchConsoleServiceError("geen toegang", code="forbidden")
        metric = self.clicks()[0]
        self.assertEqual((metric.state, metric.property, metric.property_source),
                         ("property_inaccessible", "https://www.klant.nl/", "manual"))
        self.sites.assert_called_with(refresh=True)

    def test_auto_property_retried_with_fresh_list(self):
        self.sites.side_effect = [
            [{"site_url": "sc-domain:klant.nl", "permission": "siteOwner"}],
            [{"site_url": "https://www.klant.nl/", "permission": "siteOwner"}],
        ]
        self.analytics.side_effect = [SearchConsoleServiceError("weg", code="not_found"), gsc_row(5), gsc_row(4)]
        metric = self.clicks()[0]
        self.assertEqual((metric.state, metric.value, metric.property), ("ok", 5, "https://www.klant.nl/"))

    def test_other_error(self):
        self.analytics.side_effect = SearchConsoleServiceError("Search Console-fout: kapot", code="gsc_error")
        metric = self.clicks()[0]
        self.assertEqual((metric.state, metric.message), ("error", "Search Console-fout: kapot"))

    def test_unexpected_exception_never_raises(self):
        self.analytics.side_effect = RuntimeError("boem")
        with self.assertLogs(c.logger, "ERROR"):
            metric = self.clicks()[0]
        self.assertEqual(metric.state, "error")


class Top10Test(_Base):
    def test_deduplicated_per_keyword_with_best_position(self):
        self.organic.return_value = ("ok", [
            prt_row("SEO Bureau", 12, 9),
            prt_row("seo  bureau", 4, 15),
            prt_row("webshop", "NTH", 8),
            prt_row("contact", 10, "NTH"),
            prt_row("", 1, 1),
        ], None)
        metric = c.top10_metric("https://klant.nl/")
        # seo bureau (4), webshop (–), contact (10)
        self.assertEqual((metric.state, metric.value, metric.total), ("ok", 2, 3))
        # Een maand geleden: seo bureau (9), webshop (8), contact (–)
        self.assertEqual((metric.previous, metric.delta), (2, 0))
        self.assertIsNotNone(metric.captured_at)

    def test_without_monthago_field_no_previous(self):
        self.organic.return_value = ("ok", [prt_row("a", 3), prt_row("b", 30)], None)
        metric = c.top10_metric("https://klant.nl/")
        self.assertEqual((metric.value, metric.total, metric.previous, metric.delta), (1, 2, None, None))

    def test_states(self):
        for state, expected in (("not_configured", "not_configured"), ("not_tracked", "not_tracked"),
                                ("error", "error")):
            self.organic.return_value = (state, [], "melding" if state == "error" else None)
            metric = c.top10_metric("https://klant.nl/")
            self.assertEqual(metric.state, expected)
            self.assertIsNotNone(metric.message)
            self.assertIsNone(metric.value)


class AiTest(_Base):
    def test_prompts_with_mentions_and_previous_report(self):
        self.prt.return_value = snapshot([2, 0, 1, 0])
        previous = ReportData.model_validate(_data(ai={"state": "ok", "value": 1, "total": 4}))
        metric = c.ai_metric("https://klant.nl/", previous_month_data=previous)
        self.assertEqual((metric.state, metric.value, metric.total, metric.previous, metric.delta),
                         ("ok", 2, 4, 1, 1))
        self.assertEqual(metric.captured_at, datetime(2026, 11, 25, 8, 0, tzinfo=UTC))

    def test_previous_report_not_ok_gives_no_difference(self):
        previous = ReportData.model_validate(_data(ai={"state": "out_of_window"}))
        metric = c.ai_metric("https://klant.nl/", previous_month_data=previous)
        self.assertEqual((metric.value, metric.previous, metric.delta), (1, None, None))
        self.assertIsNone(c.ai_metric("https://klant.nl/").previous)

    def test_states(self):
        for state in ("not_configured", "not_tracked", "error"):
            self.prt.return_value = prt_enrich.empty_snapshot(state, "kapot" if state == "error" else None)
            metric = c.ai_metric("https://klant.nl/")
            self.assertEqual((metric.state, metric.value), (state, None))
            self.assertIsNotNone(metric.message)


def _data(top10=None, ai=None, leads=None):
    return {
        "month": "2026-10", "collected_at": "2026-10-31T10:00:00+00:00",
        "metrics": {
            "clicks": {"state": "ok", "value": 1},
            "top10": top10 or {"state": "out_of_window"},
            "leads": leads or {"state": "not_connected"},
            "ai_mentions": ai or {"state": "out_of_window"},
        },
    }


class CollectTest(_Base):
    def test_full_snapshot(self):
        data = self.run_collect()
        self.assertIsInstance(data, ReportData)
        self.assertEqual(data.month, MONTH)
        self.assertEqual(data.metrics.clicks.value, 1240)
        self.assertEqual((data.metrics.top10.state, data.metrics.top10.value), ("ok", 1))
        self.assertEqual((data.metrics.ai_mentions.state, data.metrics.ai_mentions.value), ("ok", 1))
        self.assertEqual(data.metrics.leads.state, "not_connected")
        self.assertEqual(data.period.end, "2026-11-22")
        ReportData.model_validate(data.model_dump(mode="json"))

    def test_prt_client_has_timeout_and_is_closed(self):
        self.run_collect()
        client = self.organic.call_args.kwargs["client"]
        self.assertIsInstance(client, httpx.Client)
        self.assertEqual(client.timeout.read, 15)
        self.assertIs(self.prt.call_args.kwargs["client"], client)
        self.assertTrue(client.is_closed)

    def test_out_of_window(self):
        data = self.run_collect(today=date(2026, 12, 8))
        self.assertEqual((data.metrics.top10.state, data.metrics.ai_mentions.state), ("out_of_window", "out_of_window"))
        self.organic.assert_not_called()
        self.prt.assert_not_called()
        # Binnen 7 dagen na de maand wel.
        self.analytics.side_effect = None
        self.analytics.return_value = gsc_row(1)
        data = self.run_collect(today=date(2026, 12, 7))
        self.assertEqual(data.metrics.top10.state, "ok")

    def test_old_ok_value_is_kept(self):
        captured = "2026-11-28T09:00:00+00:00"
        old = _data(top10={"state": "ok", "value": 7, "total": 20, "captured_at": captured},
                    ai={"state": "ok", "value": 3, "total": 10, "captured_at": captured})
        old["month"] = MONTH
        data = self.run_collect(today=date(2026, 12, 20), previous_data=old)
        self.assertEqual((data.metrics.top10.state, data.metrics.top10.value), ("ok", 7))
        self.assertEqual(data.metrics.top10.captured_at, datetime(2026, 11, 28, 9, 0, tzinfo=UTC))
        self.assertEqual((data.metrics.ai_mentions.state, data.metrics.ai_mentions.value), ("ok", 3))

        # Binnen het venster maar met een fout: ook dan blijft het oude cijfer staan.
        self.analytics.side_effect = None
        self.analytics.return_value = gsc_row(1)
        self.organic.return_value = ("error", [], "kapot")
        self.prt.return_value = prt_enrich.empty_snapshot("error", "kapot")
        data = self.run_collect(previous_data=ReportData.model_validate(old))
        self.assertEqual((data.metrics.top10.value, data.metrics.ai_mentions.value), (7, 3))

    def test_new_ok_value_replaces_old_one(self):
        old = _data(top10={"state": "ok", "value": 7, "total": 20})
        data = self.run_collect(previous_data=old)
        self.assertEqual(data.metrics.top10.value, 1)

    def test_unexpected_prt_failure_never_raises(self):
        self.organic.side_effect = RuntimeError("boem")
        self.prt.side_effect = ValueError("boem")
        with self.assertLogs(c.logger, "ERROR"):
            data = self.run_collect()
        self.assertEqual((data.metrics.top10.state, data.metrics.ai_mentions.state), ("error", "error"))

    def test_leads(self):
        previous_row = MonthlyReport(id="vorige", customer_website_id=self.customer.id, month="2026-10",
                                     status="completed", manual={"leads": 10}, created_by=USER)
        data = self.run_collect(manual=Manual(leads=14), previous_month_row=previous_row)
        leads = data.metrics.leads
        self.assertEqual((leads.state, leads.value, leads.previous, leads.delta, leads.previous_source),
                         ("manual", 14, 10, 4, "previous_report"))

        self.analytics.side_effect = None
        self.analytics.return_value = gsc_row(1)
        data = self.run_collect(manual={"leads": 14, "leads_previous": 12}, previous_month_row=previous_row)
        self.assertEqual((data.metrics.leads.previous, data.metrics.leads.previous_source), (12, "manual"))

        data = self.run_collect(manual=None, previous_month_row=previous_row)
        self.assertEqual((data.metrics.leads.state, data.metrics.leads.value), ("not_connected", None))
        self.assertIsNotNone(data.metrics.leads.message)

    def test_leads_metric_states(self):
        self.assertEqual(c.leads_metric(Manual(leads=0), None).state, "manual")
        self.assertEqual(c.leads_metric(Manual(leads_previous=3), None).state, "not_connected")


class WorkTest(_Base):
    def setUp(self):
        super().setUp()
        self.analysis_id = str(uuid.uuid4())
        self.db.add(CompetitorAnalysis(id=self.analysis_id, customer_website_id=self.customer.id, created_by=USER,
                                       status="completed", country="nl", top_n=10, modules=["serp"],
                                       created_at=_now(), updated_at=_now()))
        self.db.commit()

    def change(self, topic, status, *, url="https://klant.nl/a/", done_at=None, verified=None, title="Titel"):
        self.db.add(SiteChange(
            id=str(uuid.uuid4()), customer_website_id=self.customer.id, page_url=url,
            url_key=url.split("://")[1].rstrip("/"), topic=topic, source_kind="scan_issue",
            source_key=str(uuid.uuid4()), title=title, status=status, verified=verified, done_at=done_at,
            reviewed_at=_now(), created_at=_now(), updated_at=_now(),
        ))
        self.db.commit()

    def blog(self, content, published_at, url=None, customer_id=None):
        self.db.add(Blog(id=str(uuid.uuid4()), job_id=str(uuid.uuid4()), content=content,
                         customer_website_id=customer_id or self.customer.id, published_at=published_at,
                         placement_url=url, created_at=_now()))
        self.db.commit()

    def brief(self, keyword, completed_at, *, target_url=None, status="completed"):
        keyword_id = str(uuid.uuid4())
        self.db.add(CompetitorAnalysisKeyword(id=keyword_id, analysis_id=self.analysis_id, keyword=keyword,
                                              keyword_key=keyword, target_url=target_url, status="completed",
                                              created_at=_now(), updated_at=_now()))
        self.db.add(ContentBrief(id=str(uuid.uuid4()), keyword_id=keyword_id, analysis_id=self.analysis_id,
                                 customer_website_id=self.customer.id, status=status, created_by=USER,
                                 created_at=_now(), updated_at=_now(), completed_at=completed_at))
        self.db.commit()

    def test_work_done_in_month_with_continuous_ids(self):
        nov = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
        # 1 november 00:30 in Amsterdam (UTC 31 oktober) telt mee; 30 november 23:30 lokaal niet.
        self.change("meta_description", "doorgevoerd", url="https://klant.nl/a/", verified=True,
                    done_at=datetime(2026, 10, 31, 23, 30, tzinfo=UTC), title="Meta a")
        self.change("meta_description", "doorgevoerd", url="https://klant.nl/a/", done_at=nov, title="Meta a2")
        self.change("meta_description", "doorgevoerd", url="https://klant.nl/b/", verified=False, done_at=nov)
        self.change("headings", "doorgevoerd", url="https://klant.nl/", done_at=nov, title="H1")
        self.change("headings", "doorgevoerd", done_at=datetime(2026, 11, 30, 23, 30, tzinfo=UTC))
        self.change("headings", "doorgevoerd", done_at=datetime(2026, 10, 31, 22, 30, tzinfo=UTC))
        self.change("headings", "goedgekeurd")
        for i in range(6):
            self.change("image_alt", "doorgevoerd", url=f"https://klant.nl/p{i}/", done_at=nov, title=f"Alt {i}")
        self.blog("# Mijn blog\n\nTekst", nov, url="https://klant.nl/blog/mijn-blog/")
        self.blog("Geen kop hier\n\nTekst", nov + timedelta(days=1))
        self.blog("# Oud", datetime(2026, 10, 2, tzinfo=UTC))
        self.blog("# Ander", nov, customer_id=str(uuid.uuid4()))
        self.brief("seo bureau", nov, target_url="https://klant.nl/seo/")
        self.brief("oud", datetime(2026, 10, 5, tzinfo=UTC))
        self.brief("bezig", nov, status="brief")

        work = c.work_done(self.db, self.customer.id, MONTH)
        groups = [(g.id, g.topic, g.label, g.count, g.pages, g.verified) for g in work.changes]
        self.assertEqual(groups, [
            ("W1", "meta_description", "Meta description", 3, 2, 1),
            ("W2", "headings", "Koppen", 1, 1, 0),
            ("W3", "image_alt", "Alt-teksten", 6, 6, 0),
        ])
        self.assertEqual([(e.title, e.path) for e in work.changes[1].examples], [("H1", "/")])
        self.assertEqual(len(work.changes[2].examples), 5)
        self.assertEqual(work.changes[0].examples[0].path, "/a/")
        self.assertEqual([(b.id, b.title, b.published_at, b.url) for b in work.blogs], [
            ("W4", "Mijn blog", "2026-11-10", "https://klant.nl/blog/mijn-blog/"),
            ("W5", "Geen kop hier", "2026-11-11", None),
        ])
        self.assertEqual([(b.id, b.keyword, b.new_page) for b in work.briefs], [("W6", "seo bureau", False)])

    def test_upcoming(self):
        self.change("meta_title", "goedgekeurd", url="https://klant.nl/a/")
        self.change("meta_title", "goedgekeurd", url="https://klant.nl/b/")
        self.change("faq", "goedgekeurd")
        self.change("faq", "afgewezen")
        self.brief("nieuwe pagina", datetime(2026, 10, 3, tzinfo=UTC))
        self.brief("met pagina", datetime(2026, 11, 3, tzinfo=UTC), target_url="https://klant.nl/x/")
        self.brief("te oud", datetime(2026, 9, 3, tzinfo=UTC))
        for i in range(6):
            self.brief(f"nieuw {i}", datetime(2026, 11, 4 + i, tzinfo=UTC), target_url="")
        rows = [{"keyword": f"kw {i}", "position": 5 + i, "volume": 100 * i, "kans": "hoog"} for i in range(6)]
        rows.insert(1, {"keyword": "middel", "position": 4, "volume": 900, "kans": "middel"})
        self.db.add(CustomerQuickWins(customer_website_id=self.customer.id, target="klant.nl", country="nl",
                                      rows=rows, fetched_at=_now() - timedelta(days=10), created_at=_now(),
                                      updated_at=_now()))
        self.db.commit()

        upcoming = c.upcoming(self.db, self.customer.id, MONTH)
        self.assertEqual([(g.id, g.topic, g.count, g.pages, g.verified) for g in upcoming.approved_changes],
                         [("N1", "meta_title", 2, 2, None), ("N2", "faq", 1, 1, None)])
        self.assertEqual([(b.id, b.keyword, b.new_page) for b in upcoming.briefs],
                         [("N3", "nieuw 5", True), ("N4", "nieuw 4", True), ("N5", "nieuw 3", True),
                          ("N6", "nieuw 2", True), ("N7", "nieuw 1", True)])
        self.assertEqual([(q.id, q.keyword, q.position, q.volume) for q in upcoming.quick_wins],
                         [("N8", "kw 0", 5, 0), ("N9", "kw 1", 6, 100), ("N10", "kw 2", 7, 200),
                          ("N11", "kw 3", 8, 300), ("N12", "kw 4", 9, 400)])

    def test_stale_quick_wins_are_skipped(self):
        self.db.add(CustomerQuickWins(customer_website_id=self.customer.id, target="klant.nl", country="nl",
                                      rows=[{"keyword": "kw", "position": 5, "volume": 10, "kans": "hoog"}],
                                      fetched_at=_now() - timedelta(days=46), created_at=_now(), updated_at=_now()))
        self.db.commit()
        self.assertEqual(c.upcoming(self.db, self.customer.id, MONTH).quick_wins, [])

    def test_empty(self):
        self.assertEqual(c.work_done(self.db, self.customer.id, MONTH).model_dump(),
                         {"changes": [], "blogs": [], "briefs": []})
        self.assertEqual(c.upcoming(self.db, self.customer.id, MONTH).model_dump(),
                         {"approved_changes": [], "briefs": [], "quick_wins": []})


if __name__ == "__main__":
    unittest.main()
